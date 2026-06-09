"""
多源共振监控系统 - CCXT加密数据获取器

该模块负责通过CCXT库直连加密货币交易所（Binance、OKX），
获取永续合约资金费率、持仓量等关键衍生品数据。

主要功能:
- 获取BTC/USDT永续合约资金费率
- 获取全网持仓量(OI)及其变化率
- 计算1小时OI变化率用于判断去杠杆进度
- 支持多交易所数据聚合

技术栈:
- ccxt: 统一加密货币交易所API接口
- 频率: 每5分钟调用一次
"""

import ccxt
from typing import Optional, Dict, Any, List
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from utils.logger import getLogger
from utils.exceptions import DataFetchError
from config.settings import Config

logger = getLogger('ccxt_fetcher')


class CCXTFetcher:
    """CCXT加密数据获取器
    
    通过CCXT库连接Binance和OKX交易所，获取加密货币衍生品市场数据。
    主要用于监控加密市场的杠杆清算状态和资金流向。
    
    Attributes:
        binance: Binance交易所实例
        okx: OKX交易所实例
        mock_mode: Mock模式开关
    """
    
    def __init__(self, mock_mode: bool = False):
        """初始化CCXT数据获取器
        
        Args:
            mock_mode: Mock模式开关，用于无网络连接时的测试
        """
        self.mock_mode = mock_mode
        
        # 初始化交易所实例
        try:
            self.binance = ccxt.binance({
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'future',  # 默认使用永续合约
                }
            })
            
            self.okx = ccxt.okx({
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'swap',  # OKX的永续合约类型
                }
            })
            
            logger.info("CCXTFetcher初始化完成 (Binance + OKX)")
            
        except Exception as e:
            logger.error(f"CCXT初始化失败: {str(e)}")
            self.binance = None
            self.okx = None
        
        logger.info(f"CCXTFetcher初始化完成 (mock_mode={mock_mode})")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception_type((Exception,)),
        reraise=True
    )
    def get_funding_rate(self, symbol: str = 'BTC/USDT') -> Optional[float]:
        """获取永续合约资金费率
        
        从交易所获取指定交易对的最新资金费率。
        负费率表示空头付费给多头（看跌情绪），正费率反之。
        
        Args:
            symbol: 交易对符号，如'BTC/USDT'、'ETH/USDT'
            
        Returns:
            float: 资金费率（小数形式，如-0.0001表示-0.01%）
                  失败时返回None
            
        Raises:
            DataFetchError: API请求失败时抛出
            
        Examples:
            >>> fetcher = CCXTFetcher()
            >>> rate = fetcher.get_funding_rate('BTC/USDT')
            >>> if rate is not None:
            ...     print(f"资金费率: {rate * 100:.4f}%")
            ...     if rate < -0.0001:
            ...         print("检测到负费率，市场看跌情绪浓厚")
        """
        if self.mock_mode:
            logger.warning(f"Mock模式: 返回模拟{symbol}资金费率")
            return self._get_mock_funding_rate(symbol)
        
        try:
            logger.info(f"请求资金费率: symbol={symbol}")
            
            # 优先从Binance获取
            if self.binance:
                try:
                    funding_info = self.binance.fapiPrivateGetFundingRate({
                        'symbol': symbol.replace('/', '')
                    })
                    
                    if funding_info and len(funding_info) > 0:
                        latest = funding_info[-1]
                        rate = float(latest.get('fundingRate', 0))
                        logger.debug(f"成功获取{symbol}资金费率 (Binance): {rate * 100:.4f}%")
                        return rate
                except Exception as e:
                    logger.warning(f"Binance获取资金费率失败: {str(e)}，尝试OKX")
            
            # 降级到OKX
            if self.okx:
                try:
                    # OKX需要加载市场信息
                    self.okx.load_markets()
                    
                    # 获取资金费率历史
                    funding_history = self.okx.fetch_funding_rate(symbol)
                    rate = float(funding_history.get('fundingRate', 0))
                    logger.debug(f"成功获取{symbol}资金费率 (OKX): {rate * 100:.4f}%")
                    return rate
                except Exception as e:
                    logger.warning(f"OKX获取资金费率失败: {str(e)}")
            
            logger.error("所有交易所均无法获取资金费率")
            return None
            
        except Exception as e:
            logger.error(f"Unexpected error fetching {symbol} funding rate: {e}", exc_info=True)
            return None
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception_type((Exception,)),
        reraise=True
    )
    def get_open_interest(self, symbol: str = 'BTC/USDT') -> Optional[Dict[str, Any]]:
        """获取持仓量(OI)数据
        
        从交易所获取指定交易对的当前持仓量。
        OI是衡量市场参与度和潜在清算风险的关键指标。
        
        Args:
            symbol: 交易对符号，如'BTC/USDT'
            
        Returns:
            dict: 包含以下字段:
                - 'oi': 持仓量数值（以基础货币计）
                - 'timestamp': 数据时间戳 (datetime对象)
            失败时返回None
            
        Raises:
            DataFetchError: API请求失败时抛出
            
        Examples:
            >>> fetcher = CCXTFetcher()
            >>> oi_data = fetcher.get_open_interest('BTC/USDT')
            >>> if oi_data:
            ...     print(f"持仓量: {oi_data['oi']:.2f} BTC")
            ...     print(f"时间: {oi_data['timestamp']}")
        """
        if self.mock_mode:
            logger.warning(f"Mock模式: 返回模拟{symbol}持仓量")
            return self._get_mock_open_interest(symbol)
        
        try:
            logger.info(f"请求持仓量: symbol={symbol}")
            
            # 优先从Binance获取
            if self.binance:
                try:
                    oi_info = self.binance.fapiPublicGetOpenInterest({
                        'symbol': symbol.replace('/', '')
                    })
                    
                    oi_value = float(oi_info.get('openInterest', 0))
                    timestamp_ms = int(oi_info.get('time', 0))
                    timestamp = datetime.fromtimestamp(timestamp_ms / 1000)
                    
                    result = {
                        'oi': oi_value,
                        'timestamp': timestamp
                    }
                    logger.debug(f"成功获取{symbol}持仓量 (Binance): {oi_value:.2f}")
                    return result
                except Exception as e:
                    logger.warning(f"Binance获取持仓量失败: {str(e)}，尝试OKX")
            
            # 降级到OKX
            if self.okx:
                try:
                    self.okx.load_markets()
                    
                    # OKX的持仓量API
                    oi_info = self.okx.fetch_open_interest(symbol)
                    oi_value = float(oi_info.get('openInterestAmount', 0))
                    timestamp = datetime.now()  # OKX可能不返回时间戳
                    
                    result = {
                        'oi': oi_value,
                        'timestamp': timestamp
                    }
                    logger.debug(f"成功获取{symbol}持仓量 (OKX): {oi_value:.2f}")
                    return result
                except Exception as e:
                    logger.warning(f"OKX获取持仓量失败: {str(e)}")
            
            logger.error("所有交易所均无法获取持仓量")
            return None
            
        except Exception as e:
            logger.error(f"Unexpected error fetching {symbol} open interest: {e}", exc_info=True)
            return None
    
    def calculate_oi_change_1h(self, current_oi: float, historical_oi_list: List[float]) -> Optional[float]:
        """计算1小时持仓量变化率
        
        通过对比当前OI与1小时前的OI，计算变化百分比。
        OI大幅下降（>15%）通常表示大规模强制平仓。
        
        Args:
            current_oi: 当前持仓量
            historical_oi_list: 历史OI列表（按时间顺序，最后一个为1小时前）
                               至少需要12个数据点（每5分钟一个）
            
        Returns:
            float: OI变化率（百分比形式，如-15.5表示下降15.5%）
                  失败时返回None
            
        Examples:
            >>> fetcher = CCXTFetcher()
            >>> change = fetcher.calculate_oi_change_1h(current_oi=50000, historical_oi_list=[...])
            >>> if change is not None and change < -15:
            ...     print(f"⚠️ OI断崖式下跌: {change:.2f}%，疑似大规模清算")
        """
        try:
            if not historical_oi_list or len(historical_oi_list) == 0:
                logger.error("历史OI列表为空")
                return None
            
            # 取1小时前的OI（假设每5分钟一个数据点，12个点=1小时）
            oi_1h_ago_index = max(0, len(historical_oi_list) - 12)
            oi_1h_ago = historical_oi_list[oi_1h_ago_index]
            
            if oi_1h_ago == 0:
                logger.error("1小时前OI为0，避免除零错误")
                return None
            
            change_rate = ((current_oi - oi_1h_ago) / oi_1h_ago) * 100
            
            logger.info(f"OI 1小时变化率: {change_rate:.2f}% (当前={current_oi:.2f}, 1小时前={oi_1h_ago:.2f})")
            
            # 记录异常波动
            if change_rate < -15:
                logger.warning(f"⚠️ OI断崖式下跌: {change_rate:.2f}%，疑似大规模强制平仓")
            elif change_rate > 15:
                logger.info(f"OI大幅增长: {change_rate:.2f}%，新资金入场")
            
            return change_rate
            
        except Exception as e:
            logger.error(f"计算OI变化率失败: {str(e)}", exc_info=True)
            return None
    
    def _get_mock_funding_rate(self, symbol: str) -> float:
        """生成模拟资金费率
        
        Args:
            symbol: 交易对符号
            
        Returns:
            float: 模拟的资金费率（-0.001到0.001之间）
        """
        import random
        return round(random.uniform(-0.001, 0.001), 6)
    
    def _get_mock_open_interest(self, symbol: str) -> Dict[str, Any]:
        """生成模拟持仓量数据
        
        Args:
            symbol: 交易对符号
            
        Returns:
            dict: 模拟的OI数据
        """
        import random
        from datetime import datetime
        
        # BTC持仓量通常在30000-80000之间
        oi_value = round(random.uniform(30000, 80000), 2)
        
        return {
            'oi': oi_value,
            'timestamp': datetime.now()
        }


# 便捷函数
def create_ccxt_fetcher(mock_mode: bool = False) -> CCXTFetcher:
    """创建CCXT数据获取器实例的工厂函数
    
    Args:
        mock_mode: 是否启用Mock模式
        
    Returns:
        CCXTFetcher: 配置好的获取器实例
    """
    return CCXTFetcher(mock_mode=mock_mode)
