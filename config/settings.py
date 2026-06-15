"""
多源共振监控系统 - 配置管理模块

该模块负责加载和管理系统的所有配置参数，包括：
- API密钥和认证信息
- 数据抓取频率设置
- 信号触发阈值
- 系统路径和日志配置

使用dotenv从.env文件加载环境变量，提供类型安全的配置访问接口。
"""

import os
from pathlib import Path
from typing import List, Optional
import os as _os
from pathlib import Path as _Path
from dotenv import load_dotenv

# 加载环境变量 — 使用项目根目录绝对路径确保任何 CWD 都能找到 .env
_ENV_FILE = _Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=str(_ENV_FILE))


class Config:
    """系统配置类
    
    集中管理所有配置参数，支持从环境变量读取敏感信息。
    所有配置项都有默认值，确保系统在缺少环境变量时仍可运行。
    """
    
    # ==================== API配置 ====================
    
    # Tradier API配置 (用于获取期权链和暗盘数据)
    # 生产环境: 需要真实Tradier账户API密钥,实时数据
    # 沙箱环境: 免费注册获得沙箱令牌,延迟15分钟数据
    TRADIER_API_KEY: str = os.getenv('TRADIER_API_KEY', '')
    TRADIER_ACCOUNT_ID: str = os.getenv('TRADIER_ACCOUNT_ID', '')
    TRADIER_SANDBOX_MODE: bool = os.getenv('TRADIER_SANDBOX_MODE', '').lower() in ('true', '1', 'yes')
    TRADIER_SANDBOX_TOKEN: str = os.getenv('TRADIER_SANDBOX_TOKEN', '')
    TRADIER_BASE_URL: str = 'https://api.tradier.com/v1'
    TRADIER_SANDBOX_URL: str = 'https://sandbox.tradier.com/v1'
    
    # Hyperliquid DEX API (去中心化衍生品, 完全免费, 无需API Key, 不屏蔽美国IP)
    # 目前最大的衍生品DEX, 交易量全球前三
    # API完全开放: POST https://api.hyperliquid.xyz/info
    HYPERLIQUID_BASE_URL: str = 'https://api.hyperliquid.xyz/info'
    
    # CCData (原 CryptoCompare) API配置 (CEX衍生品数据, Free Tier 10万次/月)
    # 免费注册: https://developers.coindesk.com/
    # 老牌加密数据商, 覆盖头部交易所 Funding Rate / OI / Liquidation
    CCDATA_API_KEY: str = os.getenv('CCDATA_API_KEY', '')
    CCDATA_BASE_URL: str = 'https://data-api.cryptocompare.com'
    
    # Coinglass API配置 (已弃用, 保留兼容)
    # 原用于全网加密衍生品聚合, 已替换为 Hyperliquid + CCData 降级链路
    COINGLASS_API_KEY: str = os.getenv('COINGLASS_API_KEY', '')
    COINGLASS_BASE_URL: str = 'https://open-api-v4.coinglass.com'
    
    # yfinance 做空数据 (免费, 无需API Key, 替代已删除的FMP)
    # 通过 yfinance.Ticker(symbol).info 获取 shortPercentOfFloat / shortRatio / sharesShort
    # 无需额外配置, yfinance 已在 requirements.txt 中
    
    # SqueezeMetrics API配置 (用于获取DIX/GEX指标)
    SQUEEZEMETRICS_API_KEY: str = os.getenv('SQUEEZEMETRICS_API_KEY', '')
    SQUEEZEMETRICS_BASE_URL: str = 'https://api.squeezemetrics.com'
    
    # ==================== LLM 推理配置 (V2.0 Layer 3) ====================
    
    # LLM Provider 选择: 'openai' / 'anthropic' / 'local'
    LLM_PROVIDER: str = os.getenv('LLM_PROVIDER', 'openai')
    
    # OpenAI 配置
    OPENAI_API_KEY: str = os.getenv('OPENAI_API_KEY', '')
    OPENAI_MODEL: str = os.getenv('OPENAI_MODEL', 'gpt-4o')
    OPENAI_ORGANIZATION: str = os.getenv('OPENAI_ORGANIZATION', '')
    OPENAI_BASE_URL: str = os.getenv('OPENAI_BASE_URL', '')
    
    # Anthropic 配置
    ANTHROPIC_API_KEY: str = os.getenv('ANTHROPIC_API_KEY', '')
    ANTHROPIC_MODEL: str = os.getenv('ANTHROPIC_MODEL', 'claude-sonnet-4-20250514')
    ANTHROPIC_BASE_URL: str = os.getenv('ANTHROPIC_BASE_URL', '')
    
    # LLM 通用参数
    LLM_TEMPERATURE: float = float(os.getenv('LLM_TEMPERATURE', '0.3'))
    LLM_MAX_TOKENS: int = int(os.getenv('LLM_MAX_TOKENS', '2000'))
    LLM_TIMEOUT: int = int(os.getenv('LLM_TIMEOUT', '60'))
    LLM_MAX_RETRIES: int = int(os.getenv('LLM_MAX_RETRIES', '3'))
    
    # ==================== 通知配置 ====================
    
    # SMTP邮件配置
    SMTP_SERVER: str = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT: int = int(os.getenv('SMTP_PORT', '587'))
    EMAIL_SENDER: str = os.getenv('EMAIL_SENDER', '')
    EMAIL_PASSWORD: str = os.getenv('EMAIL_PASSWORD', '')
    EMAIL_RECIPIENTS: List[str] = [
        email.strip() 
        for email in os.getenv('EMAIL_RECIPIENTS', '').split(',') 
        if email.strip()
    ]
    
    # Telegram Bot配置 (可选)
    TELEGRAM_BOT_TOKEN: str = os.getenv('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID: str = os.getenv('TELEGRAM_CHAT_ID', '')
    
    # Discord Webhook配置 (可选)
    DISCORD_WEBHOOK_URL: str = os.getenv('DISCORD_WEBHOOK_URL', '')
    
    # ==================== 抓取频率配置 (每日定时批量模式) ====================
    # v2.2: 盘中高频轮询已移除。系统现为每日单次批量采集模式，
    # 每天美东 20:00 统一拉取全部 6 数据源并触发共振评分。
    
    # 每日批量采集时间 (美东)
    DAILY_BATCH_TIME: tuple = (20, 0)  # 20:00 ET
    
    # 盘中监控频率 (秒) — [DEPRECATED] 盘中轮询已停用
    INTRADAY_FETCH_INTERVAL: int = 900  # deprecated: 盘中15分钟轮询已移除
    
    # 盘后监控时间点 (小时, 分钟) — [DEPRECATED] 已统一为 DAILY_BATCH_TIME
    AFTER_HOURS_FETCH_TIME: tuple = (20, 0)  # deprecated: 统一到 DAILY_BATCH_TIME
    
    # 开盘前准备时间 (分钟) — [DEPRECATED]
    PRE_MARKET_PREP_MINUTES: int = 30  # deprecated
    
    # ==================== 信号阈值配置 ====================
    
    # DIX (Dark Index) 阈值 - 暗盘活动强度指标
    DIX_THRESHOLD: float = 45.0
    
    # Short Volume 阈值 - 空头成交量占比
    SHORT_VOLUME_THRESHOLD: float = 45.0
    
    # GEX (Gamma Exposure) 阈值 - Gamma风险暴露
    GEX_THRESHOLD: float = 1000000.0  # 1M美元
    
    # 背离检测窗口期 (天数)
    DIVERGENCE_WINDOW: int = 5
    
    # 信号强度最小值 (0-100)
    MIN_SIGNAL_STRENGTH: float = 60.0
    
    # ==================== 数据库配置 ====================
    
    # SQLite数据库路径
    DATABASE_PATH: str = os.getenv('DATABASE_PATH', './database/monitoring.db')
    
    # ==================== 日志配置 ====================
    
    # 日志级别: DEBUG, INFO, WARNING, ERROR, CRITICAL
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    
    # 日志目录
    LOG_DIR: str = './logs'
    
    # ==================== 交易时段配置 ====================
    
    # 美股交易时段 (美东时间)
    MARKET_OPEN: tuple = (9, 30)   # 09:30
    MARKET_CLOSE: tuple = (16, 0)  # 16:00
    
    # 盘前交易时段
    PRE_MARKET_OPEN: tuple = (4, 0)   # 04:00
    PRE_MARKET_CLOSE: tuple = (9, 30) # 09:30
    
    # 盘后交易时段
    AFTER_HOURS_OPEN: tuple = (16, 0)  # 16:00
    AFTER_HOURS_CLOSE: tuple = (20, 0) # 20:00
    
    # ==================== 监控标的配置 ====================
    
    # 默认监控股票列表 (可扩展)
    DEFAULT_TICKERS: List[str] = [
        'SPY',   # S&P 500 ETF
        'QQQ',   # Nasdaq-100 ETF
        'IWM',   # Russell 2000 ETF
        'AAPL',  # Apple Inc.
        'MSFT',  # Microsoft Corp.
        'NVDA',  # NVIDIA Corp.
        'TSLA',  # Tesla Inc.
        'AMD',   # Advanced Micro Devices
    ]
    
    # ==================== 管道配置 (V2.0) ====================
    
    # 流水线输出目录
    PIPELINE_OUTPUT_DIR: str = os.getenv('PIPELINE_OUTPUT_DIR', './reports')
    
    # 回测历史天数
    PIPELINE_HISTORY_DAYS: int = int(os.getenv('PIPELINE_HISTORY_DAYS', '90'))
    
    # 并行工作数
    PIPELINE_PARALLEL_WORKERS: int = int(os.getenv('PIPELINE_PARALLEL_WORKERS', '4'))
    
    # ==================== 系统配置 ====================
    
    # 最大重试次数
    MAX_RETRIES: int = 3
    
    # 请求超时时间 (秒)
    REQUEST_TIMEOUT: int = 30
    
    # 数据缓存时间 (秒)
    CACHE_TTL: int = 300  # 5分钟
    
    # ==================== 阈值配置 ====================
    
    class Thresholds:
        """系统阈值配置
        
        集中管理所有业务逻辑中的魔法数字,便于统一调整和测试。
        包含GEX计算、VIX分析、加密市场、暗盘指标和信号评分等模块的阈值参数。
        """
        
        # GEX计算相关阈值
        GEX_RISK_FREE_RATE: float = 0.05  # 无风险利率(5%)
        GEX_CONTRACT_MULTIPLIER: int = 100  # 期权合约乘数(100股/合约)
        GEX_VOLATILITY_MIN: float = 0.01  # 最小波动率(1%)
        GEX_VOLATILITY_MAX: float = 5.0  # 最大波动率(500%)
        GEX_TIME_TO_EXPIRY_MIN: float = 1e-10  # 最小到期时间(防止除零)
        
        # VIX期限结构阈值
        VIX_CONTANGO_THRESHOLD: float = 0.95  # Contango状态阈值(VX1/VX2 < 0.95)
        VIX_BACKWARDATION_THRESHOLD: float = 1.05  # Backwardation状态阈值(VX1/VX2 > 1.05)
        VIX_EXTREME_BACKWARDATION: float = 1.15  # 极端Backwardation阈值(恐慌状态)
        VIX_PANIC_PREMIUM: float = 1.15  # 恐慌溢价阈值(与EXTREME_BACKWARDATION相同)
        
        # 加密市场阈值
        FUNDING_RATE_ANOMALY: float = -0.0001  # 资金费率异常阈值(-0.01%)
        OI_CRASH_PERCENTAGE: float = 15.0  # OI暴跌阈值(15%)
        ELR_SAFE_LEVEL: float = 0.2  # ELR安全水平(相对历史均值)
        
        # 暗盘指标阈值
        DIX_SIGNAL_THRESHOLD: float = 45.0  # DIX吸筹线(%)
        SHORT_VOLUME_THRESHOLD: float = 45.0  # 卖空比吸筹线(%)
        CONSECUTIVE_DAYS_REQUIRED: int = 2  # 连续天数要求
        
        # 信号评分阈值
        SIGNAL_COOLDOWN_MINUTES: int = 30  # 信号冷却期(分钟)
        LEVEL_3_THRESHOLD: float = 3.5  # LEVEL 3共振阈值(满分5.0)
        LEVEL_2_THRESHOLD: float = 3.0  # LEVEL 2共振阈值
        LEVEL_1_THRESHOLD: float = 2.0  # LEVEL 1共振阈值
        MAX_RESONANCE_SCORE: float = 5.0  # 共振满分
        
        # Hawkes Process阈值
        HAWKES_SUBCRITICAL: float = 0.7  # 亚临界分支比(<0.7为安全区)
        HAWKES_CRITICAL: float = 0.9  # 临界分支比(0.7-0.9为警戒区)
        HAWKES_WINDOW_MINUTES: int = 60  # 时间窗口(分钟)
    
    @classmethod
    def validate(cls) -> List[str]:
        """验证配置完整性
        
        Returns:
            List[str]: 缺失的必要配置项列表，空列表表示配置完整
        """
        missing = []
        warnings = []
        
        # 检查必要的API密钥 (沙箱模式下使用TRADIER_SANDBOX_TOKEN)
        if not cls.TRADIER_API_KEY:
            if cls.TRADIER_SANDBOX_MODE:
                if not cls.TRADIER_SANDBOX_TOKEN:
                    warnings.append("Tradier沙箱模式已启用,但TRADIER_SANDBOX_TOKEN未配置")
                else:
                    warnings.append("Tradier沙箱模式已启用,使用延迟15分钟的免费数据")
            else:
                warnings.append("TRADIER_API_KEY未配置, GEX计算不可用")
        
        if not cls.SQUEEZEMETRICS_API_KEY:
            warnings.append("SQUEEZEMETRICS_API_KEY未配置,暗盘指标将通过公开CSV免费获取(已内置支持)")
        
        if not cls.CCDATA_API_KEY:
            warnings.append("CCDATA_API_KEY未配置,加密数据将依赖Hyperliquid DEX (CCData Free Tier 10万次/月)")
        else:
            warnings.append(f"CCData API Key已配置(...{cls.CCDATA_API_KEY[-6:]}), CEX衍生品数据可用")
        
        if not cls.COINGLASS_API_KEY:
            warnings.append("COINGLASS_API_KEY未配置 (已弃用, 保留兼容)")
        
        # yfinance 做空数据 (免费, 无需API Key)
        try:
            import yfinance
            warnings.append("yfinance 库可用, 做空数据获取就绪 (shortPercentOfFloat/shortRatio/sharesShort)")
        except ImportError:
            warnings.append("yfinance 库未安装, 做空数据获取将失败 (请 pip install yfinance)")
        
        # 检查通知配置 (至少需要一种通知方式)
        if not cls.EMAIL_RECIPIENTS and not cls.TELEGRAM_BOT_TOKEN:
            warnings.append("邮件和Telegram配置均未设置,告警推送将失败")
        
        if not cls.EMAIL_SENDER or not cls.EMAIL_PASSWORD:
            warnings.append("邮件配置不完整,SMTP告警将失败")
        
        if not cls.TELEGRAM_BOT_TOKEN or not cls.TELEGRAM_CHAT_ID:
            warnings.append("Telegram配置不完整,可选功能将禁用")
        
        if not cls.DISCORD_WEBHOOK_URL:
            warnings.append("Discord Webhook URL未配置, Discord告警将禁用")
        else:
            warnings.append("Discord Webhook 已配置, 告警可推送")
        
        # 输出警告
        if warnings:
            import logging
            logger = logging.getLogger('config_validation')
            for warning in warnings:
                logger.warning(warning)
        
        return missing
    
    @classmethod
    def is_market_hours(cls) -> bool:
        """判断当前是否为交易时段 (美东时间)
        
        Returns:
            bool: True为交易时段，False为非交易时段
        """
        from datetime import datetime
        import pytz
        
        # 获取美东时间
        eastern = pytz.timezone('US/Eastern')
        now = datetime.now(eastern)
        
        current_minutes = now.hour * 60 + now.minute
        open_minutes = cls.MARKET_OPEN[0] * 60 + cls.MARKET_OPEN[1]
        close_minutes = cls.MARKET_CLOSE[0] * 60 + cls.MARKET_CLOSE[1]
        
        return open_minutes <= current_minutes < close_minutes
    
    @classmethod
    def get_next_fetch_time(cls) -> str:
        """计算下次批量采集时间
        
        每日美东 20:00。若当前时间已过今天 20:00，返回明天 20:00。
        
        Returns:
            str: 下次采集的 ISO 格式时间字符串
        """
        from datetime import datetime, timedelta
        import pytz
        
        eastern = pytz.timezone('US/Eastern')
        now = datetime.now(eastern)
        
        hour, minute = cls.DAILY_BATCH_TIME
        next_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        if next_time <= now:
            next_time += timedelta(days=1)
        
        return next_time.isoformat()


class StreamConfig:
    """Push 实时流架构配置
    
    WebSocket 连接、自动重连、Ping 保活等参数。
    """
    
    # Hyperliquid WebSocket
    HYPERLIQUID_WS_URL: str = "wss://api.hyperliquid.xyz/ws"
    
    # 自动重连参数 (指数退避)
    WS_RECONNECT_MIN_DELAY: int = 1     # 秒
    WS_RECONNECT_MAX_DELAY: int = 60    # 秒
    
    # Ping 保活
    WS_PING_INTERVAL: int = 30          # 秒
    
    # REST 轮询间隔 (非WS源)
    REST_POLL_INTERVAL_INTRADAY: int = 900   # 盘中 15分钟
    REST_POLL_INTERVAL_CRYPTO: int = 60      # 加密降级轮询 1分钟
    
    # 共振评分防抖间隔
    EVAL_COOLDOWN_SECONDS: int = 30


class DataFetchConfig:
    """数据获取层静态端点与选择器配置
    
    将所有推测的端点、DOM选择器抽取为静态配置，与业务逻辑解耦。
    网站改版或API变更时只需修改此处，无需改动业务代码。
    """
    
    # Hyperliquid DEX 端点 (去中心化衍生品, 完全免费)
    HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"
    
    # CCData Futures 端点 (CEX衍生品, Free Tier 10万次/月)
    CCDATA_FUTURES_URL = "https://data-api.cryptocompare.com/futures/v1"
    
    # FINRA 官方每日短卖量文件 (降级备选)
    # 每日美东16:00后更新, 管道分隔格式: Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market
    FINRA_SHORT_VOLUME_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date}.txt"
    
    # Stockgrid XHR 匹配与 DOM 选择器 (已弃用, 保留兼容)
    STOCKGRID_URL = "https://stockgrid.io/darkpool/{symbol}"
    STOCKGRID_XHR_PATTERN = "api/darkpool"
    STOCKGRID_DOM_CHART = ".darkpool-chart"
    STOCKGRID_DOM_TABLE = ".net-position-table"
    
    # SqueezeMetrics 官方公开静态 CSV 地址 (最稳定)
    SQUEEZEMETRICS_CSV_URL = "https://squeezemetrics.com/monitor/static/DIX.csv"
    SQUEEZEMETRICS_GEX_URL = "https://squeezemetrics.com/monitor/static/GEX.csv"


# 创建全局配置实例
config = Config()
