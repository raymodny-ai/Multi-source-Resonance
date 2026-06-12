"""
多源共振监控系统 — AXLFI 暗盘数据适配器 (C1)

为 AxlfiFetcher 添加适配层:
- 统一质量标志输出 (SourceQualityReport)
- 错误分类 (网络类重试, 结构类标记 STRUCTURE_CHANGED)
- tenacity 指数退避重试 (仅网络类, 3次: 5s→15s→45s)
- 延迟测量
- 保持原有 AxlfiFetcher 公共接口兼容

规范依据: DATA_INGESTION_SPECS AXLFI 暗盘接入 (Stockgrid 替代)
"""

import logging
import time
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

import requests
from requests.exceptions import Timeout, ConnectionError, HTTPError, RequestException
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from utils.logger import getLogger
from data_fetchers.source_status import (
    SourceStatus,
    ErrorCategory,
    SourceQualityReport,
    classify_error,
)

logger = getLogger('axlfi_adapter')


# ═══════════════════════════════════════════════════════════════
# 重试策略
# ═══════════════════════════════════════════════════════════════

# 网络类异常指数退避: 5s → 15s → 45s, 最多3次
RETRYABLE_EXCEPTIONS = (
    Timeout,
    ConnectionError,
    RequestException,
)


def _is_retryable(exception: Exception) -> bool:
    """判断异常是否可重试（仅网络类）"""
    if isinstance(exception, HTTPError):
        # HTTP 4xx 不重试, 5xx 重试
        if hasattr(exception, 'response') and exception.response is not None:
            code = exception.response.status_code
            return code >= 500
        return True
    return isinstance(exception, RETRYABLE_EXCEPTIONS)


# ═══════════════════════════════════════════════════════════════
# AXLFI 适配器
# ═══════════════════════════════════════════════════════════════

