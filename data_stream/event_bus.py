"""
多源共振监控系统 - 异步事件总线

Push 架构的核心基础设施。所有数据源（WebSocket、REST）通过 EventBus
发布数据更新事件，SignalPipeline 订阅事件并触发信号评估。

设计:
- 基于 asyncio.Queue 实现异步 pub/sub
- Topic-based 路由: crypto.* / short_volume.* / gex.* / vix.* 等
- 线程安全，支持异步回调

Topics 常量:
    crypto.funding_rate  - 资金费率更新 (float)
    crypto.open_interest - 持仓量更新 (dict: oi, timestamp)
    short_volume.spy     - SPY 短卖比更新 (dict: ratio, date)
    gex.update           - GEX/DIX 更新 (dict: gex, dix, price)
    vix.term_structure   - VIX 期限结构更新 (dict: ratio, state)
    dbmf.recovery        - DBMF 收复信号 (bool)
    darkpool.axlfi       - AXLFI 暗盘净头寸 (dict)
    data.source_error    - 数据源异常 (dict: source, error)
    data.all_ready       - 全维度就绪 (触发共振评分)
"""

import asyncio
from typing import Callable, Coroutine, Dict, List, Any, Set
from utils.logger import getLogger

logger = getLogger('event_bus')


# ============================================================
# Topic 常量定义
# ============================================================

class Topics:
    """预定义事件主题

    所有数据发布和订阅统一使用这些常量，避免字符串硬编码。
    """

    # Crypto 维度
    CRYPTO_FUNDING_RATE = "crypto.funding_rate"
    CRYPTO_OPEN_INTEREST = "crypto.open_interest"
    CRYPTO_LIQUIDATION = "crypto.liquidation"
    CRYPTO_ALL_READY = "crypto.all_ready"

    # Short Volume 维度
    SHORT_VOLUME_SPY = "short_volume.spy"
    SHORT_VOLUME_QQQ = "short_volume.qqq"

    # GEX / DIX 维度
    GEX_UPDATE = "gex.update"

    # GEXMetrix Gamma Dashboard 维度
    GEXMETRIX_SNAPSHOT = "gexmetrix.snapshot"

    # VIX 维度
    VIX_TERM_STRUCTURE = "vix.term_structure"

    # DBMF 维度
    DBMF_RECOVERY = "dbmf.recovery"

    # Dark Pool 维度 (AXLFI)
    DARKPOOL_AXLFI = "darkpool.axlfi"
    DARKPOOL_PREPROCESSED = "darkpool.preprocessed"  # EMA快慢线/零轴穿越/动量反转

    # 系统级事件
    DATA_SOURCE_ERROR = "data.source_error"
    DATA_SOURCE_RECOVERED = "data.source_recovered"
    ALL_DIMENSIONS_READY = "data.all_ready"
    SYSTEM_SHUTDOWN = "system.shutdown"


# ============================================================
# EventBus 实现
# ============================================================

class EventBus:
    """异步事件总线 (Pub/Sub)

    所有数据流和信号管线通过 EventBus 解耦。
    数据源发布事件 → EventBus 路由 → Pipeline 订阅处理。

    使用示例:
        bus = EventBus()

        # 订阅
        await bus.subscribe(Topics.CRYPTO_FUNDING_RATE, on_funding_update)

        # 发布
        await bus.publish(Topics.CRYPTO_FUNDING_RATE, -0.000125)

        # 取消订阅
        await bus.unsubscribe(Topics.CRYPTO_FUNDING_RATE, on_funding_update)
    """

    def __init__(self):
        """初始化事件总线"""
        self._subscribers: Dict[str, Set[Callable]] = {}
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self._running: bool = False
        self._dispatcher_task: asyncio.Task = None
        logger.info("EventBus 初始化完成")

    @property
    def is_running(self) -> bool:
        return self._running

    async def subscribe(self, topic: str, callback: Callable) -> None:
        """订阅指定 topic

        Args:
            topic: 事件主题 (使用 Topics 常量)
            callback: 异步或同步回调函数，接收 data 参数
        """
        if topic not in self._subscribers:
            self._subscribers[topic] = set()

        self._subscribers[topic].add(callback)
        logger.debug(f"订阅 topic='{topic}', 当前订阅者数={len(self._subscribers[topic])}")

    async def unsubscribe(self, topic: str, callback: Callable) -> None:
        """取消订阅

        Args:
            topic: 事件主题
            callback: 要移除的回调函数
        """
        if topic in self._subscribers:
            self._subscribers[topic].discard(callback)
            if not self._subscribers[topic]:
                del self._subscribers[topic]
            logger.debug(f"取消订阅 topic='{topic}'")

    async def publish(self, topic: str, data: Any = None) -> None:
        """发布事件到指定 topic

        事件先入队列，由 dispatcher 异步分发。

        Args:
            topic: 事件主题
            data: 事件负载数据
        """
        if not self._running:
            logger.warning(f"EventBus 未运行，丢弃事件: topic='{topic}'")
            return

        await self._queue.put({
            'topic': topic,
            'data': data,
        })

    async def start(self) -> None:
        """启动事件分发器"""
        if self._running:
            return

        self._running = True
        self._dispatcher_task = asyncio.create_task(self._dispatch_loop())
        logger.info("EventBus 分发器已启动")

    async def shutdown(self) -> None:
        """关闭事件总线"""
        if not self._running:
            return

        self._running = False

        # 发送 shutdown 信号
        try:
            await self._queue.put({'topic': Topics.SYSTEM_SHUTDOWN, 'data': None})
        except Exception:
            pass

        if self._dispatcher_task:
            self._dispatcher_task.cancel()
            try:
                await self._dispatcher_task
            except asyncio.CancelledError:
                pass

        logger.info("EventBus 已关闭")

    async def _dispatch_loop(self) -> None:
        """事件分发主循环

        从队列中取出事件，分发给所有订阅者。
        """
        logger.info("EventBus 分发循环已启动")

        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            topic = event['topic']
            data = event['data']

            if topic == Topics.SYSTEM_SHUTDOWN:
                break

            subscribers = self._subscribers.get(topic, set())
            if not subscribers:
                logger.debug(f"topic='{topic}' 无订阅者，丢弃")
                continue

            # 并发分发到所有订阅者
            tasks = []
            for callback in list(subscribers):
                tasks.append(self._invoke_callback(callback, topic, data))

            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for r in results:
                    if isinstance(r, Exception):
                        logger.error(f"事件回调异常: {r}")

        logger.info("EventBus 分发循环已退出")

    async def _invoke_callback(self, callback: Callable, topic: str, data: Any) -> None:
        """安全调用回调函数

        支持同步和异步回调。
        """
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(data)
            else:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, callback, data)
        except Exception as e:
            logger.error(f"回调执行失败 topic='{topic}': {e}", exc_info=True)
            raise

    def get_topic_stats(self) -> Dict[str, int]:
        """获取各 topic 的订阅者数量 (调试用)

        Returns:
            dict: {topic: subscriber_count}
        """
        return {topic: len(callbacks) for topic, callbacks in self._subscribers.items()}


# ============================================================
# 全局单例
# ============================================================

# 全局 EventBus 实例，供整个系统共用
_event_bus: EventBus = None


def get_event_bus() -> EventBus:
    """获取全局 EventBus 单例

    Returns:
        EventBus: 全局事件总线实例
    """
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def reset_event_bus() -> None:
    """重置全局 EventBus (测试用)"""
    global _event_bus
    _event_bus = None
