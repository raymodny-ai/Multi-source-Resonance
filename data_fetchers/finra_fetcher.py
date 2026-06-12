"""
多源共振监控系统 - FINRA 官方场外卖空数据获取器

该模块从 FINRA 官网直接下载每日 Consolidated Short Sale Volume 公开文件，
提取指定标的的短卖/总成交量数据并计算场外卖空比率(st/rt)。

主要功能:
- 从 FINRA CDN 下载每日管道分隔文件 (CNMSshvolYYYYMMDD.txt)
- 解析 ShortVolume / TotalVolume 字段
- 计算 Off-Exchange Short Ratio (st/rt * 100)
- 检测连续N日短卖比超过阈值

数据来源: https://cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt
文件格式: Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market

优势:
- 无需API密钥，完全免费，FINRA 官方一手数据
- 比ChartExchange等第三方加工网站更权威稳定
- 每日美东16:00后更新，盘后获取即可

注意: 盘中可能无当日数据，需降级到上一交易日
"""

import requests
from requests.exceptions import Timeout, ConnectionError, HTTPError
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta, date
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from utils.logger import getLogger
from utils.exceptions import DataFetchError
from config.settings import Config, DataFetchConfig

logger = getLogger('finra_fetcher')


class FINRAFetcher:
    """FINRA 官方场外卖空数据获取器
    
    从 FINRA 官网直接下载每日 Consolidated Short Sale Volume 公开文件，
    提取指定标的的短卖/总成交量数据。st/rt > 45% 连续2日视为机构被动吸筹信号。
    
    Attributes:
        session: requests会话对象
        base_url: FINRA CDN 文件基础URL模板
    """
    
    def __init__(self):
        """初始化FINRA数据获取器"""
        self.base_url = DataFetchConfig.FINRA_SHORT_VOLUME_URL
        
        # 创建会话对象
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/plain, */*',
        })
        
        logger.info(f"FINRAFetcher初始化完成 (live mode)")
    
    def _get_date_str(self, target_date: Optional[date] = None, try_previous: bool = True) -> Optional[str]:
        """获取有效的FINRA文件日期字符串
        
        如果目标日期的文件不存在（非交易日），自动向前回溯最多5个交易日。
        
        Args:
            target_date: 目标日期, None表示今天
            try_previous: 是否在文件不存在时向前回溯
            
        Returns:
            str: YYYYMMDD格式日期字符串, 无有效日期时返回None
        """
        if target_date is None:
            target_date = date.today()
        
        for offset in range(5 if try_previous else 1):
            check_date = target_date - timedelta(days=offset)
            date_str = check_date.strftime('%Y%m%d')
            
            if not try_previous:
                return date_str
            
            # 快速检查文件是否存在 (HEAD请求)
            url = self.base_url.format(date=date_str)
            try:
                resp = self.session.head(url, timeout=5)
                if resp.status_code == 200:
                    if offset > 0:
                        logger.info(f"目标日期{target_date}无数据,回溯至{check_date}")
                    return date_str
            except Exception:
                continue
        
        logger.error(f"无法找到{target_date}前5日内的有效FINRA数据文件")
        return None
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=5, max=45),
        retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError)),
        reraise=True
    )
    def fetch_short_volume_data(self, symbol: str = 'SPY') -> Optional[Dict[str, Any]]:
        """从 FINRA 文件获取指定标的的短卖成交量数据
        
        下载 FINRA 每日 Consolidated Short Sale Volume 公开文件，
        过滤出指定symbol的所有市场数据并汇总。
        
        Args:
            symbol: 标的股票代码，如'SPY'、'QQQ'
            
        Returns:
            dict: 包含以下字段:
                - 'date': 文件日期
                - 'symbol': 标的代码
                - 'short_volume': 总短卖成交量 (st)
                - 'total_volume': 总成交量 (rt)
                - 'short_ratio': 短卖比例 (自动计算, %)
            失败时返回None
            
        Raises:
            DataFetchError: 文件下载或解析失败时抛出
            
        Examples:
            >>> fetcher = FINRAFetcher()
            >>> data = fetcher.fetch_short_volume_data('SPY')
            >>> if data:
            ...     print(f"SPY短卖比例: {data['short_ratio']:.2f}%")
        """
        # 获取有效日期字符串
        date_str = self._get_date_str()
        if not date_str:
            return None
        
        url = self.base_url.format(date=date_str)
        
        try:
            logger.info(f"请求FINRA短卖文件: {url}")
            response = self.session.get(url, timeout=Config.REQUEST_TIMEOUT)
            
            if response.status_code == 404:
                # 非交易日，尝试回溯
                logger.warning(f"FINRA文件不存在(404), 可能为非交易日: {date_str}")
                alt_date = self._get_date_str(target_date=date.today() - timedelta(days=1))
                if alt_date and alt_date != date_str:
                    url = self.base_url.format(date=alt_date)
                    response = self.session.get(url, timeout=Config.REQUEST_TIMEOUT)
                    date_str = alt_date
                else:
                    return None
            
            response.raise_for_status()
            
            # 解析管道分隔文件
            # 格式: Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market
            total_short = 0
            total_volume = 0
            symbol_upper = symbol.upper()
            
            lines = response.text.strip().split('\n')
            for i, line in enumerate(lines):
                if i == 0:
                    # 跳过表头行
                    continue
                
                parts = line.strip().split('|')
                if len(parts) < 6:
                    continue
                
                file_symbol = parts[1].strip()
                if file_symbol == symbol_upper:
                    try:
                        short_vol = int(float(parts[2]))
                        total_vol = int(float(parts[4]))
                        total_short += short_vol
                        total_volume += total_vol
                    except (ValueError, IndexError):
                        continue
            
            if total_volume == 0:
                logger.warning(f"FINRA文件中未找到{symbol}的成交量数据")
                return None
            
            # 解析文件日期
            file_date = datetime.strptime(date_str, '%Y%m%d').strftime('%Y-%m-%d')
            
            result = {
                'date': file_date,
                'symbol': symbol_upper,
                'short_volume': total_short,
                'total_volume': total_volume,
            }
            
            logger.info(
                f"成功获取{symbol}短卖数据 (date={file_date}, "
                f"short={total_short:,}, total={total_volume:,})"
            )
            return result
            
        except Timeout as e:
            logger.error(f"FINRA文件下载超时: {url}, error: {str(e)}")
            raise DataFetchError(
                message=f"FINRA文件下载超时: {str(e)}",
                error_code="FINRA_TIMEOUT",
                details={"url": url, "symbol": symbol}
            )
        except HTTPError as e:
            logger.error(f"FINRA HTTP错误 {response.status_code}: {url}")
            return None
        except Exception as e:
            logger.error(f"FINRA文件处理失败: {str(e)}", exc_info=True)
            raise DataFetchError(
                message=f"无法从FINRA获取{symbol}短卖数据: {str(e)}",
                error_code="FINRA_REQUEST_FAILED",
                details={"url": url, "symbol": symbol, "error": str(e)}
            )
    
    def calculate_off_exchange_short_ratio(self, raw_dict: Dict[str, Any]) -> Optional[float]:
        """计算短卖比例
        
        公式: short_volume / total_volume * 100
        
        Args:
            raw_dict: fetch_short_volume_data返回的字典
                     字段: short_volume, total_volume
            
        Returns:
            float: 短卖比例百分比（如45.8表示45.8%）
                  失败时返回None
            
        Examples:
            >>> fetcher = FINRAFetcher()
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
        
        检查历史数据中是否有连续consecutive_days天的短卖比例超过threshold。
        
        Args:
            data_history: 历史数据列表，每个元素包含'date'和'short_ratio'字段
                         按时间顺序排列（最新的在最后）
            threshold: 短卖比例阈值，默认45.0%
            consecutive_days: 连续天数，默认2天
            
        Returns:
            bool: True表示满足条件，False表示不满足
            
        Examples:
            >>> fetcher = FINRAFetcher()
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
                    f"历史数据不足，需要至少{consecutive_days}天，"
                    f"当前{len(data_history)}天"
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
                f"检测到连续{consecutive_days}日短卖比>{threshold}%: {dates}"
            )
            return True
            
        except Exception as e:
            logger.error(f"检测连续天数失败: {str(e)}", exc_info=True)
            return False
    
# 便捷函数
def create_finra_fetcher() -> FINRAFetcher:
    """创建FINRA数据获取器实例的工厂函数
    
    Returns:
        FINRAFetcher: 配置好的获取器实例
    """
    return FINRAFetcher()
