"""
Multi-source Resonance V2.0 - Layer 2 网关 Schema 定义

使用 Pydantic v2 定义严格的 JSON 数据契约。
所有从 Layer 1 到 Layer 3 的数据必须通过此 Schema 验证。
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class ResonanceSnapshot(BaseModel):
    """共振快照 — Layer 2 的标准 JSON 契约

    仅包含约 15 个核心字段，将 Layer 1 的百万级数据压缩为此结构。
    LLM 仅接收此结构的序列化 JSON，绝不接触原始数据。
    """

    # 基础元数据
    timestamp: str = Field(
        default="",
        description="盘后时间戳 (ISO 8601)",
        examples=["2026-06-11T16:30:00Z"],
    )
    underlying_asset: str = Field(
        default="SPX",
        description="标的资产代码",
        examples=["SPX", "SPY", "QQQ"],
    )

    # 共振评分模块
    resonance_intensity_score: int = Field(
        default=0,
        ge=0,
        le=100,
        description="多源共振强度得分 (0-100)",
    )
    resonance_signal_state: str = Field(
        default="Weak",
        description="共振信号状态",
        examples=["Extreme Confluence", "Strong", "Moderate", "Weak"],
    )

    # 期权微观结构 (GEX)
    net_gamma_regime: str = Field(
        default="Neutral",
        description="净 Gamma 区间状态",
        examples=["High Positive Gamma", "Positive Gamma", "Neutral", "Negative Gamma", "Deep Negative Gamma"],
    )
    gamma_flip_level: float = Field(
        default=0.0,
        description="Gamma 翻转点价格",
    )
    gamma_flip_proximity_pct: float = Field(
        default=0.0,
        description="现价距离翻转点百分比 (%)",
    )
    gex_percentile: float = Field(
        default=50.0,
        ge=0.0,
        le=100.0,
        description="GEX 历史百分位",
    )

    # 关键防线判定
    core_support_wall: float = Field(
        default=0.0,
        description="核心支撑位 (最大 Put Wall 行权价)",
    )
    core_resistance_wall: float = Field(
        default=0.0,
        description="核心阻力位 (最大 Call Wall 行权价)",
    )
    support_wall_strength: str = Field(
        default="None",
        description="支撑墙强度",
        examples=["Very Strong", "Strong", "Moderate", "Weak", "None"],
    )

    # 暗盘流动性状态
    dark_pool_dix_status: str = Field(
        default="Neutral",
        description="暗盘 DIX 状态",
        examples=["ACCUMULATION", "DISTRIBUTION", "Neutral"],
    )
    dark_pool_accumulation_regime: str = Field(
        default="Neutral",
        description="吸筹/派发分类",
        examples=[
            "Aggressive Accumulation", "Moderate Accumulation",
            "Neutral", "Moderate Distribution", "Aggressive Distribution"
        ],
    )
    dix_percentile: float = Field(
        default=50.0,
        ge=0.0,
        le=100.0,
        description="DIX 历史百分位",
    )

    # 波动率动态
    vix_term_structure_state: str = Field(
        default="Neutral",
        description="VIX 期限结构状态",
        examples=["CONTANGO", "BACKWARDATION", "NEUTRAL"],
    )
    vix_panic_premium_pct: float = Field(
        default=0.0,
        description="VIX 恐慌溢价百分比 (%)",
    )
    vanna_exposure_bias: str = Field(
        default="Neutral",
        description="Vanna 暴露偏差",
        examples=["High IV Crush Buying Risk", "Moderate Buying Bias",
                  "Neutral", "Moderate Selling Bias", "High IV Crush Selling Risk"],
    )

    # 加密市场金丝雀
    crypto_leverage_state: str = Field(
        default="NORMAL",
        description="加密杠杆清洗状态",
        examples=["COMPLETED", "IN_PROGRESS", "NORMAL"],
    )
    crypto_oi_change_pct: float = Field(
        default=0.0,
        description="加密持仓量变化百分比 (%)",
    )

    # Hawkes Process
    hawkes_branching_state: str = Field(
        default="SUBCRITICAL",
        description="Hawkes 分支比状态",
        examples=["SUBCRITICAL", "CRITICAL", "SUPERCRITICAL", "INSUFFICIENT_DATA"],
    )
    hawkes_branching_ratio: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Hawkes 分支比 (0-1)",
    )

    # 数据质量
    data_quality_flag: str = Field(
        default="NORMAL",
        description="数据质量标志",
        examples=["NORMAL", "DEGRADED", "ERROR"],
    )
    available_dimensions: int = Field(
        default=5,
        ge=0,
        le=5,
        description="可用维度数量",
    )
    missing_dimensions: List[str] = Field(
        default_factory=list,
        description="缺失维度列表",
    )

    # 跨资产共振 (P2-1)
    cross_asset_coherence_score: float = Field(
        default=50.0,
        ge=0.0,
        le=100.0,
        description="跨资产一致性得分 (0-100)",
    )
    cross_asset_alignment_direction: str = Field(
        default="NEUTRAL",
        description="跨资产对齐方向",
        examples=["BULLISH", "BEARISH", "NEUTRAL"],
    )
    cross_asset_resonance_strength: str = Field(
        default="None",
        description="跨资产共振强度描述",
    )

    @field_validator('resonance_signal_state')
    @classmethod
    def validate_signal_state(cls, v: str) -> str:
        allowed = {"Extreme Confluence", "Strong", "Moderate", "Weak"}
        if v not in allowed:
            raise ValueError(f"resonance_signal_state must be one of {allowed}")
        return v

    @field_validator('net_gamma_regime')
    @classmethod
    def validate_gamma_regime(cls, v: str) -> str:
        allowed = {"High Positive Gamma", "Positive Gamma", "Neutral",
                   "Negative Gamma", "Deep Negative Gamma"}
        if v not in allowed:
            raise ValueError(f"net_gamma_regime must be one of {allowed}")
        return v

    @field_validator('data_quality_flag')
    @classmethod
    def validate_data_quality(cls, v: str) -> str:
        allowed = {"NORMAL", "DEGRADED", "ERROR"}
        if v not in allowed:
            raise ValueError(f"data_quality_flag must be one of {allowed}")
        return v

    def is_safe_for_llm(self) -> bool:
        """检查数据是否安全传递给 LLM"""
        return self.data_quality_flag in ("NORMAL", "DEGRADED")

    def to_compact_json(self) -> str:
        """输出紧凑 JSON 字符串（最小化 Token 消耗）"""
        return self.model_dump_json(exclude_none=True)


class GatewayEnvelope(BaseModel):
    """网关信封 — 包装 ResonanceSnapshot 并附加元数据"""

    schema_version: str = Field(
        default="2.0.0",
        description="Schema 版本号",
    )
    pipeline_run_id: str = Field(
        default="",
        description="流水线运行 ID (UUID)",
    )
    processing_duration_ms: int = Field(
        default=0,
        description="处理耗时 (毫秒)",
    )
    snapshot: ResonanceSnapshot = Field(
        description="共振快照数据",
    )
    created_at: str = Field(
        default="",
        description="创建时间 (ISO 8601)",
    )

    def model_post_init(self, __context):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


class ErrorSnapshot(BaseModel):
    """容错快照 — 当数据异常时的标准化错误 JSON"""

    status: str = Field(
        default="Data Feed Error",
        description="错误状态",
    )
    error_code: str = Field(
        default="DATA_FETCH_ERROR",
        description="错误代码",
    )
    message: str = Field(
        default="",
        description="错误描述",
    )
    timestamp: str = Field(
        default="",
        description="错误时间戳",
    )
    data_quality_flag: str = Field(
        default="ERROR",
        description="数据质量标志",
    )

    def model_post_init(self, __context):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()