class AxlfiAdapter:
    """AXLFI 暗盘数据适配器

    包装原有 AxlfiFetcher，增加质量报告、错误分类和智能重试。

    使用示例:
        adapter = AxlfiAdapter()
        report = adapter.fetch_with_quality("SPY")
        # report.status → SourceStatus.OK | DEGRADED_NETWORK | STRUCTURE_CHANGED

        # 兼容旧接口
        data = adapter.fetch_symbol_data("SPY")
    """

    def __init__(self):
        from data_fetchers.axlfi_fetcher import AxlfiFetcher
        self._fetcher = AxlfiFetcher()
        self._last_known_structure: Dict[str, Any] = {}

        logger.info("AxlfiAdapter 初始化完成 (live mode)")

    # ── 公开接口: 质量报告 ──

    def fetch_with_quality(self, symbol: str = "SPY", window: int = 252) -> SourceQualityReport:
        """获取暗盘数据并输出质量报告

        Args:
            symbol: 标的代码
            window: 历史窗口天数

        Returns:
            SourceQualityReport: 含状态、延迟、错误分类的完整报告
        """
        start_time = time.time()
        report = SourceQualityReport(source_name="axlfi")

        try:
            data = self._fetch_with_retry(symbol, window)
            report.latency_ms = (time.time() - start_time) * 1000

            if data is None:
                report.status = SourceStatus.UNAVAILABLE
                report.error_category = ErrorCategory.NETWORK
                report.error_detail = f"AXLFI {symbol} 数据获取返回空 (网络或API异常)"
                return report

            # 结构校验: 检查必需字段
            structure_ok, structure_msg = self._validate_structure(data, symbol)
            if not structure_ok:
                report.status = SourceStatus.STRUCTURE_CHANGED
                report.error_category = ErrorCategory.STRUCTURE
                report.error_detail = structure_msg
                return report

            # 数据新鲜度检查
            as_of = data.get('as_of_date', 'unknown')
            report.status = SourceStatus.OK
            report.error_category = ErrorCategory.UNKNOWN
            report.last_verified_at = datetime.now().isoformat()
            report.error_detail = f"OK: {symbol} as_of={as_of}, {len(data.get('dollar_dp_position', []))} data points"

            return report

        except Exception as e:
            report.latency_ms = (time.time() - start_time) * 1000
            report.error_category = classify_error(e, "axlfi")
            report.error_detail = f"{type(e).__name__}: {str(e)[:200]}"

            if report.error_category == ErrorCategory.NETWORK:
                report.status = SourceStatus.DEGRADED_NETWORK
            else:
                report.status = SourceStatus.STRUCTURE_CHANGED

            logger.error(f"AXLFI 适配器异常: {e}")
            return report

    def get_data_with_quality(
        self, symbol: str = "SPY", window: int = 252
    ) -> Tuple[Optional[Dict[str, Any]], SourceQualityReport]:
        """获取业务数据 + 质量报告

        Returns:
            (data_dict, report)
        """
        report = self.fetch_with_quality(symbol, window)

        if report.status.is_available:
            data = self._fetcher.fetch_symbol_data(symbol, window)
        else:
            data = None

        return data, report

    # ── 公开接口: 兼容原有 AxlfiFetcher 方法 ──

    def fetch_symbol_data(self, symbol: str = 'SPY', window: int = 252) -> Optional[Dict[str, Any]]:
        """获取单个标的的暗盘和卖空数据（兼容原接口）"""
        return self._fetcher.fetch_symbol_data(symbol, window)

    def fetch_leaderboard(self, metric: str = 'dollar_dp_position',
                          sort: str = 'desc', limit: int = 20) -> Optional[List[Dict]]:
        """获取暗盘全市场排行榜（兼容原接口）"""
        return self._fetcher.fetch_leaderboard(metric, sort, limit)

    def get_net_position_series(self, symbol: str = 'SPY',
                                periods: List[int] = [20, 60, 120]) -> Optional[Dict[str, List[float]]]:
        """获取暗盘净头寸序列（兼容原 Stockgrid 接口）"""
        return self._fetcher.get_net_position_series(symbol, periods)

    def get_latest_short_metrics(self, symbol: str = 'SPY') -> Dict[str, Any]:
        """获取最新卖空指标（兼容原接口）"""
        return self._fetcher.get_latest_short_metrics(symbol)

    def detect_bottom_divergence(self, net_position_series: List[float],
                                 price_series: List[float]) -> Dict[str, Any]:
        """底背离检测（兼容原接口）"""
        return self._fetcher.detect_bottom_divergence(net_position_series, price_series)

    def is_available(self) -> bool:
        """快速检查数据源是否可用"""
        report = self.fetch_with_quality("SPY", window=5)
        return report.status.is_available

    def get_status_summary(self) -> Dict[str, Any]:
        """获取数据源状态摘要"""
        report = self.fetch_with_quality("SPY", window=5)
        return {
            "source": "axlfi",
            "available": report.status.is_available,
            "status": report.status.value,
            "latency_ms": report.latency_ms,
            "last_verified_at": report.last_verified_at,
            "error_detail": report.error_detail[:200] if report.error_detail else "",
        }

    # ── 私有方法 ──

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=5, max=45),
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _fetch_with_retry(self, symbol: str, window: int) -> Optional[Dict[str, Any]]:
        """带重试的数据获取（仅网络类异常重试）"""
        return self._fetcher.fetch_symbol_data(symbol, window)

    def _validate_structure(self, data: Dict[str, Any], symbol: str) -> Tuple[bool, str]:
        """校验 API 返回数据结构

        Args:
            data: API 返回数据
            symbol: 标的代码

        Returns:
            (is_valid: bool, detail: str)
        """
        # 必需顶层字段
        required_top = ['as_of_date', 'latest']
        missing_top = [k for k in required_top if k not in data]
        if missing_top:
            return False, f"缺失顶层字段: {missing_top}"

        # 暗盘头寸字段
        dp = data.get('individual_dark_pool_position_data', {})
        if isinstance(dp, dict):
            dp_required = ['dates', 'dollar_dp_position']
            missing_dp = [k for k in dp_required if k not in dp]
            if missing_dp:
                return False, f"暗盘头寸缺失字段: {missing_dp}"

            # 检查数据非空
            dp_pos = dp.get('dollar_dp_position', [])
            if not dp_pos or len(dp_pos) == 0:
                return False, f"暗盘头寸数据为空 (symbol={symbol})"

        return True, "结构校验通过"

    def classify_error(self, exception: Exception) -> ErrorCategory:
        """对异常进行分类"""
        return classify_error(exception, "axlfi")


# ═══════════════════════════════════════════════════════════════
# 工厂函数
# ═══════════════════════════════════════════════════════════════

def create_axlfi_adapter() -> AxlfiAdapter:
    """创建 AXLFI 适配器实例"""
    return AxlfiAdapter()
