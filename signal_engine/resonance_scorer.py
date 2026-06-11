"""
多源共振监控系统 - 共振矩阵评分系统

该模块实现多维度信号评分引擎，包括：
- GEX (Gamma Exposure) 维度评分
- VIX 期限结构维度评分
- 加密市场杠杆清洗维度评分
- 暗盘吸筹维度评分
- Hawkes Process 自激抛售测算
- 综合共振评分与预警分级

所有阈值参数从 config.settings 读取，支持动态调整。
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

from config.settings import Config

logger = logging.getLogger(__name__)


class ResonanceScorer:
    """多因子共振矩阵评分系统
    
    该类负责计算四个维度的信号分值，并综合判定共振级别。
    评分范围0~5.0分，根据总分触发不同级别的预警。
    
    Attributes:
        settings: 系统配置实例，提供阈值参数
    """
    
    def __init__(self):
        """初始化评分器，从config加载阈值参数"""
        self.settings = Config()
        logger.info("ResonanceScorer 初始化完成")
    
    def calculate_gex_score(
        self,
        gex_local: float,
        gex_calibrated: float,
        flip_zone_crossed: bool,
        gex_trend: str
    ) -> Dict[str, any]:
        """计算GEX维度分值
        
        GEX (Gamma Exposure) 反映做市商对冲行为对价格的支撑/压制作用。
        当GEX由负转正时，做市商从追涨杀跌转为低买高卖，形成自动托底机制。
        
        Args:
            gex_local: 本地估算GEX (美元)
            gex_calibrated: 校准后GEX (美元)，来自SqueezeMetrics API
            flip_zone_crossed: 是否跨越翻转线 (GEX由负转正)
            gex_trend: GEX趋势方向，可选值: 'IMPROVING', 'STABLE', 'DETERIORATING'
        
        Returns:
            dict: 包含以下字段:
                - score (float): 分值 0.0~1.5
                - state (str): 状态 'NEGATIVE', 'CONVERGING', 'POSITIVE'
                - details (str): 详细说明文本
        
        Examples:
            >>> scorer = ResonanceScorer()
            >>> result = scorer.calculate_gex_score(
            ...     gex_local=-5e6,
            ...     gex_calibrated=2e6,
            ...     flip_zone_crossed=True,
            ...     gex_trend='IMPROVING'
            ... )
            >>> print(result['score'])  # 1.5
            >>> print(result['state'])  # 'POSITIVE'
        """
        try:
            if flip_zone_crossed and gex_calibrated > 0:
                score = 1.5
                state = 'POSITIVE'
                details = (
                    f"GEX已翻正至+${gex_calibrated/1e6:.1f}M, "
                    f"做市商自动托底对冲激活"
                )
                logger.info(f"GEX评分: {score}分 - {details}")
                
            elif gex_trend == 'IMPROVING':
                score = 0.75
                state = 'CONVERGING'
                details = (
                    f"GEX负值收敛中(${gex_local/1e6:.1f}M), "
                    f"左侧枯竭区"
                )
                logger.info(f"GEX评分: {score}分 - {details}")
                
            else:
                score = 0.0
                state = 'NEGATIVE'
                details = (
                    f"GEX仍为负值且未改善(${gex_local/1e6:.1f}M)"
                )
                logger.debug(f"GEX评分: {score}分 - {details}")
            
            return {
                'score': score,
                'state': state,
                'details': details
            }
            
        except Exception as e:
            logger.error(f"GEX评分计算异常: {str(e)}", exc_info=True)
            return {
                'score': 0.0,
                'state': 'ERROR',
                'details': f'计算异常: {str(e)}'
            }
    
    def calculate_vix_score(
        self,
        term_structure_ratio: float,
        slope_direction: str,
        panic_premium: float
    ) -> Dict[str, any]:
        """计算VIX维度分值
        
        VIX期限结构反映市场恐慌程度。Backwardation (近月>远月) 表示恐慌蔓延，
        Contango (近月<远月) 表示恐慌退潮。斜率向下确认反转信号。
        
        Args:
            term_structure_ratio: VX1/VX2比值 (近月/次近月隐含波动率)
            slope_direction: 期限结构斜率方向，可选值: 'UP', 'DOWN'
            panic_premium: 恐慌溢价百分比 (VX1/VIX - 1) * 100
        
        Returns:
            dict: 包含以下字段:
                - score (float): 分值 0.0~1.0
                - state (str): 状态 'BACKWARDATION', 'CONTANGO', 'NEUTRAL'
                - details (str): 详细说明文本
        
        Examples:
            >>> scorer = ResonanceScorer()
            >>> result = scorer.calculate_vix_score(
            ...     term_structure_ratio=0.95,
            ...     slope_direction='DOWN',
            ...     panic_premium=5.2
            ... )
            >>> print(result['score'])  # 1.0
            >>> print(result['state'])  # 'CONTANGO'
        """
        try:
            if term_structure_ratio > 1.15:
                score = 0.5
                state = 'BACKWARDATION'
                details = (
                    f"VIX期限结构Backwardation({term_structure_ratio:.2f}), "
                    f"近月恐慌溢价{panic_premium:.1f}%"
                )
                logger.info(f"VIX评分: {score}分 - {details}")
                
            elif term_structure_ratio < 1.0 and slope_direction == 'DOWN':
                score = 1.0
                state = 'CONTANGO'
                details = (
                    f"VIX回归Contango({term_structure_ratio:.2f}), "
                    f"恐慌退潮确认"
                )
                logger.info(f"VIX评分: {score}分 - {details}")
                
            else:
                score = 0.0
                state = 'NEUTRAL'
                details = (
                    f"VIX期限结构中性({term_structure_ratio:.2f})"
                )
                logger.debug(f"VIX评分: {score}分 - {details}")
            
            return {
                'score': score,
                'state': state,
                'details': details
            }
            
        except Exception as e:
            logger.error(f"VIX评分计算异常: {str(e)}", exc_info=True)
            return {
                'score': 0.0,
                'state': 'ERROR',
                'details': f'计算异常: {str(e)}'
            }
    
    def calculate_crypto_score(
        self,
        oi_crash: bool,
        funding_positive: bool,
        elr_safe: bool,
        leverage_cleanup_confirmed: bool
    ) -> Dict[str, any]:
        """计算加密维度分值
        
        加密市场作为流动性金丝雀，其去杠杆过程领先传统市场。
        OI (Open Interest) 暴跌 + 资金费率转正 + ELR回落 标志清算完成。
        
        Args:
            oi_crash: OI是否暴跌 >15%
            funding_positive: 资金费率是否转正 (>=0)
            elr_safe: ELR (Exchange Leverage Ratio) 是否回落至安全水平
            leverage_cleanup_confirmed: 去杠杆是否完成确认 
                                       (OI下跌 AND 费率转正 AND ELR安全)
        
        Returns:
            dict: 包含以下字段:
                - score (float): 分值 0.0~1.0
                - state (str): 状态 'CLEANUP_COMPLETE', 'IN_PROGRESS', 'HIGH_LEVERAGE'
                - details (str): 详细说明文本
        
        Examples:
            >>> scorer = ResonanceScorer()
            >>> result = scorer.calculate_crypto_score(
            ...     oi_crash=True,
            ...     funding_positive=True,
            ...     elr_safe=True,
            ...     leverage_cleanup_confirmed=True
            ... )
            >>> print(result['score'])  # 1.0
            >>> print(result['state'])  # 'CLEANUP_COMPLETE'
        """
        try:
            if leverage_cleanup_confirmed:
                score = 1.0
                state = 'CLEANUP_COMPLETE'
                details = '加密市场去杠杆完成,费率转正+OI清洗+ELR安全'
                logger.info(f"加密评分: {score}分 - {details}")
                
            elif oi_crash:
                score = 0.5
                state = 'IN_PROGRESS'
                details = '加密市场清算进行中,OI断崖式下跌'
                logger.info(f"加密评分: {score}分 - {details}")
                
            else:
                score = 0.0
                state = 'HIGH_LEVERAGE'
                details = '加密市场仍处于高杠杆风险状态'
                logger.debug(f"加密评分: {score}分 - {details}")
            
            return {
                'score': score,
                'state': state,
                'details': details
            }
            
        except Exception as e:
            logger.error(f"加密评分计算异常: {str(e)}", exc_info=True)
            return {
                'score': 0.0,
                'state': 'ERROR',
                'details': f'计算异常: {str(e)}'
            }
    
    def calculate_darkpool_score(
        self,
        dix_flag: bool,
        short_ratio_flag: bool,
        stockgrid_flag: bool,
        dbmf_recovery: bool,
        aggregated_signal: bool
    ) -> Dict[str, any]:
        """计算暗盘维度分值（标准版，不支持降级）
        
        暗盘数据揭示机构大资金动向。DIX、卖空比、Stockgrid拐点三选二
        聚合信号，结合DBMF均线收复，确认强吸筹行为。
        
        Args:
            dix_flag: DIX > 45% 信号 (暗盘买入强度指标)
            short_ratio_flag: ChartExchange卖空比 > 45% 信号
            stockgrid_flag: Stockgrid拐点信号 (订单流失衡)
            dbmf_recovery: DBMF均线收复标志 (Dark Block Mean Flow)
            aggregated_signal: 三选二聚合信号 (至少2个指标触发)
        
        Returns:
            dict: 包含以下字段:
                - score (float): 分值 0.0~1.5
                - state (str): 状态 'STRONG_ACCUMULATION', 'MODERATE', 'WEAK'
                - details (str): 详细说明文本
        
        Examples:
            >>> scorer = ResonanceScorer()
            >>> result = scorer.calculate_darkpool_score(
            ...     dix_flag=True,
            ...     short_ratio_flag=True,
            ...     stockgrid_flag=False,
            ...     dbmf_recovery=True,
            ...     aggregated_signal=True
            ... )
            >>> print(result['score'])  # 1.5
            >>> print(result['state'])  # 'STRONG_ACCUMULATION'
        """
        try:
            signal_count = sum([dix_flag, short_ratio_flag, stockgrid_flag])
            
            if aggregated_signal and dbmf_recovery:
                score = 1.5
                state = 'STRONG_ACCUMULATION'
                details = (
                    f"暗盘强吸筹确认({signal_count}/3指标触发 + DBMF收复)"
                )
                logger.info(f"暗盘评分: {score}分 - {details}")
                
            elif aggregated_signal:
                score = 0.75
                state = 'MODERATE'
                details = f"暗盘中度吸筹({signal_count}/3指标触发)"
                logger.info(f"暗盘评分: {score}分 - {details}")
                
            else:
                score = 0.0
                state = 'WEAK'
                details = f"暗盘信号微弱({signal_count}/3指标触发)"
                logger.debug(f"暗盘评分: {score}分 - {details}")
            
            return {
                'score': score,
                'state': state,
                'details': details
            }
            
        except Exception as e:
            logger.error(f"暗盘评分计算异常: {str(e)}", exc_info=True)
            return {
                'score': 0.0,
                'state': 'ERROR',
                'details': f'计算异常: {str(e)}'
            }
    
    def calculate_darkpool_score_with_fallback(
        self,
        dix_flag: bool,
        short_ratio_flag: bool,
        stockgrid_flag: bool,
        dbmf_recovery: bool,
        available_sources: Optional[Dict[str, bool]] = None,
        
        preprocessed_bonus: float = 0.0,
    ) -> Dict[str, any]:
        """支持动态降级逻辑的暗盘评分系统 (v2.1 含 EMA 预处理加成)
        
        PRD 第 6 节要求：当某数据源失败时，自动放弃该校验，将判定权交给其他两源，
        权重不作调减。本方法实现这一动态权重重分配逻辑。
        
        available_sources: 标记哪些数据源本次爬取成功
                          例: {'dix': True, 'short_ratio': False, 'stockgrid': True}
                          None 表示全部可用（等同于标准版）
        
        Returns:
            dict: 包含 score, state, details
        """
        try:
            # 默认全部可用
            if available_sources is None:
                available_sources = {
                    'dix': True,
                    'short_ratio': True,
                    'stockgrid': True
                }
            
            # 统计当前可用的信号源总量
            total_available = sum(1 for v in available_sources.values() if v)
            
            # PRD 第6节：极端全解析失败退化
            if total_available == 0:
                logger.critical("[CRITICAL] 场外暗盘所有爬虫接口触发改版异常，已退化为纯本地实时衍生品计算流模式！")
                return {
                    'score': 0.0,
                    'state': 'DEGRADED_CRITICAL',
                    'details': '全部暗盘源失效，得分降为0'
                }

            # 仅统计当前存活源的有效触发数
            active_count = 0
            if available_sources.get('dix') and dix_flag:
                active_count += 1
            if available_sources.get('short_ratio') and short_ratio_flag:
                active_count += 1
            if available_sources.get('stockgrid') and stockgrid_flag:
                active_count += 1

            # 动态计算所需触发数（满源需要2个，2个存活源也需要2个印证，1个存活源需要1个）
            required_count = 2 if total_available >= 2 else 1

            # 分数判定：权重不作调减，依然最高1.5分
            if active_count >= required_count and dbmf_recovery:
                score = 1.5
                state = 'STRONG_ACCUMULATION_DEGRADED' if total_available < 3 else 'STRONG_ACCUMULATION'
            elif active_count >= required_count:
                score = 0.75
                state = 'MODERATE_DEGRADED' if total_available < 3 else 'MODERATE'
            else:
                score = 0.0
                state = 'WEAK'

            details = f"暗盘信号({active_count}/{total_available}可用源触发)"
            if total_available < 3:
                details += " [处于容错降级模式]"

            # v2.1: EMA 预处理加成 (零轴穿越/动量反转)
            bonus = min(preprocessed_bonus, 0.5)  # 加成上限 0.5
            if bonus > 0:
                score += bonus
                details += f" +EMA预处理加成+{bonus:.2f}"

            logger.info(f"暗盘评分(降级模式): {score:.2f}分 - {details}")

            return {
                'score': round(score, 2),
                'state': state,
                'details': details
            }

        except Exception as e:
            logger.error(f"降级评分计算异常: {e}", exc_info=True)
            return {
                'score': 0.0,
                'state': 'ERROR',
                'details': '计算异常'
            }
    
    @staticmethod
    def compute_preprocessed_bonus(preprocessed: Optional[Dict[str, any]]) -> float:
        """从暗盘预处理结果计算 EMA 加成值 (v2.1)
        
        信号规则:
        - 零轴向上穿越 (BULLISH): +0.25 (买入需求回归)
        - 动量反转预警 (EARLY_SELL_WARNING): +0.15 (早期预警注意)
        
        Args:
            preprocessed: darkpool_preprocessor.full_process() 的输出
        
        Returns:
            float: 加成值 (0.0 ~ 0.40)
        """
        if not preprocessed:
            return 0.0
        
        bonus = 0.0
        
        # 零轴穿越: 空头转多头 (买入需求回归)
        zero_cross = preprocessed.get('zero_cross', {})
        if zero_cross.get('signal') == 'BULLISH':
            bonus += 0.25
            logger.info(f"DarkPool EMA 加成: 零轴向上穿越 +0.25")
        
        # 动量反转预警: 早期抛售衰减 (卖出压力减轻)
        momentum = preprocessed.get('momentum_reversal', {})
        if momentum.get('signal') == 'EARLY_SELL_WARNING':
            bonus += 0.15
            logger.info(f"DarkPool EMA 加成: 动量反转预警 +0.15")
        
        return min(bonus, 0.5)

    def calculate_total_score(
        self,
        gex_result: Dict[str, any],
        vix_result: Dict[str, any],
        crypto_result: Dict[str, any],
        darkpool_result: Dict[str, any]
    ) -> Dict[str, any]:
        """计算共振总分并判定预警级别
        
        综合四个维度分值，计算共振百分比，并根据阈值判定预警级别。
        
        Args:
            gex_result: GEX维度评分结果 (来自 calculate_gex_score)
            vix_result: VIX维度评分结果 (来自 calculate_vix_score)
            crypto_result: 加密维度评分结果 (来自 calculate_crypto_score)
            darkpool_result: 暗盘维度评分结果 (来自 calculate_darkpool_score)
        
        Returns:
            dict: 包含以下字段:
                - total_score (float): 总分 (0~5.0)
                - max_score (float): 满分 (5.0)
                - resonance_pct (float): 共振百分比 (0~100%)
                - alert_level (str): 预警级别
                  'LEVEL_3' (>=3.5), 'LEVEL_2' (>=3.0), 
                  'LEVEL_1' (>=2.0), 'NO_SIGNAL' (<2.0)
                - dimension_scores (dict): 各维度详细得分
                - trigger_conditions (list): 触发的条件列表
        
        Examples:
            >>> scorer = ResonanceScorer()
            >>> gex = scorer.calculate_gex_score(-5e6, 2e6, True, 'IMPROVING')
            >>> vix = scorer.calculate_vix_score(0.95, 'DOWN', 5.2)
            >>> crypto = scorer.calculate_crypto_score(True, True, True, True)
            >>> darkpool = scorer.calculate_darkpool_score(True, True, False, True, True)
            >>> result = scorer.calculate_total_score(gex, vix, crypto, darkpool)
            >>> print(result['alert_level'])  # 'LEVEL_3'
            >>> print(result['resonance_pct'])  # 100.0
        """
        try:
            total_score = (
                gex_result['score'] +
                vix_result['score'] +
                crypto_result['score'] +
                darkpool_result['score']
            )
            
            max_score = Config.Thresholds.MAX_RESONANCE_SCORE  # 1.5 + 1.0 + 1.0 + 1.5
            resonance_pct = (total_score / max_score) * 100
            
            # 判定预警级别
            if total_score >= Config.Thresholds.LEVEL_3_THRESHOLD:
                alert_level = 'LEVEL_3'
                logger.warning(
                    f"🚨 LEVEL 3 共振抄底信号触发! "
                    f"总分: {total_score:.2f}/{max_score}"
                )
            elif total_score >= Config.Thresholds.LEVEL_2_THRESHOLD:
                alert_level = 'LEVEL_2'
                logger.warning(
                    f"⚠️ LEVEL 2 密切监控信号! "
                    f"总分: {total_score:.2f}/{max_score}"
                )
            elif total_score >= Config.Thresholds.LEVEL_1_THRESHOLD:
                alert_level = 'LEVEL_1'
                logger.info(
                    f"📊 LEVEL 1 初步关注信号! "
                    f"总分: {total_score:.2f}/{max_score}"
                )
            else:
                alert_level = 'NO_SIGNAL'
                logger.debug(
                    f"无信号 - 总分: {total_score:.2f}/{max_score}"
                )
            
            # 收集触发条件
            trigger_conditions = []
            if gex_result['score'] > 0:
                trigger_conditions.append(f"GEX: {gex_result['details']}")
            if vix_result['score'] > 0:
                trigger_conditions.append(f"VIX: {vix_result['details']}")
            if crypto_result['score'] > 0:
                trigger_conditions.append(f"CRYPTO: {crypto_result['details']}")
            if darkpool_result['score'] > 0:
                trigger_conditions.append(f"DARKPOOL: {darkpool_result['details']}")
            
            result = {
                'total_score': round(total_score, 2),
                'max_score': max_score,
                'resonance_pct': round(resonance_pct, 1),
                'alert_level': alert_level,
                'dimension_scores': {
                    'gex': gex_result,
                    'vix': vix_result,
                    'crypto': crypto_result,
                    'darkpool': darkpool_result
                },
                'trigger_conditions': trigger_conditions
            }
            
            logger.info(
                f"共振总分: {result['total_score']}/{result['max_score']} "
                f"({result['resonance_pct']}%) - {alert_level}"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"总分计算异常: {str(e)}", exc_info=True)
            return {
                'total_score': 0.0,
                'max_score': 5.0,
                'resonance_pct': 0.0,
                'alert_level': 'NO_SIGNAL',
                'dimension_scores': {},
                'trigger_conditions': [],
                'error': str(e)
            }
    
    def estimate_hawkes_branching_ratio(
        self,
        recent_price_changes: List[float],
        recent_volumes: List[float],
        window_minutes: int = 60
    ) -> Dict[str, any]:
        """Hawkes Process自激抛售测算 (AR(1) 自回归增强版)
        
        Hawkes Process用于建模金融市场的自激现象：价格下跌引发更多抛售，
        形成正反馈循环。分支比 (branching ratio) 衡量这种自激强度。
        
        v2.1 增强: 使用 AR(1) 自回归系数替代简单 corrcoef，更准确地捕捉
        价格下跌的自激效应。AR(1) 模型: y_t = ρ * y_{t-1} + ε_t，
        其中 |ρ| 即为分支比代理 —— ρ 越大，自激效应越强。
        
        若数据不足（<20 个点），退化为 corrcoef 方法保持鲁棒性。
        
        Args:
            recent_price_changes: 最近N分钟的价格变化列表 (每分钟一个点，单位: %)
            recent_volumes: 对应的成交量列表 (单位: 股或币)
            window_minutes: 时间窗口 (默认60分钟)
        
        Returns:
            dict: 包含以下字段:
                - branching_ratio (float): 分支比 (0~1)
                - state (str): 状态
                - self_excitation_intensity (float): 自激强度百分比
                - details (str): 详细说明文本
                - method (str): 计算方法 ('AR(1)' 或 'corrcoef')
        
        Examples:
            >>> scorer = ResonanceScorer()
            >>> prices = [-0.5, -0.8, -1.2, -0.3, -0.6, -0.9, -1.5, -0.4]
            >>> volumes = [1e6, 1.5e6, 2e6, 1.2e6, 1.8e6, 2.5e6, 3e6, 1.3e6]
            >>> result = scorer.estimate_hawkes_branching_ratio(prices, volumes)
            >>> print(result['branching_ratio'])  # AR(1) 系数
            >>> print(result['state'])  # 'SUBCRITICAL' or 'CRITICAL' etc.
        """
        try:
            if len(recent_price_changes) < 10 or len(recent_volumes) < 10:
                logger.warning(
                    f"数据不足: price_changes={len(recent_price_changes)}, "
                    f"volumes={len(recent_volumes)}"
                )
                return {
                    'branching_ratio': 0.5,
                    'state': 'INSUFFICIENT_DATA',
                    'self_excitation_intensity': 0.0,
                    'details': '数据不足,无法计算Hawkes分支比',
                    'method': 'none',
                }
            
            # ───── AR(1) 自回归方法 (v2.1 增强) ─────
            # 使用 OLS 估计 AR(1) 系数: ρ = Cov(y_t, y_{t-1}) / Var(y_{t-1})
            # 这比 corrcoef 更准确：直接测量当前价格变化对下一时刻的影响强度
            if len(recent_price_changes) >= 20:
                try:
                    y = np.array(recent_price_changes, dtype=float)
                    y_lag = y[:-1]   # y_{t-1}
                    y_curr = y[1:]   # y_t
                    
                    # OLS 估计 AR(1)
                    cov = np.cov(y_curr, y_lag, ddof=1)[0, 1]
                    var_lag = np.var(y_lag, ddof=1)
                    
                    if var_lag > 1e-12:
                        ar1_coef = cov / var_lag
                        # 分支比 = |AR(1)系数|, 截断到 [0, 1]
                        branching_ratio = max(0.0, min(1.0, abs(ar1_coef)))
                        method = 'AR(1)'
                        logger.debug(
                            f"AR(1) 分支比: ρ={ar1_coef:.4f}, "
                            f"|ρ|={branching_ratio:.4f}"
                        )
                    else:
                        # 方差退化 → 降级到 corrcoef
                        branching_ratio = None
                        method = None
                        logger.warning("AR(1) 方差退化，降级到 corrcoef")
                except Exception as ar1_err:
                    logger.warning(f"AR(1) 计算失败: {ar1_err}，降级到 corrcoef")
                    branching_ratio = None
                    method = None
            else:
                # 数据点不足 20 → 降级到 corrcoef
                branching_ratio = None
                method = None
                logger.debug(f"数据点 {len(recent_price_changes)} < 20, 使用 corrcoef 降级方法")
            
            # ───── corrcoef 降级方案 ─────
            if branching_ratio is None:
                # 提取价格下跌时段
                price_drops = [-p for p in recent_price_changes if p < 0]
                volume_spikes = [
                    v for v, p in zip(recent_volumes, recent_price_changes)
                    if p < 0
                ]
                
                if len(price_drops) < 5:
                    logger.info("价格下跌样本不足，判定为低自激状态")
                    return {
                        'branching_ratio': 0.3,
                        'state': 'SUBCRITICAL',
                        'self_excitation_intensity': 0.2,
                        'details': '价格下跌样本不足,判定为低自激状态',
                        'method': 'corrcoef',
                    }
                
                try:
                    corr_matrix = np.corrcoef(price_drops, volume_spikes)
                    if np.isnan(corr_matrix).any() or np.isinf(corr_matrix).any():
                        logger.warning("Correlation matrix contains NaN or Inf")
                        branching_ratio = 0.5
                    else:
                        correlation = corr_matrix[0, 1]
                        branching_ratio = max(0.0, min(1.0, correlation))
                    method = 'corrcoef'
                except Exception as e:
                    logger.error(f"Hawks corrcoef error: {e}")
                    branching_ratio = 0.5
                    method = 'corrcoef'
            
            # ───── 判定状态 ─────
            if branching_ratio < 0.7:
                state = 'SUBCRITICAL'
                details = (
                    f"分支比{branching_ratio:.2f}<0.7, "
                    f"自激抛售进入亚临界衰竭区间"
                )
            elif branching_ratio < 0.9:
                state = 'CRITICAL'
                details = (
                    f"分支比{branching_ratio:.2f}处于临界状态, "
                    f"警惕恐慌蔓延"
                )
            else:
                state = 'SUPERCRITICAL'
                details = (
                    f"分支比{branching_ratio:.2f}>0.9, "
                    f"超临界状态,机械性踩踏进行中"
                )
            
            result = {
                'branching_ratio': round(branching_ratio, 2),
                'state': state,
                'self_excitation_intensity': round(branching_ratio * 100, 1),
                'details': details,
                'method': method,
            }
            
            logger.info(
                f"Hawkes分支比[{method}]: "
                f"{result['branching_ratio']} - {state}"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Hawkes分支比计算异常: {str(e)}", exc_info=True)
            return {
                'branching_ratio': 0.5,
                'state': 'ERROR',
                'self_excitation_intensity': 0.0,
                'details': f'计算异常: {str(e)}',
                'method': 'error',
            }
