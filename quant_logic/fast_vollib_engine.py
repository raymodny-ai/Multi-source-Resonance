"""
V2.5 P3: fast-vollib 高性能向量化引擎 (GPU/JAX 加速 + 自动降级)

提供与 py-vollib-vectorized 兼容的 API, 后端优先级:
    1) PyTorch CUDA GPU (NVIDIA 显卡 + CUDA Toolkit)
    2) PyTorch CPU (多线程)
    3) JAX JIT (CPU/GPU/TPU 透明)
    4) Numba JIT (CPU 并行)
    5) NumPy 标量 (终极降级)

所有后端使用统一的 NumPy 输入/输出接口, 调用方无感。

应用场景:
    - 动态 Gamma Flip 模拟: 500 虚拟价格 × 1000 行权价 = 50 万次 Greeks
    - 历史回测: 1.18 亿条 tick 数据的批量 IV 反演
    - 实时盘中: 30 秒内完成全链 GEX 重算
"""
from __future__ import annotations

import numpy as np
from typing import Dict, List, Optional, Tuple, Any
import time
import logging
from utils.logger import getLogger

logger = getLogger('fast_vollib')

# ── 后端可用性探测 ──
BACKEND_STATUS: Dict[str, Any] = {
    'torch_cuda': False,
    'torch_cpu': False,
    'jax': False,
    'numba': False,
    'numpy': True,  # 总可用
    'active_backend': 'numpy',
    'gpu_name': None,
}

try:
    import torch
    BACKEND_STATUS['torch_cpu'] = True
    if torch.cuda.is_available():
        BACKEND_STATUS['torch_cuda'] = True
        BACKEND_STATUS['gpu_name'] = torch.cuda.get_device_name(0)
        logger.info(f"PyTorch CUDA 可用: {BACKEND_STATUS['gpu_name']}")
except ImportError:
    pass

try:
    import jax
    import jax.numpy as jnp
    BACKEND_STATUS['jax'] = True
    logger.info("JAX 可用")
except ImportError:
    pass

try:
    from numba import njit, prange
    BACKEND_STATUS['numba'] = True
    logger.info("Numba 可用")
except ImportError:
    pass


def select_backend(prefer_gpu: bool = True) -> str:
    """根据可用性选择最优后端

    Returns:
        后端名称: 'torch_cuda' / 'torch_cpu' / 'jax' / 'numba' / 'numpy'
    """
    if prefer_gpu and BACKEND_STATUS['torch_cuda']:
        BACKEND_STATUS['active_backend'] = 'torch_cuda'
        return 'torch_cuda'
    if BACKEND_STATUS['torch_cpu']:
        BACKEND_STATUS['active_backend'] = 'torch_cpu'
        return 'torch_cpu'
    if BACKEND_STATUS['jax']:
        BACKEND_STATUS['active_backend'] = 'jax'
        return 'jax'
    if BACKEND_STATUS['numba']:
        BACKEND_STATUS['active_backend'] = 'numba'
        return 'numba'
    BACKEND_STATUS['active_backend'] = 'numpy'
    return 'numpy'


# ── 核心 Black-Scholes 实现 (各后端) ──

def _norm_cdf(x):
    """标准正态 CDF (NumPy)"""
    from scipy.stats import norm
    return norm.cdf(x)


def _norm_pdf(x):
    """标准正态 PDF (NumPy)"""
    from scipy.stats import norm
    return norm.pdf(x)


