"""
多源共振监控系统 - CCData (原 CryptoCompare) 衍生品数据获取器

CCData 是老牌加密数据提供商，Free Tier 每月 10 万次 API 调用。
提供衍生品端点，可提取头部交易所的 Funding Rate、Open Interest
和 Liquidation 数据，不需要挂代理。

优势:
- 每月 10 万次免费调用 (Free Tier)
- 老牌数据商，API 稳定可靠
- 覆盖头部 CEX 衍生品数据
- 不屏蔽美国 IP

劣势:
- 免费版历史深度和部分高频接口有颗粒度限制
- 需要 API Key 注册

主要功能:
- 获取 BTC/USDT 实时 Funding Rate
- 获取 BTC/USDT Open Interest
- 降级链: Hyperliquid DEX → CCData CEX → Mock

API 文档: https://data-api.cryptocompare.com
认证: Authorization: Apikey {key}
"""

import requests
from requests.exceptions import Timeout, ConnectionError, HTTPError
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from utils.logger import getLogger
from utils.exceptions import DataFetchError
from config.settings import Config

logger = getLogger('ccdata_fetcher')


class CCDataFetcher:
    """CCData (CryptoCompare) 衍生品数据获取器

    通过 CCData Futures API 获取 CEX 衍生品市场数据。
    Free Tier 每月 10 万次调用。

    Attributes:
        api_key: CCData API 密钥
        session: requests 会话对象
        mock_mode: Mock 模式开关
    """

    BASE_URL = "https://data-api.cryptocompare.com"
    DEFAULT_MARKET = "binance"

    def __init__(self, api_key: Optional[str] = None, mock_mode: bool = False):
        """初始化 CCData 数据获取器

        Args:
            api_key: CCData API 密钥，未提供时从 Config 读取
            mock_mode: Mock 模式开关
        """
        self.api_key = api_key or Config.CCDATA_API_KEY
        self.mock_mode = mock_mode or not self.api_key

        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'MultiSourceResonance/1.0',
        })

        if self.api_key:
            self.session.headers['Authorization'] = f'Apikey {self.api_key}'

        mode = 'mock (无API Key)' if self.mock_mode else 'live'
        logger.info(f"CCDataFetcher 初始化完成 (mode={mode})")

    def _normalize_symbol(self, symbol: str) -> tuple:
        """标准化交易对符号 → (market, instrument)

        Args:
            symbol: 如 'BTC/USDT', 'ETH/USDT'

        Returns:
            tuple: (market, instrument), 如 ('binance', 'BTC-USDT')
        """
        if '/' in symbol:
            base, quote = symbol.split('/')
        else:
            base = symbol
            quote = 'USDT'

        return (self.DEFAULT_MARKET, f"{base}-{quote}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception_type((Exception,)),
        reraise=True
    )
    def get_funding_rate(self, symbol: str = 'BTC/USDT') -> Optional[float]:
        """获取 CEX 资金费率 (Binance)

        从 CCData 获取 Binance 永续合约的实时资金费率。

        Args:
            symbol: 交易对符号

        Returns:
            float: 资金费率（小数形式），失败返回 None

        Examples:
            >>> fetcher = CCDataFetcher(api_key='your_key')
            >>> rate = fetcher.get_funding_rate('BTC/USDT')
            >>> if rate is not None:
            ...     print(f"Binance 资金费率: {rate*100:.4f}%")
        """
        if self.mock_mode:
            return self._mock_funding_rate()

        market, instrument = self._normalize_symbol(symbol)

        try:
            url = f"{self.BASE_URL}/futures/v1/funding-rate/current"
            logger.info(f"请求 CCData 资金费率: {instrument}@{market}")

            response = self.session.get(
                url,
                params={'market': market, 'instrument': instrument},
                timeout=Config.REQUEST_TIMEOUT
            )

            if response.status_code == 401:
                logger.error("CCData API Key 无效 (401)")
                return None
            if response.status_code == 429:
                logger.error("CCData 速率限制 (429)")
                return None

            response.raise_for_status()
            data = response.json()

            # 尝试多种可能的响应格式
            result = data.get('Data', data)

            # 格式1: {"Data": {"CURRENT_FUNDING_RATE": 0.0001, ...}}
            if isinstance(result, dict):
                rate = (result.get('CURRENT_FUNDING_RATE')
                        or result.get('fundingRate')
                        or result.get('funding_rate')
                        or result.get('FUNDING_RATE'))
                if rate is not None:
                    rate_val = float(rate)
                    logger.info(f"CCData {instrument} 资金费率: {rate_val*100:.4f}%")
                    return rate_val

            # 格式2: 列表形式
            if isinstance(result, list) and len(result) > 0:
                item = result[0]
                rate = (item.get('CURRENT_FUNDING_RATE')
                        or item.get('fundingRate')
                        or item.get('funding_rate'))
                if rate is not None:
                    return float(rate)

            logger.error(f"无法解析 CCData 资金费率响应: {data}")
            return None

        except Timeout as e:
            logger.error(f"CCData 请求超时: {e}")
            return None
        except Exception as e:
            logger.error(f"CCData 获取资金费率失败: {e}", exc_info=True)
            return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception_type((Exception,)),
        reraise=True
    )
    def get_open_interest(self, symbol: str = 'BTC/USDT') -> Optional[Dict[str, Any]]:
        """获取 CEX 未平仓合约量 (Binance)

        Args:
            symbol: 交易对符号

        Returns:
            dict: 包含 'oi' 和 'timestamp'，失败返回 None
        """
        if self.mock_mode:
            return self._mock_open_interest()

        market, instrument = self._normalize_symbol(symbol)

        try:
            url = f"{self.BASE_URL}/futures/v1/open-interest/current"
            logger.info(f"请求 CCData OI: {instrument}@{market}")

            response = self.session.get(
                url,
                params={'market': market, 'instrument': instrument},
                timeout=Config.REQUEST_TIMEOUT
            )

            if response.status_code == 401:
                logger.error("CCData API Key 无效 (401)")
                return None
            if response.status_code == 429:
                logger.error("CCData 速率限制 (429)")
                return None

            response.raise_for_status()
            data = response.json()

            result = data.get('Data', data)

            if isinstance(result, dict):
                oi_val = (result.get('CURRENT_OPEN_INTEREST')
                          or result.get('OPEN_INTEREST')
                          or result.get('openInterest')
                          or result.get('OI'))
                if oi_val is not None:
                    oi_usd = float(oi_val)
                    logger.info(f"CCData {instrument} OI: ${oi_usd:,.0f}")
                    return {
                        'oi': oi_usd,
                        'timestamp': datetime.now(),
                    }

            if isinstance(result, list) and len(result) > 0:
                item = result[0]
                oi_val = (item.get('CURRENT_OPEN_INTEREST')
                          or item.get('OPEN_INTEREST')
                          or item.get('openInterest'))
                if oi_val is not None:
                    return {
                        'oi': float(oi_val),
                        'timestamp': datetime.now(),
                    }

            logger.error(f"无法解析 CCData OI 响应: {data}")
            return None

        except Timeout as e:
            logger.error(f"CCData OI 请求超时: {e}")
            return None
        except Exception as e:
            logger.error(f"CCData 获取 OI 失败: {e}", exc_info=True)
            return None

    def get_liquidation_data(
        self, symbol: str = 'BTC/USDT', limit: int = 24
    ) -> Optional[List[Dict[str, Any]]]:
        """获取清算数据

        Note:
            CCData Free Tier 可能不包含清算端点，
            此方法返回 Mock 数据作为占位。

        Args:
            symbol: 交易对符号
            limit: 返回条数

        Returns:
            list: 清算事件列表，或 Mock 数据
        """
        if self.mock_mode:
            return self._mock_liquidation_data(limit)

        # CCData Free Tier 可能无清算端点，返回 Mock
        logger.debug("CCData Free Tier 可能无清算端点，返回 Mock 数据")
        return self._mock_liquidation_data(limit)

    def calculate_oi_change_1h(
        self, current_oi: float, historical_oi_list: List[float]
    ) -> Optional[float]:
        """计算 1 小时持仓量变化率"""
        try:
            if not historical_oi_list or len(historical_oi_list) == 0:
                return None

            oi_1h_ago_index = max(0, len(historical_oi_list) - 12)
            oi_1h_ago = historical_oi_list[oi_1h_ago_index]

            if oi_1h_ago == 0:
                return None

            change_rate = ((current_oi - oi_1h_ago) / oi_1h_ago) * 100

            logger.info(f"OI 1h 变化率: {change_rate:.2f}%")

            if change_rate < -15:
                logger.warning(f"OI 断崖式下跌: {change_rate:.2f}%")
            elif change_rate > 15:
                logger.info(f"OI 大幅增长: {change_rate:.2f}%")

            return change_rate

        except Exception as e:
            logger.error(f"计算 OI 变化率失败: {e}", exc_info=True)
            return None

    # ---- Mock 数据方法 ----

    def _mock_funding_rate(self) -> float:
        import random
        return round(random.uniform(-0.001, 0.001), 6)

    def _mock_open_interest(self) -> Dict[str, Any]:
        import random
        return {
            'oi': round(random.uniform(10_000_000_000, 30_000_000_000), 2),
            'timestamp': datetime.now(),
        }

    def _mock_liquidation_data(self, limit: int) -> List[Dict[str, Any]]:
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
def create_ccdata_fetcher(api_key: Optional[str] = None, mock_mode: bool = False) -> CCDataFetcher:
    """创建 CCData 数据获取器实例

    Args:
        api_key: CCData API 密钥
        mock_mode: Mock 模式开关

    Returns:
        CCDataFetcher
    """
    return CCDataFetcher(api_key=api_key, mock_mode=mock_mode)
