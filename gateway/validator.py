"""
Multi-source Resonance V2.0 - Layer 2 数据验证器

对 Layer 1 输出的降维数据进行严格校验，确保所有字段在合法范围内。
检测 NaN/Inf/None 异常值，验证 Schema 合规性。
"""

import math
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime

from gateway.schemas import ResonanceSnapshot, GatewayEnvelope, ErrorSnapshot
from utils.logger import getLogger

logger = getLogger('gateway.validator')


class SnapshotValidator:
    """共振快照验证器

    在数据进入 Layer 3 之前执行严格的数值范围检查和完整性校验。
    """

    # 字段合法范围定义
    FIELD_RANGES: Dict[str, Tuple[float, float]] = {
        'resonance_intensity_score': (0, 100),
        'gamma_flip_level': (0, float('inf')),
        'gamma_flip_proximity_pct': (-100, 100),
        'gex_percentile': (0, 100),
        'core_support_wall': (0, float('inf')),
        'core_resistance_wall': (0, float('inf')),
        'dix_percentile': (0, 100),
        'vix_panic_premium_pct': (-100, 100),
        'crypto_oi_change_pct': (-100, 100),
        'hawkes_branching_ratio': (0, 1),
        'available_dimensions': (0, 5),
    }

    # 允许的字符串枚举值
    ALLOWED_STRINGS: Dict[str, set] = {
        'resonance_signal_state': {"Extreme Confluence", "Strong", "Moderate", "Weak"},
        'net_gamma_regime': {"High Positive Gamma", "Positive Gamma", "Neutral",
                            "Negative Gamma", "Deep Negative Gamma"},
        'dark_pool_dix_status': {"ACCUMULATION", "DISTRIBUTION", "Neutral"},
        'dark_pool_accumulation_regime': {"Aggressive Accumulation", "Moderate Accumulation",
                                          "Neutral", "Moderate Distribution", "Aggressive Distribution"},
        'vix_term_structure_state': {"CONTANGO", "BACKWARDATION", "NEUTRAL"},
        'vanna_exposure_bias': {"High IV Crush Buying Risk", "Moderate Buying Bias",
                               "Neutral", "Moderate Selling Bias", "High IV Crush Selling Risk"},
        'crypto_leverage_state': {"COMPLETED", "IN_PROGRESS", "NORMAL"},
        'hawkes_branching_state': {"SUBCRITICAL", "CRITICAL", "SUPERCRITICAL", "INSUFFICIENT_DATA"},
        'support_wall_strength': {"Very Strong", "Strong", "Moderate", "Weak", "None"},
        'data_quality_flag': {"NORMAL", "DEGRADED", "ERROR"},
    }

    @classmethod
    def validate_snapshot(cls, snapshot: ResonanceSnapshot) -> Tuple[bool, List[str]]:
        """验证 ResonanceSnapshot 所有字段的合法性

        检查内容：
        1. 数值字段范围内检查
        2. NaN / Inf 检测
        3. 字符串枚举值校验
        4. 必需字段非空检查
        5. 数据一致性交叉校验

        Args:
            snapshot: Layer 1 输出经 Pydantic 验证后的 ResonanceSnapshot

        Returns:
            Tuple[bool, List[str]]: (是否通过, 错误/警告列表)
        """
        errors: List[str] = []
        warnings: List[str] = []

        # ── 1. 数值范围检查 ──
        for field_name, (min_val, max_val) in cls.FIELD_RANGES.items():
            value = getattr(snapshot, field_name, None)
            if value is None:
                errors.append(f"缺失字段: {field_name}")
                continue

            if isinstance(value, float):
                if math.isnan(value):
                    errors.append(f"NaN 检测: {field_name}")
                    continue
                if math.isinf(value):
                    errors.append(f"Inf 检测: {field_name}")
                    continue

            if value < min_val or value > max_val:
                errors.append(
                    f"数值越界: {field_name}={value} 超出 [{min_val}, {max_val}]"
                )

        # ── 2. 字符串枚举校验 ──
        for field_name, allowed in cls.ALLOWED_STRINGS.items():
            value = getattr(snapshot, field_name, None)
            if value is None:
                errors.append(f"缺失字符串字段: {field_name}")
                continue
            if value not in allowed:
                warnings.append(
                    f"未知枚举值: {field_name}='{value}' (允许: {allowed})"
                )

        # ── 3. 必需字段非空检查 ──
        required_strings = ['timestamp', 'underlying_asset']
        for field_name in required_strings:
            value = getattr(snapshot, field_name, None)
            if not value:
                errors.append(f"必需字段为空: {field_name}")

        # ── 4. 数据一致性交叉校验 ──
        # resonance_intensity_score 与 resonance_signal_state 一致性
        score = snapshot.resonance_intensity_score
        state = snapshot.resonance_signal_state
        expected_state = cls._expected_signal_state(score)
        if state != expected_state:
            warnings.append(
                f"信号状态不一致: score={score} 期望={expected_state} 实际={state}"
            )

        # available_dimensions 与 missing_dimensions 一致性
        if snapshot.available_dimensions >= 5 and len(snapshot.missing_dimensions) > 0:
            warnings.append(f"available_dimensions={snapshot.available_dimensions} 但 missing_dimensions 非空")
        if snapshot.available_dimensions < 5 and len(snapshot.missing_dimensions) == 0:
            warnings.append(f"available_dimensions={snapshot.available_dimensions}<5 但 missing_dimensions 为空")

        # 时间戳格式检查
        if snapshot.timestamp:
            try:
                datetime.fromisoformat(snapshot.timestamp.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                warnings.append(f"时间戳格式异常: {snapshot.timestamp}")

        is_valid = len(errors) == 0
        all_issues = errors + warnings

        if errors:
            logger.warning(f"快照验证失败: {len(errors)}个错误, {len(warnings)}个警告")
            for err in errors:
                logger.warning(f"  [ERROR] {err}")
        elif warnings:
            logger.info(f"快照验证通过(有警告): {len(warnings)}个警告")
            for warn in warnings:
                logger.info(f"  [WARN] {warn}")
        else:
            logger.info("快照验证完全通过 ✓")

        return is_valid, all_issues

    @classmethod
    def validate_envelope(cls, envelope: GatewayEnvelope) -> Tuple[bool, List[str]]:
        """验证 GatewayEnvelope 整体合规性

        包括快照内容验证 + 信封元数据验证。

        Args:
            envelope: 网关信封

        Returns:
            Tuple[bool, List[str]]: (是否通过, 问题列表)
        """
        all_issues: List[str] = []

        # 验证快照内容
        is_valid, snapshot_issues = cls.validate_snapshot(envelope.snapshot)
        all_issues.extend(snapshot_issues)

        # 验证信封元数据
        if not envelope.schema_version:
            all_issues.append("缺失 schema_version")
        if not envelope.pipeline_run_id:
            all_issues.append("缺失 pipeline_run_id")
        if envelope.processing_duration_ms < 0:
            all_issues.append(f"processing_duration_ms 为负: {envelope.processing_duration_ms}")

        # 验证快照与信封时间一致性
        if envelope.snapshot.timestamp and envelope.created_at:
            try:
                snap_ts_str = envelope.snapshot.timestamp.replace('Z', '+00:00')
                env_ts_str = envelope.created_at.replace('Z', '+00:00')
                snap_ts = datetime.fromisoformat(snap_ts_str)
                env_ts = datetime.fromisoformat(env_ts_str)
                # 确保两个 datetime 都是 offset-aware 或 offset-naive
                if snap_ts.tzinfo is not None:
                    from datetime import timezone
                    snap_ts = snap_ts.astimezone(timezone.utc).replace(tzinfo=None)
                if env_ts.tzinfo is not None:
                    from datetime import timezone
                    env_ts = env_ts.astimezone(timezone.utc).replace(tzinfo=None)
                diff_seconds = abs((env_ts - snap_ts).total_seconds())
                if diff_seconds > 3600:  # 超过1小时
                    all_issues.append(f"快照与信封时间差过大: {diff_seconds:.0f}秒")
            except (ValueError, AttributeError, TypeError):
                pass

        # 判断有效性：存在硬性错误（缺失字段、NaN、越界）则无效
        has_errors = any(
            keyword in i
            for i in all_issues
            for keyword in ['缺失', 'NaN', 'Inf', '越界', 'pipeline_run_id', 'schema_version', 'processing_duration_ms']
        )
        is_valid = not has_errors
        return is_valid, all_issues

    @classmethod
    def validate_schema_compliance(cls, data: Dict[str, Any]) -> Tuple[bool, Optional[ResonanceSnapshot], List[str]]:
        """验证原始字典是否符合 Schema 定义

        与 Pydantic 模型定义对比，确保 JSON 结构完整。

        Args:
            data: Layer 1 输出的原始字典

        Returns:
            Tuple[bool, Optional[ResonanceSnapshot], List[str]]:
                (是否合规, 验证后的快照(合规时), 错误列表)
        """
        from pydantic import ValidationError

        errors: List[str] = []

        try:
            snapshot = ResonanceSnapshot(**data)
        except ValidationError as e:
            for err in e.errors():
                loc = '.'.join(str(x) for x in err['loc'])
                errors.append(f"Pydantic 验证失败 [{loc}]: {err['msg']}")
            return False, None, errors

        # Pydantic 验证通过后，执行额外检查
        is_valid, extra_issues = cls.validate_snapshot(snapshot)
        errors.extend(extra_issues)

        if not is_valid:
            return False, snapshot, errors

        return True, snapshot, errors

    @classmethod
    def detect_anomalies(cls, snapshot: ResonanceSnapshot) -> Dict[str, Any]:
        """检测数据中的潜在异常（不阻断传递，仅标记）

        用于运行时监控和质量报告。

        Args:
            snapshot: 已验证的快照

        Returns:
            异常检测结果字典: {
                'has_nan': bool,
                'has_inf': bool,
                'out_of_range': [...],
                'suspicious_combinations': [...]
            }
        """
        result = {
            'has_nan': False,
            'has_inf': False,
            'out_of_range': [],
            'suspicious_combinations': [],
        }

        # 扫描所有数值字段
        numeric_fields = {
            'resonance_intensity_score', 'gamma_flip_level', 'gamma_flip_proximity_pct',
            'gex_percentile', 'core_support_wall', 'core_resistance_wall',
            'dix_percentile', 'vix_panic_premium_pct', 'crypto_oi_change_pct',
            'hawkes_branching_ratio', 'available_dimensions',
        }

        for field_name in numeric_fields:
            value = getattr(snapshot, field_name, None)
            if value is None:
                continue
            if isinstance(value, float):
                if math.isnan(value):
                    result['has_nan'] = True
                    result['out_of_range'].append(f"{field_name}=NaN")
                if math.isinf(value):
                    result['has_inf'] = True
                    result['out_of_range'].append(f"{field_name}=Inf")

        # 可疑组合检测
        # 高共振得分 + 低数据质量
        if snapshot.resonance_intensity_score > 70 and snapshot.data_quality_flag == "DEGRADED":
            result['suspicious_combinations'].append(
                "高共振得分在数据降级状态下产生，可信度受限"
            )

        # 极度恐慌 + 正Gamma = 罕见但可能极端反转
        if (snapshot.vix_term_structure_state == "BACKWARDATION"
                and "Positive" in snapshot.net_gamma_regime
                and snapshot.vix_panic_premium_pct > 10):
            result['suspicious_combinations'].append(
                "极度Backwardation + 正Gamma: 潜在极端反转信号"
            )

        return result

    # ──────────────────────────────────────────────
    # 辅助方法
    # ──────────────────────────────────────────────

    @staticmethod
    def _expected_signal_state(score: int) -> str:
        """根据共振得分返回期望的信号状态"""
        if score >= 85:
            return "Extreme Confluence"
        elif score >= 70:
            return "Strong"
        elif score >= 50:
            return "Moderate"
        return "Weak"

    @staticmethod
    def create_error_snapshot(error_code: str, message: str) -> ErrorSnapshot:
        """创建标准化的错误快照"""
        return ErrorSnapshot(
            status="Data Feed Error",
            error_code=error_code,
            message=message,
            data_quality_flag="ERROR",
        )


# ──────────────────────────────────────────────
# 便捷函数
# ──────────────────────────────────────────────

def validate_snapshot(snapshot: ResonanceSnapshot) -> Tuple[bool, List[str]]:
    """便捷函数：验证 ResonanceSnapshot"""
    return SnapshotValidator.validate_snapshot(snapshot)


def validate_schema_compliance(data: Dict[str, Any]) -> Tuple[bool, Optional[ResonanceSnapshot], List[str]]:
    """便捷函数：验证字典 Schema 合规性"""
    return SnapshotValidator.validate_schema_compliance(data)


def validate_envelope(envelope: GatewayEnvelope) -> Tuple[bool, List[str]]:
    """便捷函数：验证 GatewayEnvelope"""
    return SnapshotValidator.validate_envelope(envelope)
