"""
绩效指标计算

提供回测交易记录的标准绩效指标。
指标包括：胜率、平均收益、累计收益、最大回撤、夏普比率、盈亏比。
"""

import math
from typing import Dict, List, Optional

import numpy as np

from .signal_replay import TradeRecord

logger = __import__('logging').getLogger(__name__)


class PerformanceMetrics:
    """回测绩效指标容器"""

    __slots__ = (
        'total_trades', 'win_count', 'lose_count', 'win_rate_pct',
        'avg_return_pct', 'avg_win_pct', 'avg_loss_pct',
        'total_return_pct', 'cumulative_return_pct',
        'max_drawdown_pct', 'sharpe_ratio', 'profit_factor',
        'best_trade_pct', 'worst_trade_pct',
        'level_3_trades', 'level_3_win_rate',
        'level_2_trades', 'level_2_win_rate',
    )

    def __init__(
        self,
        total_trades: int = 0,
        win_count: int = 0,
        lose_count: int = 0,
        win_rate_pct: float = 0.0,
        avg_return_pct: float = 0.0,
        avg_win_pct: float = 0.0,
        avg_loss_pct: float = 0.0,
        total_return_pct: float = 0.0,
        cumulative_return_pct: float = 0.0,
        max_drawdown_pct: float = 0.0,
        sharpe_ratio: float = 0.0,
        profit_factor: float = 0.0,
        best_trade_pct: float = 0.0,
        worst_trade_pct: float = 0.0,
        level_3_trades: int = 0,
        level_3_win_rate: float = 0.0,
        level_2_trades: int = 0,
        level_2_win_rate: float = 0.0,
    ):
        self.total_trades = total_trades
        self.win_count = win_count
        self.lose_count = lose_count
        self.win_rate_pct = round(win_rate_pct, 2)
        self.avg_return_pct = round(avg_return_pct, 2)
        self.avg_win_pct = round(avg_win_pct, 2)
        self.avg_loss_pct = round(avg_loss_pct, 2)
        self.total_return_pct = round(total_return_pct, 2)
        self.cumulative_return_pct = round(cumulative_return_pct, 2)
        self.max_drawdown_pct = round(max_drawdown_pct, 2)
        self.sharpe_ratio = round(sharpe_ratio, 2)
        self.profit_factor = round(profit_factor, 2)
        self.best_trade_pct = round(best_trade_pct, 2)
        self.worst_trade_pct = round(worst_trade_pct, 2)
        self.level_3_trades = level_3_trades
        self.level_3_win_rate = round(level_3_win_rate, 2)
        self.level_2_trades = level_2_trades
        self.level_2_win_rate = round(level_2_win_rate, 2)

    def to_dict(self) -> Dict:
        return {
            'total_trades': self.total_trades,
            'win_count': self.win_count,
            'lose_count': self.lose_count,
            'win_rate_pct': self.win_rate_pct,
            'avg_return_pct': self.avg_return_pct,
            'avg_win_pct': self.avg_win_pct,
            'avg_loss_pct': self.avg_loss_pct,
            'total_return_pct': self.total_return_pct,
            'cumulative_return_pct': self.cumulative_return_pct,
            'max_drawdown_pct': self.max_drawdown_pct,
            'sharpe_ratio': self.sharpe_ratio,
            'profit_factor': self.profit_factor,
            'best_trade_pct': self.best_trade_pct,
            'worst_trade_pct': self.worst_trade_pct,
            'level_3': {
                'trades': self.level_3_trades,
                'win_rate': self.level_3_win_rate,
            },
            'level_2': {
                'trades': self.level_2_trades,
                'win_rate': self.level_2_win_rate,
            },
        }


