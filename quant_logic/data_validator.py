"""
Multi-source Resonance V2.0 — 数据校验防线模块 (PRD §数据校验与金融常识审查模块)

在 Layer 1 (数学运算层) 与 Layer 2 (上下文网关层) 之间部署的专用数据校验模块。
这是防止"垃圾进，垃圾出"(GIGO) 以及避免引发 LLM 逻辑推理错误的最后一道刚性防线。

实现 PRD 要求的全部六项校验:
  1. Pandera DataFrame 列类型与统计校验 (针对期权链/暗盘降维矩阵)
  2. 希腊字母边界校验 (Greeks Bounds)
  3. 平价组合逻辑校验 (Put-Call Parity)
  4. 无套利定价边界 (No-Arbitrage Bounds)
  5. Isolation Forest 微观异常检测
  6. 不可变审计日志 + 95% 通过率熔断

该模块为 Layer 1.5 组件，输出直接影响 Layer 2 是否放行。
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Tuple, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
import json

try:
    import pandera as pa
    from pandera.typing import DataFrame, Series
    PANDERA_AVAILABLE = True
except ImportError:
    PANDERA_AVAILABLE = False

try:
    from sklearn.ensemble import IsolationForest
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

from utils.logger import getLogger

logger = getLogger('data_validator')


# ═══════════════════════════════════════════
# 数据类
# ═══════════════════════════════════════════

@dataclass
class ValidationAuditEntry:
    """不可变审计日志条目"""
    timestamp: str = ""
    check_type: str = ""          # GREEKS_BOUNDS / PUT_CALL_PARITY / NO_ARBITRAGE / ISO_FOREST / PANDERA
    severity: str = "WARN"        # ERROR / WARN / INFO
    field_name: str = ""
    expected_range: str = ""
    actual_value: str = ""
    option_type: str = ""         # CALL / PUT
    strike: float = 0.0
    expiry: str = ""
    details: str = ""
    data_snapshot_b64: str = ""   # Base64 编码的问题数据片段 (用于审计回溯)


@dataclass
class ValidationResult:
    """校验结果容器"""
    passed: bool = True
    total_checks: int = 0
    passed_checks: int = 0
    failed_checks: int = 0
    pass_rate_pct: float = 100.0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    audit_entries: List[ValidationAuditEntry] = field(default_factory=list)
    should_circuit_break: bool = False  # 95% 通过率熔断标志
    circuit_break_reason: str = ""


# ═══════════════════════════════════════════
# 1. Pandera DataFrame Schema 校验
# ═══════════════════════════════════════════

# 期权链 DataFrame 的 Pandera Schema 定义
OPTION_CHAIN_SCHEMA = None
if PANDERA_AVAILABLE:
    OPTION_CHAIN_SCHEMA = pa.DataFrameSchema({
        "strike": pa.Column(float, pa.Check.ge(0), nullable=False),
        "type": pa.Column(str, pa.Check.isin(["CALL", "PUT", "Call", "Put", "call", "put", "C", "P", "c", "p"]), nullable=False),
        "expiry": pa.Column(str, nullable=False),
        "open_interest": pa.Column(float, pa.Check.ge(0), nullable=False),
        "volume": pa.Column(float, pa.Check.ge(0), nullable=True),
        "bid": pa.Column(float, pa.Check.ge(0), nullable=True),
        "ask": pa.Column(float, pa.Check.ge(0), nullable=True),
        "implied_volatility": pa.Column(float, pa.Check.in_range(0.001, 10.0), nullable=True),
        "days_to_expiry": pa.Column(float, pa.Check.ge(0), nullable=True),
    }, strict=False)


class PanderaValidator:
    """Pandera DataFrame 校验器 (PRD §双层校验技术栈 — 第一层)

    对 Layer 1 输出的期权链 DataFrame 执行严格的列类型约束和统计级检查。
    """

    @staticmethod
    def validate_option_chain(df: pd.DataFrame) -> Tuple[bool, List[str], List[ValidationAuditEntry]]:
        """校验期权链 DataFrame 的列类型和数值范围

        Args:
            df: 期权链 DataFrame

        Returns:
            (通过标志, 错误列表, 审计条目列表)
        """
        errors: List[str] = []
        audit_entries: List[ValidationAuditEntry] = []
        now = datetime.now().isoformat()

        if df is None or df.empty:
            errors.append("期权链 DataFrame 为空")
            return False, errors, audit_entries

        # ── 必需列检查 ──
        required_cols = {'strike', 'type', 'expiry', 'open_interest'}
        missing_cols = required_cols - set(df.columns)
        if missing_cols:
            errors.append(f"缺少必需列: {missing_cols}")
            return False, errors, audit_entries

        total_rows = len(df)

        # ── 行权价 ≥ 0 ──
        neg_strikes = (df['strike'] <= 0).sum()
        if neg_strikes > 0:
            errors.append(f"行权价 ≤ 0: {neg_strikes}/{total_rows} 行")
            audit_entries.append(ValidationAuditEntry(
                timestamp=now, check_type="PANDERA", severity="ERROR",
                field_name="strike", expected_range="(0, +∞)",
                actual_value=f"{neg_strikes} rows ≤ 0",
                details=f"行权价非正: {neg_strikes}/{total_rows}"
            ))

        # ── 未平仓量 ≥ 0 ──
        neg_oi = (df['open_interest'] < 0).sum()
        if neg_oi > 0:
            errors.append(f"未平仓量 < 0: {neg_oi}/{total_rows} 行")
            audit_entries.append(ValidationAuditEntry(
                timestamp=now, check_type="PANDERA", severity="ERROR",
                field_name="open_interest", expected_range="[0, +∞)",
                actual_value=f"{neg_oi} rows < 0"
            ))

        # ── 期权价格 ≥ 0 (bid/ask) ──
        for price_col in ['bid', 'ask']:
            if price_col in df.columns:
                neg_prices = (df[price_col] < 0).sum()
                if neg_prices > 0:
                    errors.append(f"{price_col} < 0: {neg_prices}/{total_rows} 行")
                    audit_entries.append(ValidationAuditEntry(
                        timestamp=now, check_type="PANDERA", severity="ERROR",
                        field_name=price_col, expected_range="[0, +∞)",
                        actual_value=f"{neg_prices} rows < 0"
                    ))

        # ── 隐含波动率在 (0, 10] 范围 ──
        if 'implied_volatility' in df.columns:
            iv_col = df['implied_volatility'].dropna()
            out_of_range = ((iv_col <= 0) | (iv_col > 10.0)).sum()
            if out_of_range > 0:
                msg = f"隐含波动率越界 (0, 10]: {out_of_range}/{len(iv_col)} 行"
                errors.append(msg)
                audit_entries.append(ValidationAuditEntry(
                    timestamp=now, check_type="PANDERA", severity="ERROR",
                    field_name="implied_volatility", expected_range="(0, 10]",
                    actual_value=f"{out_of_range} rows out of range"
                ))

        # ── 期权类型枚举 ──
        valid_types = {'CALL', 'PUT', 'Call', 'Put', 'call', 'put', 'C', 'P', 'c', 'p'}
        if 'type' in df.columns:
            invalid_types = df[~df['type'].isin(valid_types)]
            if len(invalid_types) > 0:
                errors.append(f"无效期权类型: {len(invalid_types)}行")
                audit_entries.append(ValidationAuditEntry(
                    timestamp=now, check_type="PANDERA", severity="ERROR",
                    field_name="type", expected_range=str(valid_types),
                    actual_value=f"{len(invalid_types)} invalid rows"
                ))

        # ── Pandera Schema 校验 (库可用时) ──
        if PANDERA_AVAILABLE and OPTION_CHAIN_SCHEMA is not None:
            try:
                OPTION_CHAIN_SCHEMA.validate(df, lazy=True)
            except pa.errors.SchemaErrors as e:
                errors.append(f"Pandera Schema 校验失败: {len(e.failure_cases)} 项违规")
                audit_entries.append(ValidationAuditEntry(
                    timestamp=now, check_type="PANDERA", severity="ERROR",
                    field_name="schema", details=str(e.failure_cases)[:500]
                ))

        is_valid = len(errors) == 0
        if is_valid:
            logger.info(f"Pandera 校验通过: {total_rows} 行期权链数据 ✓")
        else:
            logger.warning(f"Pandera 校验失败: {len(errors)} 个错误")

        return is_valid, errors, audit_entries


# ═══════════════════════════════════════════
# 2. 希腊字母边界校验 (Greeks Bounds)
# ═══════════════════════════════════════════

class GreeksBoundsValidator:
    """希腊字母边界校验器 (PRD §金融数据常识检查)

    强制检查 Black-Scholes 输出的希腊字母是否符合金融学定理:
    - 看涨 Delta ∈ [0, 1]
    - 看跌 Delta ∈ [-1, 0]
    - 深度价内 Delta → ±1
    - 深度价外 Delta → 0
    - Gamma ≥ 0
    """

    # 深度价内/价外判断阈值 (现价偏离行权价百分比)
    DEEP_ITM_THRESHOLD = 0.20    # S > K * 1.20 → 深度价内
    DEEP_OTM_THRESHOLD = -0.20   # S < K * 0.80 → 深度价外

    @classmethod
    def validate(
        cls,
        strikes: np.ndarray,
        spot: float,
        deltas: np.ndarray,
        gammas: np.ndarray,
        option_types: np.ndarray,
    ) -> Tuple[bool, List[str], List[ValidationAuditEntry]]:
        """对全量期权链执行希腊字母边界校验

        Args:
            strikes: 行权价数组
            spot: 标的现价
            deltas: Delta 数组
            gammas: Gamma 数组
            option_types: 期权类型数组 ('CALL'/'PUT')

        Returns:
            (通过标志, 错误列表, 审计条目列表)
        """
        errors: List[str] = []
        audit_entries: List[ValidationAuditEntry] = []
        now = datetime.now().isoformat()
        n = len(strikes)

        if n == 0:
            return True, [], []

        is_call = np.array([t.upper() in ('CALL', 'C') for t in option_types])
        is_put = ~is_call

        # ── 1. 看涨 Delta ∈ [0, 1] ──
        call_deltas = deltas[is_call]
        call_violations = (call_deltas < 0) | (call_deltas > 1)
        n_call_violations = np.sum(call_violations)
        if n_call_violations > 0:
            errors.append(f"看涨 Delta 越界 [0,1]: {n_call_violations}/{np.sum(is_call)} 合约")
            # 采样最多5条违规详情
            viol_indices = np.where(is_call)[0][call_violations][:5]
            for idx in viol_indices:
                audit_entries.append(ValidationAuditEntry(
                    timestamp=now, check_type="GREEKS_BOUNDS", severity="ERROR",
                    field_name="delta", expected_range="[0, 1]",
                    actual_value=f"{deltas[idx]:.4f}",
                    option_type="CALL", strike=float(strikes[idx]),
                    details=f"K={strikes[idx]:.2f}, S={spot:.2f}"
                ))

        # ── 2. 看跌 Delta ∈ [-1, 0] ──
        put_deltas = deltas[is_put]
        put_violations = (put_deltas < -1) | (put_deltas > 0)
        n_put_violations = np.sum(put_violations)
        if n_put_violations > 0:
            errors.append(f"看跌 Delta 越界 [-1,0]: {n_put_violations}/{np.sum(is_put)} 合约")
            viol_indices = np.where(is_put)[0][put_violations][:5]
            for idx in viol_indices:
                audit_entries.append(ValidationAuditEntry(
                    timestamp=now, check_type="GREEKS_BOUNDS", severity="ERROR",
                    field_name="delta", expected_range="[-1, 0]",
                    actual_value=f"{deltas[idx]:.4f}",
                    option_type="PUT", strike=float(strikes[idx]),
                    details=f"K={strikes[idx]:.2f}, S={spot:.2f}"
                ))

        # ── 3. Gamma ≥ 0 ──
        gamma_violations = gammas < 0
        n_gamma_violations = np.sum(gamma_violations)
        if n_gamma_violations > 0:
            errors.append(f"Gamma < 0: {n_gamma_violations}/{n} 合约")
            for idx in np.where(gamma_violations)[0][:5]:
                audit_entries.append(ValidationAuditEntry(
                    timestamp=now, check_type="GREEKS_BOUNDS", severity="ERROR",
                    field_name="gamma", expected_range="[0, +∞)",
                    actual_value=f"{gammas[idx]:.6f}",
                    option_type=option_types[idx],
                    strike=float(strikes[idx])
                ))

        # ── 4. 深度价内/价外 Delta 极限值校验 ──
        if spot > 0:
            moneyness = (spot - strikes) / spot  # > 0 为价内
            deep_itm_mask = moneyness > cls.DEEP_ITM_THRESHOLD
            deep_otm_mask = moneyness < cls.DEEP_OTM_THRESHOLD

            # 深度价内看涨 Delta 应接近 1
            deep_itm_calls = deep_itm_mask & is_call
            if np.any(deep_itm_calls):
                itm_call_deltas = deltas[deep_itm_calls]
                itm_deviations = np.abs(itm_call_deltas - 1.0) > 0.15
                if np.sum(itm_deviations) > 0:
                    errors.append(f"深度价内看涨 Delta 偏离1: {np.sum(itm_deviations)} 合约")

            # 深度价外看涨 Delta 应接近 0
            deep_otm_calls = deep_otm_mask & is_call
            if np.any(deep_otm_calls):
                otm_call_deltas = deltas[deep_otm_calls]
                otm_deviations = np.abs(otm_call_deltas) > 0.15
                if np.sum(otm_deviations) > 0:
                    errors.append(f"深度价外看涨 Delta 偏离0: {np.sum(otm_deviations)} 合约")

            # 深度价内看跌 Delta 应接近 -1
            deep_itm_puts = deep_itm_mask & is_put
            if np.any(deep_itm_puts):
                itm_put_deltas = deltas[deep_itm_puts]
                itm_deviations = np.abs(itm_put_deltas + 1.0) > 0.15
                if np.sum(itm_deviations) > 0:
                    errors.append(f"深度价内看跌 Delta 偏离-1: {np.sum(itm_deviations)} 合约")

        is_valid = len(errors) == 0
        if is_valid:
            logger.info(f"希腊字母边界校验通过: {n} 合约 ✓")
        else:
            logger.warning(f"希腊字母边界校验失败: {len(errors)} 个错误")

        return is_valid, errors, audit_entries


# ═══════════════════════════════════════════
# 3. 平价组合逻辑校验 (Put-Call Parity)
# ═══════════════════════════════════════════

class PutCallParityValidator:
    """平价组合逻辑校验器 (PRD §金融数据常识检查)

    同一行权价下，Call Delta + Put Delta ≈ 0 (更精确: Call_Delta - Put_Delta ≈ 1)
    实际: Call_Delta = N(d1), Put_Delta = N(d1) - 1 → Call_Delta + |Put_Delta| ≈ 1
    即: abs(Call_Delta + Put_Delta) 应接近 0 (因为 Put_Delta 为负)
    """

    # 容忍偏差
    TOLERANCE = 0.05  # 综合 Delta 偏离容忍度

    @classmethod
    def validate(
        cls,
        strikes: np.ndarray,
        deltas: np.ndarray,
        option_types: np.ndarray,
        sample_rate: float = 0.30,  # 抽样 30% 行权价检查
    ) -> Tuple[bool, List[str], List[ValidationAuditEntry]]:
        """抽样检查同行权价 Call+Put 组合 Delta 是否接近 0

        Args:
            strikes: 行权价数组
            deltas: Delta 数组
            option_types: 期权类型数组
            sample_rate: 抽样率

        Returns:
            (通过标志, 错误列表, 审计条目列表)
        """
        errors: List[str] = []
        audit_entries: List[ValidationAuditEntry] = []
        now = datetime.now().isoformat()

        n = len(strikes)
        if n < 2:
            return True, [], []

        is_call = np.array([t.upper() in ('CALL', 'C') for t in option_types])

        # 按行权价分组
        unique_strikes = np.unique(strikes)
        # 抽样
        sample_size = max(2, int(len(unique_strikes) * sample_rate))
        sampled = np.random.choice(unique_strikes, size=min(sample_size, len(unique_strikes)), replace=False)

        parity_violations = 0
        total_checked = 0

        for s in sampled:
            s_mask = strikes == s
            s_is_call = is_call[s_mask]
            s_deltas = deltas[s_mask]

            call_idx = np.where(s_is_call)[0]
            put_idx = np.where(~s_is_call)[0]

            if len(call_idx) == 0 or len(put_idx) == 0:
                continue  # 该行权价无配对合约

            total_checked += 1
            # 平均 Call Delta + 平均 Put Delta 应接近 0
            avg_call_delta = np.mean(s_deltas[call_idx])
            avg_put_delta = np.mean(s_deltas[put_idx])
            combined = avg_call_delta + avg_put_delta  # Put_Delta 为负

            if abs(combined) > cls.TOLERANCE:
                parity_violations += 1
                audit_entries.append(ValidationAuditEntry(
                    timestamp=now, check_type="PUT_CALL_PARITY", severity="WARN",
                    field_name="delta_parity", expected_range=f"|Δ| ≤ {cls.TOLERANCE}",
                    actual_value=f"Call={avg_call_delta:.4f}, Put={avg_put_delta:.4f}, Combined={combined:.4f}",
                    strike=float(s),
                    details=f"K={s:.2f}, Call_δ={avg_call_delta:.4f}, Put_δ={avg_put_delta:.4f}"
                ))

        violation_rate = parity_violations / total_checked if total_checked > 0 else 0

        is_valid = violation_rate < 0.10  # 违规率 < 10% 视为通过
        if is_valid:
            logger.info(f"Put-Call Parity 校验通过: {total_checked} 个行权价, 违规{parity_violations}个 ✓")
        else:
            msg = f"Put-Call Parity 违规率过高: {parity_violations}/{total_checked}"
            errors.append(msg)
            logger.warning(msg)

        return is_valid, errors, audit_entries


# ═══════════════════════════════════════════
# 4. 无套利定价边界 (No-Arbitrage Bounds)
# ═══════════════════════════════════════════

class NoArbitrageValidator:
    """无套利定价边界校验器 (PRD §金融数据常识检查)

    欧式期权必须满足:
    - 看涨: C ≥ max(0, S - K·e^(-rT))
    - 看跌: P ≥ max(0, K·e^(-rT) - S)
    - Call-Put 平价: C - P = S - K·e^(-rT)
    """

    def __init__(self, risk_free_rate: float = 0.05):
        self.r = risk_free_rate

    def validate(
        self,
        strikes: np.ndarray,
        spot: float,
        times_to_expiry: np.ndarray,
        market_prices: np.ndarray,
        option_types: np.ndarray,
    ) -> Tuple[bool, List[str], List[ValidationAuditEntry]]:
        """检查期权市场价是否在无套利理论边界内

        Args:
            strikes: 行权价数组
            spot: 标的现价
            times_to_expiry: 到期时间 (年)
            market_prices: 市场中间价 (bid+ask)/2 或结算价
            option_types: 期权类型数组

        Returns:
            (通过标志, 错误列表, 审计条目列表)
        """
        errors: List[str] = []
        audit_entries: List[ValidationAuditEntry] = []
        now = datetime.now().isoformat()
        n = len(strikes)

        if n == 0 or spot <= 0:
            return True, [], []

        is_call = np.array([t.upper() in ('CALL', 'C') for t in option_types])
        discount = np.exp(-self.r * times_to_expiry)

        # ── 看涨下限: C ≥ max(0, S - K·e^(-rT)) ──
        call_mask = is_call
        if np.any(call_mask):
            call_lower_bound = np.maximum(0, spot - strikes[call_mask] * discount[call_mask])
            call_violations = market_prices[call_mask] < call_lower_bound - 0.01  # 1 cent buffer
            n_viol = np.sum(call_violations)
            if n_viol > 0:
                errors.append(f"看涨期权低于无套利下限: {n_viol}/{np.sum(call_mask)} 合约")
                viol_indices = np.where(call_mask)[0][call_violations][:5]
                for idx in viol_indices:
                    audit_entries.append(ValidationAuditEntry(
                        timestamp=now, check_type="NO_ARBITRAGE", severity="ERROR",
                        field_name="call_lower_bound", expected_range=f"≥ {call_lower_bound[np.where(call_mask)[0][np.where(call_violations)[0][0]]]:.4f}",
                        actual_value=f"{market_prices[idx]:.4f}",
                        option_type="CALL", strike=float(strikes[idx]),
                        details=f"C={market_prices[idx]:.4f} < max(0, {spot:.2f}-{strikes[idx]:.2f}*e^(-rT))"
                    ))

        # ── 看跌下限: P ≥ max(0, K·e^(-rT) - S) ──
        put_mask = ~is_call
        if np.any(put_mask):
            put_lower_bound = np.maximum(0, strikes[put_mask] * discount[put_mask] - spot)
            put_violations = market_prices[put_mask] < put_lower_bound - 0.01
            n_viol = np.sum(put_violations)
            if n_viol > 0:
                errors.append(f"看跌期权低于无套利下限: {n_viol}/{np.sum(put_mask)} 合约")
                viol_indices = np.where(put_mask)[0][put_violations][:5]
                for idx in viol_indices:
                    audit_entries.append(ValidationAuditEntry(
                        timestamp=now, check_type="NO_ARBITRAGE", severity="ERROR",
                        field_name="put_lower_bound",
                        actual_value=f"{market_prices[idx]:.4f}",
                        option_type="PUT", strike=float(strikes[idx]),
                        details=f"P={market_prices[idx]:.4f} < max(0, K*e^(-rT)-S)"
                    ))

        is_valid = len(errors) == 0
        if is_valid:
            logger.info(f"无套利定价校验通过: {n} 合约 ✓")
        else:
            logger.warning(f"无套利定价校验失败: {len(errors)} 个错误")

        return is_valid, errors, audit_entries


# ═══════════════════════════════════════════
# 5. Isolation Forest 微观异常检测
# ═══════════════════════════════════════════

class IsolationForestDetector:
    """Isolation Forest 微观异常检测器 (PRD §微观异常检测与审计追踪)

    利用 Isolation Forest 等无监督算法监控隐含波动率曲面与 GEX 的历史分布。
    如果某日盘后 GEX 出现历史上从未见过的跳跃式极值 (≥10σ)，标记为"高置信度异常"。
    """

    # 异常检测阈值
    SIGMA_THRESHOLD = 10.0     # 标准差倍数 (≥10σ → 标记异常)
    CONTAMINATION = 0.05       # Isolation Forest 预期异常率 5%

    def __init__(self, contamination: float = CONTAMINATION):
        self.contamination = contamination
        self._model = None
        self._fitted = False
        self._historical_mean: Dict[str, float] = {}
        self._historical_std: Dict[str, float] = {}

    def fit(self, features: pd.DataFrame) -> None:
        """基于历史数据训练 Isolation Forest 模型

        Args:
            features: 历史特征 DataFrame，含 'net_gex', 'gex_call', 'gex_put',
                      'vix_spot', 'dix_value' 等列
        """
        if features.empty or len(features) < 20:
            logger.warning("历史数据不足 (需要 ≥20 天)，Isolation Forest 无法训练")
            return

        # 提取数值列
        numeric_cols = features.select_dtypes(include=[np.number]).columns.tolist()
        if len(numeric_cols) < 2:
            return

        X = features[numeric_cols].fillna(0).values

        # 计算历史均值和标准差 (用于 σ 级别检测)
        for col in numeric_cols:
            vals = features[col].dropna()
            if len(vals) > 0:
                self._historical_mean[col] = float(vals.mean())
                self._historical_std[col] = float(vals.std()) if vals.std() > 0 else 1.0

        if SKLEARN_AVAILABLE:
            try:
                self._model = IsolationForest(
                    contamination=self.contamination,
                    random_state=42,
                    n_estimators=100,
                )
                self._model.fit(X)
                self._fitted = True
                logger.info(f"Isolation Forest 训练完成: {len(X)} 样本, {len(numeric_cols)} 特征")
            except Exception as e:
                logger.warning(f"Isolation Forest 训练失败: {e}，降级到 σ 阈值检测")
                self._fitted = False
        else:
            logger.warning("scikit-learn 不可用，降级到 σ 阈值检测")

    def detect(
        self,
        current: Dict[str, float],
    ) -> Tuple[bool, List[str], List[ValidationAuditEntry]]:
        """检测当日数据是否存在极端异常

        Args:
            current: 当日指标字典，如 {'net_gex': -5e9, 'vix_spot': 25.0, ...}

        Returns:
            (通过标志, 错误列表, 审计条目列表)
        """
        errors: List[str] = []
        audit_entries: List[ValidationAuditEntry] = []
        now = datetime.now().isoformat()

        # ── σ 级别极端值检测 ──
        for key, value in current.items():
            if key in self._historical_mean and key in self._historical_std:
                mean = self._historical_mean[key]
                std = self._historical_std[key]
                if std > 0:
                    z_score = abs(value - mean) / std
                    if z_score >= self.SIGMA_THRESHOLD:
                        msg = f"极端异常检测: {key}={value:.2e}, Z-score={z_score:.1f}σ (≥{self.SIGMA_THRESHOLD}σ)"
                        errors.append(msg)
                        audit_entries.append(ValidationAuditEntry(
                            timestamp=now, check_type="ISO_FOREST", severity="ERROR",
                            field_name=key,
                            expected_range=f"|Z| < {self.SIGMA_THRESHOLD}σ",
                            actual_value=f"{value:.2e} (Z={z_score:.1f}σ)",
                            details=f"历史 μ={mean:.2e}, σ={std:.2e}"
                        ))

        # ── Isolation Forest 打分 (库可用且已训练时) ──
        if SKLEARN_AVAILABLE and self._fitted and self._model is not None:
            try:
                feature_keys = list(self._historical_mean.keys())
                if all(k in current for k in feature_keys):
                    X_curr = np.array([[current[k] for k in feature_keys]])
                    score = self._model.decision_function(X_curr)[0]
                    if score < -0.2:  # 负分表示异常
                        msg = f"Isolation Forest 标记异常: score={score:.4f}"
                        errors.append(msg)
                        audit_entries.append(ValidationAuditEntry(
                            timestamp=now, check_type="ISO_FOREST", severity="WARN",
                            field_name="anomaly_score",
                            expected_range="> -0.2",
                            actual_value=f"{score:.4f}",
                            details=str({k: f"{current[k]:.2e}" for k in feature_keys})
                        ))
            except Exception as e:
                logger.warning(f"Isolation Forest 检测失败: {e}")

        is_valid = len(errors) == 0
        if is_valid:
            logger.info("Isolation Forest 异常检测通过 ✓")
        else:
            logger.warning(f"Isolation Forest 检测到 {len(errors)} 个异常")

        return is_valid, errors, audit_entries


# ═══════════════════════════════════════════
# 6. 综合校验编排器 + 95% 通过率熔断
# ═══════════════════════════════════════════

class DataValidationPipeline:
    """综合数据校验编排器 (PRD §数据校验与金融常识审查模块)

    整合全部 5 项校验，计算总体通过率，执行 95% 通过率熔断。

    Attributes:
        pandera_validator: Pandera DataFrame 校验器
        greeks_validator: 希腊字母边界校验器
        parity_validator: 平价组合校验器
        arbitrage_validator: 无套利定价校验器
        if_detector: Isolation Forest 检测器
        audit_log: 累积审计日志
        historical_pass_rates: 历史通过率列表 (用于全局熔断)
    """

    # 全局通过率熔断阈值
    PASS_RATE_THRESHOLD: float = 0.95  # 95%
    # 熔断前需要的最小样本数
    MIN_SAMPLES_FOR_CIRCUIT = 5

    def __init__(self, risk_free_rate: float = 0.05):
        self.pandera_validator = PanderaValidator()
        self.greeks_validator = GreeksBoundsValidator()
        self.parity_validator = PutCallParityValidator()
        self.arbitrage_validator = NoArbitrageValidator(risk_free_rate=risk_free_rate)
        self.if_detector = IsolationForestDetector()
        self.audit_log: List[ValidationAuditEntry] = []
        self.historical_pass_rates: List[float] = []

    def run_full_validation(
        self,
        option_chain_df: pd.DataFrame,
        strikes: np.ndarray,
        spot: float,
        deltas: np.ndarray,
        gammas: np.ndarray,
        times_to_expiry: np.ndarray,
        market_prices: np.ndarray,
        option_types: np.ndarray,
        current_metrics: Optional[Dict[str, float]] = None,
    ) -> ValidationResult:
        """执行完整的五步数据校验流水线

        Args:
            option_chain_df: 期权链 DataFrame
            strikes: 行权价数组
            spot: 标的现价
            deltas: Delta 数组
            gammas: Gamma 数组
            times_to_expiry: 到期时间 (年)
            market_prices: 市场中间价
            option_types: 期权类型数组
            current_metrics: 当日指标 (用于 IF 检测)

        Returns:
            ValidationResult: 完整校验结果，含熔断标志
        """
        result = ValidationResult()
        result.total_checks = 5

        # ── Check 1: Pandera ──
        p_ok, p_errors, p_audit = self.pandera_validator.validate_option_chain(option_chain_df)
        if p_ok:
            result.passed_checks += 1
        else:
            result.failed_checks += 1
            result.errors.extend(p_errors)
        result.audit_entries.extend(p_audit)

        # ── Check 2: Greeks Bounds ──
        g_ok, g_errors, g_audit = self.greeks_validator.validate(
            strikes, spot, deltas, gammas, option_types
        )
        if g_ok:
            result.passed_checks += 1
        else:
            result.failed_checks += 1
            result.errors.extend(g_errors)
        result.audit_entries.extend(g_audit)

        # ── Check 3: Put-Call Parity ──
        pc_ok, pc_errors, pc_audit = self.parity_validator.validate(
            strikes, deltas, option_types
        )
        if pc_ok:
            result.passed_checks += 1
        else:
            result.failed_checks += 1
            result.errors.extend(pc_errors)
        result.audit_entries.extend(pc_audit)

        # ── Check 4: No-Arbitrage Bounds ──
        na_ok, na_errors, na_audit = self.arbitrage_validator.validate(
            strikes, spot, times_to_expiry, market_prices, option_types
        )
        if na_ok:
            result.passed_checks += 1
        else:
            result.failed_checks += 1
            result.errors.extend(na_errors)
        result.audit_entries.extend(na_audit)

        # ── Check 5: Isolation Forest ──
        if current_metrics:
            if_ok, if_errors, if_audit = self.if_detector.detect(current_metrics)
            if if_ok:
                result.passed_checks += 1
            else:
                result.failed_checks += 1
                result.errors.extend(if_errors)
            result.audit_entries.extend(if_audit)
        else:
            # 无指标数据，跳过 IF 检测
            result.passed_checks += 1

        # ── 计算通过率 ──
        result.pass_rate_pct = round(
            result.passed_checks / result.total_checks * 100, 1
        )
        result.passed = result.pass_rate_pct >= 80.0  # 单次至少 80% 通过

        # ── 95% 全局熔断判定 ──
        self.historical_pass_rates.append(result.pass_rate_pct)
        if len(self.historical_pass_rates) >= self.MIN_SAMPLES_FOR_CIRCUIT:
            recent_avg = np.mean(self.historical_pass_rates[-self.MIN_SAMPLES_FOR_CIRCUIT:])
            if recent_avg < self.PASS_RATE_THRESHOLD * 100:
                result.should_circuit_break = True
                result.circuit_break_reason = (
                    f"95%通过率熔断: 近{self.MIN_SAMPLES_FOR_CIRCUIT}次平均通过率 "
                    f"{recent_avg:.1f}% < {self.PASS_RATE_THRESHOLD*100:.0f}%"
                )
                logger.error(result.circuit_break_reason)

        # ── 累积审计日志 ──
        self.audit_log.extend(result.audit_entries)

        logger.info(
            f"数据校验完成: {result.passed_checks}/{result.total_checks} 通过 "
            f"({result.pass_rate_pct}%) | 熔断={'❌' if result.should_circuit_break else '✓'}"
        )

        return result

    def get_audit_log_json(self) -> str:
        """导出审计日志为 JSON 字符串"""
        return json.dumps(
            [e.__dict__ for e in self.audit_log],
            indent=2, ensure_ascii=False, default=str,
        )

    def clear_audit_log(self) -> None:
        """清空审计日志"""
        self.audit_log.clear()

    def reset_circuit_breaker(self) -> None:
        """重置熔断状态"""
        self.historical_pass_rates.clear()


# ═══════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════

def validate_option_chain(df: pd.DataFrame) -> Tuple[bool, List[str]]:
    """便捷函数: 仅 Pandera 校验期权链"""
    v = PanderaValidator()
    ok, errors, _ = v.validate_option_chain(df)
    return ok, errors


def quick_greeks_check(
    deltas: np.ndarray,
    gammas: np.ndarray,
    option_types: np.ndarray,
) -> Tuple[bool, List[str]]:
    """便捷函数: 仅希腊字母边界快速检查"""
    v = GreeksBoundsValidator()
    ok, errors, _ = v.validate(
        strikes=np.arange(len(deltas), dtype=float),  # dummy strikes
        spot=100.0,  # dummy spot
        deltas=deltas,
        gammas=gammas,
        option_types=option_types,
    )
    return ok, errors


def run_validation_pipeline(
    option_chain_df: pd.DataFrame,
    strikes: np.ndarray,
    spot: float,
    deltas: np.ndarray,
    gammas: np.ndarray,
    times_to_expiry: np.ndarray,
    market_prices: np.ndarray,
    option_types: np.ndarray,
) -> ValidationResult:
    """便捷函数: 一键运行完整校验流水线"""
    pipeline = DataValidationPipeline()
    return pipeline.run_full_validation(
        option_chain_df=option_chain_df,
        strikes=strikes,
        spot=spot,
        deltas=deltas,
        gammas=gammas,
        times_to_expiry=times_to_expiry,
        market_prices=market_prices,
        option_types=option_types,
    )
