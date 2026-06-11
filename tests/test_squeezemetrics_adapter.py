"""
测试: SqueezeMetrics 适配器 (squeezemetrics_adapter.py)

验证 CSV 契约校验、数值异常检测、快照归档、错误分类和质量报告输出。
"""

import os
import tempfile
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pandas as pd
import pytest

from data_fetchers.squeezemetrics_adapter import (
    SqueezeMetricsCSVContract,
    SqueezeMetricsAdapter,
    create_squeezemetrics_adapter,
)
from data_fetchers.source_status import SourceStatus, ErrorCategory


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def valid_df():
    """生成合法 CSV 的 DataFrame"""
    dates = pd.date_range(end="2026-06-09", periods=100, freq="B")
    np.random.seed(42)
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "price": np.linspace(7000, 7500, 100) + np.random.randn(100) * 30,
        "dix": np.clip(np.random.normal(0.42, 0.03, 100), 0.01, 0.99),
        "gex": np.random.normal(3e9, 5e8, 100),
    })


@pytest.fixture
def valid_csv_text(valid_df):
    """合法 CSV 文本"""
    return valid_df.to_csv(index=False)


@pytest.fixture
def mock_fetcher():
    """Mock SqueezeMetricsFetcher"""
    fetcher = MagicMock()
    fetcher.session = MagicMock()
    fetcher.get_full_metrics.return_value = {
        "date": "2026-06-09",
        "price": 7386.65,
        "dix": 43.87,
        "dix_raw": 0.4387,
        "gex": 3.13e9,
    }
    return fetcher


# ═══════════════════════════════════════════════════════════════
# SqueezeMetricsCSVContract 测试
# ═══════════════════════════════════════════════════════════════

class TestSqueezeMetricsCSVContract:
    """CSV 契约定义测试"""

    def test_default_values(self):
        contract = SqueezeMetricsCSVContract()
        assert contract.required_columns == ("date", "dix", "gex")
        assert contract.dix_min == 0.0
        assert contract.dix_max == 1.0
        assert contract.max_staleness_days == 1
        assert contract.anomaly_std_threshold == 4.0
        assert contract.rolling_window_days == 60

    def test_validate_staleness_fresh(self):
        contract = SqueezeMetricsCSVContract()
        today_str = pd.Timestamp.now().strftime("%Y-%m-%d")
        ok, msg = contract.validate_staleness(today_str)
        assert ok is True
        assert "新鲜" in msg

    def test_validate_staleness_stale(self):
        contract = SqueezeMetricsCSVContract()
        ok, msg = contract.validate_staleness("2020-01-02")
        assert ok is False
        assert "陈旧" in msg

    def test_validate_staleness_unparseable(self):
        contract = SqueezeMetricsCSVContract()
        ok, msg = contract.validate_staleness("not-a-date")
        assert ok is False
        assert "无法解析" in msg

    def test_parse_date_ymd(self):
        contract = SqueezeMetricsCSVContract()
        parsed = contract._parse_date("2026-06-09")
        assert parsed is not None
        assert parsed.year == 2026

    def test_parse_date_compact(self):
        contract = SqueezeMetricsCSVContract()
        parsed = contract._parse_date("20260609")
        assert parsed is not None
        assert parsed.month == 6

    def test_parse_date_slash(self):
        contract = SqueezeMetricsCSVContract()
        parsed = contract._parse_date("06/09/2026")
        assert parsed is not None
        assert parsed.day == 9

    def test_parse_date_invalid(self):
        contract = SqueezeMetricsCSVContract()
        parsed = contract._parse_date("garbage")
        assert parsed is None


# ═══════════════════════════════════════════════════════════════
# SqueezeMetricsAdapter 校验测试 (mock fetcher)
# ═══════════════════════════════════════════════════════════════

