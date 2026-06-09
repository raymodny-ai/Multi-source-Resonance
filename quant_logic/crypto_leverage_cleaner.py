"""
多源共振监控系统 - 加密杠杆清洗判定引擎

该模块实现加密货币市场去杠杆过程的监控和判定,包括:
- 资金费率异常检测
- 持仓量(OI)断崖式下跌识别
- 预估杠杆率(ELR)安全评估
- 综合去杠杆完成判定

加密市场的高杠杆特性使得去杠杆过程往往伴随剧烈的价格波动,
本引擎通过多维度指标识别去杠杆的关键阶段。
"""

from typing import Dict, List, Optional
from utils.logger import getLogger
from config.settings import Config

logger = getLogger('crypto_leverage_cleaner')


class CryptoLeverageCleaner:
    """加密市场杠杆清洗判定引擎
    
    监控加密货币市场的去杠杆过程,通过资金费率、持仓量和预估杠杆率三个维度
    判断清算是否正在进行或已完成。
    
    Attributes:
        FUNDING_RATE_THRESHOLD: 资金费率异常阈值(默认-0.01%)
        OI_CRASH_THRESHOLD: OI下跌幅度阈值(默认15%)
    """
    
    FUNDING_RATE_THRESHOLD = Config.Thresholds.FUNDING_RATE_ANOMALY  # -0.01%
    OI_CRASH_THRESHOLD = Config.Thresholds.OI_CRASH_PERCENTAGE / 100.0  # 15% (转换为小数)
    
    def check_funding_rate_anomaly(
        self, 
        funding_rate: float, 
        threshold: Optional[float] = None
    ) -> bool:
        """检测资金费率异常
        
        负的资金费率表明空头向多头支付费用,通常出现在市场过度看空时。
        当费率低于-0.01%时,可能触发大规模清算。
        
        Args:
            funding_rate: 资金费率(小数形式,如-0.0001表示-0.01%)
            threshold: 异常阈值,默认为-0.0001(-0.01%)
            
        Returns:
            bool: True表示费率异常低(<threshold),需激活清算监控
            
        Examples:
            >>> cleaner = CryptoLeverageCleaner()
            >>> # 正常费率
            >>> cleaner.check_funding_rate_anomaly(0.0001)  # False
            >>> # 异常负费率
            >>> cleaner.check_funding_rate_anomaly(-0.0002)  # True
        """
        if threshold is None:
            threshold = self.FUNDING_RATE_THRESHOLD
        
        is_anomaly = funding_rate < threshold
        
        if is_anomaly:
            logger.warning(
                f"Funding rate anomaly detected: {funding_rate*100:.4f}% "
                f"(threshold: {threshold*100:.4f}%)"
            )
        else:
            logger.debug(f"Funding rate normal: {funding_rate*100:.4f}%")
        
        return is_anomaly
    
    def detect_oi_crash(
        self, 
        current_oi: float, 
        historical_oi_list: List[float], 
        threshold: Optional[float] = None
    ) -> Dict[str, any]:
        """检测OI断崖式下跌
        
        通过分析当前持仓量与历史峰值的对比,识别是否发生大规模的强制平仓。
        
        Args:
            current_oi: 当前持仓量
            historical_oi_list: 过去1小时的OI列表(每5分钟一个点,共12个数据点)
            threshold: 下跌幅度阈值,默认为0.15(15%)
            
        Returns:
            dict: OI下跌分析结果
                {
                    'crash_detected': bool,         # 是否检测到暴跌
                    'drop_percentage': float,       # 下跌幅度%(相对于历史峰值)
                    'max_drop_from_peak': float     # 从峰值最大跌幅%
                }
                
        Examples:
            >>> cleaner = CryptoLeverageCleaner()
            >>> historical = [1000, 1050, 1100, 1080, 1120, 1150, 1200, 1180, 1250, 1300, 1280, 1350]
            >>> result = cleaner.detect_oi_crash(current_oi=1000, historical_oi_list=historical)
            >>> print(f"Crash: {result['crash_detected']}, Drop: {result['drop_percentage']:.2f}%")
        """
        if threshold is None:
            threshold = self.OI_CRASH_THRESHOLD
        
        # 边界条件检查
        if not historical_oi_list or len(historical_oi_list) < 2:
            logger.warning("Insufficient historical OI data")
            return {
                'crash_detected': False,
                'drop_percentage': 0.0,
                'max_drop_from_peak': 0.0
            }
        
        if current_oi <= 0:
            logger.warning(f"Invalid current OI: {current_oi}")
            return {
                'crash_detected': False,
                'drop_percentage': 0.0,
                'max_drop_from_peak': 0.0
            }
        
        # 计算历史峰值
        peak_oi = max(historical_oi_list)
        
        # 计算下跌幅度
        drop_pct = (peak_oi - current_oi) / peak_oi if peak_oi > 0 else 0.0
        
        # 判断是否达到暴跌阈值
        crash_detected = drop_pct > threshold
        
        result = {
            'crash_detected': crash_detected,
            'drop_percentage': drop_pct * 100,
            'max_drop_from_peak': drop_pct * 100
        }
        
        if crash_detected:
            logger.warning(
                f"OI CRASH DETECTED: Drop={drop_pct*100:.2f}% "
                f"(Peak: {peak_oi:,.0f}, Current: {current_oi:,.0f})"
            )
        else:
            logger.debug(
                f"OI stable: Drop={drop_pct*100:.2f}% "
                f"(Peak: {peak_oi:,.0f}, Current: {current_oi:,.0f})"
            )
        
        return result
    
    def confirm_leverage_cleanup(
        self,
        funding_rate: float,
        oi_drop_pct: float,
        elr_current: float,
        elr_historical_avg: float
    ) -> bool:
        """综合判定去杠杆完成
        
        需要同时满足以下三个条件才确认去杠杆完成:
        1. 资金费率 ≥ 0 (不再为负,表明抛压减轻)
        2. OI下跌 > 15% (杠杆已大幅清理)
        3. ELR回落至历史均值以下 (整体杠杆率回归安全水平)
        
        Args:
            funding_rate: 当前资金费率
            oi_drop_pct: OI下跌幅度%(正值表示下跌)
            elr_current: 当前CryptoQuant预估杠杆率
            elr_historical_avg: ELR历史均值
            
        Returns:
            bool: True表示满足所有条件,去杠杆已完成
            
        Examples:
            >>> cleaner = CryptoLeverageCleaner()
            >>> result = cleaner.confirm_leverage_cleanup(
            ...     funding_rate=0.0001,
            ...     oi_drop_pct=20.0,
            ...     elr_current=2.5,
            ...     elr_historical_avg=3.0
            ... )
            >>> print(f"Leverage cleanup confirmed: {result}")  # True
        """
        # 条件1: 费率转正
        funding_positive = funding_rate >= 0
        
        # 条件2: OI大幅下跌
        oi_significant_drop = oi_drop_pct > 15.0
        
        # 条件3: ELR回归安全水平
        elr_safe = elr_current < elr_historical_avg
        
        # 三者必须同时满足
        all_conditions_met = funding_positive and oi_significant_drop and elr_safe
        
        if all_conditions_met:
            logger.info(
                f"Leverage cleanup CONFIRMED: "
                f"Funding={funding_rate*100:.4f}%, OI Drop={oi_drop_pct:.2f}%, "
                f"ELR={elr_current:.2f}/{elr_historical_avg:.2f}"
            )
        else:
            logger.debug(
                f"Leverage cleanup incomplete: "
                f"Funding Positive={funding_positive}, "
                f"OI Drop Sufficient={oi_significant_drop}, "
                f"ELR Safe={elr_safe}"
            )
        
        return all_conditions_met
    
    def get_crypto_score(
        self,
        oi_crash: bool,
        funding_positive: bool,
        elr_safe: bool
    ) -> float:
        """计算加密维度信号分值
        
        根据去杠杆的不同阶段给出评分:
        - 仅OI暴跌: 0.5分(清算进行中,等待确认)
        - 费率转正+ELR安全: 1.0分(去杠杆完成,最佳入场时机)
        - 其他: 0.0分(无明确信号)
        
        Args:
            oi_crash: OI是否发生暴跌(>15%)
            funding_positive: 资金费率是否转正(≥0)
            elr_safe: ELR是否降至安全水平(<历史均值)
            
        Returns:
            float: 信号分值 (0.0 ~ 1.0)
                - 0.0: 无信号或早期阶段
                - 0.5: 清算进行中(左侧机会)
                - 1.0: 去杠杆完成(右侧确认)
                
        Examples:
            >>> cleaner = CryptoLeverageCleaner()
            >>> # 清算进行中
            >>> score1 = cleaner.get_crypto_score(oi_crash=True, funding_positive=False, elr_safe=False)
            >>> print(f"Score: {score1}")  # 0.5
            >>> 
            >>> # 去杠杆完成
            >>> score2 = cleaner.get_crypto_score(oi_crash=True, funding_positive=True, elr_safe=True)
            >>> print(f"Score: {score2}")  # 1.0
        """
        # 最高优先级: 去杠杆完成确认
        if funding_positive and elr_safe:
            logger.info("Crypto Score 1.0: Leverage cleanup completed")
            return 1.0
        
        # 次级信号: 清算进行中
        if oi_crash:
            logger.info("Crypto Score 0.5: Liquidation in progress")
            return 0.5
        
        # 无明确信号
        logger.debug("Crypto Score 0.0: No clear signal")
        return 0.0
    
    def analyze_leverage_state(
        self,
        funding_rate: float,
        current_oi: float,
        historical_oi_list: List[float],
        elr_current: float,
        elr_historical_avg: float
    ) -> Dict[str, any]:
        """综合分析杠杆状态
        
        一次性获取所有杠杆相关指标的完整分析。
        
        Args:
            funding_rate: 当前资金费率
            current_oi: 当前持仓量
            historical_oi_list: 历史OI列表
            elr_current: 当前预估杠杆率
            elr_historical_avg: ELR历史均值
            
        Returns:
            dict: 完整杠杆状态分析
        """
        # 检测各项指标
        funding_anomaly = self.check_funding_rate_anomaly(funding_rate)
        oi_analysis = self.detect_oi_crash(current_oi, historical_oi_list)
        
        # 综合判定
        cleanup_confirmed = self.confirm_leverage_cleanup(
            funding_rate=funding_rate,
            oi_drop_pct=oi_analysis['drop_percentage'],
            elr_current=elr_current,
            elr_historical_avg=elr_historical_avg
        )
        
        # 计算信号分值
        score = self.get_crypto_score(
            oi_crash=oi_analysis['crash_detected'],
            funding_positive=funding_rate >= 0,
            elr_safe=elr_current < elr_historical_avg
        )
        
        return {
            'funding_rate': funding_rate,
            'funding_anomaly': funding_anomaly,
            'oi_analysis': oi_analysis,
            'elr_current': elr_current,
            'elr_historical_avg': elr_historical_avg,
            'cleanup_confirmed': cleanup_confirmed,
            'signal_score': score,
            'stage': self._determine_stage(
                oi_analysis['crash_detected'],
                funding_rate >= 0,
                elr_current < elr_historical_avg
            )
        }
    
    @staticmethod
    def _determine_stage(
        oi_crash: bool,
        funding_positive: bool,
        elr_safe: bool
    ) -> str:
        """确定去杠杆所处阶段
        
        Args:
            oi_crash: OI是否暴跌
            funding_positive: 费率是否转正
            elr_safe: ELR是否安全
            
        Returns:
            str: 阶段描述
        """
        if funding_positive and elr_safe:
            return "COMPLETED"  # 去杠杆完成
        elif oi_crash:
            return "IN_PROGRESS"  # 清算进行中
        else:
            return "NORMAL"  # 正常状态


# 便捷函数
def quick_leverage_check(
    funding_rate: float,
    current_oi: float,
    historical_oi: List[float],
    elr_current: float,
    elr_avg: float
) -> Dict[str, any]:
    """快速杠杆状态检查
    
    Args:
        funding_rate: 资金费率
        current_oi: 当前持仓量
        historical_oi: 历史OI列表
        elr_current: 当前ELR
        elr_avg: ELR历史均值
        
    Returns:
        dict: 快速检查结果
    """
    cleaner = CryptoLeverageCleaner()
    return cleaner.analyze_leverage_state(
        funding_rate, current_oi, historical_oi, elr_current, elr_avg
    )
