"""
多源共振监控系统 - Tradier期权链数据获取器

该模块负责从Tradier API获取美股期权链原始数据，并解析为标准化的DataFrame格式。
支持自动重试机制和完整的错误处理。

主要功能:
- 获取指定标的和到期日的期权链数据
- 解析CALL/PUT期权的关键字段（行权价、价格、成交量等）
- 集成tenacity指数退避重试机制
- 支持免费Sandbox模式 (延迟15分钟,无需付费账户)

API文档: https://documentation.tradier.com/brokerage-api/markets/get-options-chains
沙箱注册: https://developer.tradier.com/user/sign_up
"""

import pandas as pd
import requests
from requests.exceptions import Timeout, ConnectionError, HTTPError
from typing import Optional, Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from utils.logger import getLogger
from utils.exceptions import DataFetchError
from config.settings import Config

logger = getLogger('tradier_fetcher')


class TradierFetcher:
    """Tradier期权链数据获取器
    
    通过Tradier Brokerage API获取美股期权链数据，支持盘中高频调用。
    主要用于计算本地Gamma敞口(GEX)和识别Put Wall关键支撑位。
    
    支持两种运行模式:
    - 生产模式: 真实账户API密钥,实时数据 (TRADIER_API_KEY)
    - 沙箱模式: 免费注册,延迟15分钟数据 (TRADIER_SANDBOX_MODE=true)
    
    Attributes:
        api_key: Tradier API密钥或沙箱令牌
        account_id: Tradier账户ID
        base_url: API基础URL (根据模式自动切换生产/沙箱端点)
        headers: HTTP请求头，包含认证信息
        sandbox_mode: 沙箱模式开关，True时使用免费沙箱端点
    """
    
    def __init__(self, api_key: Optional[str] = None, account_id: Optional[str] = None, 
                 use_sandbox: Optional[bool] = None):
        """初始化Tradier数据获取器
        
        Args:
            api_key: Tradier API密钥，默认从Config读取
            account_id: Tradier账户ID，默认从Config读取
            use_sandbox: 沙箱模式开关,None时自动从Config.TRADIER_SANDBOX_MODE读取
        """
        self.sandbox_mode = use_sandbox if use_sandbox is not None else Config.TRADIER_SANDBOX_MODE
        
        if self.sandbox_mode:
            # 沙箱模式: 使用免费sandbox端点 + 沙箱令牌
            self.api_key = api_key or Config.TRADIER_SANDBOX_TOKEN
            self.account_id = account_id or Config.TRADIER_ACCOUNT_ID or 'sandbox'
            self.base_url = Config.TRADIER_SANDBOX_URL
        else:
            # 生产模式: 使用真实API端点
            self.api_key = api_key or Config.TRADIER_API_KEY
            self.account_id = account_id or Config.TRADIER_ACCOUNT_ID
            self.base_url = Config.TRADIER_BASE_URL
        
        # 构建HTTP请求头
        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Accept': 'application/json'
        }
        
        mode_desc = 'sandbox' if self.sandbox_mode else 'production'
        logger.info(f"TradierFetcher初始化完成 (mode={mode_desc}, base_url={self.base_url})")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=5, max=45),
        retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError)),
        reraise=True
    )
    def get_option_chain(self, symbol: str, expiration_date: str) -> Optional[Dict[str, Any]]:
        """获取期权链原始JSON数据
        
        从Tradier API拉取指定标的和到期日的完整期权链数据。
        包含所有CALL和PUT期权的详细报价信息。
        
        Args:
            symbol: 标的股票代码，如'SPY', 'AAPL'
            expiration_date: 期权到期日，格式'YYYY-MM-DD'
            
        Returns:
            dict: 原始API响应JSON数据，失败时返回None
            
        Raises:
            DataFetchError: API请求失败时抛出（经重试后仍失败）
            
        Examples:
            >>> fetcher = TradierFetcher()
            >>> data = fetcher.get_option_chain('SPY', '2026-06-19')
            >>> if data:
            ...     print(f"获取到 {len(data['options']['option'])} 条期权记录")
        """
        url = f"{self.base_url}/markets/options/chains"
        params = {
            'symbol': symbol,
            'expiration': expiration_date
        }
        
        try:
            logger.info(f"请求Tradier API: symbol={symbol}, expiration={expiration_date}")
            response = requests.get(
                url, 
                headers=self.headers, 
                params=params,
                timeout=Config.REQUEST_TIMEOUT
            )
            response.raise_for_status()
            
            data = response.json()
            logger.debug(f"Successfully fetched option chain for {symbol}: {len(data.get('options', {}).get('option', []))} records")
            return data
            
        except Timeout as e:
            logger.error(f"Request timeout for {symbol}: {e}")
            return None
        except ConnectionError as e:
            logger.error(f"Connection error for {symbol}: {e}")
            return None
        except HTTPError as e:
            if response.status_code == 429:
                logger.warning(f"Rate limit exceeded for {symbol}, will retry")
            elif response.status_code == 403:
                logger.error(f"Access forbidden for {symbol}, check API key")
            else:
                logger.error(f"HTTP error {response.status_code} for {symbol}: {e}")
            return None
        except ValueError as e:
            logger.error(f"JSON decode error for {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching option chain for {symbol}: {e}", exc_info=True)
            return None
    
    def parse_option_chain(self, raw_data: Dict[str, Any]) -> Optional[pd.DataFrame]:
        """解析并标准化期权链数据为DataFrame
        
        将Tradier API返回的嵌套JSON结构转换为扁平化的DataFrame，
        提取关键字段并进行数据类型转换。
        
        Args:
            raw_data: get_option_chain返回的原始JSON数据
            
        Returns:
            pd.DataFrame: 标准化的期权链数据，包含以下列:
                - symbol: 期权合约符号
                - type: 期权类型 ('call' 或 'put')
                - strike: 行权价
                - expiry: 到期日
                - bid: 买一价
                - ask: 卖一价
                - last_price: 最新成交价
                - volume: 成交量
                - open_interest: 未平仓合约数
                - underlying: 标的价格
            失败时返回None
            
        Examples:
            >>> raw_data = fetcher.get_option_chain('SPY', '2026-06-19')
            >>> df = fetcher.parse_option_chain(raw_data)
            >>> print(df[['symbol', 'type', 'strike', 'volume']].head())
        """
        if raw_data is None:
            logger.error("输入数据为None，无法解析")
            return None
        
        try:
            options_list = raw_data.get('options', {}).get('option', [])
            
            if not options_list:
                logger.warning("期权链数据为空")
                return pd.DataFrame()
            
            # 提取关键字段
            records = []
            for opt in options_list:
                record = {
                    'symbol': opt.get('symbol', ''),
                    'type': opt.get('type', '').lower(),  # 'call' or 'put'
                    'strike': float(opt.get('strike', 0)),
                    'expiry': opt.get('expiration_date', ''),
                    'bid': float(opt.get('bid', 0)),
                    'ask': float(opt.get('ask', 0)),
                    'last_price': float(opt.get('last', 0)),
                    'volume': int(opt.get('volume', 0)),
                    'open_interest': int(opt.get('open_interest', 0)),
                    'underlying': float(opt.get('underlying', 0)),
                    'greeks_delta': float(opt.get('greeks', {}).get('delta', 0)),
                    'greeks_gamma': float(opt.get('greeks', {}).get('gamma', 0)),
                    'greeks_theta': float(opt.get('greeks', {}).get('theta', 0)),
                    'greeks_vega': float(opt.get('greeks', {}).get('vega', 0)),
                    'greeks_rho': float(opt.get('greeks', {}).get('rho', 0)),
                    'greeks_iv': float(opt.get('greeks', {}).get('iv', 0)),
                }
                records.append(record)
            
            df = pd.DataFrame(records)
            
            # 数据验证
            if df.empty:
                logger.warning("解析后的DataFrame为空")
                return df
            
            # 确保数值列的类型正确
            numeric_cols = ['strike', 'bid', 'ask', 'last_price', 'volume', 'open_interest', 'underlying']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            logger.info(f"成功解析期权链: {len(df)} 条记录, CALL={len(df[df['type']=='call'])}, PUT={len(df[df['type']=='put'])}")
            return df
            
        except Exception as e:
            logger.error(f"解析期权链数据失败: {str(e)}", exc_info=True)
            return None
    
# 便捷函数
def create_tradier_fetcher(use_sandbox: Optional[bool] = None) -> TradierFetcher:
    """创建Tradier数据获取器实例的工厂函数
    
    Args:
        use_sandbox: 是否启用沙箱模式,None时自动从Config读取
        
    Returns:
        TradierFetcher: 配置好的获取器实例
    """
    return TradierFetcher(use_sandbox=use_sandbox)
