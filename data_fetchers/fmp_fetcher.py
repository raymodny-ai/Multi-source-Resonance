"""
多源共振监控系统 - FMP (Financial Modeling Prep) 短卖+场外交易量数据获取器

FMP 专门提供结构化的基本面和量价 API，直接包含 Short Volume 和
Off-exchange Volume 接口。数据已清洗为 JSON 格式，省去解析 FINRA
管道分隔文件的步骤。

优势:
- 结构化 JSON 响应，无需解析管道分隔文件
- 直接返回 shortVolume / totalVolume，即查即用
- Free Tier: 250 requests/day, 性价比极高
- 降级策略: FMP → FINRA (管道文件) → Mock

主要功能:
- 从 FMP /api/v4/short_volume 获取短期卖空成交量
- 计算 Off-Exchange Short Ratio (shortVolume / totalVolume * 100)
- 检测连续N日短卖比超过阈值
- API Key 未配置时自动返回 None (触发上游降级到 FINRA)
- 内置 Mock 模式用于测试

API 端点: https://financialmodelingprep.com/api/v4/short_volume?symbol={SYMBOL}&apikey={KEY}
响应格式: [{"symbol":"AAPL","date":"2024-01-05","shortVolume":1234567,"shortExemptVolume":23456,"totalVolume":9876543,"market":"N"}, ...]

价格 (2026): Starter $19/月 (250 req/day), Growth $49/月, Pro $99/月
"""

import requests
from requests.exceptions import Timeout, ConnectionError, HTTPError
from typing import Optional, Dict, Any, List
from datetime import datetime, date
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from utils.logger import getLogger
from utils.exceptions import DataFetchError
from config.settings import Config

logger = getLogger('fmp_fetcher')


