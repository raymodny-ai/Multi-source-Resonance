"""
多源共振监控系统 - 事件驱动信号管线

Push 架构的信号评估核心。订阅 EventBus 各维度 topic，
在数据到达时即时计算信号分值，四维度就绪时触发共振评分和告警。

与旧 Pull 架构的对比:
    旧: APScheduler cron → 每15分钟拉取 → task_evaluate_resonance()
    新: EventBus push → 数据到达即刻 → _on_*_update() → evaluate_resonance()

特性:
- 维度就绪追踪 (crypto/gex/vix/darkpool)
- 防抖机制 (同一维度数据冲刷时避免高频打分)
- 异步回调安全
- 降级链路保留 (Hyperliquid WS 失联 → CCData REST 拉取)
"""

import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor

import pytz

from utils.logger import getLogger
from data_stream.event_bus import EventBus, Topics
from data_stream.pipeline_monitor import PipelineMonitor
from database.db_manager import DatabaseManager
from quant_logic import CryptoLeverageCleaner, VIXAnalyzer, DarkPoolVerifier
from signal_engine import ResonanceScorer, SignalStateMachine
from notification.alert_sender import AlertSender
from config.settings import Config

logger = getLogger('signal_pipeline')


class SignalPipeline:
    """事件驱动的信号评估管线

    订阅 EventBus 各维度 topic，在数据到达时即时计算信号分值。
    四维度全部就绪时自动触发共振评分和告警推送。

    使用示例:
        bus = get_event_bus()
        pipeline = SignalPipeline(bus)
        await pipeline.start()
    """

    # 共振评估最小间隔 (秒), 防止高频重复评分
    EVAL_COOLDOWN_SECONDS = 30

    def __init__(self, event_bus: EventBus):
        """初始化信号管线

        Args:
            event_bus: 全局事件总线实例
        """
        self._bus = event_bus
        self._db = DatabaseManager()
        self._config = Config()

        # 业务组件
        self._crypto_cleaner = CryptoLeverageCleaner()
        self._vix_analyzer = VIXAnalyzer()
        self._darkpool_verifier = DarkPoolVerifier()
        self._resonance_scorer = ResonanceScorer()
        self._signal_machine = SignalStateMachine(
            cooldown_minutes=Config.Thresholds.SIGNAL_COOLDOWN_MINUTES
        )
        self._alert_sender = AlertSender()

        # 线程池 (DB 写入和 CPU 密集型计算)
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._db_executor = ThreadPoolExecutor(max_workers=2)

        # 维度数据缓存
        self._crypto_cache: Dict[str, Any] = {}
        self._gex_cache: Dict[str, Any] = {}
        self._vix_cache: Dict[str, Any] = {}
        self._darkpool_cache: Dict[str, Any] = {}
        self._darkpool_preprocessed: Dict[str, Any] = {}  # v2.1 暗盘预处理结果

        # 维度就绪状态 (收到新数据后)
        self._crypto_ready = False
        self._gex_ready = False
        self._vix_ready = False
        self._darkpool_ready = False

        # 上次共振评估时间 (防抖)
        self._last_eval_time: Optional[datetime] = None

        # 降级标记: Hyperliquid WS 断开时, 尝试 CCData REST
        self._hyperliquid_connected = False
        self._ccdata_fallback_active = False

        logger.info("SignalPipeline 初始化完成")

    async def start(self) -> None:
        """启动信号管线: 订阅 EventBus 各维度 topic"""
        await self._bus.subscribe(Topics.CRYPTO_FUNDING_RATE, self._on_funding_rate)
        await self._bus.subscribe(Topics.CRYPTO_OPEN_INTEREST, self._on_open_interest)
        await self._bus.subscribe(Topics.GEX_UPDATE, self._on_gex_update)
        await self._bus.subscribe(Topics.VIX_TERM_STRUCTURE, self._on_vix_update)
        await self._bus.subscribe(Topics.DARKPOOL_AXLFI, self._on_darkpool_update)
        await self._bus.subscribe(Topics.SHORT_VOLUME_SPY, self._on_short_volume)
        await self._bus.subscribe(Topics.DBMF_RECOVERY, self._on_dbmf_recovery)
        await self._bus.subscribe(Topics.DATA_SOURCE_ERROR, self._on_source_error)
        await self._bus.subscribe(Topics.DARKPOOL_PREPROCESSED, self._on_darkpool_preprocessed)  # v2.1

        logger.info(
            "SignalPipeline 已订阅 %d 个topic",
            len(self._bus.get_topic_stats()),
        )

    async def shutdown(self) -> None:
        """关闭信号管线"""
        self._executor.shutdown(wait=False)
        self._db_executor.shutdown(wait=False)
        logger.info("SignalPipeline 已关闭")

    # ================================================================
    # Event Handlers: Crypto 维度
    # ================================================================

    async def _on_funding_rate(self, data: Dict[str, Any]) -> None:
        """Hyperliquid WS 推送资金费率"""
        self._hyperliquid_connected = True
        self._crypto_cache['funding_rate'] = data.get('rate', 0.0)
        self._crypto_cache['funding_timestamp'] = data.get('timestamp', datetime.now())
        await self._try_mark_crypto_ready()

    async def _on_open_interest(self, data: Dict[str, Any]) -> None:
        """Hyperliquid WS 推送持仓量"""
        self._hyperliquid_connected = True
        self._crypto_cache['oi'] = data.get('oi', 0.0)
        self._crypto_cache['oi_base'] = data.get('oi_base', 0.0)
        self._crypto_cache['mark_price'] = data.get('mark_price', 0.0)
        self._crypto_cache['oi_timestamp'] = data.get('timestamp', datetime.now())
        await self._try_mark_crypto_ready()

    async def _try_mark_crypto_ready(self) -> None:
        """检查 crypto 维度是否两路数据都到达"""
        if 'funding_rate' in self._crypto_cache and 'oi' in self._crypto_cache:
            self._crypto_ready = True
            logger.debug("Crypto 维度数据就绪 (funding + OI)")
            await self._evaluate_crypto_dimension()
            await self._check_all_dimensions_ready()

    async def _evaluate_crypto_dimension(self) -> None:
        """评估 Crypto 维度: 分析资金费率和OI, 写入DB"""
        try:
            loop = asyncio.get_event_loop()
            with PipelineMonitor.layer('layer1_filter', 'BTC', 2) as mon_crypto:
                funding_rate = self._crypto_cache['funding_rate']
                current_oi = self._crypto_cache['oi']

                # 获取历史OI (DB查询用 db_executor)
                crypto_history = await loop.run_in_executor(
                    self._db_executor,
                    self._db.get_crypto_history,
                    1,
                )

                # CPU计算用 executor
                historical_oi_list = (
                    crypto_history['btc_oi'].tolist()
                    if crypto_history is not None and len(crypto_history) > 0
                    else []
                )

                oi_change = await loop.run_in_executor(
                    self._executor,
                    lambda: self._crypto_cleaner.detect_oi_crash(
                        current_oi, historical_oi_list,
                    ),
                )

                funding_anomaly = await loop.run_in_executor(
                    self._executor,
                    self._crypto_cleaner.check_funding_rate_anomaly,
                    funding_rate,
                )

                # 存入DB
                timestamp = datetime.now(pytz.timezone('US/Eastern'))
                await loop.run_in_executor(
                    self._db_executor,
                    self._db.insert_crypto_derivatives,
                    timestamp,
                    funding_rate,
                    current_oi,
                    oi_change['drop_percentage'],
                    False,  # liquidation_spike
                    None,   # cryptoquant_elr
                    funding_anomaly,
                    oi_change['crash_detected'],
                    False,  # leverage_cleanup
                )
                mon_crypto.set_output(2)

            logger.info(
                f"Crypto维度评分: funding={funding_rate*100:.4f}%, "
                f"OI=${current_oi:,.0f}, anomaly={funding_anomaly}"
            )

        except Exception as e:
            logger.error(f"Crypto维度评估失败: {e}", exc_info=True)

    # ================================================================
    # Event Handlers: GEX 维度
    # ================================================================

    async def _on_gex_update(self, data: Dict[str, Any]) -> None:
        """RESTPollScheduler 推送 GEX/DIX 更新"""
        self._gex_cache.update(data)
        self._gex_ready = True
        logger.debug(
            "GEX 维度数据就绪: GEX=%.1fB, DIX=%.1f%%",
            data.get('gex', 0) / 1e9,
            data.get('dix', 0),
        )
        await self._evaluate_gex_dimension()
        await self._check_all_dimensions_ready()

    async def _evaluate_gex_dimension(self) -> None:
        """评估 GEX 维度: 写入DB"""
        try:
            loop = asyncio.get_event_loop()
            with PipelineMonitor.layer('layer2_gex', 'SPY', 1) as mon:
                gex_total = self._gex_cache.get('gex', 0.0)
                dix_pct = self._gex_cache.get('dix', 0.0)
                spx_price = self._gex_cache.get('price', 0.0)

                timestamp = datetime.now(pytz.timezone('US/Eastern'))
                await loop.run_in_executor(
                    self._db_executor,
                    self._db.insert_gex_record,
                    timestamp,
                    gex_total,   # gex_local
                    gex_total,   # gex_calibrated
                    1.0,         # alpha
                    0,           # put_wall
                    0,           # flip_zone_lower
                    0,           # flip_zone_upper
                )
                mon.set_output(1)

            logger.info(
                f"GEX维度写入: SPX={spx_price:.0f}, "
                f"GEX=${gex_total/1e9:.2f}B, DIX={dix_pct:.1f}%"
            )

        except Exception as e:
            logger.error(f"GEX维度评估失败: {e}", exc_info=True)

    # ================================================================
    # Event Handlers: VIX 维度
    # ================================================================

    async def _on_vix_update(self, data: Dict[str, Any]) -> None:
        """RESTPollScheduler 推送 VIX 期限结构"""
        # 数据可能直接是 dict 或嵌套在 'data' 字段里
        payload = data.get('data', data) if isinstance(data, dict) else data
        if isinstance(payload, dict):
            self._vix_cache.update(payload)
        else:
            self._vix_cache['spot'] = data
        self._vix_ready = True
        await self._evaluate_vix_dimension()
        await self._check_all_dimensions_ready()

    async def _evaluate_vix_dimension(self) -> None:
        """评估 VIX 维度: 分析期限结构, 写入DB"""
        try:
            loop = asyncio.get_event_loop()
            with PipelineMonitor.layer('layer3_resonance', 'VIX', 1) as mon:
                vix_spot = self._vix_cache.get('spot', 0.0)
                vx1 = self._vix_cache.get('vx1', 0.0)
                vx2 = self._vix_cache.get('vx2', 0.0)

                # VIX分析计算
                term_structure = await loop.run_in_executor(
                    self._executor,
                    self._vix_analyzer.analyze_term_structure,
                    vx1, vx2,
                )
                panic_premium = await loop.run_in_executor(
                    self._executor,
                    self._vix_analyzer.calculate_panic_premium,
                    vix_spot, vx1,
                )

                timestamp = datetime.now(pytz.timezone('US/Eastern'))
                await loop.run_in_executor(
                    self._db_executor,
                    self._db.insert_vix_analysis,
                    timestamp,
                    vix_spot,
                    vx1,
                    vx2,
                    term_structure['ratio'],
                    term_structure['state'],
                    panic_premium,
                )
                mon.set_output(1)

            logger.info(
                f"VIX维度写入: ratio={term_structure['ratio']:.4f}, "
                f"state={term_structure['state']}, panic={panic_premium}"
            )

        except Exception as e:
            logger.error(f"VIX维度评估失败: {e}", exc_info=True)

    # ================================================================
    # Event Handlers: Darkpool 维度
    # ================================================================

    async def _on_darkpool_update(self, data: Dict[str, Any]) -> None:
        """RESTPollScheduler 推送 AXLFI 暗盘数据"""
        self._darkpool_cache['axlfi'] = data
        await self._try_mark_darkpool_ready()

    async def _on_short_volume(self, data: Dict[str, Any]) -> None:
        """RESTPollScheduler 推送短卖比数据"""
        self._darkpool_cache['short_ratio'] = data.get('ratio', 0.0)
        self._darkpool_cache['short_source'] = data.get('source', 'unknown')
        await self._try_mark_darkpool_ready()

    async def _on_dbmf_recovery(self, data: Any) -> None:
        """RESTPollScheduler 推送 DBMF 收复信号"""
        self._darkpool_cache['dbmf_recovery'] = bool(data)
        await self._try_mark_darkpool_ready()

    async def _on_darkpool_preprocessed(self, data: Dict[str, Any]) -> None:
        """接收暗盘预处理结果 (EMA快慢线/零轴穿越/动量反转)"""
        self._darkpool_preprocessed = data
        logger.debug(
            f"暗盘预处理结果: V_net={data.get('latest_v_net', 0):,.0f}, "
            f"EMA_trend={data.get('ema_trend')}, "
            f"ZeroCross={data.get('zero_cross', {}).get('signal')}, "
            f"Momentum={data.get('momentum_reversal', {}).get('signal')}"
        )

    async def _try_mark_darkpool_ready(self) -> None:
        """检查 darkpool 维度是否至少两个子源就绪"""
        ready_count = 0
        if 'axlfi' in self._darkpool_cache:
            ready_count += 1
        if 'short_ratio' in self._darkpool_cache:
            ready_count += 1
        # DBMF 是加分项, 不作为必须
        if ready_count >= 1:
            self._darkpool_ready = True
            logger.debug(f"Darkpool 维度数据就绪 ({ready_count}/2 子源)")
            await self._evaluate_darkpool_dimension()
            await self._check_all_dimensions_ready()

    async def _evaluate_darkpool_dimension(self) -> None:
        """评估 Darkpool 维度: 提取信号, 写入DB"""
        try:
            loop = asyncio.get_event_loop()
            with PipelineMonitor.layer('layer1_filter', 'SPY', 5) as mon_dp:
                axlfi_data = self._darkpool_cache.get('axlfi', {})

                # 提取 AXLFI 子信号
                dp_position_list = axlfi_data.get('dollar_dp_position', [])
                close_prices = axlfi_data.get('close', [])
                divergence = axlfi_data.get('divergence', False)
                slope_20d = axlfi_data.get('slope_20d', 0.0)
                slope_60d = axlfi_data.get('slope_60d', 0.0)
                golden_cross = axlfi_data.get('golden_cross', False)

                latest_dp = dp_position_list[-1] if dp_position_list else 0
                short_pct_list = axlfi_data.get('short_volume_pct', [])
                latest_short_pct = short_pct_list[-1] if short_pct_list else 0

                # 验证信号
                confirmed_signal = await loop.run_in_executor(
                    self._executor,
                    lambda: self._darkpool_verifier.confirm_stockgrid_signal(
                        divergence, slope_20d, slope_60d,
                    ),
                )

                today = datetime.now(pytz.timezone('US/Eastern')).date()
                short_ratio = self._darkpool_cache.get('short_ratio', 0.0)
                dbmf_recovery = self._darkpool_cache.get('dbmf_recovery', False)

                await loop.run_in_executor(
                    self._db_executor,
                    self._db.insert_dark_pool_metrics,
                    today,
                    latest_dp / 1e9 if latest_dp else 0,  # 转为十亿美元
                    short_ratio,
                    slope_20d,
                    slope_60d,
                    divergence,
                    dbmf_recovery,
                    False,  # dix_signal
                    short_ratio > 45.0,
                    confirmed_signal,
                    golden_cross,
                    # v2.1 暗盘EMA预处理字段
                    self._darkpool_preprocessed.get('latest_v_net'),
                    self._darkpool_preprocessed.get('latest_ema_fast'),
                    self._darkpool_preprocessed.get('latest_ema_slow'),
                    self._darkpool_preprocessed.get('zero_cross', {}).get('signal'),
                    self._darkpool_preprocessed.get('momentum_reversal', {}).get('signal'),
                )
                mon_dp.set_output(5)

            logger.info(
                f"Darkpool维度写入: AXLFI DP=${latest_dp:,.0f}, "
                f"Short={short_ratio:.1f}%, DBMF={dbmf_recovery}, "
                f"V_net={self._darkpool_preprocessed.get('latest_v_net', 0):,.0f}, "
                f"ZCross={self._darkpool_preprocessed.get('zero_cross', {}).get('signal')}"
            )

        except Exception as e:
            logger.error(f"Darkpool维度评估失败: {e}", exc_info=True)

    # ================================================================
    # 暗盘源质量收集 (规范 §5)
    # ================================================================

    def _collect_darkpool_source_status(self) -> tuple:
        """从适配器收集暗盘各数据源的实时质量状态

        Returns:
            (source_status: Dict[str, str], degradation_mode: str)
            source_status: {'axlfi': 'OK', 'squeezemetrics': 'OK', 'stockgrid': 'UNAVAILABLE'}
            degradation_mode: NORMAL | DEGRADED | FALLBACK_ONLY_GEX
        """
        source_status: Dict[str, str] = {}

        try:
            from data_fetchers.axlfi_adapter import create_axlfi_adapter
            axlfi = create_axlfi_adapter()
            report = axlfi.fetch_with_quality("SPY", window=5)
            source_status['axlfi'] = report.status.value
        except Exception as e:
            logger.warning(f"AXLFI 质量检查失败: {e}")
            source_status['axlfi'] = 'UNAVAILABLE'

        try:
            from data_fetchers.squeezemetrics_adapter import create_squeezemetrics_adapter
            sqz = create_squeezemetrics_adapter()
            report = sqz.fetch_with_quality()
            source_status['squeezemetrics'] = report.status.value
        except Exception as e:
            logger.warning(f"SqueezeMetrics 质量检查失败: {e}")
            source_status['squeezemetrics'] = 'UNAVAILABLE'

        # Stockgrid 始终 UNAVAILABLE
        source_status['stockgrid'] = 'UNAVAILABLE'

        # 计算降级模式
        available_count = sum(
            1 for s in source_status.values()
            if s in ('OK', 'DEGRADED_NETWORK')
        )
        total_sources = len(source_status)

        if available_count == total_sources:
            degradation_mode = 'NORMAL'
        elif available_count > 0:
            degradation_mode = 'DEGRADED'
        else:
            degradation_mode = 'FALLBACK_ONLY_GEX'

        logger.info(
            f"暗盘源状态: {source_status}, "
            f"降级模式={degradation_mode} ({available_count}/{total_sources} 可用)"
        )

        return source_status, degradation_mode

    # ================================================================
    # Event Handler: 数据源错误 / 降级
    # ================================================================

    async def _on_source_error(self, data: Dict[str, Any]) -> None:
        """处理数据源错误, 触发降级"""
        source = data.get('source', 'unknown')
        error = data.get('error', '')
        logger.warning(f"数据源异常: source={source}, error={error}")

        # Hyperliquid WS 失联 → 触发 CCData REST 降级
        if source == 'hyperliquid':
            self._hyperliquid_connected = False
            if not self._ccdata_fallback_active:
                logger.warning("Hyperliquid WS 失联, 启动 CCData REST 降级")
                self._ccdata_fallback_active = True
                asyncio.create_task(self._ccdata_fallback_poll())

    async def _ccdata_fallback_poll(self) -> None:
        """CCData REST 降级轮询: 当 Hyperliquid WS 不可用时

        每隔 60 秒拉取一次 CCData REST API, 直到 Hyperliquid 恢复。
        """
        try:
            from data_fetchers import CCDataFetcher
            ccdata = CCDataFetcher()

            while not self._hyperliquid_connected and self._ccdata_fallback_active:
                logger.debug("CCData 降级轮询中...")
                loop = asyncio.get_event_loop()

                funding_rate = await loop.run_in_executor(
                    self._executor,
                    ccdata.get_funding_rate,
                    'BTC/USDT',
                )
                current_oi = await loop.run_in_executor(
                    self._executor,
                    ccdata.get_open_interest,
                    'BTC/USDT',
                )

                if funding_rate is not None and current_oi is not None:
                    now = datetime.now()
                    await self._bus.publish(
                        Topics.CRYPTO_FUNDING_RATE,
                        {'rate': funding_rate, 'coin': 'BTC', 'timestamp': now},
                    )
                    await self._bus.publish(
                        Topics.CRYPTO_OPEN_INTEREST,
                        {'oi': current_oi.get('oi', 0),
                         'oi_base': current_oi.get('oi', 0),
                         'mark_price': 0,
                         'coin': 'BTC',
                         'timestamp': now},
                    )

                await asyncio.sleep(60)

        except Exception as e:
            logger.error(f"CCData 降级轮询异常: {e}", exc_info=True)
        finally:
            self._ccdata_fallback_active = False

    # ================================================================
    # 共振评分与告警
    # ================================================================

    async def _check_all_dimensions_ready(self) -> None:
        """检查四维度是否全部就绪, 触发共振评分"""
        if not (self._crypto_ready and self._gex_ready and
                self._vix_ready and self._darkpool_ready):
            return

        # 防抖: 距离上次评估不到 EVAL_COOLDOWN_SECONDS 秒则跳过
        now = datetime.now(pytz.timezone('US/Eastern'))
        if self._last_eval_time:
            elapsed = (now - self._last_eval_time).total_seconds()
            if elapsed < self.EVAL_COOLDOWN_SECONDS:
                return

        self._last_eval_time = now
        logger.info("四维度全部就绪, 触发共振评分")

        # 异步执行共振评分 (不阻塞事件循环)
        asyncio.create_task(self._evaluate_resonance(now))

    async def _evaluate_resonance(self, current_time: datetime) -> None:
        """执行共振评分: 从DB读取最新数据 → 计算四维度分数 → 综合判定 → 告警"""
        try:
            loop = asyncio.get_event_loop()
            with PipelineMonitor.layer('layer4_signal', 'SPY', 4) as mon:
                # 从DB获取各维度最新数据
                latest_gex = await loop.run_in_executor(
                    self._db_executor, self._db.get_latest_gex,
                )
                latest_vix = await loop.run_in_executor(
                    self._db_executor, self._db.get_latest_vix_analysis,
                )
                latest_crypto = await loop.run_in_executor(
                    self._db_executor, self._db.get_latest_crypto_data,
                )
                latest_darkpool = await loop.run_in_executor(
                    self._db_executor, self._db.get_latest_dark_pool_metrics,
                )

                if not latest_gex:
                    logger.warning("GEX数据缺失，该维度记0分，继续部分评估")
                    gex_score = {'score': 0.0, 'state': 'MISSING', 'details': 'GEX数据缺失'}
                else:
                    # 计算各维度分值 (CPU密集型 → executor)
                    gex_score = await loop.run_in_executor(
                        self._executor,
                        lambda: self._resonance_scorer.calculate_gex_score(
                            gex_local=latest_gex['gex_local'],
                            gex_calibrated=latest_gex['gex_calibrated'],
                            flip_zone_crossed=latest_gex['gex_calibrated'] > 0,
                            gex_trend='IMPROVING',
                        ),
                    )

                vix_score = await loop.run_in_executor(
                    self._executor,
                    lambda: self._resonance_scorer.calculate_vix_score(
                        term_structure_ratio=(
                            latest_vix.get('term_structure_ratio', 1.0)
                            if latest_vix else 1.0
                        ),
                        slope_direction='DOWN',
                        panic_premium=(
                            latest_vix.get('panic_premium', 0.0)
                            if latest_vix else 0.0
                        ),
                    ),
                )

                crypto_score = await loop.run_in_executor(
                    self._executor,
                    lambda: self._resonance_scorer.calculate_crypto_score(
                        oi_crash=(
                            latest_crypto.get('oi_crash', False)
                            if latest_crypto else False
                        ),
                        funding_positive=(
                            latest_crypto.get('btc_funding_rate', 0) >= 0
                            if latest_crypto else False
                        ),
                        elr_safe=False,
                        leverage_cleanup_confirmed=False,
                    ),
                )

                # 暗盘评分 (支持降级) — 从适配器收集真实源状态
                darkpool_source_status, darkpool_degradation_mode = \
                    self._collect_darkpool_source_status()

                available_sources = {
                    'dix': darkpool_source_status.get('squeezemetrics', 'OK') in ('OK', 'DEGRADED_NETWORK'),
                    'short_ratio': True,  # yfinance/FINRA 始终可用
                    'stockgrid': darkpool_source_status.get('axlfi', 'OK') in ('OK', 'DEGRADED_NETWORK'),
                }
                darkpool_score = await loop.run_in_executor(
                    self._executor,
                    lambda: self._resonance_scorer.calculate_darkpool_score_with_fallback(
                        dix_flag=(
                            latest_darkpool.get('dix_signal', False)
                            if latest_darkpool else False
                        ),
                        short_ratio_flag=(
                            latest_darkpool.get('short_ratio_signal', False)
                            if latest_darkpool else False
                        ),
                        stockgrid_flag=(
                            latest_darkpool.get('stockgrid_signal', False)
                            if latest_darkpool else False
                        ),
                        dbmf_recovery=(
                            latest_darkpool.get('dbmf_ma5_recovery', False)
                            if latest_darkpool else False
                        ),
                        available_sources=available_sources,
                        
                        preprocessed_bonus=self._resonance_scorer.compute_preprocessed_bonus(
                            self._darkpool_preprocessed
                        ),
                    ),
                )

                # 计算共振总分
                resonance_result = await loop.run_in_executor(
                    self._executor,
                    lambda: self._resonance_scorer.calculate_total_score(
                        gex_result=gex_score,
                        vix_result=vix_score,
                        crypto_result=crypto_score,
                        darkpool_result=darkpool_score,
                    ),
                )

                # Hawkes Process
                hawkes_result = await loop.run_in_executor(
                    self._executor,
                    lambda: self._resonance_scorer.estimate_hawkes_branching_ratio(
                        recent_price_changes=[],
                        recent_volumes=[],
                    ),
                )

                # 检查是否触发告警
                trigger_result = await loop.run_in_executor(
                    self._executor,
                    self._signal_machine.check_and_trigger,
                    resonance_result,
                    current_time,
                )
                mon.set_output(1)

                if trigger_result['should_alert']:
                    await self._send_alert(
                        resonance_result, hawkes_result, current_time,
                    )
                else:
                    logger.debug(
                        f"共振评估完成: {resonance_result['total_score']}/"
                        f"{resonance_result['max_score']}, {trigger_result['reason']}"
                    )

                # 重置维度就绪标记, 等待下一轮数据
                self._crypto_ready = False
                self._gex_ready = False
                self._vix_ready = False
                self._darkpool_ready = False

        except Exception as e:
            logger.error(f"共振评分失败: {e}", exc_info=True)
    async def _send_alert(
        self,
        resonance_result: Dict[str, Any],
        hawkes_result: Dict[str, Any],
        current_time: datetime,
    ) -> None:
        """发送告警: 格式化消息 → 写入DB → 多渠道推送"""
        try:
            loop = asyncio.get_event_loop()

            # 格式化告警消息
            alert_message = await loop.run_in_executor(
                self._executor,
                lambda: self._alert_sender.format_level3_alert(
                    resonance_result=resonance_result,
                    hawkes_result=hawkes_result,
                    current_time=current_time,
                    put_wall_range=None,
                ),
            )

            # 写入DB
            await loop.run_in_executor(
                self._db_executor,
                self._db.insert_signal_alert,
                current_time,
                resonance_result['total_score'],
                resonance_result['dimension_scores']['gex']['score'],
                resonance_result['dimension_scores']['vix']['score'],
                resonance_result['dimension_scores']['crypto']['score'],
                resonance_result['dimension_scores']['darkpool']['score'],
                resonance_result['alert_level'],
                hawkes_result['branching_ratio'],
                resonance_result,
            )

            # 多渠道发送告警
            alert_level = resonance_result['alert_level']
            channels = (
                ['email', 'telegram'] if alert_level == 'LEVEL_3'
                else ['email']
            )

            send_results = await loop.run_in_executor(
                self._executor,
                lambda: self._alert_sender.send_multi_channel_alert(
                    subject=f"[{alert_level}] 共振抄底信号触发",
                    message=alert_message,
                    channels=channels,
                ),
            )

            success_count = sum(1 for v in send_results.values() if v)
            logger.warning(
                f"🚨 {alert_level} 告警已发送! "
                f"总分={resonance_result['total_score']}, "
                f"渠道成功={success_count}/{len(channels)}"
            )

        except Exception as e:
            logger.error(f"告警发送失败: {e}", exc_info=True)
