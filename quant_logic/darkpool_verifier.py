"""
多源共振监控系统 - 暗盘"三驾马车"验证引擎

该模块实现机构资金暗盘活动的多维度验证,包括:
- DIX(Dark Index)基线判定
- ChartExchange卖空比连续性检测
- Stockgrid底背离与拐点确认
- DBMF均线收复验证
- 三选二投票机制聚合

暗盘交易占美股成交量的40%以上,是机构资金动向的重要指标。
通过三个独立数据源的交叉验证,提高信号的可靠性。
"""

from typing import Dict, List, Optional
import numpy as np
from utils.logger import getLogger
from config.settings import Config

logger = getLogger('darkpool_verifier')


class DarkPoolVerifier:
    """暗盘机构资金三驾马车验证引擎
    
    通过DIX、ChartExchange卖空比和Stockgrid净头寸三个维度,
    验证机构资金是否在暗盘中进行大规模建仓或平仓活动。
    
    Attributes:
        DIX_THRESHOLD: DIX阈值(默认45%)
        SHORT_VOLUME_THRESHOLD: 卖空比阈值(默认45%)
        CONSECUTIVE_DAYS: 连续天数要求(默认2天)
    """
    
    DIX_THRESHOLD = Config.Thresholds.DIX_SIGNAL_THRESHOLD
    SHORT_VOLUME_THRESHOLD = Config.Thresholds.SHORT_VOLUME_THRESHOLD
    CONSECUTIVE_DAYS = Config.Thresholds.CONSECUTIVE_DAYS_REQUIRED
    
    def check_dix_threshold(self, dix_value: float, threshold: Optional[float] = None) -> bool:
        """DIX基线判定
        
        DIX(Dark Index)衡量暗盘买入强度,值越高表明大资金潜在买入意向越强。
        
        Args:
            dix_value: SqueezeMetrics DIX百分比值(0-100)
            threshold: 阈值,默认为45%
            
        Returns:
            bool: True表示DIX > threshold,大资金潜在买入意向强烈
            
        Examples:
            >>> verifier = DarkPoolVerifier()
            >>> verifier.check_dix_threshold(50.0)  # True
            >>> verifier.check_dix_threshold(40.0)  # False
        """
        if threshold is None:
            threshold = self.DIX_THRESHOLD
        
        if dix_value is None:
            logger.warning("DIX value is None, returning False")
            return False
        
        is_active = dix_value > threshold
        
        if is_active:
            logger.info(f"DIX signal ACTIVE: {dix_value:.2f}% (threshold: {threshold}%)")
        else:
            logger.debug(f"DIX signal inactive: {dix_value:.2f}% (threshold: {threshold}%)")
        
        return is_active
    
    def check_short_volume_consecutive(
        self, 
        days_data: List[Optional[float]], 
        threshold: Optional[float] = None,
        consecutive_days: Optional[int] = None
    ) -> bool:
        """ChartExchange卖空比连续性检测
        
        高卖空比通常表明市场情绪过度悲观,可能形成轧空机会。
        需要连续多日保持高位才视为有效信号。
        
        Args:
            days_data: 最近N天的卖空比列表 [day1_ratio, day2_ratio, ...]
                      按时间倒序排列(最新数据在前)
            threshold: 阈值,默认为45%
            consecutive_days: 连续天数要求,默认为2天
            
        Returns:
            bool: True表示连续consecutive_days天卖空比>threshold
            
        Examples:
            >>> verifier = DarkPoolVerifier()
            >>> # 连续2天>45%
            >>> data = [50.0, 48.0, 42.0]
            >>> verifier.check_short_volume_consecutive(data)  # True
            >>> 
            >>> # 不连续
            >>> data2 = [50.0, 40.0, 48.0]
            >>> verifier.check_short_volume_consecutive(data2)  # False
        """
        if threshold is None:
            threshold = self.SHORT_VOLUME_THRESHOLD
        if consecutive_days is None:
            consecutive_days = self.CONSECUTIVE_DAYS
        
        # 数据长度检查
        if len(days_data) < consecutive_days:
            logger.warning(
                f"Insufficient data: need {consecutive_days} days, "
                f"got {len(days_data)}"
            )
            return False
        
        # 取最近consecutive_days天的数据
        recent_data = days_data[:consecutive_days]
        
        # 检查是否有None值
        if any(ratio is None for ratio in recent_data):
            logger.warning("Found None values in short volume data")
            return False
        
        # 检查是否全部超过阈值
        all_above_threshold = all(ratio > threshold for ratio in recent_data)
        
        if all_above_threshold:
            logger.info(
                f"Short volume signal ACTIVE: "
                f"{consecutive_days} consecutive days > {threshold}% "
                f"(values: {recent_data})"
            )
        else:
            logger.debug(
                f"Short volume signal inactive: "
                f"Not all {consecutive_days} days > {threshold}% "
                f"(values: {recent_data})"
            )
        
        return all_above_threshold
    
    def confirm_stockgrid_signal(
        self,
        divergence_flag: bool,
        slope_20d: float,
        slope_60d: float
    ) -> bool:
        """Stockgrid底背离与拐点确认
        
        Stockgrid追踪机构净头寸变化,底背离或趋势线拐头向上都表明
        机构可能在悄悄建仓。
        
        Args:
            divergence_flag: 是否检测到底背离(价格新低但净头寸未新低)
            slope_20d: 20日净头寸趋势线斜率(正值表示上升)
            slope_60d: 60日净头寸趋势线斜率(正值表示上升)
            
        Returns:
            bool: True表示满足以下条件之一:
                  - 底背离=True
                  - 20日斜率>0 AND 60日斜率>0(双周期均拐头向上)
                  
        Examples:
            >>> verifier = DarkPoolVerifier()
            >>> # 底背离场景
            >>> verifier.confirm_stockgrid_signal(
            ...     divergence_flag=True, slope_20d=-0.5, slope_60d=-0.3
            ... )  # True
            >>> 
            >>> # 双周期拐头向上
            >>> verifier.confirm_stockgrid_signal(
            ...     divergence_flag=False, slope_20d=0.8, slope_60d=0.5
            ... )  # True
        """
        # 条件1: 底背离
        has_divergence = divergence_flag
        
        # 条件2: 双周期趋势线拐头向上
        dual_slope_positive = (slope_20d > 0) and (slope_60d > 0)
        
        signal_confirmed = has_divergence or dual_slope_positive
        
        if signal_confirmed:
            reason = "divergence detected" if has_divergence else "dual slopes positive"
            logger.info(
                f"Stockgrid signal CONFIRMED: {reason} "
                f"(divergence={divergence_flag}, "
                f"slope_20d={slope_20d:.4f}, slope_60d={slope_60d:.4f})"
            )
        else:
            logger.debug(
                f"Stockgrid signal not confirmed: "
                f"divergence={divergence_flag}, "
                f"slope_20d={slope_20d:.4f}, slope_60d={slope_60d:.4f}"
            )
        
        return signal_confirmed
    
    def aggregate_darkpool_signals(
        self,
        dix_flag: bool,
        short_ratio_flag: bool,
        stockgrid_flag: bool
    ) -> Dict[str, any]:
        """三选二投票机制聚合
        
        采用多数决原则,至少两个维度发出信号才确认为有效的暗盘活动。
        
        Args:
            dix_flag: DIX信号(True/False)
            short_ratio_flag: ChartExchange卖空比信号(True/False)
            stockgrid_flag: Stockgrid拐点信号(True/False)
            
        Returns:
            dict: 聚合结果
                {
                    'signal_count': int,           # 触发信号数量(0-3)
                    'aggregated_signal': bool,     # 是否满足三选二(>=2)
                    'dix_active': bool,
                    'short_ratio_active': bool,
                    'stockgrid_active': bool
                }
                
        Examples:
            >>> verifier = DarkPoolVerifier()
            >>> result = verifier.aggregate_darkpool_signals(
            ...     dix_flag=True, short_ratio_flag=True, stockgrid_flag=False
            ... )
            >>> print(f"Signal count: {result['signal_count']}")  # 2
            >>> print(f"Aggregated: {result['aggregated_signal']}")  # True
        """
        signals = [dix_flag, short_ratio_flag, stockgrid_flag]
        signal_count = sum(signals)
        
        # 三选二机制
        aggregated_signal = signal_count >= 2
        
        result = {
            'signal_count': signal_count,
            'aggregated_signal': aggregated_signal,
            'dix_active': dix_flag,
            'short_ratio_active': short_ratio_flag,
            'stockgrid_active': stockgrid_flag
        }
        
        if aggregated_signal:
            active_signals = []
            if dix_flag:
                active_signals.append("DIX")
            if short_ratio_flag:
                active_signals.append("Short Ratio")
            if stockgrid_flag:
                active_signals.append("Stockgrid")
            
            logger.info(
                f"Dark pool signal AGGREGATED: {signal_count}/3 signals active "
                f"({', '.join(active_signals)})"
            )
        else:
            logger.debug(
                f"Dark pool signal not aggregated: {signal_count}/3 signals active"
            )
        
        return result
    
    def get_darkpool_score(
        self,
        dix_flag: bool,
        short_ratio_flag: bool,
        stockgrid_flag: bool,
        dbmf_recovery: bool = False
    ) -> float:
        """计算暗盘维度信号分值
        
        评分规则:
        - 三选二满足: 0.75分(基础分)
        - 加DBMF收复: 1.5分(满分,强确认)
        - 其他情况: 0.0分
        
        Args:
            dix_flag: DIX信号
            short_ratio_flag: ChartExchange信号
            stockgrid_flag: Stockgrid信号
            dbmf_recovery: DBMF均线收复标志(可选,默认False)
            
        Returns:
            float: 信号分值 (0.0 ~ 1.5)
                - 0.0: 无信号或信号不足
                - 0.75: 三选二满足(中等置信度)
                - 1.5: 三选二 + DBMF收复(最高置信度)
                
        Examples:
            >>> verifier = DarkPoolVerifier()
            >>> # 仅三选二
            >>> score1 = verifier.get_darkpool_score(True, True, False, False)
            >>> print(f"Score: {score1}")  # 0.75
            >>> 
            >>> # 三选二 + DBMF收复
            >>> score2 = verifier.get_darkpool_score(True, True, False, True)
            >>> print(f"Score: {score2}")  # 1.5
        """
        signals = [dix_flag, short_ratio_flag, stockgrid_flag]
        signal_count = sum(signals)
        
        # 基础分: 三选二
        base_score = 0.75 if signal_count >= 2 else 0.0
        
        # DBMF收复加成
        if dbmf_recovery and base_score > 0:
            final_score = 1.5
            logger.info(
                f"Dark pool score 1.5: Strong confirmation "
                f"({signal_count}/3 signals + DBMF recovery)"
            )
        elif base_score > 0:
            final_score = base_score
            logger.info(
                f"Dark pool score {base_score}: Moderate confidence "
                f"({signal_count}/3 signals)"
            )
        else:
            final_score = 0.0
            logger.debug(f"Dark pool score 0.0: Insufficient signals ({signal_count}/3)")
        
        return final_score
    
    def full_verification(
        self,
        dix_value: float,
        short_volume_days: List[Optional[float]],
        divergence_flag: bool,
        slope_20d: float,
        slope_60d: float,
        dbmf_recovery: bool = False
    ) -> Dict[str, any]:
        """完整暗盘验证流程
        
        一次性执行所有维度的检测和聚合。
        
        Args:
            dix_value: DIX值
            short_volume_days: 最近几天的卖空比数据
            divergence_flag: 底背离标志
            slope_20d: 20日斜率
            slope_60d: 60日斜率
            dbmf_recovery: DBMF收复标志
            
        Returns:
            dict: 完整验证结果
        """
        # 各维度单独检测
        dix_flag = self.check_dix_threshold(dix_value)
        short_ratio_flag = self.check_short_volume_consecutive(short_volume_days)
        stockgrid_flag = self.confirm_stockgrid_signal(
            divergence_flag, slope_20d, slope_60d
        )
        
        # 聚合信号
        aggregation = self.aggregate_darkpool_signals(
            dix_flag, short_ratio_flag, stockgrid_flag
        )
        
        # 计算分值
        score = self.get_darkpool_score(
            dix_flag, short_ratio_flag, stockgrid_flag, dbmf_recovery
        )
        
        return {
            'dix': {
                'value': dix_value,
                'active': dix_flag
            },
            'short_volume': {
                'data': short_volume_days,
                'active': short_ratio_flag
            },
            'stockgrid': {
                'divergence': divergence_flag,
                'slope_20d': slope_20d,
                'slope_60d': slope_60d,
                'active': stockgrid_flag
            },
            'aggregation': aggregation,
            'dbmf_recovery': dbmf_recovery,
            'final_score': score,
            'signal_strength': self._interpret_score(score)
        }
    
    @staticmethod
    def _interpret_score(score: float) -> str:
        """解释信号强度
        
        Args:
            score: 信号分值
            
        Returns:
            str: 强度描述
        """
        if score >= 1.5:
            return "VERY STRONG"
        elif score >= 0.75:
            return "MODERATE"
        else:
            return "WEAK"

    # ═══════════════════════════════════════════
    # V2.0 新增方法
    # ═══════════════════════════════════════════

    @staticmethod
    def calculate_dix_percentile(
        dix_value: float,
        dix_historical: List[float],
    ) -> float:
        """计算当前 DIX 在历史数据中的百分位排名 (V2.0)

        Args:
            dix_value: 当前 DIX 值 (0-100)
            dix_historical: 历史 DIX 值列表

        Returns:
            float: 百分位 (0-100)，历史数据不足时返回 50.0
        """
        if not dix_historical or len(dix_historical) < 10:
            return 50.0
        arr = np.array(dix_historical, dtype=float)
        return float(np.sum(arr <= dix_value) / len(arr) * 100)

    @staticmethod
    def classify_accumulation_regime(
        dix_value: float,
        dix_percentile: float,
        aggregated_signal: bool,
        dbmf_recovery: bool,
    ) -> str:
        """判定吸筹/派发强度分类 (V2.0)

        分类逻辑:
        - Aggressive Accumulation: DIX > 50 AND 百分位 > 80 AND 聚合信号 AND DBMF 收复
        - Moderate Accumulation: DIX > 45 AND 百分位 > 60 AND 聚合信号
        - Neutral: 无明显信号
        - Moderate Distribution: DIX < 45 AND 百分位 < 40
        - Aggressive Distribution: DIX < 40 AND 百分位 < 20

        Args:
            dix_value: 当前 DIX 值
            dix_percentile: DIX 历史百分位
            aggregated_signal: 三选二聚合信号
            dbmf_recovery: DBMF 均线收复标志

        Returns:
            str: 吸筹/派发分类
        """
        if dix_value > 50 and dix_percentile > 80 and aggregated_signal and dbmf_recovery:
            return "Aggressive Accumulation"
        elif dix_value > 45 and dix_percentile > 60 and aggregated_signal:
            return "Moderate Accumulation"
        elif dix_value < 40 and dix_percentile < 20:
            return "Aggressive Distribution"
        elif dix_value < 45 and dix_percentile < 40:
            return "Moderate Distribution"
        else:
            return "Neutral"


# 便捷函数
def quick_darkpool_check(
    dix: float,
    short_volumes: List[float],
    divergence: bool,
    slope_20: float,
    slope_60: float,
    dbmf_recovered: bool = False
) -> Dict[str, any]:
    """快速暗盘信号检查
    
    Args:
        dix: DIX值
        short_volumes: 卖空比历史数据
        divergence: 底背离标志
        slope_20: 20日斜率
        slope_60: 60日斜率
        dbmf_recovered: DBMF是否收复
        
    Returns:
        dict: 快速检查结果
    """
    verifier = DarkPoolVerifier()
    return verifier.full_verification(
        dix, short_volumes, divergence, slope_20, slope_60, dbmf_recovered
    )
