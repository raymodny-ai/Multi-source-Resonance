"""
多源共振监控系统 - 数据抓取模块

该模块负责从多个数据源获取市场数据，包括：
- Tradier API (期权链数据, 支持沙箱免费模式)
- Yahoo Finance (VIX期货、DBMF ETF)
- Coinglass API (全网加密衍生品聚合数据, 已弃用, 保留兼容)
- Hyperliquid DEX (去中心化衍生品, 完全免费, 首选)
- CCData API (CEX衍生品, Free Tier, 降级备选)
- SqueezeMetrics CSV (DIX/GEX指标, 免费公开)
- FINRA 官方短卖文件 (管道分隔文件降级备选)
- yfinance 做空数据 (shortPercentOfFloat/shortRatio/sharesShort, 免费首选)
- AXLFI 公开API (暗盘净头寸, 替代Stockgrid)

主要类:
    TradierFetcher: Tradier期权链数据获取器
    YahooFinanceFetcher: Yahoo Finance VIX期货获取器
    CoinglassFetcher: Coinglass全网加密衍生品获取器 (已弃用)
    HyperliquidFetcher: Hyperliquid DEX 衍生品获取器 (首选, 免费)
    CCDataFetcher: CCData CEX 衍生品获取器 (降级备选)
    SqueezeMetricsFetcher: SqueezeMetrics DIX/GEX获取器
    FINRAFetcher: FINRA官方场外卖空数据获取器 (降级备选)
    StockgridFetcher: Stockgrid暗盘净头寸爬虫 (已弃用)
    DBMFFetcher: DBMF ETF动量监控获取器
"""

from data_fetchers.tradier_fetcher import TradierFetcher, create_tradier_fetcher
from data_fetchers.yahoo_finance_fetcher import YahooFinanceFetcher, create_yahoo_finance_fetcher
from data_fetchers.coinglass_fetcher import CoinglassFetcher, create_coinglass_fetcher
from data_fetchers.hyperliquid_fetcher import HyperliquidFetcher, create_hyperliquid_fetcher
from data_fetchers.ccdata_fetcher import CCDataFetcher, create_ccdata_fetcher
from data_fetchers.squeezemetrics_fetcher import SqueezeMetricsFetcher, create_squeezemetrics_fetcher
from data_fetchers.finra_fetcher import FINRAFetcher, create_finra_fetcher
from data_fetchers.stockgrid_fetcher import StockgridFetcher, create_stockgrid_fetcher
from data_fetchers.dbmf_fetcher import DBMFFetcher, create_dbmf_fetcher
from data_fetchers.gexmetrix_fetcher import GEXMetrixFetcher, create_gexmetrix_fetcher
from data_fetchers.batch_loader import (
    BatchDataLoader,
    ArchiveManager,
    load_daily_snapshot,
    init_data_structure,
)

__all__ = [
    'TradierFetcher',
    'create_tradier_fetcher',
    'YahooFinanceFetcher',
    'create_yahoo_finance_fetcher',
    'CoinglassFetcher',
    'create_coinglass_fetcher',
    'HyperliquidFetcher',
    'create_hyperliquid_fetcher',
    'CCDataFetcher',
    'create_ccdata_fetcher',
    'SqueezeMetricsFetcher',
    'create_squeezemetrics_fetcher',
    'FINRAFetcher',
    'create_finra_fetcher',
    'StockgridFetcher',
    'create_stockgrid_fetcher',
    'DBMFFetcher',
    'create_dbmf_fetcher',
    'GEXMetrixFetcher',
    'create_gexmetrix_fetcher',
    # P2-2: 批量数据框架
    'BatchDataLoader',
    'ArchiveManager',
    'load_daily_snapshot',
    'init_data_structure',
]
