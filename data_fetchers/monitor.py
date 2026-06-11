"""
多源共振监控系统 — 数据源健康监控 (规范 §6)

提供每日成功率、平均延迟、结构变更次数统计，
以及连续 N 日不可用检测 (N=3) 和自动告警。
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional

from utils.logger import getLogger

logger = getLogger('monitor')


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════

@dataclass
class DailySourceStats:
    """单日单源统计"""
    source_name: str
    date: str
    fetch_attempts: int = 0
    fetch_successes: int = 0
    total_latency_ms: float = 0.0
    structure_changes: int = 0
    contract_violations: int = 0
    network_errors: int = 0
    status_ok: bool = True

    @property
    def success_rate(self) -> float:
        if self.fetch_attempts == 0:
            return 0.0
        return self.fetch_successes / self.fetch_attempts

    @property
    def avg_latency_ms(self) -> float:
        if self.fetch_successes == 0:
            return 0.0
        return self.total_latency_ms / self.fetch_successes


@dataclass
class MonitorReport:
    """监控报告"""
    date: str
    sources: Dict[str, DailySourceStats] = field(default_factory=dict)
    overall_status: str = "OK"  # OK | DEGRADED | CRITICAL

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "overall_status": self.overall_status,
            "sources": {
                name: {
                    "success_rate": round(s.success_rate, 3),
                    "avg_latency_ms": round(s.avg_latency_ms, 1),
                    "attempts": s.fetch_attempts,
                    "successes": s.fetch_successes,
                    "structure_changes": s.structure_changes,
                    "contract_violations": s.contract_violations,
                    "network_errors": s.network_errors,
                }
                for name, s in self.sources.items()
            },
        }


# ═══════════════════════════════════════════════════════════════
# 监控器
# ═══════════════════════════════════════════════════════════════

class SourceHealthMonitor:
    """数据源健康监控器

    每日统计各数据源的成功率、延迟和结构变更，检测连续不可用并触发告警。

    使用示例:
        monitor = SourceHealthMonitor()
        monitor.record_fetch("axlfi", success=True, latency_ms=250.0)
        monitor.record_fetch("squeezemetrics", success=False, error_category="NETWORK")
        report = monitor.generate_daily_report()
        if monitor.check_consecutive_unavailable("squeezemetrics", threshold_days=3):
            monitor.trigger_unavailable_alert("squeezemetrics")
    """

    STATS_DIR = "data/monitor_stats"
    CONSECUTIVE_UNAVAILABLE_DAYS = 3

    def __init__(self, stats_dir: Optional[str] = None):
        self.stats_dir = stats_dir or self.STATS_DIR
        self._today_stats: Dict[str, DailySourceStats] = {}
        self._today_date = date.today().isoformat()

        os.makedirs(self.stats_dir, exist_ok=True)
        logger.info(f"SourceHealthMonitor 初始化, 统计目录: {self.stats_dir}")

    # ── 记录 ──

    def record_fetch(
        self,
        source_name: str,
        success: bool,
        latency_ms: float = 0.0,
        error_category: str = "",
        structure_changed: bool = False,
    ) -> None:
        """记录一次数据获取

        Args:
            source_name: 数据源名称
            success: 是否成功
            latency_ms: 延迟 (毫秒)
            error_category: 错误类别 (NETWORK/STRUCTURE/CONTRACT)
            structure_changed: 是否检测到结构变更
        """
        if source_name not in self._today_stats:
            self._today_stats[source_name] = DailySourceStats(
                source_name=source_name,
                date=self._today_date,
            )

        stats = self._today_stats[source_name]
        stats.fetch_attempts += 1

        if success:
            stats.fetch_successes += 1
            stats.total_latency_ms += latency_ms
        else:
            if error_category == "NETWORK":
                stats.network_errors += 1
            elif error_category == "CONTRACT":
                stats.contract_violations += 1

        if structure_changed:
            stats.structure_changes += 1

        stats.status_ok = success

    # ── 报告 ──

    def generate_daily_report(self) -> MonitorReport:
        """生成每日监控报告"""
        report = MonitorReport(
            date=self._today_date,
            sources=self._today_stats,
        )

        # 判定整体状态
        all_ok = all(s.status_ok for s in self._today_stats.values())
        any_available = any(s.status_ok for s in self._today_stats.values())

        if not self._today_stats:
            report.overall_status = "OK"
        elif all_ok:
            report.overall_status = "OK"
        elif any_available:
            report.overall_status = "DEGRADED"
        else:
            report.overall_status = "CRITICAL"

        logger.info(
            f"每日监控报告: {report.overall_status}, "
            f"{len(self._today_stats)} 源, "
            f"成功率: {self._compute_overall_success_rate():.1%}"
        )

        return report

    def save_daily_report(self) -> str:
        """保存每日报告到 JSON 文件"""
        report = self.generate_daily_report()
        filepath = os.path.join(
            self.stats_dir, f"monitor_{self._today_date}.json"
        )
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

        logger.info(f"监控报告已保存: {filepath}")
        return filepath

    # ── 连续不可用检测 ──

    def check_consecutive_unavailable(
        self,
        source_name: str,
        threshold_days: int = None,
    ) -> bool:
        """检测数据源是否连续 N 日不可用

        Args:
            source_name: 数据源名称
            threshold_days: 连续天数阈值 (默认 3)

        Returns:
            bool: True 表示连续 N 日不可用
        """
        threshold = threshold_days or self.CONSECUTIVE_UNAVAILABLE_DAYS

        # 加载历史报告
        consecutive = 0
        check_date = date.today()

        for _ in range(threshold + 1):  # +1 包括今天
            date_str = check_date.isoformat()
            report = self._load_report(date_str)

            if report is None:
                break

            source_stats = report.get("sources", {}).get(source_name)
            if source_stats is None:
                break

            if source_stats.get("successes", 0) == 0:
                consecutive += 1
            else:
                break  # 遇到可用日则中断

            check_date -= timedelta(days=1)

        is_unavailable = consecutive >= threshold
        if is_unavailable:
            logger.warning(
                f"⚠️ {source_name} 连续 {consecutive} 日不可用 (阈值 {threshold})"
            )

        return is_unavailable

    def trigger_unavailable_alert(self, source_name: str) -> bool:
        """触发不可用告警

        Args:
            source_name: 不可用的数据源名称

        Returns:
            bool: 告警是否成功触发
        """
        try:
            from notification.alert_sender import create_alert_sender
            sender = create_alert_sender()

            subject = f"数据源 {source_name} 连续不可用"
            message = (
                f"⚠️ 数据源 [{source_name}] 已连续 "
                f"{self.CONSECUTIVE_UNAVAILABLE_DAYS} 日不可用。\n\n"
                f"检测时间: {datetime.now().isoformat()}\n"
                f"请检查数据源状态并考虑降级策略。\n\n"
                f"— 多源共振监控系统自动告警"
            )

            result = sender.send_critical_alert(subject, message)
            logger.critical(
                f"不可用告警已触发: {source_name}, 结果={result}"
            )
            return any(result.values())

        except Exception as e:
            logger.error(f"不可用告警发送失败: {e}")
            return False

    # ── 内部方法 ──

    def _load_report(self, date_str: str) -> Optional[dict]:
        """从文件加载指定日期的报告"""
        filepath = os.path.join(
            self.stats_dir, f"monitor_{date_str}.json"
        )
        if not os.path.exists(filepath):
            return None

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载监控报告失败 ({date_str}): {e}")
            return None

    def _compute_overall_success_rate(self) -> float:
        """计算整体成功率"""
        if not self._today_stats:
            return 0.0
        total_attempts = sum(s.fetch_attempts for s in self._today_stats.values())
        total_successes = sum(s.fetch_successes for s in self._today_stats.values())
        if total_attempts == 0:
            return 0.0
        return total_successes / total_attempts


# ═══════════════════════════════════════════════════════════════
# 工厂函数
# ═══════════════════════════════════════════════════════════════

def create_health_monitor() -> SourceHealthMonitor:
    """创建健康监控器实例"""
    return SourceHealthMonitor()
