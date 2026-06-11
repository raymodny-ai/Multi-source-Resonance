"""
Multi-source Resonance V2.0 - Layer 1 多因子降维聚合器

该模块负责将第一层的海量微观计算结果（百万级期权链数据）降维为 10-15 个
核心键值对（共振向量），供 Layer 2 网关封装后传给 Layer 3 LLM 使用。

核心职责：
1. 从 GEX 计算、暗盘验证、VIX 分析、加密监控中接收中间结果
2. 计算各维度的历史百分位排名
3. 执行多因子加权聚合，输出极限压缩的共振信号向量
4. 绝不暴露原始数据（如完整期权链、逐笔暗盘记录）给上层

该模块为 Layer 1 边界组件，输出将直接流向 Layer 2 网关。
"""

import numpy as np
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime

from utils.logger import getLogger

logger = getLogger('dimension_reducer')


@dataclass
class ResonanceVector:
    """共振向量 — Layer 1 的最终输出结构

    仅包含约 15 个字段，将百万级数据压缩到此结构。
    此结构直接流向 Layer 2 的 JSON 序列化网关。
    """
    # 基础元数据
    timestamp: str = ""                          # ISO 格式盘后时间戳
    underlying_asset: str = "SPX"                # 标的资产代码

    # 共振评分
    resonance_intensity_score: int = 0           # 多源共振强度得分 (0-100)
    resonance_signal_state: str = "Weak"         # 共振信号状态

    # 期权微观结构 (GEX)
    net_gamma_regime: str = "Neutral"            # 净 Gamma 区间状态
    gamma_flip_level: float = 0.0                # Gamma 翻转点价格
    gamma_flip_proximity_pct: float = 0.0        # 现价距离翻转点百分比
    gex_percentile: float = 50.0                 # GEX 历史百分位

    # 关键防线
    core_support_wall: float = 0.0               # 核心支撑位（最大 Put Wall）
    core_resistance_wall: float = 0.0            # 核心阻力位（最大 Call Wall）
    support_wall_strength: str = "Weak"          # 支撑墙强度描述

    # 暗盘流动性
    dark_pool_dix_status: str = "Neutral"        # 暗盘 DIX 状态
    dark_pool_accumulation_regime: str = "Neutral"  # 吸筹/派发分类
    dix_percentile: float = 50.0                 # DIX 历史百分位

    # 波动率动态
    vix_term_structure_state: str = "Neutral"    # VIX 期限结构状态
    vix_panic_premium_pct: float = 0.0           # 恐慌溢价百分比
    vanna_exposure_bias: str = "Neutral"         # Vanna 暴露偏差

    # 加密市场
    crypto_leverage_state: str = "NORMAL"        # 加密杠杆清洗状态
    crypto_oi_change_pct: float = 0.0            # 加密 OI 变化百分比

    # Hawkes Process
    hawkes_branching_state: str = "SUBCRITICAL"  # Hawkes 分支比状态
    hawkes_branching_ratio: float = 0.5          # Hawkes 分支比

    # 数据质量
    data_quality_flag: str = "NORMAL"            # NORMAL / DEGRADED / ERROR
    available_dimensions: int = 4                # 可用维度数量
    missing_dimensions: List[str] = field(default_factory=list)  # 缺失维度列表

    # 跨资产共振 (P2-1)
    cross_asset_coherence_score: float = 50.0    # 跨资产一致性得分 (0-100)
    cross_asset_alignment_direction: str = "NEUTRAL"  # 对齐方向 BULLISH/BEARISH/NEUTRAL
    cross_asset_resonance_strength: str = "None" # 共振强度描述
    cross_asset_alignment_count: int = 0         # 方向对齐的资产数量


