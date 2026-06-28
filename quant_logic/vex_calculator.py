"""
V2.5 P5: Vanna Exposure (VEX) 敞口计算器

理论基础:
    Vanna = ∂Delta/∂σ = ∂²Price/∂S∂σ = -n(d1) * d2 / σ

    在 Sticky Strike 假设下, 隐含波动率随价格变化:
        ∂σ/∂S = ρ * σ / S  (其中 ρ 为相关系数, 取 SVI 拟合的 rho)

    美元对冲压力转换:
        VEX = OI × Spot × 100 × Vanna × 0.01 × IV
        = 当价格移动 1% 时的对冲金额 (与 GEX 同一量纲)

    Sticky Delta 假设:
        Δ随σ变化, 需对 VEX 加权 ρ 调整
        VEX_delta_adj = VEX × ρ

应用:
    - 0DTE 尾盘: Vanna 主导, 1% 价格变化 → 数百万美元对冲
    - 波动率暴涨: VEX 放大, 做市商被迫 delta-hedge
    - 与 GEX 相加: 获得完整的价格+波动率二维对冲压力

量纲一致性 (P5 关键):
    GEX = γ × OI × S² × 100
    VEX = Vanna × OI × S × 100 × 0.01 × IV = Vanna × OI × S × IV
    → GEX 和 VEX 均为 "价格波动 1% 的美元对冲压力", 可直接相加
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Any
from utils.logger import getLogger
from config.settings import Config

logger = getLogger('vex_calculator')


class VEXCalculator:
    """Vanna Exposure (VEX) 计算器 (V2.5 P5)

    Examples:
        >>> calc = VEXCalculator()
        >>> vex_df = calc.calculate_vex(option_chain_df, spot=5500)
        >>> # 输出含 vex_call/vex_put/net_vex 列
    """

    # 合约乘数 (与 GEX 一致)
    CONTRACT_MULTIPLIER = 100

    def __init__(self, risk_free_rate: float = 0.05):
        self.r = risk_free_rate

    def calculate_vex(
        self,
        option_chain_df: pd.DataFrame,
        spot: float,
        sticky_delta: bool = False,
        default_correlation: float = -0.7,
    ) -> pd.DataFrame:
        """计算 VEX 敞口

        Args:
            option_chain_df: 期权链 DataFrame
                必含: strike, type, days_to_expiry, open_interest, implied_volatility
                可选: bid, ask (用于 mid_price 估算)
            spot: 标的价格
            sticky_delta: 是否应用 Sticky Delta 调整
            default_correlation: 默认 ρ (无 SVI 拟合时使用, 通常 -0.7)
        Returns:
            新增列的 DataFrame:
                - vanna: 单合约 Vanna
                - vex: VEX 敞口 (美元)
                - vex_sticky: Sticky Strike/Delta 调整后 VEX
        """
        if option_chain_df.empty:
            return option_chain_df

        df = option_chain_df.copy()

        # 准备参数
        strikes = df['strike'].to_numpy(dtype=float)
        vols = df.get('implied_volatility', pd.Series(0.2, index=df.index)).to_numpy(dtype=float)
        T = (df.get('days_to_expiry', pd.Series(30, index=df.index)) / 365.0).to_numpy(dtype=float)
        oi = df['open_interest'].to_numpy(dtype=float)
        types = df['type'].to_numpy()

        # Vanna = -n(d1) * d2 / σ
        d1 = (
            np.log(spot / strikes)
            + (self.r + 0.5 * vols ** 2) * T
        ) / (vols * np.sqrt(np.maximum(T, 1e-10)))
        d1 = np.clip(d1, -50, 50)
        d2 = d1 - vols * np.sqrt(np.maximum(T, 1e-10))

        # n(d1) 标准正态 PDF
        pdf_d1 = np.exp(-0.5 * d1 ** 2) / np.sqrt(2 * np.pi)
        vanna = -pdf_d1 * d2 / np.maximum(vols, 1e-10)
        vanna = np.where(np.isfinite(vanna), vanna, 0.0)

        df['vanna'] = vanna

        # VEX = OI × Spot × Vanna × 0.01 × IV (1% 价格变化的对冲金额)
        vex = oi * spot * self.CONTRACT_MULTIPLIER * vanna * 0.01 * vols
        vex = np.where(np.isfinite(vex), vex, 0.0)
        df['vex'] = vex

        # Sticky Delta 调整: ∂σ/∂S = ρ * σ / S
        # VEX_sticky = VEX × ρ  (反映波动率联动)
        if sticky_delta:
            # 尝试使用 SVI 拟合的 rho, 否则用默认
            rho_col = df.get('svi_rho')
            if rho_col is not None:
                rho = rho_col.to_numpy(dtype=float)
            else:
                rho = np.full(len(df), default_correlation)
            df['vex_sticky'] = vex * rho
        else:
            df['vex_sticky'] = vex

        # Call / Put 分离 (便于后续 GEX 通道对齐)
        is_call = np.array([str(t).upper().startswith('C') for t in types])
        df['vex_call'] = np.where(is_call, df['vex'], 0.0)
        df['vex_put'] = np.where(~is_call, df['vex'], 0.0)

        logger.info(
            f"[VEX] Call=${df['vex_call'].sum()/1e9:.2f}B, "
            f"Put=${df['vex_put'].sum()/1e9:.2f}B, "
            f"Net=${df['vex'].sum()/1e9:.2f}B"
        )

        return df

    def calculate_aggregate_vex(
        self,
        option_chain_df: pd.DataFrame,
        spot: float,
    ) -> Dict[str, float]:
        """聚合 VEX 敞口 (单值)

        Returns:
            {call_vex, put_vex, net_vex, total_vex, dominant_vex}
        """
        df = self.calculate_vex(option_chain_df, spot)
        if df.empty:
            return {
                'call_vex': 0.0, 'put_vex': 0.0, 'net_vex': 0.0,
                'total_vex': 0.0, 'dominant_vex': 'neutral',
            }

        call_vex = float(df['vex_call'].sum())
        put_vex = float(df['vex_put'].sum())
        net_vex = call_vex - put_vex
        total_vex = call_vex + abs(put_vex)

        # 判断主导方向
        if abs(call_vex) > abs(put_vex) * 1.2:
            dominant = 'call_dominant'
        elif abs(put_vex) > abs(call_vex) * 1.2:
            dominant = 'put_dominant'
        else:
            dominant = 'neutral'

        return {
            'call_vex': call_vex,
            'put_vex': put_vex,
            'net_vex': net_vex,
            'total_vex': total_vex,
            'dominant_vex': dominant,
        }


def compute_vex_batch(
    option_chain_df: pd.DataFrame,
    spot: float,
    risk_free_rate: float = 0.05,
) -> pd.DataFrame:
    """便捷函数: 批量计算 VEX"""
    calc = VEXCalculator(risk_free_rate=risk_free_rate)
    return calc.calculate_vex(option_chain_df, spot)


# ── Charm (CHEX) 单独模块 (P5.2) ──
class CharmCalculator:
    """Charm Exposure (CHEX) 计算器

    Charm = ∂Delta/∂t = n(d1) × (2rT - d2*σ√T) / (2T*σ√T)  (每日衰减)

    物理意义: 时间每流逝 1 天, Delta 衰减多少 → 对冲金额
    """

    CONTRACT_MULTIPLIER = 100

    def __init__(self, risk_free_rate: float = 0.05):
        self.r = risk_free_rate

    def calculate_chex(
        self,
        option_chain_df: pd.DataFrame,
        spot: float,
    ) -> pd.DataFrame:
        """计算 CHEX 敞口

        Args:
            option_chain_df: 期权链 DataFrame
                必含: strike, type, days_to_expiry, open_interest, implied_volatility
            spot: 标的价格
        Returns:
            新增列: charm, chex, chex_call, chex_put
        """
        if option_chain_df.empty:
            return option_chain_df

        df = option_chain_df.copy()
        strikes = df['strike'].to_numpy(dtype=float)
        vols = df.get('implied_volatility', pd.Series(0.2, index=df.index)).to_numpy(dtype=float)
        T = (df.get('days_to_expiry', pd.Series(30, index=df.index)) / 365.0).to_numpy(dtype=float)
        oi = df['open_interest'].to_numpy(dtype=float)
        types = df['type'].to_numpy()

        # Charm 公式
        d1 = (
            np.log(spot / strikes)
            + (self.r + 0.5 * vols ** 2) * T
        ) / (vols * np.sqrt(np.maximum(T, 1e-10)))
        d1 = np.clip(d1, -50, 50)
        d2 = d1 - vols * np.sqrt(np.maximum(T, 1e-10))
        pdf_d1 = np.exp(-0.5 * d1 ** 2) / np.sqrt(2 * np.pi)

        # Charm 每日衰减 (除以 365)
        T_safe = np.maximum(T, 1e-10)
        sqrt_T = np.sqrt(T_safe)
        sigma_sqrt_T = np.maximum(vols * sqrt_T, 1e-10)

        charm_num = pdf_d1 * (2.0 * self.r * T_safe - d2 * sigma_sqrt_T)
        charm_denom = 2.0 * T_safe * sigma_sqrt_T
        charm_denom_safe = np.maximum(np.abs(charm_denom), 1e-10)
        charm = (charm_num / charm_denom_safe) / 365.0
        charm = np.where(np.isfinite(charm), charm, 0.0)

        df['charm'] = charm

        # CHEX = OI × Spot × 100 × Charm
        # 每日对冲金额变化
        chex = oi * spot * self.CONTRACT_MULTIPLIER * charm
        chex = np.where(np.isfinite(chex), chex, 0.0)
        df['chex'] = chex

        is_call = np.array([str(t).upper().startswith('C') for t in types])
        df['chex_call'] = np.where(is_call, df['chex'], 0.0)
        df['chex_put'] = np.where(~is_call, df['chex'], 0.0)

        logger.info(
            f"[CHEX] Call=${df['chex_call'].sum()/1e9:.2f}B, "
            f"Put=${df['chex_put'].sum()/1e9:.2f}B, "
            f"Net=${df['chex'].sum()/1e9:.2f}B (每日)"
        )

        return df


def compute_chex_batch(
    option_chain_df: pd.DataFrame,
    spot: float,
    risk_free_rate: float = 0.05,
) -> pd.DataFrame:
    """便捷函数: 批量计算 CHEX"""
    calc = CharmCalculator(risk_free_rate=risk_free_rate)
    return calc.calculate_chex(option_chain_df, spot)


# ── 多通道张量构建 (P5.4) ──
class MultiChannelTensorBuilder:
    """GEX + VEX + CHEX 多通道张量构建器

    输出形状: (n_strikes, n_expiries, 3) — 第三维为 [GEX, VEX, CHEX]

    Examples:
        >>> builder = MultiChannelTensorBuilder()
        >>> tensor, metadata = builder.build(option_chain_df, spot=5500)
        >>> # tensor shape: (60, 4, 3)  -- 60 strikes, 4 expiries, 3 channels
    """

    def __init__(self, risk_free_rate: float = 0.05):
        self.r = risk_free_rate
        self.gex_calc = None
        self.vex_calc = VEXCalculator(risk_free_rate=risk_free_rate)
        self.chex_calc = CharmCalculator(risk_free_rate=risk_free_rate)

    def build(
        self,
        option_chain_df: pd.DataFrame,
        spot: float,
        use_svi_smoothed_iv: bool = False,
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """构建 3 通道张量

        Args:
            option_chain_df: 期权链
            spot: 标的价格
            use_svi_smoothed_iv: 是否使用 SVI 平滑 IV
        Returns:
            (tensor, metadata)
              tensor: shape (n_strikes, n_expiries, 3) float64
              metadata: {strikes, expiries, channels, total_gex, total_vex, total_chex}
        """
        if option_chain_df.empty:
            return np.zeros((0, 0, 3), dtype=np.float64), {
                'strikes': [], 'expiries': [],
                'channels': ['GEX', 'VEX', 'CHEX'],
                'total_gex': 0, 'total_vex': 0, 'total_chex': 0,
            }

        df = option_chain_df.copy()

        # ── 计算 GEX ──
        # 使用 bs_engine (向量化)
        try:
            from quant_logic.bs_engine import VectorizedBSEngine
            engine = VectorizedBSEngine(risk_free_rate=self.r)
            strikes = df['strike'].to_numpy(dtype=float)
            vols = df.get(
                'smoothed_iv' if use_svi_smoothed_iv and 'smoothed_iv' in df.columns
                else 'implied_volatility',
                pd.Series(0.2, index=df.index),
            ).to_numpy(dtype=float)
            T = (df.get('days_to_expiry', pd.Series(30, index=df.index)) / 365.0).to_numpy(dtype=float)
            oi = df['open_interest'].to_numpy(dtype=float)
            option_types = df['type'].to_numpy()

            greeks = engine.compute_all_greeks(
                S=np.array([spot]), K=strikes, sigma=vols, T=T,
                option_types=option_types,
            )
            gex_values = (
                greeks.gamma * oi * spot ** 2
                * (1.0 if 'C' in str(option_types[0]).upper() else -1.0)
            )  # 简化: 同号处理
            # 修正: 标量版 GEX
            gex_values = greeks.gamma * 100 * oi * spot ** 2
            df['gex'] = np.where(
                np.array([str(t).upper().startswith('C') for t in option_types]),
                gex_values, -gex_values,
            )
        except Exception as e:
            logger.warning(f"GEX 计算失败, 置 0: {e}")
            df['gex'] = 0.0

        # ── 计算 VEX ──
        df = self.vex_calc.calculate_vex(df, spot)

        # ── 计算 CHEX ──
        df = self.chex_calc.calculate_chex(df, spot)

        # ── 构造张量 ──
        unique_strikes = np.sort(df['strike'].unique())
        unique_expiries = np.sort(df.get('expiry', df.get('days_to_expiry', pd.Series([30]))).unique())

        # 如果没有 expiry 列, 用 days_to_expiry 作为 proxy
        if 'expiry' not in df.columns:
            unique_expiries = np.sort(df['days_to_expiry'].unique())
            expiry_col = 'days_to_expiry'
        else:
            expiry_col = 'expiry'

        n_strikes = len(unique_strikes)
        n_expiries = len(unique_expiries)
        tensor = np.zeros((n_strikes, n_expiries, 3), dtype=np.float64)

        strike_to_idx = {s: i for i, s in enumerate(unique_strikes)}
        expiry_to_idx = {e: i for i, e in enumerate(unique_expiries)}

        for _, row in df.iterrows():
            s_idx = strike_to_idx.get(row['strike'])
            e_idx = expiry_to_idx.get(row[expiry_col])
            if s_idx is None or e_idx is None:
                continue
            tensor[s_idx, e_idx, 0] += row.get('gex', 0.0)
            tensor[s_idx, e_idx, 1] += row.get('vex', 0.0)
            tensor[s_idx, e_idx, 2] += row.get('chex', 0.0)

        metadata = {
            'strikes': unique_strikes.tolist(),
            'expiries': unique_expiries.tolist(),
            'channels': ['GEX', 'VEX', 'CHEX'],
            'total_gex': float(tensor[:, :, 0].sum()),
            'total_vex': float(tensor[:, :, 1].sum()),
            'total_chex': float(tensor[:, :, 2].sum()),
            'shape': list(tensor.shape),
        }

        logger.info(
            f"[多通道张量] 形状 {tensor.shape}, "
            f"总 GEX=${metadata['total_gex']/1e9:.2f}B, "
            f"总 VEX=${metadata['total_vex']/1e9:.2f}B, "
            f"总 CHEX=${metadata['total_chex']/1e9:.2f}B"
        )

        return tensor, metadata
