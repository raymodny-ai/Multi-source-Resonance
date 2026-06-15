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

# 每日批量采集时间 (美东)
DAILY_BATCH_HOUR = 20       # 每日美东 20:00 执行全量数据采集
DAILY_BATCH_MINUTE = 0
DAILY_BATCH_INTERVAL_SECONDS = 86400  # 24 小时

# [DEPRECATED] 旧盘中轮询常量 (保留兼容)
POLL_INTERVAL_INTRADAY = 900    # deprecated
POLL_INTERVAL_CRYPTO = 60       # deprecated
POLL_AFTERHOURS_HOUR = 20       # deprecated
POLL_AFTERHOURS_MINUTE = 0      # deprecated


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
        """启动每日定时批量采集任务

        每天美东 20:00 执行一次全量数据采集 (6 数据源)。
        数据通过 EventBus 发布后，由 SignalPipeline 消费并触发共振评分。
        """
        if self._running:
            return

        self._running = True

        # 启动每日批量采集循环
        self._tasks.append(asyncio.create_task(self._run_daily_batch_loop()))

        logger.info(
            "RESTPollScheduler 已启动 — 每日美东 %02d:%02d 执行全量数据采集",
            DAILY_BATCH_HOUR, DAILY_BATCH_MINUTE,
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
    # 每日定时批量采集 (ET 20:00)
    # ================================================================

    async def _run_daily_batch_loop(self) -> None:
        """每日批量采集主循环

        每天美东 20:00 执行一次 run_once_manual_collect()，
        将全部 6 数据源 (GEX/DIX, VIX, AXLFI暗盘, DBMF, 加密衍生品, 做空)
        的最新数据通过 EventBus 发布，由 SignalPipeline 消费。
        """
        import time as _time

        logger.info(
            "每日批量采集循环已启动 — 目标时间: 美东 %02d:%02d",
            DAILY_BATCH_HOUR, DAILY_BATCH_MINUTE,
        )

        while self._running:
            try:
                # 暂停检查
                if self._paused:
                    await asyncio.sleep(5)
                    continue

                # 计算到下一个美东 20:00 的等待秒数
                wait_seconds = self._seconds_until_next_batch()

                if wait_seconds > 0:
                    now_est = datetime.now(pytz.timezone('US/Eastern'))
                    next_run = now_est.replace(
                        hour=DAILY_BATCH_HOUR,
                        minute=DAILY_BATCH_MINUTE,
                        second=0,
                        microsecond=0,
                    )
                    if next_run <= now_est:
                        next_run = next_run.replace(day=next_run.day + 1)  # fallback

                    logger.info(
                        "距离下次批量采集: %.1f 小时 (目标: %s ET)",
                        wait_seconds / 3600,
                        next_run.strftime('%Y-%m-%d %H:%M'),
                    )

                    # 分段 sleep，每 60 秒检查一次 _running / _paused 状态
                    while wait_seconds > 0 and self._running and not self._paused:
                        chunk = min(wait_seconds, 60)
                        await asyncio.sleep(chunk)
                        wait_seconds -= chunk

                    if not self._running:
                        break
                    if self._paused:
                        continue

                # ── 执行每日批量采集 ──
                logger.info("=" * 54)
                logger.info("  DAILY BATCH COLLECT STARTED  %s",
                            datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                logger.info("=" * 54)

                result = await self.run_once_manual_collect()

                logger.info(
                    "每日批量采集完成: %d/%d 成功, 耗时 %.1fs",
                    result.get('success_count', 0),
                    result.get('total_sources', 0),
                    result.get('total_elapsed_sec', 0),
                )

                # 等待下一轮 (24小时后)
                await asyncio.sleep(DAILY_BATCH_INTERVAL_SECONDS)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"每日批量采集异常: {e}", exc_info=True)
                await asyncio.sleep(300)  # 出错等5分钟后重试

    def _seconds_until_next_batch(self) -> float:
        """计算距离下一个美东 20:00 的秒数

        Returns:
            float: 等待秒数 (0 表示应立即执行)
        """
        from datetime import timezone, timedelta

        now_utc = datetime.now(timezone.utc)
        eastern = pytz.timezone('US/Eastern')
        now_est = now_utc.astimezone(eastern)

        # 构造今天的 20:00 ET
        target = now_est.replace(
            hour=DAILY_BATCH_HOUR,
            minute=DAILY_BATCH_MINUTE,
            second=0,
            microsecond=0,
        )

        if target <= now_est:
            # 今天 20:00 已过，取明天 20:00
            target = target.replace(day=target.day + 1)

        delta = target - now_est
        return max(0.0, delta.total_seconds())

    # ================================================================
    # 盘后任务: 做空数据 (yfinance → FINRA) — 已并入每日批量采集
    # ================================================================

    async def run_afterhours_short_volume(self) -> None:
        """盘后获取做空数据 (yfinance → FINRA 降级链路)

        已并入每日批量采集 (`run_once_manual_collect` 的 `_poll_short_once`)。
        保留此方法用于独立调用和向后兼容。
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
