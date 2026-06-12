"""
多源共振监控系统 - Hyperliquid DEX 衍生品数据获取器

Hyperliquid 是目前最大的去中心化衍生品交易所 (DEX)，交易量可排全球前三。
其 API 完全开放，无需 API Key，不屏蔽美国 IP。

优势:
- Web3 原生平台，完全免费，无需注册
- API 完全开放，公共数据接口不屏蔽美国 IP
- 链上杠杆博弈比 CEX 更激进，恐慌预警效果极好
- 直接返回 funding rate / open interest / mark price

主要功能:
- 获取 BTC/USDT 实时 Funding Rate (永续合约资金费率)
- 获取 BTC/USDT Open Interest (未平仓合约量)
- 计算 OI USD 价值 (OI * markPx)
- Mock 模式支持测试

API: POST https://api.hyperliquid.xyz/info
端点: {"type": "metaAndAssetCtxs"}
响应: [universe[], asset_ctxs[]]
  universe[i].name = "BTC"
  asset_ctxs[i].funding = "0.0000125" (字符串, 小数形式)
  asset_ctxs[i].openInterest = "32772.53" (字符串, 以币计价)
  asset_ctxs[i].markPx = "62244.0" (标记价格, 用于 OI USD 换算)
"""

import requests
from requests.exceptions import Timeout, ConnectionError, HTTPError
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from utils.logger import getLogger
from utils.exceptions import DataFetchError
from config.settings import Config

logger = getLogger('hyperliquid_fetcher')


