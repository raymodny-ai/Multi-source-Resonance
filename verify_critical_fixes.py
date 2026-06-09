#!/usr/bin/env python3
"""验证Critical Issues修复

该脚本验证所有Critical级别的问题是否已正确修复:
- C1: async/await混用导致TypeError → ThreadPoolExecutor配置
- C2: 数据库路径硬编码 → 从config.settings读取
- C3: Playwright浏览器未初始化 → 自动安装检查
- C4: GEX/VIX除零风险 → 输入验证和NaN检查
- C5: 信号状态机未持久化 → JSON文件持久化
"""

import asyncio
from datetime import datetime
import pytz
import sys


def test_c1_async_executor():
    """C1: 验证ThreadPoolExecutor正确配置"""
    print("测试 C1: async/await线程池配置...")
    
    from main_scheduler import MainScheduler
    from concurrent.futures import ThreadPoolExecutor
    
    scheduler = MainScheduler()
    
    assert hasattr(scheduler, 'executor'), "Missing executor"
    assert hasattr(scheduler, 'db_executor'), "Missing db_executor"
    assert isinstance(scheduler.executor, ThreadPoolExecutor), "executor不是ThreadPoolExecutor"
    assert isinstance(scheduler.db_executor, ThreadPoolExecutor), "db_executor不是ThreadPoolExecutor"
    
    print("[PASS] C1: async/await线程池配置正确")


def test_c2_db_path_from_config():
    """C2: 验证数据库路径从config读取"""
    print("\n测试 C2: 数据库路径从config读取...")
    
    from database.db_manager import DatabaseManager
    from config.settings import Config
    
    db = DatabaseManager()
    
    assert db.db_path == Config.DATABASE_PATH, f"数据库路径不匹配: {db.db_path} != {Config.DATABASE_PATH}"
    
    print("[PASS] C2: 数据库路径从config读取")


def test_c3_playwright_auto_install():
    """C3: 验证Playwright自动安装检查"""
    print("\n测试 C3: Playwright自动安装检查...")
    
    from data_fetchers.stockgrid_fetcher import StockgridFetcher
    
    fetcher = StockgridFetcher()
    
    assert hasattr(fetcher, '_check_and_install_playwright'), "缺少自动安装方法"
    assert hasattr(StockgridFetcher, 'close_all'), "缺少close_all类方法"
    
    print("[PASS] C3: Playwright自动安装检查已添加")


def test_c4_division_by_zero_protection():
    """C4: 验证除零保护"""
    print("\n测试 C4: 除零保护...")
    
    from quant_logic.gex_calculator import GEXCalculator
    from quant_logic.vix_analyzer import VIXAnalyzer
    
    calc = GEXCalculator()
    
    # 测试零到期日
    gamma = calc.calculate_gamma(100, 105, 0.2, 0)
    assert gamma == 0.0, f"零到期日应返回0.0,实际:{gamma}"
    
    # 测试零波动率
    gamma = calc.calculate_gamma(100, 105, 0, 0.5)
    assert gamma == 0.0, f"零波动率应返回0.0,实际:{gamma}"
    
    analyzer = VIXAnalyzer()
    result = analyzer.analyze_term_structure(15.0, 0)
    assert result['state'] == 'ERROR', f"VX2=0应返回ERROR状态,实际:{result['state']}"
    
    print("[PASS] C4: 除零保护正常工作")


def test_c5_signal_state_persistence():
    """C5: 验证信号状态机持久化"""
    print("\n测试 C5: 信号状态机持久化...")
    
    from signal_engine.signal_trigger import SignalStateMachine
    from datetime import datetime
    import pytz
    import json
    from pathlib import Path
    
    est = pytz.timezone('US/Eastern')
    sm = SignalStateMachine(cooldown_minutes=30)
    
    # 模拟触发告警
    resonance_result = {
        'alert_level': 'LEVEL_3',
        'total_score': 4.8,
        'max_score': 5.0
    }
    current_time = datetime.now(est)
    
    result = sm.check_and_trigger(resonance_result, current_time)
    assert result['should_alert'] == True, "首次应触发告警"
    
    # 检查状态文件是否创建
    state_file = Path(sm.STATE_FILE)
    assert state_file.exists(), "状态文件未创建"
    
    # 验证文件内容
    with open(state_file, 'r') as f:
        data = json.load(f)
    
    assert data['last_alert_time'] is not None, "last_alert_time未保存"
    assert data['current_state'] == 'ALERT_TRIGGERED', "状态未保存"
    
    print("[PASS] C5: 信号状态机持久化正常")


