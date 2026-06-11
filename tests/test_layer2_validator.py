"""
Phase 5.2.2 — Layer 2 Validator 单元测试

验证 NaN/Inf/None 检测和异常拦截。
"""

import pytest
import math

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gateway.schemas import ResonanceSnapshot, GatewayEnvelope
from gateway.validator import SnapshotValidator


class TestSnapshotValidator:
    """SnapshotValidator 测试"""

    def make_snapshot(self, **overrides) -> ResonanceSnapshot:
        """构造测试用 ResonanceSnapshot"""
        defaults = {
            "timestamp": "2026-06-11T16:30:00Z",
            "underlying_asset": "SPX",
            "resonance_intensity_score": 50,
            "resonance_signal_state": "Moderate",
            "net_gamma_regime": "Neutral",
            "gamma_flip_level": 5500.0,
            "gamma_flip_proximity_pct": 1.5,
            "gex_percentile": 50.0,
            "core_support_wall": 5200.0,
            "core_resistance_wall": 5800.0,
            "support_wall_strength": "Moderate",
            "dark_pool_dix_status": "Neutral",
            "dark_pool_accumulation_regime": "Neutral",
            "dix_percentile": 50.0,
            "vix_term_structure_state": "NEUTRAL",
            "vix_panic_premium_pct": 0.0,
            "vanna_exposure_bias": "Neutral",
            "crypto_leverage_state": "NORMAL",
            "crypto_oi_change_pct": 0.0,
            "hawkes_branching_state": "SUBCRITICAL",
            "hawkes_branching_ratio": 0.5,
            "data_quality_flag": "NORMAL",
            "available_dimensions": 5,
            "missing_dimensions": [],
        }
        defaults.update(overrides)
        return ResonanceSnapshot(**defaults)

    # ── 合法数据测试 ──

    def test_valid_snapshot_passes(self):
        """合法快照应完全通过验证"""
        snapshot = self.make_snapshot()
        is_valid, issues = SnapshotValidator.validate_snapshot(snapshot)
        assert is_valid is True
        assert len(issues) == 0

    def test_extreme_confluence_snapshot(self):
        """极端共振快照应通过验证"""
        snapshot = self.make_snapshot(
            resonance_intensity_score=92,
            resonance_signal_state="Extreme Confluence",
            net_gamma_regime="High Positive Gamma",
        )
        is_valid, issues = SnapshotValidator.validate_snapshot(snapshot)
        assert is_valid is True

    # ── 缺失字段测试 ──

    def test_missing_timestamp(self):
        """缺失时间戳应被检测"""
        snapshot = self.make_snapshot(timestamp="")
        is_valid, issues = SnapshotValidator.validate_snapshot(snapshot)
        assert is_valid is False
        assert any("timestamp" in str(i).lower() for i in issues)

    def test_missing_underlying_asset(self):
        """缺失标的信息应被检测"""
        snapshot = self.make_snapshot(underlying_asset="")
        is_valid, issues = SnapshotValidator.validate_snapshot(snapshot)
        assert is_valid is False
        assert any("underlying_asset" in str(i).lower() for i in issues)

    # ── 范围越界测试 ──

    def test_score_out_of_range_high(self):
        """共振得分超过上限"""
        snapshot = self.make_snapshot()
        object.__setattr__(snapshot, 'resonance_intensity_score', 150)
        is_valid, issues = SnapshotValidator.validate_snapshot(snapshot)
        assert is_valid is False
        assert any("resonance_intensity_score" in i for i in issues)

    def test_hawkes_ratio_out_of_range(self):
        """Hawkes 分支比超过 1.0"""
        snapshot = self.make_snapshot()
        object.__setattr__(snapshot, 'hawkes_branching_ratio', 1.5)
        is_valid, issues = SnapshotValidator.validate_snapshot(snapshot)
        assert is_valid is False
        assert any("hawkes_branching_ratio" in i for i in issues)

    # ── 枚举值测试 ──

    def test_unknown_signal_state_generates_warning(self):
        """未知信号状态产生警告"""
        # 使用 object.__setattr__ 绕过 Pydantic validator
        snapshot = self.make_snapshot()
        object.__setattr__(snapshot, 'resonance_signal_state', 'Mega Strong')
        is_valid, issues = SnapshotValidator.validate_snapshot(snapshot)
        assert is_valid is True  # 硬错误不算
        assert any("Mega Strong" in i for i in issues)

    # ── 一致性交叉校验 ──

    def test_score_state_mismatch(self):
        """得分与状态不一致"""
        snapshot = self.make_snapshot(
            resonance_intensity_score=90,
            resonance_signal_state="Weak",  # 不一致
        )
        is_valid, issues = SnapshotValidator.validate_snapshot(snapshot)
        assert is_valid is True  # 只是警告
        assert any("不一致" in i for i in issues)

    def test_dimensions_mismatch(self):
        """维度数字与缺失列表不一致"""
        snapshot = self.make_snapshot(
            available_dimensions=5,
            missing_dimensions=["CROSS_ASSET"],  # 标记 5 个维度都可用却列出缺失
        )
        is_valid, issues = SnapshotValidator.validate_snapshot(snapshot)
        assert is_valid is True  # 警告
        assert any("available_dimensions" in i for i in issues)

    # ── Schema 合规性测试 ──

    def test_validate_schema_compliance_valid_dict(self):
        """合规字典应通过 Schema 验证"""
        data = {
            "timestamp": "2026-06-11T16:30:00Z",
            "underlying_asset": "SPX",
            "resonance_intensity_score": 75,
            "resonance_signal_state": "Strong",
            "net_gamma_regime": "Positive Gamma",
            "gamma_flip_level": 5500.0,
            "dark_pool_dix_status": "Neutral",
            "dark_pool_accumulation_regime": "Moderate Accumulation",
            "vix_term_structure_state": "CONTANGO",
            "vix_panic_premium_pct": 3.5,
            "vanna_exposure_bias": "Neutral",
            "crypto_leverage_state": "NORMAL",
            "crypto_oi_change_pct": 0.0,
            "hawkes_branching_state": "SUBCRITICAL",
            "hawkes_branching_ratio": 0.5,
            "data_quality_flag": "NORMAL",
            "support_wall_strength": "Moderate",
        }
        is_valid, snapshot, errors = SnapshotValidator.validate_schema_compliance(data)
        assert is_valid is True, f"Errors: {errors}"
        assert snapshot is not None
        assert snapshot.resonance_intensity_score == 75

    def test_validate_schema_compliance_invalid_dict(self):
        """不合规字典应被拒绝"""
        data = {
            "resonance_intensity_score": -999,  # 非法值
            "resonance_signal_state": "INVALID",
        }
        is_valid, snapshot, errors = SnapshotValidator.validate_schema_compliance(data)
        assert is_valid is False
        assert len(errors) > 0

    # ── 异常检测 ──

    def test_detect_anomalies_normal(self):
        """正常快照无异常"""
        snapshot = self.make_snapshot()
        anomalies = SnapshotValidator.detect_anomalies(snapshot)
        assert anomalies['has_nan'] is False
        assert anomalies['has_inf'] is False
        assert len(anomalies['out_of_range']) == 0

    def test_detect_suspicious_combination(self):
        """检测可疑组合：高得分 + 低质量"""
        snapshot = self.make_snapshot(
            resonance_intensity_score=85,
            data_quality_flag="DEGRADED",
        )
        anomalies = SnapshotValidator.detect_anomalies(snapshot)
        assert len(anomalies['suspicious_combinations']) > 0

    # ── 信封验证 ──

    def test_validate_envelope(self):
        """验证完整信封"""
        snapshot = self.make_snapshot()
        envelope = GatewayEnvelope(
            pipeline_run_id="test-run",
            snapshot=snapshot,
        )
        is_valid, issues = SnapshotValidator.validate_envelope(envelope)
        assert is_valid is True

    def test_validate_envelope_missing_run_id(self):
        """信封缺少 run_id"""
        snapshot = self.make_snapshot()
        envelope = GatewayEnvelope(
            pipeline_run_id="",  # 空
            snapshot=snapshot,
        )
        is_valid, issues = SnapshotValidator.validate_envelope(envelope)
        assert is_valid is False
        assert any("pipeline_run_id" in i for i in issues)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
