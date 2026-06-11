"""
多源共振监控系统 — 数据源质量状态模型

定义统一的数据源质量状态枚举、错误分类和报告数据结构，
作为从数据获取层到 Layer 1/2/3 全链路质量标志传递的契约基础。

规范依据: DATA_INGESTION_SPECS §2 通用原则、§3.5 数据输出与质量标志
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any


# ═══════════════════════════════════════════════════════════════
# 数据源状态枚举
# ═══════════════════════════════════════════════════════════════

class SourceStatus(str, Enum):
    """数据源可用状态 (规范 §5.1 可用源状态模型)

    五种状态对应不同降级行为:
    - OK: 数据符合契约，可正常参与投票/评分
    - DEGRADED_NETWORK: 存在网络异常但解析成功，可参与评分但监控中单独统计
    - STRUCTURE_CHANGED: DOM/XHR 结构变更，数据存在不确定性，不参与正式投票
    - CONTRACT_VIOLATION: 违背数值或格式契约，不可参与评分
    - UNAVAILABLE: 完全无法获取数据
    """
    OK = "OK"
    DEGRADED_NETWORK = "DEGRADED_NETWORK"
    STRUCTURE_CHANGED = "STRUCTURE_CHANGED"
    CONTRACT_VIOLATION = "CONTRACT_VIOLATION"
    UNAVAILABLE = "UNAVAILABLE"

    @property
    def is_available(self) -> bool:
        """是否可参与评分 (OK 或 DEGRADED_NETWORK)"""
        return self in (SourceStatus.OK, SourceStatus.DEGRADED_NETWORK)

    @property
    def is_blocking(self) -> bool:
        """是否为阻塞性错误 (数据不可用)"""
        return self in (
            SourceStatus.STRUCTURE_CHANGED,
            SourceStatus.CONTRACT_VIOLATION,
            SourceStatus.UNAVAILABLE,
        )


class ErrorCategory(str, Enum):
    """错误分类 (规范 §2 通用原则)

    用于驱动不同的重试策略:
    - NETWORK: 可重试 (超时、连接被重置、5xx)
    - STRUCTURE: 禁止重试 (DOM节点不存在、JSON字段缺失)
    - CONTRACT: 禁止重试 (列缺失、格式错误、数值超范围)
    - UNKNOWN: 未分类（保守处理，不重试）
    """
    NETWORK = "NETWORK"
    STRUCTURE = "STRUCTURE"
    CONTRACT = "CONTRACT"
    UNKNOWN = "UNKNOWN"

    @property
    def is_retryable(self) -> bool:
        """是否可重试 (规范 §3.3: 仅网络类异常启用重试)"""
        return self == ErrorCategory.NETWORK


# ═══════════════════════════════════════════════════════════════
# 质量报告数据结构
# ═══════════════════════════════════════════════════════════════

@dataclass
class SourceQualityReport:
    """数据源质量报告 (规范 §3.5 数据输出与质量标志)

    每个数据源在一次获取后输出本结构，供 Layer 1 聚合、Layer 2 网关
    和 Layer 3 LLM 上下文使用。

    Attributes:
        source_name: 数据源标识 (如 'squeezemetrics', 'axlfi', 'stockgrid')
        status: 当前状态
        error_category: 错误分类 (用于重试决策)
        last_verified_at: 最后人工验证时间
        structure_hash: DOM/XHR 结构哈希 (仅 Stockgrid)
        structure_hash_changed: 结构哈希是否变更
        latency_ms: 本次获取延迟 (毫秒)
        error_detail: 错误详情
    """
    source_name: str
    status: SourceStatus = SourceStatus.OK
    error_category: ErrorCategory = ErrorCategory.UNKNOWN
    last_verified_at: Optional[str] = None
    structure_hash: str = ""
    structure_hash_changed: bool = False
    latency_ms: float = 0.0
    error_detail: str = ""
    fetch_timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def is_available(self) -> bool:
        """Source name alias: 是否可用于评分"""
        return self.status.is_available

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典 (用于 JSON 序列化和 Layer 2 传递)"""
        return {
            "source_name": self.source_name,
            "status": self.status.value,
            "error_category": self.error_category.value,
            "last_verified_at": self.last_verified_at,
            "structure_hash_changed": self.structure_hash_changed,
            "latency_ms": self.latency_ms,
            "error_detail": self.error_detail[:500] if self.error_detail else "",
            "fetch_timestamp": self.fetch_timestamp,
        }


