"""
多源共振监控系统 - Yahoo Finance 数据获取器

该模块负责获取VIX现货/期货价格和做空数据，
用于计算波动率期限结构、市场恐慌程度和量化选股过滤。

主要功能:
- 获取VIX现货指数价格 (^VIX) — vix_utils (CBOE 官方数据)
- 获取VIX近月和次月期货价格 (VX1/VX2) — vix_utils (CBOE 官方数据)
- 计算VIX期限结构比率 (VX1/VX2)
- 判断Contango/Backwardation市场状态
- 获取做空数据 (shortPercentOfFloat / shortRatio / sharesShort) — yfinance库

数据源迁移:
  v2.0: Yahoo Finance → CBOE vix_utils (2024年起 Yahoo 已弃用 VIX 期货符号)
  vix_utils 专为 VIX 回测设计，直接从 CBOE 官网下载历史 CSV 并清洗为 DataFrame
  提供 2004 年至今的全曲线期限结构 & 30天常量到期日连续曲线

做空数据: yfinance.Ticker(symbol).info (免费, 无API Key, 覆盖美股全量标的)
"""

import requests
from requests.exceptions import Timeout, ConnectionError, HTTPError
from typing import Optional, Dict, Any

import pandas as pd

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from utils.logger import getLogger
from utils.exceptions import DataFetchError
from config.settings import Config

try:
    import yfinance as yf
    _YFINANCE_AVAILABLE = True
except ImportError:
    _YFINANCE_AVAILABLE = False
    yf = None

try:
    import vix_utils
    _VIX_UTILS_AVAILABLE = True
except ImportError:
    _VIX_UTILS_AVAILABLE = False

logger = getLogger('yahoo_finance_fetcher')


