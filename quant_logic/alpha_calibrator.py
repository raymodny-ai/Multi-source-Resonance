"""
Alpha 校准器 (v2.4)

将本地 GEXCalculator 估算值与 GEXMetrix 官方值对齐, 通过每日
20 日 EWM (指数加权移动) alpha 校准系数, 持续修正本地模型与
市场的系统性偏差。

设计动机:
    本地 BS 模型估算的 GEX 与 GEXMetrix 官方值存在系统性偏差
    (典型 ±10-30%), 来源包括:
        - OI 数据源差异 (OCC vs GEXMetrix 自有源)
        - IV 字段处理方式
        - 0DTE/周度合约权重
    通过 20 日 EWM 校准, alpha 收敛到稳态, 校准后的本地 GEX
    可用于高时间精度场景 (1 分钟级回放, GEXMetrix 仅 15min 更新)

使用:
    >>> from quant_logic.alpha_calibrator import AlphaCalibrator, get_effective_alpha
    >>> # 17:00 ET 日终批量
    >>> AlphaCalibrator().run_eod_batch(['SPX', 'SPY', 'QQQ'])
    >>> # 热路径 (每次 GEX 计算时)
    >>> alpha = get_effective_alpha('SPX')
    >>> net_gex *= alpha
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from database.db_manager import DatabaseManager
from quant_logic.gex_calculator import GEXCalculator
from utils.logger import getLogger

logger = getLogger('alpha_calibrator')


# ── 常量 ──
EWM_SPAN = 20                # 20 日 EWM (类似月线校准窗口)
ALPHA_SANITY_LOW = 0.5       # 校准系数下限
ALPHA_SANITY_HIGH = 1.5      # 校准系数上限
LOCAL_FALLBACK_ALPHA = 1.0   # 无历史数据时使用 (中性)
ALPHA_HISTORY_TABLE = 'alpha_history'  # 持久化表名

# 模块级内存缓存 (避免每次 GEX 计算查 DB)
_EFFECTIVE_ALPHA_CACHE: Dict[str, float] = {}


def get_effective_alpha(symbol: str) -> Optional[float]:
    """模块级热路径查询: 返回某 symbol 的有效校准系数

    优先从内存缓存取, 没有再查 DB alpha_history 的最近一条。
    用于 GEXCalculator 内部, 必须是 fast path (< 1ms)。

    Returns:
        float: alpha (无历史时返回 None, 调用方决定是否 fallback)
    """
    if symbol in _EFFECTIVE_ALPHA_CACHE:
        return _EFFECTIVE_ALPHA_CACHE[symbol]

    try:
        db = DatabaseManager()
        with db._get_cursor() as cur:
            cur.execute(
                f"SELECT ewm_alpha_20d FROM {ALPHA_HISTORY_TABLE} "
                f"WHERE symbol = ? ORDER BY date DESC LIMIT 1",
                (symbol,)
            )
            row = cur.fetchone()
            if row and row[0] is not None:
                alpha = float(row[0])
                _EFFECTIVE_ALPHA_CACHE[symbol] = alpha
                return alpha
    except sqlite3.OperationalError as e:
        # 表不存在 (尚未 migrate), 静默返回 None
        logger.debug(f"alpha_history 表不可用: {e}")
    except Exception as e:
        logger.warning(f"alpha 查询失败 {symbol}: {e}")

    return None


def clear_alpha_cache() -> None:
    """清空内存缓存 (批量校准完成后调用, 强制重读 DB)"""
    _EFFECTIVE_ALPHA_CACHE.clear()


class AlphaCalibrator:
    """每日 17:00 ET EOD 校准, 把本地 vs 官方 GEX 偏差记录并 EWM 平滑

    Examples:
        >>> cal = AlphaCalibrator()
        >>> cal.calibrate_one('SPX')         # 单标校准
        >>> cal.run_eod_batch(['SPX','SPY','QQQ','IWM','NDX','VIX'])
    """

    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or DatabaseManager()
        self.gex_calc = GEXCalculator()
        self._ensure_table()

    def _ensure_table(self) -> None:
        """创建 alpha_history 表 (idempotent)"""
        with self.db._get_cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {ALPHA_HISTORY_TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    date DATE NOT NULL,
                    local_gex REAL,
                    reference_gex REAL,
                    alpha REAL,
                    spot_price REAL,
                    ewm_alpha_20d REAL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, date)
                )
            """)
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_alpha_hist_symbol_date "
                f"ON {ALPHA_HISTORY_TABLE}(symbol, date DESC)"
            )

    def calibrate_one(self, symbol: str, target_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """对单个 symbol 跑一次当日校准

        Args:
            symbol: 标的代码
            target_date: 'YYYY-MM-DD', None=今天 ET

        Returns:
            {'symbol','date','local_gex','reference_gex','alpha','spot_price',
             'ewm_alpha_20d'} 或 None (数据不足)
        """
        if target_date is None:
            target_date = datetime.now(timezone.utc).date().isoformat()

        ref = self._fetch_reference_gex(symbol, target_date)
        if ref is None or ref.get('net_gex') is None:
            logger.info(f"  {symbol}: 无 GEXMetrix 参考数据, 跳过")
            return None

        spot = ref.get('spot_price') or 0
        if spot <= 0:
            logger.info(f"  {symbol}: 无 spot_price, 跳过")
            return None

        local_gex = self._fetch_local_gex(symbol, spot)
        if local_gex is None:
            logger.info(f"  {symbol}: 本地期权链不可用, 跳过")
            return None

        # 计算 alpha (校准系数)
        raw_alpha = self.gex_calc.calibrate_alpha(local_gex, ref['net_gex'])

        # sanity 范围: 0.5 ~ 1.5 之外视为异常, 用 1.0 fallback
        if not (ALPHA_SANITY_LOW <= raw_alpha <= ALPHA_SANITY_HIGH):
            logger.warning(
                f"  {symbol}: alpha={raw_alpha:.3f} 超出 sanity 范围, "
                f"本次不校准 (本地={local_gex:.2e}, ref={ref['net_gex']:.2e})"
            )
            return None

        ewm_alpha = self._compute_ewm(symbol, raw_alpha, target_date)
        self._persist(symbol, target_date, local_gex, ref['net_gex'], raw_alpha, spot, ewm_alpha)

        return {
            'symbol': symbol,
            'date': target_date,
            'local_gex': local_gex,
            'reference_gex': ref['net_gex'],
            'alpha': raw_alpha,
            'spot_price': spot,
            'ewm_alpha_20d': ewm_alpha,
        }

    def run_eod_batch(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """批量校准 (cron 17:00 ET 调用)"""
        results = []
        for sym in symbols:
            try:
                r = self.calibrate_one(sym)
                if r is not None:
                    results.append(r)
            except Exception as e:
                logger.warning(f"  {sym} 校准失败: {e}")
        clear_alpha_cache()
        return results

    # ────────────── 私有方法 ──────────────

    def _fetch_reference_gex(self, symbol: str, target_date: str) -> Optional[Dict[str, Any]]:
        """从 gex_snapshots 表拿最近一条 (优先 target_date 当日, 否则最近)"""
        with self.db._get_cursor() as cur:
            cur.execute(
                "SELECT net_gex, spot_price, call_wall, put_wall, zero_gamma_level "
                "FROM gex_snapshots WHERE symbol = ? AND DATE(timestamp) = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (symbol, target_date)
            )
            row = cur.fetchone()
            if row:
                return {
                    'net_gex': row[0],
                    'spot_price': row[1],
                    'call_wall': row[2],
                    'put_wall': row[3],
                    'zero_gamma_level': row[4],
                }
            # 降级: 拿最近 7 天内任意
            cur.execute(
                "SELECT net_gex, spot_price, call_wall, put_wall, zero_gamma_level "
                "FROM gex_snapshots WHERE symbol = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (symbol,)
            )
            row = cur.fetchone()
            if row:
                logger.info(f"  {symbol}: 当日无 GEXMetrix snapshot, 降级到最近一条")
                return {
                    'net_gex': row[0],
                    'spot_price': row[1],
                    'call_wall': row[2],
                    'put_wall': row[3],
                    'zero_gamma_level': row[4],
                }
        return None

    def _fetch_local_gex(self, symbol: str, spot: float) -> Optional[float]:
        """用 yfinance 拉期权链, GEXCalculator 算 net_gex"""
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            if not ticker.options:
                return None
            expiry = ticker.options[0]
            chain = ticker.option_chain(expiry)
            calls = chain.calls.copy()
            puts = chain.puts.copy()
            calls['type'] = 'CALL'
            puts['type'] = 'PUT'
            df = pd.concat([calls, puts], ignore_index=True)
            # 标准化列名 (yfinance 用 camelCase, GEXCalculator 期望 snake_case)
            if 'impliedVolatility' in df.columns:
                df = df.rename(columns={'impliedVolatility': 'implied_volatility'})
            # 估算 days_to_expiry
            from datetime import datetime as _dt
            try:
                exp_dt = _dt.strptime(expiry, '%Y-%m-%d')
                dte = max(1, (exp_dt - _dt.now()).days)
            except ValueError:
                dte = 30
            df['days_to_expiry'] = dte
            # 至少需要 strike/open_interest/implied_volatility/type/days_to_expiry
            required = {'strike', 'open_interest', 'implied_volatility', 'type', 'days_to_expiry'}
            if not required.issubset(df.columns):
                logger.debug(f"  {symbol}: yfinance df 缺列 {required - set(df.columns)}")
                return None
            result = self.gex_calc.calculate_portfolio_gex_vectorized(df, spot, symbol=None)
            return result['net_gex']
        except ImportError:
            logger.warning("  yfinance/pandas 未安装, 无法本地算 GEX")
            return None
        except Exception as e:
            logger.debug(f"  {symbol}: 本地 GEX 估算失败: {e}")
            return None

    def _compute_ewm(self, symbol: str, today_alpha: float, target_date: str) -> float:
        """20 日 EWM (含今日)

        alpha_weight = 2 / (span + 1) = 2/21 ≈ 0.095
        越近期权重越大, 对市场变化反应快, 但 20 日窗口避免单日噪声
        """
        with self.db._get_cursor() as cur:
            cur.execute(
                f"SELECT alpha FROM {ALPHA_HISTORY_TABLE} WHERE symbol = ? "
                f"AND date < ? ORDER BY date DESC LIMIT ?",
                (symbol, target_date, EWM_SPAN - 1)
            )
            history = [float(r[0]) for r in cur.fetchall() if r[0] is not None]
        history.append(today_alpha)
        if not history:
            return LOCAL_FALLBACK_ALPHA
        # history[0] = 最新 (DESC 查询), history[-1] = 最老
        # EWM 权重: 最新权重最大, 越久远越小
        # weights[i] = exp(-(i)/(n-1)) for i in 0..n-1 (i=0 最新 → 1.0)
        n = len(history)
        weights = np.exp(-np.arange(n) / max(1, n - 1))
        weights /= weights.sum()
        return float(np.dot(weights, history))

    def _persist(
        self, symbol: str, date: str, local: float, ref: float,
        alpha: float, spot: float, ewm: float,
    ) -> None:
        with self.db._get_cursor() as cur:
            cur.execute(f"""
                INSERT INTO {ALPHA_HISTORY_TABLE}
                    (symbol, date, local_gex, reference_gex, alpha,
                     spot_price, ewm_alpha_20d)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, date) DO UPDATE SET
                    local_gex=excluded.local_gex,
                    reference_gex=excluded.reference_gex,
                    alpha=excluded.alpha,
                    spot_price=excluded.spot_price,
                    ewm_alpha_20d=excluded.ewm_alpha_20d
            """, (symbol, date, local, ref, alpha, spot, ewm))
