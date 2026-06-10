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

        # 延迟导入数据获取器 (避免循环依赖)
        self._squeezemetrics = None
        self._yahoo = None  # VIX + 做空数据 (yfinance, 替代已删除FMP)
        self._axlfi = None
        self._dbmf = None
        self._finra = None

        logger.info("RESTPollScheduler 初始化完成")

    @property
    def is_running(self) -> bool:
        return self._running

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
            from data_fetchers.axlfi_fetcher import AxlfiFetcher

            self._yahoo = YahooFinanceFetcher()  # VIX + 做空数据 (yfinance)
            self._axlfi = AxlfiFetcher()
            self._dbmf = DBMFFetcher()
            self._finra = FINRAFetcher()
            logger.debug("数据获取器延迟加载完成")
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
        """
        logger.info("AXLFI 暗盘轮询任务已启动")
        interval = POLL_INTERVAL_INTRADAY

        while self._running:
            try:
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
