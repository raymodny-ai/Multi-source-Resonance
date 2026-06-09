"""
Phase 4 量化逻辑层 - 综合测试脚本

该脚本测试所有4个核心量化模块的功能:
1. GEX计算引擎
2. VIX期限结构分析器
3. 加密杠杆清洗判定引擎
4. 暗盘三驾马车验证引擎
"""

import sys
import os
import pandas as pd
import numpy as np

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


def test_gex_calculator():
    """测试GEX计算引擎"""
    print("=" * 80)
    print("测试1: GEX计算引擎")
    print("=" * 80)
    
    from quant_logic.gex_calculator import GEXCalculator, calculate_single_option_gex
    
    calc = GEXCalculator()
    
    # 测试1.1: Black-Scholes Delta计算
    print("\n[1.1] 测试Black-Scholes Delta计算")
    delta_call = calc.calculate_delta(
        strike=100, spot=105, volatility=0.2, 
        time_to_expiry=0.25, option_type='CALL'
    )
    delta_put = calc.calculate_delta(
        strike=100, spot=105, volatility=0.2, 
        time_to_expiry=0.25, option_type='PUT'
    )
    print(f"  Call Delta (S=105, K=100): {delta_call:.4f}")
    print(f"  Put Delta (S=105, K=100): {delta_put:.4f}")
    assert 0 < delta_call < 1, "Call Delta应该在0-1之间"
    assert -1 < delta_put < 0, "Put Delta应该在-1-0之间"
    print("  [PASS] Delta计算通过")
    
    # 测试1.2: Gamma计算
    print("\n[1.2] 测试Gamma计算")
    gamma = calc.calculate_gamma(
        strike=100, spot=105, volatility=0.2, time_to_expiry=0.25
    )
    print(f"  Gamma: {gamma:.6f}")
    assert gamma > 0, "Gamma应该始终为正"
    print("  [PASS] Gamma计算通过")
    
    # 测试1.3: 投资组合GEX计算
    print("\n[1.3] 测试投资组合GEX计算")
    option_df = pd.DataFrame({
        'strike': [95, 100, 105, 110],
        'type': ['CALL', 'CALL', 'PUT', 'PUT'],
        'expiry': ['2024-01-19'] * 4,
        'bid': [10.0, 5.0, 3.0, 1.0],
        'ask': [10.5, 5.5, 3.5, 1.5],
        'volume': [100, 200, 150, 80],
        'open_interest': [1000, 2000, 1500, 800],
        'implied_volatility': [0.25, 0.2, 0.22, 0.28],
        'days_to_expiry': [30, 30, 30, 30]
    })
    
    gex_result = calc.calculate_portfolio_gex(option_df, spot_price=105.0)
    print(f"  Total GEX: ${gex_result['total_gex']:,.2f}")
    print(f"  Call GEX: ${gex_result['call_gex']:,.2f}")
    print(f"  Put GEX: ${gex_result['put_gex']:,.2f}")
    print(f"  Net GEX: ${gex_result['net_gex']:,.2f}")
    print(f"  Strikes with GEX: {len(gex_result['gex_by_strike'])}")
    assert 'total_gex' in gex_result
    assert 'call_gex' in gex_result
    assert 'put_gex' in gex_result
    assert 'net_gex' in gex_result
    print("  [PASS] 投资组合GEX计算通过")
    
    # 测试1.4: Flip Zone识别
    print("\n[1.4] 测试Flip Zone识别")
    gex_profile = {
        100: -500000,
        105: -100000,
        110: 200000,
        115: 500000
    }
    flip_zone = calc.identify_flip_zone(gex_profile)
    print(f"  Flip Zone: [{flip_zone['flip_zone_lower']}, {flip_zone['flip_zone_upper']}]")
    print(f"  Flip Point: {flip_zone['flip_point']:.2f}")
    print(f"  Is Positive: {flip_zone['is_positive']}")
    assert flip_zone['flip_point'] > 0
    print("  [PASS] Flip Zone识别通过")
    
    # 测试1.5: Put Wall识别
    print("\n[1.5] 测试Put Wall识别")
    put_wall = calc.find_put_wall(gex_result['gex_by_strike'])
    print(f"  Put Wall Strike: ${put_wall}")
    print("  [PASS] Put Wall识别通过")
    
    # 测试1.6: 校准系数
    print("\n[1.6] 测试校准系数计算")
    alpha = GEXCalculator.calibrate_alpha(local_gex=1000000, official_gex=1200000)
    print(f"  Alpha: {alpha:.4f}")
    calibrated = GEXCalculator.apply_calibration(gex_local=1000000, alpha=alpha)
    print(f"  Calibrated GEX: ${calibrated:,.2f}")
    assert abs(calibrated - 1200000) < 0.01
    print("  [PASS] 校准系数计算通过")
    
    # 测试1.7: 空DataFrame鲁棒性
    print("\n[1.7] 测试空DataFrame鲁棒性")
    empty_df = pd.DataFrame()
    result_empty = calc.calculate_portfolio_gex(empty_df, 100.0)
    assert result_empty['total_gex'] == 0.0
    print("  [PASS] 空DataFrame处理通过")
    
    print("\n[PASS] GEX计算引擎所有测试通过!\n")


