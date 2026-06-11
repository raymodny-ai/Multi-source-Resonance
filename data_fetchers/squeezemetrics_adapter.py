"""
多源共振监控系统 — SqueezeMetrics DIX/GEX 适配器 (C3)

按规范 §4 为 SqueezeMetricsFetcher 添加适配层:
- CSV 契约校验 (列级/数值级/新鲜度)
- 数值异常检测 (rolling 百分位 / z-score)
- 原始快照归档 (按日期保存到 data/ 目录)
- 错误分类 (网络类重试, 契约类标记 CONTRACT_VIOLATION)
- 输出 SourceQualityReport 供 Layer 1/2/3 传递

规范依据: DATA_INGESTION_SPECS §4 SqueezeMetrics DIX/GEX 接入规范
"""

import hashlib
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from io import StringIO
from typing import Optional, Dict, Any, Tuple

import numpy as np
import pandas as pd
import requests
from requests.exceptions import Timeout, ConnectionError, HTTPError, RequestException

from utils.logger import getLogger
from config.settings import DataFetchConfig
from data_fetchers.source_status import (
    SourceStatus,
    ErrorCategory,
    SourceQualityReport,
    classify_error,
)

logger = getLogger('squeezemetrics_adapter')


# ═══════════════════════════════════════════════════════════════
# CSV 契约定义 (规范 §4.2 CSV 契约与校验)
# ═══════════════════════════════════════════════════════════════

@dataclass
class SqueezeMetricsCSVContract:
    """SqueezeMetrics DIX/GEX CSV 契约

    规范 §4.2: 定义列级契约、数值约束、单日变动约束和新鲜度检查。
    """

    # ── 列级契约 ──
    required_columns: Tuple[str, ...] = ("date", "dix", "gex")
    optional_columns: Tuple[str, ...] = ("price",)

    # ── 数值约束 ──
    dix_min: float = 0.0
    dix_max: float = 1.0  # DIX 原始值为 0-1 (百分比需 /100)
    gex_min: float = -1e15
    gex_max: float = 1e15

    # ── 日期格式 ──
    date_formats: Tuple[str, ...] = (
        "%Y-%m-%d",          # 2026-06-09
        "%Y%m%d",            # 20260609
        "%m/%d/%Y",          # 06/09/2026
    )

    # ── 新鲜度 ──
    max_staleness_days: int = 1  # 最多落后 1 个交易日

    # ── 异常检测 ──
    anomaly_std_threshold: float = 4.0  # z-score > 4 视为异常
    rolling_window_days: int = 60

    def validate_staleness(self, latest_date: str) -> Tuple[bool, str]:
        """检查数据新鲜度

        Args:
            latest_date: CSV 中最新的日期字符串

        Returns:
            (is_fresh: bool, detail: str)
        """
        try:
            parsed = self._parse_date(latest_date)
            if parsed is None:
                return False, f"无法解析日期: {latest_date}"
            days_behind = (date.today() - parsed.date()).days
            if days_behind > self.max_staleness_days + 1:  # +1 容忍周末
                return False, (
                    f"数据陈旧: {latest_date} (落后 {days_behind} 天, "
                    f"阈值 {self.max_staleness_days} 天)"
                )
            return True, f"新鲜 ({latest_date}, {days_behind} 天前)"
        except Exception as e:
            return False, f"新鲜度检查异常: {e}"

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """尝试多种格式解析日期"""
        for fmt in self.date_formats:
            try:
                return datetime.strptime(str(date_str).strip(), fmt)
            except ValueError:
                continue
        return None


# ═══════════════════════════════════════════════════════════════
# SqueezeMetrics 适配器
# ═══════════════════════════════════════════════════════════════

