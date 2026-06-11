"""
回测引擎测试

测试信号回放、绩效计算和报告生成。
"""

import unittest
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytz

# 添加项目根目录
sys.path.insert(0, str(Path(__file__).parent.parent))

# 不依赖真实 DB 和 yfinance 的纯逻辑测试
from backtest_engine.signal_replay import TradeRecord, SignalReplay
from backtest_engine.performance import PerformanceCalculator, PerformanceMetrics
from backtest_engine.report import BacktestReport


class TestTradeRecord(unittest.TestCase):
    """TradeRecord 数据类测试"""

    def setUp(self):
        self.est = pytz.timezone('US/Eastern')
        self.now = datetime.now(self.est)

    def test_winning_trade(self):
        t = TradeRecord(
            signal_id=1,
            signal_time=self.now,
            alert_level='LEVEL_3',
            total_score=4.0,
            entry_date=self.now,
            entry_price=400.0,
            exit_date=self.now + timedelta(days=5),
            exit_price=420.0,
            hold_days=5,
        )
        self.assertTrue(t.is_win)
        self.assertAlmostEqual(t.return_pct, 5.0)

    def test_losing_trade(self):
        t = TradeRecord(
            signal_id=2,
            signal_time=self.now,
            alert_level='LEVEL_3',
            total_score=3.5,
            entry_date=self.now,
            entry_price=400.0,
            exit_price=380.0,
            exit_date=self.now + timedelta(days=5),
            hold_days=5,
        )
        self.assertFalse(t.is_win)
        self.assertAlmostEqual(t.return_pct, -5.0)

    def test_to_dict(self):
        t = TradeRecord(
            signal_id=1,
            signal_time=self.now,
            alert_level='LEVEL_3',
            total_score=4.0,
            entry_date=self.now,
            entry_price=400.0,
            exit_date=self.now + timedelta(days=5),
            exit_price=420.0,
            hold_days=5,
        )
        d = t.to_dict()
        self.assertEqual(d['signal_id'], 1)
        self.assertEqual(d['alert_level'], 'LEVEL_3')
        self.assertEqual(d['return_pct'], 5.0)
        self.assertTrue(d['is_win'])


class TestPerformanceCalculator(unittest.TestCase):
    """绩效计算器测试"""

    def setUp(self):
        self.calc = PerformanceCalculator()
        self.est = pytz.timezone('US/Eastern')
        self.now = datetime.now(self.est)

    def _make_trade(self, sid, level, score, entry, exit_p, hold=5):
        return TradeRecord(
            signal_id=sid,
            signal_time=self.now + timedelta(days=sid),
            alert_level=level,
            total_score=score,
            entry_date=self.now + timedelta(days=sid),
            entry_price=entry,
            exit_date=self.now + timedelta(days=sid + hold),
            exit_price=exit_p,
            hold_days=hold,
        )

    def test_empty_trades(self):
        m = self.calc.calculate([])
        self.assertEqual(m.total_trades, 0)
        self.assertEqual(m.win_rate_pct, 0.0)

    def test_all_wins(self):
        trades = [
            self._make_trade(1, 'LEVEL_3', 4.0, 100, 110),
            self._make_trade(2, 'LEVEL_3', 4.5, 100, 105),
            self._make_trade(3, 'LEVEL_3', 3.8, 100, 102),
        ]
        m = self.calc.calculate(trades)
        self.assertEqual(m.total_trades, 3)
        self.assertEqual(m.win_count, 3)
        self.assertAlmostEqual(m.win_rate_pct, 100.0)

    def test_mixed_trades(self):
        trades = [
            self._make_trade(1, 'LEVEL_3', 4.0, 100, 110),  # +10%
            self._make_trade(2, 'LEVEL_3', 4.5, 100, 95),   # -5%
            self._make_trade(3, 'LEVEL_2', 3.2, 100, 108),  # +8%
            self._make_trade(4, 'LEVEL_2', 3.0, 100, 92),   # -8%
        ]
        m = self.calc.calculate(trades)
        self.assertEqual(m.total_trades, 4)
        self.assertEqual(m.win_count, 2)
        self.assertAlmostEqual(m.win_rate_pct, 50.0)
        self.assertGreater(m.avg_return_pct, 0)  # 总体正收益

    def test_level_stats(self):
        trades = [
            self._make_trade(1, 'LEVEL_3', 4.0, 100, 110),
            self._make_trade(2, 'LEVEL_3', 4.2, 100, 108),
            self._make_trade(3, 'LEVEL_3', 3.9, 100, 95),   # 唯一亏损
            self._make_trade(4, 'LEVEL_2', 3.2, 100, 102),
            self._make_trade(5, 'LEVEL_2', 3.1, 100, 98),
        ]
        m = self.calc.calculate(trades)
        self.assertEqual(m.level_3_trades, 3)
        self.assertAlmostEqual(m.level_3_win_rate, 66.67, delta=0.1)
        self.assertEqual(m.level_2_trades, 2)
        self.assertAlmostEqual(m.level_2_win_rate, 50.0)

    def test_max_drawdown(self):
        # 模拟净值: 1.0 → 1.10 → 0.90 → 1.05
        trades = [
            self._make_trade(1, 'LEVEL_3', 4.0, 100, 110),  # +10%
            self._make_trade(2, 'LEVEL_3', 4.5, 100, 90),   # -10%
            self._make_trade(3, 'LEVEL_3', 3.8, 100, 105),  # +5%
        ]
        m = self.calc.calculate(trades)
        # 最大回撤应在 -10% ~ -18% 之间
        self.assertLess(m.max_drawdown_pct, 0)

    def test_profit_factor(self):
        trades = [
            self._make_trade(1, 'LEVEL_3', 4.0, 100, 110),  # +10
            self._make_trade(2, 'LEVEL_3', 4.5, 100, 108),  # +8
            self._make_trade(3, 'LEVEL_3', 3.8, 100, 95),   # -5
            self._make_trade(4, 'LEVEL_2', 3.2, 100, 97),   # -3
        ]
        m = self.calc.calculate(trades)
        # 盈利总额 18，亏损总额 8，盈亏比 2.25
        self.assertGreater(m.profit_factor, 2.0)

    def test_metrics_to_dict(self):
        trades = [
            self._make_trade(1, 'LEVEL_3', 4.0, 100, 110),
        ]
        m = self.calc.calculate(trades)
        d = m.to_dict()
        self.assertEqual(d['total_trades'], 1)
        self.assertIn('level_3', d)
        self.assertIn('level_2', d)


