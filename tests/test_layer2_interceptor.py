"""
Phase 5.2.3 — Layer 2 Interceptor 单元测试

验证熔断机制：连续 N 次异常 → 阻止传递 → 生成容错 JSON。
"""

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gateway.schemas import ResonanceSnapshot, GatewayEnvelope, ErrorSnapshot
from gateway.interceptor import (
    GatewayInterceptor,
    InterceptionResult,
    InterceptionStatus,
    validate_and_intercept,
)


class TestInterceptionResult:
    """InterceptionResult 数据类测试"""

    def test_passthrough_result(self):
        """PASS_THROUGH 状态"""
        result = InterceptionResult(status=InterceptionStatus.PASS_THROUGH)
        assert result.is_passthrough is True
        assert result.is_degraded is False
        assert result.is_blocked is False

    def test_blocked_result(self):
        """BLOCKED 状态"""
        result = InterceptionResult(status=InterceptionStatus.BLOCKED)
        assert result.is_passthrough is False
        assert result.is_blocked is True

    def test_degraded_result(self):
        """DEGRADED 状态"""
        result = InterceptionResult(status=InterceptionStatus.DEGRADED)
        assert result.is_degraded is True

    def test_intercepted_at_auto_set(self):
        """拦截时间自动设置"""
        result = InterceptionResult(status=InterceptionStatus.PASS_THROUGH)
        assert result.intercepted_at != ""


class TestGatewayInterceptor:
    """GatewayInterceptor 测试"""

    def make_envelope(self, **snapshot_overrides) -> GatewayEnvelope:
        """构造测试用 GatewayEnvelope"""
        defaults = {
            "timestamp": "2026-06-11T16:30:00Z",
            "underlying_asset": "SPX",
            "resonance_intensity_score": 75,
            "resonance_signal_state": "Strong",
            "net_gamma_regime": "Positive Gamma",
            "gamma_flip_level": 5500.0,
            "gamma_flip_proximity_pct": -1.5,
            "gex_percentile": 70.0,
            "core_support_wall": 5200.0,
            "core_resistance_wall": 5800.0,
            "support_wall_strength": "Strong",
            "dark_pool_dix_status": "ACCUMULATION",
            "dark_pool_accumulation_regime": "Moderate Accumulation",
            "dix_percentile": 80.0,
            "vix_term_structure_state": "CONTANGO",
            "vix_panic_premium_pct": 3.0,
            "vanna_exposure_bias": "Neutral",
            "crypto_leverage_state": "NORMAL",
            "crypto_oi_change_pct": 0.0,
            "hawkes_branching_state": "SUBCRITICAL",
            "hawkes_branching_ratio": 0.5,
            "data_quality_flag": "NORMAL",
            "available_dimensions": 4,
            "missing_dimensions": [],
        }
        defaults.update(snapshot_overrides)
        snapshot = ResonanceSnapshot(**defaults)
        return GatewayEnvelope(
            pipeline_run_id="test-run",
            snapshot=snapshot,
        )

    # ── 正常放行测试 ──

    def test_valid_envelope_passes(self):
        """合法信封应被放行"""
        envelope = self.make_envelope()
        interceptor = GatewayInterceptor()
        result = interceptor.validate_and_intercept(envelope)
        assert result.is_passthrough is True
        assert result.envelope is not None

    def test_normal_data_quality_passes(self):
        """NORMAL 质量数据应被放行"""
        envelope = self.make_envelope(data_quality_flag="NORMAL")
        interceptor = GatewayInterceptor()
        result = interceptor.validate_and_intercept(envelope)
        assert result.is_passthrough is True

    # ── 降级测试 ──

    def test_degraded_data_quality_triggers_degraded(self):
        """DEGRADED 质量数据应触发降级"""
        envelope = self.make_envelope(data_quality_flag="DEGRADED")
        interceptor = GatewayInterceptor()
        result = interceptor.validate_and_intercept(envelope)
        assert result.is_degraded is True
        assert result.envelope is not None  # 仍传递数据

    # ── 阻止测试 ──

    def test_error_data_quality_triggers_block(self):
        """ERROR 质量数据应被阻止"""
        envelope = self.make_envelope(data_quality_flag="ERROR")
        interceptor = GatewayInterceptor()
        result = interceptor.validate_and_intercept(envelope)
        assert result.is_blocked is True
        assert result.error_snapshot is not None

    def test_blocked_result_has_error_snapshot(self):
        """阻止结果应包含 ErrorSnapshot"""
        envelope = self.make_envelope(data_quality_flag="ERROR")
        interceptor = GatewayInterceptor()
        result = interceptor.validate_and_intercept(envelope)
        assert isinstance(result.error_snapshot, ErrorSnapshot)
        assert result.error_snapshot.data_quality_flag == "ERROR"

    # ── 严格模式测试 ──

    def test_strict_mode_with_warnings(self):
        """严格模式：警告导致降级"""
        envelope = self.make_envelope(
            resonance_intensity_score=90,
            resonance_signal_state="Weak",  # 不一致产生警告
        )
        interceptor = GatewayInterceptor()
        result = interceptor.validate_and_intercept(envelope, strict_mode=True)
        assert result.is_degraded is True

    # ── 熔断测试 ──

    def test_circuit_breaker_triggers_after_threshold(self):
        """连续失败达到阈值后触发熔断"""
        interceptor = GatewayInterceptor(circuit_breaker_threshold=3)

        # 发送 3 个错误信封触发熔断
        for _ in range(3):
            envelope = self.make_envelope(data_quality_flag="ERROR")
            result = interceptor.validate_and_intercept(envelope)
            assert result.is_blocked is True

        # 第 4 个即使是正常信封也被阻止（熔断开启）
        normal_envelope = self.make_envelope(data_quality_flag="NORMAL")
        result = interceptor.validate_and_intercept(normal_envelope)
        assert result.is_blocked is True
        assert result.error_snapshot.error_code == "CIRCUIT_BREAKER_OPEN"

    def test_circuit_breaker_detection(self):
        """检测熔断状态"""
        interceptor = GatewayInterceptor(circuit_breaker_threshold=2)
        assert interceptor.is_circuit_broken() is False

        # 触发熔断
        for _ in range(3):
            envelope = self.make_envelope(data_quality_flag="ERROR")
            interceptor.validate_and_intercept(envelope)

        assert interceptor.is_circuit_broken() is True

    def test_reset_circuit(self):
        """手动重置熔断"""
        interceptor = GatewayInterceptor(circuit_breaker_threshold=2)

        for _ in range(3):
            envelope = self.make_envelope(data_quality_flag="ERROR")
            interceptor.validate_and_intercept(envelope)

        assert interceptor.is_circuit_broken() is True
        interceptor.reset_circuit()
        assert interceptor.is_circuit_broken() is False

    # ── 健康检查 ──

    def test_gateway_health(self):
        """网关健康状态报告"""
        interceptor = GatewayInterceptor()
        health = interceptor.get_gateway_health()
        assert health['module'] == 'gateway_interceptor'
        assert health['status'] in ('HEALTHY', 'DEGRADED', 'BROKEN')
        assert 'failure_count' in health
        assert 'is_circuit_broken' in health

    # ── 便捷函数测试 ──

    def test_validate_and_intercept_convenience(self):
        """便捷函数 validate_and_intercept"""
        envelope = self.make_envelope()
        result = validate_and_intercept(envelope)
        assert result.is_passthrough is True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
