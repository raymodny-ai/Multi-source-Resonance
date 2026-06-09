"""
多源共振监控系统 - DBMF ETF动量监控获取器

该模块负责从Yahoo Finance获取DBMF ETF（Managed Futures策略影子基金）的实时价格，
用于监检测试量化趋势基金的日内反转信号。

主要功能:
- 获取DBMF实时价格
- 计算5日移动平均线(MA5)
- 检测日内探底后收盘价站上MA5且涨幅>2%的反转信号

DBMF逻辑:
- DBMF是CTA趋势跟踪策略的代表性ETF
- 当市场恐慌下跌时，DBMF通常会跟随下跌
- 若DBMF日内探底后强劲反弹并收复MA5，表明量化空头动能枯竭
"""

import requests
from requests.exceptions import Timeout, ConnectionError, HTTPError
import numpy as np
from typing import Optional, List
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from utils.logger import getLogger
from utils.exceptions import DataFetchError
from config.settings import Config

logger = getLogger('dbmf_fetcher')


class DBMFFetcher:
    """DBMF ETF动量监控获取器
    
    通过Yahoo Finance API获取DBMF ETF的实时价格和历史数据，
    用于判断量化趋势基金是否出现底部反转信号。
    
    Attributes:
        base_url: Yahoo Finance API基础URL
        timeout: 请求超时时间(秒)
        mock_mode: Mock模式开关
    """
    
    def __init__(self, mock_mode: bool = False):
        """初始化DBMF数据获取器
        
        Args:
            mock_mode: Mock模式开关，用于无网络连接时的测试
        """
        self.base_url = "https://query1.finance.yahoo.com/v8/finance/chart"
        self.timeout = Config.REQUEST_TIMEOUT
        self.mock_mode = mock_mode
        
        logger.info(f"DBMFFetcher初始化完成 (mock_mode={mock_mode})")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError)),
        reraise=True
    )
    def get_dbmf_intraday_price(self) -> Optional[float]:
        """获取DBMF ETF实时价格
        
        从Yahoo Finance获取DBMF ETF的最新交易价格。
        
        Returns:
            float: DBMF实时价格，失败时返回None
            
        Raises:
            DataFetchError: API请求失败时抛出
            
        Examples:
            >>> fetcher = DBMFFetcher()
            >>> price = fetcher.get_dbmf_intraday_price()
            >>> if price:
            ...     print(f"DBMF当前价格: ${price:.2f}")
        """
        if self.mock_mode:
            logger.warning("Mock模式: 返回模拟DBMF价格")
            return self._get_mock_dbmf_price()
        
        symbol = "DBMF"
        url = f"{self.base_url}/{symbol}"
        params = {
            'range': '1d',
            'interval': '1m'
        }
        
        try:
            logger.info(f"请求Yahoo Finance API获取DBMF价格: symbol={symbol}")
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
                logger.error("无法获取DBMF价格")
                return None
            
            price = float(current_price)
            logger.debug(f"成功获取DBMF价格: ${price:.2f}")
            return price
            
        except Timeout as e:
            logger.error(f"Request timeout for DBMF price: {e}")
            return None
        except ConnectionError as e:
            logger.error(f"Connection error for DBMF price: {e}")
            return None
        except HTTPError as e:
            logger.error(f"HTTP error {e.response.status_code} for DBMF price: {e}")
            return None
        except ValueError as e:
            logger.error(f"JSON decode error for DBMF price: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching DBMF price: {e}", exc_info=True)
            return None
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError)),
        reraise=True
    )
    def get_dbmf_historical_prices(self, period: str = '5d') -> Optional[List[float]]:
        """获取DBMF历史价格序列
        
        从Yahoo Finance获取指定时间段的历史收盘价，用于计算移动平均线。
        
        Args:
            period: 时间周期，如'5d'、'1mo'、'3mo'
            
        Returns:
            list: 收盘价列表（按时间顺序），失败时返回None
            
        Raises:
            DataFetchError: API请求失败时抛出
            
        Examples:
            >>> fetcher = DBMFFetcher()
            >>> prices = fetcher.get_dbmf_historical_prices('5d')
            >>> if prices:
            ...     print(f"获取到{len(prices)}个价格数据点")
        """
        if self.mock_mode:
            logger.warning(f"Mock模式: 返回模拟DBMF历史价格 ({period})")
            return self._get_mock_dbmf_historical_prices(period)
        
        symbol = "DBMF"
        url = f"{self.base_url}/{symbol}"
        params = {
            'range': period,
            'interval': '1d'  # 日线数据
        }
        
        try:
            logger.info(f"请求Yahoo Finance API获取DBMF历史价格: period={period}")
            response = requests.get(
                url,
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            data = response.json()
            
            # 解析历史数据
            result = data.get('chart', {}).get('result', [])
            if not result:
                logger.error("API响应中缺少结果数据")
                return None
            
            quotes = result[0].get('indicators', {}).get('quote', [{}])[0]
            close_prices = quotes.get('close', [])
            
            # 过滤None值
            valid_prices = [float(p) for p in close_prices if p is not None]
            
            if not valid_prices:
                logger.error("没有有效的价格数据")
                return None
            
            logger.debug(f"成功获取DBMF历史价格: {len(valid_prices)}个数据点")
            return valid_prices
            
        except Timeout as e:
            logger.error(f"Request timeout for DBMF history: {e}")
            return None
        except ConnectionError as e:
            logger.error(f"Connection error for DBMF history: {e}")
            return None
        except HTTPError as e:
            logger.error(f"HTTP error {e.response.status_code} for DBMF history: {e}")
            return None
        except ValueError as e:
            logger.error(f"JSON decode error for DBMF history: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching DBMF history: {e}", exc_info=True)
            return None
    
    def check_ma5_recovery(
        self, 
        current_price: float, 
        historical_prices: List[float]
    ) -> Optional[bool]:
        """检测DBMF是否收复5日均线且涨幅>2%
        
        判断DBMF是否在日内探底后强劲反弹，收盘价站上MA5且涨幅超过2%。
        这是量化空头动能枯竭的重要信号。
        
        Args:
            current_price: 当前价格（或当日收盘价）
            historical_prices: 历史价格列表（至少包含最近5个交易日）
                               最后一个元素应为昨日收盘价
            
        Returns:
            bool: True表示满足条件（收复MA5且涨幅>2%）
                 False表示不满足
                 None表示数据不足或计算失败
            
        Examples:
            >>> fetcher = DBMFFetcher()
            >>> prices = fetcher.get_dbmf_historical_prices('5d')
            >>> current = fetcher.get_dbmf_intraday_price()
            >>> if current and prices:
            ...     recovery = fetcher.check_ma5_recovery(current, prices)
            ...     if recovery:
            ...         print("✅ DBMF收复MA5且涨幅>2%，量化空头动能枯竭")
        """
        try:
            if not historical_prices or len(historical_prices) < 5:
                logger.error(f"历史价格数据不足，需要至少5个数据点，当前{len(historical_prices) if historical_prices else 0}个")
                return None
            
            # 取最近5个交易日的收盘价
            last_5_prices = historical_prices[-5:]
            
            # 计算5日移动平均线
            ma5 = np.mean(last_5_prices)
            
            # 计算昨日收盘价（用于计算涨幅）
            yesterday_close = last_5_prices[-1]
            
            if yesterday_close == 0:
                logger.error("昨日收盘价为0，避免除零错误")
                return None
            
            # 计算涨幅
            gain_percent = ((current_price - yesterday_close) / yesterday_close) * 100
            
            # 判断条件：站上MA5且涨幅>2%
            above_ma5 = current_price > ma5
            significant_gain = gain_percent > 2.0
            
            recovery = above_ma5 and significant_gain
            
            logger.info(
                f"DBMF MA5检测: 当前价=${current_price:.2f}, MA5=${ma5:.2f}, "
                f"涨幅={gain_percent:.2f}%, 站上MA5={above_ma5}, 涨幅>2%={significant_gain}, "
                f"结果={'✅ 收复' if recovery else '❌ 未收复'}"
            )
            
            if recovery:
                logger.warning("⚠️ DBMF收复MA5且涨幅>2%，量化空头动能可能已枯竭")
            
            return recovery
            
        except Exception as e:
            logger.error(f"MA5恢复检测失败: {str(e)}", exc_info=True)
            return None
    
    def _get_mock_dbmf_price(self) -> float:
        """生成模拟DBMF价格
        
        Returns:
            float: 模拟的DBMF价格（25-35美元之间）
        """
        import random
        return round(random.uniform(25.0, 35.0), 2)
    
    def _get_mock_dbmf_historical_prices(self, period: str) -> List[float]:
        """生成模拟DBMF历史价格序列
        
        Args:
            period: 时间周期
            
        Returns:
            list: 模拟的价格序列
        """
        import random
        
        # 根据周期确定数据点数量
        if 'd' in period:
            days = int(period.replace('d', ''))
        elif 'mo' in period:
            days = int(period.replace('mo', '')) * 30
        else:
            days = 5
        
        # 生成带有随机波动的价格序列
        base_price = 30.0
        prices = []
        
        for i in range(days):
            # 模拟价格波动（±2%）
            change = random.uniform(-0.02, 0.02)
            base_price *= (1 + change)
            prices.append(round(base_price, 2))
        
        return prices


# 便捷函数
def create_dbmf_fetcher(mock_mode: bool = False) -> DBMFFetcher:
    """创建DBMF数据获取器实例的工厂函数
    
    Args:
        mock_mode: 是否启用Mock模式
        
    Returns:
        DBMFFetcher: 配置好的获取器实例
    """
    return DBMFFetcher(mock_mode=mock_mode)