class YahooFinanceFetcher:
    """VIX + 做空数据获取器
    
    VIX 数据: 通过 vix_utils (CBOE 官方 CSV) 获取
    做空数据: 通过 yfinance 获取
    
    Attributes:
        _vix_cache: VIX DataFrame 缓存 (避免重复下载)
    """
    
    # VIX 数据缓存 (类级别共享，避免每次实例化都重新下载)
    _futures_cache: Optional[Any] = None
    _spot_cache: Optional[Any] = None
    _cache_ts: float = 0.0
    _CACHE_TTL_SEC: float = 300.0  # 5分钟缓存有效期

    def __init__(self):
        """初始化数据获取器"""
        logger.info(f"YahooFinanceFetcher初始化完成 (live mode, vix_utils={'✓' if _VIX_UTILS_AVAILABLE else '✗'})")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError)),
        reraise=True
    )
    def get_vix_spot(self) -> Optional[float]:
        """获取VIX现货指数价格 — vix_utils (CBOE 官方数据)
        
        从 CBOE 历史波动率指数 CSV 中提取最新 VIX 收盘价。
        vix_utils 自动完成下载→清洗→DataFrame 全流程。
        
        Returns:
            float: VIX现货价格，失败时返回None
        """
        try:
            spot_df = self._load_vix_spot_data()
            if spot_df is None:
                return None
            vix_rows = spot_df[spot_df['Symbol'] == 'VIX']
            if len(vix_rows) == 0:
                logger.error("vix_utils 返回的现货数据中未找到 VIX 符号")
                return None
            latest = vix_rows.iloc[-1]
            price = float(latest['Close'])
            logger.debug(f"vix_utils: VIX 现货 = {price:.2f} (日期: {latest['Trade Date']})")
            return price
        except Exception as e:
            logger.error(f"vix_utils VIX 现货获取失败: {e}", exc_info=True)
            return None
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError)),
        reraise=True
    )
    def get_vix_futures(self, contract: str = 'VX1') -> Optional[float]:
        """获取VIX期货合约价格 — vix_utils (CBOE 官方数据)
        
        从 CBOE VIX 期货历史 CSV 中提取近月/次月结算价。
        vix_utils 自动下载多月份期货合约并拼接到统一 DataFrame。
        
        Args:
            contract: 期货合约标识
                - 'VX1': 近月期货 (Tenor_Days 最小)
                - 'VX2': 次月期货 (Tenor_Days 次小)
                
        Returns:
            float: 期货结算价 (Settle)，失败时返回None
        """
        try:
            futures_df = self._load_vix_futures_data()
            if futures_df is None:
                return None

            latest_date = futures_df['Trade Date'].max()
            today_fs = futures_df[futures_df['Trade Date'] == latest_date]

            # 去重：同一合约名可能有多个 Tenor（周度+月度），只保留 Tenor 最小的那条
            if 'Futures' in today_fs.columns:
                today_fs = today_fs.loc[today_fs.groupby('Futures')['Tenor_Days'].idxmin()]

            # 按到期日升序排列
            today_fs = today_fs.sort_values('Tenor_Days')

            if len(today_fs) < 2:
                logger.error(f"vix_utils: 最新日期 ({latest_date.date()}) 期货合约不足2个")
                return None

            # VX1 = 最近月 (tenor 最小), VX2 = 次月 (tenor 次小)
            idx = 0 if contract == 'VX1' else 1
            row = today_fs.iloc[idx]
            price = float(row['Settle']) if not pd.isna(row['Settle']) else float(row['Close'])
            logger.debug(
                f"vix_utils: {contract} = {price:.2f} "
                f"({row['Futures']}, Tenor={row['Tenor_Days']}天, 日期={latest_date.date()})"
            )
            return price

        except Exception as e:
            logger.error(f"vix_utils {contract} 获取失败: {e}", exc_info=True)
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
    # ================================================================
    # VIX 数据加载 — vix_utils 缓存层
    # ================================================================

    @classmethod
    def _load_vix_futures_data(cls):
        """加载 VIX 期货期限结构 DataFrame (带缓存)
        
        缓存有效期 5 分钟，避免每次调用都重新下载 CBOE CSV。
        """
        import time as _time
        if (
            cls._futures_cache is not None
            and (_time.time() - cls._cache_ts) < cls._CACHE_TTL_SEC
        ):
            return cls._futures_cache

        if not _VIX_UTILS_AVAILABLE:
            logger.error("vix_utils 未安装，无法获取 VIX 期货数据。pip install vix_utils")
            return None

        try:
            logger.info("vix_utils: 加载 VIX 期货期限结构 (CBOE CSV)...")
            cls._futures_cache = vix_utils.load_vix_term_structure()
            cls._cache_ts = _time.time()
            logger.info(f"vix_utils: 期货数据加载完成 ({len(cls._futures_cache)} 行)")
            return cls._futures_cache
        except Exception as e:
            logger.error(f"vix_utils 期货数据加载失败: {e}", exc_info=True)
            return None

    @classmethod
    def _load_vix_spot_data(cls):
        """加载 VIX 现货历史数据 DataFrame (带缓存)"""
        import time as _time
        if (
            cls._spot_cache is not None
            and (_time.time() - cls._cache_ts) < cls._CACHE_TTL_SEC
        ):
            return cls._spot_cache

        if not _VIX_UTILS_AVAILABLE:
            logger.error("vix_utils 未安装，无法获取 VIX 现货数据。pip install vix_utils")
            return None

        try:
            logger.info("vix_utils: 加载 VIX 现货指数历史 (CBOE CSV)...")
            cls._spot_cache = vix_utils.get_vix_index_histories()
            cls._cache_ts = _time.time()
            logger.info(f"vix_utils: 现货数据加载完成 ({len(cls._spot_cache)} 行)")
            return cls._spot_cache
        except Exception as e:
            logger.error(f"vix_utils 现货数据加载失败: {e}", exc_info=True)
            return None

    @classmethod
    def invalidate_vix_cache(cls) -> None:
        """强制清除 VIX 缓存 (手动采集时使用)"""
        cls._futures_cache = None
        cls._spot_cache = None
        cls._cache_ts = 0.0
        logger.info("vix_utils: VIX 缓存已手动清除")

    # ================================================================
    # 做空数据 (yfinance — 替代已删除的 FMP)
    # ================================================================
    
    def get_short_interest(self, symbol: str = 'SPY') -> Optional[Dict[str, Any]]:
        """获取标的做空数据 (yfinance Ticker.info)
        
        使用 yfinance 库直接从 Yahoo Finance 提取做空指标:
        - shortPercentOfFloat: 做空股数占流通股比例 (%)
        - shortRatio: 做空比率 (days to cover)
        - sharesShort: 做空总股数
        - priorMonthShort: 上个月做空股数
        
        优势: 免费, 无需API Key, 覆盖美股全量标的, 接口轻量。
        替代已删除的 FMP (Financial Modeling Prep) 短卖数据获取。
        
        Args:
            symbol: 标的股票代码, 如 'SPY', 'AAPL', 'TSLA'
        
        Returns:
            dict: {
                'symbol': str,
                'short_pct_float': float | None,  # 做空占流通股比例 (%)
                'short_ratio': float | None,       # 做空比率 (天)
                'shares_short': int | None,        # 做空总股数
                'date': str | None,                # 数据日期
            }
            yfinance 不可用或获取失败时返回 None
        """
        if not _YFINANCE_AVAILABLE:
            logger.warning("yfinance 库未安装, 无法获取做空数据")
            return None
        
        try:
            logger.info(f"获取 {symbol} 做空数据 (yfinance)")
            ticker = yf.Ticker(symbol.upper())
            info = ticker.info
            
            if not info or info.get('regularMarketPrice') is None:
                logger.warning(f"{symbol} yfinance info 为空或无效")
                return None
            
            short_pct = info.get('shortPercentOfFloat')
            short_ratio = info.get('shortRatio')
            shares_short = info.get('sharesShort')
            date_short = info.get('dateShortInterest')
            
            # 至少有一个非None字段才返回
            if short_pct is None and shares_short is None:
                logger.debug(f"{symbol} 无做空数据 (可能为ETF或数据延迟)")
                return None
            
            result = {
                'symbol': symbol.upper(),
                'short_pct_float': float(short_pct) if short_pct is not None else None,
                'short_ratio': float(short_ratio) if short_ratio is not None else None,
                'shares_short': int(shares_short) if shares_short is not None else None,
                'date': str(date_short) if date_short else None,
            }
            
            logger.info(
                f"{symbol} 做空数据: short%={result['short_pct_float']}, "
                f"ratio={result['short_ratio']}d, shares={result['shares_short']}"
            )
            return result
            
        except Exception as e:
            logger.error(f"{symbol} 做空数据获取失败: {e}")
            return None


# 便捷函数
def create_yahoo_finance_fetcher() -> YahooFinanceFetcher:
    """创建Yahoo Finance数据获取器实例的工厂函数"""
    return YahooFinanceFetcher()
