"""
多源共振监控系统 - DBMF ETF动量监控获取器

该模块负责从Yahoo Finance获取DBMF ETF（Managed Futures策略影子基金）的实时价格，
用于监控量化趋势基金的日内反转信号。

主要功能:
- 获取DBMF实时价格
- 计算5日移动平均线(MA5)
- 检测日内探底后收盘价站上MA5且涨幅>2%的反转信号

DBMF逻辑:
- DBMF是CTA趋势跟踪策略的代表性ETF
- 当市场恐慌下跌时，DBMF通常会跟随下跌
- 若DBMF日内探底后强劲反弹并收复MA5，表明量化空头动能枯竭

v2 变更: 从 raw Yahoo v8 API (429) 迁移到 yfinance.Ticker
"""

import numpy as np
from typing import Optional, List
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from utils.logger import getLogger
from utils.exceptions import DataFetchError
from config.settings import Config

logger = getLogger('dbmf_fetcher')

# 延迟导入，避免 yfinance 初始化打乱日志
_yf = None


def _get_yf():
    global _yf
    if _yf is None:
        import yfinance as _yf_mod
        _yf = _yf_mod
    return _yf


class DBMFFetcher:
    """DBMF ETF动量监控获取器 (yfinance 后端)

    通过 yfinance 获取 DBMF ETF 的实时价格和历史数据，
    用于判断量化趋势基金是否出现底部反转信号。

    对比旧版 raw Yahoo v8 API:
    - 旧版: requests.get + crumb/cookie → 频繁 429 rate limit
    - 新版: yfinance.Ticker → 自动处理 cookie/crumb/重试
    """

    SYMBOL = "DBMF"

    def __init__(self):
        self._ticker = None
        logger.info(f"DBMFFetcher初始化完成 (live mode, backend=yfinance)")

    def _get_ticker(self):
        """懒加载 yfinance Ticker"""
        if self._ticker is None:
            yf = _get_yf()
            self._ticker = yf.Ticker(self.SYMBOL)
        return self._ticker

    def get_dbmf_intraday_price(self) -> Optional[float]:
        """获取DBMF ETF实时价格

        Returns:
            float: DBMF实时价格，失败时返回None
        """
        try:
            ticker = self._get_ticker()
            info = ticker.info

            # 优先 regularMarketPrice，其次 currentPrice，最后 fast_info
            price = (info.get('regularMarketPrice')
                     or info.get('currentPrice')
                     or info.get('previousClose'))

            if price is None:
                # 降级到 history
                hist = ticker.history(period='1d')
                if not hist.empty and 'Close' in hist.columns:
                    price = float(hist['Close'].iloc[-1])

            if price is None:
                logger.error("无法获取DBMF价格（所有路径均失败）")
                return None

            result = float(price)
            logger.debug(f"DBMF实时价格: ${result:.2f}")
            return result

        except Exception as e:
            logger.error(f"获取DBMF价格失败: {e}")
            return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((Exception,)),
        reraise=True,
    )
    def get_dbmf_historical_prices(self, period: str = '5d') -> Optional[List[float]]:
        """获取DBMF历史收盘价序列

        Args:
            period: 时间周期，如 '5d', '1mo', '3mo'

        Returns:
            list[float]: 收盘价列表（按时间顺序），失败时返回None
        """
        try:
            ticker = self._get_ticker()
            hist = ticker.history(period=period)

            if hist.empty or 'Close' not in hist.columns:
                logger.error(f"DBMF历史数据为空 (period={period})")
                return None

            prices = [float(v) for v in hist['Close'].tolist() if v is not None]
            if not prices:
                logger.error("没有有效的DBMF历史价格")
                return None

            logger.debug(f"DBMF历史价格: {len(prices)}点 (period={period})")
            return prices

        except Exception as e:
            logger.error(f"获取DBMF历史价格失败: {e}", exc_info=True)
            return None

    def check_ma5_recovery(
        self,
        current_price: float,
        historical_prices: List[float],
    ) -> Optional[bool]:
        """检测DBMF是否收复5日均线且涨幅>2%

        Args:
            current_price: 当前价格
            historical_prices: 历史收盘价列表（至少5个）

        Returns:
            True/False/None
        """
        try:
            if not historical_prices or len(historical_prices) < 5:
                logger.error(f"历史价格不足，需≥5，实际{len(historical_prices) if historical_prices else 0}")
                return None

            last_5 = historical_prices[-5:]
            ma5 = float(np.mean(last_5))
            yesterday_close = last_5[-1]

            if yesterday_close == 0:
                logger.error("昨日收盘价=0，无法计算涨幅")
                return None

            gain_pct = ((current_price - yesterday_close) / yesterday_close) * 100
            recovery = current_price > ma5 and gain_pct > 2.0

            logger.info(
                f"DBMF MA5: 现价${current_price:.2f} MA5=${ma5:.2f} "
                f"涨幅={gain_pct:.2f}% → {'✅ 收复' if recovery else '❌ 未收复'}"
            )

            if recovery:
                logger.warning("⚠️ DBMF收复MA5 + 涨幅>2% → 量化空头动能枯竭")

            return recovery

        except Exception as e:
            logger.error(f"MA5检测失败: {e}", exc_info=True)
            return None

def create_dbmf_fetcher() -> DBMFFetcher:
    return DBMFFetcher()
