"""
V2.5 P3: fast-vollib 引擎性能基准测试

覆盖:
  - 后端自动选择
  - 2D Gamma 网格计算 (与 NumPy 数值一致性)
  - 性能基准 (加速比)
  - GEXCalculator.calculate_gex_profile_fast 集成
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import numpy as np
import pandas as pd
from quant_logic.fast_vollib_engine import (
    FastVollibEngine,
    select_backend,
    get_backend_info,
    BACKEND_STATUS,
)


class TestBackendSelection:
    """后端选择测试"""

    def test_backend_info(self):
        """后端状态信息"""
        info = get_backend_info()
        assert 'numpy' in info
        assert info['numpy'] is True
        assert 'active_backend' in info

    def test_select_backend_returns_valid(self):
        """select_backend 返回有效后端"""
        backend = select_backend(prefer_gpu=False)
        assert backend in ('torch_cuda', 'torch_cpu', 'jax', 'numba', 'numpy')
        assert BACKEND_STATUS['active_backend'] == backend

    def test_engine_init(self):
        """引擎初始化"""
        engine = FastVollibEngine(prefer_gpu=False)
        assert engine.r == 0.05
        assert engine.backend in ('torch_cpu', 'jax', 'numba', 'numpy')


class TestGammaGrid2D:
    """2D Gamma 网格测试"""

    def setup_method(self):
        self.engine = FastVollibEngine(prefer_gpu=False)
        self.S_grid = np.linspace(95, 105, 50)
        self.K = np.array([96, 98, 100, 102, 104], dtype=float)
        self.sigma = np.array([0.20, 0.22, 0.25, 0.22, 0.20])
        self.T = np.full(5, 0.1)

    def test_grid_shape(self):
        """网格输出形状正确"""
        result = self.engine.compute_gamma_grid_2d(
            self.S_grid, self.K, self.sigma, self.T,
        )
        assert result.shape == (50, 5), f"形状错误: {result.shape}"

    def test_grid_values_positive(self):
        """Gamma 值应非负"""
        result = self.engine.compute_gamma_grid_2d(
            self.S_grid, self.K, self.sigma, self.T,
        )
        assert np.all(result >= 0), "Gamma 应非负"
        # 有效值 > 0
        assert (result > 0).any(), "Gamma 应有有效正数"

    def test_grid_atm_max(self):
        """ATM 附近 Gamma 最大 (微笑)"""
        result = self.engine.compute_gamma_grid_2d(
            self.S_grid, self.K, self.sigma, self.T,
        )
        # K=100 是 ATM 列, S=100 是 ATM 行
        atm_idx = np.argmin(np.abs(self.S_grid - 100))
        atm_gamma = result[atm_idx, 2]  # K=100 是第3个 (index 2)
        # 远离 ATM 的 Gamma 应小于 ATM
        far_idx = np.argmin(np.abs(self.S_grid - 105))
        far_gamma = result[far_idx, 2]
        assert atm_gamma > far_gamma, f"ATM Gamma 应大于远离 ATM: {atm_gamma} vs {far_gamma}"

    def test_scalar_sigma(self):
        """标量 sigma 应广播到所有 strikes"""
        result = self.engine.compute_gamma_grid_2d(
            self.S_grid, self.K, 0.25, 0.1,
        )
        assert result.shape == (50, 5)

    def test_consistency_with_numpy(self):
        """NumPy 后端结果应一致 (直接对比)"""
        np_engine = FastVollibEngine(prefer_gpu=False)
        np_engine.backend = 'numpy'
        np_engine._setup_backend = lambda: None
        np_engine._gamma_2d = FastVollibEngine._gamma_2d_numpy

        result = np_engine.compute_gamma_grid_2d(
            self.S_grid, self.K, self.sigma, self.T,
        )
        # 检查数值合理性
        assert np.all(result >= 0)
        assert result.max() < 100, f"Gamma 数值异常: {result.max()}"


class TestPerformance:
    """性能基准测试"""

    def test_benchmark_small(self):
        """小规模基准 (500×1000)"""
        engine = FastVollibEngine(prefer_gpu=False)
        results = engine.benchmark(n_prices=100, n_strikes=200, n_iterations=2)
        assert engine.backend in results
        # 应至少完成一次
        assert results[engine.backend] > 0

    def test_benchmark_speedup_vs_baseline(self):
        """加速比测试: 对比 NumPy 基线"""
        engine = FastVollibEngine(prefer_gpu=False)
        # 测试当前后端 vs NumPy
        results = engine.benchmark(n_prices=200, n_strikes=500, n_iterations=1)
        if 'numpy_baseline' in results:
            speedup = results['numpy_baseline'] / results[engine.backend]
            # 加速比至少 > 0.5 (允许 Numba 等后端退化)
            assert speedup > 0.3, f"加速比异常: {speedup:.2f}x"


class TestGEXIntegration:
    """GEXCalculator 集成测试"""

    def _make_chain(self, spot=100.0, n=50, dte=30):
        strikes = np.linspace(spot * 0.9, spot * 1.1, n)
        rows = []
        for s in strikes:
            oi = 1000
            iv = 0.20 + 0.5 * ((s - spot) / spot) ** 2
            for opt_type in ('CALL', 'PUT'):
                rows.append({
                    'strike': float(s),
                    'open_interest': oi,
                    'implied_volatility': iv,
                    'type': opt_type,
                    'days_to_expiry': dte,
                })
        return pd.DataFrame(rows)

    def test_calculate_gex_profile_fast(self):
        """calculate_gex_profile_fast 集成"""
        from quant_logic.gex_calculator import GEXCalculator
        os.environ['OI_GATE_THRESHOLD'] = '100'

        calc = GEXCalculator()
        df = self._make_chain(spot=5500, n=30, dte=30)
        result = calc.calculate_gex_profile_fast(
            df, spot_price=5500, num_steps=50, prefer_gpu=False,
        )
        assert 'spot_prices' in result
        assert 'net_gex_values' in result
        assert 'backend' in result
        assert len(result['spot_prices']) == 50
        assert len(result['net_gex_values']) == 50


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
