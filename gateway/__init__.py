"""
Multi-source Resonance V2.0 - Layer 2 JSON 上下文网关

严格的数据契约层，将 Layer 1 的降维向量封装为 LLM 可安全解析的 JSON。

核心组件:
- ResonanceSnapshot: Pydantic v2 数据模型 (≈25 个核心字段)
- GatewayEnvelope: 包装快照并附加流水线元数据
- GatewaySerializer: Layer 1 输出 → Pydantic 验证 → JSON 字符串
- SnapshotValidator: 范围/NaN/Inf/Schema 合规性校验
- GatewayInterceptor: 数据质量门禁 + 熔断机制
- ErrorSnapshot: 标准化容错 JSON

数据流:
    Layer 1 (ResonanceVector) → Serializer → GatewayEnvelope
    → Validator → Interceptor → Layer 3 (LLM Prompt JSON)
"""

from gateway.schemas import ResonanceSnapshot, GatewayEnvelope, ErrorSnapshot
from gateway.serializer import GatewaySerializer, serialize_to_json
from gateway.validator import (
    SnapshotValidator,
    validate_snapshot,
    validate_schema_compliance,
    validate_envelope,
)
from gateway.interceptor import (
    GatewayInterceptor,
    InterceptionResult,
    InterceptionStatus,
    validate_and_intercept,
)

__all__ = [
    # Schemas
    'ResonanceSnapshot',
    'GatewayEnvelope',
    'ErrorSnapshot',
    # Serializer
    'GatewaySerializer',
    'serialize_to_json',
    # Validator
    'SnapshotValidator',
    'validate_snapshot',
    'validate_schema_compliance',
    'validate_envelope',
    # Interceptor
    'GatewayInterceptor',
    'InterceptionResult',
    'InterceptionStatus',
    'validate_and_intercept',
]
