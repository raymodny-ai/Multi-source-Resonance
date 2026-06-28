"""
多源共振监控系统 V2.0 - Gamma敞口(GEX)计算引擎

该模块实现期权Gamma风险暴露的计算和分析,包括:
- Black-Scholes模型Delta和Gamma计算
- 投资组合级别GEX聚合计算（向量化版）
- Flip Zone和Put Wall识别
- GEX Profile 曲线生成
- 净 Gamma 区间分类
- 盘后校准系数动态更新

技术实现:
- 可选 py_vollib_vectorized 加速（导入 bs_engine 向量化引擎）
- Polars/Pandas 向量化运算提升性能
- 支持内存中快速计算和批量处理

该模块为 Layer 1 纯本地计算组件，严禁任何 LLM 依赖。
"""

import numpy as np
import pandas as pd
from scipy import stats
from typing import Dict, List, Optional, Tuple
from utils.logger import getLogger
from config.settings import Config

# V2.0: 导入向量化 BS 引擎（可选）
try:
    from quant_logic.bs_engine import VectorizedBSEngine
    VECTORIZED_AVAILABLE = True
except ImportError:
    VECTORIZED_AVAILABLE = False

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

    def __init__(self):
        """初始化 GEX 计算引擎 (V2.0: 懒加载向量化 BS 引擎)"""
        self._bs_engine = None

    # ═══════════════════════════════════════════
    # V2.5 P1 优化: 双重流动性门控
    # ═══════════════════════════════════════════

    @staticmethod
    def apply_liquidity_gate(
        option_chain_df: pd.DataFrame,
        oi_threshold: Optional[int] = None,
        spread_pct_threshold: Optional[float] = None,
        low_price_threshold: Optional[float] = None,
        low_price_abs_spread: Optional[float] = None,
    ) -> Tuple[pd.DataFrame, Dict[str, int]]:
        """V2.5 双重流动性门控

        隔离做市商宽幅挂单导致的"僵尸报价"污染。
        三道过滤:
          1) OI 门控: 剔除 OI < 500 的非活跃合约
          2) 相对价差门控: 剔除 Spread% > 10% 的合约
          3) 低价合约绝对价差门控: 价格 < 1美元 且 Ask-Bid > 0.10

        Args:
            option_chain_df: 期权链 DataFrame, 必含 open_interest, bid, ask
            oi_threshold: OI 阈值, 默认从 Config.Thresholds.OI_GATE_THRESHOLD
            spread_pct_threshold: Spread% 阈值, 默认 10.0
            low_price_threshold: 低价阈值, 默认 1.0
            low_price_abs_spread: 绝对价差阈值, 默认 0.10

        Returns:
            (filtered_df, stats_dict):
              - filtered_df: 通过门控的合约
              - stats_dict: {原始/过滤后/被剔除数, 各阶段剔除数}
        """
        if option_chain_df.empty:
            return option_chain_df.copy(), {
                'original_count': 0, 'kept_count': 0, 'removed_count': 0,
                'removed_oi': 0, 'removed_spread': 0, 'removed_low_price_spread': 0,
            }

        # 读取默认阈值
        oi_thr = oi_threshold if oi_threshold is not None else Config.Thresholds.OI_GATE_THRESHOLD
        sp_thr = spread_pct_threshold if spread_pct_threshold is not None else Config.Thresholds.SPREAD_PCT_GATE_THRESHOLD
        lp_thr = low_price_threshold if low_price_threshold is not None else Config.Thresholds.LOW_PRICE_THRESHOLD
        lp_abs = low_price_abs_spread if low_price_abs_spread is not None else Config.Thresholds.LOW_PRICE_ABS_SPREAD_GATE

        original_count = len(option_chain_df)
        df = option_chain_df.copy()

        # 准备 spread 字段 (V2.5 P1: 容错处理, 缺列时仅 OI 门控)
        has_spread_data = 'ask' in df.columns and 'bid' in df.columns
        if has_spread_data:
            if 'spread' not in df.columns:
                df['spread'] = (df['ask'] - df['bid']).clip(lower=0.0)
            if 'mid_price' not in df.columns:
                df['mid_price'] = (df['ask'] + df['bid']) / 2.0
            if 'spread_pct' not in df.columns:
                df['spread_pct'] = np.where(
                    df['ask'] > 0,
                    df['spread'] / df['ask'] * 100.0,
                    np.nan,
                )

        # ── 阶段 1: OI 门控 (总是执行) ──
        oi_mask = df['open_interest'] >= oi_thr
        removed_oi_count = int((~oi_mask).sum())

        df = df[oi_mask].copy()

        # ── 阶段 2: 价差门控 (仅当有 bid/ask 数据) ──
        if has_spread_data and len(df) > 0:
            # 中价 >= 1美元:  使用百分比阈值
            normal_mask = (df['mid_price'] >= lp_thr) & (df['spread_pct'] <= sp_thr)
            # 低价合约: 使用绝对价差阈值
            low_price_mask = (df['mid_price'] < lp_thr) & (df['spread'] <= lp_abs)
            spread_mask = normal_mask | low_price_mask

            removed_spread = int((~spread_mask).sum())
            low_price_high_spread = int(
                ((df['mid_price'] < lp_thr) & (df['spread'] > lp_abs)).sum()
            )
            normal_high_spread = removed_spread - low_price_high_spread

            df = df[spread_mask].copy()
        else:
            # 无 bid/ask 数据: 跳过价差门控
            normal_high_spread = 0
            low_price_high_spread = 0

        kept_count = len(df)
        stats = {
            'original_count': original_count,
            'kept_count': kept_count,
            'removed_count': original_count - kept_count,
            'removed_oi': removed_oi_count,
            'removed_spread': normal_high_spread,
            'removed_low_price_spread': low_price_high_spread,
            'oi_threshold': oi_thr,
            'spread_pct_threshold': sp_thr if has_spread_data else None,
            'low_price_threshold': lp_thr if has_spread_data else None,
            'low_price_abs_spread': lp_abs if has_spread_data else None,
            'has_spread_data': has_spread_data,
        }

        removal_pct = (original_count - kept_count) / original_count * 100 if original_count > 0 else 0
        spread_info = (
            f", 价差 -{normal_high_spread}, 低价绝对价差 -{low_price_high_spread}"
            if has_spread_data else " (无 bid/ask 数据, 跳过价差门控)"
        )
        logger.info(
            f"[流动性门控] 原始 {original_count} → 保留 {kept_count} "
            f"(剔除 {original_count - kept_count}, {removal_pct:.1f}%); "
            f"OI 门控 -{removed_oi_count}{spread_info}"
        )
        return df, stats

    def apply_zero_dte_protection(
        self,
        option_chain_df: pd.DataFrame,
        zero_dte_oi_threshold: Optional[int] = None,
    ) -> pd.DataFrame:
        """V2.5 0DTE 流动性保护

        0DTE 期权流动性虽低, 但对盘中 Flip 判定极重要, 放宽 OI 阈值。
        """
        if option_chain_df.empty or 'days_to_expiry' not in option_chain_df.columns:
            return option_chain_df

        zero_dte_thr = (
            zero_dte_oi_threshold if zero_dte_oi_threshold is not None
            else Config.Thresholds.ZERO_DTE_OI_GATE
        )
        zero_dte_days = Config.Thresholds.ZERO_DTE_DAYS

        df = option_chain_df.copy()
        is_zero_dte = df['days_to_expiry'] <= zero_dte_days
        # 0DTE 用更宽松的 OI 阈值
        relaxed_oi_mask = (df['open_interest'] >= zero_dte_thr) | (~is_zero_dte)
        return df[relaxed_oi_mask].copy()

    @property
    def bs_engine(self):
        """懒加载向量化 BS 引擎"""
        if self._bs_engine is None and VECTORIZED_AVAILABLE:
            self._bs_engine = VectorizedBSEngine(
                risk_free_rate=self.RISK_FREE_RATE
            )
        return self._bs_engine

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

    # ═══════════════════════════════════════════
    # V2.0 新增方法
    # ═══════════════════════════════════════════

    def calculate_portfolio_gex_vectorized(
        self,
        option_chain_df: pd.DataFrame,
        spot_price: float,
        symbol: Optional[str] = None,
    ) -> Dict[str, any]:
        """向量化版组合 GEX 计算 (V2.0)

        使用 bs_engine 向量化引擎或 NumPy 批量计算所有期权合约的 Gamma，
        避免逐行 apply()，实现百万级合约的秒级处理。

        Args:
            option_chain_df: 期权链 DataFrame，须含 strike, type, expiry,
                             bid, ask, volume, open_interest, implied_volatility,
                             days_to_expiry
            spot_price: 标的资产当前价格
            symbol: 标的代码 (e.g. 'SPX'). 若提供, 应用 alpha 校准
                    使 net_gex 与 GEXMetrix 官方值对齐 (v2.4 校准)
                    None = 跳过校准, 返回原始本地估值 (向后兼容)

        Returns:
            同 calculate_portfolio_gex 的返回格式 + 'net_gex_calibrated': bool
        """
        if option_chain_df.empty:
            return self._empty_gex_result()

        df = option_chain_df.copy()

        # V2.5 P1 优化: 双重流动性门控 (OI + Spread%)
        # 隔离做市商宽幅挂单导致的"僵尸报价"污染
        df, _gate_stats = self.apply_liquidity_gate(df)
        if df.empty:
            return self._empty_gex_result()

        # V2.5 P1 优化: 0DTE 流动性保护 (放宽 OI 阈值)
        df = self.apply_zero_dte_protection(df)
        if df.empty:
            return self._empty_gex_result()

        # 准备向量化输入
        strikes = df['strike'].to_numpy(dtype=float)
        vols = df.get('implied_volatility', pd.Series(0.2, index=df.index)).to_numpy(dtype=float)
        T = (df.get('days_to_expiry', pd.Series(30, index=df.index)) / 365.0).to_numpy(dtype=float)
        oi = df['open_interest'].to_numpy(dtype=float)
        option_types = df['type'].to_numpy()

        # 向量化 Gamma 计算
        if VECTORIZED_AVAILABLE and self.bs_engine is not None:
            gamma = self.bs_engine.compute_gamma_only(
                S=np.array([spot_price]),
                K=strikes,
                sigma=vols,
                T=T,
            )
        else:
            # 降级：NumPy 向量化
            d1 = (np.log(spot_price / strikes) + (self.RISK_FREE_RATE + 0.5 * vols**2) * T) / (vols * np.sqrt(np.maximum(T, 1e-10)))
            gamma = stats.norm.pdf(d1) / (spot_price * vols * np.sqrt(np.maximum(T, 1e-10)))
            gamma = np.where(np.isnan(gamma) | np.isinf(gamma), 0.0, gamma)

        # GEX 贡献 = gamma * 100 * OI * S^2
        gex_contrib = gamma * self.CONTRACT_MULTIPLIER * oi * spot_price**2
        gex_contrib = np.where(np.isnan(gex_contrib), 0.0, gex_contrib)

        # Call / Put 分离
        is_call = np.array([t.upper() == 'CALL' for t in option_types])
        is_put = ~is_call
        call_gex = float(np.sum(gex_contrib[is_call]))
        put_gex = float(np.sum(gex_contrib[is_put]))
        net_gex = call_gex - put_gex

        # v2.4: alpha 校准 (与 GEXMetrix 官方对齐)
        net_gex_calibrated = False
        if symbol is not None:
            try:
                from quant_logic.alpha_calibrator import get_effective_alpha
                alpha = get_effective_alpha(symbol)
                if alpha is not None and 0.5 <= alpha <= 1.5:  # sanity range
                    net_gex *= alpha
                    net_gex_calibrated = True
            except ImportError:
                # alpha_calibrator 不可用 (开发/测试场景), 跳过
                pass
            except Exception as e:
                logger.debug(f"alpha calibration skipped for {symbol}: {e}")

        # 按行权价分组
        gex_by_strike = {}
        for i, strike in enumerate(strikes):
            s = float(strike)
            gex_by_strike[s] = gex_by_strike.get(s, 0.0) + float(gex_contrib[i])

        logger.info(
            f"[V2.0 Vectorized] GEX: Call=${call_gex/1e9:.2f}B, "
            f"Put=${put_gex/1e9:.2f}B, Net=${net_gex/1e9:.2f}B"
        )

        return {
            'total_gex': float(call_gex + put_gex),
            'call_gex': float(call_gex),
            'put_gex': float(put_gex),
            'gex_by_strike': gex_by_strike,
            'net_gex': float(net_gex),
            'net_gex_calibrated': net_gex_calibrated,
        }

    def calculate_gex_profile(
        self,
        option_chain_df: pd.DataFrame,
        spot_price: float,
        price_range_pct: float = 0.10,
        num_steps: int = 40,
        symbol: Optional[str] = None,
    ) -> Dict[str, any]:
        """生成完整 GEX 曲线 (Net GEX vs Price) (V2.0)

        按 0.5% 价格步长计算不同标的价格下的净 GEX，用于精确 Flip Zone 定位。

        Args:
            option_chain_df: 期权链 DataFrame
            spot_price: 当前标的价格
            price_range_pct: 价格扫描范围 (±10%)
            num_steps: 扫描步数
            symbol: 标的代码 (可选, v2.4 alpha 校准)

        Returns:
            {
                'spot_prices': [price_0, price_1, ...],
                'net_gex_values': [gex_0, gex_1, ...],
                'current_spot': spot_price,
                'current_net_gex': float,
            }
        """
        low = spot_price * (1 - price_range_pct)
        high = spot_price * (1 + price_range_pct)
        scan_prices = np.linspace(low, high, num_steps)

        net_gex_values = []
        for p in scan_prices:
            result = self.calculate_portfolio_gex_vectorized(option_chain_df, p, symbol)
            net_gex_values.append(result['net_gex'])

        current_result = self.calculate_portfolio_gex_vectorized(option_chain_df, spot_price, symbol)

        return {
            'spot_prices': scan_prices.tolist(),
            'net_gex_values': net_gex_values,
            'current_spot': spot_price,
            'current_net_gex': current_result['net_gex'],
        }

    def calculate_gex_profile_fast(
        self,
        option_chain_df: pd.DataFrame,
        spot_price: float,
        price_range_pct: float = 0.10,
        num_steps: int = 100,
        symbol: Optional[str] = None,
        prefer_gpu: bool = True,
    ) -> Dict[str, any]:
        """V2.5 P3: fast-vollib 加速版 GEX Profile 扫描

        2D Gamma 网格一次计算所有价格点 × 所有行权价的 Gamma,
        避免循环调用 BS 引擎的 Python overhead。

        Args:
            option_chain_df: 期权链 DataFrame
            spot_price: 当前标的价格
            price_range_pct: 价格扫描范围
            num_steps: 扫描步数 (默认 100, 较默认 40 步加密)
            symbol: 标的代码
            prefer_gpu: 是否优先 GPU 后端
        Returns:
            同 calculate_gex_profile, 增加 'backend' 字段
        """
        try:
            from quant_logic.fast_vollib_engine import FastVollibEngine
        except ImportError:
            logger.warning("fast_vollib_engine 不可用, 降级到 calculate_gex_profile")
            return self.calculate_gex_profile(
                option_chain_df, spot_price, price_range_pct, num_steps, symbol
            )

        # 应用流动性门控 (与 calculate_gex_profile 行为一致)
        df, _ = self.apply_liquidity_gate(option_chain_df)
        if df.empty:
            return {
                'spot_prices': [],
                'net_gex_values': [],
                'current_spot': spot_price,
                'current_net_gex': 0.0,
                'backend': 'none',
            }

        # 准备数据
        strikes = df['strike'].to_numpy(dtype=float)
        vols = df.get('implied_volatility', pd.Series(0.2, index=df.index)).to_numpy(dtype=float)
        T = (df.get('days_to_expiry', pd.Series(30, index=df.index)) / 365.0).to_numpy(dtype=float)
        oi = df['open_interest'].to_numpy(dtype=float)
        option_types = df['type'].to_numpy()

        # 价格网格
        low = spot_price * (1 - price_range_pct)
        high = spot_price * (1 + price_range_pct)
        S_grid = np.linspace(low, high, num_steps)

        # 2D Gamma 计算
        engine = FastVollibEngine(prefer_gpu=prefer_gpu, risk_free_rate=self.RISK_FREE_RATE)
        gamma_grid = engine.compute_gamma_grid_2d(S_grid, strikes, vols, T)
        # gamma_grid shape: (num_steps, n_strikes)

        # GEX 计算: gamma * multiplier * OI * S^2
        # 广播: (n_steps, 1) × (1, n_strikes)
        multiplier = self.CONTRACT_MULTIPLIER
        oi_row = oi[None, :]
        S_col = S_grid[:, None]
        gex_grid = gamma_grid * multiplier * oi_row * S_col ** 2
        gex_grid = np.where(np.isfinite(gex_grid), gex_grid, 0.0)

        # Call / Put 分离
        is_call = np.array([t.upper() == 'CALL' for t in option_types])
        call_mask = is_call[None, :]
        put_mask = ~is_call
        put_mask_b = put_mask[None, :]

        call_gex_per_step = gex_grid * call_mask  # put 部分置 0
        put_gex_per_step = gex_grid * put_mask_b
        net_gex_values = np.sum(call_gex_per_step, axis=1) - np.sum(put_gex_per_step, axis=1)

        # 当前 spot 处的 GEX
        idx = np.argmin(np.abs(S_grid - spot_price))
        current_net_gex = float(net_gex_values[idx])

        return {
            'spot_prices': S_grid.tolist(),
            'net_gex_values': net_gex_values.tolist(),
            'current_spot': spot_price,
            'current_net_gex': current_net_gex,
            'backend': engine.backend,
        }

    def calculate_gex_profile_adaptive(
        self,
        option_chain_df: pd.DataFrame,
        spot_price: float,
        coarse_steps: int = 40,
        fine_steps: int = 120,
        expand_pct: float = 0.005,
        symbol: Optional[str] = None,
    ) -> Dict[str, any]:
        """两阶段自适应 GEX 曲线扫描 (在零 Gamma 附近加密)

        设计动机:
            默认 calculate_gex_profile 使用 40 步 ±10% 区间, 步长 ≈ 0.5% × spot,
            对 SPX 而言粒度约 27.5pt, 远大于 dealer 对冲精度 (5pt)。
            本方法先粗扫定位翻转区间, 再在翻转区间 ±0.5% 内加密 120 步,
            精度可达 1-2pt, 同时比单次 500 步省 68% 计算量。

        Args:
            option_chain_df: 期权链 DataFrame (含 strike/open_interest/implied_volatility/option_type/days_to_expiry)
            spot_price: 当前标的价格
            coarse_steps: 第一阶段粗扫步数 (默认 40, 沿用现默认)
            fine_steps: 第二阶段精扫步数 (默认 120)
            expand_pct: 翻转区间局部放大比例 (默认 ±0.5%)

        Returns:
            {
                'spot_prices': [float],           # 精扫段价格数组
                'net_gex_values': [float],         # 精扫段 GEX 数组
                'current_spot': float,
                'current_net_gex': float,
                'flip_point': float | None,        # 线性插值精确翻转点
                'flip_zone': (lower, upper) | None,  # 粗扫识别的翻转区间
                'coarse_steps': int,
                'fine_steps': int,
            }

        Examples:
            >>> calc = GEXCalculator()
            >>> profile = calc.calculate_gex_profile_adaptive(df, 5500)
            >>> print(profile['flip_point'])  # 5492.35 (SPX 真实 zero gamma 价位)
        """
        # ── 第一阶段:粗扫 (40 步, ±10%) — 找翻转区间 ──
        coarse = self.calculate_gex_profile(
            option_chain_df, spot_price, symbol=symbol,
            price_range_pct=0.10, num_steps=coarse_steps,
        )

        spot_arr = coarse['spot_prices']
        gex_arr = coarse['net_gex_values']

        # 找第一个符号变化区间
        flip_zone = None
        for i in range(len(gex_arr) - 1):
            if gex_arr[i] * gex_arr[i + 1] < 0:
                flip_zone = (float(spot_arr[i]), float(spot_arr[i + 1]))
                break

        # 无翻转点, 直接返回粗扫结果
        if flip_zone is None:
            return {
                'spot_prices': spot_arr,
                'net_gex_values': gex_arr,
                'current_spot': spot_price,
                'current_net_gex': coarse['current_net_gex'],
                'flip_point': None,
                'flip_zone': None,
                'coarse_steps': coarse_steps,
                'fine_steps': 0,
            }

        p_lo, p_hi = flip_zone

        # ── 第二阶段:精扫 (翻转区间 ±0.5% 内 120 步) ──
        fine_low = p_lo * (1 - expand_pct)
        fine_high = p_hi * (1 + expand_pct)
        # 保证 fine_low < fine_high (极端情况: 翻转区间本身就是 0)
        if fine_high <= fine_low:
            fine_high = p_hi * (1 + expand_pct)
        fine_prices = np.linspace(fine_low, fine_high, fine_steps)
        fine_gex = [
            self.calculate_portfolio_gex_vectorized(option_chain_df, float(p), symbol)['net_gex']
            for p in fine_prices
        ]

        # 在精扫里找翻转点 → 线性插值
        flip_point = None
        for i in range(len(fine_gex) - 1):
            if fine_gex[i] * fine_gex[i + 1] < 0:
                g1, g2 = fine_gex[i], fine_gex[i + 1]
                if g2 != g1:
                    flip_point = float(
                        fine_prices[i] + (-g1) * (fine_prices[i + 1] - fine_prices[i])
                        / (g2 - g1)
                    )
                break

        return {
            'spot_prices': [float(p) for p in fine_prices],
            'net_gex_values': [float(g) for g in fine_gex],
            'current_spot': spot_price,
            'current_net_gex': coarse['current_net_gex'],
            'flip_point': flip_point,
            'flip_zone': flip_zone,
            'coarse_steps': coarse_steps,
            'fine_steps': fine_steps,
        }

    def aggregate_gex_by_expiry(
        self,
        option_chain_df: pd.DataFrame,
        spot_price: float,
        symbol: Optional[str] = None,
    ) -> Dict[str, any]:
        """按到期日分组计算 GEX 时间分布 (V2.0)

        Args:
            option_chain_df: 期权链 DataFrame（须含 expiry 列）
            spot_price: 当前标的价格

        Returns:
            {
                'gex_by_expiry': {expiry_date: net_gex},
                'near_term_gex': float,  # 30天内到期
                'medium_term_gex': float,  # 30-90天
                'long_term_gex': float,  # >90天
            }
        """
        df = option_chain_df.copy()
        df = df[df['open_interest'] > 0]
        if df.empty or 'expiry' not in df.columns:
            return {'gex_by_expiry': {}, 'near_term_gex': 0, 'medium_term_gex': 0, 'long_term_gex': 0}

        unique_expiries = df['expiry'].unique()
        gex_by_expiry = {}

        for expiry in unique_expiries:
            subset = df[df['expiry'] == expiry]
            result = self.calculate_portfolio_gex_vectorized(subset, spot_price, symbol)
            gex_by_expiry[str(expiry)] = result['net_gex']

        # 按到期远近分类
        today = pd.Timestamp.now()
        near_term = 0.0
        medium_term = 0.0
        long_term = 0.0
        for expiry_str, net_gex in gex_by_expiry.items():
            try:
                days = (pd.Timestamp(expiry_str) - today).days
            except Exception:
                days = 60  # 默认中端
            if days <= 30:
                near_term += net_gex
            elif days <= 90:
                medium_term += net_gex
            else:
                long_term += net_gex

        return {
            'gex_by_expiry': gex_by_expiry,
            'near_term_gex': near_term,
            'medium_term_gex': medium_term,
            'long_term_gex': long_term,
        }

    def find_top_walls(
        self,
        gex_by_strike: Dict[float, float],
        top_n: int = 3,
    ) -> Dict[str, List[float]]:
        """识别 Top-N Put Walls 和 Call Walls (V2.0)

        Args:
            gex_by_strike: 按行权价分组的 GEX 字典
            top_n: 返回前 N 个

        Returns:
            {'put_walls': [strike_1, strike_2, ...], 'call_walls': [strike_1, ...]}
        """
        put_strikes = {k: v for k, v in gex_by_strike.items() if v < 0}
        call_strikes = {k: v for k, v in gex_by_strike.items() if v > 0}

        put_walls = sorted(put_strikes, key=lambda k: put_strikes[k])[:top_n]
        call_walls = sorted(call_strikes, key=lambda k: call_strikes[k], reverse=True)[:top_n]

        return {
            'put_walls': put_walls,
            'call_walls': call_walls,
        }

    def calculate_net_gamma_regime(
        self,
        net_gex: float,
        gex_historical: Optional[List[float]] = None,
    ) -> str:
        """基于净 GEX 符号和历史百分位判定市场区间 (V2.0)

        分类:
        - High Positive Gamma: 净 GEX > 0 且处于历史前 20%
        - Positive Gamma: 净 GEX > 0
        - Neutral: 净 GEX ≈ 0
        - Negative Gamma: 净 GEX < 0
        - Deep Negative Gamma: 净 GEX < 0 且处于历史后 10%

        Args:
            net_gex: 当前净 GEX
            gex_historical: 历史净 GEX 列表（用于百分位判定）

        Returns:
            区间状态字符串
        """
        if net_gex > 0:
            if gex_historical and len(gex_historical) >= 20:
                pct = (np.sum(np.array(gex_historical) <= net_gex) / len(gex_historical)) * 100
                if pct >= 80:
                    return "High Positive Gamma"
            return "Positive Gamma"
        elif net_gex < 0:
            if gex_historical and len(gex_historical) >= 20:
                pct = (np.sum(np.array(gex_historical) <= net_gex) / len(gex_historical)) * 100
                if pct <= 10:
                    return "Deep Negative Gamma"
            return "Negative Gamma"
        else:
            return "Neutral"

    @staticmethod
    def _empty_gex_result() -> Dict[str, any]:
        """返回空的 GEX 结果"""
        return {
            'total_gex': 0.0, 'call_gex': 0.0, 'put_gex': 0.0,
            'gex_by_strike': {}, 'net_gex': 0.0,
            'net_gex_calibrated': False,
        }


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
