"""
多源共振监控系统 - Stockgrid暗盘净头寸爬虫

该模块使用Playwright无头浏览器爬取Stockgrid网站的暗盘大宗交易净头寸数据。
通过追踪20/60/120日累积美元净头寸曲线，识别机构底部背离信号。

主要功能:
- 拦截XHR响应获取JSON格式的net_position数组
- 降级策略：解析DOM表格元素提取数值
- 检测价格与净头寸的底背离
- 单例模式管理Browser实例

技术要求:
- Playwright异步无头浏览器 (Headless=True)
- Viewport: 1920x1080, User-Agent伪装
- 超时设置: 页面加载30秒，元素等待10秒
"""

import numpy as np
from typing import Optional, Dict, Any, List
from datetime import datetime
import subprocess
import sys
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from utils.logger import getLogger
from utils.exceptions import DataFetchError
from config.settings import Config, DataFetchConfig

logger = getLogger('stockgrid_fetcher')

# 延迟导入playwright，避免未安装时的导入错误
try:
    from playwright.async_api import async_playwright, Browser, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright未安装，StockgridFetcher将返回空数据")


class PlaywrightManager:
    """Playwright浏览器管理器（单例模式）
    
    管理Browser实例的生命周期，避免频繁启动关闭浏览器。
    采用单例模式确保全局只有一个Browser实例。
    """
    
    _instance: Optional['PlaywrightManager'] = None
    _browser: Optional[Any] = None
    _playwright: Optional[Any] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        if not PLAYWRIGHT_AVAILABLE:
            logger.error("Playwright库未安装，无法初始化浏览器管理器")
            self._initialized = True
            return
        
        # 检查并安装Playwright浏览器驱动
        self._check_and_install_playwright()
        
        self._initialized = True
        logger.info("PlaywrightManager单例初始化")
    
    def _check_and_install_playwright(self):
        """检查并安装Playwright浏览器驱动"""
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                # 尝试启动浏览器,如果失败则安装
                browser = p.chromium.launch(headless=True)
                browser.close()
                logger.info("Playwright浏览器驱动已就绪")
        except Exception as e:
            logger.warning(f"Playwright浏览器驱动未找到,正在安装: {e}")
            try:
                subprocess.check_call([sys.executable, '-m', 'playwright', 'install', 'chromium'])
                logger.info("Playwright浏览器驱动安装成功")
            except subprocess.CalledProcessError as install_error:
                logger.error(f"Playwright安装失败: {install_error}")
                raise
    
    async def get_browser(self) -> Optional[Any]:
        """获取或创建Browser实例
        
        Returns:
            Browser: Playwright Browser实例，失败时返回None
        """
        if not PLAYWRIGHT_AVAILABLE:
            logger.error("Playwright不可用")
            return None
        
        if self._browser is None:
            try:
                self._playwright = await async_playwright().start()
                
                # 启动Chromium浏览器（headless模式）
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-gpu',
                    ]
                )
                
                logger.info("Playwright Browser实例创建成功")
                
            except Exception as e:
                logger.error(f"创建Browser实例失败: {str(e)}", exc_info=True)
                return None
        
        return self._browser
    
    async def close(self):
        """关闭Browser实例和Playwright"""
        if self._browser:
            try:
                await self._browser.close()
                logger.info("Browser实例已关闭")
            except Exception as e:
                logger.error(f"关闭Browser失败: {str(e)}")
        
        if self._playwright:
            try:
                await self._playwright.stop()
                logger.info("Playwright已停止")
            except Exception as e:
                logger.error(f"停止Playwright失败: {str(e)}")
        
        self._browser = None
        self._playwright = None
    
    @classmethod
    def close_all(cls):
        """类方法:关闭所有浏览器实例(用于优雅关闭)"""
        if cls._instance and cls._instance._browser:
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                loop.run_until_complete(cls._instance._browser.close())
                logger.info("Browser实例已关闭")
            except Exception as e:
                logger.error(f"关闭Browser失败: {e}")
        
        if cls._instance and cls._instance._playwright:
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                loop.run_until_complete(cls._instance._playwright.stop())
                logger.info("Playwright已停止")
            except Exception as e:
                logger.error(f"停止Playwright失败: {e}")
        
        cls._browser = None
        cls._playwright = None