def test_vix_analyzer():
    """测试VIX期限结构分析器"""
    print("=" * 80)
    print("测试2: VIX期限结构分析器")
    print("=" * 80)
    
    from quant_logic.vix_analyzer import VIXAnalyzer, quick_vix_analysis
    
    analyzer = VIXAnalyzer()
    
    # 测试2.1: Contango状态
    print("\n[2.1] 测试Contango状态识别")
    result_contango = analyzer.analyze_term_structure(vx1=15.0, vx2=16.0)
    print(f"  State: {result_contango['state']}")
    print(f"  Ratio: {result_contango['ratio']:.3f}")
    print(f"  Contango %: {result_contango['contango_pct']:.2f}%")
    assert result_contango['state'] == 'CONTANGO'
    assert result_contango['ratio'] < 1.0
    print("  [PASS] Contango识别通过")
    
    # 测试2.2: Backwardation状态
    print("\n[2.2] 测试Backwardation状态识别")
    result_backward = analyzer.analyze_term_structure(vx1=20.0, vx2=17.0)
    print(f"  State: {result_backward['state']}")
    print(f"  Ratio: {result_backward['ratio']:.3f}")
    print(f"  Is Extreme: {result_backward['is_extreme_backwardation']}")
    assert result_backward['state'] == 'BACKWARDATION'
    assert result_backward['ratio'] > 1.0
    print("  [PASS] Backwardation识别通过")
    
    # 测试2.3: 极端Backwardation
    print("\n[2.3] 测试极端Backwardation检测")
    result_extreme = analyzer.analyze_term_structure(vx1=25.0, vx2=20.0)
    print(f"  Ratio: {result_extreme['ratio']:.3f}")
    print(f"  Is Extreme Backwardation: {result_extreme['is_extreme_backwardation']}")
    assert result_extreme['is_extreme_backwardation'] == True
    print("  [PASS] 极端Backwardation检测通过")
    
    # 测试2.4: 恐慌溢价计算
    print("\n[2.4] 测试恐慌溢价计算")
    panic_result = analyzer.calculate_panic_premium(vix_spot=15.0, vx1=18.0)
    print(f"  Premium Ratio: {panic_result['premium_ratio']:.3f}")
    print(f"  Is Panic: {panic_result['is_panic']}")
    print(f"  Premium %: {panic_result['premium_pct']:.2f}%")
    assert panic_result['premium_ratio'] > 1.0
    print("  [PASS] 恐慌溢价计算通过")
    
    # 测试2.5: VIX信号分值
    print("\n[2.5] 测试VIX信号分值计算")
    score1 = analyzer.get_vix_score(vx1=25.0, vx2=20.0, slope_direction='UP')
    print(f"  Score (Extreme Backwardation): {score1}")
    assert score1 == 0.5
    
    score2 = analyzer.get_vix_score(vx1=14.0, vx2=16.0, slope_direction='DOWN')
    print(f"  Score (Return to Contango): {score2}")
    assert score2 == 1.0
    
    score3 = analyzer.get_vix_score(vx1=15.0, vx2=16.0, slope_direction='UP')
    print(f"  Score (Normal Contango): {score3}")
    assert score3 == 0.0
    print("  [PASS] VIX信号分值计算通过")
    
    # 测试2.6: 快速分析函数
    print("\n[2.6] 测试快速分析函数")
    quick_result = quick_vix_analysis(vx1=18.0, vx2=16.0, vix_spot=15.0)
    print(f"  Term Structure: {quick_result['term_structure']['state']}")
    print(f"  Interpretation: {quick_result['interpretation'][:50]}...")
    if 'panic_premium' in quick_result:
        print(f"  Panic Premium: {quick_result['panic_premium']['premium_pct']:.2f}%")
    print("  [PASS] 快速分析函数通过")
    
    print("\n[PASS] VIX期限结构分析器所有测试通过!\n")


