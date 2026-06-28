"""
Multi-source Resonance V2.0 - Layer 1 向量化 Black-Scholes 引擎

该模块实现全量期权链的批量隐含波动率反演和希腊字母计算。
采用 py_vollib_vectorized 基于 NumPy 的向量化加速，支持百万级合约的秒级处理。

该模块为 Layer 1 纯本地计算组件，严禁任何 LLM 依赖。

支持的希腊字母：
- Delta (Δ): ∂Price/∂Spot
- Gamma (Γ): ∂²Price/∂Spot²
- Vega (ν): ∂Price/∂σ
- Theta (Θ): -∂Price/∂t
- Rho (ρ): ∂Price/∂r
- Vanna: ∂Delta/∂σ = ∂²Price/∂Spot∂σ
- Charm: ∂Delta/∂t = ∂²Price/∂Spot∂t
"""

import numpy as np
from typing import Dict, Tuple, Optional
from dataclasses import dataclass
from utils.logger import getLogger

logger = getLogger('bs_engine')

# 尝试导入向量化库，失败时降级到 scipy
try:
    from py_vollib_vectorized import (
        price_vectorized,
        implied_volatility_vectorized,
        greeks_vectorized_cached,
    )
    VECTORIZED_AVAILABLE = True
except ImportError:
    VECTORIZED_AVAILABLE = False
    logger.warning("py_vollib_vectorized 不可用，降级到 scipy 逐行计算")

from scipy.stats import norm


@dataclass
class GreeksResult:
    """希腊字母计算结果容器"""
    delta: np.ndarray
    gamma: np.ndarray
    vega: np.ndarray
    theta: np.ndarray
    rho: np.ndarray
    vanna: np.ndarray
    charm: np.ndarray