class TestSqueezeMetricsAdapterValidation:
    """契约校验测试"""

    @pytest.fixture
    def adapter(self, mock_fetcher):
        with patch(
            "data_fetchers.squeezemetrics_fetcher.SqueezeMetricsFetcher",
            return_value=mock_fetcher,
        ):
            return SqueezeMetricsAdapter()

    def test_validate_columns_pass(self, adapter, valid_df):
        ok, msg = adapter._validate_columns(valid_df)
        assert ok is True
        assert "通过" in msg

    def test_validate_columns_missing(self, adapter):
        df = pd.DataFrame({"date": ["2026-06-09"], "price": [7000]})
        ok, msg = adapter._validate_columns(df)
        assert ok is False
        assert "缺失必需列" in msg

    def test_validate_values_pass(self, adapter, valid_df):
        ok, msg = adapter._validate_values(valid_df)
        assert ok is True

    def test_validate_values_dix_out_of_range(self, adapter):
        df = pd.DataFrame({
            "date": ["2026-06-09"],
            "price": [7000],
            "dix": [5.0],
            "gex": [3e9],
        })
        ok, msg = adapter._validate_values(df)
        assert ok is False
        assert "DIX" in msg

    def test_validate_values_gex_out_of_range(self, adapter):
        df = pd.DataFrame({
            "date": ["2026-06-09"],
            "price": [7000],
            "dix": [0.5],
            "gex": [2e15],
        })
        ok, msg = adapter._validate_values(df)
        assert ok is False
        assert "GEX" in msg

    def test_compute_content_hash(self, adapter):
        h = adapter._compute_content_hash("hello,world")
        assert len(h) == 64
        assert isinstance(h, str)

    def test_compute_content_hash_different(self, adapter):
        h1 = adapter._compute_content_hash("data_v1")
        h2 = adapter._compute_content_hash("data_v2")
        assert h1 != h2


# ═══════════════════════════════════════════════════════════════
# SqueezeMetricsAdapter 异常检测测试
# ═══════════════════════════════════════════════════════════════

class TestSqueezeMetricsAdapterAnomaly:
    """数值异常检测测试"""

    @pytest.fixture
    def adapter(self, mock_fetcher):
        with patch(
            "data_fetchers.squeezemetrics_fetcher.SqueezeMetricsFetcher",
            return_value=mock_fetcher,
        ):
            return SqueezeMetricsAdapter()

    def test_check_anomaly_normal(self, adapter):
        """正常数据无异常"""
        np.random.seed(42)
        dates = pd.date_range(end="2026-06-09", periods=80, freq="B")
        df = pd.DataFrame({
            "date": dates.strftime("%Y-%m-%d"),
            "price": np.linspace(7000, 7500, 80),
            "dix": np.clip(np.random.normal(0.42, 0.02, 80), 0.01, 0.99),
            "gex": np.random.normal(3e9, 1e8, 80),
        })
        result = adapter._check_anomaly(df)
        assert result["has_anomaly"] is False

    def test_check_anomaly_dix_spike(self, adapter):
        """DIX 突然飙升应被检测"""
        np.random.seed(42)
        dates = pd.date_range(end="2026-06-09", periods=80, freq="B")
        dix_values = np.clip(np.random.normal(0.42, 0.02, 80), 0.01, 0.99).tolist()
        dix_values[-1] = 0.95  # z-score 会非常高
        df = pd.DataFrame({
            "date": dates.strftime("%Y-%m-%d"),
            "price": np.linspace(7000, 7500, 80),
            "dix": dix_values,
            "gex": np.random.normal(3e9, 1e8, 80),
        })
        result = adapter._check_anomaly(df)
        assert result["has_anomaly"] is True
        assert "DIX" in result["details"]

    def test_check_anomaly_gex_spike(self, adapter):
        """GEX 突然暴增应被检测"""
        np.random.seed(42)
        dates = pd.date_range(end="2026-06-09", periods=80, freq="B")
        gex_values = np.random.normal(3e9, 1e8, 80).tolist()
        gex_values[-1] = 1e10  # 极端值
        df = pd.DataFrame({
            "date": dates.strftime("%Y-%m-%d"),
            "price": np.linspace(7000, 7500, 80),
            "dix": np.clip(np.random.normal(0.42, 0.02, 80), 0.01, 0.99),
            "gex": gex_values,
        })
        result = adapter._check_anomaly(df)
        assert result["has_anomaly"] is True
        assert "GEX" in result["details"]

    def test_check_anomaly_insufficient_data(self, adapter):
        """数据不足时不检测异常"""
        dates = pd.date_range(end="2026-06-09", periods=10, freq="B")
        df = pd.DataFrame({
            "date": dates.strftime("%Y-%m-%d"),
            "price": [7000] * 10,
            "dix": [0.5] * 10,
            "gex": [3e9] * 10,
        })
        result = adapter._check_anomaly(df)
        assert result["has_anomaly"] is False


