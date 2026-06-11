"""
Phase 5.2.1 — Layer 2 Schema 单元测试

验证 Pydantic 模型对合法/非法输入的序列化/拒绝行为。
"""

import pytest
from datetime import datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gateway.schemas import ResonanceSnapshot, GatewayEnvelope, ErrorSnapshot


class TestResonanceSnapshot:
    """ResonanceSnapshot 模型测试"""

    def test_valid_snapshot_defaults(self):
        """测试默认值构建"""
        snapshot = ResonanceSnapshot()
        assert snapshot.resonance_intensity_score == 0
        assert snapshot.resonance_signal_state == "Weak"
        assert snapshot.net_gamma_regime == "Neutral"
        assert snapshot.data_quality_flag == "NORMAL"

    def test_valid_snapshot_full(self):
        """测试全字段有效构建"""
        data = {
            "timestamp": "2026-06-11T16:30:00Z",
            "underlying_asset": "SPX",
            "resonance_intensity_score": 85,
            "resonance_signal_state": "Extreme Confluence",
            "net_gamma_regime": "Positive Gamma",
            "gamma_flip_level": 5650.0,
            "gamma_flip_proximity_pct": -1.8,
            "gex_percentile": 85.0,
            "core_support_wall": 5500.0,
            "core_resistance_wall": 5800.0,
            "support_wall_strength": "Very Strong",
            "dark_pool_dix_status": "ACCUMULATION",
            "dark_pool_accumulation_regime": "Aggressive Accumulation",
            "dix_percentile": 90.0,
            "vix_term_structure_state": "BACKWARDATION",
            "vix_panic_premium_pct": 12.5,
            "vanna_exposure_bias": "Moderate Buying Bias",
            "crypto_leverage_state": "COMPLETED",
            "crypto_oi_change_pct": -12.0,
            "hawkes_branching_state": "SUBCRITICAL",
            "hawkes_branching_ratio": 0.5,
            "data_quality_flag": "NORMAL",
            "available_dimensions": 4,
            "missing_dimensions": [],
        }
        snapshot = ResonanceSnapshot(**data)
        assert snapshot.resonance_intensity_score == 85
        assert snapshot.resonance_signal_state == "Extreme Confluence"
        assert snapshot.core_support_wall == 5500.0

    def test_invalid_resonance_score_too_high(self):
        """测试共振得分越界 (>100)"""
        with pytest.raises(Exception):
            ResonanceSnapshot(resonance_intensity_score=150)

    def test_invalid_resonance_score_negative(self):
        """测试共振得分越界 (<0)"""
        with pytest.raises(Exception):
            ResonanceSnapshot(resonance_intensity_score=-10)

    def test_invalid_signal_state(self):
        """测试无效的共振信号状态"""
        with pytest.raises(Exception):
            ResonanceSnapshot(resonance_signal_state="INVALID_STATE")

    def test_invalid_gamma_regime(self):
        """测试无效的 Gamma 区间"""
        with pytest.raises(Exception):
            ResonanceSnapshot(net_gamma_regime="Super Gamma")

    def test_invalid_data_quality(self):
        """测试无效的数据质量标志"""
        with pytest.raises(Exception):
            ResonanceSnapshot(data_quality_flag="BROKEN")

    def test_is_safe_for_llm_normal(self):
        """测试 NORMAL 数据可安全传递给 LLM"""
        snapshot = ResonanceSnapshot(data_quality_flag="NORMAL")
        assert snapshot.is_safe_for_llm() is True

    def test_is_safe_for_llm_degraded(self):
        """测试 DEGRADED 数据可安全传递给 LLM"""
        snapshot = ResonanceSnapshot(data_quality_flag="DEGRADED")
        assert snapshot.is_safe_for_llm() is True

    def test_is_safe_for_llm_error(self):
        """测试 ERROR 数据不可传递给 LLM"""
        snapshot = ResonanceSnapshot(data_quality_flag="ERROR")
        assert snapshot.is_safe_for_llm() is False

    def test_to_compact_json(self):
        """测试紧凑 JSON 序列化"""
        snapshot = ResonanceSnapshot(
            resonance_intensity_score=85,
            underlying_asset="SPX",
        )
        json_str = snapshot.to_compact_json()
        assert '"resonance_intensity_score":85' in json_str
        assert '"underlying_asset":"SPX"' in json_str

    def test_default_lists(self):
        """测试默认列表字段"""
        snapshot = ResonanceSnapshot()
        assert snapshot.missing_dimensions == []


class TestGatewayEnvelope:
    """GatewayEnvelope 模型测试"""

    def test_valid_envelope(self):
        """测试有效信封构建"""
        snapshot = ResonanceSnapshot(resonance_intensity_score=42)
        envelope = GatewayEnvelope(
            pipeline_run_id="test-run-001",
            snapshot=snapshot,
        )
        assert envelope.schema_version == "2.0.0"
        assert envelope.pipeline_run_id == "test-run-001"
        assert envelope.snapshot.resonance_intensity_score == 42
        assert envelope.created_at != ""

    def test_envelope_auto_created_at(self):
        """测试 created_at 自动生成"""
        snapshot = ResonanceSnapshot()
        envelope = GatewayEnvelope(
            pipeline_run_id="test",
            snapshot=snapshot,
        )
        assert envelope.created_at != ""
        assert "T" in envelope.created_at  # ISO 格式

    def test_envelope_to_json(self):
        """测试信封 JSON 序列化"""
        snapshot = ResonanceSnapshot(resonance_intensity_score=75)
        envelope = GatewayEnvelope(
            pipeline_run_id="run-123",
            snapshot=snapshot,
        )
        json_str = envelope.model_dump_json()
        assert '"resonance_intensity_score":75' in json_str
        assert '"run-123"' in json_str


class TestErrorSnapshot:
    """ErrorSnapshot 模型测试"""

    def test_default_error(self):
        """测试默认错误快照"""
        error = ErrorSnapshot()
        assert error.status == "Data Feed Error"
        assert error.error_code == "DATA_FETCH_ERROR"
        assert error.data_quality_flag == "ERROR"

    def test_custom_error(self):
        """测试自定义错误快照"""
        error = ErrorSnapshot(
            error_code="CIRCUIT_BREAKER_OPEN",
            message="熔断已触发",
        )
        assert error.error_code == "CIRCUIT_BREAKER_OPEN"
        assert error.message == "熔断已触发"
        assert error.timestamp != ""  # 自动生成


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
