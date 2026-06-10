"""
多源共振监控系统 - 实时数据流模块 (Push 架构)

该模块实现了从 APScheduler 定时轮询 (Pull) 到 WebSocket/EventBus
实时推送 (Push) 的架构升级。

核心组件:
    EventBus: 异步发布/订阅事件总线
    HyperliquidStream: Hyperliquid DEX WebSocket 连接器
    SignalPipeline: 事件驱动的信号评估管线
    RESTPollScheduler: 非WS数据源的轻量轮询调度
    StreamEngine: 统一流引擎 (替代 MainScheduler)

使用示例:
    from data_stream.stream_engine import StreamEngine, create_and_start_engine

    engine = StreamEngine()
    engine.start()
"""

from data_stream.event_bus import EventBus, Topics, get_event_bus
from data_stream.hyperliquid_stream import HyperliquidStream
from data_stream.signal_pipeline import SignalPipeline
from data_stream.rest_poll_scheduler import RESTPollScheduler
from data_stream.stream_engine import StreamEngine

__all__ = [
    'EventBus',
    'Topics',
    'get_event_bus',
    'HyperliquidStream',
    'SignalPipeline',
    'RESTPollScheduler',
    'StreamEngine',
]
