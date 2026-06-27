"""
GEX 数据质量验证器测试

覆盖:
    1. 正常快照 → score=1.0, valid=True
    2. 陈旧快照 (lag > 600s) → 减分
    3. 稀疏行权价 (< 50) → 减分
    4. 零 OI 比例过高 (> 30%) → 减分
    5. 缺失 spot_price → 减分
    6. 缺失 timestamp → 大幅减分
    7. IV 一致性违例 → 减分
    8. 验证失败时 validate_after_fetch 优雅降级
"""
import os
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from quant_logic.gex_data_quality import (
    GEXDataQualityValidator,
    validate_after_fetch,
    STALE_LAG_SECONDS,
    THIN_STRIKES_THRESHOLD,
    HIGH_ZERO_OI_RATIO,
    OI_COVERAGE_THRESHOLD,
    IV_VIOLATION_THRESHOLD,
    MIN_PASS_SCORE,
)


def make_snapshot(
    n_strikes: int = 100,
    spot: float = 5500.0,
    timestamp: str | None = None,
    zero_oi_ratio: float = 0.0,
    iv_violation_ratio: float = 0.0,
    has_iv: bool = True,
) -> dict:
    """合成一个 GEXMetrix 风格的快照"""
    if timestamp is None:
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    else:
        ts = timestamp
    strikes = []
    base_iv = 0.20
    for i in range(n_strikes):
        s = spot * 0.90 + (spot * 0.20) * i / max(1, n_strikes - 1)
        is_zero = (i / max(1, n_strikes)) < zero_oi_ratio
        oi = 0 if is_zero else 10000
        if has_iv and (i / max(1, n_strikes)) < iv_violation_ratio:
            call_iv = base_iv
            put_iv = base_iv + 0.05
        else:
            call_iv = base_iv
            put_iv = base_iv
        strikes.append({
            'strike': s,
            'call_oi': oi,
            'put_oi': oi,
            'call_iv': call_iv,
            'put_iv': put_iv,
        })
    return {
        'data': {
            'timestamp': ts,
            'spot_price': spot,
            'strikes': strikes,
        }
    }


def test_perfect_snapshot_scores_1():
    print("=" * 60)
    print("测试1: 完美快照 → score=1.0")
    print("=" * 60)
    v = GEXDataQualityValidator()
    snap = make_snapshot(n_strikes=120, spot=5500.0)
    result = v.validate_snapshot('SPY', snap)
    print(f"  score={result['score']}, valid={result['valid']}, issues={result['issues']}")
    assert result['valid'] is True
    assert result['score'] >= 0.85, f"完美快照 score 应 >= 0.85, 实际 {result['score']}"
    print("  [PASS]")


def test_stale_snapshot_deducts():
    print()
    print("=" * 60)
    print("测试2: 陈旧快照 (lag > 600s) 减分")
    print("=" * 60)
    v = GEXDataQualityValidator()
    old_ts = (datetime.now(timezone.utc) - timedelta(seconds=1200)).strftime('%Y-%m-%d %H:%M:%S')
    snap = make_snapshot(n_strikes=120, timestamp=old_ts)
    result = v.validate_snapshot('SPY', snap)
    print(f"  lag={result['lag_seconds']}s, score={result['score']}, issues={result['issues']}")
    assert result['lag_seconds'] > STALE_LAG_SECONDS
    assert any('stale' in i for i in result['issues']), "应包含 stale issue"
    assert result['score'] <= 0.85, f"陈旧快照应减分, 实际 {result['score']}"
    print("  [PASS]")


def test_thin_strikes_deduct():
    print()
    print("=" * 60)
    print("测试3: 稀疏行权价 (< 50) 减分")
    print("=" * 60)
    v = GEXDataQualityValidator()
    snap = make_snapshot(n_strikes=30)
    result = v.validate_snapshot('SPY', snap)
    print(f"  density={result['strike_density']}, score={result['score']}, issues={result['issues']}")
    assert result['strike_density'] < THIN_STRIKES_THRESHOLD
    assert any('thin_strikes' in i for i in result['issues'])
    print("  [PASS]")


