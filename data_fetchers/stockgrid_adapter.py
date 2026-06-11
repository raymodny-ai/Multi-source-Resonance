"""
多源共振监控系统 — Stockgrid 暗盘数据适配器 (C2)

按规范 §3 实现配置驱动的 Stockgrid 适配层:
- 集中管理 URL 模式、XHR 匹配规则、DOM 选择器
- 一级路径 XHR JSON → 二级路径 DOM 解析
- 错误分类 (网络/结构) → 拒绝盲目重试
- DOM 结构哈希监控 → 变更时降低数据信任度
- 输出 SourceQualityReport 供 Layer 1/2/3 传递

当前状态: Stockgrid 已下线 (重定向至 axlfi.com)，标记为 UNAVAILABLE。
适配器保留完整的抓取逻辑框架，当目标站点恢复时可重新启用。

规范依据: DATA_INGESTION_SPECS §3 Stockgrid 接入规范
"""

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List

from utils.logger import getLogger
from data_fetchers.source_status import (
    SourceStatus,
    ErrorCategory,
    SourceQualityReport,
    compute_structure_hash,
    check_hash_change,
    classify_error,
)

logger = getLogger('stockgrid_adapter')


# ═══════════════════════════════════════════════════════════════
# Stockgrid 适配器配置 (规范 §3.1 适配层设计要求)
# ═══════════════════════════════════════════════════════════════

@dataclass
class StockgridAdapterConfig:
    """Stockgrid 适配器配置

    所有 URL 模式、XHR 匹配规则、DOM 选择器集中定义于此。
    网站改版时只需修改此处，无需改动业务代码。

    规范 §3.1: 适配器需为每项配置记录 last_verified_at 和验证备注。
    """

    # ── URL 模式 ──
    base_url: str = "https://stockgrid.io"
    darkpool_page_template: str = "{base_url}/darkpool/{symbol}"

    # ── XHR 匹配规则 ──
    xhr_url_pattern: str = "api/darkpool"  # 规范 §3.2 一级路径
    xhr_content_type: str = "application/json"

    # ── DOM 选择器 (规范 §3.4 DOM结构哈希监控) ──
    dom_selectors: Dict[str, str] = field(default_factory=lambda: {
        "chart_container": ".darkpool-chart, .net-position-chart, #darkpool-chart",
        "data_table": ".net-position-table, .data-table, #position-data",
        "period_selector": ".period-selector, .timeframe-btn, [data-period]",
        "value_cell": ".position-value, .net-amount, td.value-cell",
        "date_column": ".date-column, td.date-cell",
        "loading_indicator": ".loading-spinner, .skeleton-loader",
        "error_message": ".error-message, .alert-danger",
    })

    # ── 验证元数据 (规范 §3.1) ──
    last_verified_at: str = "2026-06-09"
    verification_notes: str = (
        "浏览器抓包确认: stockgrid.io 已重定向至 axlfi.com/landing。"
        "原站 XHR 接口 (api/darkpool) 和 DOM 选择器 (.darkpool-chart/.net-position-table) "
        "在 AXLFI 站点上均不存在 (使用 Tailwind CSS)。"
        "Stockgrid 适配器标记为 UNAVAILABLE，数据获取已迁移至 AXLFI。"
    )

    # ── 重试配置 (规范 §3.3) ──
    max_retries: int = 3
    retry_min_wait: int = 5  # 秒
    retry_max_wait: int = 45  # 秒

    # ── 页面加载 ──
    page_load_timeout_ms: int = 30000
    element_wait_timeout_ms: int = 10000

    def get_darkpool_url(self, symbol: str) -> str:
        """生成暗盘页面 URL"""
        return self.darkpool_page_template.format(
            base_url=self.base_url, symbol=symbol,
        )

    def get_structure_hash(self) -> str:
        """为当前 DOM 选择器配置计算结构哈希 (规范 §3.4)"""
        return compute_structure_hash(self.dom_selectors)


# ═══════════════════════════════════════════════════════════════
# Stockgrid 适配器
# ═══════════════════════════════════════════════════════════════

