"""
回测报告生成

将回测结果格式化为 Markdown 报告和 JSON 摘要。
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .performance import PerformanceCalculator, PerformanceMetrics
from .signal_replay import TradeRecord

logger = logging.getLogger(__name__)


class BacktestReport:
    """回测报告生成器

    Attributes:
        output_dir: 报告输出目录
    """

    def __init__(self, output_dir: str = './reports'):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_markdown(
        self,
        trades: List[TradeRecord],
        metrics: PerformanceMetrics,
        symbol: str = 'SPY',
        hold_days: int = 5,
    ) -> str:
        """生成 Markdown 格式回测报告

        Args:
            trades: 交易记录
            metrics: 绩效指标
            symbol: 标的代码
            hold_days: 持仓天数

        Returns:
            Markdown 文本
        """
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 定级
        grade = self._grade_metrics(metrics)

        md = f"""# 多源共振信号回测报告

**生成时间**: {now}
**回测标的**: {symbol}
**持仓周期**: {hold_days} 个交易日
**交易总数**: {metrics.total_trades}

---

## 📊 绩效总览

| 指标 | 数值 | 评级 |
|------|------|------|
| 总交易数 | {metrics.total_trades} | — |
| 胜率 | {metrics.win_rate_pct}% | {'✅' if metrics.win_rate_pct >= 50 else '⚠️'} |
| 平均收益 | {metrics.avg_return_pct:+.2f}% | {'✅' if metrics.avg_return_pct > 0 else '❌'} |
| 平均盈利 | {metrics.avg_win_pct:+.2f}% | — |
| 平均亏损 | {metrics.avg_loss_pct:+.2f}% | — |
| 累计收益 | {metrics.cumulative_return_pct:+.2f}% | {'✅' if metrics.cumulative_return_pct > 0 else '❌'} |
| 最大回撤 | {metrics.max_drawdown_pct:.2f}% | {'✅' if metrics.max_drawdown_pct > -20 else '⚠️'} |
| 夏普比率 | {metrics.sharpe_ratio:.2f} | {'✅' if metrics.sharpe_ratio > 0.5 else '⚠️'} |
| 盈亏比 | {metrics.profit_factor:.2f} | {'✅' if metrics.profit_factor > 1.0 else '❌'} |
| 最佳交易 | {metrics.best_trade_pct:+.2f}% | — |
| 最差交易 | {metrics.worst_trade_pct:+.2f}% | — |

---

## 🚨 信号分级表现

| 级别 | 交易数 | 胜率 | 评价 |
|------|--------|------|------|
| LEVEL_3 (≥3.5分) | {metrics.level_3_trades} | {metrics.level_3_win_rate}% | {'⭐ 高置信度' if metrics.level_3_win_rate >= 60 else '📉 待优化'} |
| LEVEL_2 (≥3.0分) | {metrics.level_2_trades} | {metrics.level_2_win_rate}% | {'👍 有效' if metrics.level_2_win_rate >= 50 else '📉 待优化'} |

---

## 📈 综合评定

**{grade}**

{self._generate_commentary(metrics)}

---

## 📋 交易明细

