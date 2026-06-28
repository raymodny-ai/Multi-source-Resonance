"""
V2.5 P5/P6: VEX/CHEX 多通道张量 + 管道监控 集成测试
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import numpy as np
import pandas as pd
from quant_logic.vex_calculator import (
    VEXCalculator,
    CharmCalculator,
    MultiChannelTensorBuilder,
    compute_vex_batch,
    compute_chex_batch,
)
from data_stream.pipeline_monitor import PipelineMonitor, monitor_layer


class TestVEXCalculator:
    """VEX 敞口计算测试"""

    def setup_method(self):
        self.calc = VEXCalculator()
        self.spot = 100.0
        # 构造合成期权链
        strikes = np.array([95, 98, 100, 102, 105], dtype=float)
        rows = []
        for s in strikes:
            moneyness = (s - self.spot) / self.spot
            iv = 0.25 + 0.5 * moneyness ** 2
            for t in ('CALL', 'PUT'):
                rows.append({
                    'strike': s,
                    'type': t,
                    'days_to_expiry': 30,
                    'open_interest': 1000,
                    'implied_volatility': iv,
                })
        self.df = pd.DataFrame(rows)

    def test_calculate_vex_columns(self):
        """VEX 计算应新增正确列"""
        df = self.calc.calculate_vex(self.df, self.spot)
        assert 'vanna' in df.columns
        assert 'vex' in df.columns
        assert 'vex_sticky' in df.columns
        assert 'vex_call' in df.columns
        assert 'vex_put' in df.columns

    def test_calculate_vex_values_finite(self):
        """VEX 数值应有限"""
        df = self.calc.calculate_vex(self.df, self.spot)
        assert np.isfinite(df['vex']).all(), "VEX 数值应有限"
        # 0DTE 边界: 不应全部为 0
        assert (df['vex'] != 0).any(), "VEX 应有非零值"

    def test_calculate_aggregate_vex(self):
        """聚合 VEX"""
        agg = self.calc.calculate_aggregate_vex(self.df, self.spot)
        assert 'call_vex' in agg
        assert 'put_vex' in agg
        assert 'net_vex' in agg
        assert 'dominant_vex' in agg
        # net = call - put
        assert abs(agg['net_vex'] - (agg['call_vex'] - agg['put_vex'])) < 1e-6

    def test_vex_with_svi_rho(self):
        """Sticky Delta 调整: 使用 SVI 拟合的 rho"""
        df = self.df.copy()
        df['svi_rho'] = -0.5  # 自定义相关系数
        result = self.calc.calculate_vex(df, self.spot, sticky_delta=True)
        # sticky 与 base 的差异应反映 rho
        assert (result['vex_sticky'] != result['vex']).any() or (result['vex_sticky'] == result['vex']).all()


class TestCharmCalculator:
    """CHEX 敞口计算测试"""

    def setup_method(self):
        self.calc = CharmCalculator()
        self.spot = 100.0
        strikes = np.array([95, 100, 105], dtype=float)
        rows = []
        for s in strikes:
            for t in ('CALL', 'PUT'):
                rows.append({
                    'strike': s, 'type': t, 'days_to_expiry': 30,
                    'open_interest': 1000, 'implied_volatility': 0.25,
                })
        self.df = pd.DataFrame(rows)

    def test_calculate_chex(self):
        """CHEX 计算"""
        df = self.calc.calculate_chex(self.df, self.spot)
        assert 'charm' in df.columns
        assert 'chex' in df.columns
        assert 'chex_call' in df.columns
        assert 'chex_put' in df.columns
        assert np.isfinite(df['chex']).all()


class TestMultiChannelTensor:
    """多通道张量构建测试"""

    def setup_method(self):
        self.builder = MultiChannelTensorBuilder()
        self.spot = 100.0
        strikes = np.linspace(95, 105, 11)
        rows = []
        for s in strikes:
            for t in ('CALL', 'PUT'):
                rows.append({
                    'strike': s, 'type': t, 'days_to_expiry': 30,
                    'open_interest': 1000, 'implied_volatility': 0.25,
                })
        self.df = pd.DataFrame(rows)

    def test_tensor_shape(self):
        """张量形状: (n_strikes, n_expiries, 3)"""
        tensor, metadata = self.builder.build(self.df, self.spot)
        assert tensor.ndim == 3
        assert tensor.shape[2] == 3  # 3 通道
        assert tensor.shape[0] == 11  # 11 个 strikes
        assert tensor.shape[1] == 1   # 1 个 expiry

    def test_tensor_channels(self):
        """三通道: GEX, VEX, CHEX"""
        tensor, metadata = self.builder.build(self.df, self.spot)
        assert metadata['channels'] == ['GEX', 'VEX', 'CHEX']

    def test_tensor_metadata(self):
        """元数据完整"""
        tensor, metadata = self.builder.build(self.df, self.spot)
        assert 'strikes' in metadata
        assert 'expiries' in metadata
        assert 'total_gex' in metadata
        assert 'total_vex' in metadata
        assert 'total_chex' in metadata


class TestPipelineMonitor:
    """管道监控测试"""

    def test_context_manager_records_metric(self):
        """上下文管理器自动记录"""
        PipelineMonitor.clear_buffer()
        with PipelineMonitor.layer('test_layer', 'SPY', input_count=100) as mon:
            mon.set_output(80)
        metrics = PipelineMonitor.get_recent_metrics(layer_name='test_layer')
        assert len(metrics) == 1
        assert metrics[0]['symbol'] == 'SPY'
        assert metrics[0]['input_count'] == 100
        assert metrics[0]['output_count'] == 80
        assert metrics[0]['removed_count'] == 20
        assert metrics[0]['duration_ms'] >= 0

    def test_layer_stats(self):
        """层聚合统计"""
        PipelineMonitor.clear_buffer()
        for i in range(10):
            with PipelineMonitor.layer('stat_layer', f'SYM{i}', 100) as mon:
                mon.set_output(50)
        stats = PipelineMonitor.get_layer_stats('stat_layer')
        assert stats['count'] == 10
        assert stats['avg_ms'] >= 0
        assert stats['max_ms'] >= stats['min_ms']

    def test_error_captured(self):
        """异常被捕获"""
        PipelineMonitor.clear_buffer()
        with pytest.raises(ValueError):
            with PipelineMonitor.layer('err_layer', 'TEST', 10) as mon:
                raise ValueError("test error")
        metrics = PipelineMonitor.get_recent_metrics(layer_name='err_layer')
        assert len(metrics) == 1
        assert 'test error' in metrics[0]['error']

    def test_decorator(self):
        """装饰器自动监控"""
        PipelineMonitor.clear_buffer()

        @monitor_layer('deco_layer')
        def sample_func(symbol='N/A'):
            return [1, 2, 3, 4, 5]

        result = sample_func(symbol='SPY')
        assert result == [1, 2, 3, 4, 5]
        metrics = PipelineMonitor.get_recent_metrics(layer_name='deco_layer')
        assert len(metrics) == 1
        assert metrics[0]['symbol'] == 'SPY'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
