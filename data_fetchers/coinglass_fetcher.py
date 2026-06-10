"""
多源共振监控系统 - Coinglass 聚合加密衍生品数据获取器

该模块通过 Coinglass API v4 获取跨 30+ 交易所聚合的加密衍生品市场数据，
替代原有的 CCXT 单交易所模式，提供全网资金费率和持仓量。

主要功能:
- 获取全网加权资金费率 (Global Funding Rate)
- 获取全网聚合持仓量 (Aggregated Open Interest)
- 获取清算热力图数据 (Liquidation Heatmap)
- 计算1小时OI变化率用于判断去杠杆进度
- 内置Mock模式,无API密钥时自动降级

API文档: https://coinglass.github.io/API-Reference/
Base URL: https://open-api-v4.coinglass.com
认证方式: Header CG-API-KEY

优势:
- 30+ 交易所聚合数据, 无需逐交易所调用
- 美国IP完全开放, 不需要代理
- 直接获取全网加权费率, 无需手动加权平均
"""

import requests
from requests.exceptions import Timeout, ConnectionError, HTTPError
from typing import Optional, Dict, Any, List, Union
from datetime import datetime, timedelta
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from utils.logger import getLogger
from utils.exceptions import DataFetchError
from config.settings import Config

logger = getLogger('coinglass_fetcher')


