"""
测试: AXLFI 暗盘适配器 (axlfi_adapter.py)

验证质量报告输出、错误分类、智能重试、结构校验和旧接口兼容性。
"""

from unittest.mock import MagicMock, patch

import pytest

from data_fetchers.axlfi_adapter import (
    AxlfiAdapter,
    create_axlfi_adapter,
    _is_retryable,
)
from data_fetchers.source_status import SourceStatus, ErrorCategory


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def valid_axlfi_data():
    """合法 AXLFI API 返回数据"""
    return {
        "symbol": "SPY",
        "as_of_date": "2026-06-09",
        "latest": {"dollar_dp_position": "-1400000000"},
        "individual_dark_pool_position_data": {
            "dates": ["2026-06-01", "2026-06-02", "2026-06-09"],
            "dollar_dp_position": [-1.4, -1.5, -1.3],
            "dollar_net_volume": [-0.7, -0.8, -0.6],
        },
        "individual_short_volume": {
            "dates": ["2026-06-09"],
            "net_volume": [100000],
            "short_volume": [52000],
            "short_volume_pct": [52.0],
        },
        "prices": {
            "dates": ["2026-06-09"],
            "close": [7386.65],
        },
    }


@pytest.fixture
def mock_fetcher(valid_axlfi_data):
    """Mock AxlfiFetcher"""
    fetcher = MagicMock()
    fetcher.fetch_symbol_data.return_value = valid_axlfi_data
    fetcher.get_net_position_series.return_value = {
        "20d": [-1.4e9] * 20,
        "60d": [-1.5e9] * 60,
        "120d": [-1.3e9] * 120,
    }
    fetcher.get_latest_short_metrics.return_value = {
        "latest_short_pct": 52.0,
        "latest_short_volume": 52000,
    }
    fetcher.detect_bottom_divergence.return_value = {
        "divergence": False,
        "slope_20d": 1e6,
        "slope_60d": 5e5,
        "golden_cross": False,
    }
    return fetcher


# ═══════════════════════════════════════════════════════════════
# 重试策略测试
# ═══════════════════════════════════════════════════════════════

class TestRetryPolicy:
    """tenacity 重试策略测试"""

    def test_timeout_is_retryable(self):
        from requests.exceptions import Timeout
        assert _is_retryable(Timeout("timed out")) is True

    def test_connection_error_is_retryable(self):
        from requests.exceptions import ConnectionError
        assert _is_retryable(ConnectionError("refused")) is True

    def test_request_exception_is_retryable(self):
        from requests.exceptions import RequestException
        assert _is_retryable(RequestException("generic")) is True

    def test_http_500_is_retryable(self):
        from requests.exceptions import HTTPError
        import requests
        resp = requests.Response()
        resp.status_code = 500
        exc = HTTPError("500 Error", response=resp)
        assert _is_retryable(exc) is True

    def test_http_503_is_retryable(self):
        from requests.exceptions import HTTPError
        import requests
        resp = requests.Response()
        resp.status_code = 503
        exc = HTTPError("503 Error", response=resp)
        assert _is_retryable(exc) is True

    def test_http_404_is_not_retryable(self):
        from requests.exceptions import HTTPError
        import requests
        resp = requests.Response()
        resp.status_code = 404
        exc = HTTPError("404 Error", response=resp)
        assert _is_retryable(exc) is False

    def test_value_error_is_not_retryable(self):
        assert _is_retryable(ValueError("bad value")) is False


# ═══════════════════════════════════════════════════════════════
# 适配器核心测试 (mock fetcher)
# ═══════════════════════════════════════════════════════════════

