"""
多源共振监控系统 - SqueezeMetrics DIX+GEX 数据获取器

从 SqueezeMetrics 公开 CSV 获取 DIX (暗盘指数) 和 GEX (Gamma 风险暴露)。
CSV 文件每日更新，完全免费，无需 API Key。

数据源: https://squeezemetrics.com/monitor/static/DIX.csv
格式: date,price,dix,gex  (3800+行, 自2011年起)
注意: GEX.csv 不存在 (404), GEX 数据已内嵌在 DIX.csv 中。
"""

import requests
import pandas as pd
from requests.exceptions import Timeout, ConnectionError, HTTPError
from typing import Optional, Dict, Any
from io import StringIO
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from utils.logger import getLogger
from utils.exceptions import DataFetchError
from config.settings import DataFetchConfig

logger = getLogger('squeezemetrics_fetcher')


class SqueezeMetricsFetcher:
    """SqueezeMetrics 指标获取器 (CSV 直接下载模式)

    从 DIX.csv 同时获取 DIX + GEX + SPX价格。
    DIX > 45% → 机构暗盘吸筹信号。
    GEX > 0  → 做市商多头对冲 (正Gamma, 压制波动)。
    GEX < 0  → 做市商空头对冲 (负Gamma, 放大波动)。

    优势:
    - 无需 API 密钥，完全免费
    - 3800+ 天历史数据 (2011至今)
    - CSV 格式稳定，轻量级
    """

    def __init__(self, mock_mode: bool = False):
        self.mock_mode = mock_mode
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        logger.info(f"SqueezeMetricsFetcher 初始化 (mock_mode={mock_mode})")

    # ==================== 核心方法 ====================

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=5, max=45),
        retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError)),
        reraise=True
    )
    def get_full_metrics(self) -> Optional[Dict[str, Any]]:
        """获取完整 DIX+GEX 指标 (单次 CSV 下载)

        DIX.csv 格式: date,price,dix,gex

        Returns:
            {
                'date': '2026-06-09',
                'price': 7386.65,     # SPX 收盘价
                'dix': 43.87,         # DIX 百分比 (43.87%)
                'dix_raw': 0.4387,    # DIX 原始小数
                'gex': 3131028235.51, # GEX 美元总值
            }
        """
        if self.mock_mode:
            return self._get_mock_full_metrics()

        try:
            logger.info(f"下载 SqueezeMetrics CSV: {DataFetchConfig.SQUEEZEMETRICS_CSV_URL}")
            resp = self.session.get(DataFetchConfig.SQUEEZEMETRICS_CSV_URL, timeout=15)
            resp.raise_for_status()

            df = pd.read_csv(StringIO(resp.text))
            if df.empty or 'dix' not in df.columns or 'gex' not in df.columns:
                logger.error("CSV 缺少 dix 或 gex 列")
                return None

            latest = df.iloc[-1]
            dix_raw = float(latest['dix'])
            gex_raw = float(latest['gex'])
            price   = float(latest['price'])
            date    = str(latest['date'])

            result = {
                'date': date,
                'price': price,
                'dix': round(dix_raw * 100, 2),
                'dix_raw': dix_raw,
                'gex': gex_raw,
            }

            logger.info(
                f"SQZ: {date} | SPX={price:.0f} | DIX={result['dix']:.1f}% | "
                f"GEX=${gex_raw/1e9:.2f}B"
            )

            if result['dix'] > 45:
                logger.warning(f"⚠️ DIX={result['dix']:.1f}% > 45%，机构暗盘吸筹信号")

            return result

        except Exception as e:
            logger.error(f"SQZ 获取失败: {e}", exc_info=True)
            return None

    def get_daily_dix(self) -> Optional[float]:
        """获取每日 DIX 百分比值 (兼容旧接口)"""
        if self.mock_mode:
            return self._get_mock_dix()
        data = self.get_full_metrics()
        return data['dix'] if data else None

    def get_daily_gex(self) -> Optional[float]:
        """获取每日 GEX 总值 (从 DIX.csv, GEX.csv 不存在)"""
        if self.mock_mode:
            return 2.5e9
        data = self.get_full_metrics()
        return data['gex'] if data else None

    def get_official_gex(self) -> Optional[float]:
        """官方 GEX 值 (供 α 校准, 等同于 get_daily_gex)"""
        return self.get_daily_gex()

    def get_barchart_gamma_profile(self) -> Optional[Dict[str, Any]]:
        """获取 GEX 数据 (从 DIX.csv)

        DIX.csv 只提供总 GEX 值，不提供逐行权价分布。
        因此 put_wall / flip_zone 无法从 CSV 计算。

        Returns:
            {'total_gex': float, 'timestamp': str}
        """
        if self.mock_mode:
            return self._get_mock_gamma_profile()

        data = self.get_full_metrics()
        if not data:
            return None

        return {
            'total_gex': data['gex'],
            'timestamp': data['date'],
        }

    # ==================== 历史数据 ====================

    def get_history(self, days: int = 252) -> Optional[pd.DataFrame]:
        """获取 DIX+GEX 历史 DataFrame

        Args:
            days: 获取最近 N 天 (默认252)

        Returns:
            DataFrame with columns: date, price, dix, gex
        """
        if self.mock_mode:
            import random
            from datetime import datetime, timedelta
            dates = [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(days)[::-1]]
            return pd.DataFrame({
                'date': dates,
                'price': [7000 + i*2 + random.uniform(-50,50) for i in range(days)],
                'dix': [random.uniform(0.35, 0.50) for _ in range(days)],
                'gex': [3e9 + i*1e7 + random.uniform(-5e8,5e8) for i in range(days)],
            })

        try:
            resp = self.session.get(DataFetchConfig.SQUEEZEMETRICS_CSV_URL, timeout=15)
            resp.raise_for_status()
            df = pd.read_csv(StringIO(resp.text))
            return df.tail(days)
        except Exception as e:
            logger.error(f"获取历史数据失败: {e}")
            return None

    # ==================== Mock ====================
    def _get_mock_full_metrics(self) -> Dict[str, Any]:
        import random
        from datetime import date
        return {
            'date': str(date.today()),
            'price': round(random.uniform(7000, 7500), 2),
            'dix': round(random.uniform(38, 52), 2),
            'dix_raw': round(random.uniform(0.38, 0.52), 4),
            'gex': random.uniform(2e9, 5e9),
        }

    def _get_mock_dix(self) -> float:
        import random
        return round(random.uniform(40.0, 55.0), 2)

    def _get_mock_gamma_profile(self) -> Dict[str, Any]:
        import random
        return {
            'total_gex': random.uniform(2e9, 5e9),
            'timestamp': 'mock',
        }


def create_squeezemetrics_fetcher(mock_mode: bool = False) -> SqueezeMetricsFetcher:
    return SqueezeMetricsFetcher(mock_mode=mock_mode)
