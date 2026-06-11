"""
测试: Stockgrid 适配器 (stockgrid_adapter.py)

验证配置驱动、结构哈希、质量报告输出、UNAVAILABLE 状态标记。
"""

import pytest
from data_fetchers.stockgrid_adapter import (
    StockgridAdapterConfig,
    StockgridAdapter,
    create_stockgrid_adapter,
)
from data_fetchers.source_status import SourceStatus, ErrorCategory


class TestStockgridAdapterConfig:
    """适配器配置测试"""

    def test_default_config(self):
        config = StockgridAdapterConfig()
        assert config.base_url == "https://stockgrid.io"
        assert config.xhr_url_pattern == "api/darkpool"
        assert "chart_container" in config.dom_selectors
        assert config.last_verified_at is not None
        assert config.max_retries == 3

    def test_get_darkpool_url(self):
        config = StockgridAdapterConfig()
        url = config.get_darkpool_url("SPY")
        assert "stockgrid.io" in url
        assert "SPY" in url
        assert "darkpool" in url

    def test_get_structure_hash(self):
        config = StockgridAdapterConfig()
        h = config.get_structure_hash()
        assert len(h) == 16
        assert isinstance(h, str)

    def test_custom_config(self):
        config = StockgridAdapterConfig(
            base_url="https://custom.example.com",
            max_retries=5,
            last_verified_at="2026-01-01",
        )
        assert config.base_url == "https://custom.example.com"
        assert config.max_retries == 5
        assert config.last_verified_at == "2026-01-01"


class TestStockgridAdapter:
    """适配器行为测试"""

    def test_factory(self):
        adapter = create_stockgrid_adapter()
        assert isinstance(adapter, StockgridAdapter)

    def test_fetch_quality_report_returns_unavailable(self):
        adapter = StockgridAdapter()
        report = adapter.fetch_quality_report("SPY")
        assert report.status == SourceStatus.UNAVAILABLE
        assert report.source_name == "stockgrid"
        assert "axlfi" in report.error_detail.lower()
        assert report.error_detail  # 应该有详细说明

    def test_is_available_returns_false(self):
        adapter = StockgridAdapter()
        assert adapter.is_available() is False

    def test_fetch_net_position_history(self):
        adapter = StockgridAdapter()
        result = adapter.fetch_net_position_history("SPY")
        assert result["status"] == "UNAVAILABLE"
        assert result["periods"] == {}
        assert result["data"] is None
        assert "quality_report" in result
        assert result["quality_report"]["source_name"] == "stockgrid"

    def test_get_status_summary(self):
        adapter = StockgridAdapter()
        summary = adapter.get_status_summary()
        assert summary["source"] == "stockgrid"
        assert summary["available"] is False
        assert summary["status"] == "UNAVAILABLE"
        assert "AXLFI" in summary["recommended_replacement"]

    def test_classify_error_timeout_returns_network(self):
        adapter = StockgridAdapter()
        from requests.exceptions import Timeout
        cat = adapter.classify_error(Timeout("timeout"))
        assert cat == ErrorCategory.NETWORK

    def test_classify_error_keyerror_returns_structure(self):
        adapter = StockgridAdapter()
        cat = adapter.classify_error(KeyError("missing"))
        assert cat == ErrorCategory.STRUCTURE


class TestStructureHashMonitoring:
    """结构哈希监控测试"""

    def test_get_current_structure_hash(self):
        adapter = StockgridAdapter()
        h = adapter.get_current_structure_hash()
        assert len(h) == 16

    def test_verify_structure_first_run_no_change(self):
        adapter = StockgridAdapter()
        adapter._last_known_hash = ""  # 重置
        result = adapter.verify_structure()
        assert result["changed"] is False

    def test_verify_structure_detects_change(self):
        adapter = StockgridAdapter()
        adapter._last_known_hash = "abcd1234efgh5678"
        result = adapter.verify_structure(
            current_hash="different_hash_"
        )
        assert result["changed"] is True
        assert result["previous"] == "abcd1234efgh5678"

    def test_update_last_known_hash(self):
        adapter = StockgridAdapter()
        adapter.update_last_known_hash("new_hash_123456")
        assert adapter._last_known_hash == "new_hash_123456"
