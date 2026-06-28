"""
GEX 数据质量验证器

为 GEXMetrix 快照提供 4 维质量评估:
    1. 时效性 (data_lag_seconds): snapshot timestamp 与 now 的延迟
    2. 结构性 (strike_density, zero_oi_pct): 行权价覆盖密度
    3. OI 覆盖率 (oi_coverage_pct): 与 yfinance 期权链作免费基准比对
    4. IV 一致性 (iv_violations): 同 strike Call/Put IV 偏差

设计原则:
    - 失败优雅: yfinance/网络异常返回 None, 不阻塞主流程
    - 评分透明: 0-1 分, 各项减分有明确阈值
    - 可单独使用: GEXDataQualityValidator.validate_snapshot() 即核心入口
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database.db_manager import DatabaseManager
from utils.logger import getLogger

logger = getLogger('gex_quality')


# ── 阈值常量 (统一在此,便于调整) ──
STALE_LAG_SECONDS = 600           # 10 分钟以上视为陈旧
THIN_STRIKES_THRESHOLD = 50       # 少于 50 个行权价视为稀疏
HIGH_ZERO_OI_RATIO = 0.30         # 零 OI 行权价比例超过 30% 视为数据稀疏
OI_COVERAGE_THRESHOLD = 0.90      # OI 覆盖率低于 90% 视为不完整
IV_VIOLATION_THRESHOLD = 0.02     # 同 strike Call/Put IV 偏差 > 2%
IV_VIOLATION_RATIO = 0.05         # 违例行权价比例 > 5% 视为质量差
MIN_PASS_SCORE = 0.5              # 综合分低于此值标记为 invalid

# V2.5 P1: 流动性门控阈值
LOW_LIQUIDITY_OI_THRESHOLD = 500      # OI < 500 视为低流动性
LOW_LIQUIDITY_SPREAD_PCT = 0.10       # Spread% > 10% 视为流动性差
HIGH_LOW_LIQUIDITY_RATIO = 0.50       # 低流动性合约占比超过 50% 扣分

# yfinance 期权链质量可靠的子集 (CBOE 完整镜像)
YF_BENCHMARK_SYMBOLS = frozenset({
    'SPY', 'QQQ', 'IWM', 'GLD', 'SLV', 'TSLA', 'NVDA',
})


class GEXDataQualityValidator:
    """GEX 快照质量验证器

    Examples:
        >>> v = GEXDataQualityValidator()
        >>> result = v.validate_snapshot('SPY', gex_snapshot_dict)
        >>> print(result['score'], result['issues'])
    """

    def __init__(self, db: Optional[DatabaseManager] = None):
        # 允许注入, 便于测试
        self.db = db or DatabaseManager()

    def validate_snapshot(
        self,
        symbol: str,
        gex_snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        """对单条 GEXMetrix 快照跑全套验证

        Args:
            symbol: 标的代码
            gex_snapshot: GEXMetrix 原始响应, 含 data 字段

        Returns:
            {
                'symbol': str,
                'valid': bool,           # score >= 0.5
                'score': float,          # 0-1 综合分
                'lag_seconds': int | None,
                'oi_coverage_pct': float | None,  # 仅 YF 可比时
                'iv_violations': int,
                'strike_density': int,
                'zero_oi_pct': float,
                'issues': list[str],
            }
        """
        inner = gex_snapshot.get('data', gex_snapshot) or {}
        strikes = inner.get('strikes', []) or []
        snap_ts = inner.get('timestamp') or gex_snapshot.get('timestamp')
        spot = inner.get('spot_price')

        result: Dict[str, Any] = {
            'symbol': symbol,
            'valid': True,
            'score': 1.0,
            'lag_seconds': self._calc_lag(snap_ts),
            'oi_coverage_pct': None,
            'iv_violations': 0,
            'strike_density': len(strikes),
            'zero_oi_pct': 0.0,
            'low_liquidity_pct': 0.0,    # V2.5 P1: 低流动性合约占比
            'issues': [],
        }

        # ── 1. 时效性 ──
        if result['lag_seconds'] is None:
            result['issues'].append('no_timestamp')
            result['score'] -= 0.3
        elif result['lag_seconds'] > STALE_LAG_SECONDS:
            result['issues'].append(f'stale_{result["lag_seconds"]}s')
            result['score'] -= 0.2

        # ── 2. 结构检查 ──
        if len(strikes) < THIN_STRIKES_THRESHOLD:
            result['issues'].append(f'thin_strikes_{len(strikes)}')
            result['score'] -= 0.15

        if strikes:
            zero_oi = sum(
                1 for s in strikes
                if (s.get('call_oi', 0) or 0) + (s.get('put_oi', 0) or 0) == 0
            )
            result['zero_oi_pct'] = zero_oi / len(strikes)
            if result['zero_oi_pct'] > HIGH_ZERO_OI_RATIO:
                result['issues'].append(f'zero_oi_{zero_oi}/{len(strikes)}')
                result['score'] -= 0.2

            # V2.5 P1: 低流动性合约占比 (OI<500 或 Spread%>10%)
            low_liq = sum(
                1 for s in strikes
                if self._is_low_liquidity(s)
            )
            result['low_liquidity_pct'] = low_liq / len(strikes)
            if result['low_liquidity_pct'] > HIGH_LOW_LIQUIDITY_RATIO:
                result['issues'].append(
                    f'low_liquidity_{low_liq}/{len(strikes)}'
                )
                result['score'] -= 0.15

        if not spot:
            result['issues'].append('no_spot')
            result['score'] -= 0.2

        # ── 3. OI 覆盖比对 (仅 YF 基准集) ──
        if symbol in YF_BENCHMARK_SYMBOLS:
            coverage = self._check_oi_coverage_yf(symbol, strikes, spot or 0)
            result['oi_coverage_pct'] = coverage
            if coverage is not None and coverage < OI_COVERAGE_THRESHOLD:
                result['issues'].append(f'oi_coverage_{coverage:.1%}')
                result['score'] -= 0.2

        # ── 4. IV 一致性 ──
        iv_violations = self._check_iv_parity(strikes)
        result['iv_violations'] = len(iv_violations)
        if iv_violations and strikes:
            violation_ratio = len(iv_violations) / len(strikes)
            if violation_ratio > IV_VIOLATION_RATIO:
                result['issues'].append(f'iv_violations_{violation_ratio:.1%}')
                result['score'] -= 0.15

        # 截断 + 标记
        result['score'] = max(0.0, round(result['score'], 2))
        result['valid'] = result['score'] >= MIN_PASS_SCORE
        return result

    # ────────────── helpers ──────────────

    def _calc_lag(self, ts_str: Optional[str]) -> Optional[int]:
        """snapshot timestamp → 距 now 的秒数 (UTC)"""
        if not ts_str:
            return None
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%SZ'):
            try:
                dt = datetime.strptime(ts_str, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return int((datetime.now(timezone.utc) - dt).total_seconds())
            except ValueError:
                continue
        return None

    def _check_oi_coverage_yf(
        self, symbol: str, gex_strikes: List[Dict[str, Any]], spot: float,
    ) -> Optional[float]:
        """用 yfinance 期权链作免费 OI 覆盖基准 (限 ±5% 行权价范围)"""
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            expiry = ticker.options[0]
            chain = ticker.option_chain(expiry)
            yf_total = int(
                chain.calls['openInterest'].fillna(0).sum()
                + chain.puts['openInterest'].fillna(0).sum()
            )
            if yf_total == 0 or spot <= 0:
                return None

            lo, hi = spot * 0.95, spot * 1.05
            gex_total = sum(
                (s.get('call_oi', 0) or 0) + (s.get('put_oi', 0) or 0)
                for s in gex_strikes
                if lo <= s.get('strike', 0) <= hi
            )
            return gex_total / yf_total
        except Exception as e:
            logger.debug(f"YF coverage check failed for {symbol}: {e}")
            return None

    def _check_iv_parity(
        self, strikes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """同 strike Call/Put IV 偏差 > 2% 视为异常"""
        violations: List[Dict[str, Any]] = []
        for s in strikes:
            call_iv = s.get('call_iv') or s.get('callIV')
            put_iv = s.get('put_iv') or s.get('putIV')
            if call_iv and put_iv and abs(call_iv - put_iv) > IV_VIOLATION_THRESHOLD:
                violations.append({
                    'strike': s.get('strike'),
                    'diff': abs(call_iv - put_iv),
                })
        return violations

    def _is_low_liquidity(self, strike_data: Dict[str, Any]) -> bool:
        """V2.5 P1: 判断单个 strike 是否低流动性

        低流动性定义 (任一满足):
          - OI < 500 (call_oi + put_oi 合计)
          - Spread% > 10% (call 或 put 至少一侧)
        """
        call_oi = strike_data.get('call_oi', 0) or 0
        put_oi = strike_data.get('put_oi', 0) or 0
        total_oi = call_oi + put_oi
        if total_oi < LOW_LIQUIDITY_OI_THRESHOLD:
            return True

        # 检查买卖价差 (尝试多种字段名)
        for prefix in ('call', 'put'):
            bid = strike_data.get(f'{prefix}_bid', 0) or 0
            ask = strike_data.get(f'{prefix}_ask', 0) or 0
            if ask > 0:
                spread_pct = (ask - bid) / ask
                if spread_pct > LOW_LIQUIDITY_SPREAD_PCT:
                    return True
        return False


# ── 便捷函数:在 fetcher 抓完后立即调 ──
def validate_after_fetch(symbol: str, gex_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """在 GEXMetrixFetcher.fetch_core/_indices/_all 之后立即跑验证

    返回完整的 validation dict, 供调用方:
        - 写入 gex_snapshots.quality_score 等列
        - 更新 summary.json 中的 quality 字段
        - 不通过时打 warning 日志

    Examples:
        >>> quality = validate_after_fetch('SPY', raw_response)
        >>> if not quality['valid']:
        ...     logger.warning(f"SPY 数据质量低: {quality['issues']}")
    """
    try:
        v = GEXDataQualityValidator()
        return v.validate_snapshot(symbol, gex_snapshot)
    except Exception as e:
        # 验证本身失败不能阻塞 fetcher
        logger.warning(f"GEX quality validation failed for {symbol}: {e}")
        return {
            'symbol': symbol,
            'valid': True,  # 默认放行
            'score': 0.5,   # 中性
            'lag_seconds': None,
            'oi_coverage_pct': None,
            'iv_violations': 0,
            'strike_density': 0,
            'zero_oi_pct': 0.0,
            'low_liquidity_pct': 0.0,   # V2.5 P1
            'issues': ['validator_error'],
        }