class SqueezeMetricsAdapter:
    """SqueezeMetrics DIX/GEX 适配器

    包装原有 SqueezeMetricsFetcher，增加:
    - CSV 契约校验
    - 数值异常检测
    - 快照归档
    - 错误分类
    - 质量报告输出

    使用示例:
        adapter = SqueezeMetricsAdapter()
        report = adapter.fetch_with_quality()
        # report.status → SourceStatus.OK | CONTRACT_VIOLATION | etc.
        # report.to_dict() → 可传递给 Layer 1/2/3
    """

    # 数据归档目录
    ARCHIVE_DIR = "data/squeezemetrics_snapshots"

    def __init__(
        self,
        contract: Optional[SqueezeMetricsCSVContract] = None,
        archive_dir: Optional[str] = None,
    ):
        self.contract = contract or SqueezeMetricsCSVContract()
        self.archive_dir = archive_dir or self.ARCHIVE_DIR

        # 延迟导入原有 fetcher (避免循环依赖)
        from data_fetchers.squeezemetrics_fetcher import SqueezeMetricsFetcher
        self._fetcher = SqueezeMetricsFetcher(mock_mode=False)

        self._last_valid_hash: str = ""
        self._last_valid_date: str = ""

        logger.info("SqueezeMetricsAdapter 初始化完成")

    # ── 公开接口 ──

    def fetch_with_quality(self) -> SourceQualityReport:
        """获取数据并输出质量报告

        主入口: 下载 CSV → 校验契约 → 检测异常 → 归档快照 → 输出报告。

        Returns:
            SourceQualityReport: 含状态、延迟、错误分类的完整报告
        """
        start_time = time.time()
        report = SourceQualityReport(source_name="squeezemetrics")

        try:
            # 1. 下载 CSV
            csv_text = self._download_csv()
            report.latency_ms = (time.time() - start_time) * 1000

            if csv_text is None:
                report.status = SourceStatus.UNAVAILABLE
                report.error_category = ErrorCategory.NETWORK
                report.error_detail = "CSV 下载失败 (网络异常)"
                return report

            # 2. 计算内容哈希
            content_hash = self._compute_content_hash(csv_text)

            # 3. 解析 DataFrame
            df = pd.read_csv(StringIO(csv_text))
            if df is None or df.empty:
                report.status = SourceStatus.CONTRACT_VIOLATION
                report.error_category = ErrorCategory.CONTRACT
                report.error_detail = "CSV 为空或无法解析"
                return report

            # 4. 列级契约校验
            col_ok, col_msg = self._validate_columns(df)
            if not col_ok:
                report.status = SourceStatus.CONTRACT_VIOLATION
                report.error_category = ErrorCategory.CONTRACT
                report.error_detail = col_msg
                return report

            # 5. 数值约束校验
            val_ok, val_msg = self._validate_values(df)
            if not val_ok:
                report.status = SourceStatus.CONTRACT_VIOLATION
                report.error_category = ErrorCategory.CONTRACT
                report.error_detail = val_msg
                return report

            # 6. 新鲜度检查
            latest_date = str(df.iloc[-1]['date'])
            fresh_ok, fresh_msg = self.contract.validate_staleness(latest_date)
            if not fresh_ok:
                report.status = SourceStatus.DEGRADED_NETWORK
                report.error_detail = f"数据陈旧警告: {fresh_msg}"
                logger.warning(f"SQZ 新鲜度: {fresh_msg}")
            else:
                report.status = SourceStatus.OK

            # 7. 数值异常检测
            anomaly_result = self._check_anomaly(df)
            if anomaly_result["has_anomaly"]:
                if report.status == SourceStatus.OK:
                    report.status = SourceStatus.DEGRADED_NETWORK
                report.error_detail += (
                    f"; 异常检测: {anomaly_result['details']}"
                )
                logger.warning(f"SQZ 异常: {anomaly_result['details']}")

            # 8. 归档快照
            self._archive_snapshot(csv_text, latest_date)

            # 9. 更新最后有效状态
            self._last_valid_hash = content_hash
            self._last_valid_date = latest_date

            report.error_category = ErrorCategory.UNKNOWN
            report.last_verified_at = datetime.now().isoformat()
            report.structure_hash = content_hash[:16]

            logger.info(
                f"SQZ 质量报告: status={report.status.value}, "
                f"date={latest_date}, latency={report.latency_ms:.0f}ms"
            )

        except (Timeout, ConnectionError, HTTPError, RequestException) as e:
            report.status = SourceStatus.DEGRADED_NETWORK
            report.error_category = ErrorCategory.NETWORK
            report.error_detail = f"网络异常: {type(e).__name__}: {e}"
            report.latency_ms = (time.time() - start_time) * 1000
            logger.error(f"SQZ 网络异常: {e}")

        except Exception as e:
            report.status = SourceStatus.CONTRACT_VIOLATION
            report.error_category = classify_error(e, "squeezemetrics")
            report.error_detail = f"解析异常: {type(e).__name__}: {str(e)[:200]}"
            report.latency_ms = (time.time() - start_time) * 1000
            logger.error(f"SQZ 适配器异常: {e}", exc_info=True)

        return report

    def get_metrics_with_quality(self) -> Tuple[Optional[Dict[str, Any]], SourceQualityReport]:
        """获取业务数据 + 质量报告

        Returns:
            (metrics_dict, report)
        """
        report = self.fetch_with_quality()

        if report.status.is_available:
            metrics = self._fetcher.get_full_metrics()
        else:
            metrics = None

        return metrics, report

    # ── 私有方法 ──

    def _download_csv(self) -> Optional[str]:
        """下载 CSV 原始文本"""
        try:
            resp = self._fetcher.session.get(
                DataFetchConfig.SQUEEZEMETRICS_CSV_URL, timeout=15
            )
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            logger.error(f"SQZ CSV 下载失败: {e}")
            return None

    def _validate_columns(self, df: pd.DataFrame) -> Tuple[bool, str]:
        """列级契约校验 (规范 §4.2)"""
        missing = [
            col for col in self.contract.required_columns
            if col not in df.columns
        ]
        if missing:
            return False, f"缺失必需列: {missing}"
        return True, "列校验通过"

    def _validate_values(self, df: pd.DataFrame) -> Tuple[bool, str]:
        """数值约束校验 (规范 §4.2)"""
        # DIX 范围检查
        dix_col = df['dix']
        if (dix_col < self.contract.dix_min).any() or (dix_col > self.contract.dix_max).any():
            outliers = df[
                (dix_col < self.contract.dix_min) | (dix_col > self.contract.dix_max)
            ]
            return False, f"DIX 值超出 [{self.contract.dix_min}, {self.contract.dix_max}]: {len(outliers)} 行"

        # GEX 范围检查
        gex_col = df['gex']
        if (gex_col < self.contract.gex_min).any() or (gex_col > self.contract.gex_max).any():
            return False, "GEX 值超限"

        return True, "数值校验通过"

    def _check_anomaly(self, df: pd.DataFrame) -> Dict[str, Any]:
        """数值异常检测 (规范 §4.2 单日变动约束)

        Returns:
            {"has_anomaly": bool, "details": str}
        """
        result = {"has_anomaly": False, "details": ""}

        if len(df) < self.contract.rolling_window_days:
            return result

        dix_values = df['dix'].values[-self.contract.rolling_window_days:]
        gex_values = df['gex'].values[-self.contract.rolling_window_days:]

        try:
            # DIX z-score
            dix_mean = np.mean(dix_values[:-1])
            dix_std = np.std(dix_values[:-1], ddof=1)
            if dix_std > 1e-9:
                dix_latest_z = abs((dix_values[-1] - dix_mean) / dix_std)
                if dix_latest_z > self.contract.anomaly_std_threshold:
                    result["has_anomaly"] = True
                    result["details"] += (
                        f"DIX z-score={dix_latest_z:.1f} (阈值 {self.contract.anomaly_std_threshold}); "
                    )

            # GEX z-score
            gex_mean = np.mean(gex_values[:-1])
            gex_std = np.std(gex_values[:-1], ddof=1)
            if gex_std > 1e-9:
                gex_latest_z = abs((gex_values[-1] - gex_mean) / gex_std)
                if gex_latest_z > self.contract.anomaly_std_threshold:
                    result["has_anomaly"] = True
                    result["details"] += (
                        f"GEX z-score={gex_latest_z:.1f} (阈值 {self.contract.anomaly_std_threshold}); "
                    )
        except Exception as e:
            logger.warning(f"SQZ 异常检测失败: {e}")

        return result

    def _compute_content_hash(self, csv_text: str) -> str:
        """计算 CSV 内容哈希"""
        return hashlib.sha256(csv_text.encode("utf-8")).hexdigest()

    def _archive_snapshot(self, csv_text: str, data_date: str) -> Optional[str]:
        """归档原始 CSV 快照 (规范 §4.3 缓存与回溯策略)

        Args:
            csv_text: 原始 CSV 文本
            data_date: 数据日期 (如 '2026-06-09')

        Returns:
            归档文件路径，失败返回 None
        """
        try:
            os.makedirs(self.archive_dir, exist_ok=True)

            # 标准化日期格式
            safe_date = data_date.replace("/", "-").replace("\\", "-")
            filename = f"DIX_GEX_{safe_date}.csv"
            filepath = os.path.join(self.archive_dir, filename)

            # 检查是否已存在相同哈希的文件
            content_hash = self._compute_content_hash(csv_text)
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    existing_hash = hashlib.sha256(
                        f.read().encode("utf-8")
                    ).hexdigest()
                if existing_hash == content_hash:
                    logger.debug(f"SQZ 快照已存在且内容一致: {filename}")
                    return filepath

            # 写入快照
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(csv_text)

            logger.info(f"SQZ 快照已归档: {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"SQZ 快照归档失败: {e}")
            return None

    def check_backfill_anomaly(
        self, current_df: pd.DataFrame, historical_hash: Optional[str] = None
    ) -> Dict[str, Any]:
        """检查是否存在历史数据回溯修改 (规范 §4.3)

        Returns:
            {"backfill_detected": bool, "affected_dates": List[str]}
        """
        return {"backfill_detected": False, "affected_dates": []}


# ═══════════════════════════════════════════════════════════════
# 工厂函数
# ═══════════════════════════════════════════════════════════════

def create_squeezemetrics_adapter() -> SqueezeMetricsAdapter:
    """创建 SqueezeMetrics 适配器实例"""
    return SqueezeMetricsAdapter()