class DimensionReducer:
    """多因子降维聚合引擎

    接收各维度量化分析结果，执行百分位排名计算和多因子聚合，
    输出高度压缩的 ResonanceVector。

    Attributes:
        gex_total_weight: GEX 维度在共振总分中的权重
        darkpool_weight: 暗盘维度权重
        vix_weight: VIX 维度权重
        crypto_weight: 加密维度权重
    """

    def __init__(
        self,
        gex_weight: float = 0.30,
        darkpool_weight: float = 0.25,
        vix_weight: float = 0.15,
        crypto_weight: float = 0.15,
        cross_asset_weight: float = 0.15,
    ):
        self.gex_weight = gex_weight
        self.darkpool_weight = darkpool_weight
        self.vix_weight = vix_weight
        self.crypto_weight = crypto_weight
        self.cross_asset_weight = cross_asset_weight

    def compute_resonance_vector(
        self,
        underlying_asset: str,
        spot_price: float,
        # GEX 维度输入
        net_gex: float,
        gex_regime: str,
        gamma_flip_level: float,
        put_wall_strikes: List[float],
        call_wall_strikes: List[float],
        gex_by_strike: Dict[float, float],
        # 暗盘维度输入
        dix_value: float,
        dix_signal: bool,
        darkpool_aggregated: bool,
        accumulation_regime: str,
        # VIX 维度输入
        vx1: float,
        vx2: float,
        vix_spot: float,
        vix_state: str,
        panic_premium: float,
        vanna_net_exposure: float,
        # 加密维度输入
        crypto_leverage_state: str,
        crypto_oi_change_pct: float,
        funding_rate: float,
        # Hawkes 输入
        hawkes_ratio: float,
        hawkes_state: str,
        # 跨资产共振输入 (P2-1)
        cross_asset_coherence: float = 50.0,
        cross_asset_direction: str = "NEUTRAL",
        cross_asset_strength: str = "None",
        cross_asset_aligned: int = 0,
        # 历史百分位数据（来自数据库，可选）
        gex_historical: Optional[List[float]] = None,
        dix_historical: Optional[List[float]] = None,
        # 数据质量
        available_dimensions: int = 4,
        missing_dimensions: Optional[List[str]] = None,
    ) -> ResonanceVector:
        """执行完整的多因子降维聚合

        Args:
            各维度中间计算结果（详见参数列表）

        Returns:
            ResonanceVector: 压缩后的共振向量
        """
        if missing_dimensions is None:
            missing_dimensions = []

        # ── 1. 历史百分位计算 ──
        gex_pct = self._compute_percentile(net_gex, gex_historical)
        dix_pct = self._compute_percentile(dix_value, dix_historical)

        # ── 2. 各维度子评分 (0-100) ──
        gex_sub_score = self._score_gex_dimension(
            net_gex, gex_regime, gamma_flip_level, spot_price, gex_pct
        )
        darkpool_sub_score = self._score_darkpool_dimension(
            dix_value, dix_signal, darkpool_aggregated, accumulation_regime, dix_pct
        )
        vix_sub_score = self._score_vix_dimension(
            vx1, vx2, vix_spot, vix_state, panic_premium
        )
        crypto_sub_score = self._score_crypto_dimension(
            crypto_leverage_state, crypto_oi_change_pct, funding_rate
        )
        cross_asset_sub_score = self._score_cross_asset_dimension(
            cross_asset_coherence, cross_asset_direction, cross_asset_aligned
        )

        # ── 3. 加权总共振得分 ──
        total_score = (
            gex_sub_score * self.gex_weight
            + darkpool_sub_score * self.darkpool_weight
            + vix_sub_score * self.vix_weight
            + crypto_sub_score * self.crypto_weight
            + cross_asset_sub_score * self.cross_asset_weight
        )
        total_score = min(100, max(0, round(total_score)))

        # ── 4. 共振信号强度判定 ──
        signal_state = self._classify_resonance(total_score, available_dimensions)

        # ── 5. 关键价格位 ──
        support_wall = max(put_wall_strikes) if put_wall_strikes else 0.0
        resistance_wall = min(call_wall_strikes) if call_wall_strikes else 0.0
        support_strength = self._classify_wall_strength(
            support_wall, gex_by_strike
        )

        # ── 6. Flip 距离 ──
        flip_proximity = 0.0
        if gamma_flip_level > 0 and spot_price > 0:
            flip_proximity = round((spot_price - gamma_flip_level) / spot_price * 100, 2)

        # ── 7. Vanna 暴露判定 ──
        vanna_bias = self._classify_vanna_exposure(vanna_net_exposure)

        # ── 8. 数据质量标志 ──
        data_quality = self._determine_data_quality(
            available_dimensions, missing_dimensions
        )

        # ── 9. 构建共振向量 ──
        vector = ResonanceVector(
            timestamp=datetime.now().isoformat(),
            underlying_asset=underlying_asset,
            resonance_intensity_score=total_score,
            resonance_signal_state=signal_state,
            net_gamma_regime=gex_regime,
            gamma_flip_level=round(gamma_flip_level, 2),
            gamma_flip_proximity_pct=flip_proximity,
            gex_percentile=round(gex_pct, 1),
            core_support_wall=round(support_wall, 2),
            core_resistance_wall=round(resistance_wall, 2),
            support_wall_strength=support_strength,
            dark_pool_dix_status="ACCUMULATION" if dix_signal else "DISTRIBUTION" if dix_value < 45 else "Neutral",
            dark_pool_accumulation_regime=accumulation_regime,
            dix_percentile=round(dix_pct, 1),
            vix_term_structure_state=vix_state,
            vix_panic_premium_pct=round(panic_premium, 2),
            vanna_exposure_bias=vanna_bias,
            crypto_leverage_state=crypto_leverage_state,
            crypto_oi_change_pct=round(crypto_oi_change_pct, 2),
            hawkes_branching_state=hawkes_state,
            hawkes_branching_ratio=round(hawkes_ratio, 2),
            data_quality_flag=data_quality,
            available_dimensions=available_dimensions,
            missing_dimensions=missing_dimensions,
            # P2-1: 跨资产共振
            cross_asset_coherence_score=round(cross_asset_coherence, 1),
            cross_asset_alignment_direction=cross_asset_direction,
            cross_asset_resonance_strength=cross_asset_strength,
            cross_asset_alignment_count=cross_asset_aligned,
        )

        logger.info(
            f"降维完成: 共振得分={total_score}/100, "
            f"状态={signal_state}, 质量={data_quality}"
        )
        return vector

    # ──────────────────────────────────────────────
    # 私有方法：各维度评分 (0-100)
    # ──────────────────────────────────────────────

    def _score_gex_dimension(
        self,
        net_gex: float,
        regime: str,
        flip_level: float,
        spot: float,
        percentile: float,
    ) -> float:
        """GEX 维度评分 (满分 100)"""
        score = 0.0

        # 正 Gamma + 跌破 Flip = 强反转信号
        if "Positive" in regime and spot < flip_level:
            score += 40
        elif "Negative" in regime:
            score += 10  # 负 Gamma = 高风险
        else:
            score += 25

        # 历史极值加分
        if percentile < 10:  # GEX 处于历史最低 10%
            score += 30
        elif percentile < 25:
            score += 20
        elif percentile > 75:  # GEX 处于历史最高 25%
            score += 30
        elif percentile > 50:
            score += 15

        return min(100, score)

    def _score_darkpool_dimension(
        self,
        dix: float,
        dix_signal: bool,
        aggregated: bool,
        regime: str,
        percentile: float,
    ) -> float:
        """暗盘维度评分 (满分 100)"""
        score = 0.0

        if "Aggressive Accumulation" == regime:
            score += 50
        elif "Moderate Accumulation" == regime:
            score += 35
        elif "Neutral" == regime:
            score += 15

        if dix_signal:
            score += 20
        if aggregated:
            score += 20

        if percentile > 80:
            score += 10
        elif percentile < 20:
            score -= 10

        return min(100, max(0, score))

    def _score_vix_dimension(
        self,
        vx1: float,
        vx2: float,
        spot: float,
        state: str,
        panic: float,
    ) -> float:
        """VIX 维度评分 (满分 100)"""
        score = 0.0

        if state == "CONTANGO":
            score += 40  # 恐慌退潮
        elif state == "BACKWARDATION":
            score += 15  # 恐慌中
        else:
            score += 25

        # 恐慌溢价
        if panic > 15:
            score += 30  # 极端恐慌 → 潜在反转
        elif panic > 5:
            score += 20
        elif panic < -5:
            score += 40  # 市场过度安逸 → 反向指标

        return min(100, score)

    def _score_crypto_dimension(
        self,
        leverage_state: str,
        oi_change: float,
        funding: float,
    ) -> float:
        """加密维度评分 (满分 100)"""
        score = 0.0

        if leverage_state == "COMPLETED":
            score += 50  # 去杠杆完成
        elif leverage_state == "IN_PROGRESS":
            score += 30  # 去杠杆中
        else:
            score += 10

        if oi_change < -15:
            score += 30  # OI 大幅清洗
        elif oi_change < -5:
            score += 15

        if funding >= 0:
            score += 20

        return min(100, score)

    def _score_cross_asset_dimension(
        self,
        coherence_score: float,
        alignment_direction: str,
        alignment_count: int,
    ) -> float:
        """跨资产共振维度评分 (满分 100) (P2-1)

        跨资产一致性得分越高，代表多市场同时指向同一方向，
        趋势可持续性越强。
        """
        score = 0.0

        # 基于一致性得分的基准分
        if coherence_score >= 85:
            score += 40  # 极强跨资产共振
        elif coherence_score >= 70:
            score += 30
        elif coherence_score >= 55:
            score += 15
        else:
            score += 5   # 弱/无共振

        # 方向对齐加分
        if alignment_direction == "BULLISH" and alignment_count >= 3:
            score += 35  # 多资产同时看涨
        elif alignment_direction == "BEARISH" and alignment_count >= 3:
            score += 15  # 多资产同时看跌(风险信号)
        elif alignment_count >= 2:
            score += 15

        # 极端一致性加分
        if coherence_score >= 90:
            score += 25
        elif coherence_score <= 10:
            score += 20  # 极端分歧→反向指标

        return min(100, score)

    # ──────────────────────────────────────────────
    # 私有方法：分类器
    # ──────────────────────────────────────────────

    @staticmethod
    def _classify_resonance(score: int, available: int) -> str:
        """判定共振信号强度"""
        if score >= 85:
            return "Extreme Confluence"
        elif score >= 70:
            return "Strong"
        elif score >= 50:
            return "Moderate"
        else:
            return "Weak"

    @staticmethod
    def _classify_wall_strength(
        wall_price: float,
        gex_by_strike: Dict[float, float],
    ) -> str:
        """判定支撑/阻力墙强度"""
        if wall_price <= 0 or not gex_by_strike:
            return "None"
        gex_at_wall = abs(gex_by_strike.get(wall_price, 0))
        if gex_at_wall > 5e9:
            return "Very Strong"
        elif gex_at_wall > 1e9:
            return "Strong"
        elif gex_at_wall > 1e8:
            return "Moderate"
        return "Weak"

    @staticmethod
    def _classify_vanna_exposure(net_vanna: float) -> str:
        """判定 Vanna 暴露偏差"""
        if abs(net_vanna) < 1e6:
            return "Neutral"
        if net_vanna > 5e7:
            return "High IV Crush Buying Risk"
        elif net_vanna > 1e7:
            return "Moderate Buying Bias"
        elif net_vanna < -5e7:
            return "High IV Crush Selling Risk"
        elif net_vanna < -1e7:
            return "Moderate Selling Bias"
        return "Neutral"

    @staticmethod
    def _determine_data_quality(
        available: int,
        missing: List[str],
    ) -> str:
        """判定数据质量标志 (P2-1: 升级为5维判定)"""
        if available >= 5 and not missing:
            return "NORMAL"
        elif available >= 3:
            return "DEGRADED"
        return "ERROR"

    @staticmethod
    def _compute_percentile(
        value: float,
        historical: Optional[List[float]],
    ) -> float:
        """计算当前值在历史数据中的百分位"""
        if not historical or len(historical) < 10:
            return 50.0
        arr = np.array(historical)
        return float(np.sum(arr <= value) / len(arr) * 100)


