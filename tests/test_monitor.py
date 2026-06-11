"""
测试: 数据源健康监控 (monitor.py)

验证每日统计、连续不可用检测和告警触发逻辑。
"""

import json
import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from data_fetchers.monitor import (
    DailySourceStats,
    MonitorReport,
    SourceHealthMonitor,
    create_health_monitor,
)


class TestDailySourceStats:
    """单日统计模型测试"""

    def test_defaults(self):
        stats = DailySourceStats(source_name="axlfi", date="2026-06-09")
        assert stats.source_name == "axlfi"
        assert stats.fetch_attempts == 0
        assert stats.success_rate == 0.0
        assert stats.avg_latency_ms == 0.0

    def test_success_rate(self):
        stats = DailySourceStats(source_name="test", date="2026-06-09")
        stats.fetch_attempts = 10
        stats.fetch_successes = 8
        assert stats.success_rate == 0.8

    def test_success_rate_zero_attempts(self):
        stats = DailySourceStats(source_name="test", date="2026-06-09")
        assert stats.success_rate == 0.0

    def test_avg_latency(self):
        stats = DailySourceStats(source_name="test", date="2026-06-09")
        stats.fetch_successes = 5
        stats.total_latency_ms = 500.0
        assert stats.avg_latency_ms == 100.0

    def test_avg_latency_zero_successes(self):
        stats = DailySourceStats(source_name="test", date="2026-06-09")
        stats.fetch_successes = 0
        stats.total_latency_ms = 500.0
        assert stats.avg_latency_ms == 0.0


class TestMonitorReport:
    """监控报告测试"""

    def test_empty_report(self):
        report = MonitorReport(date="2026-06-09")
        assert report.overall_status == "OK"
        assert report.sources == {}

    def test_report_to_dict(self):
        stats = DailySourceStats(source_name="axlfi", date="2026-06-09")
        stats.fetch_attempts = 10
        stats.fetch_successes = 9
        stats.total_latency_ms = 450.0
        stats.network_errors = 1

        report = MonitorReport(
            date="2026-06-09",
            sources={"axlfi": stats},
            overall_status="OK",
        )

        d = report.to_dict()
        assert d["date"] == "2026-06-09"
        assert d["overall_status"] == "OK"
        assert d["sources"]["axlfi"]["success_rate"] == 0.9
        assert d["sources"]["axlfi"]["network_errors"] == 1


