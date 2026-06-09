"""
多源共振监控系统 - SqueezeMetrics DIX数据获取器

该模块负责从SqueezeMetrics API获取暗盘活动指标(DIX)和Gamma风险暴露(GEX)数据。
DIX是衡量机构在暗盘买入强度的关键指标，GEX反映做市商对冲压力。

主要功能:
- 每日收盘后获取DIX百分比值
- 获取Barchart Put Wall直方图数据
- 提供Mock模式用于测试

API文档: https://squeezemetrics.com/monitor
频率: 每日美东时间16:00后执行
"""

import requests
from requests.exceptions import Timeout, ConnectionError, HTTPError
from typing import Optional, Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from utils.logger import getLogger
from utils.exceptions import DataFetchError
from config.settings import Config

logger = getLogger('squeezemetrics_fetcher')


class SqueezeMetricsFetcher:
    """SqueezeMetrics暗盘指标获取器
    
    通过SqueezeMetrics API获取官方DIX（Dark Index）和GEX（Gamma Exposure）指标。
    DIX > 45% 表示机构在暗盘大量买入，是重要的左侧抄底信号。
    
    Attributes:
        api_key: SqueezeMetrics API密钥
        base_url: API基础URL
        mock_mode: Mock模式开关
    """
    
    def __init__(self, api_key: Optional[str] = None, mock_mode: bool = False):
        """初始化SqueezeMetrics数据获取器
        
        Args:
            api_key: SqueezeMetrics API密钥，默认从Config读取
            mock_mode: Mock模式开关，用于无API密钥时的测试
        """
        self.api_key = api_key or Config.SQUEEZEMETRICS_API_KEY
        self.base_url = Config.SQUEEZEMETRICS_BASE_URL
        self.mock_mode = mock_mode
        
        logger.info(f"SqueezeMetricsFetcher初始化完成 (mock_mode={mock_mode})")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=5, max=45),
        retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError)),
        reraise=True
    )
    def get_daily_dix(self) -> Optional[float]:
        """获取每日DIX指标值
        
        从SqueezeMetrics API获取最新的DIX（Dark Index）百分比值。
        DIX衡量暗盘交易量占总交易量的比例，高DIX值表明机构在隐蔽建仓。
        
        Returns:
            float: DIX百分比值（如45.8表示45.8%）
                  失败时返回None
            
        Raises:
            DataFetchError: API请求失败时抛出
            
        Examples:
            >>> fetcher = SqueezeMetricsFetcher()
            >>> dix = fetcher.get_daily_dix()
            >>> if dix is not None:
            ...     print(f"当前DIX: {dix:.1f}%")
            ...     if dix > 45.0:
            ...         print("⚠️ DIX超过阈值，机构暗盘吸筹信号触发")
        """
        if self.mock_mode:
            logger.warning("Mock模式: 返回模拟DIX值")
            return self._get_mock_dix()
        
        # TODO: 需通过实际API文档确认准确的端点和参数
        # 以下为推测的API端点，需要根据实际情况调整
        url = f"{self.base_url}/monitor/dix"
        params = {
            'key': self.api_key,
            'format': 'json'
        }
        
        try:
            logger.info("请求SqueezeMetrics API获取DIX指标")
            response = requests.get(
                url,
                params=params,
                timeout=Config.REQUEST_TIMEOUT
            )
            response.raise_for_status()
            
            data = response.json()
            
            # 解析DIX值（具体字段名需根据实际API响应调整）
            dix_value = data.get('dix') or data.get('DIX') or data.get('value')
            
            if dix_value is None:
                logger.error("API响应中缺少DIX字段")
                logger.debug(f"完整响应: {data}")
                return None
            
            dix_float = float(dix_value)
            logger.debug(f"成功获取DIX指标: {dix_float:.2f}%")
            
            # 记录阈值状态
            if dix_float > 45.0:
                logger.warning(f"⚠️ DIX={dix_float:.2f}% 超过阈值45%，机构暗盘吸筹信号")
            
            return dix_float
            
        except Timeout as e:
            logger.error(f"Request timeout for DIX: {e}")
            return None
        except ConnectionError as e:
            logger.error(f"Connection error for DIX: {e}")
            return None
        except HTTPError as e:
            logger.error(f"HTTP error {e.response.status_code} for DIX: {e}")
            return None
        except ValueError as e:
            logger.error(f"JSON decode error for DIX: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching DIX: {e}", exc_info=True)
            return None
    
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
            dict: Gamma分布数据，包含以下字段:
                - 'strikes': 行权价列表
                - 'call_gamma': 各strike的Call Gamma值列表
                - 'put_gamma': 各strike的Put Gamma值列表
                - 'net_gamma': 净Gamma值列表
                - 'put_wall_strike': Put Wall所在行权价
            失败时返回None
            
        Raises:
            DataFetchError: API请求失败时抛出
            
        Examples:
            >>> fetcher = SqueezeMetricsFetcher()
            >>> gamma_data = fetcher.get_barchart_gamma_profile()
            >>> if gamma_data:
            ...     print(f"Put Wall位于: {gamma_data['put_wall_strike']}")
            ...     print(f"总Gamma敞口: ${sum(gamma_data['net_gamma']):,.0f}")
        """
        if self.mock_mode:
            logger.warning("Mock模式: 返回模拟Gamma分布数据")
            return self._get_mock_gamma_profile()
        
        # TODO: 需通过实际API文档确认准确的端点和参数
        url = f"{self.base_url}/monitor/gex"
        params = {
            'key': self.api_key,
            'symbol': 'SPX',  # 默认获取S&P 500指数
            'format': 'json'
        }
        
        try:
            logger.info("请求SqueezeMetrics API获取Gamma分布")
            response = requests.get(
                url,
                params=params,
                timeout=Config.REQUEST_TIMEOUT
            )
            response.raise_for_status()
            
            data = response.json()
            
            # 解析Gamma分布数据（具体字段名需根据实际API响应调整）
            strikes = data.get('strikes', [])
            call_gamma = data.get('call_gamma', [])
            put_gamma = data.get('put_gamma', [])
            
            if not strikes or not call_gamma or not put_gamma:
                logger.error("API响应中缺少Gamma分布字段")
                logger.debug(f"完整响应: {data}")
                return None
            
            # 计算净Gamma
            net_gamma = [c - p for c, p in zip(call_gamma, put_gamma)]
            
            # 识别Put Wall（最大负Gamma的行权价）
            min_gamma_idx = net_gamma.index(min(net_gamma))
            put_wall_strike = strikes[min_gamma_idx]
            
            result = {
                'strikes': strikes,
                'call_gamma': call_gamma,
                'put_gamma': put_gamma,
                'net_gamma': net_gamma,
                'put_wall_strike': put_wall_strike,
                'timestamp': data.get('timestamp', '')
            }
            
            logger.debug(f"成功获取Gamma分布: {len(strikes)}个行权价, Put Wall={put_wall_strike}")
            return result
            
        except Timeout as e:
            logger.error(f"Request timeout for Gamma profile: {e}")
            return None
        except ConnectionError as e:
            logger.error(f"Connection error for Gamma profile: {e}")
            return None
        except HTTPError as e:
            logger.error(f"HTTP error {e.response.status_code} for Gamma profile: {e}")
            return None
        except ValueError as e:
            logger.error(f"JSON decode error for Gamma profile: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching Gamma profile: {e}", exc_info=True)
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
def create_squeezemetrics_fetcher(api_key: Optional[str] = None, mock_mode: bool = False) -> SqueezeMetricsFetcher:
    """创建SqueezeMetrics数据获取器实例的工厂函数
    
    Args:
        api_key: SqueezeMetrics API密钥
        mock_mode: 是否启用Mock模式
        
    Returns:
        SqueezeMetricsFetcher: 配置好的获取器实例
    """
    return SqueezeMetricsFetcher(api_key=api_key, mock_mode=mock_mode)
