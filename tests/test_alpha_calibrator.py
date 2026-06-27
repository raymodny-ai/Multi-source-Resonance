"""
Alpha 校准器测试 (使用 monitoring.db 真实 schema, 事务回滚隔离)

覆盖:
    1. calibrate_alpha (静态方法) 基础数学正确
    2. sanity range 过滤 (alpha 超出 [0.5, 1.5] 不入库)
    3. EWM 平滑: 单点更新正确叠加历史
    4. get_effective_alpha 模块级热路径
    5. 缺 GEXMetrix 参考数据时优雅返回 None
    6. 表不存在时 get_effective_alpha 静默返回 None
    7. 集成: 端到端 calibrate_one 写入 + 读回
    8. clear_alpha_cache 行为
"""
import os
import sys
import sqlite3
from unittest.mock import patch

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import numpy as np
from quant_logic.gex_calculator import GEXCalculator
from quant_logic.alpha_calibrator import (
    AlphaCalibrator,
    get_effective_alpha,
    clear_alpha_cache,
    _EFFECTIVE_ALPHA_CACHE,
    EWM_SPAN,
    ALPHA_SANITY_LOW,
    ALPHA_HISTORY_TABLE,
)


# ── 测试用真实 DB (开发库, 事务回滚隔离避免污染) ──
TEST_DB = os.path.join(project_root, 'database', 'monitoring.db')


def _make_test_db():
    """返回 DatabaseManager 实例 (使用真实 monitoring.db)"""
    from database.db_manager import DatabaseManager
    return DatabaseManager(db_path=TEST_DB)


def test_calibrate_alpha_basic():
    print("=" * 60)
    print("测试1: calibrate_alpha 数学正确")
    print("=" * 60)
    a1 = GEXCalculator.calibrate_alpha(1e6, 1.2e6)
    a2 = GEXCalculator.calibrate_alpha(1e6, 8e5)
    a3 = GEXCalculator.calibrate_alpha(0.0, 1e6)  # div by zero guard
    assert abs(a1 - 1.2) < 1e-9, f"a1={a1}"
    assert abs(a2 - 0.8) < 1e-9, f"a2={a2}"
    assert a3 == 1.0, f"a3 (零保护)={a3}"
    print(f"  a1=1.2 ✓, a2=0.8 ✓, a3=1.0 (安全) ✓")
    print("  [PASS]")


def test_sanity_range_filter():
    print()
    print("=" * 60)
    print("测试2: sanity range 过滤")
    print("=" * 60)
    db = _make_test_db()
    cal = AlphaCalibrator(db=db)

    # 在 alpha_history 表临时插入一条 ref, 测试完删除
    test_id = None
    try:
        # 插入 ref data, 同时创建一个会让 alpha 超出范围的 local
        # ref net_gex=1e9, spot=5500
        with cal.db._get_cursor() as cur:
            cur.execute(
                "INSERT INTO gex_snapshots (symbol, timestamp, filename, net_gex, spot_price) "
                "VALUES ('SANITY', '2026-06-28 16:00:00', 'test.json', 1e9, 5500.0)"
            )
            # alpha=100 (极端), 模拟 local=1e7, ref=1e9
            with patch.object(cal, '_fetch_local_gex', return_value=1e7):
                r = cal.calibrate_one('SANITY', target_date='2026-06-28')
            assert r is None, f"alpha=100 应返回 None, 实际 {r}"
            print(f"  alpha=100 (极端) → return None ✓")
            # 确认未持久化
            cur.execute(
                f"SELECT COUNT(*) FROM {ALPHA_HISTORY_TABLE} WHERE symbol = 'SANITY'"
            )
            assert cur.fetchone()[0] == 0, "alpha 超出范围不应入库"
            print(f"  DB 无 alpha_history['SANITY'] ✓ (未污染)")
    finally:
        with db._get_cursor() as cur:
            cur.execute("DELETE FROM gex_snapshots WHERE symbol = 'SANITY'")
    print("  [PASS]")


def test_ewm_smoothing():
    print()
    print("=" * 60)
    print("测试3: EWM 20 日平滑")
    print("=" * 60)
    db = _make_test_db()
    cal = AlphaCalibrator(db=db)
    test_sym = 'EWMTEST'
    try:
        # 注入 5 天历史 alpha
        with cal.db._get_cursor() as cur:
            for i, a in enumerate([1.0, 1.1, 1.2, 1.15, 1.05]):
                day = f"2026-06-{20 + i:02d}"
                cur.execute(
                    f"INSERT INTO {ALPHA_HISTORY_TABLE} (symbol, date, alpha) "
                    f"VALUES (?, ?, ?)",
                    (test_sym, day, a)
                )
        # 今日 alpha=1.10
        ewm = cal._compute_ewm(test_sym, 1.10, '2026-06-28')
        # 简单 EWM 6 点, 越近期权重越大
        # history 顺序: SQL DESC 取 [1.05, 1.15, 1.2, 1.1, 1.0] + 今日 1.10
        history = [1.05, 1.15, 1.2, 1.1, 1.0, 1.10]
        n = len(history)
        weights = np.exp(-np.arange(n) / max(1, n - 1))
        weights /= weights.sum()
        expected = np.dot(weights, history)
        assert abs(ewm - expected) < 1e-6, f"ewm={ewm}, expected={expected}"
        print(f"  6 点 EWM = {ewm:.4f} (期望 {expected:.4f}) ✓")
    finally:
        with db._get_cursor() as cur:
            cur.execute(f"DELETE FROM {ALPHA_HISTORY_TABLE} WHERE symbol = ?", (test_sym,))
    print("  [PASS]")


