"""
回测引擎 (Backtesting Engine)

基于历史 signal_alerts 数据复盘共振信号的实战表现。
核心流程：
    1. 从 DB 加载历史信号
    2. 获取对应时段的价格数据 (yfinance SPX/SPY)
    3. 模拟入场/离场，计算每笔交易收益
    4. 生成绩效指标和 Markdown 报告

模块：
    - signal_replay: 信号回放，模拟交易
    - performance:  绩效指标计算 (胜率/平均收益/最大回撤/夏普比率)
    - report:       回测报告生成 (Markdown + JSON)
"""

from .signal_replay import SignalReplay
from .performance import PerformanceCalculator
from .report import BacktestReport

__all__ = ['SignalReplay', 'PerformanceCalculator', 'BacktestReport']