def test_high_zero_oi_deduct():
    print()
    print("=" * 60)
    print("测试4: 零 OI 比例过高减分")
    print("=" * 60)
    v = GEXDataQualityValidator()
    snap = make_snapshot(n_strikes=100, zero_oi_ratio=0.5)
    result = v.validate_snapshot('SPY', snap)
    print(f"  zero_oi_pct={result['zero_oi_pct']:.1%}, score={result['score']}")
    assert result['zero_oi_pct'] > HIGH_ZERO_OI_RATIO
    assert any('zero_oi' in i for i in result['issues'])
    print("  [PASS]")


def test_missing_spot_deduct():
    print()
    print("=" * 60)
    print("测试5: 缺失 spot_price 减分")
    print("=" * 60)
    v = GEXDataQualityValidator()
    snap = make_snapshot(n_strikes=100)
    del snap['data']['spot_price']
    result = v.validate_snapshot('SPY', snap)
    print(f"  score={result['score']}, issues={result['issues']}")
    assert 'no_spot' in result['issues']
    print("  [PASS]")


def test_missing_timestamp_heavy_deduct():
    print()
    print("=" * 60)
    print("测试6: 缺失 timestamp 大幅减分")
    print("=" * 60)
    v = GEXDataQualityValidator()
    snap = make_snapshot(n_strikes=100, timestamp="")
    result = v.validate_snapshot('SPY', snap)
    print(f"  score={result['score']}, issues={result['issues']}")
    assert 'no_timestamp' in result['issues']
    assert result['lag_seconds'] is None
    assert result['score'] <= 0.7, f"missing timestamp 应 score <= 0.7, 实际 {result['score']}"
    print("  [PASS]")


def test_iv_violations_deduct():
    print()
    print("=" * 60)
    print("测试7: IV 一致性违例减分")
    print("=" * 60)
    v = GEXDataQualityValidator()
    snap = make_snapshot(n_strikes=100, iv_violation_ratio=0.20)
    result = v.validate_snapshot('SPY', snap)
    print(f"  iv_violations={result['iv_violations']}, score={result['score']}, issues={result['issues']}")
    assert result['iv_violations'] > 0
    assert any('iv_violations' in i for i in result['issues'])
    print("  [PASS]")


def test_combo_drops_below_threshold():
    print()
    print("=" * 60)
    print("测试8: 多重问题 → valid=False")
    print("=" * 60)
    v = GEXDataQualityValidator()
    old_ts = (datetime.now(timezone.utc) - timedelta(seconds=1200)).strftime('%Y-%m-%d %H:%M:%S')
    snap = make_snapshot(
        n_strikes=30,
        timestamp=old_ts,
        zero_oi_ratio=0.4,
        iv_violation_ratio=0.10,
    )
    del snap['data']['spot_price']
    result = v.validate_snapshot('SPY', snap)
    print(f"  score={result['score']}, valid={result['valid']}, issues={result['issues']}")
    assert result['valid'] is False, f"多重问题应 invalid, 实际 valid={result['valid']}"
    assert result['score'] < MIN_PASS_SCORE
    print("  [PASS]")


def test_validate_after_fetch_graceful_degradation():
    print()
    print("=" * 60)
    print("测试9: validate_after_fetch 验证器自身异常时优雅降级")
    print("=" * 60)
    with patch.object(GEXDataQualityValidator, 'validate_snapshot', side_effect=RuntimeError("boom")):
        result = validate_after_fetch('SPY', make_snapshot())
    print(f"  score={result['score']}, valid={result['valid']}, issues={result['issues']}")
    assert result['valid'] is True, "validator 异常时应默认放行"
    assert 'validator_error' in result['issues']
    print("  [PASS]")


def test_validate_after_fetch_handles_garbage():
    print()
    print("=" * 60)
    print("测试10: validate_after_fetch 处理垃圾输入")
    print("=" * 60)
    result = validate_after_fetch('SPY', {'foo': 'bar'})
    print(f"  score={result['score']}, valid={result['valid']}, issues={result['issues']}")
    assert isinstance(result, dict)
    assert 'valid' in result
    print("  [PASS]")


if __name__ == '__main__':
    test_perfect_snapshot_scores_1()
    test_stale_snapshot_deducts()
    test_thin_strikes_deduct()
    test_high_zero_oi_deduct()
    test_missing_spot_deduct()
    test_missing_timestamp_heavy_deduct()
    test_iv_violations_deduct()
    test_combo_drops_below_threshold()
    test_validate_after_fetch_graceful_degradation()
    test_validate_after_fetch_handles_garbage()
    print()
    print("=" * 60)
    print("ALL TESTS PASSED ✓")
    print("=" * 60)
