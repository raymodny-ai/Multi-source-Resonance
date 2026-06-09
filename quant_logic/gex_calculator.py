"""
多源共振监控系统 - Gamma敞口(GEX)计算引擎

该模块实现期权Gamma风险暴露的计算和分析,包括:
- Black-Scholes模型Delta和Gamma计算
- 投资组合级别GEX聚合计算
- Flip Zone和Put Wall识别
- 盘后校准系数动态更新

技术实现:
- 使用scipy.stats进行概率分布计算
- Pandas向量化运算提升性能
- 支持内存中快速计算和批量处理
"""

import numpy as np
import pandas as pd
from scipy import stats
from typing import Dict, List, Optional, Tuple
from utils.logger import getLogger
from config.settings import Config

logger = getLogger('gex_calculator')


class GEXCalculator:
    """Gamma敞口(GEX)计算引擎
    
    基于Black-Scholes模型计算期权的Gamma风险暴露,用于识别市场做市商的对冲行为
    和潜在的支撑/阻力位。
    
    Attributes:
        RISK_FREE_RATE: 无风险利率(默认5%)
        CONTRACT_MULTIPLIER: 美股期权合约乘数(100股/合约)
    """
    
    RISK_FREE_RATE = Config.Thresholds.GEX_RISK_FREE_RATE  # 无风险利率5%
    CONTRACT_MULTIPLIER = Config.Thresholds.GEX_CONTRACT_MULTIPLIER  # 美股期权合约乘数
    
    @staticmethod
    def _validate_inputs(
        strike: float, 
        spot: float, 
        volatility: float, 
        time_to_expiry: float
    ) -> bool:
        """验证输入参数有效性
        
        Args:
            strike: 行权价
            spot: 标的资产价格
            volatility: 隐含波动率
            time_to_expiry: 到期时间
            
        Returns:
            bool: 参数是否有效
        """
        if strike <= 0 or spot <= 0:
            return False
        if volatility < Config.Thresholds.GEX_VOLATILITY_MIN or volatility > Config.Thresholds.GEX_VOLATILITY_MAX:
            logger.warning(f"Volatility out of range [{Config.Thresholds.GEX_VOLATILITY_MIN}, {Config.Thresholds.GEX_VOLATILITY_MAX}]: {volatility}")
            return False
        if time_to_expiry <= Config.Thresholds.GEX_TIME_TO_EXPIRY_MIN:
            return False
        return True
    
    @staticmethod
    def _calculate_d1(
        strike: float, 
        spot: float, 
        volatility: float, 
        time_to_expiry: float
    ) -> float:
        """计算Black-Scholes d1参数(增加除零保护)
        
        Args:
            strike: 行权价
            spot: 标的资产价格
            volatility: 隐含波动率(年化)
            time_to_expiry: 到期时间(年)
            
        Returns:
            float: d1值
        """
        # 输入验证
        if strike <= 0 or spot <= 0:
            logger.warning(f"Invalid strike({strike}) or spot({spot})")
            return 0.0
        
        if time_to_expiry <= 0:
            logger.debug("Time to expiry is zero or negative, returning 0")
            return 0.0
        
        if volatility <= 0:
            logger.warning(f"Invalid volatility: {volatility}")
            return 0.0
        
        try:
            # 防止除零
            denom = volatility * np.sqrt(time_to_expiry)
            if abs(denom) < 1e-10:
                logger.warning("Denominator near zero in d1 calculation")
                return 0.0
            
            d1 = (
                np.log(spot / strike) + 
                (GEXCalculator.RISK_FREE_RATE + 0.5 * volatility**2) * time_to_expiry
            ) / denom
            
            # 检查NaN和Inf
            if np.isnan(d1) or np.isinf(d1):
                logger.warning(f"d1 is NaN or Inf: {d1}")
                return 0.0
            
            return d1
        except (ZeroDivisionError, ValueError, OverflowError) as e:
            logger.error(f"d1 calculation error: {e}")
            return 0.0
    
    @staticmethod
    def _calculate_d2(d1: float, volatility: float, time_to_expiry: float) -> float:
        """计算Black-Scholes d2参数
        
        Args:
            d1: d1值
            volatility: 隐含波动率
            time_to_expiry: 到期时间
            
        Returns:
            float: d2值
        """
        return d1 - volatility * np.sqrt(time_to_expiry)
    
    def calculate_delta(
        self, 
        strike: float, 
        spot: float, 
        volatility: float, 
        time_to_expiry: float, 
        option_type: str = 'CALL'
    ) -> float:
        """计算期权Delta
        
        Delta衡量期权价格对标的资产价格变动的敏感度。
        
        Args:
            strike: 行权价
            spot: 标的资产价格
            volatility: 隐含波动率(年化)
            time_to_expiry: 到期时间(年)
            option_type: 期权类型 ('CALL' 或 'PUT')
            
        Returns:
            float: Delta值
                - CALL期权: 0 ~ 1
                - PUT期权: -1 ~ 0
                
        Examples:
            >>> calc = GEXCalculator()
            >>> delta = calc.calculate_delta(100, 105, 0.2, 0.25, 'CALL')
            >>> print(f"Call Delta: {delta:.4f}")  # 约0.7左右
        """
        d1 = self._calculate_d1(strike, spot, volatility, time_to_expiry)
        
        if option_type.upper() == 'CALL':
            delta = stats.norm.cdf(d1)
        elif option_type.upper() == 'PUT':
            delta = stats.norm.cdf(d1) - 1
        else:
            raise ValueError(f"Invalid option_type: {option_type}. Use 'CALL' or 'PUT'.")
        
        return delta
    
    def calculate_gamma(
        self, 
        strike: float, 
        spot: float, 
        volatility: float, 
        time_to_expiry: float
    ) -> float:
        """计算期权Gamma(增加除零保护)
        
        Gamma衡量Delta对标的资产价格变动的敏感度,始终为正值。
        
        Args:
            strike: 行权价
            spot: 标的资产价格
            volatility: 隐含波动率(年化)
            time_to_expiry: 到期时间(年)
            
        Returns:
            float: Gamma值(始终为正)
            
        Examples:
            >>> calc = GEXCalculator()
            >>> gamma = calc.calculate_gamma(100, 105, 0.2, 0.25)
            >>> print(f"Gamma: {gamma:.6f}")
        """
        if not self._validate_inputs(strike, spot, volatility, time_to_expiry):
            return 0.0
        
        d1 = self._calculate_d1(strike, spot, volatility, time_to_expiry)
        
        if d1 == 0.0:
            return 0.0
        
        try:
            denom = spot * volatility * np.sqrt(time_to_expiry)
            if abs(denom) < 1e-10:
                return 0.0
            
            gamma = stats.norm.pdf(d1) / denom
            
            # 检查NaN和Inf
            if np.isnan(gamma) or np.isinf(gamma):
                return 0.0
            
            return gamma
        except (ZeroDivisionError, ValueError) as e:
            logger.error(f"Gamma calculation error: {e}")
            return 0.0
    
    def calculate_portfolio_gex(
        self, 
        option_chain_df: pd.DataFrame, 
        spot_price: float
    ) -> Dict[str, any]:
        """计算整个期权组合的名义GEX敞口
        
        使用向量化运算批量计算所有期权合约的Gamma,然后按持仓量加权求和。
        
        计算公式:
            GEX_i = gamma_i * contract_multiplier * open_interest_i * spot_price²
            Total GEX = Σ(GEX_CALL) - Σ(GEX_PUT)
        
        Args:
            option_chain_df: 期权链DataFrame,必须包含以下列:
                - strike: 行权价
                - type: 期权类型 ('CALL' 或 'PUT')
                - expiry: 到期日期
                - bid: 买价
                - ask: 卖价
                - volume: 成交量
                - open_interest: 未平仓合约数
            spot_price: 标的资产当前价格
            
        Returns:
            dict: GEX计算结果
                {
                    'total_gex': float,           # 总GEX(美元)
                    'call_gex': float,            # Call端GEX
                    'put_gex': float,             # Put端GEX
                    'gex_by_strike': dict,        # 按行权价分组的GEX {strike: gex_value}
                    'net_gex': float              # 净GEX(Call - Put)
                }
                
        Examples:
            >>> calc = GEXCalculator()
            >>> df = pd.DataFrame({
            ...     'strike': [100, 105, 110],
            ...     'type': ['CALL', 'CALL', 'PUT'],
            ...     'expiry': ['2024-01-19'] * 3,
            ...     'bid': [5.0, 2.0, 3.0],
            ...     'ask': [5.5, 2.5, 3.5],
            ...     'volume': [100, 200, 150],
            ...     'open_interest': [1000, 2000, 1500]
            ... })
            >>> result = calc.calculate_portfolio_gex(df, 105.0)
            >>> print(f"Total GEX: ${result['total_gex']:,.2f}")
        """
        if option_chain_df.empty:
            logger.warning("Empty option chain DataFrame")
            return {
                'total_gex': 0.0,
                'call_gex': 0.0,
                'put_gex': 0.0,
                'gex_by_strike': {},
                'net_gex': 0.0
            }
        
        # 过滤无效数据
        df = option_chain_df.copy()
        df = df[df['open_interest'] > 0]  # 过滤无持仓的合约
        
        if df.empty:
            logger.warning("No valid options with open interest > 0")
            return {
                'total_gex': 0.0,
                'call_gex': 0.0,
                'put_gex': 0.0,
                'gex_by_strike': {},
                'net_gex': 0.0
            }
        
        # 假设波动率和到期时间(实际应从市场数据获取)
        # 这里使用默认值作为示例
        df['volatility'] = df.get('implied_volatility', 0.2)  # 默认20%波动率
        df['time_to_expiry'] = df.get('days_to_expiry', 30) / 365.0  # 默认30天
        
        # 向量化计算Gamma
        df['gamma'] = df.apply(
            lambda row: self.calculate_gamma(
                strike=row['strike'],
                spot=spot_price,
                volatility=row['volatility'],
                time_to_expiry=row['time_to_expiry']
            ),
            axis=1
        )
        
        # 计算每个合约的GEX贡献
        # GEX_i = gamma_i * 100 * open_interest_i * spot_price²
        df['gex_contribution'] = (
            df['gamma'] * 
            self.CONTRACT_MULTIPLIER * 
            df['open_interest'] * 
            spot_price**2
        )
        
        # 分离Call和Put
        call_mask = df['type'].str.upper() == 'CALL'
        put_mask = df['type'].str.upper() == 'PUT'
        
        call_gex = df.loc[call_mask, 'gex_contribution'].sum()
        put_gex = df.loc[put_mask, 'gex_contribution'].sum()
        
        # 按行权价分组
        gex_by_strike = df.groupby('strike')['gex_contribution'].sum().to_dict()
        
        # 计算净值
        net_gex = call_gex - put_gex
        
        result = {
            'total_gex': call_gex + put_gex,
            'call_gex': call_gex,
            'put_gex': put_gex,
            'gex_by_strike': gex_by_strike,
            'net_gex': net_gex
        }
        
        logger.info(
            f"GEX Calculation Complete: "
            f"Call=${call_gex:,.2f}, Put=${put_gex:,.2f}, Net=${net_gex:,.2f}"
        )
        
        return result
    
    def identify_flip_zone(
        self, 
        gex_profile: Dict[float, float], 
        spot_range: Optional[List[float]] = None
    ) -> Dict[str, any]:
        """识别GEX翻转区域(由负转正的价格区间)
        
        Flip Zone是GEX从负值转变为正值的临界价格区域,通常代表重要的支撑/阻力位。
        
        Args:
            gex_profile: GEX按价格分布的字典 {price: gex_value}
            spot_range: 价格扫描范围 [min, max, step], 
                       默认为 [spot*0.9, spot*1.1, 10]
            
        Returns:
            dict: Flip Zone信息
                {
                    'flip_zone_lower': float,     # Flip Zone下界
                    'flip_zone_upper': float,     # Flip Zone上界
                    'flip_point': float,          # 精确翻转点(线性插值)
                    'is_positive': bool           # 当前GEX是否为正
                }
                
        Examples:
            >>> calc = GEXCalculator()
            >>> profile = {100: -500000, 105: -100000, 110: 200000, 115: 500000}
            >>> flip = calc.identify_flip_zone(profile)
            >>> print(f"Flip Zone: {flip['flip_zone_lower']} - {flip['flip_zone_upper']}")
        """
        if not gex_profile:
            logger.warning("Empty GEX profile")
            return {
                'flip_zone_lower': 0.0,
                'flip_zone_upper': 0.0,
                'flip_point': 0.0,
                'is_positive': False
            }
        
        # 按价格排序
        sorted_prices = sorted(gex_profile.keys())
        gex_values = [gex_profile[p] for p in sorted_prices]
        
        # 检查当前状态
        current_gex = gex_profile.get(sorted_prices[-1], 0)
        is_positive = current_gex > 0
        
        # 寻找符号变化点
        flip_points = []
        for i in range(len(gex_values) - 1):
            if gex_values[i] * gex_values[i+1] < 0:  # 符号相反
                # 线性插值找到精确翻转点
                price1, price2 = sorted_prices[i], sorted_prices[i+1]
                gex1, gex2 = gex_values[i], gex_values[i+1]
                
                # 线性插值: flip_point = price1 + (0 - gex1) * (price2 - price1) / (gex2 - gex1)
                if gex2 != gex1:
                    flip_point = price1 + (-gex1) * (price2 - price1) / (gex2 - gex1)
                    flip_points.append((price1, price2, flip_point))
        
        if flip_points:
            # 取第一个翻转点(最接近当前价格的)
            lower, upper, flip_point = flip_points[0]
            return {
                'flip_zone_lower': lower,
                'flip_zone_upper': upper,
                'flip_point': flip_point,
                'is_positive': is_positive
            }
        else:
            # 没有找到翻转点
            return {
                'flip_zone_lower': sorted_prices[0],
                'flip_zone_upper': sorted_prices[-1],
                'flip_point': np.mean(sorted_prices),
                'is_positive': is_positive
            }
    
    def find_put_wall(self, gex_by_strike: Dict[float, float]) -> float:
        """找到Put Wall支撑位(Put Gamma绝对值最大的行权价)
        
        Put Wall是Put Gamma累积值最大的行权价,通常构成强支撑位。
        
        Args:
            gex_by_strike: 按行权价分组的GEX字典 {strike: gex_value}
                          (Put的GEX值为负)
            
        Returns:
            float: Put Wall的行权价,如果没有Put则返回0
            
        Examples:
            >>> calc = GEXCalculator()
            >>> gex_strikes = {100: -500000, 105: -300000, 110: 200000}
            >>> wall = calc.find_put_wall(gex_strikes)
            >>> print(f"Put Wall at: ${wall}")
        """
        if not gex_by_strike:
            return 0.0
        
        # 找到最小的GEX值(最大的负值,即Put Wall)
        put_strikes = {k: v for k, v in gex_by_strike.items() if v < 0}
        
        if not put_strikes:
            logger.info("No Put positions found")
            return 0.0
        
        # 返回绝对值最大的Put行权价
        put_wall_strike = min(put_strikes, key=lambda k: put_strikes[k])
        
        logger.info(f"Put Wall identified at strike: ${put_wall_strike}")
        return put_wall_strike
    
    @staticmethod
    def calibrate_alpha(local_gex: float, official_gex: float) -> float:
        """计算校准系数α
        
        用于将本地估算的GEX与官方数据对齐。
        
        Args:
            local_gex: 本地估算GEX
            official_gex: SqueezeMetrics官方GEX
            
        Returns:
            float: 校准系数 alpha = official_gex / local_gex
                  如果local_gex为0,返回1.0作为安全默认值
                  
        Examples:
            >>> alpha = GEXCalculator.calibrate_alpha(1000000, 1200000)
            >>> print(f"Alpha: {alpha}")  # 1.2
        """
        if abs(local_gex) < 1e-10:
            logger.warning("Local GEX near zero, returning alpha=1.0")
            return 1.0
        
        alpha = official_gex / local_gex
        
        logger.debug(f"Calibration alpha calculated: {alpha:.4f}")
        return alpha
    
    @staticmethod
    def apply_calibration(gex_local: float, alpha: float) -> float:
        """应用校准系数
        
        Args:
            gex_local: 本地计算的GEX值
            alpha: 校准系数
            
        Returns:
            float: 校准后的GEX值
        """
        return gex_local * alpha


# 便捷函数
def calculate_single_option_gex(
    strike: float,
    spot: float,
    volatility: float,
    time_to_expiry: float,
    open_interest: int,
    option_type: str = 'CALL'
) -> float:
    """快速计算单个期权的GEX贡献
    
    Args:
        strike: 行权价
        spot: 标的价格
        volatility: 波动率
        time_to_expiry: 到期时间(年)
        open_interest: 未平仓合约数
        option_type: 期权类型
        
    Returns:
        float: GEX值(美元)
    """
    calc = GEXCalculator()
    gamma = calc.calculate_gamma(strike, spot, volatility, time_to_expiry)
    gex = gamma * GEXCalculator.CONTRACT_MULTIPLIER * open_interest * spot**2
    
    if option_type.upper() == 'PUT':
        gex = -gex  # Put的GEX为负
    
    return gex
