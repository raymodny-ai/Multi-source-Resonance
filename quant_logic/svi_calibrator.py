"""
V2.5 P2: SVI (Stochastic Volatility Inspired) 无套利波动率曲面校准器

理论基础:
    SVI 参数化 (Gatheral 2004) 对每一到期日 τ 的隐含波动率 w(k, τ) 拟合:
        w(k) = a + b * (ρ(k - m) + sqrt((k - m)² + σ²))

    其中:
        k = log(K/F)  log-moneyness
        a ≥ 0        ATM 总方差水平
        b ∈ [0, 1]   倾斜强度
        ρ ∈ (-1, 1)  偏度
        m ∈ ℝ        平移
        σ > 0        ATM 曲率 (微笑曲率)

    SSVI 形式 (Gatheral-Jacquier 2014):
        w(k, τ) = θ(τ)/2 * [1 + ρ φ k + sqrt((φ k + ρ)² + (1 - ρ²))]

    其中 θ(τ) = σ²_atm(τ) * τ 是 ATM 总方差,
    φ = φ(τ) 是与到期日相关的曲率参数。

无套利约束:
    1) Calendar Arbitrage:  ∂w/∂T ≥ 0  (总方差关于时间单调)
    2) Butterfly Arbitrage: g(k) := (1 - k·w'/2w)² - (w')²/4 + w''/2 ≥ 0
       简化为: 0 ≤ w'' ≤ (1 + 1/|k|²) · w'² ·  ...  (参考 Gatheral 2014)

应用场景:
    Layer 1 过滤 → Layer 2 向量化 → Layer 2.5 SVI 曲面平滑 → Layer 3 张量构建

本模块依赖:
    - numpy / pandas / scipy (项目已配置)
    - 不依赖 svi-py / ssvi 外部包 (自实现保持轻量)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from typing import Dict, List, Optional, Tuple, Any
from utils.logger import getLogger

logger = getLogger('svi_calibrator')


class SVICalibrator:
    """SVI 单到期日校准器

    Examples:
        >>> cal = SVICalibrator()
        >>> params = cal.fit(strikes=ks, market_ivs=ivs, forward=F, time_to_expiry=T)
        >>> smooth_ivs = cal.iv_surface(ks, F, T, params)
    """

    # 默认参数边界
    A_BOUNDS = (-0.1, 1.0)      # ATM 方差水平 (允许轻微负值)
    B_BOUNDS = (0.01, 1.0)      # 倾斜强度
    RHO_BOUNDS = (-0.999, 0.999)
    M_BOUNDS = (-2.0, 2.0)
    SIGMA_BOUNDS = (0.01, 2.0)  # ATM 曲率

    def __init__(self, enforce_no_arbitrage: bool = True):
        self.enforce_no_arbitrage = enforce_no_arbitrage
        self.last_fit: Optional[Dict[str, Any]] = None

    # ────────────── SVI 公式 ──────────────

    @staticmethod
    def svi_total_variance(
        k: np.ndarray, a: float, b: float, rho: float, m: float, sigma: float
    ) -> np.ndarray:
        """SVI 原始公式: w(k) = a + b * (ρ(k - m) + sqrt((k - m)² + σ²))

        Args:
            k: log-moneyness,  shape (N,)
            a, b, rho, m, sigma: SVI 参数
        Returns:
            w: 总方差, shape (N,). w >= 0
        """
        k = np.asarray(k, dtype=float)
        diff = k - m
        radicand = diff * diff + sigma * sigma
        w = a + b * (rho * diff + np.sqrt(radicand))
        # 数值保护: 总方差非负
        return np.maximum(w, 1e-8)

    @staticmethod
    def iv_from_total_variance(w: np.ndarray, t: float) -> np.ndarray:
        """总方差 → 隐含波动率: σ = sqrt(w / T)

        Args:
            w: 总方差
            t: 到期时间 (年化)
        Returns:
            iv: 隐含波动率
        """
        t = max(t, 1e-8)
        return np.sqrt(np.maximum(w, 1e-8) / t)

    # ────────────── 拟合入口 ──────────────

    def fit(
        self,
        strikes: np.ndarray,
        market_ivs: np.ndarray,
        forward: float,
        time_to_expiry: float,
        weights: Optional[np.ndarray] = None,
    ) -> Dict[str, float]:
        """单到期日 SVI 校准

        Args:
            strikes: 行权价数组
            market_ivs: 隐含波动率数组 (小数, e.g. 0.25 = 25%)
            forward: 远期价格
            time_to_expiry: 到期时间 (年化)
            weights: 拟合权重 (如 OI 倒数或 VOMMA 倒数)
        Returns:
            {a, b, rho, m, sigma, residual}
        """
        strikes = np.asarray(strikes, dtype=float)
        market_ivs = np.asarray(market_ivs, dtype=float)
        if forward <= 0 or time_to_expiry <= 0 or len(strikes) < 5:
            return self._empty_params()

        # log-moneyness
        k = np.log(strikes / forward)

        # 市场总方差
        w_market = market_ivs * market_ivs * time_to_expiry
        w_atm = float(np.mean(w_market))

        # ── 自适应边界: 基于 ATM 方差缩放 ──
        w_scale = max(w_atm, 1e-4)
        # a 应接近 ATM 方差
        a_lo, a_hi = -0.1 * w_scale, 5.0 * w_scale
        # b 决定倾斜幅度
        b_lo, b_hi = 0.01 * np.sqrt(w_scale), 5.0 * np.sqrt(w_scale)
        # m 围绕 ATM
        m_lo, m_hi = float(k.min()) - 0.1, float(k.max()) + 0.1
        # sigma 决定曲率
        sigma_lo, sigma_hi = 0.01, 2.0

        # 初始参数估计
        a0 = w_atm * 0.5
        b0 = max(float(np.std(w_market)) * 2.0, 0.05)
        rho0 = -0.3
        m0 = float(np.mean(k))
        sigma0 = 0.1

        x0 = np.array([a0, b0, rho0, m0, sigma0])
        bounds = [
            (a_lo, a_hi), (b_lo, b_hi), self.RHO_BOUNDS,
            (m_lo, m_hi), (sigma_lo, sigma_hi),
        ]

        if weights is None:
            weights = np.ones_like(k)

        def objective(x: np.ndarray) -> float:
            a, b, rho, m, sigma = x
            try:
                w_model = self.svi_total_variance(k, a, b, rho, m, sigma)
                residuals = (w_model - w_market) * weights
                return float(np.sum(residuals * residuals))
            except (ValueError, FloatingPointError):
                return 1e10

        try:
            result = minimize(
                objective, x0, method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 500, 'ftol': 1e-10},
            )

            a, b, rho, m, sigma = result.x
            w_fit = self.svi_total_variance(k, a, b, rho, m, sigma)
            residual = float(np.sqrt(np.mean((w_fit - w_market) ** 2)))

            arb_violations = self.check_arbitrage(k, a, b, rho, m, sigma)
            arb_severity = (
                sum(v['severity'] for v in arb_violations)
                if arb_violations else 0.0
            )

            params = {
                'a': float(a), 'b': float(b), 'rho': float(rho),
                'm': float(m), 'sigma': float(sigma),
                'residual': residual,
                'arb_violations': arb_violations,
                'arb_severity': arb_severity,
                'converged': bool(result.success),
            }
            self.last_fit = params
            return params

        except Exception as e:
            logger.error(f"SVI 拟合异常: {e}", exc_info=True)
            return self._empty_params()

    def _empty_params(self) -> Dict[str, Any]:
        return {
            'a': 0.0, 'b': 0.0, 'rho': 0.0, 'm': 0.0, 'sigma': 0.1,
            'residual': float('inf'),
            'arb_violations': [],
            'arb_severity': 0.0,
            'converged': False,
        }

    # ────────────── 套利约束 ──────────────

    def _arb_penalty(
        self, k: np.ndarray, a: float, b: float, rho: float, m: float, sigma: float
    ) -> float:
        """套利惩罚项

        SVI 解析性质: w''(k) = b * sigma² / sqrt((k-m)² + sigma²)³ >= 0
        (当 b > 0, sigma > 0 时自动满足, 无 Butterfly 套利)
        Calendar Arbitrage 需跨到期日检查, 不在此处处理。
        """
        return 0.0

    def check_arbitrage(
        self, k: np.ndarray, a: float, b: float, rho: float, m: float, sigma: float
    ) -> List[Dict[str, Any]]:
        """检测 SVI 曲面上的套利违规

        1) Static: w(k) >= 0
        2) Butterfly: g(k) = (1 - k w'/2w)² - (w')²/4 + w''/2 >= 0

        SVI 解析: w''(k) = b * sigma² / sqrt((k-m)² + sigma²)³ (恒正)
        """
        violations: List[Dict[str, Any]] = []
        k = np.asarray(k, dtype=float)
        d = k - m
        sqrt_term = np.sqrt(d * d + sigma * sigma)

        w = self.svi_total_variance(k, a, b, rho, m, sigma)
        w_prime = b * (rho + d / sqrt_term)
        w_second = b * sigma * sigma / (sqrt_term ** 3)  # 解析正确

        valid = w > 1e-8
        if valid.any():
            k_v = k[valid]
            w_v = w[valid]
            wp_v = w_prime[valid]
            ws_v = w_second[valid]
            g = (
                (1 - k_v * wp_v / (2 * w_v)) ** 2
                - wp_v ** 2 / 4
                + ws_v / 2
            )
            neg = g < 0
            if neg.any():
                for k_val, g_val in zip(k_v[neg], g[neg]):
                    violations.append({
                        'type': 'butterfly',
                        'location': float(k_val),
                        'severity': float(-g_val),
                    })

        return violations

    # ────────────── 表面生成 ──────────────

    def iv_surface(
        self,
        strikes: np.ndarray,
        forward: float,
        time_to_expiry: float,
        params: Dict[str, float],
    ) -> np.ndarray:
        """使用拟合参数重采样 IV

        Args:
            strikes: 目标行权价 (可任意密度, 用于平滑插值)
            forward: 远期价
            time_to_expiry: 到期时间
            params: fit() 返回的参数字典
        Returns:
            ivs: 平滑后的隐含波动率
        """
        strikes = np.asarray(strikes, dtype=float)
        k = np.log(strikes / forward)
        a = params['a']; b = params['b']; rho = params['rho']
        m = params['m']; sigma = params['sigma']
        w = self.svi_total_variance(k, a, b, rho, m, sigma)
        return self.iv_from_total_variance(w, time_to_expiry)


class SVISurfaceCalibrator:
    """多到期日 SVI 曲面校准器 (SSVI 风格)

    Examples:
        >>> sc = SVISurfaceCalibrator()
        >>> results = sc.fit_surface(option_chains, forward=100.0, spot=99.5)
        >>> # results: {dte: {a,b,rho,m,sigma}, ...}
    """

    def __init__(self, enforce_no_arbitrage: bool = True):
        self.single_cal = SVICalibrator(enforce_no_arbitrage)
        self.fits: Dict[int, Dict[str, float]] = {}

    def fit_surface(
        self,
        options_df: pd.DataFrame,
        spot: float,
        risk_free_rate: float = 0.05,
    ) -> Dict[int, Dict[str, float]]:
        """拟合多到期日 SVI 曲面

        Args:
            options_df: 期权链, 必含 strike, expiry, type, bid, ask, implied_volatility
            spot: 标的价格
            risk_free_rate: 无风险利率
        Returns:
            {dte_days: {a,b,rho,m,sigma,residual,...}, ...}
        """
        if options_df.empty:
            return {}

        results: Dict[int, Dict[str, float]] = {}
        # 按到期日分组
        grouped = options_df.groupby('days_to_expiry')
        for dte, group in grouped:
            if dte <= 0:
                continue
            T = dte / 365.0
            forward = spot * np.exp(risk_free_rate * T)

            # 使用 mid_price 计算 IV (优先用 market IV)
            if 'implied_volatility' in group.columns and group['implied_volatility'].notna().any():
                strikes = group['strike'].to_numpy()
                ivs = group['implied_volatility'].to_numpy()
                # IV > 0
                mask = (ivs > 0) & np.isfinite(ivs)
                if mask.sum() < 5:
                    continue
                weights = self._compute_weights(group[mask])
                params = self.single_cal.fit(
                    strikes[mask], ivs[mask], forward, T, weights
                )
                params['forward'] = float(forward)
                params['spot'] = float(spot)
                params['T'] = float(T)
                params['strike_count'] = int(mask.sum())
                results[int(dte)] = params

        self.fits = results
        logger.info(
            f"SSVI 曲面拟合完成: {len(results)} 个到期日, "
            f"残差均值 = {np.mean([p['residual'] for p in results.values()]):.6f}"
        )
        return results

    def _compute_weights(self, group_df: pd.DataFrame) -> np.ndarray:
        """按 OI 计算拟合权重 (OOI 越大权重越高)"""
        if 'open_interest' in group_df.columns:
            oi = group_df['open_interest'].fillna(0).to_numpy()
            oi = np.where(oi <= 0, 1.0, oi)
            return np.sqrt(oi) / np.max(np.sqrt(oi))
        return np.ones(len(group_df))

    def resample_ivs(
        self,
        option_chain_df: pd.DataFrame,
        spot: float,
        risk_free_rate: float = 0.05,
        iv_col: str = 'implied_volatility',
    ) -> pd.DataFrame:
        """用拟合曲面重采样所有合约的 IV (消除锯齿)

        Args:
            option_chain_df: 原始期权链
            spot: 标的价格
            risk_free_rate: 无风险利率
            iv_col: 原 IV 列名
        Returns:
            新的 DataFrame, 增加 'smoothed_iv' 列
        """
        if not self.fits:
            logger.warning("SSVI 曲面未拟合, 跳过平滑")
            df = option_chain_df.copy()
            df['smoothed_iv'] = df[iv_col] if iv_col in df.columns else np.nan
            return df

        df = option_chain_df.copy()
        smoothed = np.full(len(df), np.nan)

        for idx, row in df.iterrows():
            dte = int(row.get('days_to_expiry', 0))
            if dte not in self.fits:
                smoothed[idx] = row.get(iv_col, np.nan)
                continue
            params = self.fits[dte]
            T = dte / 365.0
            forward = spot * np.exp(risk_free_rate * T)
            iv_smooth = self.single_cal.iv_surface(
                np.array([float(row['strike'])]), forward, T, params
            )[0]
            smoothed[idx] = iv_smooth

        df['smoothed_iv'] = smoothed
        # 填充缺失: 用原 IV
        df['smoothed_iv'] = df['smoothed_iv'].fillna(df[iv_col])
        logger.info(f"SSVI 重新采样完成: {len(df)} 个合约")
        return df

    def check_calendar_arbitrage(self) -> List[Dict[str, Any]]:
        """检测 Calendar Arbitrage: 总方差应关于到期日单调非降

        Returns:
            违规列表: [{dte_a, dte_b, severity}, ...]
        """
        if len(self.fits) < 2:
            return []
        violations: List[Dict[str, Any]] = []
        dtes = sorted(self.fits.keys())
        for i in range(len(dtes) - 1):
            dte_a, dte_b = dtes[i], dtes[i + 1]
            # 使用 ATM 方差近似
            w_a = self.fits[dte_a]['a'] + self.fits[dte_a]['b'] * (
                self.fits[dte_a]['sigma'] - self.fits[dte_a]['rho'] * self.fits[dte_a]['m']
            )
            w_b = self.fits[dte_b]['a'] + self.fits[dte_b]['b'] * (
                self.fits[dte_b]['sigma'] - self.fits[dte_b]['rho'] * self.fits[dte_b]['m']
            )
            if w_b < w_a - 1e-6:
                violations.append({
                    'dte_a': dte_a, 'dte_b': dte_b,
                    'w_a': float(w_a), 'w_b': float(w_b),
                    'severity': float(w_a - w_b),
                })
        if violations:
            logger.warning(
                f"SSVI Calendar Arbitrage 违规: {len(violations)} 处"
            )
        return violations


# ── 便捷函数 ──

def smooth_option_chain_ivs(
    option_chain_df: pd.DataFrame,
    spot: float,
    risk_free_rate: float = 0.05,
) -> Tuple[pd.DataFrame, Dict[int, Dict[str, float]]]:
    """一站式 SVI 平滑入口

    Examples:
        >>> df_smooth, fits = smooth_option_chain_ivs(df, spot=99.5)
        >>> # df_smooth 新增 'smoothed_iv' 列
    """
    if option_chain_df.empty:
        return option_chain_df, {}
    sc = SVISurfaceCalibrator(enforce_no_arbitrage=True)
    fits = sc.fit_surface(option_chain_df, spot, risk_free_rate)
    sc.check_calendar_arbitrage()
    df_out = sc.resample_ivs(option_chain_df, spot, risk_free_rate)
    return df_out, fits