def test_crypto_leverage_cleaner():
    """测试加密杠杆清洗判定引擎"""
    print("=" * 80)
    print("测试3: 加密杠杆清洗判定引擎")
    print("=" * 80)
    
    from quant_logic.crypto_leverage_cleaner import CryptoLeverageCleaner, quick_leverage_check
    
    cleaner = CryptoLeverageCleaner()
    
    # 测试3.1: 资金费率异常检测
    print("\n[3.1] 测试资金费率异常检测")
    anomaly1 = cleaner.check_funding_rate_anomaly(funding_rate=-0.0002)
    print(f"  Funding Rate -0.02%: Anomaly={anomaly1}")
    assert anomaly1 == True
    
    anomaly2 = cleaner.check_funding_rate_anomaly(funding_rate=0.0001)
    print(f"  Funding Rate +0.01%: Anomaly={anomaly2}")
    assert anomaly2 == False
    print("  [PASS] 资金费率异常检测通过")
    
    # 测试3.2: OI断崖式下跌检测
    print("\n[3.2] 测试OI断崖式下跌检测")
    historical_oi = [1000, 1050, 1100, 1080, 1120, 1150, 1200, 1180, 1250, 1300, 1280, 1350]
    oi_result = cleaner.detect_oi_crash(current_oi=1000, historical_oi_list=historical_oi)
    print(f"  Crash Detected: {oi_result['crash_detected']}")
    print(f"  Drop Percentage: {oi_result['drop_percentage']:.2f}%")
    print(f"  Max Drop from Peak: {oi_result['max_drop_from_peak']:.2f}%")
    assert oi_result['crash_detected'] == True
    assert oi_result['drop_percentage'] > 15.0
    print("  [PASS] OI断崖式下跌检测通过")
    
    # 测试3.3: 去杠杆完成判定
    print("\n[3.3] 测试去杠杆完成判定")
    cleanup = cleaner.confirm_leverage_cleanup(
        funding_rate=0.0001,
        oi_drop_pct=20.0,
        elr_current=2.5,
        elr_historical_avg=3.0
    )
    print(f"  Leverage Cleanup Confirmed: {cleanup}")
    assert cleanup == True
    
    cleanup2 = cleaner.confirm_leverage_cleanup(
        funding_rate=-0.0001,  # 费率仍为负
        oi_drop_pct=20.0,
        elr_current=2.5,
        elr_historical_avg=3.0
    )
    print(f"  Cleanup (Negative Funding): {cleanup2}")
    assert cleanup2 == False
    print("  [PASS] 去杠杆完成判定通过")
    
    # 测试3.4: 加密信号分值
    print("\n[3.4] 测试加密信号分值计算")
    score1 = cleaner.get_crypto_score(
        oi_crash=True, funding_positive=False, elr_safe=False
    )
    print(f"  Score (OI Crash Only): {score1}")
    assert score1 == 0.5
    
    score2 = cleaner.get_crypto_score(
        oi_crash=True, funding_positive=True, elr_safe=True
    )
    print(f"  Score (Cleanup Complete): {score2}")
    assert score2 == 1.0
    
    score3 = cleaner.get_crypto_score(
        oi_crash=False, funding_positive=False, elr_safe=False
    )
    print(f"  Score (No Signal): {score3}")
    assert score3 == 0.0
    print("  [PASS] 加密信号分值计算通过")
    
    # 测试3.5: 综合分析
    print("\n[3.5] 测试综合分析函数")
    analysis = cleaner.analyze_leverage_state(
        funding_rate=0.0001,
        current_oi=1000,
        historical_oi_list=historical_oi,
        elr_current=2.5,
        elr_historical_avg=3.0
    )
    print(f"  Stage: {analysis['stage']}")
    print(f"  Signal Score: {analysis['signal_score']}")
    print(f"  Cleanup Confirmed: {analysis['cleanup_confirmed']}")
    assert analysis['stage'] == 'COMPLETED'
    print("  [PASS] 综合分析函数通过")
    
    # 测试3.6: 边界条件
    print("\n[3.6] 测试边界条件")
    edge_result = cleaner.detect_oi_crash(current_oi=100, historical_oi_list=[])
    assert edge_result['crash_detected'] == False
    print("  [PASS] 边界条件处理通过")
    
    print("\n[PASS] 加密杠杆清洗判定引擎所有测试通过!\n")


