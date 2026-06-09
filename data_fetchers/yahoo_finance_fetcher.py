"""
多源共振监控系统 - Yahoo Finance VIX期货数据获取器

该模块负责从Yahoo Finance API获取VIX现货和期货价格数据，
用于计算波动率期限结构和分析市场恐慌程度。

主要功能:
- 获取VIX现货指数价格 (^VIX)
- 获取VIX近月和次月期货价格 (VX=F, VX2=F)
- 计算VIX期限结构比率 (VX1/VX2)
- 判断Contango/Backwardation市场状态

API端点: https://query1.finance.yahoo.com/v8/finance/chart/{symbol}
"""

import requests
from requests.exceptions import Timeout, ConnectionError, HTTPError
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from utils.logger import getLogger
from utils.exceptions import DataFetchError
from config.settings import Config

logger = getLogger('yahoo_finance_fetcher')


class YahooFinanceFetcher:
    """Yahoo Finance VIX期货数据获取器
    
    通过Yahoo Finance公共API获取VIX波动率指数及其期货合约价格。
    主要用于监控市场恐慌情绪和期限结构变化。
    
    Attributes:
        base_url: Yahoo Finance API基础URL
        timeout: 请求超时时间(秒)
        mock_mode: Mock模式开关
    """
    
    def __init__(self, mock_mode: bool = False):
        """初始化Yahoo Finance数据获取器
        
        Args:
            mock_mode: Mock模式开关，用于无网络连接时的测试
        """
        self.base_url = "https://query1.finance.yahoo.com/v8/finance/chart"
        self.timeout = Config.REQUEST_TIMEOUT
        self.mock_mode = mock_mode
        
        logger.info(f"YahooFinanceFetcher初始化完成 (mock_mode={mock_mode})")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError)),
        reraise=True
    )
    def get_vix_spot(self) -> Optional[float]:
        """获取VIX现货指数价格
        
        从Yahoo Finance获取CBOE波动率指数(^VIX)的实时价格。
        VIX是衡量S&P 500指数未来30天预期波动率的指标。
        
        Returns:
            float: VIX现货价格，失败时返回None
            
        Raises:
            DataFetchError: API请求失败时抛出（经重试后仍失败）
            
        Examples:
            >>> fetcher = YahooFinanceFetcher()
            >>> vix_price = fetcher.get_vix_spot()
            >>> if vix_price:
            ...     print(f"当前VIX指数: {vix_price:.2f}")
        """
        if self.mock_mode:
            logger.warning("Mock模式: 返回模拟VIX现货价格")
            return self._get_mock_vix_spot()
        
        symbol = "^VIX"
        url = f"{self.base_url}/{symbol}"
        params = {
            'range': '1d',
            'interval': '1m'
        }
        
        try:
            logger.info(f"请求Yahoo Finance API: symbol={symbol}")
            response = requests.get(
                url,
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            data = response.json()
            
            # 解析价格数据
            result = data.get('chart', {}).get('result', [])
            if not result:
                logger.error("API响应中缺少结果数据")
                return None
            
            meta = result[0].get('meta', {})
            current_price = meta.get('regularMarketPrice')
            
            if current_price is None:
                logger.error("无法获取VIX现货价格")
                return None
            
            price = float(current_price)
            logger.debug(f"成功获取VIX现货价格: {price:.2f}")
            return price
            
        except Timeout as e:
            logger.error(f"Request timeout for VIX spot: {e}")
            return None
        except ConnectionError as e:
            logger.error(f"Connection error for VIX spot: {e}")
            return None
        except HTTPError as e:
            logger.error(f"HTTP error {e.response.status_code} for VIX spot: {e}")
            return None
        except ValueError as e:
            logger.error(f"JSON decode error for VIX spot: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching VIX spot price: {e}", exc_info=True)
            return None
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError)),
        reraise=True
    )
    def get_vix_futures(self, contract: str = 'VX1') -> Optional[float]:
        """获取VIX期货合约价格
        
        从Yahoo Finance获取指定月份的VIX期货价格。
        
        Args:
            contract: 期货合约标识
                - 'VX1': 近月期货 (VX=F)
                - 'VX2': 次月期货 (需确认真实符号，可能为VXM=F或VXN=F)
                
        Returns:
            float: 期货价格，失败时返回None
            
        Raises:
            DataFetchError: API请求失败时抛出
            
        Examples:
            >>> fetcher = YahooFinanceFetcher()
            >>> vx1_price = fetcher.get_vix_futures('VX1')
            >>> vx2_price = fetcher.get_vix_futures('VX2')
        """
        if self.mock_mode:
            logger.warning(f"Mock模式: 返回模拟{contract}期货价格")
            return self._get_mock_vix_futures(contract)
        
        # 映射合约符号到Yahoo Finance ticker
        contract_map = {
            'VX1': 'VX=F',   # 近月期货
            'VX2': 'VXM=F',  # 次月期货 (TODO: 需通过浏览器F12确认准确符号)
        }
        
        symbol = contract_map.get(contract)
        if not symbol:
            logger.error(f"未知的期货合约: {contract}")
            raise ValueError(f"不支持的期货合约: {contract}，支持的合约: {list(contract_map.keys())}")
        
        url = f"{self.base_url}/{symbol}"
        params = {
            'range': '1d',
            'interval': '1m'
        }
        
        try:
            logger.info(f"请求Yahoo Finance API: symbol={symbol} ({contract})")
            response = requests.get(
                url,
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            data = response.json()
            
            # 解析价格数据
            result = data.get('chart', {}).get('result', [])
            if not result:
                logger.error(f"API响应中缺少{contract}期货结果数据")
                return None
            
            meta = result[0].get('meta', {})
            current_price = meta.get('regularMarketPrice')
            
            if current_price is None:
                logger.error(f"无法获取{contract}期货价格")
                return None
            
            price = float(current_price)
            logger.debug(f"成功获取{contract}期货价格: {price:.2f}")
            return price
            
        except Timeout as e:
            logger.error(f"Request timeout for {contract}: {e}")
            return None
        except ConnectionError as e:
            logger.error(f"Connection error for {contract}: {e}")
            return None
        except HTTPError as e:
            logger.error(f"HTTP error {e.response.status_code} for {contract}: {e}")
            return None
        except ValueError as e:
            logger.error(f"JSON decode error for {contract}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching {contract} futures price: {e}", exc_info=True)
            return None
    
    def calculate_term_structure_ratio(self) -> Optional[float]:
        """计算VIX期限结构比率 (VX1/VX2)
        
        计算近月期货与次月期货的价格比率，用于判断市场处于
        Contango（远期溢价）还是Backwardation（近期溢价）状态。
        
        Returns:
            float: 期限结构比率
                - ratio > 1.0: Backwardation（近期恐慌）
                - ratio < 1.0: Contango（正常状态）
                - ratio > 1.15: 极度恐慌信号
            失败时返回None
            
        Examples:
            >>> fetcher = YahooFinanceFetcher()
            >>> ratio = fetcher.calculate_term_structure_ratio()
            >>> if ratio:
            ...     state = "Backwardation" if ratio > 1.0 else "Contango"
            ...     print(f"VIX期限结构: {ratio:.3f} ({state})")
        """
        try:
            vx1_price = self.get_vix_futures('VX1')
            vx2_price = self.get_vix_futures('VX2')
            
            if vx1_price is None or vx2_price is None:
                logger.error("无法获取期货价格，无法计算期限结构比率")
                return None
            
            if vx2_price == 0:
                logger.error("VX2价格为0，避免除零错误")
                return None
            
            ratio = vx1_price / vx2_price
            logger.info(f"VIX期限结构比率: {ratio:.4f} (VX1={vx1_price:.2f}, VX2={vx2_price:.2f})")
            
            # 记录市场状态
            if ratio > 1.15:
                logger.warning(f"⚠️ 极度Backwardation状态 (ratio={ratio:.3f} > 1.15)，市场恐慌严重")
            elif ratio > 1.0:
                logger.info(f"Backwardation状态 (ratio={ratio:.3f} > 1.0)")
            else:
                logger.info(f"Contango状态 (ratio={ratio:.3f} < 1.0)")
            
            return ratio
            
        except Exception as e:
            logger.error(f"计算期限结构比率失败: {str(e)}", exc_info=True)
            return None
    
    def _get_mock_vix_spot(self) -> float:
        """生成模拟VIX现货价格
        
        Returns:
            float: 模拟的VIX价格（15-30范围内随机）
        """
        import random
        return round(random.uniform(15.0, 30.0), 2)
    
    def _get_mock_vix_futures(self, contract: str) -> float:
        """生成模拟VIX期货价格
        
        Args:
            contract: 期货合约标识 ('VX1' 或 'VX2')
            
        Returns:
            float: 模拟的期货价格
        """
        import random
        
        base_price = random.uniform(16.0, 28.0)
        
        # VX2通常比VX1略高（Contango常态）
        if contract == 'VX2':
            base_price += random.uniform(0.5, 2.0)
        
        return round(base_price, 2)


# 便捷函数
def create_yahoo_finance_fetcher(mock_mode: bool = False) -> YahooFinanceFetcher:
    """创建Yahoo Finance数据获取器实例的工厂函数
    
    Args:
        mock_mode: 是否启用Mock模式
        
    Returns:
        YahooFinanceFetcher: 配置好的获取器实例
    """
    return YahooFinanceFetcher(mock_mode=mock_mode)