class FMPFetcher:
    """FMP (Financial Modeling Prep) 短卖数据获取器

    通过 FMP 的结构化 JSON API 获取每日短卖成交量数据。
    API Key 未配置时，fetch_short_volume_data() 返回 None，
    上游调度器会自动降级到 FINRA 管道文件。

    Attributes:
        session: requests 会话对象
        api_key: FMP API 密钥
        mock_mode: Mock 模式开关
        base_url: FMP API 基础地址
    """

    BASE_URL = "https://financialmodelingprep.com"
    SHORT_VOLUME_ENDPOINT = "/api/v4/short_volume"

    def __init__(self, api_key: Optional[str] = None, mock_mode: bool = False):
        """初始化 FMP 数据获取器

        Args:
            api_key: FMP API 密钥，可从 https://site.financialmodelingprep.com 免费获取
                     未提供时自动从 Config.FMP_API_KEY 读取
            mock_mode: Mock 模式开关，用于无网络连接时的测试
        """
        self.mock_mode = mock_mode
        self.api_key = api_key or Config.FMP_API_KEY

        # 创建会话对象
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json',
        })

        if self.api_key:
            logger.info(f"FMPFetcher 初始化完成 (API Key: ...{self.api_key[-6:]})")
        elif mock_mode:
            logger.info("FMPFetcher 初始化完成 (Mock模式)")
        else:
            logger.warning("FMPFetcher 初始化完成 (无API Key，将自动降级到FINRA)")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=5, max=45),
        retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError)),
        reraise=True
    )
    def fetch_short_volume_data(self, symbol: str = 'SPY') -> Optional[Dict[str, Any]]:
        """从 FMP 获取指定标的的短卖成交量数据

        调用 FMP /api/v4/short_volume 端点获取结构化 JSON，
        自动聚合所有市场条目（同 FINRA 模式兼容）。

        Args:
            symbol: 标的股票代码，如 'SPY'、'QQQ'

        Returns:
            dict: 包含以下字段:
                - 'date': 数据日期 (YYYY-MM-DD)
                - 'symbol': 标的代码
                - 'short_volume': 总短卖成交量
                - 'total_volume': 总成交量
                - 'short_ratio': 短卖比例 (自动计算, %)
            失败时返回 None

        Raises:
            DataFetchError: API 请求或解析失败时抛出

        Examples:
            >>> fetcher = FMPFetcher(api_key='your_key')
            >>> data = fetcher.fetch_short_volume_data('SPY')
            >>> if data:
            ...     print(f"SPY短卖比例: {data['short_ratio']:.2f}%")
        """
        if self.mock_mode:
            logger.warning(f"Mock模式: 返回模拟{symbol}卖空数据")
            return self._get_mock_short_volume_data(symbol)

        # API Key 未配置 → 返回 None (触发上游降级)
        if not self.api_key:
            logger.warning("FMP API Key 未配置，返回 None 触发上游降级")
            return None

        symbol_upper = symbol.upper()
        url = f"{self.BASE_URL}{self.SHORT_VOLUME_ENDPOINT}"

        try:
            logger.info(f"请求 FMP 短卖数据: symbol={symbol_upper}")
            response = self.session.get(
                url,
                params={
                    'symbol': symbol_upper,
                    'apikey': self.api_key,
                },
                timeout=Config.REQUEST_TIMEOUT
            )

            if response.status_code == 401:
                logger.error("FMP API Key 无效 (401 Unauthorized)")
                return None

            if response.status_code == 429:
                logger.error("FMP 速率限制 (429)，请求过于频繁")
                return None

            response.raise_for_status()
            data = response.json()

            if not data or not isinstance(data, list):
                logger.warning(f"FMP 返回空数据: symbol={symbol_upper}")
                return None

            # 聚合所有市场条目 (FMP 可能返回多行，每行对应不同市场代码)
            total_short = 0
            total_volume = 0
            latest_date = None

            for item in data:
                item_symbol = item.get('symbol', '').upper()
                if item_symbol != symbol_upper:
                    continue

                short_vol = item.get('shortVolume', 0)
                total_vol = item.get('totalVolume', 0)

                total_short += short_vol
                total_volume += total_vol

                # 取最新的日期
                item_date = item.get('date', '')
                if item_date and (latest_date is None or item_date > latest_date):
                    latest_date = item_date

            if total_volume == 0:
                logger.warning(f"FMP 数据中 {symbol_upper} 总成交量为零")
                return None

            result = {
                'date': latest_date or datetime.now().strftime('%Y-%m-%d'),
                'symbol': symbol_upper,
                'short_volume': total_short,
                'total_volume': total_volume,
            }

            logger.info(
                f"FMP 成功获取 {symbol_upper} 短卖数据 "
                f"(date={result['date']}, "
                f"short={total_short:,}, total={total_volume:,})"
            )
            return result

        except Timeout as e:
            logger.error(f"FMP 请求超时: symbol={symbol_upper}, error={str(e)}")
            raise DataFetchError(
                message=f"FMP 请求超时: {str(e)}",
                error_code="FMP_TIMEOUT",
                details={"symbol": symbol_upper}
            )
        except HTTPError as e:
            logger.error(f"FMP HTTP 错误: status={response.status_code}")
            return None
        except Exception as e:
            logger.error(f"FMP 数据处理失败: {str(e)}", exc_info=True)
            raise DataFetchError(
                message=f"无法从 FMP 获取 {symbol_upper} 短卖数据: {str(e)}",
                error_code="FMP_REQUEST_FAILED",
                details={"symbol": symbol_upper, "error": str(e)}
            )

    def calculate_off_exchange_short_ratio(self, raw_dict: Dict[str, Any]) -> Optional[float]:
        """计算短卖比例

        公式: short_volume / total_volume * 100

        Args:
            raw_dict: fetch_short_volume_data 返回的字典
                     字段: short_volume, total_volume

        Returns:
            float: 短卖比例百分比（如 45.8 表示 45.8%）
                  失败时返回 None

        Examples:
            >>> fetcher = FMPFetcher(api_key='your_key')
            >>> data = fetcher.fetch_short_volume_data('SPY')
            >>> ratio = fetcher.calculate_off_exchange_short_ratio(data)
            >>> if ratio and ratio > 45.0:
            ...     print("短卖比例超过45%，机构吸筹信号")
        """
        try:
            if raw_dict is None:
                logger.error("输入数据为None")
                return None

            short_vol = raw_dict.get('short_volume', 0)
            total_vol = raw_dict.get('total_volume', 0)

            if total_vol == 0:
                logger.error("总成交量为0，避免除零错误")
                return None

            ratio = (short_vol / total_vol) * 100

            logger.info(
                f"短卖比例: {ratio:.2f}% "
                f"(short={short_vol:,}, total={total_vol:,})"
            )

            if ratio > 45.0:
                logger.warning(f"短卖比例={ratio:.2f}% 超过阈值45%，机构被动吸筹信号")

            return ratio

        except Exception as e:
            logger.error(f"计算短卖比例失败: {str(e)}", exc_info=True)
            return None

    def check_consecutive_days(
        self,
        data_history: List[Dict[str, Any]],
        threshold: float = 45.0,
        consecutive_days: int = 2
    ) -> bool:
        """检测连续N日短卖比超过阈值

        检查历史数据中是否有连续 consecutive_days 天的短卖比例超过 threshold。

        Args:
            data_history: 历史数据列表，每个元素包含 'date' 和 'short_ratio' 字段
                         按时间顺序排列（最新的在最后）
            threshold: 短卖比例阈值，默认 45.0%
            consecutive_days: 连续天数，默认 2 天

        Returns:
            bool: True 表示满足条件，False 表示不满足

        Examples:
            >>> fetcher = FMPFetcher(api_key='your_key')
            >>> history = [
            ...     {'date': '2026-06-07', 'short_ratio': 46.5},
            ...     {'date': '2026-06-08', 'short_ratio': 47.2},
            ... ]
            >>> if fetcher.check_consecutive_days(history):
            ...     print("连续2日短卖比>45%，确认机构吸筹")
        """
        try:
            if not data_history or len(data_history) < consecutive_days:
                logger.warning(
                    f"历史数据不足，需要至少 {consecutive_days} 天，"
                    f"当前 {len(data_history)} 天"
                )
                return False

            recent_data = data_history[-consecutive_days:]

            for day_data in recent_data:
                ratio = day_data.get('short_ratio')
                if ratio is None or ratio <= threshold:
                    logger.info(
                        f"不满足条件: {day_data.get('date')} "
                        f"短卖比={ratio}%"
                    )
                    return False

            dates = [d.get('date', 'unknown') for d in recent_data]
            logger.info(
                f"检测到连续 {consecutive_days} 日短卖比>{threshold}%: {dates}"
            )
            return True

        except Exception as e:
            logger.error(f"检测连续天数失败: {str(e)}", exc_info=True)
            return False

    def _get_mock_short_volume_data(self, symbol: str) -> Dict[str, Any]:
        """生成模拟卖空数据

        Args:
            symbol: 标的股票代码

        Returns:
            dict: 模拟的卖空数据结构
        """
        import random

        today = datetime.now()

        # 模拟合理成交量 (SPY日均约5-8千万, QQQ约2-4千万)
        if symbol.upper() in ('SPY', 'SPX'):
            total_volume = random.randint(50000000, 80000000)
        elif symbol.upper() in ('QQQ', 'IWM'):
            total_volume = random.randint(20000000, 40000000)
        else:
            total_volume = random.randint(5000000, 20000000)

        # 短卖比在 40-55% 之间波动 (正常范围)
        short_ratio = random.uniform(40.0, 55.0)
        short_volume = int(total_volume * short_ratio / 100)

        return {
            'date': today.strftime('%Y-%m-%d'),
            'symbol': symbol.upper(),
            'short_volume': short_volume,
            'total_volume': total_volume,
            'short_ratio': round(short_ratio, 2),
        }


# 便捷函数
def create_fmp_fetcher(api_key: Optional[str] = None, mock_mode: bool = False) -> FMPFetcher:
    """创建 FMP 数据获取器实例的工厂函数

    Args:
        api_key: FMP API 密钥
        mock_mode: 是否启用 Mock 模式

    Returns:
        FMPFetcher: 配置好的获取器实例
    """
    return FMPFetcher(api_key=api_key, mock_mode=mock_mode)