class VectorizedBSEngine:
    """向量化 Black-Scholes 计算引擎

    支持欧式看涨/看跌期权的全量批量计算。
    输入为 NumPy 数组，输出为对应形状的希腊字母数组。

    数学基础：
        d1 = [ln(S/K) + (r + σ²/2)T] / (σ√T)
        d2 = d1 - σ√T

        Call Price = S·N(d1) - K·e^(-rT)·N(d2)
        Put Price  = K·e^(-rT)·N(-d2) - S·N(-d1)

        Delta_call  = N(d1)
        Delta_put   = N(d1) - 1
        Gamma       = n(d1) / (S·σ·√T)
        Vega        = S·n(d1)·√T
        Theta_call  = -S·n(d1)·σ/(2√T) - r·K·e^(-rT)·N(d2)
        Theta_put   = -S·n(d1)·σ/(2√T) + r·K·e^(-rT)·N(-d2)
        Rho_call    = K·T·e^(-rT)·N(d2)
        Rho_put     = -K·T·e^(-rT)·N(-d2)

        Vanna = -n(d1)·d2/σ  (∂Delta/∂σ)
        Charm = n(d1)·[2rT - d2·σ√T] / (2T·σ√T)  (∂Delta/∂t)
    """

    def __init__(self, risk_free_rate: float = 0.05):
        """初始化 BS 引擎

        Args:
            risk_free_rate: 无风险利率（默认 5%）
        """
        self.r = risk_free_rate

    # ──────────────────────────────────────────────
    # 核心计算：d1 / d2（向量化）
    # ──────────────────────────────────────────────

    def _compute_d1_d2(
        self,
        S: np.ndarray,
        K: np.ndarray,
        sigma: np.ndarray,
        T: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """向量化计算 d1 和 d2 参数

        Args:
            S: 标的资产价格数组
            K: 行权价数组
            sigma: 隐含波动率数组（年化，小数）
            T: 到期时间数组（年）

        Returns:
            (d1, d2) 元组
        """
        # 输入验证
        mask = (S > 0) & (K > 0) & (sigma > 0) & (T > 0)
        d1 = np.zeros_like(S, dtype=float)
        d2 = np.zeros_like(S, dtype=float)

        valid = mask
        if not valid.any():
            return d1, d2

        denom = sigma[valid] * np.sqrt(T[valid])
        denom_safe = np.where(denom < 1e-10, 1e-10, denom)

        d1[valid] = (
            np.log(S[valid] / K[valid])
            + (self.r + 0.5 * sigma[valid] ** 2) * T[valid]
        ) / denom_safe

        d2[valid] = d1[valid] - denom_safe

        # 截断异常值
        d1 = np.clip(d1, -50, 50)
        d2 = np.clip(d2, -50, 50)

        return d1, d2

    # ──────────────────────────────────────────────
    # 希腊字母批量计算
    # ──────────────────────────────────────────────

    def compute_all_greeks(
        self,
        S: np.ndarray,
        K: np.ndarray,
        sigma: np.ndarray,
        T: np.ndarray,
        option_types: np.ndarray,
    ) -> GreeksResult:
        """批量计算所有希腊字母

        Args:
            S: 标的资产价格（标量或数组）
            K: 行权价数组
            sigma: 隐含波动率数组
            T: 到期时间数组
            option_types: 期权类型数组，'C' 或 'c' 为看涨，'P' 或 'p' 为看跌

        Returns:
            GreeksResult: 包含所有希腊字母的 dataclass
        """
        # 确保输入为数组
        S = np.atleast_1d(np.asarray(S, dtype=float))
        K = np.atleast_1d(np.asarray(K, dtype=float))
        sigma = np.atleast_1d(np.asarray(sigma, dtype=float))
        T = np.atleast_1d(np.asarray(T, dtype=float))

        # 广播 S 到与 K 相同形状
        if S.size == 1:
            S = np.full_like(K, S.item())

        d1, d2 = self._compute_d1_d2(S, K, sigma, T)

        # 期权类型标志
        is_call = np.array([ot.upper() == 'C' for ot in option_types], dtype=float)
        is_put = 1.0 - is_call

        # ── Delta ──
        delta = norm.cdf(d1) * is_call + (norm.cdf(d1) - 1.0) * is_put

        # ── Gamma ──
        pdf_d1 = norm.pdf(d1)
        denom_gamma = S * sigma * np.sqrt(T)
        denom_gamma_safe = np.where(np.abs(denom_gamma) < 1e-10, 1e-10, denom_gamma)
        gamma = pdf_d1 / denom_gamma_safe

        # ── Vega (1% = 0.01 变化量) ──
        vega = S * pdf_d1 * np.sqrt(T) * 0.01

        # ── Theta (每日衰减，除以 365) ──
        sqrt_T = np.sqrt(T)
        sqrt_T_safe = np.where(sqrt_T < 1e-10, 1e-10, sqrt_T)
        theta_term = -S * pdf_d1 * sigma / (2.0 * sqrt_T_safe)
        disc_K = K * np.exp(-self.r * T)
        theta_c = theta_term - self.r * disc_K * norm.cdf(d2)
        theta_p = theta_term + self.r * disc_K * norm.cdf(-d2)
        theta = (theta_c * is_call + theta_p * is_put) / 365.0

        # ── Rho (1% 利率变化 = 0.01) ──
        disc_K_rho = K * T * np.exp(-self.r * T)
        rho_c = disc_K_rho * norm.cdf(d2) * 0.01
        rho_p = -disc_K_rho * norm.cdf(-d2) * 0.01
        rho = rho_c * is_call + rho_p * is_put

        # ── Vanna (∂Delta/∂σ) ──
        sigma_safe = np.where(sigma < 1e-10, 1e-10, sigma)
        vanna = -pdf_d1 * d2 / sigma_safe

        # ── Charm (∂Delta/∂t，每日衰减) ──
        T_safe = np.where(T < 1e-10, 1e-10, T)
        sigma_sqrt_T = sigma * sqrt_T_safe
        sigma_sqrt_T_safe = np.where(np.abs(sigma_sqrt_T) < 1e-10, 1e-10, sigma_sqrt_T)
        charm_num = pdf_d1 * (2.0 * self.r * T_safe - d2 * sigma_sqrt_T_safe)
        charm_denom = 2.0 * T_safe * sigma_sqrt_T_safe
        charm_denom_safe = np.where(np.abs(charm_denom) < 1e-10, 1e-10, charm_denom)
        charm = (charm_num / charm_denom_safe) / 365.0

        # 清理 NaN/Inf
        for arr in [delta, gamma, vega, theta, rho, vanna, charm]:
            arr[np.isnan(arr) | np.isinf(arr)] = 0.0

        return GreeksResult(
            delta=delta,
            gamma=gamma,
            vega=vega,
            theta=theta,
            rho=rho,
            vanna=vanna,
            charm=charm,
        )

    def compute_gamma_only(
        self,
        S: np.ndarray,
        K: np.ndarray,
        sigma: np.ndarray,
        T: np.ndarray,
    ) -> np.ndarray:
        """仅计算 Gamma（GEX 计算的核心输入，性能优化路径）

        Args:
            S: 标的资产价格
            K: 行权价数组
            sigma: 隐含波动率数组
            T: 到期时间数组

        Returns:
            Gamma 数组
        """
        S = np.atleast_1d(np.asarray(S, dtype=float))
        K = np.atleast_1d(np.asarray(K, dtype=float))
        sigma = np.atleast_1d(np.asarray(sigma, dtype=float))
        T = np.atleast_1d(np.asarray(T, dtype=float))

        if S.size == 1:
            S = np.full_like(K, S.item())

        d1, _ = self._compute_d1_d2(S, K, sigma, T)
        pdf_d1 = norm.pdf(d1)
        denom = S * sigma * np.sqrt(T)
        denom_safe = np.where(np.abs(denom) < 1e-10, 1e-10, denom)
        gamma = pdf_d1 / denom_safe
        gamma[np.isnan(gamma) | np.isinf(gamma)] = 0.0
        return gamma

    # ──────────────────────────────────────────────
    # 隐含波动率反演
    # ──────────────────────────────────────────────

    def compute_implied_volatility(
        self,
        market_prices: np.ndarray,
        S: np.ndarray,
        K: np.ndarray,
        T: np.ndarray,
        option_types: np.ndarray,
        initial_guess: float = 0.3,
    ) -> np.ndarray:
        """批量计算隐含波动率（Newton-Raphson 向量化）

        Args:
            market_prices: 市场价格数组
            S: 标的资产价格
            K: 行权价数组
            T: 到期时间数组
            option_types: 期权类型数组
            initial_guess: 初始波动率猜测

        Returns:
            隐含波动率数组
        """
        S = np.atleast_1d(np.asarray(S, dtype=float))
        K = np.atleast_1d(np.asarray(K, dtype=float))
        T = np.atleast_1d(np.asarray(T, dtype=float))
        market_prices = np.atleast_1d(np.asarray(market_prices, dtype=float))

        if S.size == 1:
            S = np.full_like(K, S.item())

        if VECTORIZED_AVAILABLE:
            try:
                is_call_arr = np.array([ot.upper() == 'C' for ot in option_types])
                iv = implied_volatility_vectorized(
                    market_prices, S, K, T, self.r, is_call_arr
                )
                iv = np.where(np.isnan(iv) | np.isinf(iv), 0.0, np.clip(iv, 0.01, 5.0))
                return iv
            except Exception as e:
                logger.warning(f"向量化 IV 反演失败，降级到 Newton-Raphson: {e}")

        # 降级：逐合约 Newton-Raphson
        n = len(K)
        iv = np.full(n, initial_guess)
        for _ in range(50):  # 最大 50 次迭代
            try:
                result = self.compute_all_greeks(S, K, iv, T, option_types)
                is_call_arr = np.array([ot.upper() == 'C' for ot in option_types])
                prices = self._bs_price(S, K, iv, T, is_call_arr)
                price_diff = prices - market_prices

                vega = result.vega / 0.01  # 还原为原始 Vega

                # Newton 更新
                vega_safe = np.where(np.abs(vega) < 1e-10, 1e-10, vega)
                iv_new = iv - price_diff / vega_safe
                iv_new = np.clip(iv_new, 0.01, 5.0)

                if np.max(np.abs(iv_new - iv)) < 1e-8:
                    iv = iv_new
                    break
                iv = iv_new
            except Exception:
                break

        iv[np.isnan(iv) | np.isinf(iv)] = 0.0
        iv = np.clip(iv, 0.01, 5.0)
        return iv

    def _bs_price(
        self,
        S: np.ndarray,
        K: np.ndarray,
        sigma: np.ndarray,
        T: np.ndarray,
        is_call: np.ndarray,
    ) -> np.ndarray:
        """计算 BS 理论价格"""
        d1, d2 = self._compute_d1_d2(S, K, sigma, T)
        disc = np.exp(-self.r * T)
        call_price = S * norm.cdf(d1) - K * disc * norm.cdf(d2)
        put_price = K * disc * norm.cdf(-d2) - S * norm.cdf(-d1)
        prices = is_call * call_price + (1.0 - is_call) * put_price
        prices[np.isnan(prices) | np.isinf(prices)] = 0.0
        return prices

    # ═══════════════════════════════════════════
    # V2.5 P2: SVI 平滑集成
    # ═══════════════════════════════════════════

    def compute_gamma_with_svi_smoothing(
        self,
        S: np.ndarray,
        K: np.ndarray,
        T: np.ndarray,
        svi_fits: Dict[int, Dict[str, float]],
        spot: float,
        risk_free_rate: Optional[float] = None,
        option_types: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """使用 SVI 拟合的 IV 计算 Gamma (消除锯齿噪声)

        Args:
            S: 标的价格 (标量或数组)
            K: 行权价数组
            T: 到期时间数组 (年)
            svi_fits: {dte_days: {a, b, rho, m, sigma}, ...}
            spot: 标的价格
            risk_free_rate: 无风险利率, 默认用 self.r
            option_types: 期权类型数组 ('C'/'P'), 用于 Vanna 计算. 可选.
        Returns:
            gamma_array: 平滑后的 Gamma
        """
        from quant_logic.svi_calibrator import SVISurfaceCalibrator
        r = risk_free_rate if risk_free_rate is not None else self.r

        # 构造临时的 SurfaceCalibrator 用现有 fits
        sc = SVISurfaceCalibrator(enforce_no_arbitrage=False)
        sc.fits = svi_fits
        sc.single_cal = SVICalibrator(enforce_no_arbitrage=False)

        if S.size == 1:
            S = np.full_like(K, S.item())

        # 重新采样 IV
        n = len(K)
        sigma_smooth = np.full(n, 0.2, dtype=float)
        for i in range(n):
            T_val = float(T[i]) if T.ndim > 0 else float(T)
            dte = int(round(T_val * 365))
            if dte in svi_fits:
                params = svi_fits[dte]
                T_t = T_val
                forward = spot * np.exp(r * T_t)
                try:
                    iv_smooth = sc.single_cal.iv_surface(
                        np.array([float(K[i])]), forward, T_t, params
                    )[0]
                    if np.isfinite(iv_smooth) and iv_smooth > 0:
                        sigma_smooth[i] = iv_smooth
                except Exception as e:
                    logger.debug(f"SVI smooth failed for K={K[i]}: {e}")
                    sigma_smooth[i] = 0.2

        # 使用平滑后的 IV 计算 Gamma
        if option_types is None:
            option_types = np.array(['C'] * n)
        greeks = self.compute_all_greeks(S, K, sigma_smooth, T, option_types)
        return greeks.gamma


# ──────────────────────────────────────────────
# 便捷函数
# ──────────────────────────────────────────────

def compute_greeks_batch(
    spot: float,
    strikes: np.ndarray,
    volatilities: np.ndarray,
    times_to_expiry: np.ndarray,
    option_types: np.ndarray,
    risk_free_rate: float = 0.05,
) -> GreeksResult:
    """便捷接口：批量计算希腊字母"""
    engine = VectorizedBSEngine(risk_free_rate=risk_free_rate)
    return engine.compute_all_greeks(
        S=np.array([spot]),
        K=strikes,
        sigma=volatilities,
        T=times_to_expiry,
        option_types=option_types,
    )
