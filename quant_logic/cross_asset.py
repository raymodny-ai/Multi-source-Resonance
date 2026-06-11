"""
Multi-source Resonance V2.0 - Cross-Asset Resonance Engine (P2-1)

跨资产共振检测引擎。在原有单资产（SPX）四维评分基础上，
引入跨资产类别之间的相关性分析，检测多市场同时指向同一方向的共振信号。

核心职责：
1. 计算跨资产相关性矩阵（SPX GEX ↔ Crypto OI ↔ VIX Structure ↔ Darkpool DIX）
2. 检测多资产维度的方向对齐（Regime Alignment）
3. 输出跨资产共振一致性得分（Cross-Asset Coherence Score, 0-100）
4. 绝不暴露原始资产价格或持仓细节给上层

理论基础：
- 当 SPX 期权做市商对冲方向、加密杠杆清洗状态、VIX 恐慌结构和暗盘机构流向
  同时指向同一方向时，市场出现罕见的"多源共振"。
- 跨资产共振强度直接与后续趋势的可持续性正相关。

该模块为 Layer 1 边界组件，输出直接流向 dimension_reducer。
"""

import numpy as np
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from utils.logger import getLogger

logger = getLogger('cross_asset')


@dataclass
class CrossAssetSignal:
    """单个资产的归一化信号

    Attributes:
        asset_name: 资产名称 (e.g. GEX, CRYPTO, VIX, DARKPOOL)
        raw_value: 原始信号值
        normalized: 归一化值 [-1, 1] 正值=看涨/吸筹, 负值=看跌/派发
        confidence: 信号置信度 [0, 1]
        regime: 当前市场区间状态
    """
    asset_name: str
    raw_value: float = 0.0
    normalized: float = 0.0
    confidence: float = 0.5
    regime: str = "Neutral"


@dataclass
class CrossAssetResonanceResult:
    """跨资产共振分析结果

    Attributes:
        timestamp: 分析时间戳
        coherence_score: 跨资产一致性得分 (0-100)
        alignment_count: 方向对齐的资产数量
        total_assets: 总资产数量
        alignment_direction: 对齐方向 (BULLISH/BEARISH/NEUTRAL)
        correlation_matrix: 资产间相关性矩阵
        asset_signals: 各资产归一化信号列表
        resonance_strength: 共振强度描述
    """
    timestamp: str = ""
    coherence_score: float = 0.0
    alignment_count: int = 0
    total_assets: int = 4
    alignment_direction: str = "NEUTRAL"
    correlation_matrix: Optional[Dict[str, Dict[str, float]]] = None
    asset_signals: List[CrossAssetSignal] = field(default_factory=list)
    resonance_strength: str = "None"