# ═══════════════════════════════════════════════════════════════
# SqueezeMetricsAdapter 快照归档测试
# ═══════════════════════════════════════════════════════════════

class TestSqueezeMetricsAdapterArchive:
    """快照归档测试"""

    @pytest.fixture
    def adapter(self, mock_fetcher):
        with patch(
            "data_fetchers.squeezemetrics_fetcher.SqueezeMetricsFetcher",
            return_value=mock_fetcher,
        ):
            with tempfile.TemporaryDirectory() as tmpdir:
                adapter = SqueezeMetricsAdapter(archive_dir=tmpdir)
                yield adapter

    def test_archive_snapshot_creates_file(self, adapter):
        csv_text = "date,dix,gex\n2026-06-09,0.44,3.1e9\n"
        path = adapter._archive_snapshot(csv_text, "2026-06-09")
        assert path is not None
        assert os.path.exists(path)
        assert "DIX_GEX_2026-06-09.csv" in path

    def test_archive_snapshot_skips_duplicate(self, adapter):
        csv_text = "date,dix,gex\n2026-06-09,0.44,3.1e9\n"
        path1 = adapter._archive_snapshot(csv_text, "2026-06-09")
        path2 = adapter._archive_snapshot(csv_text, "2026-06-09")
        assert path1 == path2  # 应返回同一路径

    def test_archive_snapshot_overwrite_different(self, adapter):
        csv1 = "date,dix,gex\n2026-06-09,0.44,3.1e9\n"
        csv2 = "date,dix,gex\n2026-06-09,0.50,2.8e9\n"
        path1 = adapter._archive_snapshot(csv1, "2026-06-09")
        path2 = adapter._archive_snapshot(csv2, "2026-06-09")
        # 第二次内容不同，应覆盖写入
        with open(path2, "r") as f:
            content = f.read()
        assert "0.50" in content


# ═══════════════════════════════════════════════════════════════
# SqueezeMetricsAdapter fetch_with_quality 测试
# ═══════════════════════════════════════════════════════════════

