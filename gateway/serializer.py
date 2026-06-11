"""
Multi-source Resonance V2.0 - Layer 2 序列化器

将 Layer 1 的降维向量 (Dict) 转换为 Pydantic 验证后的 JSON 字符串。
"""

import json
from typing import Dict, Any
from pydantic import ValidationError

from gateway.schemas import ResonanceSnapshot, GatewayEnvelope
from quant_logic.dimension_reducer import ResonanceVector
from utils.logger import getLogger

logger = getLogger('gateway.serializer')


class GatewaySerializer:
    """将 Layer 1 输出序列化为 Layer 2 标准 JSON"""

    @staticmethod
    def from_resonance_vector(
        vector: ResonanceVector,
        pipeline_run_id: str = "",
        processing_duration_ms: int = 0,
    ) -> GatewayEnvelope:
        """从 ResonanceVector 构建 GatewayEnvelope

        Args:
            vector: Layer 1 降维聚合器的输出
            pipeline_run_id: 流水线运行 ID
            processing_duration_ms: 处理耗时

        Returns:
            GatewayEnvelope: 已验证的数据信封
        """
        snapshot = ResonanceSnapshot(
            timestamp=vector.timestamp,
            underlying_asset=vector.underlying_asset,
            resonance_intensity_score=vector.resonance_intensity_score,
            resonance_signal_state=vector.resonance_signal_state,
            net_gamma_regime=vector.net_gamma_regime,
            gamma_flip_level=vector.gamma_flip_level,
            gamma_flip_proximity_pct=vector.gamma_flip_proximity_pct,
            gex_percentile=vector.gex_percentile,
            core_support_wall=vector.core_support_wall,
            core_resistance_wall=vector.core_resistance_wall,
            support_wall_strength=vector.support_wall_strength,
            dark_pool_dix_status=vector.dark_pool_dix_status,
            dark_pool_accumulation_regime=vector.dark_pool_accumulation_regime,
            dix_percentile=vector.dix_percentile,
            vix_term_structure_state=vector.vix_term_structure_state,
            vix_panic_premium_pct=vector.vix_panic_premium_pct,
            vanna_exposure_bias=vector.vanna_exposure_bias,
            crypto_leverage_state=vector.crypto_leverage_state,
            crypto_oi_change_pct=vector.crypto_oi_change_pct,
            hawkes_branching_state=vector.hawkes_branching_state,
            hawkes_branching_ratio=vector.hawkes_branching_ratio,
            data_quality_flag=vector.data_quality_flag,
            available_dimensions=vector.available_dimensions,
            missing_dimensions=vector.missing_dimensions,
            darkpool_source_status=vector.darkpool_source_status,
            darkpool_degradation_mode=vector.darkpool_degradation_mode,
            # P2-1: 跨资产共振
            cross_asset_coherence_score=vector.cross_asset_coherence_score,
            cross_asset_alignment_direction=vector.cross_asset_alignment_direction,
            cross_asset_resonance_strength=vector.cross_asset_resonance_strength,
        )

        envelope = GatewayEnvelope(
            pipeline_run_id=pipeline_run_id,
            processing_duration_ms=processing_duration_ms,
            snapshot=snapshot,
        )

        logger.info(f"序列化完成: {len(envelope.snapshot.to_compact_json())} 字节")
        return envelope

    @staticmethod
    def from_dict(
        data: Dict[str, Any],
        pipeline_run_id: str = "",
    ) -> GatewayEnvelope:
        """从原始字典构建 GatewayEnvelope（含 Pydantic 验证）

        Args:
            data: Layer 1 输出的原始字典
            pipeline_run_id: 流水线运行 ID

        Returns:
            GatewayEnvelope

        Raises:
            ValidationError: 数据不符合 Schema
        """
        snapshot = ResonanceSnapshot(**data)
        envelope = GatewayEnvelope(
            pipeline_run_id=pipeline_run_id,
            snapshot=snapshot,
        )
        return envelope

    @staticmethod
    def to_llm_prompt_json(envelope: GatewayEnvelope) -> str:
        """将信封序列化为供 LLM Prompt 注入的 JSON 字符串

        Args:
            envelope: 已验证的网关信封

        Returns:
            紧凑 JSON 字符串
        """
        return envelope.snapshot.model_dump_json(
            indent=2,
            exclude_none=True,
        )

    @staticmethod
    def to_file(envelope: GatewayEnvelope, file_path: str) -> None:
        """将信封持久化到文件（用于审计和回测）

        Args:
            envelope: 网关信封
            file_path: 输出 JSON 文件路径
        """
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(envelope.model_dump_json(indent=2))
        logger.info(f"网关快照已持久化: {file_path}")


# ──────────────────────────────────────────────
# 便捷函数
# ──────────────────────────────────────────────

def serialize_to_json(
    vector: ResonanceVector,
    run_id: str = "",
    duration_ms: int = 0,
) -> str:
    """便捷函数：一步完成序列化 → JSON 字符串"""
    serializer = GatewaySerializer()
    envelope = serializer.from_resonance_vector(vector, run_id, duration_ms)
    return serializer.to_llm_prompt_json(envelope)
