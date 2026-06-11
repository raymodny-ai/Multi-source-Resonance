"""
多源共振监控系统 - REST 轮询调度器 (轻量级, 替代 APScheduler)

处理不支持 WebSocket 的数据源 (SqueezeMetrics GEX, Yahoo VIX,
AXLFI 暗盘, DBMF, FINRA 短卖比)。

与旧 Pull 架构的对比:
    旧: APScheduler cron jobs → 固定时刻执行
    新: asyncio.create_task + asyncio.sleep → 轻量循环

特性:
- 每个数据源独立 asyncio.Task
- 盘中和盘后自动切换间隔
- 数据获取 → 发布到 EventBus (而非直接写DB)
- 优雅关闭 (cancel all tasks)
"""

import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor

import pytz

from utils.logger import getLogger
from data_stream.event_bus import EventBus, Topics
from config.settings import Config, DataFetchConfig

logger = getLogger('rest_poll_scheduler')

# 默认轮询间隔 (秒)
POLL_INTERVAL_INTRADAY = 900    # 盘中 15分钟
POLL_INTERVAL_CRYPTO = 60       # 加密降级轮询 1分钟
POLL_AFTERHOURS_HOUR = 20       # 盘后任务触发小时 (美东)
POLL_AFTERHOURS_MINUTE = 30     # 盘后任务触发分钟


