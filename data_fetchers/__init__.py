"""
多源共振监控系统 - 数据抓取模块

该模块负责从多个数据源获取市场数据，包括：
- Tradier API (期权链、暗盘数据)
- Yahoo Finance (VIX期货、DBMF ETF)
- CCXT (加密货币交易所数据)
- SqueezeMetrics API (DIX/GEX指标)
- ChartExchange (场外卖空比率)
- Stockgrid (暗盘净头寸)

主要类:
    TradierFetcher: Tradier期权链数据获取器
    YahooFinanceFetcher: Yahoo Finance VIX期货获取器
    CCXTFetcher: CCXT加密数据获取器
    SqueezeMetricsFetcher: SqueezeMetrics DIX获取器
    ChartExchangeFetcher: ChartExchange卖空比率解析器
    StockgridFetcher: Stockgrid暗盘净头寸爬虫
    DBMFFetcher: DBMF ETF动量监控获取器
"""

from data_fetchers.tradier_fetcher import TradierFetcher, create_tradier_fetcher
from data_fetchers.yahoo_finance_fetcher import YahooFinanceFetcher, create_yahoo_finance_fetcher
from data_fetchers.ccxt_fetcher import CCXTFetcher, create_ccxt_fetcher
from data_fetchers.squeezemetrics_fetcher import SqueezeMetricsFetcher, create_squeezemetrics_fetcher
from data_fetchers.chartexchange_fetcher import ChartExchangeFetcher, create_chartexchange_fetcher
from data_fetchers.stockgrid_fetcher import StockgridFetcher, create_stockgrid_fetcher
from data_fetchers.dbmf_fetcher import DBMFFetcher, create_dbmf_fetcher

__all__ = [
    'TradierFetcher',
    'create_tradier_fetcher',
    'YahooFinanceFetcher',
    'create_yahoo_finance_fetcher',
    'CCXTFetcher',
    'create_ccxt_fetcher',
    'SqueezeMetricsFetcher',
    'create_squeezemetrics_fetcher',
    'ChartExchangeFetcher',
    'create_chartexchange_fetcher',
    'StockgridFetcher',
    'create_stockgrid_fetcher',
    'DBMFFetcher',
    'create_dbmf_fetcher',
]
