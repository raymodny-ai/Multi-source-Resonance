"""
多源共振监控系统 - 信号引擎模块

该模块负责综合多源信号并生成交易信号，包括：
- 信号权重分配
- 多因子共振判断
- 信号强度评分
- 信号去重与过滤
- 共振矩阵评分系统 (Phase 5)
- 信号触发状态机 (Phase 5)
"""

from signal_engine.resonance_scorer import ResonanceScorer
from signal_engine.signal_trigger import SignalStateMachine, format_alert_message

__all__ = [
    'ResonanceScorer',
    'SignalStateMachine',
    'format_alert_message',
]