class CrossAssetResonanceEngine:
    """跨资产共振检测引擎

    基于 PRD V2.0 §多源共振体系的深层逻辑: 当多个独立维度同时指向
    同一方向时，系统赋予极高的共振得分。

    评分逻辑:
    1. 计算各资产的归一化信号方向 [-1, 1]
    2. 建立资产间 Pairwise 方向一致性矩阵
    3. 加权聚合为一致性得分 (0-100)
    4. 判定共振强度等级

    Attributes:
        min_confidence: 最低信号置信度阈值
        alignment_threshold: 方向对齐判定阈值
        weights: 各资产维度的权重
    """

    def __init__(
        self,
        gex_weight: float = 0.35,
        crypto_weight: float = 0.25,
        vix_weight: float = 0.20,
        darkpool_weight: float = 0.20,
        min_confidence: float = 0.3,
        alignment_threshold: float = 0.15,
    ):
        self.weights = {
            'GEX': gex_weight,
            'CRYPTO': crypto_weight,
            'VIX': vix_weight,
            'DARKPOOL': darkpool_weight,
        }
        self.min_confidence = min_confidence
        self.alignment_threshold = alignment_threshold

    def analyze(
        self,
        # GEX 维度
        net_gex: float,
        gex_regime: str,
        gex_percentile: float,
        # 加密维度
        crypto_leverage_state: str,
        crypto_oi_change_pct: float,
        crypto_funding_rate: float,
        # VIX 维度
        vix_spot: float,
        vix_term_structure: str,
        vix_panic_premium: float,
        # 暗盘维度
        dix_value: float,
        accumulation_regime: str,
        dix_percentile: float,
        # 可选历史百分位
        gex_historical: Optional[List[float]] = None,
        ) -> CrossAssetResonanceResult:
        """执行完整跨资产共振分析

        Args:
            net_gex: 净 GEX 值 (美元)
            gex_regime: GEX 区间 (Positive/Negative Gamma)
            gex_percentile: GEX 历史百分位
            crypto_leverage_state: 加密杠杆状态
            crypto_oi_change_pct: 加密 OI 变化率 (%)
            crypto_funding_rate: 资金费率
            vix_spot: VIX 现货值
            vix_term_structure: VIX 期限结构 (CONTANGO/BACKWARDATION)
            vix_panic_premium: VIX 恐慌溢价 (%)
            dix_value: DIX 暗盘买入强度
            accumulation_regime: 吸筹/派发分类
            dix_percentile: DIX 历史百分位
            gex_historical: GEX 历史值列表（用于百分位计算）

        Returns:
            CrossAssetResonanceResult
        """
        # ── 1. 构建各资产归一化信号 ──
        signals = []

        # GEX 信号: 正GEX=看涨(+), 负GEX=看跌(-)
        gex_signal = self._normalize_gex(net_gex, gex_regime, gex_percentile)
        gex_signal.asset_name = 'GEX'
        signals.append(gex_signal)

        # 加密信号: 去杠杆完成=risk-on(+), 高杠杆=risk-off(-)
        crypto_signal = self._normalize_crypto(
            crypto_leverage_state, crypto_oi_change_pct, crypto_funding_rate
        )
        crypto_signal.asset_name = 'CRYPTO'
        signals.append(crypto_signal)

        # VIX 信号: Contango=恐慌退潮(+), Backwardation=恐慌(-)
        vix_signal = self._normalize_vix(
            vix_spot, vix_term_structure, vix_panic_premium
        )
        vix_signal.asset_name = 'VIX'
        signals.append(vix_signal)

        # 暗盘信号: 吸筹=看涨(+), 派发=看跌(-)
        dp_signal = self._normalize_darkpool(
            dix_value, accumulation_regime, dix_percentile
        )
        dp_signal.asset_name = 'DARKPOOL'
        signals.append(dp_signal)

        # ── 2. 计算 Pairwise 方向一致性 ──
        corr_matrix = self._compute_pairwise_alignment(signals)
        alignment_count, alignment_dir = self._count_alignment(signals)

        # ── 3. 加权聚合一致性得分 ──
        coherence_score = self._compute_coherence(signals, corr_matrix)

        # ── 4. 判定共振强度 ──
        strength = self._classify_strength(coherence_score, alignment_count)

        return CrossAssetResonanceResult(
            timestamp=datetime.now().isoformat(),
            coherence_score=round(coherence_score, 1),
            alignment_count=alignment_count,
            total_assets=len(signals),
            alignment_direction=alignment_dir,
            correlation_matrix=corr_matrix,
            asset_signals=signals,
            resonance_strength=strength,
        )

    # ──────────────────────────────────────────────
    # 归一化方法：各资产信号 → [-1, 1]
    # ──────────────────────────────────────────────

    def _normalize_gex(
        self, net_gex: float, regime: str, percentile: float
    ) -> CrossAssetSignal:
        """GEX 归一化: 正Gamma+跌破Flip → 强看涨(+1)"""
        normalized = 0.0
        confidence = 0.5

        if "Negative" in regime:
            normalized = -0.6
            confidence = 0.7
        elif "Positive" in regime:
            normalized = 0.4
            confidence = 0.6

        # 历史极值增强
        if percentile < 10:
            normalized -= 0.3  # 极端负GEX → 更强看跌
            confidence = min(1.0, confidence + 0.2)
        elif percentile > 90:
            normalized += 0.3  # 极端正GEX → 更强看涨
            confidence = min(1.0, confidence + 0.2)

        normalized = max(-1.0, min(1.0, normalized))

        return CrossAssetSignal(
            asset_name='GEX',
            raw_value=net_gex,
            normalized=round(normalized, 3),
            confidence=round(confidence, 3),
            regime=regime,
        )

    def _normalize_crypto(
        self, leverage_state: str, oi_change: float, funding: float
    ) -> CrossAssetSignal:
        """加密归一化: 去杠杆完成 → 看涨(+), 高杠杆 → 看跌(-)"""
        normalized = 0.0
        confidence = 0.5

        if leverage_state == 'COMPLETED':
            normalized = 0.7
            confidence = 0.8
        elif leverage_state == 'IN_PROGRESS':
            normalized = 0.3
            confidence = 0.6
        elif leverage_state == 'HIGH_LEVERAGE':
            normalized = -0.5
            confidence = 0.7

        # OI 变化率调整
        if oi_change < -15:
            normalized += 0.2  # OI 大幅清洗 → 看涨
        elif oi_change > 15:
            normalized -= 0.2  # OI 膨胀 → 看跌

        # 资金费率调整
        if funding < -0.005:
            normalized -= 0.15
        elif funding > 0.005:
            normalized += 0.1

        normalized = max(-1.0, min(1.0, normalized))

        return CrossAssetSignal(
            asset_name='CRYPTO',
            raw_value=oi_change,
            normalized=round(normalized, 3),
            confidence=round(confidence, 3),
            regime=leverage_state,
        )

    def _normalize_vix(
        self, vix_spot: float, term_structure: str, panic_premium: float
    ) -> CrossAssetSignal:
        """VIX 归一化: Contango=恐慌退潮(+), Backwardation=恐慌(-)"""
        normalized = 0.0
        confidence = 0.5

        if term_structure == 'CONTANGO':
            normalized = 0.5
            confidence = 0.7
        elif term_structure == 'BACKWARDATION':
            normalized = -0.6
            confidence = 0.7

        # VIX 绝对值调整
        if vix_spot > 30:
            normalized -= 0.2  # 高VIX → 更恐慌
            confidence += 0.1
        elif vix_spot < 15:
            normalized += 0.2  # 低VIX → 过度安逸(反向指标)
            confidence += 0.1

        # 恐慌溢价调整
        if panic_premium > 10:
            normalized -= 0.2
        elif panic_premium < -5:
            normalized += 0.2

        normalized = max(-1.0, min(1.0, normalized))

        return CrossAssetSignal(
            asset_name='VIX',
            raw_value=vix_spot,
            normalized=round(normalized, 3),
            confidence=round(confidence, 3),
            regime=term_structure,
        )

    def _normalize_darkpool(
        self, dix_value: float, accumulation: str, percentile: float
    ) -> CrossAssetSignal:
        """暗盘归一化: 激进吸筹=看涨(+), 激进派发=看跌(-)"""
        normalized = 0.0
        confidence = 0.5

        if "Aggressive Accumulation" == accumulation:
            normalized = 0.8
            confidence = 0.85
        elif "Moderate Accumulation" == accumulation:
            normalized = 0.4
            confidence = 0.7
        elif "Distribution" in accumulation:
            normalized = -0.6
            confidence = 0.7
        elif "Aggressive Distribution" in accumulation:
            normalized = -0.8
            confidence = 0.85

        # DIX 阈值调整
        if dix_value > 55:
            normalized += 0.15
        elif dix_value < 40:
            normalized -= 0.15

        # 百分位增强
        if percentile > 80:
            normalized += 0.1
            confidence = min(1.0, confidence + 0.1)
        elif percentile < 20:
            normalized -= 0.1
            confidence = min(1.0, confidence + 0.1)

        normalized = max(-1.0, min(1.0, normalized))

        return CrossAssetSignal(
            asset_name='DARKPOOL',
            raw_value=dix_value,
            normalized=round(normalized, 3),
            confidence=round(confidence, 3),
            regime=accumulation,
        )

    # ──────────────────────────────────────────────
    # 方向一致性计算
    # ──────────────────────────────────────────────

    def _compute_pairwise_alignment(
        self,
        signals: List[CrossAssetSignal],
    ) -> Dict[str, Dict[str, float]]:
        """计算资产间 Pairwise 方向一致性矩阵

        对每对资产 (i, j)，计算:
          alignment_ij = sign(n_i) == sign(n_j) ? |n_i * n_j| : -|n_i * n_j|
          其中 n_i 为资产 i 的归一化信号值

        Returns:
            嵌套字典 {asset_i: {asset_j: alignment_score}}
        """
        matrix = {}
        for s_i in signals:
            matrix[s_i.asset_name] = {}
            for s_j in signals:
                if s_i.asset_name == s_j.asset_name:
                    matrix[s_i.asset_name][s_j.asset_name] = 1.0
                else:
                    prod = s_i.normalized * s_j.normalized
                    # 同向 → 正值；反向 → 负值
                    if (s_i.normalized >= 0) == (s_j.normalized >= 0):
                        alignment = abs(prod)
                    else:
                        alignment = -abs(prod)
                    matrix[s_i.asset_name][s_j.asset_name] = round(alignment, 3)

        return matrix

    def _count_alignment(
        self, signals: List[CrossAssetSignal]
    ) -> Tuple[int, str]:
        """统计方向对齐的资产数量及主导方向

        Returns:
            (alignment_count, direction): 对齐数量和方向
        """
        bullish = sum(1 for s in signals if s.normalized > self.alignment_threshold)
        bearish = sum(1 for s in signals if s.normalized < -self.alignment_threshold)

        if bullish >= bearish and bullish >= 2:
            return bullish, "BULLISH"
        elif bearish > bullish and bearish >= 2:
            return bearish, "BEARISH"
        else:
            return max(bullish, bearish), "NEUTRAL"

    def _compute_coherence(
        self,
        signals: List[CrossAssetSignal],
        corr_matrix: Dict[str, Dict[str, float]],
    ) -> float:
        """加权聚合跨资产一致性得分 (0-100)

        逻辑:
        1. 计算加权平均 Pairwise Alignment
        2. 乘以信号置信度因子
        3. 缩放至 0-100
        """
        asset_names = [s.asset_name for s in signals]

        # 加权 Pairwise Alignment
        total_alignment = 0.0
        total_weight = 0.0
        pair_count = 0

        for i, name_i in enumerate(asset_names):
            w_i = self.weights.get(name_i, 0.25)
            n_i = next(s.normalized for s in signals if s.asset_name == name_i)
            c_i = next(s.confidence for s in signals if s.asset_name == name_i)

            for j, name_j in enumerate(asset_names):
                if i >= j:
                    continue
                w_j = self.weights.get(name_j, 0.25)
                n_j = next(s.normalized for s in signals if s.asset_name == name_j)
                c_j = next(s.confidence for s in signals if s.asset_name == name_j)

                alignment = corr_matrix[name_i][name_j]
                pair_weight = (w_i + w_j) / 2
                pair_confidence = (c_i + c_j) / 2

                total_alignment += alignment * pair_weight * pair_confidence
                total_weight += pair_weight * pair_confidence
                pair_count += 1

        if total_weight == 0 or pair_count == 0:
            return 50.0

        avg_alignment = total_alignment / total_weight

        # 缩放至 0-100: alignment ∈ [-1, 1] → score ∈ [0, 100]
        # alignment=0 (随机) → score=50, alignment=1 (完美共振) → score=100
        score = 50.0 + avg_alignment * 50.0
        return float(np.clip(score, 0.0, 100.0))

    @staticmethod
    def _classify_strength(score: float, alignment_count: int) -> str:
        """判定共振强度等级"""
        if score >= 85 and alignment_count >= 3:
            return "Extreme Cross-Asset Confluence"
        elif score >= 70:
            return "Strong Cross-Asset Alignment"
        elif score >= 55:
            return "Moderate Cross-Asset Alignment"
        elif score <= 30:
            return "Cross-Asset Divergence"
        elif score <= 15:
            return "Extreme Cross-Asset Divergence"
        else:
            return "No Significant Alignment"


# ──────────────────────────────────────────────
# 便捷函数
# ──────────────────────────────────────────────

def compute_cross_asset_coherence(
    net_gex: float,
    gex_regime: str,
    gex_percentile: float,
    crypto_leverage_state: str,
    crypto_oi_change_pct: float,
    crypto_funding_rate: float,
    vix_spot: float,
    vix_term_structure: str,
    vix_panic_premium: float,
    dix_value: float,
    accumulation_regime: str,
    dix_percentile: float,
) -> CrossAssetResonanceResult:
    """便捷接口：一键跨资产共振分析"""
    engine = CrossAssetResonanceEngine()
    return engine.analyze(
        net_gex=net_gex,
        gex_regime=gex_regime,
        gex_percentile=gex_percentile,
        crypto_leverage_state=crypto_leverage_state,
        crypto_oi_change_pct=crypto_oi_change_pct,
        crypto_funding_rate=crypto_funding_rate,
        vix_spot=vix_spot,
        vix_term_structure=vix_term_structure,
        vix_panic_premium=vix_panic_premium,
        dix_value=dix_value,
        accumulation_regime=accumulation_regime,
        dix_percentile=dix_percentile,
    )
