"""
多源共振监控系统 - 统一实时流引擎 (Push 架构入口)

替代原有的 MainScheduler (APScheduler Pull 模式),
统一编排 WebSocket 长连接和 REST 轮询任务。

架构:
    StreamEngine
      ├─ EventBus (全局 pub/sub)
      ├─ HyperliquidStream (WebSocket → crypto.funding_rate / crypto.open_interest)
      ├─ RESTPollScheduler (每日 ET 22:00 批量采集 → gex/vix/axlfi/dbmf/crypto/short)
      ├─ SignalPipeline (订阅 EventBus → 评分 → 告警)
      └─ 盘后任务 (短卖比 yfinance→FINRA 降级, 已并入每日批量)

使用示例:
    from data_stream.stream_engine import StreamEngine

    engine = StreamEngine()
    engine.start()
"""

import asyncio
import signal
from typing import Optional

from utils.logger import getLogger
from data_stream.event_bus import EventBus, get_event_bus
from data_stream.hyperliquid_stream import HyperliquidStream
from data_stream.signal_pipeline import SignalPipeline
from data_stream.rest_poll_scheduler import RESTPollScheduler

logger = getLogger('stream_engine')


class StreamEngine:
    """统一实时流引擎

    管理所有 Push 架构组件: EventBus → HyperliquidStream (WS) +
    RESTPollScheduler → SignalPipeline。替代 MainScheduler 的
    APScheduler 定时任务模型。

    RESTPollScheduler 现为每日单次批量采集模式 (美东 22:00)，
    不再进行盘中高频轮询。

    Attributes:
        event_bus: 全局事件总线
        hyperliquid_stream: Hyperliquid DEX WebSocket 连接器
        rest_scheduler: REST 轮询调度器
        signal_pipeline: 事件驱动信号管线
    """

    def __init__(self):
        """初始化流引擎和所有子组件"""
        self.event_bus: EventBus = get_event_bus()
        self.hyperliquid_stream = HyperliquidStream(self.event_bus, coin='BTC')
        self.rest_scheduler = RESTPollScheduler(self.event_bus)
        self.signal_pipeline = SignalPipeline(self.event_bus)

        self._running = False
        logger.info("StreamEngine 初始化完成 (Push 架构)")

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        """启动流引擎 (阻塞)

        启动顺序: EventBus → SignalPipeline → RESTPollScheduler → HyperliquidStream
        然后进入事件循环等待中断信号。
        """
        if self._running:
            return

        self._running = True

        try:
            asyncio.run(self._run())
        except KeyboardInterrupt:
            logger.info("收到中断信号")
        finally:
            self._running = False

    async def start_async(self) -> None:
        """启动流引擎 (异步, 非阻塞)

        适合嵌入已有 asyncio 事件循环的场景。
        """
        if self._running:
            return

        self._running = True
        await self._run()

    async def shutdown(self) -> None:
        """优雅关闭流引擎"""
        if not self._running:
            return

        logger.info("正在关闭 StreamEngine...")
        self._running = False

        # 按启动的逆序关闭
        await self.hyperliquid_stream.shutdown()
        await self.rest_scheduler.shutdown()
        await self.signal_pipeline.shutdown()
        await self.event_bus.shutdown()

        logger.info("StreamEngine 已完全关闭")

    async def _run(self) -> None:
        """主运行协程"""
        logger.info("=" * 60)
        logger.info("🚀 多源共振监控系统 (Push 实时流架构) 正在启动")
        logger.info("=" * 60)

        # 1. 启动 EventBus 分发器
        await self.event_bus.start()
        logger.info("✓ EventBus 分发器已启动")

        # 2. 启动 SignalPipeline (订阅 EventBus)
        await self.signal_pipeline.start()
        logger.info("✓ SignalPipeline 已启动 (监听事件)")

        # 3. 启动 REST 轮询调度器 (每日 ET 22:00 批量采集)
        await self.rest_scheduler.start()
        logger.info("✓ RESTPollScheduler 已启动 (每日美东 22:00 批量采集)")

        # 4. 启动 Hyperliquid WebSocket 连接
        await self.hyperliquid_stream.start()
        logger.info("✓ HyperliquidStream 已启动 (BTC 实时数据)")

        logger.info("-" * 60)
        logger.info("所有组件已就绪, 实时监控中...")
        logger.info("按 Ctrl+C 停止")
        logger.info("-" * 60)

        # 等待关闭信号
        try:
            while self._running:
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()


def create_and_start_engine() -> None:
    """便捷函数: 创建并启动流引擎

    直接运行即可启动 Push 架构的实时监控系统。

    Usage:
        from data_stream.stream_engine import create_and_start_engine
        create_and_start_engine()
    """
    engine = StreamEngine()
    engine.start()
