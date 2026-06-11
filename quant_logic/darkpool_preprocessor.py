"""
多源共振监控系统 - 暗盘数据预处理与降噪模块

该模块实现暗池净做空量的 EMA 平滑降噪和拐点特征工程:

一、数据预处理与降噪
- 计算绝对净做空量: V_net = V_short - V_buy_est
- EMA 快慢双线平滑:
  - EMA_fast(V_net, span=5): 近一周短期做市商情绪
  - EMA_slow(V_net, span=20): 近一月基准流动性状态

二、特征工程：拐点逻辑
1. 零轴穿越因子 (Zero-Axis Crossover)
   - 多头→空头: EMA_fast 从正数向下击穿0轴
   - 空头→多头: EMA_fast 从负数向上突破0轴
2. 动量加速度因子 (Momentum Reversal)
   - ΔV = EMA_fast(t) - EMA_fast(t-1)
   - 连续2~3天大幅负值 → 早期抛售预警
"""

from typing import Dict, List, Optional, Tuple
import numpy as np
from utils.logger import getLogger

logger = getLogger('darkpool_preprocessor')


class DarkPoolPreprocessor:
    """暗盘数据预处理器

    对 AXLFI 暗盘短卖数据进行 EMA 降噪和拐点检测，
    输出零轴穿越信号和动量反转预警。

    Attributes:
        EMA_FAST_SPAN: 快线EMA平滑周期 (默认5)
        EMA_SLOW_SPAN: 慢线EMA平滑周期 (默认20)
        MOMENTUM_WINDOW: 动量反转检测窗口 (默认3)
        MOMENTUM_THRESHOLD_PCT: 动量反转百分比阈值 (默认0.10 = 10%)
    """

    EMA_FAST_SPAN: int = 5
    EMA_SLOW_SPAN: int = 20
    MOMENTUM_WINDOW: int = 3
    MOMENTUM_THRESHOLD_PCT: float = 0.10

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def compute_v_net(
        self,
        short_volume: List[float],
        total_volume: List[float],
    ) -> List[float]:
        """计算绝对净做空量 V_net

        V_net = V_short - V_buy_est
        V_buy_est = V_total - V_short
        → V_net = 2 * V_short - V_total

        正值 = 净做空 (做市商卖出满足买盘)
        负值 = 净买入 (做市商买入承接抛盘)

        Args:
            short_volume: 卖空成交量序列
            total_volume: 总成交量序列 (net_volume from AXLFI)

        Returns:
            V_net 序列，长度与输入一致
        """
        if len(short_volume) != len(total_volume):
            min_len = min(len(short_volume), len(total_volume))
            if min_len == 0:
                logger.warning("V_net 计算: 输入序列为空")
                return []
            short_volume = short_volume[-min_len:]
            total_volume = total_volume[-min_len:]
            logger.warning(
                f"V_net 计算: 序列长度不一致, 截取到最后 {min_len} 个点"
            )

        result = []
        for sv, tv in zip(short_volume, total_volume):
            try:
                v_net = 2.0 * float(sv) - float(tv)
                result.append(v_net)
            except (TypeError, ValueError):
                result.append(0.0)

        return result

    def compute_ema(self, series: List[float], span: int) -> List[float]:
        """计算指数移动平均 (EMA)

        使用 pandas ewm(span=n, adjust=False) 等价公式，
        确保不依赖 pandas 以保持轻量化。

        alpha = 2 / (span + 1)
        EMA_0 = series[0]
        EMA_t = alpha * series[t] + (1 - alpha) * EMA_{t-1}

        Args:
            series: 输入数值序列
            span: EMA 平滑周期

        Returns:
            EMA 序列，长度与输入一致，前 span-1 个点为 NaN
        """
        if span <= 0 or len(series) == 0:
            return []

        alpha = 2.0 / (span + 1.0)
        ema = [float('nan')] * len(series)

        # 第一个有效点的 EMA 为简单平均
        seed = np.mean(series[:span]) if len(series) >= span else np.mean(series)
        ema[0] = seed
        for i in range(1, len(series)):
            if np.isnan(float(series[i])):
                ema[i] = ema[i - 1]  # 保持上一个值
            else:
                ema[i] = alpha * float(series[i]) + (1.0 - alpha) * ema[i - 1]

        # 前 span-1 个点标记为 NaN (EMA 尚未稳定)
        for i in range(min(span - 1, len(series))):
            ema[i] = float('nan')

        return ema

    # ------------------------------------------------------------------
    # 零轴穿越因子
    # ------------------------------------------------------------------

    def detect_zero_cross(
        self,
        ema_fast: List[float],
    ) -> Dict[str, any]:
        """检测 EMA_fast 零轴穿越事件

        多头→空头 (BEARISH): EMA_fast 从 >0 跌落 <0
        空头→多头 (BULLISH):  EMA_fast 从 <0 突破 >0

        Args:
            ema_fast: EMA 快线序列 (跨度5)

        Returns:
            {
                'signal': 'BULLISH' | 'BEARISH' | None,
                'cross_index': int | None,   # 穿越发生的索引
                'prev_value': float | None,  # 穿越前的 EMA 值
                'curr_value': float | None,  # 穿越后的 EMA 值
            }
        """
        if len(ema_fast) < 2:
            return {
                'signal': None, 'cross_index': None,
                'prev_value': None, 'curr_value': None,
            }

        # 从最新向回找第一个有效穿越
        for i in range(len(ema_fast) - 1, 0, -1):
            prev = ema_fast[i - 1]
            curr = ema_fast[i]
            if np.isnan(prev) or np.isnan(curr):
                continue

            if prev > 0 and curr < 0:
                logger.info(
                    f"零轴穿越 BEARISH: EMA_fast 从 {prev:.4f} 下穿至 {curr:.4f} "
                    f"(index {i}), 抛售压力增加"
                )
                return {
                    'signal': 'BEARISH',
                    'cross_index': i,
                    'prev_value': float(prev),
                    'curr_value': float(curr),
                }

            if prev < 0 and curr > 0:
                logger.info(
                    f"零轴穿越 BULLISH: EMA_fast 从 {prev:.4f} 上穿至 {curr:.4f} "
                    f"(index {i}), 买入需求回归"
                )
                return {
                    'signal': 'BULLISH',
                    'cross_index': i,
                    'prev_value': float(prev),
                    'curr_value': float(curr),
                }

        return {
            'signal': None, 'cross_index': None,
            'prev_value': None, 'curr_value': None,
        }

    # ------------------------------------------------------------------
    # 动量加速度因子
    # ------------------------------------------------------------------

    def detect_momentum_reversal(
        self,
        ema_fast: List[float],
        window: Optional[int] = None,
        threshold_pct: Optional[float] = None,
    ) -> Dict[str, any]:
        """检测动量反转 (Momentum Reversal)

        ΔV = EMA_fast(t) - EMA_fast(t-1)

        如果在 V_net 仍然为正的情况下，ΔV 连续 window 个周期
        出现大幅负值 (> threshold_pct)，触发"早期抛售预警"。

        Args:
            ema_fast: EMA 快线序列
            window: 检测窗口 (默认 3)
            threshold_pct: 反转幅度阈值百分比 (默认 0.10)

        Returns:
            {
                'signal': 'EARLY_SELL_WARNING' | None,
                'delta_v_series': List[float],      # ΔV 序列
                'consecutive_drops': int,            # 连续下跌周期数
                'current_v_net_sign': str,           # 当前 V_net 正负
                'details': str,
            }
        """
        if window is None:
            window = self.MOMENTUM_WINDOW
        if threshold_pct is None:
            threshold_pct = self.MOMENTUM_THRESHOLD_PCT

        if len(ema_fast) < window + 1:
            return {
                'signal': None,
                'delta_v_series': [],
                'consecutive_drops': 0,
                'current_v_net_sign': 'unknown',
                'details': f'数据不足, 需要至少 {window + 1} 点, 当前 {len(ema_fast)}',
            }

        # 计算 ΔV 序列
        delta_v = []
        for i in range(1, len(ema_fast)):
            if np.isnan(ema_fast[i - 1]) or np.isnan(ema_fast[i]):
                delta_v.append(0.0)
            else:
                delta_v.append(float(ema_fast[i] - ema_fast[i - 1]))

        # 取最近 window 个 ΔV
        recent_deltas = delta_v[-window:] if len(delta_v) >= window else delta_v

        # 当前 V_net 正负 (取最新非 NaN 值)
        current_v_net = ema_fast[-1]
        for v in reversed(ema_fast):
            if not np.isnan(v):
                current_v_net = v
                break
        v_net_sign = 'positive' if current_v_net > 0 else 'negative' if current_v_net < 0 else 'zero'

        # 检测连续大幅负值
        consecutive_drops = 0
        for dv in reversed(recent_deltas):
            # 大幅负值: ΔV < 0 且 |ΔV| > threshold_pct * |V_net|
            abs_threshold = threshold_pct * abs(current_v_net) if abs(current_v_net) > 1e-10 else threshold_pct * 1e6
            if dv < 0 and abs(dv) > abs_threshold:
                consecutive_drops += 1
            else:
                break

        signal = None
        details = ''
        if consecutive_drops >= window and v_net_sign == 'positive':
            signal = 'EARLY_SELL_WARNING'
            details = (
                f"早期抛售预警: V_net 仍为正但 ΔV 连续 {consecutive_drops} 期大幅回落, "
                f"做市商净做空加速衰减, 可能是买入需求回归前的早期信号"
            )
            logger.warning(details)
        elif consecutive_drops >= window:
            details = (
                f"连续 {consecutive_drops} 期 ΔV 大幅负值, "
                f"但当前 V_net 为 {v_net_sign}, 暂不触发预警"
            )
        else:
            details = (
                f"ΔV 连续负值 {consecutive_drops}/{window} 期, "
                f"未达到预警阈值"
            )

        return {
            'signal': signal,
            'delta_v_series': delta_v,
            'consecutive_drops': consecutive_drops,
            'current_v_net_sign': v_net_sign,
            'details': details,
        }

    # ------------------------------------------------------------------
    # 完整处理管线
    # ------------------------------------------------------------------

    def full_process(
        self,
        short_volume: List[float],
        total_volume: List[float],
    ) -> Dict[str, any]:
        """完整暗盘数据预处理管线

        一站式执行: V_net 计算 → EMA 平滑 → 零轴穿越 → 动量反转

        Args:
            short_volume: 卖空成交量序列 (来自 AXLFI short_volume)
            total_volume: 总成交量序列 (来自 AXLFI net_volume)

        Returns:
            {
                'v_net': List[float],              # 净做空量序列
                'ema_fast': List[float],           # EMA-5 快线
                'ema_slow': List[float],           # EMA-20 慢线
                'latest_v_net': float,             # 最新 V_net
                'latest_ema_fast': float,          # 最新 EMA_fast
                'latest_ema_slow': float,          # 最新 EMA_slow
                'zero_cross': dict,                # 零轴穿越结果
                'momentum_reversal': dict,         # 动量反转结果
                'v_net_sign': str,                 # 当前 V_net 正负
                'ema_trend': str,                  # EMA_fast 趋势 (UP/DOWN/FLAT)
            }
        """
        # Step 1: 计算 V_net
        v_net = self.compute_v_net(short_volume, total_volume)

        if len(v_net) < self.EMA_FAST_SPAN:
            logger.warning(
                f"V_net 序列长度 ({len(v_net)}) 不足 EMA_FAST 最小要求 "
                f"({self.EMA_FAST_SPAN}), 返回空结果"
            )
            return {
                'v_net': v_net,
                'ema_fast': [],
                'ema_slow': [],
                'latest_v_net': v_net[-1] if v_net else 0.0,
                'latest_ema_fast': float('nan'),
                'latest_ema_slow': float('nan'),
                'zero_cross': {'signal': None},
                'momentum_reversal': {'signal': None},
                'v_net_sign': 'unknown',
                'ema_trend': 'FLAT',
            }

        # Step 2: 计算 EMA 快慢线
        ema_fast = self.compute_ema(v_net, self.EMA_FAST_SPAN)
        ema_slow = self.compute_ema(v_net, self.EMA_SLOW_SPAN)

        # Step 3: 零轴穿越检测
        zero_cross = self.detect_zero_cross(ema_fast)

        # Step 4: 动量反转检测
        momentum = self.detect_momentum_reversal(ema_fast)

        # 取最新有效值
        latest_v_net = v_net[-1] if v_net else 0.0
        latest_ema_fast = float('nan')
        for v in reversed(ema_fast):
            if not np.isnan(v):
                latest_ema_fast = float(v)
                break
        latest_ema_slow = float('nan')
        for v in reversed(ema_slow):
            if not np.isnan(v):
                latest_ema_slow = float(v)
                break

        # V_net 正负
        v_net_sign = (
            'positive' if latest_v_net > 0
            else 'negative' if latest_v_net < 0
            else 'zero'
        )

        # EMA 趋势 (最近两个有效点)
        ema_trend = 'FLAT'
        valid_fast = [v for v in ema_fast if not np.isnan(v)]
        if len(valid_fast) >= 2:
            diff = valid_fast[-1] - valid_fast[-2]
            if diff > 0:
                ema_trend = 'UP'
            elif diff < 0:
                ema_trend = 'DOWN'

        logger.info(
            f"DarkPool 预处理完成: V_net={latest_v_net:,.0f}, "
            f"EMA_fast={latest_ema_fast:,.0f}, EMA_slow={latest_ema_slow:,.0f}, "
            f"EMA_trend={ema_trend}, "
            f"ZeroCross={zero_cross.get('signal')}, "
            f"Momentum={momentum.get('signal')}"
        )

        return {
            'v_net': v_net,
            'ema_fast': ema_fast,
            'ema_slow': ema_slow,
            'latest_v_net': latest_v_net,
            'latest_ema_fast': latest_ema_fast,
            'latest_ema_slow': latest_ema_slow,
            'zero_cross': zero_cross,
            'momentum_reversal': momentum,
            'v_net_sign': v_net_sign,
            'ema_trend': ema_trend,
        }


# ------------------------------------------------------------------
# 便捷函数
# ------------------------------------------------------------------

def quick_preprocess(
    short_volume: List[float],
    total_volume: List[float],
) -> Dict[str, any]:
    """快速暗盘预处理"""
    preprocessor = DarkPoolPreprocessor()
    return preprocessor.full_process(short_volume, total_volume)


def compute_ema_series(series: List[float], span: int) -> List[float]:
    """独立 EMA 计算函数"""
    preprocessor = DarkPoolPreprocessor()
    return preprocessor.compute_ema(series, span)
