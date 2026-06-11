"""
信号回放与交易模拟

该模块负责：
1. 从数据库加载历史信号
2. 获取对应时段价格数据
3. 按信号模拟入场/离场
4. 生成交易记录列表
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pytz
import yfinance as yf

logger = logging.getLogger(__name__)

# 默认回测参数
DEFAULT_SYMBOL = 'SPY'
DEFAULT_HOLD_DAYS = 5          # 默认持仓天数
DEFAULT_MIN_LEVEL = 'LEVEL_2'  # 最低回测信号等级
LEVEL_RANK = {'LEVEL_3': 3, 'LEVEL_2': 2, 'LEVEL_1': 1, 'NO_SIGNAL': 0}


class TradeRecord:
    """单笔交易记录"""

    __slots__ = (
        'signal_id', 'signal_time', 'alert_level', 'total_score',
        'entry_date', 'entry_price', 'exit_date', 'exit_price',
        'hold_days', 'return_pct', 'is_win', 'dimension_scores',
    )

    def __init__(
        self,
        signal_id: int,
        signal_time: datetime,
        alert_level: str,
        total_score: float,
        entry_date: datetime,
        entry_price: float,
        exit_date: datetime,
        exit_price: float,
        hold_days: int,
        dimension_scores: Optional[Dict] = None,
    ):
        self.signal_id = signal_id
        self.signal_time = signal_time
        self.alert_level = alert_level
        self.total_score = total_score
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.exit_date = exit_date
        self.exit_price = exit_price
        self.hold_days = hold_days
        self.return_pct = (exit_price - entry_price) / entry_price * 100
        self.is_win = self.return_pct > 0
        self.dimension_scores = dimension_scores or {}

    def to_dict(self) -> Dict:
        return {
            'signal_id': self.signal_id,
            'signal_time': self.signal_time.isoformat(),
            'alert_level': self.alert_level,
            'total_score': self.total_score,
            'entry_date': self.entry_date.strftime('%Y-%m-%d') if isinstance(self.entry_date, datetime) else str(self.entry_date),
            'entry_price': round(self.entry_price, 2),
            'exit_date': self.exit_date.strftime('%Y-%m-%d') if isinstance(self.exit_date, datetime) else str(self.exit_date),
            'exit_price': round(self.exit_price, 2),
            'hold_days': self.hold_days,
            'return_pct': round(self.return_pct, 2),
            'is_win': self.is_win,
        }


class SignalReplay:
    """信号回放引擎

    从数据库加载历史信号，匹配价格数据，模拟交易执行。

    Attributes:
        symbol: 回测标的 (默认 SPY)
        hold_days: 持仓天数
        min_level: 最低回测信号等级
        est: 美东时区
    """

    def __init__(
        self,
        symbol: str = DEFAULT_SYMBOL,
        hold_days: int = DEFAULT_HOLD_DAYS,
        min_level: str = DEFAULT_MIN_LEVEL,
    ):
        self.symbol = symbol
        self.hold_days = hold_days
        self.min_level = min_level
        self.est = pytz.timezone('US/Eastern')

    def load_signals_from_db(self, db_manager, lookback_days: int = 365) -> List[Dict]:
        """从数据库加载历史信号

        Args:
            db_manager: DatabaseManager 实例
            lookback_days: 回溯天数

        Returns:
            信号字典列表
        """
        try:
            cursor = db_manager._get_cursor()
            cursor.execute(
                """SELECT * FROM signal_alerts
                   WHERE trigger_time >= datetime('now', '-' || ? || ' days')
                     AND alert_level IN ('LEVEL_2', 'LEVEL_3')
                   ORDER BY trigger_time ASC""",
                (lookback_days,)
            )
            rows = cursor.fetchall()
            signals = [db_manager._row_to_dict(r) for r in rows]
            logger.info(f"从 DB 加载 {len(signals)} 条历史信号")
            return signals
        except Exception as e:
            logger.error(f"加载历史信号失败: {e}")
            return []

    def _get_next_trading_day(self, dt: datetime, prices: pd.DataFrame) -> Optional[datetime]:
        """找到 dt 之后（含）的第一个交易日

        Args:
            dt: 基准时间
            prices: 价格 DataFrame (index 为日期)

        Returns:
            第一个交易日，若超出范围返回 None
        """
        target_date = dt.date() if hasattr(dt, 'date') else pd.Timestamp(dt).date()
        # 在价格索引中找 >= target_date 的第一个日期
        future_dates = prices.index[prices.index >= pd.Timestamp(target_date)]
        if len(future_dates) == 0:
            return None
        return future_dates[0].to_pydatetime()

    def fetch_price_data(self, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """通过 yfinance 获取历史价格数据

        Args:
            start_date: 起始日期
            end_date: 截止日期

        Returns:
            DataFrame (index=Date, columns=['Close'])
        """
        try:
            ticker = yf.Ticker(self.symbol)
            df = ticker.history(start=start_date, end=end_date)
            if df.empty:
                logger.warning(f"{self.symbol} 无价格数据: {start_date} ~ {end_date}")
                return df
            df = df[['Close']].copy()
            df.index = df.index.normalize()  # 归一化到日期
            logger.info(f"获取 {self.symbol} 价格数据: {len(df)} 个交易日")
            return df
        except Exception as e:
            logger.error(f"获取价格数据失败: {e}")
            return pd.DataFrame()

    def simulate_trades(
        self,
        signals: List[Dict],
        prices: pd.DataFrame,
    ) -> List[TradeRecord]:
        """模拟交易

        对每条信号，在信号发出的下一个交易日以收盘价入场，
        持有 hold_days 个交易日后以收盘价离场。

        Args:
            signals: 信号列表
            prices: 价格 DataFrame

        Returns:
            交易记录列表
        """
        if prices.empty or not signals:
            return []

        trades: List[TradeRecord] = []
        min_rank = LEVEL_RANK.get(self.min_level, 2)

        for sig in signals:
            alert_level = sig.get('alert_level', 'NO_SIGNAL')
            # 过滤低于最低等级的
            if LEVEL_RANK.get(alert_level, 0) < min_rank:
                continue

            signal_time = sig.get('trigger_time')
            if isinstance(signal_time, str):
                signal_time = datetime.fromisoformat(signal_time)

            # 找入场日（信号触发后的下一个交易日）
            entry_dt = self._get_next_trading_day(signal_time, prices)
            if entry_dt is None:
                continue

            # 获取入场价格
            try:
                entry_price = float(prices.loc[pd.Timestamp(entry_dt), 'Close'])
            except KeyError:
                continue

            # 找离场日（入场日后 hold_days 个交易日）
            price_dates = prices.index[prices.index >= pd.Timestamp(entry_dt)]
            if len(price_dates) <= self.hold_days:
                continue  # 数据不足，跳过
            exit_dt = price_dates[self.hold_days].to_pydatetime()

            try:
                exit_price = float(prices.loc[pd.Timestamp(exit_dt), 'Close'])
            except KeyError:
                continue

            # 提取维度得分
            dimension_scores = {
                'gex': sig.get('gex_score', 0),
                'vix': sig.get('vix_score', 0),
                'crypto': sig.get('crypto_score', 0),
                'darkpool': sig.get('darkpool_score', 0),
            }

            trade = TradeRecord(
                signal_id=sig.get('id', 0),
                signal_time=signal_time,
                alert_level=alert_level,
                total_score=float(sig.get('total_score', 0)),
                entry_date=entry_dt,
                entry_price=entry_price,
                exit_date=exit_dt,
                exit_price=exit_price,
                hold_days=self.hold_days,
                dimension_scores=dimension_scores,
            )
            trades.append(trade)

        logger.info(f"模拟完成: {len(trades)} 笔交易 (共 {len(signals)} 条信号)")
        return trades

    def run(
        self,
        db_manager,
        lookback_days: int = 365,
        prices: Optional[pd.DataFrame] = None,
    ) -> Tuple[List[TradeRecord], pd.DataFrame]:
        """运行完整回放流程

        Args:
            db_manager: 数据库管理器
            lookback_days: 回溯天数
            prices: 预获取的价格数据 (可选，不提供则自动获取)

        Returns:
            (交易记录列表, 价格 DataFrame)
        """
        # 1. 加载信号
        signals = self.load_signals_from_db(db_manager, lookback_days)
        if not signals:
            logger.warning("无历史信号可回放")
            return [], pd.DataFrame()

        # 2. 获取价格数据
        if prices is None or prices.empty:
            earliest = min(
                datetime.fromisoformat(s['trigger_time'])
                if isinstance(s['trigger_time'], str) else s['trigger_time']
                for s in signals
            )
            latest = max(
                datetime.fromisoformat(s['trigger_time'])
                if isinstance(s['trigger_time'], str) else s['trigger_time']
                for s in signals
            )
            # 扩展范围以容纳持仓期
            start = earliest - timedelta(days=10)
            end = latest + timedelta(days=self.hold_days + 30)
            prices = self.fetch_price_data(start, end)

        # 3. 模拟交易
        trades = self.simulate_trades(signals, prices)

        return trades, prices
