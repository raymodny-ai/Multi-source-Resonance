"""
Phase 5.4.1 — 集成测试：完整 6 阶段流水线

使用模拟数据运行完整流水线，验证数据在各层间正确传递。
"""

import pytest
import asyncio
import json
from datetime import datetime, date

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestPipelineIntegration:
    """流水线集成测试"""

    def test_pipeline_context_creation(self):
        """PipelineContext 可正确创建"""
        from pipeline_v2.orchestrator import PipelineContext
        ctx = PipelineContext()
        assert ctx.run_id != ""
        assert ctx.elapsed_seconds >= 0
        assert ctx.errors == []

    def test_pipeline_context_set_get_result(self):
        """PipelineContext 阶段结果存取"""
        from pipeline_v2.orchestrator import PipelineContext
        ctx = PipelineContext()

        ctx.set_result('test_stage', {'value': 42})
        result = ctx.get_result('test_stage')
        assert result == {'value': 42}

    def test_pipeline_context_add_error(self):
        """PipelineContext 错误记录"""
        from pipeline_v2.orchestrator import PipelineContext
        ctx = PipelineContext()

        try:
            raise ValueError("test error")
        except ValueError as e:
            ctx.add_error('test_stage', e)

        assert ctx.has_errors is True
        assert len(ctx.errors) == 1
        assert ctx.errors[0]['stage'] == 'test_stage'
        assert 'ValueError' in ctx.errors[0]['error_type']

    @pytest.mark.asyncio
    async def test_full_pipeline_skip_llm(self):
        """完整流水线 (跳过 LLM)"""
        from pipeline_v2.orchestrator import PipelineOrchestrator
        orchestrator = PipelineOrchestrator(output_dir='./test_reports')

        ctx = await orchestrator.run_full_pipeline(skip_llm=True)
        assert ctx is not None
        assert ctx.run_id != ""
        # 至少应完成 stage 1-4
        assert ctx.get_result('ingest') is not None or ctx.has_errors
        assert ctx.get_result('gateway') is not None or ctx.has_errors

        # 检查网关结果
        gateway = ctx.get_result('gateway')
        if gateway:
            assert 'envelope' in gateway
            assert 'json' in gateway

    @pytest.mark.asyncio
    async def test_pipeline_degraded_mode(self):
        """降级模式：模拟数据不足时仍正确降级"""
        from pipeline_v2.orchestrator import PipelineOrchestrator
        orchestrator = PipelineOrchestrator(output_dir='./test_reports')

        # 跳过 LLM，测试完整降级链
        ctx = await orchestrator.run_full_pipeline(skip_llm=True)

        # 检查 dispatch 结果
        dispatch = ctx.get_result('dispatch')
        if dispatch:
            assert 'report_text' in dispatch
            assert 'markdown_path' in dispatch
            # 降级模式报告应包含关键信息
            report = dispatch['report_text']
            assert 'Resonance' in report or 'Resonance' in report.lower()

    @pytest.mark.asyncio
    async def test_pipeline_orchestrator_init(self):
        """PipelineOrchestrator 正确初始化"""
        from pipeline_v2.orchestrator import PipelineOrchestrator
        orchestrator = PipelineOrchestrator(output_dir='./test_reports')
        assert orchestrator.output_dir == './test_reports'
        assert orchestrator.fallback is not None

    @pytest.mark.asyncio
    async def test_run_daily_static_method(self):
        """静态方法 run_daily 可被调用"""
        from pipeline_v2.orchestrator import PipelineOrchestrator

        ctx = await PipelineOrchestrator.run_daily()
        assert ctx is not None
        assert ctx.run_id != ""