class HyperliquidFetcher:
    """Hyperliquid DEX 衍生品数据获取器

    从 Hyperliquid L1 区块链 Info API 获取永续合约的 funding rate 和 open interest。
    完全免费，无需 API Key，不限美国 IP。

    Attributes:
        session: requests 会话对象
        BASE_URL: API 基础地址
        _universe_cache: 缓存 universe 映射 (coin_name → index)
        _cache_ts: 缓存时间戳
    """

    BASE_URL = "https://api.hyperliquid.xyz/info"
    CACHE_TTL_SECONDS = 60  # universe 映射缓存 60 秒

    def __init__(self):
        self._universe_cache: Optional[Dict[str, int]] = None
        self._cache_ts: Optional[datetime] = None

        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'MultiSourceResonance/1.0',
        })

        logger.info(f"HyperliquidFetcher 初始化完成 (live mode)")

    def _normalize_symbol(self, symbol: str) -> str:
        """标准化交易对符号 → Hyperliquid coin name

        Args:
            symbol: 如 'BTC/USDT', 'BTC/USD', 'BTC'

        Returns:
            str: Hyperliquid 格式, 如 'BTC'
        """
        if '/' in symbol:
            return symbol.split('/')[0]
        return symbol.upper()

    def _fetch_universe(self) -> Optional[List[Dict[str, Any]]]:
        """获取 Hyperliquid universe (所有交易对元数据)

        Returns:
            list: universe 数组，或 None
        """
        try:
            response = self.session.post(
                self.BASE_URL,
                json={'type': 'meta'},
                timeout=Config.REQUEST_TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
            universe = data.get('universe', [])
            logger.debug(f"Hyperliquid universe: {len(universe)} 个交易对")
            return universe
        except Exception as e:
            logger.error(f"获取 Hyperliquid universe 失败: {e}")
            return None

    def _get_asset_index(self, coin: str) -> Optional[int]:
        """获取指定 coin 在 universe 中的索引 (含缓存)

        Args:
            coin: 币种名称, 如 'BTC'

        Returns:
            int: 索引，未找到返回 None
        """
        # 检查缓存
        if (self._universe_cache is not None and self._cache_ts is not None
                and (datetime.now() - self._cache_ts).total_seconds() < self.CACHE_TTL_SECONDS):
            return self._universe_cache.get(coin)

        # 拉取 universe
        universe = self._fetch_universe()
        if not universe:
            return None

        # 构建映射: coin_name → index
        self._universe_cache = {}
        for idx, asset in enumerate(universe):
            name = asset.get('name', '')
            self._universe_cache[name] = idx

        self._cache_ts = datetime.now()
        return self._universe_cache.get(coin)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception_type((Exception,)),
        reraise=True
    )
    def _fetch_meta_and_asset_ctxs(self) -> Optional[tuple]:
        """获取 meta + asset contexts 数据

        Returns:
            tuple: (universe_list, asset_ctxs_list) 或 None
        """
        response = self.session.post(
            self.BASE_URL,
            json={'type': 'metaAndAssetCtxs'},
            timeout=Config.REQUEST_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()

        if not isinstance(data, list) or len(data) < 2:
            logger.error(f"Hyperliquid metaAndAssetCtxs 响应格式异常: {type(data)}")
            return None

        universe = data[0].get('universe', [])
        asset_ctxs = data[1]

        return (universe, asset_ctxs)

    def get_funding_rate(self, symbol: str = 'BTC/USDT') -> Optional[float]:
        """获取 Hyperliquid 资金费率

        Hyperliquid 的资金费率以小数形式返回 (如 0.0000125 = 0.00125%)，
        正值表示多头付费给空头（看涨情绪），负值反之。

        Args:
            symbol: 交易对符号，如 'BTC/USDT'

        Returns:
            float: 资金费率（小数形式，如 -0.0001 表示 -0.01%）
                  失败返回 None

        Examples:
            >>> fetcher = HyperliquidFetcher()
            >>> rate = fetcher.get_funding_rate('BTC/USDT')
            >>> if rate is not None:
            ...     print(f"DEX资金费率: {rate*100:.4f}%")
        """
        coin = self._normalize_symbol(symbol)

        try:
            result = self._fetch_meta_and_asset_ctxs()
            if not result:
                return None

            universe, asset_ctxs = result

            # 找 coin 索引
            coin_idx = None
            for idx, asset in enumerate(universe):
                if asset.get('name', '') == coin:
                    coin_idx = idx
                    break

            if coin_idx is None or coin_idx >= len(asset_ctxs):
                logger.error(f"Hyperliquid universe 中未找到 {coin}")
                return None

            ctx = asset_ctxs[coin_idx]
            funding_str = ctx.get('funding', '0')
            funding_rate = float(funding_str)

            logger.info(
                f"Hyperliquid {coin} 资金费率: {funding_rate*100:.4f}% "
                f"(premium={ctx.get('premium', 'N/A')})"
            )
            return funding_rate

        except Timeout as e:
            logger.error(f"Hyperliquid 请求超时: {e}")
            return None
        except Exception as e:
            logger.error(f"Hyperliquid 获取资金费率失败: {e}", exc_info=True)
            return None

    def get_open_interest(self, symbol: str = 'BTC/USDT') -> Optional[Dict[str, Any]]:
        """获取 Hyperliquid 未平仓合约量 (OI)

        Hyperliquid 返回的 OI 以币计价 (如 32772.53 BTC),
        本方法自动转换为 USD 价值 (OI × markPx)。

        Args:
            symbol: 交易对符号，如 'BTC/USDT'

        Returns:
            dict: 包含:
                - 'oi': 持仓量（USD 价值）
                - 'oi_base': 持仓量（币本位）
                - 'mark_price': 标记价格
                - 'timestamp': datetime 对象
            失败返回 None

        Examples:
            >>> fetcher = HyperliquidFetcher()
            >>> oi = fetcher.get_open_interest('BTC/USDT')
            >>> if oi:
            ...     print(f"DEX OI: ${oi['oi']:,.0f}")
        """
        coin = self._normalize_symbol(symbol)

        try:
            result = self._fetch_meta_and_asset_ctxs()
            if not result:
                return None

            universe, asset_ctxs = result

            coin_idx = None
            for idx, asset in enumerate(universe):
                if asset.get('name', '') == coin:
                    coin_idx = idx
                    break

            if coin_idx is None or coin_idx >= len(asset_ctxs):
                logger.error(f"Hyperliquid universe 中未找到 {coin}")
                return None

            ctx = asset_ctxs[coin_idx]
            oi_base_str = ctx.get('openInterest', '0')
            mark_px_str = ctx.get('markPx', '0')

            oi_base = float(oi_base_str)
            mark_px = float(mark_px_str)
            oi_usd = oi_base * mark_px

            logger.info(
                f"Hyperliquid {coin} OI: ${oi_usd:,.0f} "
                f"({oi_base:,.2f} {coin} @ ${mark_px:,.2f})"
            )

            return {
                'oi': oi_usd,
                'oi_base': oi_base,
                'mark_price': mark_px,
                'timestamp': datetime.now(),
            }

        except Timeout as e:
            logger.error(f"Hyperliquid OI 请求超时: {e}")
            return None
        except Exception as e:
            logger.error(f"Hyperliquid 获取 OI 失败: {e}", exc_info=True)
            return None

    def get_liquidation_data(
        self, symbol: str = 'BTC/USDT', limit: int = 24
    ) -> Optional[List[Dict[str, Any]]]:
        """获取清算数据

        Note:
            Hyperliquid Info API 不直接提供清算历史数据。
            此方法返回空列表，上游应降级到 CCData 或使用 Mock。

        Args:
            symbol: 交易对符号
            limit: 返回条数 (忽略)

        Returns:
            list: 空列表 (Hyperliquid 不提供清算数据)
        """
        logger.debug("Hyperliquid 不提供清算历史数据，返回空列表")
        return []

    def calculate_oi_change_1h(
        self, current_oi: float, historical_oi_list: List[float]
    ) -> Optional[float]:
        """计算 1 小时持仓量变化率

        通过对比当前 OI 与 1 小时前的 OI，计算变化百分比。
        OI 大幅下降（>15%）通常表示大规模强制平仓。

        Args:
            current_oi: 当前持仓量 (USD)
            historical_oi_list: 历史 OI 列表（按时间顺序）

        Returns:
            float: OI 变化率（百分比），失败返回 None
        """
        try:
            if not historical_oi_list or len(historical_oi_list) == 0:
                logger.error("历史 OI 列表为空")
                return None

            oi_1h_ago_index = max(0, len(historical_oi_list) - 12)
            oi_1h_ago = historical_oi_list[oi_1h_ago_index]

            if oi_1h_ago == 0:
                logger.error("1 小时前 OI 为 0")
                return None

            change_rate = ((current_oi - oi_1h_ago) / oi_1h_ago) * 100

            logger.info(
                f"OI 1h 变化率: {change_rate:.2f}% "
                f"(当前=${current_oi:,.0f}, 1h前=${oi_1h_ago:,.0f})"
            )

            if change_rate < -15:
                logger.warning(f"OI 断崖式下跌: {change_rate:.2f}%, 疑似大规模清算")
            elif change_rate > 15:
                logger.info(f"OI 大幅增长: {change_rate:.2f}%, 新资金入场")

            return change_rate

        except Exception as e:
            logger.error(f"计算 OI 变化率失败: {e}", exc_info=True)
            return None

# 便捷函数
def create_hyperliquid_fetcher() -> HyperliquidFetcher:
    """创建 Hyperliquid 数据获取器实例

    Returns:
        HyperliquidFetcher: 配置好的获取器实例
    """
    return HyperliquidFetcher()
