"""
多源共振监控系统 - 自定义异常模块

定义系统专用的异常类层次结构，提供：
- 统一的错误码管理
- 详细的错误上下文信息
- 便于异常捕获和处理的分类体系

使用示例:
    from utils.exceptions import DataFetchError
    
    try:
        data = fetch_market_data()
    except DataFetchError as e:
        logger.error(f"错误 {e.error_code}: {e.details}")
"""

from typing import Optional, Dict, Any


class BaseMonitoringError(Exception):
    """监控系统基础异常类
    
    所有自定义异常的基类，提供错误码和详细信息属性。
    
    Attributes:
        error_code: 错误代码字符串，用于快速识别错误类型
        details: 详细的错误信息字典，包含上下文数据
        message: 人类可读的错误描述
    """
    
    def __init__(
        self, 
        message: str = "", 
        error_code: str = "UNKNOWN_ERROR",
        details: Optional[Dict[str, Any]] = None
    ):
        """初始化基础异常
        
        Args:
            message: 错误描述消息
            error_code: 错误代码标识
            details: 额外的错误上下文信息
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}
    
    def __str__(self) -> str:
        """返回格式化的错误信息"""
        base_str = f"[{self.error_code}] {self.message}"
        if self.details:
            details_str = ", ".join(
                f"{k}={v}" for k, v in self.details.items()
            )
            return f"{base_str} (Details: {details_str})"
        return base_str
    
    def __repr__(self) -> str:
        """返回异常的详细表示"""
        return (
            f"{self.__class__.__name__}("
            f"message='{self.message}', "
            f"error_code='{self.error_code}', "
            f"details={self.details})"
        )


class DataFetchError(BaseMonitoringError):
    """数据获取异常
    
    当从API或数据源获取数据失败时抛出。
    
    Examples:
        >>> raise DataFetchError(
        ...     "无法连接到Tradier API",
        ...     error_code="TRADIER_CONNECTION_FAILED",
        ...     details={"url": "https://api.tradier.com", "timeout": 30}
        ... )
    """
    
    def __init__(
        self, 
        message: str = "数据获取失败", 
        error_code: str = "DATA_FETCH_ERROR",
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message, error_code, details)


class CalculationError(BaseMonitoringError):
    """量化计算异常
    
    当执行量化指标计算或统计分析时发生错误。
    
    Examples:
        >>> raise CalculationError(
        ...     "DIX指标计算失败：数据不足",
        ...     error_code="DIX_CALCULATION_FAILED",
        ...     details={"required_points": 100, "actual_points": 50}
        ... )
    """
    
    def __init__(
        self, 
        message: str = "量化计算失败", 
        error_code: str = "CALCULATION_ERROR",
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message, error_code, details)


class SignalTriggerError(BaseMonitoringError):
    """信号触发异常
    
    当信号引擎处理或触发交易信号时发生错误。
    
    Examples:
        >>> raise SignalTriggerError(
        ...     "信号强度评分超出范围",
        ...     error_code="SIGNAL_STRENGTH_OUT_OF_RANGE",
        ...     details={"strength": 150, "max_allowed": 100}
        ... )
    """
    
    def __init__(
        self, 
        message: str = "信号触发异常", 
        error_code: str = "SIGNAL_TRIGGER_ERROR",
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message, error_code, details)


class DatabaseError(BaseMonitoringError):
    """数据库操作异常
    
    当执行数据库读写操作时发生错误。
    
    Examples:
        >>> raise DatabaseError(
        ...     "无法写入信号记录",
        ...     error_code="DB_WRITE_FAILED",
        ...     details={"table": "signals", "operation": "INSERT"}
        ... )
    """
    
    def __init__(
        self, 
        message: str = "数据库操作失败", 
        error_code: str = "DATABASE_ERROR",
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message, error_code, details)


class ConfigurationError(BaseMonitoringError):
    """配置异常
    
    当系统配置缺失或无效时抛出。
    
    Examples:
        >>> raise ConfigurationError(
        ...     "缺少必要的API密钥",
        ...     error_code="MISSING_API_KEY",
        ...     details={"missing_keys": ["TRADIER_API_KEY"]}
        ... )
    """
    
    def __init__(
        self, 
        message: str = "配置错误", 
        error_code: str = "CONFIGURATION_ERROR",
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message, error_code, details)


class NotificationError(BaseMonitoringError):
    """通知发送异常
    
    当发送邮件、Telegram消息等通知失败时抛出。
    
    Examples:
        >>> raise NotificationError(
        ...     "邮件发送失败",
        ...     error_code="EMAIL_SEND_FAILED",
        ...     details={"recipient": "user@example.com", "smtp_error": "Connection refused"}
        ... )
    """
    
    def __init__(
        self, 
        message: str = "通知发送失败", 
        error_code: str = "NOTIFICATION_ERROR",
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message, error_code, details)


# 异常映射表 - 用于根据错误码快速查找异常类型
EXCEPTION_MAP = {
    'DATA_FETCH': DataFetchError,
    'CALCULATION': CalculationError,
    'SIGNAL': SignalTriggerError,
    'DATABASE': DatabaseError,
    'CONFIGURATION': ConfigurationError,
    'NOTIFICATION': NotificationError,
}


def get_exception_by_code(error_code: str) -> type:
    """根据错误代码前缀获取对应的异常类
    
    Args:
        error_code: 错误代码字符串
        
    Returns:
        type: 对应的异常类，如果未找到则返回BaseMonitoringError
        
    Examples:
        >>> exc_class = get_exception_by_code('DATA_FETCH_TIMEOUT')
        >>> # 返回 DataFetchError
    """
    prefix = error_code.split('_')[0] if '_' in error_code else error_code
    
    for key, exc_class in EXCEPTION_MAP.items():
        if key.startswith(prefix) or prefix.startswith(key):
            return exc_class
    
    return BaseMonitoringError