class TestBacktestReport(unittest.TestCase):
    """报告生成测试"""

    def setUp(self):
        self.report = BacktestReport(output_dir='./test_reports')
        self.est = pytz.timezone('US/Eastern')
        self.now = datetime.now(self.est)

    def _make_trade(self, sid, level, score, entry, exit_p):
        return TradeRecord(
            signal_id=sid,
            signal_time=self.now + timedelta(days=sid),
            alert_level=level,
            total_score=score,
            entry_date=self.now + timedelta(days=sid),
            entry_price=entry,
            exit_date=self.now + timedelta(days=sid + 5),
            exit_price=exit_p,
            hold_days=5,
        )

    def test_generate_markdown(self):
        trades = [
            self._make_trade(1, 'LEVEL_3', 4.0, 400, 420),
            self._make_trade(2, 'LEVEL_3', 4.5, 420, 415),
        ]
        calc = PerformanceCalculator()
        metrics = calc.calculate(trades)
        md = self.report.generate_markdown(trades, metrics)
        self.assertIn('多源共振信号回测报告', md)
        self.assertIn('绩效总览', md)
        self.assertIn('LEVEL_3', md)
        self.assertIn('+5.00%', md)

    def test_generate_json(self):
        trades = [
            self._make_trade(1, 'LEVEL_3', 4.0, 400, 420),
        ]
        calc = PerformanceCalculator()
        metrics = calc.calculate(trades)
        j = self.report.generate_json(trades, metrics)
        self.assertEqual(j['parameters']['symbol'], 'SPY')
        self.assertEqual(len(j['trades']), 1)

    def test_save_report(self):
        trades = [
            self._make_trade(1, 'LEVEL_3', 4.0, 400, 420),
        ]
        calc = PerformanceCalculator()
        metrics = calc.calculate(trades)
        paths = self.report.save_report(trades, metrics, filename_prefix='test')
        self.assertTrue(Path(paths['md_path']).exists())
        self.assertTrue(Path(paths['json_path']).exists())


class TestSignalReplayLogic(unittest.TestCase):
    """SignalReplay 纯逻辑测试 (不依赖 DB/yfinance)"""

    def setUp(self):
        self.replay = SignalReplay(symbol='SPY', hold_days=5)
        self.est = pytz.timezone('US/Eastern')

    def test_empty_signals(self):
        trades = self.replay.simulate_trades([], pd.DataFrame())
        self.assertEqual(len(trades), 0)

    def test_trade_simulation(self):
        """用模拟价格数据测试交易模拟逻辑"""
        dates = pd.date_range('2025-01-01', periods=30, freq='B')
        prices = pd.DataFrame({
            'Close': 400.0 + np.cumsum(np.random.randn(30) * 3),
        }, index=dates)

        base_dt = datetime(2025, 1, 2, tzinfo=self.est)
        signals = [
            {
                'id': 1,
                'trigger_time': base_dt,
                'alert_level': 'LEVEL_3',
                'total_score': 4.0,
            },
        ]

        trades = self.replay.simulate_trades(signals, prices)
        if trades:
            self.assertEqual(trades[0].alert_level, 'LEVEL_3')
            self.assertEqual(trades[0].hold_days, 5)
            self.assertIsNotNone(trades[0].entry_price)

    def test_level_filter(self):
        """测试等级过滤"""
        replay = SignalReplay(min_level='LEVEL_3')
        dates = pd.date_range('2025-01-01', periods=30, freq='B')
        prices = pd.DataFrame({
            'Close': np.full(30, 400.0),
        }, index=dates)

        base_dt = datetime(2025, 1, 2, tzinfo=self.est)
        signals = [
            {'id': 1, 'trigger_time': base_dt, 'alert_level': 'LEVEL_2', 'total_score': 3.2},
            {'id': 2, 'trigger_time': base_dt, 'alert_level': 'LEVEL_3', 'total_score': 4.0},
        ]

        trades = replay.simulate_trades(signals, prices)
        # 只有 LEVEL_3 被纳入了
        for t in trades:
            self.assertEqual(t.alert_level, 'LEVEL_3')

    def test_level_rank(self):
        from backtest_engine.signal_replay import LEVEL_RANK
        self.assertEqual(LEVEL_RANK['LEVEL_3'], 3)
        self.assertEqual(LEVEL_RANK['LEVEL_2'], 2)
        self.assertEqual(LEVEL_RANK['LEVEL_1'], 1)


if __name__ == '__main__':
    unittest.main()