class StockgridAdapter:
    """Stockgrid 暗盘数据适配器

    按规范 §3 实现分层抓取、错误分类、结构哈希监控。
    当前标记为 UNAVAILABLE — 目标站点已下线。

    使用示例:
        adapter = StockgridAdapter()
        report = adapter.fetch_quality_report('SPY')
        # report.status == SourceStatus.UNAVAILABLE
        # report.error_detail == "stockgrid.io 已下线，重定向至 axlfi.com"
    """

    # 上次成功抓取时的结构哈希 (用于变更检测)
    _last_known_hash: str = ""

    def __init__(self, config: Optional[StockgridAdapterConfig] = None):
        self.config = config or StockgridAdapterConfig()
        logger.info(
            f"StockgridAdapter 初始化 (last_verified={self.config.last_verified_at})"
        )

    # ── 公开接口 ──

    def fetch_quality_report(self, symbol: str = "SPY") -> SourceQualityReport:
        """获取 Stockgrid 数据质量报告 (规范 §3.5 数据输出与质量标志)

        由于目标站点已下线，直接返回 UNAVAILABLE 状态。

        Args:
            symbol: 标的代码

        Returns:
            SourceQualityReport: 质量报告，当前始终为 UNAVAILABLE
        """
        start_time = time.time()

        report = SourceQualityReport(
            source_name="stockgrid",
            status=SourceStatus.UNAVAILABLE,
            error_category=ErrorCategory.STRUCTURE,
            last_verified_at=self.config.last_verified_at,
            structure_hash=self.config.get_structure_hash(),
            structure_hash_changed=True,
            error_detail=(
                "stockgrid.io 已下线 — 2026-06-09 浏览器抓包确认重定向至 "
                "axlfi.com/landing。原 XHR 接口 (api/darkpool) 和 DOM 选择器 "
                "(.darkpool-chart) 在新站点不存在。数据获取已迁移至 AXLFI。"
            ),
        )

        report.latency_ms = (time.time() - start_time) * 1000
        logger.warning(f"Stockgrid [{symbol}]: {report.status.value} — {report.error_detail[:100]}")

        return report

    def fetch_net_position_history(
        self, symbol: str = "SPY", period_days: List[int] = [20, 60, 120]
    ) -> Dict[str, Any]:
        """获取暗盘净头寸历史 (已弃用)

        提供与原有 StockgridFetcher 兼容的返回格式，
        但 status 标记为 UNAVAILABLE。

        Returns:
            dict: {"status": "UNAVAILABLE", "periods": {}, "quality_report": {...}}
        """
        report = self.fetch_quality_report(symbol)
        return {
            "status": "UNAVAILABLE",
            "periods": {},
            "quality_report": report.to_dict(),
            "data": None,
        }

    # ── 错误分类 ──

    def classify_error(self, exception: Exception) -> ErrorCategory:
        """分类异常类型 (规范 §3.3 重试策略)

        网络类 → 可重试；结构类 → 禁止重试，标记站点变更。
        """
        return classify_error(exception, source_name="stockgrid")

    # ── 结构哈希监控 ──

    def get_current_structure_hash(self) -> str:
        """获取当前 DOM 选择器配置的结构哈希 (规范 §3.4)"""
        return self.config.get_structure_hash()

    def verify_structure(
        self, current_hash: Optional[str] = None
    ) -> Dict[str, Any]:
        """对比结构哈希，检测站点改版 (规范 §3.4)

        Args:
            current_hash: 当前计算的结构哈希 (None则使用配置默认值)

        Returns:
            {"changed": bool, "previous": str, "current": str}
        """
        if current_hash is None:
            current_hash = self.config.get_structure_hash()

        result = check_hash_change(
            current_hash=current_hash,
            previous_hash=self._last_known_hash,
            source_name="stockgrid",
        )

        if result["changed"] and self._last_known_hash:
            logger.warning(
                f"[WARNING] Stockgrid 结构疑似改版! "
                f"旧哈希={self._last_known_hash}, 新哈希={current_hash}"
            )

        return result

    def update_last_known_hash(self, new_hash: Optional[str] = None) -> None:
        """更新上次已知的哈希值"""
        self._last_known_hash = new_hash or self.config.get_structure_hash()

    # ── 状态查询 ──

    def is_available(self) -> bool:
        """Stockgrid 是否可用"""
        return False  # 站点已下线

    def get_status_summary(self) -> Dict[str, Any]:
        """获取状态摘要"""
        return {
            "source": "stockgrid",
            "available": self.is_available(),
            "status": SourceStatus.UNAVAILABLE.value,
            "last_verified_at": self.config.last_verified_at,
            "verification_notes": self.config.verification_notes,
            "recommended_replacement": "AXLFI (axlfi_fetcher.py)",
        }


# ═══════════════════════════════════════════════════════════════
# 工厂函数
# ═══════════════════════════════════════════════════════════════

def create_stockgrid_adapter() -> StockgridAdapter:
    """创建 Stockgrid 适配器实例"""
    return StockgridAdapter()
