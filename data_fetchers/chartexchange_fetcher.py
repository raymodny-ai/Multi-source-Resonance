"""
多源共振监控系统 - ChartExchange场外卖空比率解析器

该模块负责从ChartExchange网站抓取SPY/QQQ的场外卖空成交量数据。
基于做市商对冲原理，Off-Exchange Short Volume %的大幅拉高表明机构在悄悄左侧接盘。

主要功能:
- 抓取场外卖空成交量和总成交量
- 计算Off-Exchange Short Ratio百分比
- 检测连续2日卖空比>45%的信号
- 集成tenacity重试机制应对403/429错误

技术实现:
- 使用requests + 伪装Headers (User-Agent轮换、Referer)
- 尝试访问底层JSON API端点（需通过浏览器F12抓包确认真实URL）
- 提供Mock模式用于测试

注意: 由于无法实际抓包，代码中标记了需要手动确认的API端点TODO注释
"""

import requests
from requests.exceptions import Timeout, ConnectionError, HTTPError
import random
from typing import Optional, Dict, Any, List
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from utils.logger import getLogger
from utils.exceptions import DataFetchError
from config.settings import Config

logger = getLogger('chartexchange_fetcher')


class ChartExchangeFetcher:
    """ChartExchange场外卖空比率解析器
    
    通过HTTP请求抓取ChartExchange网站的场外卖空成交量数据。
    Off-Exchange Short Volume % > 45% 连续2日视为机构被动吸筹信号。
    
    Attributes:
        session: requests会话对象（支持连接池和Cookie持久化）
        base_url: ChartExchange网站基础URL
        mock_mode: Mock模式开关
        user_agents: User-Agent轮换列表
    """
    
    # TODO: 需要通过浏览器F12 Network面板抓包确认真实的API端点
    # 以下为推测的端点，实际使用时需要根据抓包结果修改
    API_ENDPOINTS = {
        'short_volume': '/api/v1/shortvolume/{symbol}',  # 待确认
        'daily_data': '/data/daily/{symbol}/shortvol',   # 待确认
    }
    
    def __init__(self, mock_mode: bool = False):
        """初始化ChartExchange数据获取器
        
        Args:
            mock_mode: Mock模式开关，用于无网络连接或API不可用时的测试
        """
        self.mock_mode = mock_mode
        self.base_url = "https://chartexchange.com"
        
        # 创建会话对象
        self.session = requests.Session()
        
        # User-Agent轮换列表（模拟不同浏览器）
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
        ]
        
        # 设置默认请求头
        self._set_random_headers()
        
        logger.info(f"ChartExchangeFetcher初始化完成 (mock_mode={mock_mode})")
    
    def _set_random_headers(self):
        """设置随机请求头以规避反爬检测"""
        ua = random.choice(self.user_agents)
        self.session.headers.update({
            'User-Agent': ua,
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': f'{self.base_url}/charts/',
            'Origin': self.base_url,
            'Connection': 'keep-alive',
        })
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=5, max=45),
        retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError)),
        reraise=True
    )
    def fetch_short_volume_data(self, symbol: str = 'SPY') -> Optional[Dict[str, Any]]:
        """抓取场外卖空成交量原始数据
        
        从ChartExchange网站获取指定标的的场外卖空成交量数据。
        包含off_exchange_short_volume和off_exchange_total_volume字段。
        
        Args:
            symbol: 标的股票代码，如'SPY'、'QQQ'
            
        Returns:
            dict: 原始JSON数据，包含以下字段:
                - 'date': 交易日期
                - 'off_exchange_short_volume': 场外卖空成交量
                - 'off_exchange_total_volume': 场外总成交量
                - 'short_ratio': 卖空比例（自动计算）
            失败时返回None
            
        Raises:
            DataFetchError: API请求失败时抛出（经重试后仍失败）
            
        Examples:
            >>> fetcher = ChartExchangeFetcher()
            >>> data = fetcher.fetch_short_volume_data('SPY')
            >>> if data:
            ...     print(f"卖空比例: {data['short_ratio']:.2f}%")
        """
        if self.mock_mode:
            logger.warning(f"Mock模式: 返回模拟{symbol}卖空数据")
            return self._get_mock_short_volume_data(symbol)
        
        # TODO: 需要手动确认真实的API端点
        # 策略A: 尝试JSON API端点
        api_url_candidates = [
            f"{self.base_url}/api/v1/shortvolume/{symbol}",
            f"{self.base_url}/data/daily/{symbol}/shortvol",
            f"{self.base_url}/api/chart/{symbol}/short-volume",
        ]
        
        last_error = None
        
        for url in api_url_candidates:
            try:
                logger.info(f"尝试请求ChartExchange API: {url}")
                
                # 每次请求前更换User-Agent
                self._set_random_headers()
                
                response = self.session.get(
                    url,
                    timeout=Config.REQUEST_TIMEOUT
                )
                
                # 处理403/429错误
                if response.status_code == 403:
                    logger.warning(f"403 Forbidden，可能需要验证码或IP被封")
                    continue
                elif response.status_code == 429:
                    logger.warning(f"429 Too Many Requests，触发频率限制")
                    continue
                
                response.raise_for_status()
                
                # 尝试解析JSON
                try:
                    data = response.json()
                    logger.info(f"成功获取{symbol}卖空数据 (JSON格式)")
                    return data
                except ValueError:
                    logger.warning(f"响应不是JSON格式，可能是HTML页面")
                    # 策略B: 如果API返回HTML，需要解析DOM（此处简化处理）
                    continue
                    
            except Timeout as e:
                logger.warning(f"Request timeout: {url}, error: {str(e)}")
                last_error = e
                continue
            except ConnectionError as e:
                logger.warning(f"Connection error: {url}, error: {str(e)}")
                last_error = e
                continue
            except HTTPError as e:
                logger.warning(f"HTTP error ({e.response.status_code}): {url}")
                last_error = e
                continue
            except Exception as e:
                logger.warning(f"请求失败: {url}, 错误: {str(e)}")
                last_error = e
                continue
        
        # 所有候选端点均失败
        logger.error(f"所有API端点均失败，最后错误: {last_error}")
        
        # 降级策略：返回None，由调用方决定是否使用历史缓存
        raise DataFetchError(
            message=f"无法从ChartExchange获取{symbol}卖空数据，所有端点均失败",
            error_code="CHARTEXCHANGE_ALL_ENDPOINTS_FAILED",
            details={"tried_urls": api_url_candidates, "last_error": str(last_error)}
        )
    
    def calculate_off_exchange_short_ratio(self, raw_json: Dict[str, Any]) -> Optional[float]:
        """计算场外卖空比例
        
        公式: off_exchange_short_volume / off_exchange_total_volume * 100
        
        Args:
            raw_json: fetch_short_volume_data返回的原始JSON数据
            
        Returns:
            float: 卖空比例百分比（如45.8表示45.8%）
                  失败时返回None
            
        Examples:
            >>> fetcher = ChartExchangeFetcher()
            >>> data = fetcher.fetch_short_volume_data('SPY')
            >>> ratio = fetcher.calculate_off_exchange_short_ratio(data)
            >>> if ratio and ratio > 45.0:
            ...     print("⚠️ 场外卖空比例超过45%，机构吸筹信号")
        """
        try:
            if raw_json is None:
                logger.error("输入数据为None")
                return None
            
            # 尝试多种可能的字段名
            short_vol = (
                raw_json.get('off_exchange_short_volume') or
                raw_json.get('shortVolume') or
                raw_json.get('offExchangeShortVol') or
                raw_json.get('short_vol')
            )
            
            total_vol = (
                raw_json.get('off_exchange_total_volume') or
                raw_json.get('totalVolume') or
                raw_json.get('offExchangeTotalVol') or
                raw_json.get('total_vol')
            )
            
            if short_vol is None or total_vol is None:
                logger.error("缺少必要的成交量字段")
                logger.debug(f"可用字段: {list(raw_json.keys())}")
                return None
            
            short_vol = float(short_vol)
            total_vol = float(total_vol)
            
            if total_vol == 0:
                logger.error("总成交量为0，避免除零错误")
                return None
            
            ratio = (short_vol / total_vol) * 100
            
            logger.info(f"场外卖空比例: {ratio:.2f}% (short_vol={short_vol:.0f}, total_vol={total_vol:.0f})")
            
            # 记录阈值状态
            if ratio > 45.0:
                logger.warning(f"⚠️ 场外卖空比例={ratio:.2f}% 超过阈值45%，机构被动吸筹信号")
            
            return ratio
            
        except Exception as e:
            logger.error(f"计算卖空比例失败: {str(e)}", exc_info=True)
            return None
    
    def check_consecutive_days(
        self, 
        data_history: List[Dict[str, Any]], 
        threshold: float = 45.0, 
        consecutive_days: int = 2
    ) -> bool:
        """检测连续N日卖空比超过阈值
        
        检查历史数据中是否有连续consecutive_days天的卖空比例超过threshold。
        
        Args:
            data_history: 历史数据列表，每个元素包含'date'和'short_ratio'字段
                         按时间顺序排列（最新的在最后）
            threshold: 卖空比例阈值，默认45.0%
            consecutive_days: 连续天数，默认2天
            
        Returns:
            bool: True表示满足条件，False表示不满足
            
        Examples:
            >>> fetcher = ChartExchangeFetcher()
            >>> history = [
            ...     {'date': '2026-06-07', 'short_ratio': 46.5},
            ...     {'date': '2026-06-08', 'short_ratio': 47.2},
            ... ]
            >>> if fetcher.check_consecutive_days(history):
            ...     print("✅ 连续2日卖空比>45%，确认机构吸筹")
        """
        try:
            if not data_history or len(data_history) < consecutive_days:
                logger.warning(f"历史数据不足，需要至少{consecutive_days}天，当前{len(data_history)}天")
                return False
            
            # 检查最近consecutive_days天的数据
            recent_data = data_history[-consecutive_days:]
            
            for day_data in recent_data:
                ratio = day_data.get('short_ratio')
                if ratio is None or ratio <= threshold:
                    logger.info(f"不满足条件: {day_data.get('date')} 卖空比={ratio}%")
                    return False
            
            dates = [d.get('date', 'unknown') for d in recent_data]
            logger.info(f"✅ 检测到连续{consecutive_days}日卖空比>{threshold}%: {dates}")
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
        from datetime import datetime, timedelta
        
        # 模拟最近的交易日期
        today = datetime.now()
        
        # 生成合理的卖空数据（40-50%之间波动）
        total_volume = random.randint(50000000, 100000000)  # 5000万-1亿
        short_ratio = random.uniform(40.0, 50.0)
        short_volume = int(total_volume * short_ratio / 100)
        
        return {
            'date': today.strftime('%Y-%m-%d'),
            'symbol': symbol,
            'off_exchange_short_volume': short_volume,
            'off_exchange_total_volume': total_volume,
            'short_ratio': round(short_ratio, 2),
            'market': 'NYSE Arca',  # SPY在NYSE Arca交易
        }


# 便捷函数
def create_chartexchange_fetcher(mock_mode: bool = False) -> ChartExchangeFetcher:
    """创建ChartExchange数据获取器实例的工厂函数
    
    Args:
        mock_mode: 是否启用Mock模式
        
    Returns:
        ChartExchangeFetcher: 配置好的获取器实例
    """
    return ChartExchangeFetcher(mock_mode=mock_mode)
