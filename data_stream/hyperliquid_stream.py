"""
多源共振监控系统 - Hyperliquid DEX WebSocket 实时数据连接器

通过 Hyperliquid WebSocket API 持续接收 BTC 永续合约的实时
资金费率、持仓量和标记价格数据。收到数据后即时发布到 EventBus。

API: wss://api.hyperliquid.xyz/ws
订阅: {"method": "subscribe", "subscription": {"type": "activeAssetData", "coin": "BTC"}}
响应字段: funding, openInterest, markPx, premium, dayNtlVlm, oraclePx 等

特性:
- 自动重连 (指数退避: 1s → 60s max)
- Ping/Pong 保活 (每 30s)
- 数据到达 → EventBus.publish() 即时推送
- 优雅关闭 (取消订阅 + 断开连接)
"""

import asyncio
import json
from typing import Optional, Dict, Any
from datetime import datetime

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from utils.logger import getLogger
from data_stream.event_bus import EventBus, Topics

logger = getLogger('hyperliquid_stream')


class HyperliquidStream:
    """Hyperliquid DEX WebSocket 实时数据连接器

    建立到 Hyperliquid 的 WebSocket 长连接，订阅 BTC activeAssetData，
    实时推送 funding rate / OI / mark price 到 EventBus。

    使用示例:
        bus = EventBus()
        stream = HyperliquidStream(bus)
        await stream.start()
        # ... 系统运行 ...
        await stream.shutdown()
    """

    WS_URL = "wss://api.hyperliquid.xyz/ws"
    PING_INTERVAL = 30          # 秒
    PING_TIMEOUT = 10           # 秒
    RECONNECT_MIN_DELAY = 1     # 秒
    RECONNECT_MAX_DELAY = 60    # 秒
    RECONNECT_MULTIPLIER = 2    # 指数退避乘数

    def __init__(
        self,
        event_bus: EventBus,
        coin: str = "BTC",
        ws_url: Optional[str] = None,
    ):
        """初始化 Hyperliquid WebSocket 连接器

        Args:
            event_bus: 全局事件总线实例
            coin: 监控币种, 默认 "BTC"
            ws_url: WebSocket URL, 默认 "wss://api.hyperliquid.xyz/ws"
        """
        self._bus = event_bus
        self._coin = coin
        self._ws_url = ws_url or self.WS_URL

        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running: bool = False
        self._reconnect_task: Optional[asyncio.Task] = None
        self._ping_task: Optional[asyncio.Task] = None
        self._listen_task: Optional[asyncio.Task] = None

        logger.info(f"HyperliquidStream 初始化: coin={coin}, url={self._ws_url}")

    @property
    def is_connected(self) -> bool:
        """WebSocket 是否已连接"""
        if self._ws is None:
            return False
        try:
            return not self._ws.closed
        except AttributeError:
            return self._ws.state == 1  # State.OPEN

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """启动 WebSocket 连接

        建立连接 → 订阅 activeAssetData → 启动消息监听循环。
        连接断开时自动重连。
        """
        if self._running:
            return

        self._running = True
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())
        logger.info("HyperliquidStream 已启动")

    async def shutdown(self) -> None:
        """关闭 WebSocket 连接

        取消订阅 → 发送 pong → 关闭连接 → 取消所有任务。
        """
        if not self._running:
            return

        self._running = False
        logger.info("正在关闭 HyperliquidStream...")

        # 取消重连循环
        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None

        # 取消 ping 任务
        if self._ping_task:
            self._ping_task.cancel()
            self._ping_task = None

        # 取消 listen 任务
        if self._listen_task:
            self._listen_task.cancel()
            self._listen_task = None

        # 关闭 WebSocket 连接
        await self._disconnect()

        logger.info("HyperliquidStream 已关闭")

    async def _connect(self) -> bool:
        """建立 WebSocket 连接并订阅

        Returns:
            bool: 是否连接成功
        """
        try:
            logger.info(f"正在连接 Hyperliquid WS: {self._ws_url}")
            self._ws = await websockets.connect(
                self._ws_url,
                ping_interval=None,     # 手动管理 ping
                ping_timeout=None,
                close_timeout=5,
                open_timeout=10,
            )

            # 订阅 activeAssetData
            sub_msg = {
                "method": "subscribe",
                "subscription": {
                    "type": "activeAssetData",
                    "coin": self._coin,
                },
            }
            await self._ws.send(json.dumps(sub_msg))
            logger.info(f"Hyperliquid WS 已连接并订阅 {self._coin} activeAssetData")

            # 启动 ping 和 listen 任务
            self._ping_task = asyncio.create_task(self._ping_loop())
            self._listen_task = asyncio.create_task(self._listen_loop())

            return True

        except (OSError, WebSocketException, asyncio.TimeoutError) as e:
            logger.error(f"Hyperliquid WS 连接失败: {e}")
            self._ws = None
            return False

    async def _disconnect(self) -> None:
        """断开 WebSocket 连接"""
        if self._ws and self.is_connected:
            try:
                # 发送取消订阅 (可选，大多数 WS 服务器会自动清理)
                unsub_msg = {
                    "method": "unsubscribe",
                    "subscription": {
                        "type": "activeAssetData",
                        "coin": self._coin,
                    },
                }
                await asyncio.wait_for(
                    self._ws.send(json.dumps(unsub_msg)), timeout=2
                )
            except Exception:
                pass

            try:
                await asyncio.wait_for(self._ws.close(), timeout=3)
            except Exception:
                pass

        self._ws = None

    async def _reconnect_loop(self) -> None:
        """自动重连循环 (指数退避)

        当连接断开时，以指数退避策略重新连接。
        """
        delay = self.RECONNECT_MIN_DELAY

        while self._running:
            if self.is_connected:
                await asyncio.sleep(1)
                continue

            logger.info(f"尝试重连 Hyperliquid WS (delay={delay}s)...")
            success = await self._connect()

            if success:
                delay = self.RECONNECT_MIN_DELAY  # 重置延迟
            else:
                logger.warning(f"重连失败, {delay}s 后重试")
                await asyncio.sleep(delay)
                delay = min(delay * self.RECONNECT_MULTIPLIER, self.RECONNECT_MAX_DELAY)

    async def _ping_loop(self) -> None:
        """Ping/Pong 保活循环

        每 PING_INTERVAL 秒发送一次 ping，超时则断开触发重连。
        """
        try:
            while self._running and self.is_connected:
                await asyncio.sleep(self.PING_INTERVAL)

                if not self.is_connected:
                    break

                try:
                    pong = await asyncio.wait_for(
                        self._ws.ping(), timeout=self.PING_TIMEOUT
                    )
                    await pong
                except (asyncio.TimeoutError, ConnectionClosed):
                    logger.warning("Hyperliquid WS ping 超时，断开连接")
                    await self._disconnect()
                    break

        except asyncio.CancelledError:
            pass

    async def _listen_loop(self) -> None:
        """消息监听循环

        接收 WebSocket 消息 → 解析 → 发布到 EventBus。
        """
        try:
            while self._running and self.is_connected:
                try:
                    raw = await asyncio.wait_for(self._ws.recv(), timeout=60)
                except asyncio.TimeoutError:
                    continue
                except ConnectionClosed as e:
                    logger.warning(f"Hyperliquid WS 连接关闭: code={e.code}")
                    break

                try:
                    self._handle_message(raw)
                except Exception as e:
                    logger.error(f"处理 Hyperliquid WS 消息失败: {e}", exc_info=True)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Hyperliquid WS listen 循环异常: {e}", exc_info=True)
        finally:
            await self._disconnect()

    def _handle_message(self, raw: str) -> None:
        """解析并分发 WebSocket 消息

        提取 funding / openInterest / markPx / premium，
        换算 OI USD 价值，发布到 EventBus。

        Args:
            raw: 原始 JSON 消息字符串
        """
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug(f"无法解析 WS 消息 (非JSON): {raw[:100]}")
            return

        # 检查 channel 类型
        channel = msg.get("channel")
        if channel != "activeAssetData":
            # 可能是 subscription 确认消息或其他
            if channel == "subscriptionResponse":
                logger.info(f"订阅确认: {msg}")
            return

        data = msg.get("data", {})
        if not data:
            return

        coin = data.get("coin", "")
        if coin != self._coin:
            return

        # 提取关键字段
        funding_str = data.get("funding", "0")
        oi_base_str = data.get("openInterest", "0")
        mark_px_str = data.get("markPx", "0")
        premium_str = data.get("premium", "0")

        try:
            funding_rate = float(funding_str)
            oi_base = float(oi_base_str)
            mark_px = float(mark_px_str)
            oi_usd = oi_base * mark_px
        except (ValueError, TypeError):
            logger.error(f"无法解析 Hyperliquid WS 数值: {data}")
            return

        # 构建标准事件数据
        now = datetime.now()
        funding_event = {"rate": funding_rate, "coin": coin, "timestamp": now}
        oi_event = {
            "oi": oi_usd,
            "oi_base": oi_base,
            "mark_price": mark_px,
            "coin": coin,
            "timestamp": now,
        }

        # 异步发布到 EventBus (使用 create_task 避免阻塞)
        asyncio.create_task(
            self._bus.publish(Topics.CRYPTO_FUNDING_RATE, funding_event)
        )
        asyncio.create_task(
            self._bus.publish(Topics.CRYPTO_OPEN_INTEREST, oi_event)
        )

        logger.debug(
            f"Hype WS: funding={funding_rate*100:.4f}%, "
            f"OI=${oi_usd:,.0f}, mark=${mark_px:.2f}"
        )