class PerformanceCalculator:
    """绩效指标计算器

    从交易记录列表中提取标准绩效指标。

    Attributes:
        risk_free_rate: 无风险利率 (年化，小数)
    """

    def __init__(self, risk_free_rate: float = 0.03):
        self.risk_free_rate = risk_free_rate

    def calculate(self, trades: List[TradeRecord]) -> PerformanceMetrics:
        """计算所有绩效指标

        Args:
            trades: 交易记录列表

        Returns:
            PerformanceMetrics 实例
        """
        if not trades:
            return PerformanceMetrics()

        returns = np.array([t.return_pct for t in trades])
        wins = returns[returns > 0]
        losses = returns[returns <= 0]

        total = len(trades)
        win_count = len(wins)

        # 基础指标
        win_rate = win_count / total * 100 if total else 0
        avg_return = float(np.mean(returns)) if total else 0
        avg_win = float(np.mean(wins)) if len(wins) else 0
        avg_loss = float(np.mean(losses)) if len(losses) else 0
        best = float(np.max(returns)) if total else 0
        worst = float(np.min(returns)) if total else 0

        # 累计收益
        cumulative = float(np.prod(1 + returns / 100)) * 100 - 100 if total else 0

        # 等权重组合收益之和
        total_return = float(np.sum(returns))

        # 最大回撤 (基于等权收益序列)
        max_dd = self._calc_max_drawdown(returns)

        # 夏普比率 (日化 → 年化 ∵ 持仓 ~5天)
        sharpe = self._calc_sharpe(returns)

        # 盈亏比
        profit_factor = self._calc_profit_factor(wins, losses)

        # 分级统计
        l3 = self._level_stats(trades, 'LEVEL_3')
        l2 = self._level_stats(trades, 'LEVEL_2')

        return PerformanceMetrics(
            total_trades=total,
            win_count=win_count,
            lose_count=total - win_count,
            win_rate_pct=win_rate,
            avg_return_pct=avg_return,
            avg_win_pct=avg_win,
            avg_loss_pct=avg_loss,
            total_return_pct=total_return,
            cumulative_return_pct=cumulative,
            max_drawdown_pct=max_dd,
            sharpe_ratio=sharpe,
            profit_factor=profit_factor,
            best_trade_pct=best,
            worst_trade_pct=worst,
            level_3_trades=l3['trades'],
            level_3_win_rate=l3['win_rate'],
            level_2_trades=l2['trades'],
            level_2_win_rate=l2['win_rate'],
        )

    @staticmethod
    def _calc_max_drawdown(returns: np.ndarray) -> float:
        """计算最大回撤 (%)"""
        if len(returns) == 0:
            return 0.0
        cumulative = np.cumprod(1 + returns / 100)
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = (cumulative - running_max) / running_max * 100
        return float(np.min(drawdowns))

    def _calc_sharpe(self, returns: np.ndarray) -> float:
        """计算年化夏普比率

        使用简化算法：mean(daily_return) / std(daily_return) * sqrt(252)
        由于每笔交易持有 ~hold_days 天，这里使用交易级别收益。
        """
        if len(returns) < 2:
            return 0.0
        excess = returns / 100  # 转为小数
        avg_excess = np.mean(excess) - self.risk_free_rate / 252 * 5  # 约 5 天无风险
        std_excess = np.std(excess, ddof=1)
        if std_excess == 0:
            return 0.0
        # 交易级别夏普 → 近似年化 (假设每年 50 笔交易)
        return float(avg_excess / std_excess * math.sqrt(50))

    @staticmethod
    def _calc_profit_factor(wins: np.ndarray, losses: np.ndarray) -> float:
        """计算盈亏比 (profit factor)"""
        total_gain = float(np.sum(wins)) if len(wins) else 0
        total_loss = abs(float(np.sum(losses))) if len(losses) else 0
        if total_loss == 0:
            return float('inf') if total_gain > 0 else 0.0
        return round(total_gain / total_loss, 2)

    @staticmethod
    def _level_stats(trades: List[TradeRecord], level: str) -> Dict:
        """计算指定等级的统计"""
        filtered = [t for t in trades if t.alert_level == level]
        if not filtered:
            return {'trades': 0, 'win_rate': 0.0}
        wins = sum(1 for t in filtered if t.is_win)
        return {
            'trades': len(filtered),
            'win_rate': round(wins / len(filtered) * 100, 2),
        }