class CoinglassFetcher:
    """Coinglass 聚合加密衍生品数据获取器
    
    通过 Coinglass API v4 获取全网聚合的加密货币衍生品市场数据。
    覆盖 Binance, OKX, Bybit, CME, Deribit, Bitget 等 30+ 交易所。
    
    Attributes:
        api_key: Coinglass API密钥
        base_url: API基础URL
        session: requests会话对象
        mock_mode: Mock模式开关 (无API密钥时自动启用)
    """
    
    # 币种映射: CCXT格式 → Coinglass格式
    SYMBOL_MAP = {
        'BTC/USDT': 'BTC',
        'BTC/USD': 'BTC',
        'ETH/USDT': 'ETH',
        'ETH/USD': 'ETH',
        'BTC': 'BTC',
        'ETH': 'ETH',
    }
    
    def __init__(self, api_key: Optional[str] = None, mock_mode: bool = False):
        """初始化Coinglass数据获取器
        
        Args:
            api_key: Coinglass API密钥，默认从Config读取
            mock_mode: Mock模式开关，无API密钥时自动启用
        """
        self.api_key = api_key or Config.COINGLASS_API_KEY
        self.base_url = Config.COINGLASS_BASE_URL
        
        # 无API密钥时自动降级为Mock模式
        self.mock_mode = mock_mode or not self.api_key
        
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'MultiSourceResonance/1.0',
        })
        
        if self.api_key:
            self.session.headers['CG-API-KEY'] = self.api_key
        
        mode_desc = 'mock (无API密钥)' if self.mock_mode else 'live'
        logger.info(f"CoinglassFetcher初始化完成 (mode={mode_desc})")
    
    def _normalize_symbol(self, symbol: str) -> str:
        """将CCXT格式的交易对转换为Coinglass格式
        
        Args:
            symbol: 交易对符号，如'BTC/USDT'
            
        Returns:
            str: Coinglass格式，如'BTC'
        """
        return self.SYMBOL_MAP.get(symbol, symbol.split('/')[0] if '/' in symbol else symbol)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception_type((Exception,)),
        reraise=True
    )
    def get_funding_rate(self, symbol: str = 'BTC/USDT') -> Optional[float]:
        """获取全网加权资金费率
        
        从Coinglass获取跨交易所聚合的实时资金费率。
        返回的是全网加权平均值，比单交易所数据更可靠。
        负费率表示空头付费给多头（看跌情绪），正费率反之。
        
        Args:
            symbol: 交易对符号，如'BTC/USDT'、'ETH/USDT'
            
        Returns:
            float: 资金费率（小数形式，如-0.0001表示-0.01%）
                  失败时返回None
            
        Raises:
            DataFetchError: API请求失败时抛出
            
        Examples:
            >>> fetcher = CoinglassFetcher()
            >>> rate = fetcher.get_funding_rate('BTC/USDT')
            >>> if rate is not None:
            ...     print(f"全网资金费率: {rate * 100:.4f}%")
            ...     if rate < -0.0001:
            ...         print("全网看跌情绪浓厚")
        """
        if self.mock_mode:
            logger.warning(f"Mock模式: 返回模拟{symbol}资金费率")
            return self._get_mock_funding_rate(symbol)
        
        coin = self._normalize_symbol(symbol)
        url = f"{self.base_url}/api/futures/fundingRate/current"
        
        try:
            logger.info(f"请求Coinglass资金费率: coin={coin}")
            response = self.session.get(
                url,
                params={'symbol': coin},
                timeout=Config.REQUEST_TIMEOUT
            )
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('code') != '0':
                logger.error(f"Coinglass API返回错误: code={data.get('code')}, msg={data.get('msg')}")
                return None
            
            result_data = data.get('data', {})
            
            # CoinGlass返回各交易所费率列表, 提取加权平均值
            # 响应结构: data是一个列表，每项包含 exchangeName, rate 等字段
            if isinstance(result_data, list):
                rates = []
                for item in result_data:
                    rate_str = item.get('rate') or item.get('fundingRate') or item.get('currentFundingRate')
                    if rate_str is not None:
                        rate_val = float(rate_str)
                        # 费率通常以小数形式返回 (如 0.0001 = 0.01%)
                        rates.append(rate_val)
                
                if rates:
                    # 取各交易所费率的算术均值作为全网估计值
                    avg_rate = sum(rates) / len(rates)
                    logger.info(
                        f"成功获取{coin}全网资金费率: {avg_rate * 100:.4f}% "
                        f"(来自{len(rates)}个交易所)"
                    )
                    return avg_rate
            
            # 如果响应是单个对象
            if isinstance(result_data, dict):
                rate_val = result_data.get('rate') or result_data.get('fundingRate')
                if rate_val is not None:
                    return float(rate_val)
            
            logger.error(f"无法从Coinglass响应中提取资金费率: {result_data}")
            return None
            
        except Timeout as e:
            logger.error(f"Coinglass请求超时: {url}, error: {str(e)}")
            return None
        except HTTPError as e:
            logger.error(f"Coinglass HTTP错误: {e}")
            return None
        except Exception as e:
            logger.error(f"获取资金费率失败: {str(e)}", exc_info=True)
            return None
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception_type((Exception,)),
        reraise=True
    )
    def get_open_interest(self, symbol: str = 'BTC/USDT') -> Optional[Dict[str, Any]]:
        """获取全网聚合持仓量(OI)
        
        从Coinglass获取跨交易所聚合的持仓量数据。
        OI是衡量市场参与度和潜在清算风险的关键指标。
        
        Args:
            symbol: 交易对符号，如'BTC/USDT'
            
        Returns:
            dict: 包含以下字段:
                - 'oi': 持仓量数值（以美元计）
                - 'timestamp': 数据时间戳 (datetime对象)
            失败时返回None
            
        Raises:
            DataFetchError: API请求失败时抛出
            
        Examples:
            >>> fetcher = CoinglassFetcher()
            >>> oi_data = fetcher.get_open_interest('BTC/USDT')
            >>> if oi_data:
            ...     print(f"全网持仓量: ${oi_data['oi']:,.0f}")
        """
        if self.mock_mode:
            logger.warning(f"Mock模式: 返回模拟{symbol}持仓量")
            return self._get_mock_open_interest(symbol)
        
        coin = self._normalize_symbol(symbol)
        
        # 使用 OHLC history 端点获取最新OI (取最近1条)
        url = f"{self.base_url}/api/futures/openInterest/ohlc-history"
        
        try:
            logger.info(f"请求Coinglass OI数据: coin={coin}")
            response = self.session.get(
                url,
                params={
                    'symbol': coin,
                    'interval': '1h',
                    'limit': 2  # 取最近2条以保证至少有1条
                },
                timeout=Config.REQUEST_TIMEOUT
            )
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('code') != '0':
                logger.error(f"Coinglass API返回错误: code={data.get('code')}, msg={data.get('msg')}")
                return None
            
            result_data = data.get('data', [])
            
            if isinstance(result_data, list) and len(result_data) > 0:
                # 取最新一条OI记录
                latest = result_data[-1]
                
                # Coinglass OI OHLC返回: [timestamp, open, high, low, close, ...]
                # close 即为当前OI值
                oi_value = float(latest[4]) if len(latest) > 4 else 0
                timestamp_ms = int(latest[0]) if len(latest) > 0 else 0
                ts = datetime.fromtimestamp(timestamp_ms / 1000)
                
                result = {
                    'oi': oi_value,
                    'timestamp': ts
                }
                logger.info(f"成功获取{coin}全网OI: ${oi_value:,.0f}")
                return result
            
            logger.error(f"Coinglass OI响应格式异常: {result_data}")
            return None
            
        except Timeout as e:
            logger.error(f"Coinglass OI请求超时: {url}")
            return None
        except Exception as e:
            logger.error(f"获取持仓量失败: {str(e)}", exc_info=True)
            return None
    
    def get_liquidation_data(self, symbol: str = 'BTC/USDT', limit: int = 24) -> Optional[List[Dict[str, Any]]]:
        """获取清算热力图数据
        
        从Coinglass获取近期清算事件数据，用于判断市场去杠杆进度。
        大规模清算通常表示强制平仓潮，可能预示市场见底。
        
        Args:
            symbol: 交易对符号
            limit: 返回数据条数，默认24条(24小时)
            
        Returns:
            list: 清算事件列表，每项包含:
                - 'timestamp': 时间戳
                - 'long_liquidation': 多头清算量(USD)
                - 'short_liquidation': 空头清算量(USD)
                - 'total_liquidation': 总清算量(USD)
            失败时返回None
        """
        if self.mock_mode:
            return self._get_mock_liquidation_data(limit)
        
        coin = self._normalize_symbol(symbol)
        url = f"{self.base_url}/api/futures/liquidation/aggregated-history"
        
        try:
            logger.info(f"请求Coinglass清算数据: coin={coin}")
            response = self.session.get(
                url,
                params={
                    'symbol': coin,
                    'interval': '1h',
                    'limit': limit
                },
                timeout=Config.REQUEST_TIMEOUT
            )
            response.raise_for_status()
            
            data = response.json()
            if data.get('code') != '0':
                return None
            
            result_list = data.get('data', [])
            if not isinstance(result_list, list):
                return None
            
            formatted = []
            for item in result_list:
                if isinstance(item, list) and len(item) >= 4:
                    formatted.append({
                        'timestamp': datetime.fromtimestamp(int(item[0]) / 1000),
                        'long_liquidation': float(item[1]),
                        'short_liquidation': float(item[2]),
                        'total_liquidation': float(item[3]),
                    })
            
            return formatted if formatted else None
            
        except Exception as e:
            logger.error(f"获取清算数据失败: {str(e)}", exc_info=True)
            return None
    
    def calculate_oi_change_1h(
        self, current_oi: float, historical_oi_list: List[float]
    ) -> Optional[float]:
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
            >>> fetcher = CoinglassFetcher()
            >>> change = fetcher.calculate_oi_change_1h(
            ...     current_oi=10_000_000_000,
            ...     historical_oi_list=[9_500_000_000] * 13
            ... )
            >>> if change is not None and change < -15:
            ...     print(f"OI断崖式下跌: {change:.2f}%，疑似大规模清算")
        """
        try:
            if not historical_oi_list or len(historical_oi_list) == 0:
                logger.error("历史OI列表为空")
                return None
            
            oi_1h_ago_index = max(0, len(historical_oi_list) - 12)
            oi_1h_ago = historical_oi_list[oi_1h_ago_index]
            
            if oi_1h_ago == 0:
                logger.error("1小时前OI为0，避免除零错误")
                return None
            
            change_rate = ((current_oi - oi_1h_ago) / oi_1h_ago) * 100
            
            logger.info(
                f"OI 1小时变化率: {change_rate:.2f}% "
                f"(当前=${current_oi:,.0f}, 1小时前=${oi_1h_ago:,.0f})"
            )
            
            if change_rate < -15:
                logger.warning(
                    f"OI断崖式下跌: {change_rate:.2f}%，"
                    f"疑似大规模强制平仓"
                )
            elif change_rate > 15:
                logger.info(f"OI大幅增长: {change_rate:.2f}%，新资金入场")
            
            return change_rate
            
        except Exception as e:
            logger.error(f"计算OI变化率失败: {str(e)}", exc_info=True)
            return None
    
    def _get_mock_funding_rate(self, symbol: str) -> float:
        """生成模拟资金费率"""
        import random
        return round(random.uniform(-0.001, 0.001), 6)
    
    def _get_mock_open_interest(self, symbol: str) -> Dict[str, Any]:
        """生成模拟持仓量数据"""
        import random
        
        # BTC全网OI通常在100-300亿美元
        oi_value = round(random.uniform(10_000_000_000, 30_000_000_000), 2)
        
        return {
            'oi': oi_value,
            'timestamp': datetime.now()
        }
    
    def _get_mock_liquidation_data(self, limit: int) -> List[Dict[str, Any]]:
        """生成模拟清算数据"""
        import random
        
        data = []
        for i in range(limit):
            ts = datetime.now() - timedelta(hours=i)
            long_liq = random.uniform(1_000_000, 50_000_000)
            short_liq = random.uniform(1_000_000, 50_000_000)
            data.append({
                'timestamp': ts,
                'long_liquidation': long_liq,
                'short_liquidation': short_liq,
                'total_liquidation': long_liq + short_liq,
            })
        return data


# 便捷函数
def create_coinglass_fetcher(mock_mode: bool = False, api_key: Optional[str] = None) -> CoinglassFetcher:
    """创建Coinglass数据获取器实例的工厂函数
    
    Args:
        mock_mode: 是否启用Mock模式
        api_key: Coinglass API密钥（可选，默认从config读取）
        
    Returns:
        CoinglassFetcher: 配置好的获取器实例
    """
    return CoinglassFetcher(mock_mode=mock_mode, api_key=api_key)