def test_darkpool_verifier():
    """测试暗盘三驾马车验证引擎"""
    print("=" * 80)
    print("测试4: 暗盘三驾马车验证引擎")
    print("=" * 80)
    
    from quant_logic.darkpool_verifier import DarkPoolVerifier, quick_darkpool_check
    
    verifier = DarkPoolVerifier()
    
    # 测试4.1: DIX阈值检测
    print("\n[4.1] 测试DIX阈值检测")
    dix_active = verifier.check_dix_threshold(dix_value=50.0)
    print(f"  DIX=50%: Active={dix_active}")
    assert dix_active == True
    
    dix_inactive = verifier.check_dix_threshold(dix_value=40.0)
    print(f"  DIX=40%: Active={dix_inactive}")
    assert dix_inactive == False
    print("  [PASS] DIX阈值检测通过")
    
    # 测试4.2: 卖空比连续性检测
    print("\n[4.2] 测试卖空比连续性检测")
    short_data_consecutive = [50.0, 48.0, 42.0]
    short_active = verifier.check_short_volume_consecutive(short_data_consecutive)
    print(f"  Data {short_data_consecutive}: Active={short_active}")
    assert short_active == True
    
    short_data_not_consecutive = [50.0, 40.0, 48.0]
    short_inactive = verifier.check_short_volume_consecutive(short_data_not_consecutive)
    print(f"  Data {short_data_not_consecutive}: Active={short_inactive}")
    assert short_inactive == False
    print("  [PASS] 卖空比连续性检测通过")
    
    # 测试4.3: Stockgrid信号确认
    print("\n[4.3] 测试Stockgrid信号确认")
    stockgrid1 = verifier.confirm_stockgrid_signal(
        divergence_flag=True, slope_20d=-0.5, slope_60d=-0.3
    )
    print(f"  Divergence=True: Confirmed={stockgrid1}")
    assert stockgrid1 == True
    
    stockgrid2 = verifier.confirm_stockgrid_signal(
        divergence_flag=False, slope_20d=0.8, slope_60d=0.5
    )
    print(f"  Dual Slopes Positive: Confirmed={stockgrid2}")
    assert stockgrid2 == True
    
    stockgrid3 = verifier.confirm_stockgrid_signal(
        divergence_flag=False, slope_20d=-0.5, slope_60d=-0.3
    )
    print(f"  No Signal: Confirmed={stockgrid3}")
    assert stockgrid3 == False
    print("  [PASS] Stockgrid信号确认通过")
    
    # 测试4.4: 三选二聚合机制
    print("\n[4.4] 测试三选二聚合机制")
    agg_result = verifier.aggregate_darkpool_signals(
        dix_flag=True, short_ratio_flag=True, stockgrid_flag=False
    )
    print(f"  Signal Count: {agg_result['signal_count']}")
    print(f"  Aggregated: {agg_result['aggregated_signal']}")
    assert agg_result['signal_count'] == 2
    assert agg_result['aggregated_signal'] == True
    
    agg_result2 = verifier.aggregate_darkpool_signals(
        dix_flag=True, short_ratio_flag=False, stockgrid_flag=False
    )
    print(f"  Single Signal Aggregated: {agg_result2['aggregated_signal']}")
    assert agg_result2['aggregated_signal'] == False
    print("  [PASS] 三选二聚合机制通过")
    
    # 测试4.5: 暗盘信号分值
    print("\n[4.5] 测试暗盘信号分值计算")
    score1 = verifier.get_darkpool_score(
        dix_flag=True, short_ratio_flag=True, stockgrid_flag=False, dbmf_recovery=False
    )
    print(f"  Score (3选2): {score1}")
    assert score1 == 0.75
    
    score2 = verifier.get_darkpool_score(
        dix_flag=True, short_ratio_flag=True, stockgrid_flag=False, dbmf_recovery=True
    )
    print(f"  Score (3选2 + DBMF): {score2}")
    assert score2 == 1.5
    
    score3 = verifier.get_darkpool_score(
        dix_flag=True, short_ratio_flag=False, stockgrid_flag=False, dbmf_recovery=False
    )
    print(f"  Score (Insufficient): {score3}")
    assert score3 == 0.0
    print("  [PASS] 暗盘信号分值计算通过")
    
    # 测试4.6: 完整验证流程
    print("\n[4.6] 测试完整验证流程")
    full_result = verifier.full_verification(
        dix_value=50.0,
        short_volume_days=[50.0, 48.0, 42.0],
        divergence_flag=False,
        slope_20d=0.8,
        slope_60d=0.5,
        dbmf_recovery=True
    )
    print(f"  Final Score: {full_result['final_score']}")
    print(f"  Signal Strength: {full_result['signal_strength']}")
    print(f"  Aggregation: {full_result['aggregation']['signal_count']}/3 signals")
    assert full_result['final_score'] == 1.5
    assert full_result['signal_strength'] == 'VERY STRONG'
    print("  [PASS] 完整验证流程通过")
    
    # 测试4.7: None值处理
    print("\n[4.7] 测试None值处理")
    dix_none = verifier.check_dix_threshold(dix_value=None)
    assert dix_none == False
    print("  [PASS] None值处理通过")
    
    print("\n[PASS] 暗盘三驾马车验证引擎所有测试通过!\n")


def main():
    """运行所有测试"""
    print("\n" + "=" * 80)
    print("Phase 4 量化逻辑层 - 综合测试")
    print("=" * 80 + "\n")
    
    try:
        test_gex_calculator()
        test_vix_analyzer()
        test_crypto_leverage_cleaner()
        test_darkpool_verifier()
        
        print("\n" + "=" * 80)
        print("SUCCESS! 所有测试通过! Phase 4量化逻辑层实现成功!")
        print("=" * 80)
        return 0
        
    except AssertionError as e:
        print(f"\n[ERROR] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n[ERROR] 发生错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
