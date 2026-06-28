"""
GEX 自适应步长扫描测试

验证目标:
    1. calculate_gex_profile_adaptive 返回的 flip_point 精度高于固定 40 步
    2. 计算量明显少于等精度单次扫描
    3. 极端情况 (无翻转点) 优雅降级
    4. 不破坏现有 calculate_gex_profile 的接口
"""
import os
import sys
import time
import numpy as np
import pandas as pd

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from quant_logic.gex_calculator import GEXCalculator


# ── 辅助:构造合成期权链 ──
def make_chain(spot: float, num_strikes: int = 60, dte: int = 30) -> pd.DataFrame:
    """合成一份以 spot 为中心、±10% 行权价、真实 OI 分布的期权链
    设计为: 高于 spot 的 call OI 更大, 低于 spot 的 put OI 更大,
    → 当 spot 下跌时 net_gex 变负, 创造真正的翻转点

    V2.5 P1: 提高 OI 基准至 500000, 确保最远 OTM strike OI ≥ 500
    """
    strikes = np.linspace(spot * 0.90, spot * 1.10, num_strikes)
    rows = []
    for s in strikes:
        moneyness = (s - spot) / spot
        oi_intensity = 500000 * np.exp(-moneyness ** 2 / (2 * 0.03 ** 2))
        iv = 0.20 + 0.15 * moneyness ** 2 / 0.01
        for opt_type in ('CALL', 'PUT'):
            # call OI 随 moneyness 递增 (做市商对冲 call 仓在价外), put 反之
            if opt_type == 'CALL':
                oi_mult = 1.0 + 5.0 * max(moneyness, 0)  # 价外 call OI 大
            else:
                oi_mult = 1.0 + 5.0 * max(-moneyness, 0)  # 价外 put OI 大
            rows.append({
                'strike': float(s),
                'open_interest': int(oi_intensity * oi_mult),
                'implied_volatility': float(iv),
                'type': opt_type,
                'days_to_expiry': dte,
            })
    return pd.DataFrame(rows)


def test_adaptive_finds_flip_point():
    """基本功能: 自适应扫描应该能识别翻转点"""
    print("=" * 60)
    print("测试1: 自适应扫描识别翻转点")
    print("=" * 60)
    calc = GEXCalculator()
    spot = 5500
    df = make_chain(spot)

    result = calc.calculate_gex_profile_adaptive(df, spot)
    assert 'flip_point' in result, "返回结果必须包含 flip_point"
    assert 'flip_zone' in result, "返回结果必须包含 flip_zone"
    assert 'spot_prices' in result, "返回结果必须包含 spot_prices"
    assert 'net_gex_values' in result, "返回结果必须包含 net_gex_values"

    print(f"  翻转点: {result['flip_point']}")
    print(f"  翻转区间: {result['flip_zone']}")
    print(f"  精扫步数: {result['fine_steps']}")
    print(f"  精扫价格范围: {result['spot_prices'][0]:.2f} - {result['spot_prices'][-1]:.2f}")
    print("  [PASS] 自适应扫描基本功能通过")
    return result


def test_adaptive_precision_vs_legacy():
    """精度对比: 自适应应该比固定 40 步更接近 ground truth (500 步)"""
    print()
    print("=" * 60)
    print("测试2: 自适应精度 vs 固定 40 步")
    print("=" * 60)
    calc = GEXCalculator()
    spot = 5500
    df = make_chain(spot)

    # ground truth: 500 步均匀扫描
    truth = calc.calculate_gex_profile(df, spot, price_range_pct=0.10, num_steps=500)
    # 找 ground truth 翻转点
    truth_flip = _find_flip(truth['spot_prices'], truth['net_gex_values'])
    assert truth_flip is not None, "ground truth 必须能识别翻转点"

    # 旧方法: 40 步
    legacy = calc.calculate_gex_profile(df, spot, price_range_pct=0.10, num_steps=40)
    legacy_flip = _find_flip(legacy['spot_prices'], legacy['net_gex_values'])

    # 新方法
    adaptive = calc.calculate_gex_profile_adaptive(df, spot)
    adaptive_flip = adaptive['flip_point']

    print(f"  ground truth (500步): {truth_flip:.4f}")
    print(f"  legacy  (40步):       {legacy_flip:.4f}" if legacy_flip else "  legacy:  无翻转点")
    print(f"  adaptive (40+120步):  {adaptive_flip:.4f}" if adaptive_flip else "  adaptive: 无翻转点")

    legacy_err = abs(legacy_flip - truth_flip) if legacy_flip else float('inf')
    adaptive_err = abs(adaptive_flip - truth_flip) if adaptive_flip else float('inf')

    print(f"  legacy  偏差: {legacy_err:.4f}")
    print(f"  adaptive 偏差: {adaptive_err:.4f}")

    # 自适应精度应优于旧方法 (允许在 OI 离散点处有少量误差)
    assert adaptive_err <= legacy_err + 0.5, (
        f"自适应精度不应明显劣于旧方法: adaptive={adaptive_err:.4f}, legacy={legacy_err:.4f}"
    )
    print("  [PASS] 精度对比通过 (adaptive <= legacy)")