def test_thresholds_class():
    """验证Thresholds类创建成功"""
    print("\n测试 Thresholds类...")
    
    from config.settings import Config
    
    # 验证关键常量存在
    assert hasattr(Config.Thresholds, 'GEX_RISK_FREE_RATE'), "缺少GEX_RISK_FREE_RATE"
    assert hasattr(Config.Thresholds, 'VIX_CONTANGO_THRESHOLD'), "缺少VIX_CONTANGO_THRESHOLD"
    assert hasattr(Config.Thresholds, 'FUNDING_RATE_ANOMALY'), "缺少FUNDING_RATE_ANOMALY"
    assert hasattr(Config.Thresholds, 'DIX_SIGNAL_THRESHOLD'), "缺少DIX_SIGNAL_THRESHOLD"
    assert hasattr(Config.Thresholds, 'LEVEL_3_THRESHOLD'), "缺少LEVEL_3_THRESHOLD"
    assert hasattr(Config.Thresholds, 'HAWKES_SUBCRITICAL'), "缺少HAWKES_SUBCRITICAL"
    
    # 验证值正确
    assert Config.Thresholds.GEX_RISK_FREE_RATE == 0.05, "GEX_RISK_FREE_RATE值错误"
    assert Config.Thresholds.VIX_CONTANGO_THRESHOLD == 0.95, "VIX_CONTANGO_THRESHOLD值错误"
    assert Config.Thresholds.LEVEL_3_THRESHOLD == 3.5, "LEVEL_3_THRESHOLD值错误"
    
    print("[PASS] Thresholds类创建成功且值正确")


def test_quant_logic_uses_thresholds():
    """验证quant_logic模块使用Thresholds常量"""
    print("\n测试 quant_logic模块引用Thresholds...")
    
    from quant_logic.gex_calculator import GEXCalculator
    from quant_logic.vix_analyzer import VIXAnalyzer
    from quant_logic.crypto_leverage_cleaner import CryptoLeverageCleaner
    from quant_logic.darkpool_verifier import DarkPoolVerifier
    from config.settings import Config
    
    # 验证GEXCalculator使用Thresholds
    assert GEXCalculator.RISK_FREE_RATE == Config.Thresholds.GEX_RISK_FREE_RATE, \
        "GEXCalculator未使用Config.Thresholds.GEX_RISK_FREE_RATE"
    assert GEXCalculator.CONTRACT_MULTIPLIER == Config.Thresholds.GEX_CONTRACT_MULTIPLIER, \
        "GEXCalculator未使用Config.Thresholds.GEX_CONTRACT_MULTIPLIER"
    
    # 验证VIXAnalyzer使用Thresholds
    assert VIXAnalyzer.CONTANGO_THRESHOLD == Config.Thresholds.VIX_CONTANGO_THRESHOLD, \
        "VIXAnalyzer未使用Config.Thresholds.VIX_CONTANGO_THRESHOLD"
    
    # 验证CryptoLeverageCleaner使用Thresholds
    assert CryptoLeverageCleaner.FUNDING_RATE_THRESHOLD == Config.Thresholds.FUNDING_RATE_ANOMALY, \
        "CryptoLeverageCleaner未使用Config.Thresholds.FUNDING_RATE_ANOMALY"
    
    # 验证DarkPoolVerifier使用Thresholds
    assert DarkPoolVerifier.DIX_THRESHOLD == Config.Thresholds.DIX_SIGNAL_THRESHOLD, \
        "DarkPoolVerifier未使用Config.Thresholds.DIX_SIGNAL_THRESHOLD"
    
    print("[PASS] quant_logic模块正确引用Thresholds常量")


def test_signal_engine_uses_thresholds():
    """验证signal_engine模块使用Thresholds常量"""
    print("\n测试 signal_engine模块引用Thresholds...")
    
    from signal_engine.resonance_scorer import ResonanceScorer
    from config.settings import Config
    
    scorer = ResonanceScorer()
    
    # 通过反射检查代码中是否使用了Thresholds
    import inspect
    source = inspect.getsource(scorer.calculate_total_score)
    
    assert 'Config.Thresholds.MAX_RESONANCE_SCORE' in source, \
        "calculate_total_score未使用Config.Thresholds.MAX_RESONANCE_SCORE"
    assert 'Config.Thresholds.LEVEL_3_THRESHOLD' in source, \
        "calculate_total_score未使用Config.Thresholds.LEVEL_3_THRESHOLD"
    assert 'Config.Thresholds.LEVEL_2_THRESHOLD' in source, \
        "calculate_total_score未使用Config.Thresholds.LEVEL_2_THRESHOLD"
    assert 'Config.Thresholds.LEVEL_1_THRESHOLD' in source, \
        "calculate_total_score未使用Config.Thresholds.LEVEL_1_THRESHOLD"
    
    print("[PASS] signal_engine模块正确引用Thresholds常量")


if __name__ == "__main__":
    print("=" * 70)
    print("多源共振监控系统 - Critical Issues修复验证")
    print("=" * 70)
    
    try:
        test_c1_async_executor()
        test_c2_db_path_from_config()
        test_c3_playwright_auto_install()
        test_c4_division_by_zero_protection()
        test_c5_signal_state_persistence()
        test_thresholds_class()
        test_quant_logic_uses_thresholds()
        test_signal_engine_uses_thresholds()
        
        print("\n" + "=" * 70)
        print("🎉 所有Critical Issues修复验证通过!")
        print("=" * 70)
        sys.exit(0)
        
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