class StockgridFetcher:
    """Stockgrid暗盘净头寸爬虫
    
    使用Playwright无头浏览器访问Stockgrid网站，抓取SPY/QQQ的
    暗盘大宗交易累积净头寸数据（20/60/120日周期）。
    
    Attributes:
        browser_manager: Playwright浏览器管理器单例
        base_url: Stockgrid网站基础URL
        selectors: CSS选择器配置字典（外置以便维护）
    """
    
    # ✅ PRD要求：CSS选择器外置配置，便于网站改版时快速调整
    SELECTORS = {
        'chart_container': '.darkpool-chart, .net-position-chart, #darkpool-chart',
        'data_table': '.net-position-table, .data-table, #position-data',
        'period_selector': '.period-selector, .timeframe-btn, [data-period]',
        'value_cell': '.position-value, .net-amount, td.value-cell',
        'date_column': '.date-column, td.date-cell',
        'loading_indicator': '.loading-spinner, .skeleton-loader',
        'error_message': '.error-message, .alert-danger',
    }
    
    def __init__(self):
        """初始化Stockgrid数据获取器"""
        self.browser_manager = PlaywrightManager()
        self.base_url = "https://stockgrid.io"
        
        logger.info(f"StockgridFetcher初始化完成 (live mode)")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=5, min=5, max=45),  # 5s → 15s → 45s
        retry=retry_if_exception_type((DataFetchError, TimeoutError, Exception)),
        reraise=True,
        before_sleep=lambda retry_state: logger.warning(
            f"Stockgrid爬取失败，第{retry_state.attempt_number}次重试 "
            f"(等待{retry_state.next_action.sleep}秒): {retry_state.outcome.exception()}"
        )
    )
    async def scrape_net_position_history(
        self, 
        symbol: str = 'SPY', 
        period_days: List[int] = [20, 60, 120]
    ) -> Optional[Dict[str, List[float]]]:
        """爬取暗盘净头寸历史数据
        
        访问Stockgrid网站的Dark Pool板块，提取指定标的在多个时间周期内的
        累积美元净头寸序列。
        
        策略A（优先）: 拦截XHR响应获取JSON格式的net_position数组
        策略B（降级）: 解析DOM表格元素提取数值
        
        Args:
            symbol: 标的股票代码，如'SPY'、'QQQ'
            period_days: 时间周期列表，默认[20, 60, 120]天
            
        Returns:
            dict: 各周期的净头寸序列
                {
                    '20d': [value1, value2, ...],
                    '60d': [value1, value2, ...],
                    '120d': [value1, value2, ...]
                }
            失败时返回None
            
        Raises:
            DataFetchError: 爬取失败时抛出（经3次重试后仍失败）
            
        Examples:
            >>> fetcher = StockgridFetcher()
            >>> data = await fetcher.scrape_net_position_history('SPY')
            >>> if data:
            ...     print(f"20日净头寸序列长度: {len(data['20d'])}")
        """
        if not PLAYWRIGHT_AVAILABLE:
            logger.error("Playwright不可用，请安装: pip install playwright && playwright install")
            return None
        
        try:
            logger.info(f"开始爬取Stockgrid: symbol={symbol}, periods={period_days}")
            
            browser = await self.browser_manager.get_browser()
            if not browser:
                raise DataFetchError(
                    message="无法获取Browser实例",
                    error_code="STOCKGRID_BROWSER_ERROR"
                )
            
            # 创建新页面
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            
            page = await context.new_page()
            
            # 存储XHR响应数据
            xhr_responses = []
            
            # 策略A: 拦截XHR请求（使用外置配置的URL匹配规则）
            async def handle_response(response):
                try:
                    url = response.url
                    if DataFetchConfig.STOCKGRID_XHR_PATTERN in url.lower():
                        content_type = response.headers.get('content-type', '')
                        if 'application/json' in content_type:
                            try:
                                json_data = await response.json()
                                xhr_responses.append(json_data)
                                logger.info(f"拦截到XHR响应: {url}")
                            except Exception:
                                pass
                except Exception as e:
                    logger.debug(f"处理响应失败: {str(e)}")
            
            page.on("response", handle_response)
            
            # 访问目标页面（使用外置配置的URL模板）
            target_url = DataFetchConfig.STOCKGRID_URL.format(symbol=symbol)
            logger.info(f"访问页面: {target_url}")
            
            await page.goto(
                target_url,
                wait_until='networkidle',
                timeout=30000  # 30秒超时
            )
            
            # 等待关键元素加载
            try:
                await page.wait_for_selector('.darkpool-chart, .net-position-table', timeout=10000)
            except Exception:
                logger.warning("未找到预期的图表或表格元素，尝试继续解析")
            
            # 检查是否捕获到XHR数据
            if xhr_responses:
                logger.info(f"成功捕获{len(xhr_responses)}个XHR响应")
                parsed_data = self._parse_xhr_responses(xhr_responses, period_days)
                if parsed_data:
                    await context.close()
                    return parsed_data
            
            # 策略B: 降级为DOM解析
            logger.info("XHR拦截失败，降级为DOM解析")
            dom_data = await self._parse_dom_table(page, symbol, period_days)
            
            await context.close()
            
            if dom_data:
                logger.info("DOM解析成功")
                return dom_data
            else:
                logger.error("DOM解析也失败")
                return None
            
        except Exception as e:
            logger.error(f"爬取Stockgrid数据失败: {str(e)}", exc_info=True)
            raise DataFetchError(
                message=f"爬取Stockgrid数据失败: {str(e)}",
                error_code="STOCKGRID_SCRAPING_ERROR",
                details={"error": str(e), "symbol": symbol}
            )
    
    async def _parse_dom_table(
        self, 
        page: Any, 
        symbol: str, 
        period_days: List[int]
    ) -> Optional[Dict[str, List[float]]]:
        """解析DOM表格提取净头寸数据（降级策略）
        
        使用外置的CSS选择器配置，便于网站改版时快速调整。
        
        Args:
            page: Playwright Page对象
            symbol: 标的符号
            period_days: 时间周期列表
            
        Returns:
            dict: 各周期的净头寸序列，失败时返回None
        """
        try:
            result = {}
            
            # ✅ 使用外置选择器配置
            data_table_selector = self.SELECTORS['data_table']
            value_cell_selector = self.SELECTORS['value_cell']
            
            for period in period_days:
                # 尝试从页面提取数据
                # 优先尝试周期特定的选择器
                selector_candidates = [
                    f'.net-position-data[data-period="{period}"]',
                    f'{data_table_selector}[data-period="{period}"]',
                    f'{value_cell_selector}.period-{period}',
                ]
                
                selected = False
                for selector in selector_candidates:
                    try:
                        # 等待元素出现
                        await page.wait_for_selector(selector, timeout=5000)
                        
                        # 提取文本内容
                        text_content = await page.text_content(selector)
                        
                        # 解析数值（假设格式为逗号分隔的数字序列）
                        if text_content:
                            values = []
                            for item in text_content.split(','):
                                try:
                                    values.append(float(item.strip()))
                                except ValueError:
                                    continue
                            
                            if values:
                                result[f'{period}d'] = values
                                logger.info(f"DOM解析成功: {period}d周期, {len(values)}个数据点 (选择器: {selector})")
                                selected = True
                                break
                    
                    except Exception as e:
                        logger.debug(f"选择器 '{selector}' 失败: {str(e)}")
                        continue
                
                if not selected:
                    logger.warning(f"{period}d周期所有选择器均失败，尝试下一个周期")
            
            if result:
                return result
            else:
                logger.error("所有周期的DOM解析均失败")
                return None
                
        except Exception as e:
            logger.error(f"DOM解析异常: {str(e)}", exc_info=True)
            return None
    
    def _parse_xhr_responses(
        self, 
        xhr_responses: List[Dict[str, Any]], 
        period_days: List[int]
    ) -> Optional[Dict[str, List[float]]]:
        """解析XHR响应数据（策略A）
        
        使用外置的API字段名配置，便于API改版时快速调整。
        
        Args:
            xhr_responses: XHR响应JSON数据列表
            period_days: 时间周期列表
            
        Returns:
            dict: 各周期的净头寸序列，失败时返回None
        """
        try:
            result = {}
            
            # ✅ 外置API字段名配置
            api_field_patterns = [
                'net_position_{period}d',
                'netPosition{period}d',
                '{period}d_net_position',
                'data_{period}d',
                'position_data_{period}',
            ]
            
            for response in xhr_responses:
                for period in period_days:
                    # 使用配置的字段模式
                    key_candidates = [
                        pattern.format(period=period) for pattern in api_field_patterns
                    ]
                    
                    for key in key_candidates:
                        if key in response:
                            data = response[key]
                            if isinstance(data, list):
                                result[f'{period}d'] = [float(v) for v in data]
                                logger.info(f"XHR解析成功: {key}")
                                break
            
            if result:
                return result
            else:
                logger.warning("XHR响应中未找到预期的数据字段")
                return None
                
        except Exception as e:
            logger.error(f"XHR解析异常: {str(e)}", exc_info=True)
            return None
    
    def detect_bottom_divergence(
        self, 
        net_position_series: List[float], 
        price_series: List[float]
    ) -> Dict[str, Any]:
        """【修复】检测底背离信号：分别对20日和60日周期进行切片拟合
        
        当价格创新低但净头寸斜率转正时，标记为底背离。
        分别计算20日和60日窗口的独立斜率，实现PRD要求的双周期验证。
        新增Golden Cross检测：双周期斜率皆转正（20d > 0 AND 60d > 0）。
        
        Args:
            net_position_series: 净头寸时间序列（最近N个数据点，必须>=60）
            price_series: 价格时间序列（与净头寸对应的时间段，必须>=60）
            
        Returns:
            dict: 背离检测结果
        """
        try:
            if len(net_position_series) < 60 or len(price_series) < 60:
                logger.error(f"数据点不足60个（净头寸={len(net_position_series)}, 价格={len(price_series)}），无法计算完整双周期斜率")
                return {
                    'divergence': False,
                    'slope_20d': 0.0,
                    'slope_60d': 0.0,
                    'price_trend': 'unknown',
                    'position_trend': 'unknown'
                }
            
            # --- 分别切片计算斜率 ---
            # 60日计算
            recent_60_pos = net_position_series[-60:]
            slope_60d = float(np.polyfit(np.arange(60), recent_60_pos, 1)[0])
            
            # 20日计算（独立切片，不复用60日数据）
            recent_20_pos = net_position_series[-20:]
            slope_20d = float(np.polyfit(np.arange(20), recent_20_pos, 1)[0])
            
            # 价格趋势计算（以近期60日为宏观基准）
            recent_60_price = price_series[-60:]
            price_slope = float(np.polyfit(np.arange(60), recent_60_price, 1)[0])
            
            # 判断趋势方向
            position_trend = 'up' if slope_20d > 0 else ('down' if slope_20d < 0 else 'flat')
            price_trend = 'up' if price_slope > 0 else ('down' if price_slope < 0 else 'flat')
            
            # 检测底背离：价格下跌但短期净头寸上升，且双周期斜率皆转正 (黄金交叉)
            dual_slope_positive = (slope_20d > 0 and slope_60d > 0)
            divergence = (price_trend == 'down' and position_trend == 'up') or dual_slope_positive
            
            result = {
                'divergence': divergence,
                'slope_20d': slope_20d,   # 修复：独立的20日斜率
                'slope_60d': slope_60d,   # 修复：独立的60日斜率
                'price_trend': price_trend,
                'position_trend': position_trend
            }
            
            if divergence:
                logger.warning(
                    f"✅ 检测到底背离或双周期转正! "
                    f"20d斜率={slope_20d:.4f}, 60d斜率={slope_60d:.4f}, "
                    f"Golden Cross={dual_slope_positive}"
                )
            
            return result
            
        except Exception as e:
            logger.error(f"检测底背离失败: {str(e)}", exc_info=True)
            return {
                'divergence': False,
                'slope_20d': 0.0,
                'slope_60d': 0.0,
                'price_trend': 'error',
                'position_trend': 'error'
            }
    
# 便捷函数
def create_stockgrid_fetcher() -> StockgridFetcher:
    """创建Stockgrid数据获取器实例的工厂函数
    
    Returns:
        StockgridFetcher: 配置好的获取器实例
    """
    return StockgridFetcher()