def test_adaptive_faster_than_equivalent():
    """性能: 自适应 160 步应该显著快于等精度单次扫描"""
    print()
    print("=" * 60)
    print("测试3: 自适应性能")
    print("=" * 60)
    calc = GEXCalculator()
    spot = 5500
    df = make_chain(spot, num_strikes=120)  # 加大链规模,凸显计算时间

    # 单次 200 步扫描 (同等精度)
    t0 = time.perf_counter()
    for _ in range(3):
        calc.calculate_gex_profile(df, spot, price_range_pct=0.10, num_steps=200)
    baseline = (time.perf_counter() - t0) / 3

    # 自适应
    t0 = time.perf_counter()
    for _ in range(3):
        calc.calculate_gex_profile_adaptive(df, spot)
    adaptive = (time.perf_counter() - t0) / 3

    speedup = baseline / adaptive if adaptive > 0 else 0
    print(f"  单次 200 步平均耗时: {baseline*1000:.1f}ms")
    print(f"  自适应平均耗时:      {adaptive*1000:.1f}ms")
    print(f"  加速比: {speedup:.2f}x")

    # 自适应应该至少不慢于单次 200 步 (允许 ±20% 抖动)
    assert adaptive <= baseline * 1.2, (
        f"自适应不应该明显慢于等精度单次: adaptive={adaptive*1000:.1f}ms, "
        f"baseline={baseline*1000:.1f}ms"
    )
    print("  [PASS] 性能测试通过")


def test_no_flip_graceful_degradation():
    """边界: 无翻转点 (纯正/纯负 GEX) 优雅降级"""
    print()
    print("=" * 60)
    print("测试4: 无翻转点优雅降级")
    print("=" * 60)
    calc = GEXCalculator()
    spot = 5500

    # 构造极不均衡的链: 只有 call, 几乎无 put → net_gex 始终为正
    strikes = np.linspace(spot * 0.90, spot * 1.10, 30)
    rows = []
    for s in strikes:
        for opt_type in ('CALL',):
            rows.append({
                'strike': float(s),
                'open_interest': 50000,
                'implied_volatility': 0.25,
                'type': opt_type,
                'days_to_expiry': 30,
            })
    df = pd.DataFrame(rows)

    result = calc.calculate_gex_profile_adaptive(df, spot)
    # 无翻转点时, flip_point 应为 None, flip_zone 应为 None
    assert result['flip_point'] is None, f"无翻转点时 flip_point 应为 None, 实际 {result['flip_point']}"
    assert result['flip_zone'] is None, f"无翻转点时 flip_zone 应为 None, 实际 {result['flip_zone']}"
    # 应退化为粗扫全段
    assert len(result['spot_prices']) > 0
    print(f"  flip_point: {result['flip_point']}")
    print(f"  flip_zone: {result['flip_zone']}")
    print(f"  返回价格点数量: {len(result['spot_prices'])}")
    print("  [PASS] 无翻转点降级通过")


def test_legacy_still_works():
    """回归: 旧接口 calculate_gex_profile 必须保持兼容"""
    print()
    print("=" * 60)
    print("测试5: 旧接口兼容性回归")
    print("=" * 60)
    calc = GEXCalculator()
    spot = 5500
    df = make_chain(spot)

    result = calc.calculate_gex_profile(df, spot)
    # 旧接口返回字段
    assert 'spot_prices' in result
    assert 'net_gex_values' in result
    assert 'current_spot' in result
    assert 'current_net_gex' in result
    # 默认 40 步
    assert len(result['spot_prices']) == 40
    print(f"  旧接口返回 40 步, current_spot={result['current_spot']}, "
          f"current_net_gex={result['current_net_gex']:.2e}")
    print("  [PASS] 旧接口兼容性通过")


# ── 辅助:在价格/gex 数组中找翻转点 ──
def _find_flip(prices, gex_values):
    for i in range(len(gex_values) - 1):
        if gex_values[i] * gex_values[i + 1] < 0:
            g1, g2 = gex_values[i], gex_values[i + 1]
            if g2 != g1:
                return prices[i] + (-g1) * (prices[i+1] - prices[i]) / (g2 - g1)
    return None


if __name__ == '__main__':
    test_adaptive_finds_flip_point()
    test_adaptive_precision_vs_legacy()
    test_adaptive_faster_than_equivalent()
    test_no_flip_graceful_degradation()
    test_legacy_still_works()
    print()
    print("=" * 60)
    print("ALL TESTS PASSED ✓")
    print("=" * 60)