class TestAxlfiAdapter:
    """AXLFI 适配器核心行为测试"""

    @pytest.fixture
    def adapter(self, mock_fetcher):
        with patch(
            "data_fetchers.axlfi_fetcher.AxlfiFetcher",
            return_value=mock_fetcher,
        ):
            return AxlfiAdapter()

    def test_factory(self, mock_fetcher):
        with patch(
            "data_fetchers.axlfi_fetcher.AxlfiFetcher",
            return_value=mock_fetcher,
        ):
            adapter = create_axlfi_adapter()
            assert isinstance(adapter, AxlfiAdapter)

    def test_factory_with_mock_mode(self):
        adapter = create_axlfi_adapter(mock_mode=True)
        assert adapter._mock_mode is True

    def test_fetch_with_quality_ok(self, adapter, valid_axlfi_data):
        """正常数据路径: OK 状态"""
        report = adapter.fetch_with_quality("SPY")
        assert report.source_name == "axlfi"
        assert report.status == SourceStatus.OK
        assert report.latency_ms >= 0
        assert report.last_verified_at is not None

    def test_fetch_with_quality_network_error(self, mock_fetcher):
        """网络异常应返回 DEGRADED_NETWORK"""
        from requests.exceptions import Timeout
        mock_fetcher.fetch_symbol_data.side_effect = Timeout("Connection timed out")

        with patch(
            "data_fetchers.axlfi_fetcher.AxlfiFetcher",
            return_value=mock_fetcher,
        ):
            adapter = AxlfiAdapter()
            report = adapter.fetch_with_quality("SPY")

        assert report.status == SourceStatus.DEGRADED_NETWORK
        assert report.error_category == ErrorCategory.NETWORK

    def test_fetch_with_quality_structure_changed(self, mock_fetcher):
        """API 结构变更应标记 STRUCTURE_CHANGED"""
        bad_data = {
            "symbol": "SPY",
            "as_of_date": "2026-06-09",
            "latest": {},
            # 缺少 individual_dark_pool_position_data
        }
        mock_fetcher.fetch_symbol_data.return_value = bad_data

        with patch(
            "data_fetchers.axlfi_fetcher.AxlfiFetcher",
            return_value=mock_fetcher,
        ):
            adapter = AxlfiAdapter()
            report = adapter.fetch_with_quality("SPY")

        assert report.status == SourceStatus.STRUCTURE_CHANGED
        assert report.error_category == ErrorCategory.STRUCTURE

    def test_fetch_with_quality_unavailable(self, mock_fetcher):
        """返回 None 应标记 UNAVAILABLE"""
        mock_fetcher.fetch_symbol_data.return_value = None

        with patch(
            "data_fetchers.axlfi_fetcher.AxlfiFetcher",
            return_value=mock_fetcher,
        ):
            adapter = AxlfiAdapter()
            report = adapter.fetch_with_quality("SPY")

        assert report.status == SourceStatus.UNAVAILABLE
        assert report.error_category == ErrorCategory.NETWORK

    def test_get_data_with_quality_ok(self, adapter, valid_axlfi_data):
        """获取业务数据 + 质量报告"""
        data, report = adapter.get_data_with_quality("SPY")
        assert report.status == SourceStatus.OK
        assert data is not None
        assert data["symbol"] == "SPY"

    def test_get_data_with_quality_unavailable(self, mock_fetcher):
        """不可用状态下 data 为 None"""
        mock_fetcher.fetch_symbol_data.return_value = None

        with patch(
            "data_fetchers.axlfi_fetcher.AxlfiFetcher",
            return_value=mock_fetcher,
        ):
            adapter = AxlfiAdapter()
            data, report = adapter.get_data_with_quality("SPY")

        assert data is None
        assert not report.status.is_available

    def test_is_available_true(self, adapter):
        assert adapter.is_available() is True

    def test_is_available_false(self, mock_fetcher):
        mock_fetcher.fetch_symbol_data.return_value = None

        with patch(
            "data_fetchers.axlfi_fetcher.AxlfiFetcher",
            return_value=mock_fetcher,
        ):
            adapter = AxlfiAdapter()
            assert adapter.is_available() is False

    def test_get_status_summary(self, adapter):
        summary = adapter.get_status_summary()
        assert summary["source"] == "axlfi"
        assert summary["available"] is True
        assert summary["status"] == "OK"
        assert "latency_ms" in summary
        assert "last_verified_at" in summary

    def test_classify_error_timeout(self, adapter):
        from requests.exceptions import Timeout
        cat = adapter.classify_error(Timeout("timeout"))
        assert cat == ErrorCategory.NETWORK

    def test_classify_error_keyerror(self, adapter):
        cat = adapter.classify_error(KeyError("missing"))
        assert cat == ErrorCategory.STRUCTURE