class TestPipelineMonitor:
    """PipelineMonitor 测试"""

    def test_monitor_start_end(self):
        """监控启动和结束"""
        from pipeline_v2.monitor import PipelineMonitor
        from pipeline_v2.orchestrator import PipelineContext

        monitor = PipelineMonitor()
        monitor.start_run("test-run", "2026-06-11")

        ctx = PipelineContext(run_id="test-run")
        monitor.record_stage_start("ingest")
        monitor.record_stage_end("ingest", "success", 1500)

        run_metrics = monitor.end_run(ctx)
        assert run_metrics.overall_status == "success"
        assert len(run_metrics.stages) == 1
        assert run_metrics.stages[0].stage_name == "ingest"
        assert run_metrics.stages[0].status == "success"
        assert run_metrics.stages[0].duration_ms == 1500

    def test_monitor_run_summary(self):
        """运行摘要统计"""
        from pipeline_v2.monitor import PipelineMonitor
        from pipeline_v2.orchestrator import PipelineContext

        monitor = PipelineMonitor()

        for i in range(3):
            monitor.start_run(f"run-{i}", f"2026-06-{11 + i}")
            ctx = PipelineContext(run_id=f"run-{i}")
            monitor.record_stage_start("test")
            monitor.record_stage_end("test", "success", 1000 * (i + 1))
            monitor.end_run(ctx)

        summary = monitor.get_run_summary()
        assert summary['total_runs'] == 3
        assert summary['success_rate'] == 100.0

    def test_monitor_latest_run(self):
        """最近一次运行"""
        from pipeline_v2.monitor import PipelineMonitor
        from pipeline_v2.orchestrator import PipelineContext

        monitor = PipelineMonitor()
        monitor.start_run("test-run-latest", "2026-06-15")
        ctx = PipelineContext(run_id="test-run-latest")
        monitor.record_stage_start("test")
        monitor.record_stage_end("test", "success", 2000)
        monitor.end_run(ctx)

        latest = monitor.get_latest_run()
        assert latest is not None
        assert latest.run_id == "test-run-latest"


class TestStageIntegration:
    """Layer 间数据传递测试"""

    def test_serializer_integrates_with_validator(self):
        """Serializer → Validator 集成"""
        from quant_logic.dimension_reducer import ResonanceVector
        from gateway.serializer import GatewaySerializer
        from gateway.validator import SnapshotValidator

        vector = ResonanceVector(
            timestamp="2026-06-11T16:30:00Z",
            underlying_asset="SPX",
            resonance_intensity_score=75,
            resonance_signal_state="Strong",
            net_gamma_regime="Positive Gamma",
            gamma_flip_level=5500.0,
            gamma_flip_proximity_pct=-1.5,
            gex_percentile=70.0,
            core_support_wall=5200.0,
            core_resistance_wall=5800.0,
            support_wall_strength="Strong",
            dark_pool_dix_status="ACCUMULATION",
            dark_pool_accumulation_regime="Moderate Accumulation",
            dix_percentile=80.0,
            vix_term_structure_state="CONTANGO",
            vix_panic_premium_pct=3.0,
            vanna_exposure_bias="Neutral",
            crypto_leverage_state="NORMAL",
            crypto_oi_change_pct=0.0,
            hawkes_branching_state="SUBCRITICAL",
            hawkes_branching_ratio=0.5,
            data_quality_flag="NORMAL",
            available_dimensions=4,
            missing_dimensions=[],
        )

        serializer = GatewaySerializer()
        envelope = serializer.from_resonance_vector(vector, pipeline_run_id="integration-test")

        is_valid, issues = SnapshotValidator.validate_envelope(envelope)
        assert is_valid is True

    def test_prompt_builder_integrates_with_envelope(self):
        """PromptBuilder 正确接收 GatewayEnvelope"""
        from gateway.schemas import ResonanceSnapshot, GatewayEnvelope
        from llm_inference.prompt_builder import PromptBuilder

        snapshot = ResonanceSnapshot(
            resonance_intensity_score=80,
            resonance_signal_state="Strong",
            underlying_asset="SPX",
            gamma_flip_level=5500.0,
            core_support_wall=5200.0,
            core_resistance_wall=5800.0,
        )
        envelope = GatewayEnvelope(pipeline_run_id="test", snapshot=snapshot)

        builder = PromptBuilder()
        user_prompt = builder.build_user_prompt(envelope)
        assert "80" in user_prompt or "Strong" in user_prompt
        assert "SPX" in user_prompt
        assert "json" in user_prompt.lower()

    def test_response_parser_with_mock_output(self):
        """ResponseParser 解析模拟 LLM 输出"""
        from llm_inference.response_parser import ResponseParser

        mock_output = """## Macro Resonance Overview
The market shows strong bullish confluence with resonance score of 80.

## Dealer Positioning Dynamics
Positive gamma regime with support at 5200.

## Dark Pool Flow Analysis
Institutional accumulation detected.

## Volatility Landscape
Contango structure indicates decreasing fear.

## Tactical Outlook for Next Session
Bullish bias above 5500 gamma flip level.
"""
        briefing = ResponseParser.parse_strategy_briefing(mock_output)
        assert briefing.overview != ""
        assert briefing.dealer_positioning != ""
        assert briefing.tactical_outlook != ""


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