# ═══════════════════════════════════════════════════════════════
# 错误分类函数
# ═══════════════════════════════════════════════════════════════

def classify_error(exception: Exception, source_name: str = "") -> ErrorCategory:
    """根据异常类型自动分类错误 (规范 §2 通用原则)

    分类规则:
    - 网络类: Timeout, ConnectionError, HTTPError(5xx), RequestException
    - 结构类: KeyError, IndexError (JSON/DOM 解析失败), AttributeError
    - 契约类: ValueError (格式错误), 自定义 DataFetchError
    - 其它: UNKNOWN

    Args:
        exception: 捕获的异常对象
        source_name: 数据源名称 (用于日志上下文)

    Returns:
        ErrorCategory: 错误分类
    """
    from requests.exceptions import (
        Timeout, ConnectionError as ReqConnectionError,
        HTTPError, RequestException,
    )

    exc_type = type(exception)
    exc_str = str(exception).lower()

    # ── 网络类 ──
    if issubclass(exc_type, (Timeout, ReqConnectionError, ConnectionError)):
        return ErrorCategory.NETWORK
    if issubclass(exc_type, HTTPError):
        # 5xx → 网络类, 4xx → 契约类
        if hasattr(exception, 'response') and exception.response is not None:
            status_code = exception.response.status_code
            return ErrorCategory.NETWORK if 500 <= status_code < 600 else ErrorCategory.CONTRACT
        return ErrorCategory.NETWORK
    if issubclass(exc_type, RequestException):
        return ErrorCategory.NETWORK

    # ── 结构类 (JSON/DOM 解析失败) ──
    if issubclass(exc_type, (KeyError, IndexError, AttributeError, TypeError)):
        return ErrorCategory.STRUCTURE

    # ── 契约类 (格式/数值错误) ──
    if issubclass(exc_type, ValueError):
        return ErrorCategory.CONTRACT

    # ── 自定义异常 ──
    if 'DataFetchError' in exc_type.__name__:
        if any(kw in exc_str for kw in ('timeout', 'connect', 'network', '5xx', '503')):
            return ErrorCategory.NETWORK
        if any(kw in exc_str for kw in ('parse', 'json', 'dom', 'column', 'missing')):
            return ErrorCategory.STRUCTURE
        return ErrorCategory.CONTRACT

    return ErrorCategory.UNKNOWN


# ═══════════════════════════════════════════════════════════════
# 结构哈希工具
# ═══════════════════════════════════════════════════════════════

def compute_structure_hash(
    elements: Dict[str, str],
    algorithm: str = "sha256",
) -> str:
    """为 DOM/XHR 结构生成哈希指纹 (规范 §3.4 DOM结构哈希监控)

    哈希源包括标签名、class列表、关键属性和简化子树轮廓。
    用于检测目标站点改版。

    Args:
        elements: 关键DOM元素的描述字典 {名称: 选择器/内容摘要}
        algorithm: 哈希算法

    Returns:
        十六进制哈希字符串
    """
    ordered_keys = sorted(elements.keys())
    source = "|".join(f"{k}={elements[k]}" for k in ordered_keys)
    h = hashlib.new(algorithm)
    h.update(source.encode("utf-8"))
    return h.hexdigest()[:16]  # 截取前16位便于日志


def check_hash_change(
    current_hash: str,
    previous_hash: str,
    source_name: str = "",
) -> Dict[str, Any]:
    """检查结构哈希是否变更

    Args:
        current_hash: 当前抓取计算的哈希
        previous_hash: 上次成功抓取的哈希 (空字符串表示首次)
        source_name: 数据源名称

    Returns:
        {"changed": bool, "previous": str, "current": str}
    """
    if not previous_hash:
        return {"changed": False, "previous": "", "current": current_hash}

    changed = current_hash != previous_hash
    return {
        "changed": changed,
        "previous": previous_hash,
        "current": current_hash,
    }
