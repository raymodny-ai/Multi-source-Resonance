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
    TradierFetcher,  # 保留导入但不再用于 GEX (已替换为 SqueezeMetrics CSV)
    YahooFinanceFetcher,
    CCXTFetcher,
    SqueezeMetricsFetcher,
    ChartExchangeFetcher,
    DBMFFetcher
)
from data_fetchers.axlfi_fetcher import AxlfiFetcher
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
from notification import AlertSender
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
        self.tradier_fetcher = None  # GEX 已替换为 SqueezeMetrics CSV, 不再使用 Tradier
        self.yahoo_fetcher = YahooFinanceFetcher()
        self.ccxt_fetcher = CCXTFetcher()
        self.squeezemetrics_fetcher = SqueezeMetricsFetcher()
        self.chartexchange_fetcher = ChartExchangeFetcher()  # API密钥从config自动读取
        self.axlfi_fetcher = AxlfiFetcher()  # AXLFI 公开API替代已下线Stockgrid
        self.dbmf_fetcher = DBMFFetcher()
        
        # 初始化工具类
        self.gex_calculator = GEXCalculator()
        self.vix_analyzer = VIXAnalyzer()
        self.crypto_cleaner = CryptoLeverageCleaner()
        self.darkpool_verifier = DarkPoolVerifier()
        self.resonance_scorer = ResonanceScorer()
        self.signal_machine = SignalStateMachine(cooldown_minutes=30)
        
        # 初始化告警发送器
        self.alert_sender = AlertSender()
        
        # 初始化降级管理器
        self.fallback_manager = FallbackManager()
        
        logger.info("主调度器初始化完成")
    
    def setup_intraday_tasks(self):
        """设置盘中高频任务(美东时间9:30-16:00,每15分钟执行)
        
        注册5个盘中监控任务:
        - GEX+DIX: 从 SqueezeMetrics 公开 CSV 直接获取 (替代 Tradier)
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
        """任务: 获取 SqueezeMetrics GEX+DIX 指标
        
        从 SqueezeMetrics 公开 CSV 直接获取 GEX 和 DIX，无需 Tradier API。
        DIX.csv 每日更新，包含 SPX 价格 + DIX + GEX 三列。
        """
        try:
            logger.debug("开始执行 SQZ GEX+DIX 获取")
            loop = asyncio.get_event_loop()

            # 从 SqueezeMetrics CSV 获取完整指标 (一次请求，免费)
            metrics = await loop.run_in_executor(
                self.executor,
                self.squeezemetrics_fetcher.get_full_metrics
            )

            if not metrics:
                logger.warning("SqueezeMetrics 数据获取失败")
                self.fallback_manager.record_failure('task_calculate_gex')
                return

            # GEX 数值 (SqueezeMetrics 官方值，无需校准)
            gex_total = metrics['gex']
            # DIX 百分比值
            dix_pct = metrics['dix']
            # SPX 价格
            spx_price = metrics['price']

            # 存入数据库 (put_wall / flip_zone 留空，CSV 不提供逐行权价分布)
            timestamp = datetime.now(pytz.timezone('US/Eastern'))
            await loop.run_in_executor(
                self.db_executor,
                self.db.insert_gex_record,
                timestamp,
                gex_total,        # gex_local
                gex_total,        # gex_calibrated (SqueezeMetrics 即官方值)
                1.0,              # alpha (不需要校准)
                0,                # put_wall (CSV 无逐行权价)
                0,                # flip_zone_lower
                0,                # flip_zone_upper
            )

            self.fallback_manager.reset_failure_count('task_calculate_gex')

            logger.info(
                f"SQZ GEX+DIX: SPX={spx_price:.0f} | "
                f"GEX=\${gex_total/1e9:.2f}B | DIX={dix_pct:.1f}%"
            )

        except Exception as e:
            logger.error(f"SQZ GEX+DIX 失败: {e}", exc_info=True)
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
                
            # 检查数据源可用性（PRD第6节降级逻辑）
            available_sources = await loop.run_in_executor(
                self.executor,
                self._check_data_source_availability
            )
            
            # 使用支持降级逻辑的暗盘评分方法
            darkpool_score = await loop.run_in_executor(
                self.executor,
                lambda: self.resonance_scorer.calculate_darkpool_score_with_fallback(
                    dix_flag=latest_darkpool.get('dix_signal', False) if latest_darkpool else False,
                    short_ratio_flag=latest_darkpool.get('short_ratio_signal', False) if latest_darkpool else False,
                    stockgrid_flag=latest_darkpool.get('stockgrid_signal', False) if latest_darkpool else False,
                    dbmf_recovery=latest_darkpool.get('dbmf_ma5_recovery', False) if latest_darkpool else False,
                    available_sources=available_sources
                )
            )
            
            # ✅ PRD第6节：极端退化时的紧急推送机制
            all_darkpool_down = (
                not available_sources.get('dix', True) and 
                not available_sources.get('short_ratio', True) and 
                not available_sources.get('stockgrid', True)
            )
            if all_darkpool_down:
                logger.critical("[CRITICAL] 所有暗盘爬虫接口触发改版异常!")
                await loop.run_in_executor(
                    self.executor,
                    lambda: self.alert_sender.send_multi_channel_alert(
                        subject="[CRITICAL] 爬虫全线崩溃预警",
                        message=(
                            "场外暗盘所有爬虫接口触发改版异常，"
                            "已退化为纯本地实时衍生品计算流模式，"
                            "请及时排查前端结构。"
                        ),
                        channels=['email', 'telegram']
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
                # 格式化LEVEL 3告警消息（使用alert_sender的格式化方法）
                alert_message = await loop.run_in_executor(
                    self.executor,
                    lambda: self.alert_sender.format_level3_alert(
                        resonance_result=resonance_result,
                        hawkes_result=hawkes_result,
                        current_time=current_time,
                        put_wall_range=None  # TODO: 从GEX数据获取Put Wall区间
                    )
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
                    
                # 多渠道发送告警（邮件 + Telegram）
                logger.warning(f"🚨 {resonance_result['alert_level']} 信号触发! 总分: {resonance_result['total_score']}")
                
                channels_to_use = ['email', 'telegram'] if resonance_result['alert_level'] == 'LEVEL_3' else ['email']
                
                send_results = await loop.run_in_executor(
                    self.executor,
                    lambda: self.alert_sender.send_multi_channel_alert(
                        subject=f"[{resonance_result['alert_level']}] 共振抄底信号触发",
                        message=alert_message,
                        channels=channels_to_use
                    )
                )
                
                # 记录发送结果
                success_count = sum(1 for v in send_results.values() if v)
                logger.info(
                    f"告警发送完成: {success_count}/{len(channels_to_use)} 成功 "
                    f"(结果: {send_results})"
                )
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
        """任务: 获取AXLFI暗盘净头寸
        
        使用axlfi.com公开API获取真实暗盘净头寸和卖空数据，
        检测底背离信号（替代已下线Stockgrid）。
        """
        try:
            logger.info("开始执行AXLFI暗盘数据获取")
            loop = asyncio.get_event_loop()

            # 获取完整数据（暗盘净头寸 + 价格）
            symbol_data = await loop.run_in_executor(
                self.executor,
                lambda: self.axlfi_fetcher.fetch_symbol_data('SPY', 120)
            )

            if not symbol_data:
                logger.warning("AXLFI数据获取失败")
                self.fallback_manager.record_failure('task_fetch_stockgrid')
                return

            dp_position = symbol_data.get('dollar_dp_position', [])
            close_prices = symbol_data.get('close', [])

            if len(dp_position) < 60:
                logger.warning(f"AXLFI数据点不足: {len(dp_position)}个")
                self.fallback_manager.record_failure('task_fetch_stockgrid')
                return

            # 检测底背离（使用真实价格序列）
            divergence_result = await loop.run_in_executor(
                self.executor,
                lambda: self.axlfi_fetcher.detect_bottom_divergence(
                    dp_position[-120:] if len(dp_position) >= 120 else dp_position,
                    close_prices[-120:] if close_prices and len(close_prices) >= 120 else dp_position[-120:]
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

            # 获取最新卖空指标
            latest_dp = symbol_data.get('dollar_dp_position', [])[-1] if dp_position else 0
            short_pct_list = symbol_data.get('short_volume_pct', [])
            latest_short_pct = short_pct_list[-1] if short_pct_list else 0

            # 更新暗盘指标
            await loop.run_in_executor(
                self.db_executor,
                self.db.insert_dark_pool_metrics,
                today,
                latest_dp / 1e9 if latest_dp else 0,  # 转为十亿美元
                latest_short_pct,
                divergence_result.get('slope_20d', 0),
                divergence_result.get('slope_60d', 0),
                divergence_result.get('divergence', False),
                False, False, False, confirmed_signal,
                divergence_result.get('golden_cross', False)
            )

            # 成功后重置失败计数
            self.fallback_manager.reset_failure_count('task_fetch_stockgrid')

            logger.info(
                f"AXLFI暗盘获取完成: DP=¥{latest_dp:,.0f}, "
                f"20d Slope={divergence_result.get('slope_20d', 0):.2f}, "
                f"Divergence={divergence_result.get('divergence')}, "
                f"Golden Cross={divergence_result.get('golden_cross')}"
            )

        except Exception as e:
            logger.error(f"AXLFI暗盘任务失败: {e}", exc_info=True)
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
    
    def _check_data_source_availability(self) -> Dict[str, bool]:
        """检查各暗盘数据源的可用性状态
        
        通过查询数据库最新记录时间戳判断数据源是否可用。
        用于PRD第6节降级逻辑：当某数据源失败时自动放弃该校验。
        
        Returns:
            dict: 各数据源可用性标记
                  {'dix': True/False, 'short_ratio': True/False, 'stockgrid': True/False}
        """
        try:
            loop = asyncio.get_event_loop()
            
            # 获取最新暗盘指标记录
            latest_darkpool = loop.run_until_complete(
                loop.run_in_executor(
                    self.db_executor,
                    self.db.get_latest_dark_pool_metrics
                )
            )
            
            if not latest_darkpool:
                logger.warning("无暗盘数据记录，默认所有源不可用")
                availability = {
                    'dix': False,
                    'short_ratio': False,
                    'stockgrid': False
                }
            else:
                # 检查各字段是否有有效值（非None且非False）
                dix_available = latest_darkpool.get('dix_value') is not None and latest_darkpool.get('dix_signal', False)
                short_ratio_available = latest_darkpool.get('short_ratio') is not None and latest_darkpool.get('short_ratio_signal', False)
                stockgrid_available = latest_darkpool.get('slope_20d') is not None and latest_darkpool.get('stockgrid_signal', False)
                
                availability = {
                    'dix': dix_available,
                    'short_ratio': short_ratio_available,
                    'stockgrid': stockgrid_available
                }
            
            # ✅ PRD第6节要求：检查是否触发极端退化模式，发送CRITICAL告警
            total_available = sum(1 for v in availability.values() if v)
            if total_available == 0:
                critical_msg = (
                    "[CRITICAL] 场外暗盘所有爬虫接口触发改版异常，"
                    "已退化为纯本地实时衍生品计算流模式，请及时排查前端结构。"
                )
                logger.critical(critical_msg)
                
                # 尝试发送CRITICAL告警到所有渠道
                try:
                    loop.run_until_complete(
                        loop.run_in_executor(
                            self.executor,
                            lambda: self.alert_sender.send_multi_channel_alert(
                                subject="[CRITICAL] 暗盘数据源全部失效",
                                message=critical_msg,
                                channels=['email', 'telegram', 'discord']
                            )
                        )
                    )
                    logger.info("CRITICAL告警已发送到所有渠道")
                except Exception as alert_err:
                    logger.critical(f"CRITICAL告警发送失败: {alert_err}")
            
            logger.debug(f"数据源可用性检查完成: {availability}")
            return availability
            
        except Exception as e:
            logger.error(f"数据源可用性检查失败: {e}", exc_info=True)
            # 异常时保守假设全部可用（保持原有行为）
            return {
                'dix': True,
                'short_ratio': True,
                'stockgrid': True
            }
    
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
