"""
多源共振监控系统 - VIX期限结构分析器

该模块实现VIX期货期限结构的分析和恐慌指标计算,包括:
- Contango/Backwardation状态识别
- 恐慌溢价计算
- VIX维度信号分值评估

VIX期限结构是市场情绪的重要指标:
- Contango(期货>现货): 正常市场状态,投资者愿意支付溢价购买未来保护
- Backwardation(期货<现货): 恐慌状态,投资者急需即时保护
"""

from typing import Dict, Optional
from utils.logger import getLogger
from config.settings import Config

logger = getLogger('vix_analyzer')


class VIXAnalyzer:
    """VIX期限结构分析器
    
    分析VIX现货与期货之间的期限结构关系,用于判断市场恐慌程度和潜在的反转信号。
    
    Attributes:
        CONTANGO_THRESHOLD: Contango阈值(默认0.95)
        BACKWARDATION_THRESHOLD: Backwardation阈值(默认1.05)
        EXTREME_BACKWARDATION_THRESHOLD: 极端Backwardation阈值(默认1.15)
    """
    
    CONTANGO_THRESHOLD = Config.Thresholds.VIX_CONTANGO_THRESHOLD
    BACKWARDATION_THRESHOLD = Config.Thresholds.VIX_BACKWARDATION_THRESHOLD
    EXTREME_BACKWARDATION_THRESHOLD = Config.Thresholds.VIX_EXTREME_BACKWARDATION
    
    def analyze_term_structure(self, vx1: float, vx2: float) -> Dict[str, any]:
        """分析VIX期限结构状态(增加除零保护)
        
        通过比较近月(VX1)和次月(VX2)期货价格,判断市场处于Contango还是Backwardation状态。
        
        Args:
            vx1: 近月期货价格(通常指当月到期)
            vx2: 次月期货价格(通常指次月到期)
            
        Returns:
            dict: 期限结构分析结果
                {
                    'ratio': float,                    # VX1/VX2比值
                    'state': str,                      # CONTANGO/BACKWARDATION/NEUTRAL
                    'contango_pct': float,             # Contango幅度%(负值表示Backwardation)
                    'is_extreme_backwardation': bool   # 是否极端Backwardation(>1.15)
                }
                
        Examples:
            >>> analyzer = VIXAnalyzer()
            >>> result = analyzer.analyze_term_structure(15.0, 16.0)
            >>> print(f"State: {result['state']}")  # CONTANGO
            >>> 
            >>> result2 = analyzer.analyze_term_structure(20.0, 17.0)
            >>> print(f"State: {result2['state']}")  # BACKWARDATION
        """
        if vx2 <= 0:
            logger.error(f"Invalid VX2 price: {vx2}")
            return {
                'ratio': float('nan'),
                'state': 'ERROR',
                'contango_pct': float('nan'),
                'is_extreme_backwardation': False
            }
        
        ratio = vx1 / vx2
        
        # 检查NaN和Inf
        import numpy as np
        if np.isnan(ratio) or np.isinf(ratio):
            logger.warning(f"VIX ratio is NaN or Inf: {ratio}")
            return {
                'ratio': float('nan'),
                'state': 'ERROR',
                'contango_pct': float('nan'),
                'is_extreme_backwardation': False
            }
        
        # 判断状态
        if ratio < self.CONTANGO_THRESHOLD:
            state = "CONTANGO"
        elif ratio > self.BACKWARDATION_THRESHOLD:
            state = "BACKWARDATION"
        else:
            state = "NEUTRAL"
        
        # 计算Contango幅度百分比
        contango_pct = (ratio - 1.0) * 100
        
        # 检查是否为极端Backwardation
        is_extreme_backwardation = ratio > self.EXTREME_BACKWARDATION_THRESHOLD
        
        result = {
            'ratio': ratio,
            'state': state,
            'contango_pct': contango_pct,
            'is_extreme_backwardation': is_extreme_backwardation
        }
        
        logger.info(
            f"VIX Term Structure: {state} "
            f"(VX1/VX2={ratio:.3f}, Contango={contango_pct:.2f}%)"
        )
        
        return result
    
    def calculate_panic_premium(self, vix_spot: float, vx1: float) -> Dict[str, any]:
        """计算恐慌溢价
        
        恐慌溢价衡量VIX期货相对现货的溢价程度,反映市场对即时保护的渴求程度。
        
        Args:
            vix_spot: VIX现货价格
            vx1: 近月期货价格
            
        Returns:
            dict: 恐慌溢价分析结果
                {
                    'premium_ratio': float,            # VX1/VIX比值
                    'is_panic': bool,                  # 是否恐慌状态(>1.15)
                    'premium_pct': float               # 溢价百分比
                }
                
        Examples:
            >>> analyzer = VIXAnalyzer()
            >>> result = analyzer.calculate_panic_premium(15.0, 18.0)
            >>> print(f"Panic: {result['is_panic']}, Premium: {result['premium_pct']:.2f}%")
        """
        if vix_spot <= 0:
            logger.warning(f"Invalid VIX spot price: {vix_spot}, using default ratio=1.0")
            premium_ratio = 1.0
        else:
            premium_ratio = vx1 / vix_spot
        
        # 判断是否进入恐慌状态
        is_panic = premium_ratio > self.EXTREME_BACKWARDATION_THRESHOLD
        
        # 计算溢价百分比
        premium_pct = (premium_ratio - 1.0) * 100
        
        result = {
            'premium_ratio': premium_ratio,
            'is_panic': is_panic,
            'premium_pct': premium_pct
        }
        
        if is_panic:
            logger.warning(
                f"PANIC DETECTED: VIX Premium={premium_pct:.2f}% "
                f"(VX1={vx1}, Spot={vix_spot})"
            )
        else:
            logger.debug(
                f"VIX Panic Premium: {premium_pct:.2f}% "
                f"(VX1={vx1}, Spot={vix_spot})"
            )
        
        return result
    
    def get_vix_score(
        self, 
        vx1: float, 
        vx2: float, 
        slope_direction: str = 'UP'
    ) -> float:
        """计算VIX维度信号分值(用于共振矩阵)
        
        根据VIX期限结构状态和斜率方向,计算0-1范围内的信号分值。
        
        评分逻辑:
        - Backwardation > 1.15: 0.5分(左侧枯竭区,极度踩踏但尚未确认反转)
        - 回归Contango < 1.0 且斜率向下: 1.0分(右侧确认反转,最佳入场时机)
        - 其他情况: 0.0分(无明确信号)
        
        Args:
            vx1: 近月期货价格
            vx2: 次月期货价格
            slope_direction: 斜率方向 ('UP' 或 'DOWN'),表示VIX期货曲线的变化趋势
            
        Returns:
            float: 信号分值 (0.0 ~ 1.0)
                - 0.0: 无信号
                - 0.5: 左侧枯竭区(极度Backwardation)
                - 1.0: 右侧确认反转(回归Contango + 斜率向下)
                
        Examples:
            >>> analyzer = VIXAnalyzer()
            >>> # 极度Backwardation场景
            >>> score1 = analyzer.get_vix_score(25.0, 20.0, 'UP')
            >>> print(f"Score: {score1}")  # 0.5
            >>> 
            >>> # 回归Contango确认反转
            >>> score2 = analyzer.get_vix_score(14.0, 16.0, 'DOWN')
            >>> print(f"Score: {score2}")  # 1.0
        """
        if vx2 <= 0:
            logger.warning(f"Invalid VX2 price: {vx2}, returning score=0.0")
            return 0.0
        
        ratio = vx1 / vx2
        
        # 极度Backwardation: 左侧枯竭区
        if ratio > self.EXTREME_BACKWARDATION_THRESHOLD:
            logger.info(f"VIX Score 0.5: Extreme Backwardation (ratio={ratio:.3f})")
            return 0.5
        
        # 回归Contango + 斜率向下: 右侧确认反转
        if ratio < 1.0 and slope_direction.upper() == 'DOWN':
            logger.info(
                f"VIX Score 1.0: Return to Contango confirmed "
                f"(ratio={ratio:.3f}, slope=DOWN)"
            )
            return 1.0
        
        # 其他情况: 无明确信号
        logger.debug(f"VIX Score 0.0: No clear signal (ratio={ratio:.3f}, slope={slope_direction})")
        return 0.0
    
    def interpret_term_structure(self, vx1: float, vx2: float) -> str:
        """解释期限结构的市场含义
        
        Args:
            vx1: 近月期货价格
            vx2: 次月期货价格
            
        Returns:
            str: 市场状态描述
        """
        analysis = self.analyze_term_structure(vx1, vx2)
        state = analysis['state']
        ratio = analysis['ratio']
        
        interpretations = {
            'CONTANGO': (
                f"市场处于Contango状态(VX1/VX2={ratio:.3f}),表明投资者预期未来波动率上升。"
                f"这是正常的市场结构,暗示当前市场相对稳定。"
            ),
            'BACKWARDATION': (
                f"市场处于Backwardation状态(VX1/VX2={ratio:.3f}),表明投资者急于购买即时保护。"
                f"这通常出现在市场恐慌或下跌期间,暗示短期风险较高。"
            ),
            'NEUTRAL': (
                f"市场处于中性状态(VX1/VX2={ratio:.3f}),期限结构接近平坦。"
                f"这表明市场对未来波动率的预期较为平衡。"
            )
        }
        
        if analysis['is_extreme_backwardation']:
            interpretations['BACKWARDATION'] += " ⚠️ 极端Backwardation,高度警惕!"
        
        return interpretations.get(state, "无法确定市场状态")


# 便捷函数
def quick_vix_analysis(vx1: float, vx2: float, vix_spot: Optional[float] = None) -> Dict[str, any]:
    """快速VIX分析
    
    一次性获取期限结构和恐慌溢价的完整分析。
    
    Args:
        vx1: 近月期货价格
        vx2: 次月期货价格
        vix_spot: VIX现货价格(可选,用于计算恐慌溢价)
        
    Returns:
        dict: 完整分析结果
    """
    analyzer = VIXAnalyzer()
    
    result = {
        'term_structure': analyzer.analyze_term_structure(vx1, vx2),
        'interpretation': analyzer.interpret_term_structure(vx1, vx2)
    }
    
    if vix_spot is not None:
        result['panic_premium'] = analyzer.calculate_panic_premium(vix_spot, vx1)
    
    return result
