"""
多源共振监控系统 - 日志管理模块

提供统一的日志记录功能，支持：
- 分级日志输出 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
- 同时输出到控制台和文件
- 按日期分割日志文件
- 错误日志单独记录
- 结构化日志格式

使用示例:
    from utils.logger import getLogger
    
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

# 日志格式
LOG_FORMAT = '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# 日志级别映射
LOG_LEVELS = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL,
}


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
    
    def get_logger(self, name: str, level: Optional[str] = None) -> logging.Logger:
        """获取或创建logger实例
        
        Args:
            name: logger名称，通常为模块名
            level: 日志级别字符串，默认为配置的级别
            
        Returns:
            logging.Logger: 配置好的logger实例
        """
        if name in self._loggers:
            return self._loggers[name]
        
        # 创建logger
        logger = logging.getLogger(name)
        
        # 设置日志级别
        log_level = LOG_LEVELS.get(
            level or self._get_config_level(), 
            logging.INFO
        )
        logger.setLevel(log_level)
        
        # 避免重复添加handler
        if logger.handlers:
            self._loggers[name] = logger
            return logger
        
        # 创建formatter
        formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
        
        # 控制台handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
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
        file_handler.setFormatter(formatter)
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
        error_handler.setFormatter(formatter)
        logger.addHandler(error_handler)
        
        self._loggers[name] = logger
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


def getLogger(name: str, level: Optional[str] = None) -> logging.Logger:
    """获取logger实例的便捷函数
    
    Args:
        name: logger名称，通常为模块名
        level: 日志级别字符串，可选
        
    Returns:
        logging.Logger: 配置好的logger实例
        
    Examples:
        >>> logger = getLogger('data_fetchers')
        >>> logger.info('系统启动')
        [2026-06-09 10:30:00] [INFO] [data_fetchers] 系统启动
    """
    return _logger_manager.get_logger(name, level)


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