# ═══════════════════════════════════════════════════════════════
# 结构校验测试
# ═══════════════════════════════════════════════════════════════

class TestAxlfiStructureValidation:
    """API 结构校验测试"""

    @pytest.fixture
    def adapter(self, mock_fetcher):
        with patch(
            "data_fetchers.axlfi_fetcher.AxlfiFetcher",
            return_value=mock_fetcher,
        ):
            return AxlfiAdapter()

    def test_validate_structure_pass(self, adapter, valid_axlfi_data):
        ok, msg = adapter._validate_structure(valid_axlfi_data, "SPY")
        assert ok is True
        assert "通过" in msg

    def test_validate_structure_missing_top_field(self, adapter):
        data = {"symbol": "SPY"}
        ok, msg = adapter._validate_structure(data, "SPY")
        assert ok is False
        assert "缺失顶层字段" in msg

    def test_validate_structure_missing_dp_field(self, adapter):
        data = {
            "as_of_date": "2026-06-09",
            "latest": {},
            "individual_dark_pool_position_data": {
                "dates": ["2026-06-09"],
                # 缺少 dollar_dp_position
            },
        }
        ok, msg = adapter._validate_structure(data, "SPY")
        assert ok is False
        assert "暗盘头寸缺失字段" in msg

    def test_validate_structure_empty_dp(self, adapter):
        data = {
            "as_of_date": "2026-06-09",
            "latest": {},
            "individual_dark_pool_position_data": {
                "dates": [],
                "dollar_dp_position": [],
            },
        }
        ok, msg = adapter._validate_structure(data, "SPY")
        assert ok is False
        assert "为空" in msg


# ═══════════════════════════════════════════════════════════════
# 旧接口兼容性测试
# ═══════════════════════════════════════════════════════════════

class TestAxlfiAdapterCompatibility:
    """确保适配器完全兼容原有 AxlfiFetcher 公共接口"""

    @pytest.fixture
    def adapter(self, mock_fetcher):
        with patch(
            "data_fetchers.axlfi_fetcher.AxlfiFetcher",
            return_value=mock_fetcher,
        ):
            return AxlfiAdapter()

    def test_fetch_symbol_data_delegates(self, adapter, mock_fetcher):
        result = adapter.fetch_symbol_data("QQQ", 60)
        mock_fetcher.fetch_symbol_data.assert_called_once_with("QQQ", 60)
        assert result is not None

    def test_fetch_leaderboard_delegates(self, adapter, mock_fetcher):
        mock_fetcher.fetch_leaderboard.return_value = [
            {"ticker": "SPY", "dollar_dp_position": -1.4e9}
        ]
        result = adapter.fetch_leaderboard("short_volume_percent", "desc", 10)
        mock_fetcher.fetch_leaderboard.assert_called_once_with(
            "short_volume_percent", "desc", 10
        )
        assert len(result) == 1

    def test_get_net_position_series_delegates(self, adapter, mock_fetcher):
        result = adapter.get_net_position_series("SPY", [20, 60])
        mock_fetcher.get_net_position_series.assert_called_once_with("SPY", [20, 60])
        assert "20d" in result

    def test_get_latest_short_metrics_delegates(self, adapter, mock_fetcher):
        result = adapter.get_latest_short_metrics("SPY")
        mock_fetcher.get_latest_short_metrics.assert_called_once_with("SPY")
        assert result["latest_short_pct"] == 52.0

    def test_detect_bottom_divergence_delegates(self, adapter, mock_fetcher):
        result = adapter.detect_bottom_divergence([1.0] * 60, [100.0] * 60)
        mock_fetcher.detect_bottom_divergence.assert_called_once()
        assert "divergence" in result
