"""
多源共振监控系统 - 主调度器

该模块负责管理所有定时任务，包括：
- 盘中高频任务（每5-15分钟执行）
- 盘后批量任务（每日美东20:30执行）
- 异常处理与优雅关闭
- 任务依赖管理

使用示例:
    from main_scheduler import MainScheduler, create_and_start_scheduler
    
    # 方式1: 直接启动
    create_and_start_scheduler()
    
    # 方式2: 手动控制
    scheduler = MainScheduler()
    scheduler.start()
"""

import asyncio
from datetime import datetime, time, date
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

from utils.logger import getLogger
from config.settings import Config
from database.db_manager import DatabaseManager
from data_fetchers import (
    TradierFetcher,
    YahooFinanceFetcher,
    CCXTFetcher,
    SqueezeMetricsFetcher,
    ChartExchangeFetcher,
    StockgridFetcher,
    DBMFFetcher
)
from quant_logic import (
    GEXCalculator,
    VIXAnalyzer,
    CryptoLeverageCleaner,
    DarkPoolVerifier
)
from signal_engine import (
    ResonanceScorer,
    SignalStateMachine,
    format_alert_message
)
from utils.fallback_manager import FallbackManager, handle_fetch_errors

logger = getLogger('main_scheduler')


class MainScheduler:
    """主调度器 - 管理所有定时任务
    
    基于APScheduler实现异步任务调度,包含盘中高频任务(每15分钟)
    和盘后批量任务(每日美东20:30)。通过ThreadPoolExecutor包装同步
    数据获取方法,避免阻塞事件循环。
    
    Attributes:
        scheduler: APScheduler异步调度器实例
        executor: ThreadPoolExecutor用于数据获取操作
        db_executor: ThreadPoolExecutor用于数据库操作
        db: DatabaseManager数据库管理器单例
    """
    
    def __init__(self):
        """初始化调度器和所有依赖组件"""
        self.scheduler = AsyncIOScheduler(timezone='US/Eastern')
        self.db = DatabaseManager()
        
        # 添加线程池用于同步方法调用
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.db_executor = ThreadPoolExecutor(max_workers=2)
        
        # 初始化数据获取器
        self.tradier_fetcher = TradierFetcher()
        self.yahoo_fetcher = YahooFinanceFetcher()
        self.ccxt_fetcher = CCXTFetcher()
        self.squeezemetrics_fetcher = SqueezeMetricsFetcher()
        self.chartexchange_fetcher = ChartExchangeFetcher()
        self.stockgrid_fetcher = StockgridFetcher()
        self.dbmf_fetcher = DBMFFetcher()
        
        # 初始化工具类
        self.gex_calculator = GEXCalculator()
        self.vix_analyzer = VIXAnalyzer()
        self.crypto_cleaner = CryptoLeverageCleaner()
        self.darkpool_verifier = DarkPoolVerifier()
        self.resonance_scorer = ResonanceScorer()
        self.signal_machine = SignalStateMachine(cooldown_minutes=30)
        
        # 初始化降级管理器
        self.fallback_manager = FallbackManager()
        
        logger.info("主调度器初始化完成")
    
    def setup_intraday_tasks(self):
        """设置盘中高频任务(美东时间9:30-16:00,每15分钟执行)
        
        注册5个盘中监控任务:
        - GEX计算: 拉取Tradier期权链并计算Gamma敞口
        - VIX分析: 获取VIX期货并分析期限结构
        - 加密监控: 监控BTC资金费率和持仓量变化
        - DBMF检测: 检查DBMF ETF均线收复信号
        - 共振评分: 综合四维度评分并触发告警
        
        Note:
            所有任务通过ThreadPoolExecutor在线程池中执行,
            避免阻塞asyncio事件循环。
        """
        
        # 任务1: GEX计算 (每15分钟)
        self.scheduler.add_job(
            self.task_calculate_gex,
            trigger='cron',
            minute='*/15',
            hour='9-16',  # 美东时间9:30-16:00交易时段
            id='calculate_gex',
            name='计算GEX敞口',
            misfire_grace_time=300  # 允许5分钟的延迟容忍
        )
        
        # 任务2: VIX期限结构分析 (每15分钟)
        self.scheduler.add_job(
            self.task_analyze_vix,
            trigger='cron',
            minute='*/15',
            hour='9-16',
            id='analyze_vix',
            name='分析VIX期限结构',
            misfire_grace_time=300
        )
        
        # 任务3: 加密杠杆监控 (每5分钟，24小时)
        self.scheduler.add_job(
            self.task_monitor_crypto,
            trigger='cron',
            minute='*/5',  # 每5分钟
            hour='0-23',   # 24小时监控
            id='monitor_crypto',
            name='监控加密市场杠杆',
            misfire_grace_time=120
        )
        
        # 任务4: DBMF动量检测 (每15分钟)
        self.scheduler.add_job(
            self.task_check_dbmf,
            trigger='cron',
            minute='*/15',
            hour='9-16',
            id='check_dbmf',
            name='检测DBMF均线收复',
            misfire_grace_time=300
        )
        
        # 任务5: 共振评分与信号触发 (每15分钟)
        self.scheduler.add_job(
            self.task_evaluate_resonance,
            trigger='cron',
            minute='*/15',
            hour='9-16',
            id='evaluate_resonance',
            name='评估共振矩阵并触发信号',
            misfire_grace_time=300
        )
        
        logger.info("盘中高频任务设置完成(共5个)")
    
    def setup_afterhours_tasks(self):
        """设置盘后批量任务(每日美东20:30-21:30执行)
        
        注册5个盘后数据抓取任务:
        - DIX获取 (20:30): SqueezeMetrics官方暗盘指标
        - ChartExchange (20:35): 场外卖空比率数据
        - Stockgrid (20:40): Playwright爬取净头寸趋势
        - α系数更新 (21:00): 校准GEX计算模型
        - 数据库备份 (21:30): SQLite数据库快照
        
        Note:
            盘后任务按顺序执行,避免同时访问同一数据源造成限流。
        """
        
        # 任务1: 获取SqueezeMetrics DIX (美东20:30)
        self.scheduler.add_job(
            self.task_fetch_dix,
            trigger='cron',
            hour='20',
            minute='30',
            id='fetch_dix',
            name='获取DIX指标',
            misfire_grace_time=3600  # 允许1小时延迟
        )
        
        # 任务2: 抓取ChartExchange卖空比 (美东20:35)
        self.scheduler.add_job(
            self.task_fetch_chartexchange,
            trigger='cron',
            hour='20',
            minute='35',
            id='fetch_chartexchange',
            name='抓取ChartExchange数据',
            misfire_grace_time=3600
        )
        
        # 任务3: Playwright抓取Stockgrid (美东20:40)
        self.scheduler.add_job(
            self.task_fetch_stockgrid,
            trigger='cron',
            hour='20',
            minute='40',
            id='fetch_stockgrid',
            name='抓取Stockgrid净头寸',
            misfire_grace_time=3600
        )
        
        # 任务4: 更新校准系数α (美东21:00)
        self.scheduler.add_job(
            self.task_update_alpha,
            trigger='cron',
            hour='21',
            minute='0',
            id='update_alpha',
            name='更新GEX校准系数',
            misfire_grace_time=3600
        )
        
        # 任务5: 备份数据库 (美东21:30)
        self.scheduler.add_job(
            self.task_backup_database,
            trigger='cron',
            hour='21',
            minute='30',
            id='backup_database',
            name='备份SQLite数据库',
            misfire_grace_time=3600
        )
        
        logger.info("盘后批量任务设置完成(共5个)")
    
    async def task_calculate_gex(self):
        """任务: 计算GEX敞口
        
        从Tradier获取期权链数据，计算Gamma Exposure，
        识别Flip Zone和Put Wall关键价位。
        """
        try:
            logger.debug("开始执行GEX计算任务")
            loop = asyncio.get_event_loop()
            
            # 获取当前日期和下一个周五的期权到期日
            today = datetime.now(pytz.timezone('US/Eastern'))
            expiry_date = self._get_next_friday_expiry(today)
            
            # 获取期权链 - 通过线程池执行同步方法
            option_chain = await loop.run_in_executor(
                self.executor,
                self.tradier_fetcher.get_option_chain,
                'SPY',
                expiry_date
            )
            if not option_chain:
                logger.warning("期权链获取失败,跳过本轮GEX计算")
                self.fallback_manager.record_failure('task_calculate_gex')
                return
            
            # 获取当前价格 - 通过线程池执行同步方法
            spot_price = await loop.run_in_executor(
                self.executor,
                self.yahoo_fetcher.get_spy_price
            )
            if not spot_price:
                logger.warning("SPY价格获取失败,跳过GEX计算")
                self.fallback_manager.record_failure('task_calculate_gex')
                return
            
            # GEX计算是CPU密集型,也在executor中执行
            gex_result = await loop.run_in_executor(
                self.executor,
                self.gex_calculator.calculate_portfolio_gex,
                option_chain,
                spot_price
            )
            
            # 应用校准系数 - 数据库操作使用db_executor
            alpha_str = await loop.run_in_executor(
                self.db_executor,
                self.db.get_config_value,
                'alpha_factor',
                '1.0'
            )
            alpha = float(alpha_str)
            
            gex_calibrated = await loop.run_in_executor(
                self.db_executor,
                lambda: self.gex_calculator.apply_calibration(gex_result['total_gex'], alpha)
            )
            
            # 识别Flip Zone和Put Wall
            flip_zone = await loop.run_in_executor(
                self.executor,
                self.gex_calculator.identify_flip_zone,
                gex_result['gex_by_strike']
            )
            put_wall = await loop.run_in_executor(
                self.executor,
                self.gex_calculator.find_put_wall,
                gex_result['gex_by_strike']
            )
            
            # 存入数据库
            timestamp = datetime.now(pytz.timezone('US/Eastern'))
            await loop.run_in_executor(
                self.db_executor,
                self.db.insert_gex_record,
                timestamp,
                gex_result['total_gex'],
                gex_calibrated,
                alpha,
                put_wall,
                flip_zone.get('flip_zone_lower'),
                flip_zone.get('flip_zone_upper')
            )
            
            # 成功后重置失败计数
            self.fallback_manager.reset_failure_count('task_calculate_gex')
            
            logger.debug(
                f"GEX计算完成: Local=${gex_result['total_gex']/1e6:.1f}M, "
                f"Calibrated=${gex_calibrated/1e6:.1f}M, Put Wall=${put_wall}"
            )
            
        except Exception as e:
            logger.error(f"GEX计算任务失败: {e}", exc_info=True)
            self.fallback_manager.record_failure('task_calculate_gex')
    
    async def task_analyze_vix(self):
        """任务: 分析VIX期限结构
        
        获取VIX现货和期货价格，分析期限结构形态
        （Contango/Backwardation），计算恐慌溢价。
        """
        try:
            logger.debug("开始执行VIX分析任务")
            loop = asyncio.get_event_loop()
            
            vx1 = await loop.run_in_executor(
                self.executor,
                self.yahoo_fetcher.get_vix_futures,
                'VX1'
            )
            vx2 = await loop.run_in_executor(
                self.executor,
                self.yahoo_fetcher.get_vix_futures,
                'VX2'
            )
            vix_spot = await loop.run_in_executor(
                self.executor,
                self.yahoo_fetcher.get_vix_spot
            )
            
            if not all([vx1, vx2, vix_spot]):
                logger.warning("VIX数据获取不完整,跳过分析")
                self.fallback_manager.record_failure('task_analyze_vix')
                return
            
            # 分析期限结构
            term_structure = await loop.run_in_executor(
                self.executor,
                self.vix_analyzer.analyze_term_structure,
                vx1,
                vx2
            )
            panic_premium = await loop.run_in_executor(
                self.executor,
                self.vix_analyzer.calculate_panic_premium,
                vix_spot,
                vx1
            )
            
            # 存入数据库
            timestamp = datetime.now(pytz.timezone('US/Eastern'))
            await loop.run_in_executor(
                self.db_executor,
                self.db.insert_vix_analysis,
                timestamp,
                vix_spot,
                vx1,
                vx2,
                term_structure['ratio'],
                term_structure['state'],
                panic_premium
            )
            
            # 成功后重置失败计数
            self.fallback_manager.reset_failure_count('task_analyze_vix')
            
            logger.debug(
                f"VIX分析完成: Ratio={term_structure['ratio']:.2f}, "
                f"State={term_structure['state']}, Panic Premium={panic_premium:.2f}"
            )
            
        except Exception as e:
            logger.error(f"VIX分析任务失败: {e}", exc_info=True)
            self.fallback_manager.record_failure('task_analyze_vix')
    
    async def task_monitor_crypto(self):
        """任务: 监控加密市场杠杆
        
        实时监控BTC永续合约资金费率和未平仓合约量，
        检测杠杆清算风险。
        """
        try:
            logger.debug("开始执行加密市场监控任务")
            loop = asyncio.get_event_loop()
            
            funding_rate = await loop.run_in_executor(
                self.executor,
                self.ccxt_fetcher.get_funding_rate,
                'BTC/USDT'
            )
            current_oi = await loop.run_in_executor(
                self.executor,
                self.ccxt_fetcher.get_open_interest,
                'BTC/USDT'
            )
            
            if not funding_rate or not current_oi:
                logger.warning("加密数据获取失败")
                self.fallback_manager.record_failure('task_monitor_crypto')
                return
            
            # 获取历史OI计算变化率
            historical_oi = await loop.run_in_executor(
                self.db_executor,
                self.db.get_crypto_history,
                1
            )
            oi_change = await loop.run_in_executor(
                self.executor,
                lambda: self.crypto_cleaner.detect_oi_crash(
                    current_oi['oi'],
                    historical_oi['btc_oi'].tolist() if len(historical_oi) > 0 else []
                )
            )
            
            # 检测费率异常
            funding_anomaly = await loop.run_in_executor(
                self.executor,
                self.crypto_cleaner.check_funding_rate_anomaly,
                funding_rate
            )
            
            # 存入数据库
            timestamp = datetime.now(pytz.timezone('US/Eastern'))
            await loop.run_in_executor(
                self.db_executor,
                self.db.insert_crypto_derivatives,
                timestamp,
                funding_rate,
                current_oi['oi'],
                oi_change['drop_percentage'],
                False,  # liquidation_spike
                None,   # cryptoquant_elr
                funding_anomaly,
                oi_change['crash_detected'],
                False   # leverage_cleanup
            )
            
            # 成功后重置失败计数
            self.fallback_manager.reset_failure_count('task_monitor_crypto')
            
            logger.debug(
                f"加密监控完成: Funding={funding_rate*100:.4f}%, "
                f"OI Change={oi_change['drop_percentage']:.1f}%, "
                f"Anomaly={funding_anomaly}"
            )
            
        except Exception as e:
            logger.error(f"加密监控任务失败: {e}", exc_info=True)
            self.fallback_manager.record_failure('task_monitor_crypto')
    
    async def task_check_dbmf(self):
        """任务: 检测DBMF均线收复
        
        监控DBMF基金价格是否收复5日均线，
        作为暗盘流动性恢复的信号。
        """
        try:
            logger.debug("开始执行DBMF检测任务")
            loop = asyncio.get_event_loop()
            
            current_price = await loop.run_in_executor(
                self.executor,
                self.dbmf_fetcher.get_dbmf_intraday_price
            )
            historical_prices = await loop.run_in_executor(
                self.executor,
                lambda: self.dbmf_fetcher.get_dbmf_historical_prices(days=10)
            )
            
            if not current_price or not historical_prices:
                logger.warning("DBMF数据获取失败")
                self.fallback_manager.record_failure('task_check_dbmf')
                return
            
            recovery = await loop.run_in_executor(
                self.executor,
                self.dbmf_fetcher.check_ma5_recovery,
                current_price,
                historical_prices
            )
            
            # 更新暗盘指标表
            today = datetime.now(pytz.timezone('US/Eastern')).date()
            existing = await loop.run_in_executor(
                self.db_executor,
                self.db.get_dark_pool_metrics_by_date,
                today
            )
            
            if existing and len(existing) > 0:
                # TODO: 需要实现update方法
                logger.debug(f"DBMF检测到收复信号: {recovery} (待更新现有记录)")
            else:
                await loop.run_in_executor(
                    self.db_executor,
                    self.db.insert_dark_pool_metrics,
                    today,
                    None, None, None, None, False, recovery, False, False, False, False
                )
            
            # 成功后重置失败计数
            self.fallback_manager.reset_failure_count('task_check_dbmf')
            
            logger.debug(f"DBMF检测完成: Recovery={recovery}")
            
        except Exception as e:
            logger.error(f"DBMF检测任务失败: {e}", exc_info=True)
            self.fallback_manager.record_failure('task_check_dbmf')
    
    async def task_evaluate_resonance(self):
        """任务: 评估共振矩阵并触发信号
            
        综合GEX、VIX、Crypto、Darkpool四个维度的数据，
        计算共振评分，触发告警信号。
        """
        try:
            logger.debug("开始执行共振评估任务")
            loop = asyncio.get_event_loop()
                
            # 获取最新数据 - 数据库操作使用db_executor
            latest_gex = await loop.run_in_executor(
                self.db_executor,
                self.db.get_latest_gex
            )
            latest_crypto = await loop.run_in_executor(
                self.db_executor,
                self.db.get_latest_crypto_data
            )
            latest_darkpool = await loop.run_in_executor(
                self.db_executor,
                self.db.get_latest_dark_pool_metrics
            )
            latest_vix = await loop.run_in_executor(
                self.db_executor,
                self.db.get_latest_vix_analysis
            )
                
            if not latest_gex:
                logger.warning("GEX数据缺失,跳过共振评估")
                self.fallback_manager.record_failure('task_evaluate_resonance')
                return
                
            # 计算各维度分值 - CPU密集型计算使用executor
            gex_score = await loop.run_in_executor(
                self.executor,
                lambda: self.resonance_scorer.calculate_gex_score(
                    gex_local=latest_gex['gex_local'],
                    gex_calibrated=latest_gex['gex_calibrated'],
                    flip_zone_crossed=latest_gex['gex_calibrated'] > 0,
                    gex_trend='IMPROVING'
                )
            )
                
            vix_score = await loop.run_in_executor(
                self.executor,
                lambda: self.resonance_scorer.calculate_vix_score(
                    term_structure_ratio=latest_vix.get('term_structure_ratio', 1.0) if latest_vix else 1.0,
                    slope_direction='DOWN',
                    panic_premium=latest_vix.get('panic_premium', 0.0) if latest_vix else 0.0
                )
            )
                
            crypto_score = await loop.run_in_executor(
                self.executor,
                lambda: self.resonance_scorer.calculate_crypto_score(
                    oi_crash=latest_crypto.get('oi_crash', False) if latest_crypto else False,
                    funding_positive=(latest_crypto.get('btc_funding_rate', 0) >= 0) if latest_crypto else False,
                    elr_safe=False,
                    leverage_cleanup_confirmed=False
                )
            )
                
            darkpool_score = await loop.run_in_executor(
                self.executor,
                lambda: self.resonance_scorer.calculate_darkpool_score(
                    dix_flag=latest_darkpool.get('dix_signal', False) if latest_darkpool else False,
                    short_ratio_flag=latest_darkpool.get('short_ratio_signal', False) if latest_darkpool else False,
                    stockgrid_flag=latest_darkpool.get('stockgrid_signal', False) if latest_darkpool else False,
                    dbmf_recovery=latest_darkpool.get('dbmf_ma5_recovery', False) if latest_darkpool else False,
                    aggregated_signal=latest_darkpool.get('aggregated_signal', False) if latest_darkpool else False
                )
            )
                
            # 计算总分
            resonance_result = await loop.run_in_executor(
                self.executor,
                lambda: self.resonance_scorer.calculate_total_score(
                    gex_result=gex_score,
                    vix_result=vix_score,
                    crypto_result=crypto_score,
                    darkpool_result=darkpool_score
                )
            )
                
            # Hawkes Process测算
            hawkes_result = await loop.run_in_executor(
                self.executor,
                lambda: self.resonance_scorer.estimate_hawkes_branching_ratio(
                    recent_price_changes=[],
                    recent_volumes=[]
                )
            )
                
            # 检查是否触发告警
            current_time = datetime.now(pytz.timezone('US/Eastern'))
            trigger_result = await loop.run_in_executor(
                self.executor,
                self.signal_machine.check_and_trigger,
                resonance_result,
                current_time
            )
                
            if trigger_result['should_alert']:
                # 格式化告警消息
                alert_message = await loop.run_in_executor(
                    self.executor,
                    format_alert_message,
                    resonance_result,
                    hawkes_result,
                    current_time
                )
                    
                # 存入数据库
                await loop.run_in_executor(
                    self.db_executor,
                    self.db.insert_signal_alert,
                    current_time,
                    resonance_result['total_score'],
                    gex_score['score'],
                    vix_score['score'],
                    crypto_score['score'],
                    darkpool_score['score'],
                    resonance_result['alert_level'],
                    hawkes_result['branching_ratio'],
                    resonance_result
                )
                    
                # 发送通知(待实现notification模块)
                logger.warning(f"🚨 {resonance_result['alert_level']} 信号触发! 总分: {resonance_result['total_score']}")
                logger.info(f"告警详情: {alert_message[:200]}...")
            else:
                logger.debug(
                    f"共振评估完成: {resonance_result['total_score']}/{resonance_result['max_score']}, "
                    f"{trigger_result['reason']}"
                )
                
            # 成功后重置失败计数
            self.fallback_manager.reset_failure_count('task_evaluate_resonance')
                
        except Exception as e:
            logger.error(f"共振评估任务失败: {e}", exc_info=True)
            self.fallback_manager.record_failure('task_evaluate_resonance')
    
    async def task_fetch_dix(self):
        """任务: 获取SqueezeMetrics DIX
        
        盘后获取当日DIX指标，作为暗盘活动强度信号。
        """
        try:
            logger.info("开始执行DIX获取任务")
            loop = asyncio.get_event_loop()
            
            dix_value = await loop.run_in_executor(
                self.executor,
                self.squeezemetrics_fetcher.get_daily_dix
            )
            
            if dix_value is None:
                logger.warning("DIX获取失败")
                self.fallback_manager.record_failure('task_fetch_dix')
                return
            
            today = datetime.now(pytz.timezone('US/Eastern')).date()
            
            # 更新暗盘指标
            await loop.run_in_executor(
                self.db_executor,
                self.db.insert_dark_pool_metrics,
                today,
                dix_value, None, None, None, False, False, dix_value > 45.0, False, False, False
            )
            
            # 成功后重置失败计数
            self.fallback_manager.reset_failure_count('task_fetch_dix')
            
            logger.info(f"DIX获取完成: {dix_value}%")
            
        except Exception as e:
            logger.error(f"DIX获取任务失败: {e}", exc_info=True)
            self.fallback_manager.record_failure('task_fetch_dix')
    
    async def task_fetch_chartexchange(self):
        """任务: 抓取ChartExchange卖空比
        
        盘后抓取场外卖空成交量占比，作为暗盘空头压力指标。
        """
        try:
            logger.info("开始执行ChartExchange抓取任务")
            loop = asyncio.get_event_loop()
            
            spy_data = await loop.run_in_executor(
                self.executor,
                lambda: self.chartexchange_fetcher.fetch_short_volume_data('SPY')
            )
            
            if not spy_data:
                logger.warning("ChartExchange数据获取失败")
                self.fallback_manager.record_failure('task_fetch_chartexchange')
                return
            
            short_ratio = await loop.run_in_executor(
                self.executor,
                self.chartexchange_fetcher.calculate_off_exchange_short_ratio,
                spy_data
            )
            
            today = datetime.now(pytz.timezone('US/Eastern')).date()
            
            # 更新暗盘指标
            await loop.run_in_executor(
                self.db_executor,
                self.db.insert_dark_pool_metrics,
                today,
                None, short_ratio, None, None, False, False, False, short_ratio > 45.0, False, False
            )
            
            # 成功后重置失败计数
            self.fallback_manager.reset_failure_count('task_fetch_chartexchange')
            
            logger.info(f"ChartExchange抓取完成: Short Ratio={short_ratio:.1f}%")
            
        except Exception as e:
            logger.error(f"ChartExchange抓取任务失败: {e}", exc_info=True)
            self.fallback_manager.record_failure('task_fetch_chartexchange')
    
    async def task_fetch_stockgrid(self):
        """任务: 抓取Stockgrid净头寸
        
        使用Playwright抓取Stockgrid网站的机构净头寸数据，
        检测底背离信号。
        """
        try:
            logger.info("开始执行Stockgrid抓取任务")
            loop = asyncio.get_event_loop()
            
            net_position = await loop.run_in_executor(
                self.executor,
                lambda: self.stockgrid_fetcher.scrape_net_position_history('SPY', [20, 60, 120])
            )
            
            if not net_position:
                logger.warning("Stockgrid数据获取失败")
                self.fallback_manager.record_failure('task_fetch_stockgrid')
                return
            
            # 检测底背离
            divergence_result = await loop.run_in_executor(
                self.executor,
                lambda: self.stockgrid_fetcher.detect_bottom_divergence(
                    net_position.get('20d', []),
                    []
                )
            )
            
            today = datetime.now(pytz.timezone('US/Eastern')).date()
            
            # 验证信号
            confirmed_signal = await loop.run_in_executor(
                self.executor,
                lambda: self.darkpool_verifier.confirm_stockgrid_signal(
                    divergence_result.get('divergence', False),
                    divergence_result.get('slope_20d', 0),
                    divergence_result.get('slope_60d', 0)
                )
            )
            
            # 更新暗盘指标
            await loop.run_in_executor(
                self.db_executor,
                self.db.insert_dark_pool_metrics,
                today,
                None, None, divergence_result.get('slope_20d'), divergence_result.get('slope_60d'),
                divergence_result.get('divergence', False), False, False, False, confirmed_signal, False
            )
            
            # 成功后重置失败计数
            self.fallback_manager.reset_failure_count('task_fetch_stockgrid')
            
            logger.info(f"Stockgrid抓取完成: 20d Slope={divergence_result.get('slope_20d', 0):.4f}")
            
        except Exception as e:
            logger.error(f"Stockgrid抓取任务失败: {e}", exc_info=True)
            self.fallback_manager.record_failure('task_fetch_stockgrid')
    
    async def task_update_alpha(self):
        """任务: 更新GEX校准系数α
        
        比较本地计算的GEX与SqueezeMetrics官方GEX，
        动态调整校准系数以提高准确性。
        """
        try:
            logger.info("开始执行α系数更新任务")
            loop = asyncio.get_event_loop()
            
            # 获取今日本地GEX和官方GEX
            latest_gex = await loop.run_in_executor(
                self.db_executor,
                self.db.get_latest_gex
            )
            official_gex = await loop.run_in_executor(
                self.executor,
                self.squeezemetrics_fetcher.get_official_gex
            )
            
            if not latest_gex or not official_gex:
                logger.warning("GEX数据不完整,跳过α更新")
                self.fallback_manager.record_failure('task_update_alpha')
                return
            
            # 计算新α
            new_alpha = await loop.run_in_executor(
                self.executor,
                lambda: self.gex_calculator.calibrate_alpha(latest_gex['gex_local'], official_gex)
            )
            
            # 更新配置
            await loop.run_in_executor(
                self.db_executor,
                self.db.update_alpha_factor,
                new_alpha
            )
            
            # 成功后重置失败计数
            self.fallback_manager.reset_failure_count('task_update_alpha')
            
            logger.info(f"α系数更新完成: {new_alpha:.4f}")
            
        except Exception as e:
            logger.error(f"α系数更新任务失败: {e}", exc_info=True)
            self.fallback_manager.record_failure('task_update_alpha')
    
    async def task_backup_database(self):
        """任务: 备份数据库
        
        定期备份SQLite数据库到backups目录，
        防止数据丢失。
        """
        try:
            logger.info("开始执行数据库备份任务")
            loop = asyncio.get_event_loop()
            
            backup_path = await loop.run_in_executor(
                self.db_executor,
                self.db.backup_database
            )
            
            logger.info(f"数据库备份完成: {backup_path}")
            
        except Exception as e:
            logger.error(f"数据库备份任务失败: {e}", exc_info=True)
    
    def _get_next_friday_expiry(self, current_date: datetime) -> str:
        """获取下一个周五期权到期日
        
        Args:
            current_date: 当前日期
        
        Returns:
            str: YYYY-MM-DD格式的到期日
        """
        days_until_friday = (4 - current_date.weekday()) % 7
        if days_until_friday == 0:
            days_until_friday = 7  # 如果今天是周五，取下周周五
        
        next_friday = current_date.replace(day=current_date.day + days_until_friday)
        return next_friday.strftime('%Y-%m-%d')
    
    def start(self):
        """启动调度器
        
        设置所有任务并启动APScheduler，
        保持进程运行直到收到中断信号。
        """
        self.setup_intraday_tasks()
        self.setup_afterhours_tasks()
        
        self.scheduler.start()
        logger.info("🚀 主调度器已启动,所有任务正在运行")
        
        try:
            # 保持运行
            asyncio.get_event_loop().run_forever()
        except (KeyboardInterrupt, SystemExit):
            logger.info("收到停止信号,正在关闭调度器...")
            self.shutdown()
    
    def shutdown(self):
        """关闭调度器
        
        优雅关闭调度器和数据库连接，
        确保资源正确释放。
        """
        logger.info("正在关闭调度器...")
        
        # 关闭调度器
        if self.scheduler.running:
            self.scheduler.shutdown(wait=True)
            logger.info("调度器已停止")
        
        # 关闭Playwright浏览器
        try:
            from data_fetchers.stockgrid_fetcher import StockgridFetcher
            StockgridFetcher.close_all()
            logger.info("Playwright浏览器已关闭")
        except Exception as e:
            logger.error(f"关闭Playwright时出错: {e}")
        
        # 关闭线程池
        try:
            self.executor.shutdown(wait=True)
            self.db_executor.shutdown(wait=True)
            logger.info("线程池已关闭")
        except Exception as e:
            logger.error(f"关闭线程池时出错: {e}")
        
        # 关闭数据库连接
        try:
            self.db.close()
            logger.info("数据库连接已关闭")
        except Exception as e:
            logger.error(f"关闭数据库时出错: {e}")
        
        logger.info("[SHUTDOWN COMPLETE] 调度器已完全关闭")
    
    def get_task_status(self) -> Dict[str, Any]:
        """获取所有任务的状态
        
        Returns:
            dict: 任务ID -> 任务信息的映射
        """
        jobs = self.scheduler.get_jobs()
        status = {}
        
        for job in jobs:
            status[job.id] = {
                'name': job.name,
                'next_run_time': job.next_run_time.isoformat() if job.next_run_time else None,
                'trigger': str(job.trigger)
            }
        
        return status


# ==================== 便捷函数 ====================

def create_and_start_scheduler():
    """创建并启动调度器
    
    便捷函数，用于快速启动系统。
    
    Usage:
        from main_scheduler import create_and_start_scheduler
        create_and_start_scheduler()
    """
    scheduler = MainScheduler()
    scheduler.start()


if __name__ == "__main__":
    # 直接运行时启动调度器
    create_and_start_scheduler()
