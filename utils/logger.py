"""
多源共振监控系统 - 日志管理模块

提供统一的日志记录功能，支持：
- 分级日志输出 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
- 同时输出到控制台和文件
- 按日期分割日志文件
- 错误日志单独记录
- 结构化日志格式 (OpenCLAW Web UI 风格)
- StructuredFormatter: 适合 Web 控制台终端的对齐列格式

使用示例:
    from utils.logger import getLogger, StructuredFormatter
    
    logger = getLogger('data_fetchers')
    logger.info('开始获取数据...')
    logger.error('数据获取失败', exc_info=True)
"""

import logging
import sys
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Optional


# 日志目录
LOG_DIR = Path('./logs')
LOG_DIR.mkdir(exist_ok=True)

# 日志格式 (文件)
LOG_FORMAT = '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# OpenCLAW Web UI 结构化格式 (控制台)
STRUCTURED_FORMAT = '[%(asctime)s] [%(levelname)-7s] [%(source)-8s] %(message)s'
STRUCTURED_DATE_FORMAT = '%H:%M:%S'

# 日志级别映射
LOG_LEVELS = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL,
}

# 级别颜色/图标标记 (OpenCLAW 风格)
LEVEL_MARKERS = {
    'DEBUG':    '·',
    'INFO':     ' ',  # 普通信息无标记
    'WARNING':  '⚠',
    'ERROR':    '✗',
    'CRITICAL': '‼',
}


class StructuredFormatter(logging.Formatter):
    """OpenCLAW Web UI 风格的结构化日志格式化器
    
    输出对齐列格式，适合在 Web 控制台终端中渲染：
      [14:30:00] [  INFO  ] [GEX/DIX ] 消息内容
      [14:30:01] [  WARN  ] [VIX     ] ⚠ 警告消息
      [14:30:02] [ ERROR  ] [AXLFI   ] ✗ 错误消息
    
    使用方式:
        handler = logging.StreamHandler()
        handler.setFormatter(StructuredFormatter())
        logger.addHandler(handler)
    """

    LEVEL_WIDTH = 7     # "  INFO  "
    SOURCE_WIDTH = 8    # "GEX/DIX "

    def __init__(self, fmt: Optional[str] = None, datefmt: Optional[str] = None):
        super().__init__(
            fmt=fmt or STRUCTURED_FORMAT,
            datefmt=datefmt or STRUCTURED_DATE_FORMAT,
        )

    def format(self, record: logging.LogRecord) -> str:
        # 注入 source 字段 (如果 record 没有，使用 name 截断)
        source = getattr(record, 'source', None)
        if source is None:
            source = record.name[:self.SOURCE_WIDTH]
        record.source = source.ljust(self.SOURCE_WIDTH)[:self.SOURCE_WIDTH]

        # 添加级别标记
        marker = LEVEL_MARKERS.get(record.levelname, '')
        original_msg = record.getMessage()
        if marker.strip():
            record._original_msg = original_msg
            record.args = ()  # 清除 args 避免二次格式化
            record.msg = f"{marker} {original_msg}"

        return super().format(record)

    def formatTime(self, record: logging.LogRecord, datefmt: Optional[str] = None) -> str:
        """使用短时间格式 HH:MM:SS"""
        ct = datetime.fromtimestamp(record.created)
        if datefmt:
            return ct.strftime(datefmt)
        return ct.strftime(STRUCTURED_DATE_FORMAT)


class LoggerManager:
    """日志管理器
    
    单例模式管理所有logger实例，确保日志配置的一致性。
    """
    
    _instance: Optional['LoggerManager'] = None
    _loggers: dict = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self.default_level = logging.INFO
    
    def get_logger(self, name: str, level: Optional[str] = None, structured: bool = False) -> logging.Logger:
        """获取或创建logger实例
        
        Args:
            name: logger名称，通常为模块名
            level: 日志级别字符串，默认为配置的级别
            structured: 是否使用 OpenCLAW 结构化格式 (控制台输出)
            
        Returns:
            logging.Logger: 配置好的logger实例
        """
        cache_key = f"{name}__{'structured' if structured else 'plain'}"
        if cache_key in self._loggers:
            return self._loggers[cache_key]
        
        # 创建logger
        logger = logging.getLogger(cache_key)
        
        # 设置日志级别
        log_level = LOG_LEVELS.get(
            level or self._get_config_level(), 
            logging.INFO
        )
        logger.setLevel(log_level)
        
        # 避免重复添加handler
        if logger.handlers:
            self._loggers[cache_key] = logger
            return logger
        
        # 创建formatter — 根据 structured 模式选择
        if structured:
            console_formatter = StructuredFormatter()
        else:
            console_formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
        
        file_formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
        
        # 控制台handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        
        # 文件handler - 所有日志
        today = datetime.now().strftime('%Y%m%d')
        all_log_file = LOG_DIR / f'app_{today}.log'
        file_handler = RotatingFileHandler(
            all_log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
        
        # 文件handler - 仅错误日志
        error_log_file = LOG_DIR / f'error_{today}.log'
        error_handler = RotatingFileHandler(
            error_log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(file_formatter)
        logger.addHandler(error_handler)
        
        self._loggers[cache_key] = logger
        return logger
    
    @staticmethod
    def _get_config_level() -> str:
        """从配置获取日志级别
        
        Returns:
            str: 日志级别字符串
        """
        try:
            from config.settings import Config
            return Config.LOG_LEVEL
        except ImportError:
            return 'INFO'
    
    def set_level(self, level: str):
        """动态修改所有logger的日志级别
        
        Args:
            level: 日志级别字符串
        """
        if level not in LOG_LEVELS:
            raise ValueError(f"Invalid log level: {level}")
        
        log_level = LOG_LEVELS[level]
        self.default_level = log_level
        
        for logger in self._loggers.values():
            logger.setLevel(log_level)
            for handler in logger.handlers:
                if isinstance(handler, logging.StreamHandler):
                    handler.setLevel(log_level)


# 全局logger管理器实例
_logger_manager = LoggerManager()


def getLogger(name: str, level: Optional[str] = None, structured: bool = False) -> logging.Logger:
    """获取logger实例的便捷函数
    
    Args:
        name: logger名称，通常为模块名
        level: 日志级别字符串，可选
        structured: 是否使用 OpenCLAW 结构化格式 (控制台)  
        
    Returns:
        logging.Logger: 配置好的logger实例
        
    Examples:
        >>> logger = getLogger('data_fetchers')
        >>> logger.info('系统启动')
        [2026-06-09 10:30:00] [INFO] [data_fetchers] 系统启动
        
        >>> cli = getLogger('collect', structured=True)
        >>> cli.info('开始采集')
        [10:30:00] [  INFO  ] [collect ] 开始采集
    """
    return _logger_manager.get_logger(name, level, structured=structured)


def setLogLevel(level: str):
    """动态修改日志级别
    
    Args:
        level: 日志级别字符串 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
        
    Examples:
        >>> setLogLevel('DEBUG')  # 启用调试日志
    """
    _logger_manager.set_level(level)


# 模块加载时自动配置根logger
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt=DATE_FORMAT,
)