| # | 时间 | 级别 | 得分 | 入场价 | 离场价 | 收益 | 胜/负 |
|---|------|------|------|--------|--------|------|-------|
"""
        for i, t in enumerate(trades, 1):
            icon = '✅' if t.is_win else '❌'
            signal_time = t.signal_time.strftime('%Y-%m-%d') if hasattr(t.signal_time, 'strftime') else str(t.signal_time)[:10]
            entry_date = t.entry_date.strftime('%Y-%m-%d') if hasattr(t.entry_date, 'strftime') else str(t.entry_date)[:10]
            exit_date = t.exit_date.strftime('%Y-%m-%d') if hasattr(t.exit_date, 'strftime') else str(t.exit_date)[:10]
            md += f"| {i} | {signal_time} | {t.alert_level} | {t.total_score:.1f} | {t.entry_price:.2f} | {t.exit_price:.2f} | {t.return_pct:+.2f}% | {icon} |\n"

        return md

    def generate_json(
        self,
        trades: List[TradeRecord],
        metrics: PerformanceMetrics,
        symbol: str = 'SPY',
        hold_days: int = 5,
    ) -> Dict:
        """生成 JSON 格式摘要

        Returns:
            结构化字典
        """
        return {
            'generated_at': datetime.now().isoformat(),
            'parameters': {
                'symbol': symbol,
                'hold_days': hold_days,
            },
            'metrics': metrics.to_dict(),
            'trades': [t.to_dict() for t in trades],
        }

    def save_report(
        self,
        trades: List[TradeRecord],
        metrics: PerformanceMetrics,
        symbol: str = 'SPY',
        hold_days: int = 5,
        filename_prefix: str = 'backtest',
    ) -> Dict[str, str]:
        """保存 Markdown + JSON 报告到文件

        Returns:
            {'md_path': str, 'json_path': str}
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        md_path = self.output_dir / f'{filename_prefix}_{timestamp}.md'
        md_text = self.generate_markdown(trades, metrics, symbol, hold_days)
        md_path.write_text(md_text, encoding='utf-8')

        json_path = self.output_dir / f'{filename_prefix}_{timestamp}.json'
        json_data = self.generate_json(trades, metrics, symbol, hold_days)
        json_path.write_text(json.dumps(json_data, indent=2, ensure_ascii=False), encoding='utf-8')

        logger.info(f"报告已保存: {md_path}, {json_path}")
        return {'md_path': str(md_path), 'json_path': str(json_path)}

    @staticmethod
    def _grade_metrics(metrics: PerformanceMetrics) -> str:
        """综合评级"""
        score = 0
        if metrics.win_rate_pct >= 50:
            score += 1
        if metrics.avg_return_pct > 0:
            score += 1
        if metrics.sharpe_ratio > 0.5:
            score += 1
        if metrics.profit_factor > 1.0:
            score += 1
        if metrics.max_drawdown_pct > -20:
            score += 1

        if score >= 4:
            return '🟢 信号有效 — 共振评分具备正向预测能力'
        elif score >= 2:
            return '🟡 信号中等 — 部分维度有效，建议结合风控'
        else:
            return '🔴 信号偏弱 — 回测表现不佳，需审查评分权重'

    @staticmethod
    def _generate_commentary(metrics: PerformanceMetrics) -> str:
        """生成文本评语"""
        parts = []

        if metrics.total_trades < 5:
            parts.append(f"- ⚠️ 样本量仅 {metrics.total_trades} 笔，统计显著性不足")
        else:
            parts.append(f"- 基于 {metrics.total_trades} 笔交易的回测结果")

        if metrics.win_rate_pct >= 60:
            parts.append(f"- 胜率 {metrics.win_rate_pct}% 表现优秀，LEVEL_3 信号可靠性高")
        elif metrics.win_rate_pct >= 50:
            parts.append(f"- 胜率 {metrics.win_rate_pct}% 处于盈亏平衡线上方，勉强有效")
        else:
            parts.append(f"- 胜率 {metrics.win_rate_pct}% 偏低，建议提高触发阈值或增加确认条件")

        if metrics.sharpe_ratio > 1.0:
            parts.append(f"- 夏普比率 {metrics.sharpe_ratio:.2f}，风险调整后收益优异")
        elif metrics.sharpe_ratio > 0:
            parts.append(f"- 夏普比率 {metrics.sharpe_ratio:.2f}，风险调整后存在正收益")
        else:
            parts.append(f"- 夏普比率 {metrics.sharpe_ratio:.2f} 为负，策略风险调整后不产生价值")

        if metrics.level_3_trades > 0 and metrics.level_3_win_rate > metrics.level_2_win_rate:
            parts.append("- LEVEL_3 信号胜率高于 LEVEL_2，评分机制有效区分信号质量")

        return '\n'.join(parts)