class FastVollibEngine:
    """统一接口的 fast-vollib 引擎

    Examples:
        >>> engine = FastVollibEngine(prefer_gpu=True)
        >>> gammas = engine.compute_gamma_grid_2d(
        ...     S_grid=np.linspace(90, 110, 50),
        ...     K=np.array([95, 100, 105]),
        ...     sigma=0.25,
        ...     T=0.1,
        ... )
        >>> # 输出形状: (50, 3)
    """

    def __init__(self, prefer_gpu: bool = True, risk_free_rate: float = 0.05):
        self.r = risk_free_rate
        self.backend = select_backend(prefer_gpu=prefer_gpu)
        logger.info(f"FastVollib 引擎初始化: backend={self.backend}")
        self._setup_backend()

    def _setup_backend(self):
        """根据后端选择, 预编译计算函数"""
        if self.backend == 'torch_cuda':
            import torch
            self.device = torch.device('cuda')
            self._gamma_2d = self._gamma_2d_torch_cuda
        elif self.backend == 'torch_cpu':
            import torch
            self.device = torch.device('cpu')
            self._gamma_2d = self._gamma_2d_torch_cpu
        elif self.backend == 'jax':
            self._gamma_2d = self._gamma_2d_jax
        elif self.backend == 'numba':
            try:
                from numba import njit, prange
                self._gamma_2d = self._gamma_2d_numba
            except ImportError:
                self._gamma_2d = self._gamma_2d_numpy
        else:
            self._gamma_2d = self._gamma_2d_numpy

    # ────────────── 核心: 二维 Gamma 网格 ──────────────

    def compute_gamma_grid_2d(
        self,
        S_grid: np.ndarray,
        K: np.ndarray,
        sigma: np.ndarray,
        T: np.ndarray,
    ) -> np.ndarray:
        """计算 (S × K) 二维 Gamma 网格

        Args:
            S_grid: 标的价格数组, shape (n_prices,)
            K: 行权价数组, shape (n_strikes,)
            sigma: 波动率数组, shape (n_strikes,) or scalar
            T: 到期时间数组 (年), shape (n_strikes,) or scalar
        Returns:
            gamma_grid: shape (n_prices, n_strikes)
        """
        return self._gamma_2d(S_grid, K, sigma, T)

    # ── NumPy 后端 (基线) ──
    @staticmethod
    def _gamma_2d_numpy(
        S_grid: np.ndarray,
        K: np.ndarray,
        sigma: np.ndarray,
        T: np.ndarray,
    ) -> np.ndarray:
        """NumPy 实现的二维 Gamma 网格 (基线性能)"""
        S_grid = np.asarray(S_grid, dtype=np.float64)
        K = np.asarray(K, dtype=np.float64)
        sigma = np.asarray(sigma, dtype=np.float64)
        T = np.asarray(T, dtype=np.float64)

        # 广播: (n_prices, 1) × (1, n_strikes) → (n_prices, n_strikes)
        S = S_grid[:, None]
        if sigma.ndim == 0:
            sigma = np.full_like(K, float(sigma))
        if T.ndim == 0:
            T = np.full_like(K, float(T))

        d1 = (np.log(S / K[None, :]) + (0.05 + 0.5 * sigma[None, :] ** 2) * T[None, :]) / (
            sigma[None, :] * np.sqrt(np.maximum(T[None, :], 1e-10))
        )
        d1 = np.clip(d1, -50, 50)
        pdf_d1 = _norm_pdf(d1)
        denom = S * sigma[None, :] * np.sqrt(np.maximum(T[None, :], 1e-10))
        gamma = pdf_d1 / np.maximum(denom, 1e-10)
        return np.where(np.isfinite(gamma), gamma, 0.0)

    # ── PyTorch 后端 ──
    def _gamma_2d_torch_cpu(self, S_grid, K, sigma, T):
        """PyTorch CPU 多线程"""
        import torch
        return self._gamma_2d_torch_impl(S_grid, K, sigma, T, torch.device('cpu'))

    def _gamma_2d_torch_cuda(self, S_grid, K, sigma, T):
        """PyTorch CUDA GPU"""
        import torch
        return self._gamma_2d_torch_impl(S_grid, K, sigma, T, torch.device('cuda'))

    def _gamma_2d_torch_impl(self, S_grid, K, sigma, T, device):
        """PyTorch 通用实现 (CPU/GPU)"""
        import torch
        S_g = torch.as_tensor(S_grid, dtype=torch.float64, device=device)
        K_t = torch.as_tensor(K, dtype=torch.float64, device=device)
        sigma_t = torch.as_tensor(
            sigma if hasattr(sigma, '__len__') else [float(sigma)] * len(K),
            dtype=torch.float64, device=device,
        )
        T_t = torch.as_tensor(
            T if hasattr(T, '__len__') else [float(T)] * len(K),
            dtype=torch.float64, device=device,
        )

        # 广播
        S = S_g.unsqueeze(1)
        sqrt_T = torch.sqrt(torch.clamp(T_t.unsqueeze(0), min=1e-10))
        d1 = (
            torch.log(S / K_t.unsqueeze(0))
            + (self.r + 0.5 * sigma_t.unsqueeze(0) ** 2) * T_t.unsqueeze(0)
        ) / (sigma_t.unsqueeze(0) * sqrt_T)
        d1 = torch.clamp(d1, -50, 50)

        # 标准正态 PDF (PyTorch)
        pdf_d1 = torch.exp(-0.5 * d1 ** 2) / np.sqrt(2 * np.pi)
        denom = S * sigma_t.unsqueeze(0) * sqrt_T
        gamma = pdf_d1 / torch.clamp(denom, min=1e-10)
        gamma = torch.where(torch.isfinite(gamma), gamma, torch.zeros_like(gamma))

        return gamma.cpu().numpy()

    # ── JAX 后端 ──
    def _gamma_2d_jax(self, S_grid, K, sigma, T):
        """JAX JIT 编译"""
        try:
            import jax
            import jax.numpy as jnp
        except ImportError:
            return self._gamma_2d_numpy(S_grid, K, sigma, T)

        @jax.jit
        def compute(S_g, K_a, sigma_a, T_a, r):
            S = S_g[:, None]
            sqrt_T = jnp.sqrt(jnp.maximum(T_a[None, :], 1e-10))
            d1 = (
                jnp.log(S / K_a[None, :])
                + (r + 0.5 * sigma_a[None, :] ** 2) * T_a[None, :]
            ) / (sigma_a[None, :] * sqrt_T)
            d1 = jnp.clip(d1, -50, 50)
            pdf_d1 = jnp.exp(-0.5 * d1 ** 2) / jnp.sqrt(2 * jnp.pi)
            denom = S * sigma_a[None, :] * sqrt_T
            gamma = pdf_d1 / jnp.maximum(denom, 1e-10)
            return jnp.where(jnp.isfinite(gamma), gamma, 0.0)

        S_g = jnp.asarray(S_grid, dtype=jnp.float64)
        K_a = jnp.asarray(K, dtype=jnp.float64)
        sigma_a = jnp.asarray(
            sigma if hasattr(sigma, '__len__') else [float(sigma)] * len(K),
            dtype=jnp.float64,
        )
        T_a = jnp.asarray(
            T if hasattr(T, '__len__') else [float(T)] * len(K),
            dtype=jnp.float64,
        )
        return jnp.asarray(compute(S_g, K_a, sigma_a, T_a, self.r))

    # ── Numba 后端 ──
    def _gamma_2d_numba(self, S_grid, K, sigma, T):
        """Numba CPU 并行 (基于 NumPy 数组)"""
        from numba import njit, prange

        @njit(parallel=True, fastmath=True, cache=True)
        def compute_gamma_inner(S_arr, K_arr, sigma_arr, T_arr, r):
            n_p = len(S_arr)
            n_s = len(K_arr)
            out = np.zeros((n_p, n_s))
            sqrt_2pi = np.sqrt(2 * np.pi)
            for i in prange(n_p):
                for j in range(n_s):
                    S = S_arr[i]
                    K_v = K_arr[j]
                    sig = sigma_arr[j] if j < len(sigma_arr) else sigma_arr[0]
                    T_v = T_arr[j] if j < len(T_arr) else T_arr[0]
                    if sig > 0 and T_v > 0 and S > 0 and K_v > 0:
                        d1 = (np.log(S / K_v) + (r + 0.5 * sig ** 2) * T_v) / (sig * np.sqrt(T_v))
                        if d1 < 50 and d1 > -50:
                            pdf = np.exp(-0.5 * d1 ** 2) / sqrt_2pi
                            out[i, j] = pdf / (S * sig * np.sqrt(T_v))
            return out

        S_arr = np.asarray(S_grid, dtype=np.float64)
        K_arr = np.asarray(K, dtype=np.float64)
        sigma_arr = np.asarray(
            sigma if hasattr(sigma, '__len__') else np.full(len(K), float(sigma)),
            dtype=np.float64,
        )
        T_arr = np.asarray(
            T if hasattr(T, '__len__') else np.full(len(K), float(T)),
            dtype=np.float64,
        )
        return compute_gamma_inner(S_arr, K_arr, sigma_arr, T_arr, self.r)

    # ────────────── 性能基准 ──────────────

    def benchmark(
        self,
        n_prices: int = 500,
        n_strikes: int = 1000,
        n_iterations: int = 3,
    ) -> Dict[str, float]:
        """性能基准测试: 对比各后端的 2D Gamma 计算耗时

        Returns:
            {backend: avg_milliseconds}
        """
        results: Dict[str, float] = {}
        S_grid = np.linspace(90, 110, n_prices)
        K = np.linspace(80, 120, n_strikes)
        sigma = np.full(n_strikes, 0.25)
        T = np.full(n_strikes, 0.1)

        # 测试当前后端
        times = []
        for _ in range(n_iterations):
            t0 = time.perf_counter()
            self._gamma_2d(S_grid, K, sigma, T)
            times.append((time.perf_counter() - t0) * 1000)
        results[self.backend] = float(np.mean(times))
        logger.info(
            f"基准测试 ({n_prices}×{n_strikes}, 重复 {n_iterations} 次): "
            f"{self.backend} = {results[self.backend]:.2f}ms"
        )

        # 强制对比 NumPy (基线)
        if self.backend != 'numpy':
            np_times = []
            for _ in range(n_iterations):
                t0 = time.perf_counter()
                self._gamma_2d_numpy(S_grid, K, sigma, T)
                np_times.append((time.perf_counter() - t0) * 1000)
            results['numpy_baseline'] = float(np.mean(np_times))
            speedup = results['numpy_baseline'] / results[self.backend] if results[self.backend] > 0 else 0
            logger.info(
                f"加速比: {speedup:.2f}x (基线 NumPy: {results['numpy_baseline']:.2f}ms)"
            )

        return results


# ── 便捷函数 ──

def get_engine(prefer_gpu: bool = True) -> FastVollibEngine:
    """获取全局引擎实例 (单例)"""
    global _ENGINE_SINGLETON
    if '_ENGINE_SINGLETON' not in globals():
        _ENGINE_SINGLETON = FastVollibEngine(prefer_gpu=prefer_gpu)
    return _ENGINE_SINGLETON


def get_backend_info() -> Dict[str, Any]:
    """获取后端状态信息"""
    return BACKEND_STATUS.copy()


# 公开的初始化
_ENGINE_SINGLETON: Optional[FastVollibEngine] = None