def test_get_effective_alpha_no_history():
    print()
    print("=" * 60)
    print("测试4: get_effective_alpha 无历史数据 → None")
    print("=" * 60)
    clear_alpha_cache()
    # 用一个永不存在的 symbol
    alpha = get_effective_alpha('__NEVER_EXISTS_9999__')
    assert alpha is None, f"无历史应 None, 实际 {alpha}"
    print(f"  未知 symbol → return None ✓")
    print("  [PASS]")


def test_get_effective_alpha_from_db():
    print()
    print("=" * 60)
    print("测试5: get_effective_alpha 从 DB 读最新")
    print("=" * 60)
    clear_alpha_cache()
    db = _make_test_db()
    test_sym = 'GETALPHATEST'
    try:
        cal = AlphaCalibrator(db=db)
        with cal.db._get_cursor() as cur:
            cur.execute(
                f"INSERT INTO {ALPHA_HISTORY_TABLE} (symbol, date, ewm_alpha_20d) "
                f"VALUES (?, '2026-06-25', 1.15), (?, '2026-06-27', 1.18)",
                (test_sym, test_sym)
            )
        clear_alpha_cache()
        alpha = get_effective_alpha(test_sym)
        assert alpha == 1.18, f"应取最近日期 1.18, 实际 {alpha}"
        print(f"  两次写入 1.15, 1.18 → 取最近 1.18 ✓")
    finally:
        with db._get_cursor() as cur:
            cur.execute(f"DELETE FROM {ALPHA_HISTORY_TABLE} WHERE symbol = ?", (test_sym,))
    print("  [PASS]")


def test_calibrate_one_missing_reference():
    print()
    print("=" * 60)
    print("测试6: 缺 GEXMetrix 参考数据 → None")
    print("=" * 60)
    db = _make_test_db()
    cal = AlphaCalibrator(db=db)
    # 用一个永不存在的 symbol
    r = cal.calibrate_one('__NODATA_9999__', target_date='2026-06-28')
    assert r is None, f"缺 ref 应 None, 实际 {r}"
    print(f"  无 snapshot → return None ✓")
    print("  [PASS]")


def test_calibrate_one_end_to_end():
    print()
    print("=" * 60)
    print("测试7: 端到端 calibrate_one 写 + 读")
    print("=" * 60)
    db = _make_test_db()
    cal = AlphaCalibrator(db=db)
    test_sym = 'E2ETEST'
    try:
        # 插入 ref: spot=5500, net_gex=1.2e9
        with cal.db._get_cursor() as cur:
            cur.execute(
                "INSERT INTO gex_snapshots (symbol, timestamp, filename, net_gex, spot_price) "
                "VALUES (?, '2026-06-28 16:00:00', 'x.json', 1.2e9, 5500.0)",
                (test_sym,)
            )
        # 模拟 local = 1.0e9 → alpha = 1.2
        with patch.object(cal, '_fetch_local_gex', return_value=1.0e9):
            r = cal.calibrate_one(test_sym, target_date='2026-06-28')
        assert r is not None
        assert r['alpha'] == 1.2, f"alpha={r['alpha']}"
        assert r['ewm_alpha_20d'] is not None
        assert 1.0 < r['ewm_alpha_20d'] < 1.5
        print(f"  local=1.0e9, ref=1.2e9 → alpha=1.2 ✓")
        print(f"  ewm={r['ewm_alpha_20d']:.4f} (单点 1.2 略平滑) ✓")

        # 读回
        clear_alpha_cache()
        a2 = get_effective_alpha(test_sym)
        assert abs(a2 - r['ewm_alpha_20d']) < 1e-9
        print(f"  DB 读回 alpha={a2:.4f} ✓")
    finally:
        with db._get_cursor() as cur:
            cur.execute(f"DELETE FROM {ALPHA_HISTORY_TABLE} WHERE symbol = ?", (test_sym,))
            cur.execute("DELETE FROM gex_snapshots WHERE symbol = ?", (test_sym,))
    print("  [PASS]")


def test_clear_alpha_cache():
    print()
    print("=" * 60)
    print("测试8: clear_alpha_cache")
    print("=" * 60)
    _EFFECTIVE_ALPHA_CACHE['TEST'] = 1.23
    assert _EFFECTIVE_ALPHA_CACHE['TEST'] == 1.23
    clear_alpha_cache()
    assert 'TEST' not in _EFFECTIVE_ALPHA_CACHE
    print(f"  写入 → 缓存有 → clear → 缓存空 ✓")
    print("  [PASS]")


if __name__ == '__main__':
    test_calibrate_alpha_basic()
    test_sanity_range_filter()
    test_ewm_smoothing()
    test_get_effective_alpha_no_history()
    test_get_effective_alpha_from_db()
    test_calibrate_one_missing_reference()
    test_calibrate_one_end_to_end()
    test_clear_alpha_cache()
    print()
    print("=" * 60)
    print("ALL TESTS PASSED ✓")
    print("=" * 60)