# ──────────────────────────────────────────────
# 便捷函数
# ──────────────────────────────────────────────

def reduce_dimensions(
    spot_price: float,
    net_gex: float,
    gex_regime: str,
    gamma_flip: float,
    put_walls: List[float],
    call_walls: List[float],
    gex_strike_map: Dict[float, float],
    dix_value: float,
    dix_signal: bool,
    darkpool_agg: bool,
    accumulation: str,
    vx1: float,
    vx2: float,
    vix_spot: float,
    vix_state: str,
    panic: float,
    vanna: float,
    crypto_state: str,
    crypto_oi: float,
    funding: float,
    hawkes_ratio: float,
    hawkes_state: str,
    cross_asset_coherence: float = 50.0,
    cross_asset_direction: str = "NEUTRAL",
    cross_asset_strength: str = "None",
    cross_asset_aligned: int = 0,
) -> ResonanceVector:
    """便捷接口：一键降维"""
    reducer = DimensionReducer()
    return reducer.compute_resonance_vector(
        underlying_asset="SPX",
        spot_price=spot_price,
        net_gex=net_gex,
        gex_regime=gex_regime,
        gamma_flip_level=gamma_flip,
        put_wall_strikes=put_walls,
        call_wall_strikes=call_walls,
        gex_by_strike=gex_strike_map,
        dix_value=dix_value,
        dix_signal=dix_signal,
        darkpool_aggregated=darkpool_agg,
        accumulation_regime=accumulation,
        vx1=vx1,
        vx2=vx2,
        vix_spot=vix_spot,
        vix_state=vix_state,
        panic_premium=panic,
        vanna_net_exposure=vanna,
        crypto_leverage_state=crypto_state,
        crypto_oi_change_pct=crypto_oi,
        funding_rate=funding,
        hawkes_ratio=hawkes_ratio,
        hawkes_state=hawkes_state,
        # P2-1: 跨资产共振
        cross_asset_coherence=cross_asset_coherence,
        cross_asset_direction=cross_asset_direction,
        cross_asset_strength=cross_asset_strength,
        cross_asset_aligned=cross_asset_aligned,
    )
