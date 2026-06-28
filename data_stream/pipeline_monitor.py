"""
V2.5 P6: 管道监控与可观测性

提供:
  - 各层处理耗时记录
  - 输入/输出/剔除数量统计
  - 异常告警
  - 指标写入 ClickHouse / SQLite
  - 上下文管理器 (with block) 自动埋点

Examples:
    >>> from data_stream.pipeline_monitor import PipelineMonitor
    >>> with PipelineMonitor.layer('layer1_filter', 'SPY', input_count=1000) as mon:
    ...     filtered_df = ...  # 处理
    ...     mon.set_output(len(filtered_df))
"""
from __future__ import annotations

import time
import json
import logging
from contextlib import contextmanager
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

from utils.logger import getLogger

logger = getLogger('pipeline_monitor')


# ── 内存指标存储 (降级) ──
_METRICS_BUFFER: List[Dict[str, Any]] = []
_MAX_BUFFER_SIZE = 5000


class LayerMetric:
    """单层管道指标"""

    def __init__(
        self,
        layer_name: str,
        symbol: str,
        input_count: int = 0,
        output_count: int = 0,
        removed_count: int = 0,
        error: str = '',
        metadata: Optional[Dict] = None,
    ):
        self.layer_name = layer_name
        self.symbol = symbol
        self.input_count = input_count
        self.output_count = output_count
        self.removed_count = removed_count
        self.error = error
        self.metadata = metadata or {}
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.duration_ms: int = 0

    def set_output(self, count: int):
        self.output_count = count
        self.removed_count = max(self.input_count - count, 0)

    def add_metadata(self, key: str, value: Any):
        self.metadata[key] = value

    def to_dict(self) -> Dict[str, Any]:
        return {
            'layer_name': self.layer_name,
            'symbol': self.symbol,
            'duration_ms': self.duration_ms,
            'input_count': self.input_count,
            'output_count': self.output_count,
            'removed_count': self.removed_count,
            'error': self.error,
            'metadata': json.dumps(self.metadata, ensure_ascii=False),
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }


class PipelineMonitor:
    """V2.5 管道监控器 (P6)"""

    # 性能告警阈值 (ms)
    LAYER_WARN_THRESHOLD_MS = {
        'layer1_filter': 50,
        'layer2_vectorized': 200,
        'layer2.5_svi_smooth': 500,
        'layer3_tensor_build': 100,
        'layer4_llm_inference': 5000,
    }
    LAYER_ERROR_THRESHOLD_MS = {
        'layer1_filter': 200,
        'layer2_vectorized': 1000,
        'layer2.5_svi_smooth': 2000,
        'layer3_tensor_build': 500,
        'layer4_llm_inference': 30000,
    }

    @staticmethod
    @contextmanager
    def layer(
        layer_name: str,
        symbol: str = 'N/A',
        input_count: int = 0,
    ):
        """上下文管理器: 自动记录单层处理耗时

        Usage:
            with PipelineMonitor.layer('layer1_filter', 'SPY', 1000) as mon:
                filtered = ...
                mon.set_output(len(filtered))
        """
        metric = LayerMetric(layer_name=layer_name, symbol=symbol, input_count=input_count)
        metric.start_time = time.perf_counter()
        try:
            yield metric
        except Exception as e:
            metric.error = str(e)
            logger.error(f"[{layer_name}] {symbol} 异常: {e}")
            raise
        finally:
            metric.end_time = time.perf_counter()
            metric.duration_ms = int((metric.end_time - metric.start_time) * 1000)
            PipelineMonitor._record(metric)

    @staticmethod
    def _record(metric: LayerMetric):
        """记录单条指标"""
        # 1. 写入内存 buffer
        _METRICS_BUFFER.append(metric.to_dict())
        if len(_METRICS_BUFFER) > _MAX_BUFFER_SIZE:
            _METRICS_BUFFER.pop(0)

        # 2. 写入 ClickHouse (如果可用)
        try:
            from database.clickhouse_client import get_client
            ch_client = get_client()
            ch_client.insert_pipeline_metric(
                layer_name=metric.layer_name,
                symbol=metric.symbol,
                duration_ms=metric.duration_ms,
                input_count=metric.input_count,
                output_count=metric.output_count,
                removed_count=metric.removed_count,
                error=metric.error,
                metadata=metric.metadata,
            )
        except Exception as e:
            logger.debug(f"ClickHouse 指标写入失败: {e}")

        # 3. 检查性能告警
        warn_thr = PipelineMonitor.LAYER_WARN_THRESHOLD_MS.get(metric.layer_name)
        err_thr = PipelineMonitor.LAYER_ERROR_THRESHOLD_MS.get(metric.layer_name)

        if err_thr and metric.duration_ms > err_thr:
            logger.error(
                f"[P6 严重] {metric.layer_name} {metric.symbol} "
                f"耗时 {metric.duration_ms}ms > {err_thr}ms 阈值"
            )
        elif warn_thr and metric.duration_ms > warn_thr:
            logger.warning(
                f"[P6 警告] {metric.layer_name} {metric.symbol} "
                f"耗时 {metric.duration_ms}ms > {warn_thr}ms 阈值"
            )
        else:
            logger.info(
                f"[P6] {metric.layer_name} {metric.symbol} "
                f"耗时 {metric.duration_ms}ms (in={metric.input_count}, "
                f"out={metric.output_count}, removed={metric.removed_count})"
            )

    @staticmethod
    def get_recent_metrics(
        layer_name: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """获取最近的指标记录"""
        results = _METRICS_BUFFER
        if layer_name:
            results = [m for m in results if m['layer_name'] == layer_name]
        if symbol:
            results = [m for m in results if m['symbol'] == symbol]
        return list(results)[-limit:]

    @staticmethod
    def get_layer_stats(
        layer_name: str,
        symbol: Optional[str] = None,
        window: int = 50,
    ) -> Dict[str, Any]:
        """获取单层聚合统计 (avg/min/max/p95/p99)"""
        metrics = PipelineMonitor.get_recent_metrics(
            layer_name=layer_name, symbol=symbol, limit=window,
        )
        if not metrics:
            return {
                'count': 0, 'avg_ms': 0, 'min_ms': 0,
                'max_ms': 0, 'p95_ms': 0, 'p99_ms': 0,
            }
        durations = [m['duration_ms'] for m in metrics]
        durations_sorted = sorted(durations)
        n = len(durations_sorted)
        return {
            'count': n,
            'avg_ms': round(sum(durations) / n, 2),
            'min_ms': min(durations),
            'max_ms': max(durations),
            'p95_ms': durations_sorted[min(int(n * 0.95), n - 1)],
            'p99_ms': durations_sorted[min(int(n * 0.99), n - 1)],
        }

    @staticmethod
    def clear_buffer():
        """清空内存 buffer (测试用)"""
        _METRICS_BUFFER.clear()


# ── 便捷装饰器 ──
def monitor_layer(layer_name: str, symbol_arg: str = 'symbol'):
    """装饰器: 自动监控函数耗时

    Usage:
        @monitor_layer('layer1_filter', symbol_arg='symbol')
        def filter_options(option_chain_df, symbol='SPY'):
            ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            # 提取 symbol (从 kwargs 或 args)
            symbol = kwargs.get(symbol_arg, 'N/A')
            input_count = kwargs.get('input_count', 0)
            with PipelineMonitor.layer(layer_name, symbol, input_count) as mon:
                result = func(*args, **kwargs)
                # 尝试推断 output_count
                if hasattr(result, '__len__'):
                    mon.set_output(len(result))
                return result
        return wrapper
    return decorator
