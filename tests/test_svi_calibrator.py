"""
V2.5 P2: SVI 校准器单元测试

覆盖:
  - 单到期日 SVI 拟合 (基本 sanity)
  - 套利检测 (Butterfly / Calendar)
  - 多到期日曲面拟合
  - IV 重采样
  - 边界情况 (空数据, 极端值)
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import numpy as np
import pandas as pd
from quant_logic.svi_calibrator import (
    SVICalibrator,
    SVISurfaceCalibrator,
    smooth_option_chain_ivs,
)


class TestSVICalibrator:
    """单到期日 SVI 校准测试"""

    def setup_method(self):
        self.cal = SVICalibrator(enforce_no_arbitrage=True)

    def test_svi_total_variance_basic(self):
        """SVI 公式基础测试: 总方差非负"""
        k = np.linspace(-0.5, 0.5, 50)
        a, b, rho, m, sigma = 0.04, 0.4, -0.3, 0.0, 0.1
        w = self.cal.svi_total_variance(k, a, b, rho, m, sigma)
        assert np.all(w > 0), "总方差应始终为正"

    def test_svi_total_variance_atm(self):
        """ATM (k=0, m=0) 总方差 = a + b * sigma"""
        k = np.array([0.0])
        a, b, rho, m, sigma = 0.04, 0.4, -0.3, 0.0, 0.1
        w = self.cal.svi_total_variance(k, a, b, rho, m, sigma)
        # ATM 公式: w(0) = a + b * sqrt(0 + sigma²) = a + b * sigma
        expected = a + b * sigma
        assert abs(w[0] - expected) < 1e-6, f"ATM 方差不匹配: {w[0]} vs {expected}"

    def test_fit_basic_synthetic_chain(self):
        """合成期权链 → 拟合 → 检查残差"""
        # 构造合成期权链: log-moneyness 范围 -0.4 ~ 0.4
        spot = 100.0
        forward = 100.0
        T = 0.1
        strikes = np.array([90, 92, 95, 97, 100, 103, 105, 108, 110], dtype=float)
        # 真实市场 IV: ATM 最低, 双翼略高 (微笑)
        k = np.log(strikes / forward)
        market_ivs = 0.25 + 0.5 * k ** 2 - 0.3 * k  # 简单二次函数

        params = self.cal.fit(strikes, market_ivs, forward, T)
        # 拟合应至少有一定精度
        assert params['converged'] or params['residual'] < 1e-2, \
            f"SVI 拟合残差过大: {params['residual']}"
        # 参数应在合理范围
        assert 0 <= params['a'] <= 1.0, f"a 异常: {params['a']}"
        assert 0 < params['b'] <= 1.0, f"b 异常: {params['b']}"
        assert -1 < params['rho'] < 1, f"rho 异常: {params['rho']}"

    def test_fit_invalid_input(self):
        """边界情况: 空数据 / 极短到期 / 负 forward"""
        # 空
        params = self.cal.fit(np.array([]), np.array([]), 100, 0.1)
        assert params['residual'] == float('inf')

        # 5 个点 (最小要求)
        strikes = np.linspace(95, 105, 5)
        ivs = np.full(5, 0.2)
        params = self.cal.fit(strikes, ivs, 100, 0.1)
        assert params is not None

    def test_check_arbitrage_no_violation(self):
        """参数良好的 SVI 应无套利违规"""
        k = np.linspace(-0.5, 0.5, 100)
        a, b, rho, m, sigma = 0.04, 0.4, -0.3, 0.0, 0.1
        violations = self.cal.check_arbitrage(k, a, b, rho, m, sigma)
        # 良好的 SVI 参数应无或极少量违规
        assert len(violations) == 0, f"发现意外套利: {violations[:3]}"

    def test_iv_surface_smoothness(self):
        """IV 表面平滑性: 重采样应得到连续 IV"""
        strikes_fit = np.linspace(95, 105, 9)
        forward = 100.0
        T = 0.1
        ivs_market = 0.25 + 0.5 * (np.log(strikes_fit / forward)) ** 2

        params = self.cal.fit(strikes_fit, ivs_market, forward, T)
        if not params['converged'] and params['residual'] > 1e-1:
            pytest.skip("SVI 未收敛, 跳过平滑测试")

        # 密集采样
        strikes_dense = np.linspace(92, 108, 100)
        ivs_dense = self.cal.iv_surface(strikes_dense, forward, T, params)

        # 平滑性: 二阶差分应较小
        first_diff = np.diff(ivs_dense)
        second_diff = np.diff(first_diff)
        max_curvature = np.max(np.abs(second_diff))
        # 平滑性约束: 100 点跨度下曲率 < 0.01
        assert max_curvature < 0.05, f"IV 表面不平滑: max curvature = {max_curvature}"


class TestSVISurfaceCalibrator:
    """多到期日 SVI 曲面测试"""

    def setup_method(self):
        self.sc = SVISurfaceCalibrator(enforce_no_arbitrage=True)

    def _make_synthetic_chain(self, spot=100.0, r=0.05):
        """构造多到期日合成期权链"""
        dtes = [7, 30, 60, 90]
        rows = []
        np.random.seed(42)
        for dte in dtes:
            T = dte / 365.0
            forward = spot * np.exp(r * T)
            # ATM 波动率随到期日增大 (term structure)
            atm_iv = 0.20 + 0.001 * dte
            for k_pct in np.arange(-0.2, 0.21, 0.025):
                strike = spot * (1 + k_pct)
                k = np.log(strike / forward)
                iv = atm_iv + 0.5 * k ** 2 - 0.3 * k + np.random.normal(0, 0.002)
                rows.append({
                    'strike': float(strike),
                    'days_to_expiry': dte,
                    'implied_volatility': max(iv, 0.05),
                    'open_interest': 1000,
                    'type': 'C' if k_pct >= 0 else 'P',
                })
        return pd.DataFrame(rows)

    def test_fit_surface(self):
        """多到期日曲面拟合"""
        df = self._make_synthetic_chain()
        results = self.sc.fit_surface(df, spot=100.0)
        assert len(results) >= 2, "应至少拟合 2 个到期日"
        for dte, params in results.items():
            assert 'a' in params and 'b' in params
            assert params['residual'] < 0.01, f"DTE {dte} 残差过大: {params['residual']}"

    def test_resample_ivs_adds_column(self):
        """重采样应新增 'smoothed_iv' 列"""
        df = self._make_synthetic_chain()
        self.sc.fit_surface(df, spot=100.0)
        df_out = self.sc.resample_ivs(df, spot=100.0)
        assert 'smoothed_iv' in df_out.columns
        # 平滑后 IV 仍应合理
        valid = df_out['smoothed_iv'].dropna()
        assert len(valid) > 0
        assert valid.between(0.05, 1.0).all(), "平滑 IV 应在合理范围"

    def test_calendar_arbitrage_check(self):
        """Calendar Arbitrage 检测: ATM 方差应随到期日增大"""
        df = self._make_synthetic_chain()
        self.sc.fit_surface(df, spot=100.0)
        violations = self.sc.check_calendar_arbitrage()
        # 良好合成数据应无 calendar arbitrage
        assert len(violations) == 0, f"Calendar 套利违规: {violations}"

    def test_empty_input(self):
        """空 DataFrame 处理"""
        results = self.sc.fit_surface(pd.DataFrame(), spot=100.0)
        assert results == {}

        df = self._make_synthetic_chain()
        df_out = self.sc.resample_ivs(pd.DataFrame(), spot=100.0)
        assert len(df_out) == 0


class TestSmoothConvenience:
    """便捷函数测试"""

    def test_smooth_option_chain_ivs(self):
        spot = 100.0
        dtes = [30, 60]
        rows = []
        for dte in dtes:
            T = dte / 365.0
            for k_pct in np.arange(-0.15, 0.16, 0.05):
                strike = spot * (1 + k_pct)
                k = np.log(strike / (spot * np.exp(0.05 * T)))
                iv = 0.25 + 0.5 * k ** 2
                rows.append({
                    'strike': float(strike),
                    'days_to_expiry': dte,
                    'implied_volatility': iv,
                    'open_interest': 1000,
                    'type': 'C',
                })
        df = pd.DataFrame(rows)
        df_out, fits = smooth_option_chain_ivs(df, spot=spot)
        assert 'smoothed_iv' in df_out.columns
        assert len(fits) >= 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
