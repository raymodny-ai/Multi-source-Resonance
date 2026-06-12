"""
多源共振监控系统 - AXLFI 暗盘数据获取器

替代已下线的 Stockgrid，使用 axlfi.com 公开 API 获取暗盘净头寸和卖空数据。
API 公开无需鉴权，提供 252 天历史数据。

数据维度:
- dark_pool_position: 暗盘净头寸（美元）
- dark_pool_net_volume: 暗盘净成交量（股）
- short_volume_pct: 卖空占比（%）
- prices: 收盘价序列
"""
import requests
import numpy as np
from typing import Optional, Dict, Any, List
from datetime import datetime
from utils.logger import getLogger

logger = getLogger('axlfi_fetcher')

BASE_URL = "https://axlfi.com/axlfi-app-backend/api"


class AxlfiFetcher:
    """AXLFI 暗盘数据获取器
    
    从 axlfi.com 公开 API 提取:
    - 暗盘累积净头寸 (dollar_dp_position)
    - 暗盘净成交量 (dollar_net_volume)
    - 卖空占比 (short_volume_pct)
    - Leaderboard（全市场暗盘排行）
    
    API 公开无需 API Key，默认 252 天窗口。
    """

    def __init__(self):
        self.base_url = BASE_URL
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        logger.info(f"AxlfiFetcher 初始化 (live mode)")

    def fetch_symbol_data(self, symbol: str = 'SPY', window: int = 252) -> Optional[Dict[str, Any]]:
        """获取单个标的的暗盘和卖空数据
        
        Args:
            symbol: 股票代码 (SPY, QQQ, IWM, AAPL, etc.)
            window: 历史窗口天数 (默认252)
            
        Returns:
            dict with keys: dates, dollar_dp_position, dollar_net_volume,
                            net_volume, short_volume, short_volume_pct, prices
        """
        try:
            url = f"{self.base_url}/dark_pools/symbol?symbol={symbol}&window={window}"
            r = self.session.get(url, timeout=15)
            r.raise_for_status()
            data = r.json()

            # 解析返回结构
            result = {
                'symbol': symbol,
                'as_of_date': data.get('as_of_date'),
                'latest': data.get('latest', {}),
            }

            # 暗盘净头寸序列（API 返回百万美元单位，×1M 转为实际美元）
            dp = data.get('individual_dark_pool_position_data', {})
            SCALE = 1_000_000
            if isinstance(dp, dict):
                result['dates'] = dp.get('dates', [])
                result['dollar_dp_position'] = [float(v) * SCALE if v else 0 for v in dp.get('dollar_dp_position', [])]
                result['dollar_net_volume'] = [float(v) * SCALE if v else 0 for v in dp.get('dollar_net_volume', [])]

            # 卖空数据
            sv = data.get('individual_short_volume', {})
            if isinstance(sv, dict):
                result['short_volume_dates'] = sv.get('dates', [])
                result['net_volume'] = [float(v) if v else 0 for v in sv.get('net_volume', [])]
                result['short_volume'] = [float(v) if v else 0 for v in sv.get('short_volume', [])]
                result['short_volume_pct'] = [float(v) if v else 0 for v in sv.get('short_volume_pct', [])]

            # 价格序列
            prices = data.get('prices', {})
            if isinstance(prices, dict):
                result['price_dates'] = prices.get('dates', [])
                result['close'] = [float(v) if v else 0 for v in prices.get('close', [])]

            logger.info(
                f"AXLFI {symbol}: dp_pos={result['dollar_dp_position'][-1] if result.get('dollar_dp_position') else 'N/A':.0f}, "
                f"short_pct={result['short_volume_pct'][-1] if result.get('short_volume_pct') else 'N/A'}%, "
                f"date={result['as_of_date']}"
            )
            return result

        except Exception as e:
            logger.error(f"AXLFI {symbol} 数据获取失败: {e}")
            return None

    def fetch_leaderboard(self, metric: str = 'dollar_dp_position',
                          sort: str = 'desc', limit: int = 20) -> Optional[List[Dict]]:
        """获取暗盘全市场排行榜
        
        Args:
            metric: 排序指标 (dollar_dp_position, short_volume_percent, etc.)
            sort: asc/desc
            limit: 返回数量
        """
        try:
            url = f"{self.base_url}/dark_pools/leaderboard?metric={metric}&sort={sort}&limit={limit}"
            r = self.session.get(url, timeout=15)
            r.raise_for_status()
            data = r.json()
            logger.info(f"AXLFI leaderboard: {len(data.get('data', []))} symbols, as_of={data.get('as_of_date')}")
            return data.get('data', [])
        except Exception as e:
            logger.error(f"AXLFI leaderboard 获取失败: {e}")
            return None

    def get_net_position_series(self, symbol: str = 'SPY',
                                periods: List[int] = [20, 60, 120]) -> Optional[Dict[str, List[float]]]:
        """获取指定周期的暗盘净头寸序列（兼容旧 Stockgrid 接口）
        
        Args:
            symbol: 标的代码
            periods: 周期天数列表
            
        Returns:
            {f'{period}d': [values...]} 格式，兼容 darkpool_verifier
        """
        data = self.fetch_symbol_data(symbol, window=max(periods))
        if not data or not data.get('dollar_dp_position'):
            return None

        dp_position = data['dollar_dp_position']
        result = {}
        for p in periods:
            if len(dp_position) >= p:
                result[f'{p}d'] = dp_position[-p:]
            else:
                result[f'{p}d'] = dp_position

        return result

    def detect_bottom_divergence(self, net_position_series: List[float],
                                 price_series: List[float]) -> Dict[str, Any]:
        """底背离检测：暗盘净头寸 vs 价格
        
        当价格下跌但暗盘净头寸上升时 → 机构在底部吸筹（底背离信号）

        Args:
            net_position_series: 暗盘净头寸序列
            price_series: 价格序列
            
        Returns:
            {divergence, slope_20d, slope_60d, golden_cross, ...}
        """
        if len(net_position_series) < 60 or len(price_series) < 60:
            return {'divergence': False, 'slope_20d': 0, 'slope_60d': 0, 'golden_cross': False}

        pos_20 = net_position_series[-20:]
        pos_60 = net_position_series[-60:]
        price_60 = price_series[-60:]

        slope_20d = float(np.polyfit(range(20), pos_20, 1)[0])
        slope_60d = float(np.polyfit(range(60), pos_60, 1)[0])
        price_slope = float(np.polyfit(range(60), price_60, 1)[0])

        golden_cross = slope_20d > 0 and slope_60d > 0
        divergence = (price_slope < 0 and slope_20d > 0) or golden_cross

        return {
            'divergence': divergence,
            'slope_20d': slope_20d,
            'slope_60d': slope_60d,
            'price_trend': 'down' if price_slope < 0 else 'up',
            'golden_cross': golden_cross,
        }

    def get_latest_short_metrics(self, symbol: str = 'SPY') -> Dict[str, Any]:
        """获取最新卖空指标"""
        data = self.fetch_symbol_data(symbol, window=5)
        if not data:
            return {}
        return {
            'latest_short_pct': data.get('short_volume_pct', [0])[-1] if data.get('short_volume_pct') else 0,
            'latest_short_volume': data.get('short_volume', [0])[-1] if data.get('short_volume') else 0,
        }

def create_axlfi_fetcher() -> AxlfiFetcher:
    return AxlfiFetcher()