class RESTPollScheduler:
    """轻量级 REST 轮询调度器

    为每个不支持 WebSocket 的数据源创建独立的异步轮询任务。
    数据获取后发布到 EventBus，由 SignalPipeline 统一处理。

    使用示例:
        bus = get_event_bus()
        scheduler = RESTPollScheduler(bus)
        await scheduler.start()
    """

    def __init__(self, event_bus: EventBus):
        """初始化轮询调度器

        Args:
            event_bus: 全局事件总线实例
        """
        self._bus = event_bus
        self._config = Config()
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._tasks: List[asyncio.Task] = []
        self._running = False
        self._paused = False  # 自动轮询暂停标志

        # 延迟导入数据获取器 (避免循环依赖)
        self._squeezemetrics = None
        self._yahoo = None  # VIX + 做空数据 (yfinance, 替代已删除FMP)
        self._axlfi = None
        self._dbmf = None
        self._finra = None
        self._hyperliquid = None  # 加密衍生品 REST
        self._ccdata = None       # 加密衍生品降级

        logger.info("RESTPollScheduler 初始化完成")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        """暂停所有自动轮询任务 (任务继续运行但跳过数据采集)"""
        if self._paused:
            return
        self._paused = True
        logger.warning("[AUTO_POLLING] 自动轮询已暂停 — 只有手动采集可用")

    def resume(self) -> None:
        """恢复自动轮询"""
        if not self._paused:
            return
        self._paused = False
        logger.info("[AUTO_POLLING] 自动轮询已恢复")

    async def start(self) -> None:
        """启动所有轮询任务"""
        if self._running:
            return

        self._running = True

        # 延迟加载数据获取器
        self._load_fetchers()

        # 启动各数据源轮询任务
        self._tasks.append(asyncio.create_task(self._poll_gex_dix()))
        self._tasks.append(asyncio.create_task(self._poll_vix()))
        self._tasks.append(asyncio.create_task(self._poll_axlfi()))
        self._tasks.append(asyncio.create_task(self._poll_dbmf()))

        logger.info(
            f"RESTPollScheduler 已启动, {len(self._tasks)} 个轮询任务运行中"
        )

    async def shutdown(self) -> None:
        """关闭所有轮询任务"""
        if not self._running:
            return

        self._running = False

        for task in self._tasks:
            task.cancel()

        # 等待所有任务取消完成
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        self._executor.shutdown(wait=False)
        logger.info("RESTPollScheduler 已关闭")

    def _load_fetchers(self) -> None:
        """延迟加载数据获取器实例"""
        try:
            from data_fetchers import SqueezeMetricsFetcher, YahooFinanceFetcher
            from data_fetchers import FINRAFetcher, DBMFFetcher
            from data_fetchers import HyperliquidFetcher, CCDataFetcher
            from data_fetchers.axlfi_fetcher import AxlfiFetcher

            self._yahoo = YahooFinanceFetcher()  # VIX + 做空数据 (yfinance)
            self._axlfi = AxlfiFetcher()
            self._dbmf = DBMFFetcher()
            self._finra = FINRAFetcher()
            self._hyperliquid = HyperliquidFetcher()  # 加密衍生品 (REST 降级)
            self._ccdata = CCDataFetcher()            # 加密衍生品 (二级降级)
            logger.debug("数据获取器延迟加载完成 (6 数据源)")
        except Exception as e:
            logger.error(f"数据获取器加载失败: {e}", exc_info=True)

    def _is_market_hours(self) -> bool:
        """判断当前是否为美股交易时段 (美东 9:30-16:00)"""
        try:
            return Config.is_market_hours()
        except Exception:
            # 降级: 按UTC时间粗略判断 (美东=UTC-4 夏令时)
            from datetime import timezone, timedelta
            now_utc = datetime.now(timezone.utc)
            est_offset = timedelta(hours=-4)
            now_est = now_utc + est_offset
            minutes = now_est.hour * 60 + now_est.minute
            return 570 <= minutes < 960  # 9:30-16:00

    def _is_weekday(self) -> bool:
        """判断是否为工作日 (周一到周五)"""
        try:
            eastern = pytz.timezone('US/Eastern')
            now = datetime.now(eastern)
            return now.weekday() < 5
        except Exception:
            return datetime.now().weekday() < 5

    # ================================================================
    # Poll Tasks: GEX/DIX (SqueezeMetrics)
    # ================================================================

    async def _poll_gex_dix(self) -> None:
        """轮询 SqueezeMetrics GEX+DIX 数据

        盘中每15分钟获取一次, 发布到 EventBus Topics.GEX_UPDATE
        """
        logger.info("GEX/DIX 轮询任务已启动")
        interval = POLL_INTERVAL_INTRADAY

        while self._running:
            try:
                # 暂停检查: 自动轮询关闭时休眠等待
                if self._paused:
                    await asyncio.sleep(1)
                    continue

                if not self._is_market_hours() or not self._is_weekday():
                    await asyncio.sleep(60)
                    interval = POLL_INTERVAL_INTRADAY
                    continue

                loop = asyncio.get_event_loop()
                metrics = await loop.run_in_executor(
                    self._executor,
                    self._squeezemetrics.get_full_metrics,
                )

                if metrics:
                    await self._bus.publish(Topics.GEX_UPDATE, {
                        'gex': metrics.get('gex', 0.0),
                        'dix': metrics.get('dix', 0.0),
                        'price': metrics.get('price', 0.0),
                        'timestamp': datetime.now(),
                    })
                    logger.debug(
                        f"GEX/DIX 已发布: GEX={metrics['gex']/1e9:.2f}B, "
                        f"DIX={metrics['dix']:.1f}%"
                    )
                else:
                    logger.debug("GEX/DIX 获取为空, 跳过")

                interval = POLL_INTERVAL_INTRADAY
                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"GEX/DIX 轮询异常: {e}", exc_info=True)
                await self._bus.publish(Topics.DATA_SOURCE_ERROR, {
                    'source': 'squeezemetrics',
                    'error': str(e),
                })
                await asyncio.sleep(60)

    # ================================================================
    # Poll Tasks: VIX (Yahoo Finance)
    # ================================================================

    async def _poll_vix(self) -> None:
        """轮询 Yahoo Finance VIX 期限结构数据

        盘中每15分钟获取一次, 发布到 EventBus Topics.VIX_TERM_STRUCTURE
        """
        logger.info("VIX 轮询任务已启动")
        interval = POLL_INTERVAL_INTRADAY

        while self._running:
            try:
                # 暂停检查: 自动轮询关闭时休眠等待
                if self._paused:
                    await asyncio.sleep(1)
                    continue

                if not self._is_market_hours() or not self._is_weekday():
                    await asyncio.sleep(60)
                    interval = POLL_INTERVAL_INTRADAY
                    continue

                loop = asyncio.get_event_loop()

                vx1 = await loop.run_in_executor(
                    self._executor,
                    self._yahoo.get_vix_futures,
                    'VX1',
                )
                vx2 = await loop.run_in_executor(
                    self._executor,
                    self._yahoo.get_vix_futures,
                    'VX2',
                )
                vix_spot = await loop.run_in_executor(
                    self._executor,
                    self._yahoo.get_vix_spot,
                )

                if all([vx1, vx2, vix_spot]):
                    await self._bus.publish(Topics.VIX_TERM_STRUCTURE, {
                        'spot': vix_spot,
                        'vx1': vx1,
                        'vx2': vx2,
                        'timestamp': datetime.now(),
                    })
                    logger.debug(
                        f"VIX 已发布: spot={vix_spot:.2f}, "
                        f"VX1={vx1:.2f}, VX2={vx2:.2f}"
                    )
                else:
                    logger.debug("VIX 数据不完整, 跳过")

                interval = POLL_INTERVAL_INTRADAY
                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"VIX 轮询异常: {e}", exc_info=True)
                await self._bus.publish(Topics.DATA_SOURCE_ERROR, {
                    'source': 'yahoo_vix',
                    'error': str(e),
                })
                await asyncio.sleep(60)

    # ================================================================
    # Poll Tasks: AXLFI Darkpool
    # ================================================================

    async def _poll_axlfi(self) -> None:
        """轮询 AXLFI 暗盘净头寸数据

        盘中每15分钟获取一次, 发布到 EventBus Topics.DARKPOOL_AXLFI
        同时运行暗盘预处理器 (EMA快慢线/零轴穿越/动量反转)
        """
        logger.info("AXLFI 暗盘轮询任务已启动")
        interval = POLL_INTERVAL_INTRADAY

        # 延迟导入预处理器
        from quant_logic.darkpool_preprocessor import DarkPoolPreprocessor
        preprocessor = DarkPoolPreprocessor()

        while self._running:
            try:
                # 暂停检查: 自动轮询关闭时休眠等待
                if self._paused:
                    await asyncio.sleep(1)
                    continue

                if not self._is_market_hours() or not self._is_weekday():
                    await asyncio.sleep(60)
                    interval = POLL_INTERVAL_INTRADAY
                    continue

                loop = asyncio.get_event_loop()
                symbol_data = await loop.run_in_executor(
                    self._executor,
                    lambda: self._axlfi.fetch_symbol_data('SPY', 120),
                )

                if symbol_data:
                    dp_position = symbol_data.get('dollar_dp_position', [])
                    close_prices = symbol_data.get('close', [])

                    if len(dp_position) >= 60:
                        # 检测底背离
                        divergence_result = await loop.run_in_executor(
                            self._executor,
                            lambda: self._axlfi.detect_bottom_divergence(
                                (dp_position[-120:]
                                 if len(dp_position) >= 120
                                 else dp_position),
                                (close_prices[-120:]
                                 if close_prices and len(close_prices) >= 120
                                 else dp_position[-120:]),
                            ),
                        )

                        latest_dp = dp_position[-1]
                        short_pct_list = symbol_data.get('short_volume_pct', [])
                        latest_short_pct = (
                            short_pct_list[-1] if short_pct_list else 0
                        )

                        # === 暗盘预处理: EMA快慢线/零轴穿越/动量反转 ===
                        short_vol_series = symbol_data.get('short_volume', [])
                        net_vol_series = symbol_data.get('net_volume', [])
                        preprocess_result = None
                        if short_vol_series and net_vol_series and len(short_vol_series) >= 20:
                            preprocess_result = await loop.run_in_executor(
                                self._executor,
                                lambda: preprocessor.full_process(
                                    short_vol_series[-120:] if len(short_vol_series) >= 120 else short_vol_series,
                                    net_vol_series[-120:] if len(net_vol_series) >= 120 else net_vol_series,
                                ),
                            )

                        await self._bus.publish(Topics.DARKPOOL_AXLFI, {
                            'dollar_dp_position': dp_position,
                            'close': close_prices,
                            'divergence': divergence_result.get('divergence', False),
                            'slope_20d': divergence_result.get('slope_20d', 0.0),
                            'slope_60d': divergence_result.get('slope_60d', 0.0),
                            'golden_cross': divergence_result.get('golden_cross', False),
                            'short_volume_pct': short_pct_list,
                            'timestamp': datetime.now(),
                        })

                        # 同时发布短卖比数据 (如果 yfinance 还未推送)
                        # 注: yfinance 做空数据已在 run_afterhours_short_volume() 中获取
                        if latest_short_pct > 0:
                            await self._bus.publish(Topics.SHORT_VOLUME_SPY, {
                                'ratio': latest_short_pct,
                                'source': 'axlfi',
                                'timestamp': datetime.now(),
                            })

                        # 发布暗盘预处理结果 (EMA快慢线/零轴穿越/动量反转)
                        if preprocess_result:
                            await self._bus.publish(Topics.DARKPOOL_PREPROCESSED, preprocess_result)

                        logger.debug(
                            f"AXLFI 已发布: DP=${latest_dp:,.0f}, "
                            f"divergence={divergence_result.get('divergence')}"
                        )
                    else:
                        logger.debug(f"AXLFI 数据点不足: {len(dp_position)}")
                else:
                    logger.debug("AXLFI 数据为空, 跳过")

                interval = POLL_INTERVAL_INTRADAY
                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"AXLFI 轮询异常: {e}", exc_info=True)
                await self._bus.publish(Topics.DATA_SOURCE_ERROR, {
                    'source': 'axlfi',
                    'error': str(e),
                })
                await asyncio.sleep(60)

    # ================================================================
    # Poll Tasks: DBMF
    # ================================================================

    async def _poll_dbmf(self) -> None:
        """轮询 DBMF 均线收复信号

        盘中每15分钟检测一次, 发布到 EventBus Topics.DBMF_RECOVERY
        """
        logger.info("DBMF 轮询任务已启动")
        interval = POLL_INTERVAL_INTRADAY

        while self._running:
            try:
                # 暂停检查: 自动轮询关闭时休眠等待
                if self._paused:
                    await asyncio.sleep(1)
                    continue

                if not self._is_market_hours() or not self._is_weekday():
                    await asyncio.sleep(60)
                    interval = POLL_INTERVAL_INTRADAY
                    continue

                loop = asyncio.get_event_loop()

                current_price = await loop.run_in_executor(
                    self._executor,
                    self._dbmf.get_dbmf_intraday_price,
                )
                historical_prices = await loop.run_in_executor(
                    self._executor,
                    lambda: self._dbmf.get_dbmf_historical_prices(days=10),
                )

                if current_price and historical_prices:
                    recovery = await loop.run_in_executor(
                        self._executor,
                        self._dbmf.check_ma5_recovery,
                        current_price,
                        historical_prices,
                    )

                    await self._bus.publish(
                        Topics.DBMF_RECOVERY,
                        {'recovery': recovery, 'price': current_price},
                    )
                    logger.debug(
                        f"DBMF 已发布: price={current_price:.2f}, recovery={recovery}"
                    )

                interval = POLL_INTERVAL_INTRADAY
                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"DBMF 轮询异常: {e}", exc_info=True)
                await self._bus.publish(Topics.DATA_SOURCE_ERROR, {
                    'source': 'dbmf',
                    'error': str(e),
                })
                await asyncio.sleep(60)

    # ================================================================
    # 盘后任务: 做空数据 (yfinance → FINRA)
    # ================================================================

    async def run_afterhours_short_volume(self) -> None:
        """盘后获取做空数据 (yfinance → FINRA 降级链路)

        一次性执行: yfinance short interest 优先, 失败则降级 FINRA 管道文件。
        结果发布到 EventBus Topics.SHORT_VOLUME_SPY
        """
        logger.info("盘后做空数据任务启动 (yfinance → FINRA 降级)")
        try:
            loop = asyncio.get_event_loop()
            short_ratio = None
            data_source = None

            # 第1步: yfinance 做空数据 (免费, 无API Key)
            short_data = await loop.run_in_executor(
                self._executor,
                lambda: self._yahoo.get_short_interest('SPY'),
            )

            if short_data and short_data.get('short_pct_float') is not None:
                short_ratio = short_data['short_pct_float']
                data_source = 'yfinance'
            else:
                # 第2步: 降级 FINRA 管道文件
                logger.warning("yfinance 做空数据失败, 降级到 FINRA")
                spy_data = await loop.run_in_executor(
                    self._executor,
                    lambda: self._finra.fetch_short_volume_data('SPY'),
                )
                if spy_data:
                    short_ratio = await loop.run_in_executor(
                        self._executor,
                        self._finra.calculate_off_exchange_short_ratio,
                        spy_data,
                    )
                    data_source = 'FINRA'

            if short_ratio is not None:
                await self._bus.publish(Topics.SHORT_VOLUME_SPY, {
                    'ratio': short_ratio,
                    'source': data_source,
                    'timestamp': datetime.now(),
                })
                logger.info(
                    f"盘后做空数据: {short_ratio:.1f}% (源={data_source})"
                )
            else:
                logger.warning("yfinance 和 FINRA 均获取做空数据失败")

        except Exception as e:
            logger.error(f"盘后做空数据任务失败: {e}", exc_info=True)

    # ================================================================
    # 手动采集: 一次性执行所有 6 数据源 (忽略暂停/市场时间限制)
    # ================================================================

    async def run_once_manual_collect(self) -> Dict[str, Any]:
        """手动触发一次完整的 6 数据源采集循环

        忽略自动轮询暂停状态和市场时间限制，
        并发执行所有数据源采集，并通过 EventBus 发布。

        Returns:
            dict: 每个数据源的采集结果 {"name": str, "status": str, "elapsed_sec": float, ...}
        """
        import time as _time
        start_ts = _time.time()
        results: List[Dict[str, Any]] = []

        # ── OpenCLAW 风格分界线 ──
        logger.info("=" * 54)
        logger.info("  MANUAL COLLECT STARTED  %s", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        logger.info("=" * 54)
        logger.info("── 开始手动采集 (6 数据源) ──")

        self._load_fetchers()

        # 强制刷新 VIX 缓存 (确保手动采集获取最新 CBOE 数据)
        try:
            from data_fetchers.yahoo_finance_fetcher import YahooFinanceFetcher
            YahooFinanceFetcher.invalidate_vix_cache()
            logger.info("[VIX     ] VIX 缓存已刷新，将获取最新 CBOE 数据")
        except Exception:
            pass

        async def _collect_one(name: str, source_tag: str, coro):
            t0 = _time.time()
            try:
                await coro
                elapsed = round(_time.time() - t0, 2)
                logger.info("[%-8s] ✓ 采集成功  耗时 %.2fs", source_tag, elapsed)
                return {"name": name, "source_tag": source_tag, "status": "success", "elapsed_sec": elapsed}
            except Exception as e:
                elapsed = round(_time.time() - t0, 2)
                logger.error("[%-8s] ✗ 采集失败  耗时 %.2fs  (%s)", source_tag, elapsed, str(e)[:80])
                return {"name": name, "source_tag": source_tag, "status": "error", "elapsed_sec": elapsed, "error": str(e)}

        # 并发执行全部 6 个采集任务
        tasks = [
            _collect_one("GEX/DIX",       "GEX/DIX", self._poll_gex_dix_once()),
            _collect_one("VIX期限结构",    "VIX",     self._poll_vix_once()),
            _collect_one("AXLFI暗盘",      "AXLFI",   self._poll_axlfi_once()),
            _collect_one("DBMF均线",       "DBMF",    self._poll_dbmf_once()),
            _collect_one("加密衍生品",     "CRYPTO",  self._poll_crypto_once()),
            _collect_one("做空数据",       "SHORT",   self._poll_short_once()),
        ]
        results = list(await asyncio.gather(*tasks))

        total_sources = len(results)
        success_count = sum(1 for r in results if r.get("status") == "success")
        total_elapsed = round(_time.time() - start_ts, 2)

        # ── 汇总分界线 ──
        if success_count == total_sources:
            logger.info("── 采集完成 %d/%d 全部成功, 总耗时 %.2fs ──", success_count, total_sources, total_elapsed)
        elif success_count > 0:
            logger.warning("── 采集完成 %d/%d 部分成功, 总耗时 %.2fs ──", success_count, total_sources, total_elapsed)
        else:
            logger.error("── 采集完成 %d/%d 全部失败, 总耗时 %.2fs ──", success_count, total_sources, total_elapsed)
        logger.info("=" * 54)

        summary = f"[MANUAL] 手动采集完成: {success_count}/{total_sources} 成功, 耗时 {total_elapsed}s"

        return {
            "summary": summary,
            "success_count": success_count,
            "total_sources": total_sources,
            "total_elapsed_sec": total_elapsed,
            "sources": results,
        }

    async def _poll_gex_dix_once(self):
        """单次 GEX/DIX 采集 (忽略市场时间)"""
        loop = asyncio.get_event_loop()
        metrics = await loop.run_in_executor(
            self._executor, self._squeezemetrics.get_full_metrics
        )
        if metrics:
            await self._bus.publish(Topics.GEX_UPDATE, {
                'gex': metrics.get('gex', 0.0),
                'dix': metrics.get('dix', 0.0),
                'price': metrics.get('price', 0.0),
                'timestamp': datetime.now(),
            })

    async def _poll_vix_once(self):
        """单次 VIX 采集"""
        loop = asyncio.get_event_loop()
        vx1 = await loop.run_in_executor(self._executor, self._yahoo.get_vix_futures, 'VX1')
        vx2 = await loop.run_in_executor(self._executor, self._yahoo.get_vix_futures, 'VX2')
        vix_spot = await loop.run_in_executor(self._executor, self._yahoo.get_vix_spot)
        if all([vx1, vx2, vix_spot]):
            await self._bus.publish(Topics.VIX_TERM_STRUCTURE, {
                'spot': vix_spot, 'vx1': vx1, 'vx2': vx2, 'timestamp': datetime.now(),
            })

    async def _poll_axlfi_once(self):
        """单次 AXLFI 采集 (含暗盘预处理)"""
        loop = asyncio.get_event_loop()
        symbol_data = await loop.run_in_executor(
            self._executor, lambda: self._axlfi.fetch_symbol_data('SPY', 120)
        )
        if symbol_data:
            dp_position = symbol_data.get('dollar_dp_position', [])
            close_prices = symbol_data.get('close', [])
            if len(dp_position) >= 60:
                divergence_result = await loop.run_in_executor(
                    self._executor,
                    lambda: self._axlfi.detect_bottom_divergence(
                        dp_position[-120:] if len(dp_position) >= 120 else dp_position,
                        close_prices[-120:] if close_prices and len(close_prices) >= 120 else dp_position[-120:],
                    ),
                )
                await self._bus.publish(Topics.DARKPOOL_AXLFI, {
                    'dollar_dp_position': dp_position,
                    'close': close_prices,
                    'divergence': divergence_result.get('divergence', False),
                    'slope_20d': divergence_result.get('slope_20d', 0.0),
                    'slope_60d': divergence_result.get('slope_60d', 0.0),
                    'golden_cross': divergence_result.get('golden_cross', False),
                    'short_volume_pct': symbol_data.get('short_volume_pct', []),
                    'timestamp': datetime.now(),
                })

                # 暗盘预处理: EMA快慢线/零轴穿越/动量反转
                short_vol = symbol_data.get('short_volume', [])
                net_vol = symbol_data.get('net_volume', [])
                if short_vol and net_vol and len(short_vol) >= 20:
                    from quant_logic.darkpool_preprocessor import DarkPoolPreprocessor
                    pp = DarkPoolPreprocessor()
                    preprocess_result = await loop.run_in_executor(
                        self._executor,
                        lambda: pp.full_process(
                            short_vol[-120:] if len(short_vol) >= 120 else short_vol,
                            net_vol[-120:] if len(net_vol) >= 120 else net_vol,
                        ),
                    )
                    if preprocess_result:
                        await self._bus.publish(Topics.DARKPOOL_PREPROCESSED, preprocess_result)

    async def _poll_dbmf_once(self):
        """单次 DBMF 采集"""
        loop = asyncio.get_event_loop()
        current_price = await loop.run_in_executor(self._executor, self._dbmf.get_dbmf_intraday_price)
        historical_prices = await loop.run_in_executor(
            self._executor, lambda: self._dbmf.get_dbmf_historical_prices(days=10)
        )
        if current_price and historical_prices:
            recovery = await loop.run_in_executor(
                self._executor, self._dbmf.check_ma5_recovery, current_price, historical_prices
            )
            await self._bus.publish(Topics.DBMF_RECOVERY, {'recovery': recovery, 'price': current_price})

    async def _poll_crypto_once(self):
        """单次加密衍生品采集 (Hyperliquid REST → CCData 降级)

        获取 BTC funding rate 和 open interest，
        优先 Hyperliquid REST API，失败则降级 CCData。
        """
        loop = asyncio.get_event_loop()
        funding_rate = None
        oi_data = None
        data_source = None

        # 第1步: Hyperliquid REST API
        try:
            funding_rate = await loop.run_in_executor(
                self._executor, self._hyperliquid.get_funding_rate, 'BTC/USDT'
            )
            oi_data = await loop.run_in_executor(
                self._executor, self._hyperliquid.get_open_interest, 'BTC/USDT'
            )
            if funding_rate is not None or oi_data is not None:
                data_source = 'Hyperliquid'
        except Exception as e:
            logger.debug(f"Hyperliquid REST 加密数据失败: {e}")

        # 第2步: CCData 降级
        if data_source is None:
            try:
                funding_rate = await loop.run_in_executor(
                    self._executor, self._ccdata.get_funding_rate, 'BTC/USDT'
                )
                oi_data = await loop.run_in_executor(
                    self._executor, self._ccdata.get_open_interest, 'BTC/USDT'
                )
                if funding_rate is not None or oi_data is not None:
                    data_source = 'CCData'
            except Exception as e:
                logger.debug(f"CCData 加密数据失败: {e}")

        if data_source and (funding_rate is not None or oi_data is not None):
            oi_value = oi_data.get('oi') if isinstance(oi_data, dict) else oi_data
            await self._bus.publish(Topics.CRYPTO_FUNDING_RATE, {
                'rate': funding_rate or 0.0,
                'coin': 'BTC',
                'timestamp': datetime.now(),
            })
            if oi_value is not None:
                await self._bus.publish(Topics.CRYPTO_OPEN_INTEREST, {
                    'oi': oi_value,
                    'coin': 'BTC',
                    'source': data_source,
                    'timestamp': datetime.now(),
                })
        else:
            raise RuntimeError("Hyperliquid 和 CCData 均获取加密数据失败")

    async def _poll_short_once(self):
        """单次做空数据采集 (yfinance → FINRA 降级)

        获取 SPY 做空比例，优先 yfinance short interest，
        失败则降级 FINRA 管道文件。
        """
        loop = asyncio.get_event_loop()
        short_ratio = None
        data_source = None

        # 第1步: yfinance 做空数据
        try:
            short_data = await loop.run_in_executor(
                self._executor,
                lambda: self._yahoo.get_short_interest('SPY'),
            )
            if short_data and short_data.get('short_pct_float') is not None:
                short_ratio = short_data['short_pct_float']
                data_source = 'yfinance'
        except Exception as e:
            logger.debug(f"yfinance 做空数据失败: {e}")

        # 第2步: FINRA 降级
        if data_source is None:
            try:
                spy_data = await loop.run_in_executor(
                    self._executor,
                    lambda: self._finra.fetch_short_volume_data('SPY'),
                )
                if spy_data:
                    short_ratio = await loop.run_in_executor(
                        self._executor,
                        self._finra.calculate_off_exchange_short_ratio,
                        spy_data,
                    )
                    data_source = 'FINRA'
            except Exception as e:
                logger.debug(f"FINRA 做空数据失败: {e}")

        if short_ratio is not None:
            await self._bus.publish(Topics.SHORT_VOLUME_SPY, {
                'ratio': short_ratio,
                'source': data_source,
                'timestamp': datetime.now(),
            })
        else:
            raise RuntimeError("yfinance 和 FINRA 均获取做空数据失败")
