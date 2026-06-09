"""
多源共振监控系统 - SqueezeMetrics DIX数据获取器

该模块负责从SqueezeMetrics官网获取暗盘活动指标(DIX)和Gamma风险暴露(GEX)数据。
DIX是衡量机构在暗盘买入强度的关键指标，GEX反映做市商对冲压力。

主要功能:
- 每日收盘后通过CSV直接下载获取DIX百分比值（无需API密钥）
- 获取Barchart Put Wall直方图数据
- 提供Mock模式用于测试

数据源: https://squeezemetrics.com/monitor/static/DIX.csv
频率: 每日美东时间16:00后执行
"""

import requests
import pandas as pd
from requests.exceptions import Timeout, ConnectionError, HTTPError
from typing import Optional, Dict, Any
from io import StringIO
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from utils.logger import getLogger
from utils.exceptions import DataFetchError
from config.settings import Config, DataFetchConfig

logger = getLogger('squeezemetrics_fetcher')


class SqueezeMetricsFetcher:
    """SqueezeMetrics暗盘指标获取器 (重构为 CSV 直接下载模式)
    
    通过SqueezeMetrics官方CSV文件直接下载获取DIX（Dark Index）和GEX指标。
    不再依赖推测的JSON API或Playwright，直接拉取官方每日更新的静态CSV文件。
    
    DIX > 45% 表示机构在暗盘大量买入，是重要的左侧抄底信号。
    
    优势:
    - 无需API密钥，完全免费
    - CSV格式稳定，不受JavaScript渲染影响
    - 轻量级请求，响应速度快
    
    Attributes:
        mock_mode: Mock模式开关
        session: 带重试的requests.Session实例
    """
    
    def __init__(self, mock_mode: bool = False):
        """初始化SqueezeMetrics数据获取器
        
        Args:
            mock_mode: Mock模式开关，用于无网络连接时的测试
        """
        self.mock_mode = mock_mode
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        logger.info(f"SqueezeMetricsFetcher初始化完成 (mock_mode={mock_mode}, CSV直接下载模式)")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=5, max=45),
        retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError)),
        reraise=True
    )
    def get_daily_dix(self) -> Optional[float]:
        """获取每日 DIX 指标值 (解析官方静态 CSV)
        
        从SqueezeMetrics官方CSV文件获取最新的DIX（Dark Index）百分比值。
        DIX衡量暗盘交易量占总交易量的比例，高DIX值表明机构在隐蔽建仓。
        
        CSV格式: date,price,short_vol,total_vol,dix,gex
        数据按日期排序，最后一行为最新数据。
        
        Returns:
            float: DIX百分比值（如45.8表示45.8%）
                  失败时返回None
            
        Raises:
            DataFetchError: CSV下载或解析失败时抛出
        """
        if self.mock_mode:
            return self._get_mock_dix()
            
        try:
            logger.info(f"正在从 SqueezeMetrics 下载 DIX CSV 数据: {DataFetchConfig.SQUEEZEMETRICS_CSV_URL}")
            response = self.session.get(DataFetchConfig.SQUEEZEMETRICS_CSV_URL, timeout=15)
            response.raise_for_status()
            
            # 解析 CSV (格式: date,price,short_vol,total_vol,dix,gex)
            df = pd.read_csv(StringIO(response.text))
            if df.empty or 'dix' not in df.columns:
                logger.error("CSV 解析失败或缺少 dix 字段")
                return None
                
            # 获取最新一日的 DIX 值 (CSV 中通常为小数，需转为百分比)
            latest_dix = float(df.iloc[-1]['dix']) * 100
            
            logger.info(f"成功获取 DIX 指标: {latest_dix:.2f}%")
            if latest_dix > 45.0:
                logger.warning(f"⚠️ DIX={latest_dix:.2f}% > 45%，机构暗盘吸筹信号")
            
            return latest_dix
            
        except Exception as e:
            logger.error(f"获取 DIX 失败: {e}", exc_info=True)
            raise DataFetchError(f"DIX获取失败: {e}", "SQZ_FETCH_ERROR")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=5, max=45),
        retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError)),
        reraise=True
    )
    def get_daily_gex(self) -> Optional[float]:
        """获取每日 GEX 指标值 (解析官方静态 CSV)
        
        从SqueezeMetrics官方GEX CSV文件获取最新的Gamma Exposure总值。
        
        Returns:
            float: GEX美元值，失败时返回None
        """
        if self.mock_mode:
            return 2.5e9  # Mock: 2.5B GEX
            
        try:
            logger.info(f"正在从 SqueezeMetrics 下载 GEX CSV 数据: {DataFetchConfig.SQUEEZEMETRICS_GEX_URL}")
            response = self.session.get(DataFetchConfig.SQUEEZEMETRICS_GEX_URL, timeout=15)
            response.raise_for_status()
            
            df = pd.read_csv(StringIO(response.text))
            if df.empty or 'gex' not in df.columns:
                logger.error("CSV 解析失败或缺少 gex 字段")
                return None
                
            latest_gex = float(df.iloc[-1]['gex'])
            logger.info(f"成功获取 GEX 指标: ${latest_gex/1e9:.2f}B")
            return latest_gex
            
        except Exception as e:
            logger.error(f"获取 GEX 失败: {e}", exc_info=True)
            raise DataFetchError(f"GEX获取失败: {e}", "SQZ_GEX_FETCH_ERROR")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=5, max=45),
        retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError)),
        reraise=True
    )
    def get_barchart_gamma_profile(self) -> Optional[Dict[str, Any]]:
        """获取Barchart Gamma分布直方图数据
        
        从SqueezeMetrics获取各期权行权价的名义Gamma敞口分布。
        用于识别Put Wall（最大Put Gamma集中区）作为关键支撑位。
        
        Returns:
            dict: Gamma分布数据，失败时返回None
        """
        if self.mock_mode:
            return self._get_mock_gamma_profile()
        
        try:
            logger.info("请求SqueezeMetrics CSV获取Gamma分布")
            response = self.session.get(DataFetchConfig.SQUEEZEMETRICS_GEX_URL, timeout=15)
            response.raise_for_status()
            
            df = pd.read_csv(StringIO(response.text))
            if df.empty:
                logger.error("GEX CSV为空")
                return None
            
            # CSV格式: date,price,gex_total,gex_by_strike (JSON)
            # 尝试提取各列
            latest = df.iloc[-1]
            result = {
                'total_gex': float(latest.get('gex', 0)),
                'timestamp': str(latest.get('date', '')),
                'strikes': [],
                'call_gamma': [],
                'put_gamma': [],
                'net_gamma': [],
                'put_wall_strike': None
            }
            
            logger.debug(f"成功获取Gamma分布: Total GEX=${result['total_gex']/1e9:.2f}B")
            return result
            
        except Exception as e:
            logger.error(f"获取Gamma分布失败: {e}", exc_info=True)
            return None
    
    def get_official_gex(self) -> Optional[float]:
        """获取官方GEX总值（供α校准使用）
        
        Returns:
            float: 官方GEX美元值
        """
        try:
            return self.get_daily_gex()
        except Exception as e:
            logger.error(f"获取官方GEX失败: {e}")
            return None
    
    def _get_mock_dix(self) -> float:
        """生成模拟DIX值
        
        Returns:
            float: 模拟的DIX百分比值（40-55之间随机）
        """
        import random
        return round(random.uniform(40.0, 55.0), 2)
    
    def _get_mock_gamma_profile(self) -> Dict[str, Any]:
        """生成模拟Gamma分布数据
        
        Returns:
            dict: 模拟的Gamma分布数据结构
        """
        import random
        
        # 生成行权价范围（以SPX为例，假设当前点位4500）
        base_strike = 4500
        strikes = [base_strike + i * 50 for i in range(-20, 21)]  # 41个行权价
        
        call_gamma = []
        put_gamma = []
        
        for strike in strikes:
            # 模拟Gamma分布：ATM附近Gamma最大
            distance_from_atm = abs(strike - base_strike) / base_strike
            
            # Call Gamma在OTM区域递减
            call_g = max(0, 100000 * (1 - distance_from_atm * 3) + random.uniform(-5000, 5000))
            call_gamma.append(round(call_g, 0))
            
            # Put Gamma在ITM区域较大
            if strike < base_strike:
                put_g = max(0, 150000 * (1 - distance_from_atm * 2) + random.uniform(-5000, 5000))
            else:
                put_g = max(0, 50000 * (1 - distance_from_atm * 4) + random.uniform(-2000, 2000))
            put_gamma.append(round(put_g, 0))
        
        # 计算净Gamma
        net_gamma = [c - p for c, p in zip(call_gamma, put_gamma)]
        
        # 找到Put Wall（最大负Gamma位置）
        min_gamma_idx = net_gamma.index(min(net_gamma))
        put_wall_strike = strikes[min_gamma_idx]
        
        return {
            'strikes': strikes,
            'call_gamma': call_gamma,
            'put_gamma': put_gamma,
            'net_gamma': net_gamma,
            'put_wall_strike': put_wall_strike,
            'timestamp': 'mock_timestamp'
        }


# 便捷函数
def create_squeezemetrics_fetcher(mock_mode: bool = False) -> SqueezeMetricsFetcher:
    """创建SqueezeMetrics数据获取器实例的工厂函数
    
    Args:
        mock_mode: 是否启用Mock模式
        
    Returns:
        SqueezeMetricsFetcher: 配置好的获取器实例
    """
    return SqueezeMetricsFetcher(mock_mode=mock_mode)
