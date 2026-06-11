"""
测试: 数据质量状态模型 (source_status.py)

验证枚举值、错误分类逻辑、结构哈希计算和数据报告序列化。
"""

import pytest
from data_fetchers.source_status import (
    SourceStatus,
    ErrorCategory,
    SourceQualityReport,
    classify_error,
    compute_structure_hash,
    check_hash_change,
)


class TestSourceStatus:
    """SourceStatus 枚举行为测试"""

    def test_ok_is_available(self):
        assert SourceStatus.OK.is_available is True
        assert SourceStatus.OK.is_blocking is False

    def test_degraded_network_is_available(self):
        assert SourceStatus.DEGRADED_NETWORK.is_available is True
        assert SourceStatus.DEGRADED_NETWORK.is_blocking is False

    def test_structure_changed_is_blocking(self):
        assert SourceStatus.STRUCTURE_CHANGED.is_available is False
        assert SourceStatus.STRUCTURE_CHANGED.is_blocking is True

    def test_contract_violation_is_blocking(self):
        assert SourceStatus.CONTRACT_VIOLATION.is_available is False
        assert SourceStatus.CONTRACT_VIOLATION.is_blocking is True

    def test_unavailable_is_blocking(self):
        assert SourceStatus.UNAVAILABLE.is_available is False
        assert SourceStatus.UNAVAILABLE.is_blocking is True

    def test_string_values(self):
        assert SourceStatus.OK.value == "OK"
        assert SourceStatus.DEGRADED_NETWORK.value == "DEGRADED_NETWORK"
        assert SourceStatus.STRUCTURE_CHANGED.value == "STRUCTURE_CHANGED"
        assert SourceStatus.CONTRACT_VIOLATION.value == "CONTRACT_VIOLATION"
        assert SourceStatus.UNAVAILABLE.value == "UNAVAILABLE"


class TestErrorCategory:
    """ErrorCategory 枚举行为测试"""

    def test_network_is_retryable(self):
        assert ErrorCategory.NETWORK.is_retryable is True

    def test_structure_is_not_retryable(self):
        assert ErrorCategory.STRUCTURE.is_retryable is False

    def test_contract_is_not_retryable(self):
        assert ErrorCategory.CONTRACT.is_retryable is False

    def test_unknown_is_not_retryable(self):
        assert ErrorCategory.UNKNOWN.is_retryable is False


class TestClassifyError:
    """错误分类逻辑测试"""

    def test_timeout_is_network(self):
        from requests.exceptions import Timeout
        category = classify_error(Timeout("Connection timed out"))
        assert category == ErrorCategory.NETWORK

    def test_connection_error_is_network(self):
        from requests.exceptions import ConnectionError as ReqConnError
        category = classify_error(ReqConnError("Connection refused"))
        assert category == ErrorCategory.NETWORK

    def test_http_503_is_network(self):
        import requests
        try:
            resp = requests.Response()
            resp.status_code = 503
            raise requests.exceptions.HTTPError("503 Server Error", response=resp)
        except requests.exceptions.HTTPError as e:
            category = classify_error(e)
            assert category == ErrorCategory.NETWORK

    def test_http_404_is_contract(self):
        import requests
        try:
            resp = requests.Response()
            resp.status_code = 404
            raise requests.exceptions.HTTPError("404 Not Found", response=resp)
        except requests.exceptions.HTTPError as e:
            category = classify_error(e)
            assert category == ErrorCategory.CONTRACT

    def test_key_error_is_structure(self):
        category = classify_error(KeyError("missing_column"))
        assert category == ErrorCategory.STRUCTURE

    def test_value_error_is_contract(self):
        category = classify_error(ValueError("invalid literal"))
        assert category == ErrorCategory.CONTRACT

    def test_builtin_value_error_is_structure(self):
        category = classify_error(AttributeError("'NoneType' has no attribute 'keys'"))
        assert category == ErrorCategory.STRUCTURE

    def test_unknown_exception_is_unknown(self):
        category = classify_error(RuntimeError("something unexpected"))
        assert category == ErrorCategory.UNKNOWN


class TestSourceQualityReport:
    """质量报告数据结构测试"""

    def test_default_ok(self):
        report = SourceQualityReport(source_name="test_source")
        assert report.source_name == "test_source"
        assert report.status == SourceStatus.OK
        assert report.is_available is True

    def test_to_dict(self):
        report = SourceQualityReport(
            source_name="squeezemetrics",
            status=SourceStatus.OK,
            error_category=ErrorCategory.UNKNOWN,
            latency_ms=150.5,
            last_verified_at="2026-06-09",
        )
        d = report.to_dict()
        assert d["source_name"] == "squeezemetrics"
        assert d["status"] == "OK"
        assert d["latency_ms"] == 150.5
        assert d["last_verified_at"] == "2026-06-09"

    def test_to_dict_truncates_error_detail(self):
        report = SourceQualityReport(
            source_name="test",
            error_detail="x" * 1000,
        )
        d = report.to_dict()
        assert len(d["error_detail"]) <= 500

    def test_fetch_timestamp_auto(self):
        report = SourceQualityReport(source_name="test")
        assert report.fetch_timestamp is not None
        assert "T" in report.fetch_timestamp


class TestStructureHash:
    """结构哈希计算测试"""

    def test_same_elements_produce_same_hash(self):
        elements = {"chart": ".darkpool-chart", "table": ".net-position-table"}
        h1 = compute_structure_hash(elements)
        h2 = compute_structure_hash(elements)
        assert h1 == h2

    def test_different_elements_produce_different_hash(self):
        h1 = compute_structure_hash({"a": ".selector-1"})
        h2 = compute_structure_hash({"a": ".selector-2"})
        assert h1 != h2

    def test_hash_length(self):
        h = compute_structure_hash({"test": ".test"})
        assert len(h) == 16

    def test_check_hash_change_no_previous(self):
        result = check_hash_change("abc123", "")
        assert result["changed"] is False

    def test_check_hash_change_detected(self):
        result = check_hash_change("new_hash", "old_hash")
        assert result["changed"] is True
        assert result["previous"] == "old_hash"
        assert result["current"] == "new_hash"