class TestSourceHealthMonitor:
    """健康监控器行为测试"""

    def test_factory(self):
        monitor = create_health_monitor()
        assert isinstance(monitor, SourceHealthMonitor)

    def test_record_fetch_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = SourceHealthMonitor(stats_dir=tmpdir)
            monitor.record_fetch("axlfi", success=True, latency_ms=250.0)
            monitor.record_fetch("axlfi", success=True, latency_ms=300.0)

            stats = monitor._today_stats["axlfi"]
            assert stats.fetch_attempts == 2
            assert stats.fetch_successes == 2
            assert stats.total_latency_ms == 550.0

    def test_record_fetch_network_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = SourceHealthMonitor(stats_dir=tmpdir)
            monitor.record_fetch(
                "squeezemetrics", success=False, error_category="NETWORK"
            )

            stats = monitor._today_stats["squeezemetrics"]
            assert stats.fetch_attempts == 1
            assert stats.fetch_successes == 0
            assert stats.network_errors == 1

    def test_record_fetch_contract_violation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = SourceHealthMonitor(stats_dir=tmpdir)
            monitor.record_fetch(
                "squeezemetrics", success=False, error_category="CONTRACT"
            )

            stats = monitor._today_stats["squeezemetrics"]
            assert stats.contract_violations == 1

    def test_record_fetch_structure_changed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = SourceHealthMonitor(stats_dir=tmpdir)
            monitor.record_fetch(
                "axlfi", success=False, structure_changed=True
            )

            stats = monitor._today_stats["axlfi"]
            assert stats.structure_changes == 1

    def test_generate_daily_report_ok(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = SourceHealthMonitor(stats_dir=tmpdir)
            monitor.record_fetch("axlfi", success=True)
            monitor.record_fetch("squeezemetrics", success=True)

            report = monitor.generate_daily_report()
            assert report.overall_status == "OK"

    def test_generate_daily_report_degraded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = SourceHealthMonitor(stats_dir=tmpdir)
            monitor.record_fetch("axlfi", success=True)
            monitor.record_fetch("squeezemetrics", success=False)

            report = monitor.generate_daily_report()
            assert report.overall_status == "DEGRADED"

    def test_generate_daily_report_critical(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = SourceHealthMonitor(stats_dir=tmpdir)
            monitor.record_fetch("axlfi", success=False)
            monitor.record_fetch("squeezemetrics", success=False)

            report = monitor.generate_daily_report()
            assert report.overall_status == "CRITICAL"

    def test_save_daily_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = SourceHealthMonitor(stats_dir=tmpdir)
            monitor.record_fetch("axlfi", success=True, latency_ms=100.0)

            filepath = monitor.save_daily_report()
            assert os.path.exists(filepath)
            assert "monitor_" in filepath

            with open(filepath, "r") as f:
                data = json.load(f)
            assert data["overall_status"] == "OK"

    def test_check_consecutive_unavailable_yes(self):
        """模拟连续3天不可用"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 手动写入前3天的报告 (全失败)
            from datetime import date, timedelta
            for i in range(1, 4):
                day = (date.today() - timedelta(days=i)).isoformat()
                report = {
                    "date": day,
                    "overall_status": "DEGRADED",
                    "sources": {
                        "axlfi": {
                            "success_rate": 0.0,
                            "attempts": 1,
                            "successes": 0,
                            "structure_changes": 0,
                            "contract_violations": 0,
                            "network_errors": 1,
                            "avg_latency_ms": 0.0,
                        }
                    },
                }
                filepath = os.path.join(tmpdir, f"monitor_{day}.json")
                with open(filepath, "w") as f:
                    json.dump(report, f)

            monitor = SourceHealthMonitor(stats_dir=tmpdir)
            # 今天也失败
            monitor.record_fetch("axlfi", success=False, error_category="NETWORK")
            monitor.save_daily_report()

            result = monitor.check_consecutive_unavailable("axlfi", threshold_days=3)
            assert result is True

    def test_check_consecutive_unavailable_no(self):
        """有一天成功则不算连续不可用"""
        with tempfile.TemporaryDirectory() as tmpdir:
            from datetime import date, timedelta
            # 2天前成功
            day = (date.today() - timedelta(days=2)).isoformat()
            report = {
                "date": day,
                "overall_status": "OK",
                "sources": {
                    "axlfi": {
                        "success_rate": 1.0,
                        "attempts": 1,
                        "successes": 1,
                        "structure_changes": 0,
                        "contract_violations": 0,
                        "network_errors": 0,
                        "avg_latency_ms": 100.0,
                    }
                },
            }
            filepath = os.path.join(tmpdir, f"monitor_{day}.json")
            with open(filepath, "w") as f:
                json.dump(report, f)

            # 昨天失败
            day2 = (date.today() - timedelta(days=1)).isoformat()
            report2 = {
                "date": day2,
                "overall_status": "DEGRADED",
                "sources": {
                    "axlfi": {
                        "success_rate": 0.0,
                        "attempts": 1,
                        "successes": 0,
                        "structure_changes": 0,
                        "contract_violations": 0,
                        "network_errors": 1,
                        "avg_latency_ms": 0.0,
                    }
                },
            }
            filepath2 = os.path.join(tmpdir, f"monitor_{day2}.json")
            with open(filepath2, "w") as f:
                json.dump(report2, f)

            monitor = SourceHealthMonitor(stats_dir=tmpdir)
            # 今天也失败
            monitor.record_fetch("axlfi", success=False)
            monitor.save_daily_report()

            result = monitor.check_consecutive_unavailable("axlfi", threshold_days=3)
            # 只有2天连续失败，第3天是成功的
            assert result is False

    def test_trigger_unavailable_alert_calls_sender(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = SourceHealthMonitor(stats_dir=tmpdir)

            mock_sender = MagicMock()
            mock_sender.send_critical_alert.return_value = {
                "email": True, "telegram": True, "discord": False
            }

            with patch(
                "notification.alert_sender.create_alert_sender",
                return_value=mock_sender,
            ):
                result = monitor.trigger_unavailable_alert("axlfi")

            assert result is True
            mock_sender.send_critical_alert.assert_called_once()
            call_args = mock_sender.send_critical_alert.call_args
            assert "axlfi" in call_args[0][0]  # 第一个位置参数是 subject