class TestSqueezeMetricsAdapterFetchWithQuality:
    """fetch_with_quality 端到端测试"""

    def test_fetch_with_quality_ok(self, valid_csv_text, mock_fetcher):
        """正常数据路径: OK 状态"""
        mock_response = MagicMock()
        mock_response.text = valid_csv_text
        mock_response.raise_for_status = MagicMock()
        mock_fetcher.session.get.return_value = mock_response

        with patch(
            "data_fetchers.squeezemetrics_fetcher.SqueezeMetricsFetcher",
            return_value=mock_fetcher,
        ):
            with tempfile.TemporaryDirectory() as tmpdir:
                adapter = SqueezeMetricsAdapter(archive_dir=tmpdir)
                report = adapter.fetch_with_quality()

        assert report.source_name == "squeezemetrics"
        assert report.status in (SourceStatus.OK, SourceStatus.DEGRADED_NETWORK)
        assert report.latency_ms >= 0

    def test_fetch_with_quality_network_error(self, mock_fetcher):
        """网络异常导致下载失败应返回 UNAVAILABLE"""
        from requests.exceptions import Timeout
        mock_fetcher.session.get.side_effect = Timeout("Connection timed out")

        with patch(
            "data_fetchers.squeezemetrics_fetcher.SqueezeMetricsFetcher",
            return_value=mock_fetcher,
        ):
            adapter = SqueezeMetricsAdapter()
            report = adapter.fetch_with_quality()

        assert report.source_name == "squeezemetrics"
        assert report.status == SourceStatus.UNAVAILABLE
        assert report.error_category == ErrorCategory.NETWORK

    def test_fetch_with_quality_csv_download_fail(self, mock_fetcher):
        """CSV 下载返回 None → UNAVAILABLE"""
        mock_fetcher.session.get.side_effect = Exception("Download failed")

        with patch(
            "data_fetchers.squeezemetrics_fetcher.SqueezeMetricsFetcher",
            return_value=mock_fetcher,
        ):
            adapter = SqueezeMetricsAdapter()
            report = adapter.fetch_with_quality()

        assert report.status == SourceStatus.UNAVAILABLE

    def test_fetch_with_quality_contract_violation_missing_columns(self, mock_fetcher):
        """缺少必需列 → CONTRACT_VIOLATION"""
        bad_csv = "date,price,wrong_col\n2026-06-09,7000,0.5\n"
        mock_response = MagicMock()
        mock_response.text = bad_csv
        mock_response.raise_for_status = MagicMock()
        mock_fetcher.session.get.return_value = mock_response

        with patch(
            "data_fetchers.squeezemetrics_fetcher.SqueezeMetricsFetcher",
            return_value=mock_fetcher,
        ):
            adapter = SqueezeMetricsAdapter()
            report = adapter.fetch_with_quality()

        assert report.status == SourceStatus.CONTRACT_VIOLATION
        assert report.error_category == ErrorCategory.CONTRACT

    def test_get_metrics_with_quality_ok(self, valid_csv_text, mock_fetcher):
        """获取业务数据 + 质量报告"""
        mock_response = MagicMock()
        mock_response.text = valid_csv_text
        mock_response.raise_for_status = MagicMock()
        mock_fetcher.session.get.return_value = mock_response

        with patch(
            "data_fetchers.squeezemetrics_fetcher.SqueezeMetricsFetcher",
            return_value=mock_fetcher,
        ):
            with tempfile.TemporaryDirectory() as tmpdir:
                adapter = SqueezeMetricsAdapter(archive_dir=tmpdir)
                metrics, report = adapter.get_metrics_with_quality()

        assert report.source_name == "squeezemetrics"
        assert report.status in (SourceStatus.OK, SourceStatus.DEGRADED_NETWORK)
        if report.status.is_available:
            assert metrics is not None
            assert "dix" in metrics

    def test_get_metrics_with_quality_unavailable(self, mock_fetcher):
        """不可用状态下 metrics 为 None"""
        from requests.exceptions import Timeout
        mock_fetcher.session.get.side_effect = Timeout("timeout")

        with patch(
            "data_fetchers.squeezemetrics_fetcher.SqueezeMetricsFetcher",
            return_value=mock_fetcher,
        ):
            adapter = SqueezeMetricsAdapter()
            metrics, report = adapter.get_metrics_with_quality()

        assert metrics is None
        assert not report.status.is_available


# ═══════════════════════════════════════════════════════════════
# 工厂函数 & 其他测试
# ═══════════════════════════════════════════════════════════════

class TestSqueezeMetricsAdapterMisc:
    """杂项测试"""

    def test_factory_creates_adapter(self, mock_fetcher):
        with patch(
            "data_fetchers.squeezemetrics_fetcher.SqueezeMetricsFetcher",
            return_value=mock_fetcher,
        ):
            adapter = create_squeezemetrics_adapter()
            assert isinstance(adapter, SqueezeMetricsAdapter)

    def test_check_backfill_anomaly_default(self, mock_fetcher):
        with patch(
            "data_fetchers.squeezemetrics_fetcher.SqueezeMetricsFetcher",
            return_value=mock_fetcher,
        ):
            adapter = SqueezeMetricsAdapter()
            result = adapter.check_backfill_anomaly(pd.DataFrame())
            assert result["backfill_detected"] is False
            assert result["affected_dates"] == []

    def test_custom_contract(self, mock_fetcher):
        contract = SqueezeMetricsCSVContract(
            dix_min=-0.5,
            dix_max=1.5,
            anomaly_std_threshold=3.0,
        )
        with patch(
            "data_fetchers.squeezemetrics_fetcher.SqueezeMetricsFetcher",
            return_value=mock_fetcher,
        ):
            adapter = SqueezeMetricsAdapter(contract=contract)
            assert adapter.contract.dix_min == -0.5
            assert adapter.contract.anomaly_std_threshold == 3.0
