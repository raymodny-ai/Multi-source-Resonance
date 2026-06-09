"""
Phase 4 量化逻辑层 - 快速验证脚本

运行此脚本快速验证所有模块是否正确安装和导入。
"""

import sys
import os

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)


def verify_imports():
    """验证模块导入"""
    print("=" * 80)
    print("验证1: 模块导入")
    print("=" * 80)
    
    try:
        from quant_logic import (
            GEXCalculator,
            VIXAnalyzer,
            CryptoLeverageCleaner,
            DarkPoolVerifier,
            calculate_single_option_gex,
            quick_vix_analysis,
            quick_leverage_check,
            quick_darkpool_check
        )
        print("[PASS] 所有核心类导入成功")
        print("[PASS] 所有便捷函数导入成功")
        return True
    except ImportError as e:
        print(f"[FAIL] 导入失败: {e}")
        return False


def verify_gex_calculator():
    """验证GEX计算引擎"""
    print("\n" + "=" * 80)
    print("验证2: GEX计算引擎")
    print("=" * 80)
    
    try:
        from quant_logic import GEXCalculator
        import pandas as pd
        
        calc = GEXCalculator()
        
        # 测试Delta计算
        delta = calc.calculate_delta(100, 105, 0.2, 0.25, 'CALL')
        assert 0 < delta < 1, "Delta范围错误"
        print(f"[PASS] Delta计算: {delta:.4f}")
        
        # 测试Gamma计算
        gamma = calc.calculate_gamma(100, 105, 0.2, 0.25)
        assert gamma > 0, "Gamma应为正"
        print(f"[PASS] Gamma计算: {gamma:.6f}")
        
        # 测试组合GEX
        df = pd.DataFrame({
            'strike': [100],
            'type': ['CALL'],
            'expiry': ['2024-01-19'],
            'bid': [5.0],
            'ask': [5.5],
            'volume': [100],
            'open_interest': [1000],
            'implied_volatility': [0.2],
            'days_to_expiry': [30]
        })
        result = calc.calculate_portfolio_gex(df, 105.0)
        assert 'total_gex' in result
        print(f"[PASS] 组合GEX计算: ${result['total_gex']:,.2f}")
        
        return True
    except Exception as e:
        print(f"[FAIL] GEX验证失败: {e}")
        return False


def verify_vix_analyzer():
    """验证VIX分析器"""
    print("\n" + "=" * 80)
    print("验证3: VIX期限结构分析器")
    print("=" * 80)
    
    try:
        from quant_logic import VIXAnalyzer
        
        analyzer = VIXAnalyzer()
        
        # 测试Contango识别
        result = analyzer.analyze_term_structure(15.0, 16.0)
        assert result['state'] == 'CONTANGO'
        print(f"[PASS] Contango识别: {result['state']}")
        
        # 测试Backwardation识别
        result = analyzer.analyze_term_structure(20.0, 17.0)
        assert result['state'] == 'BACKWARDATION'
        print(f"[PASS] Backwardation识别: {result['state']}")
        
        # 测试信号分值
        score = analyzer.get_vix_score(14.0, 16.0, 'DOWN')
        assert score == 1.0
        print(f"[PASS] VIX信号分值: {score}")
        
        return True
    except Exception as e:
        print(f"[FAIL] VIX验证失败: {e}")
        return False


def verify_crypto_leverage_cleaner():
    """验证加密杠杆清洗判定引擎"""
    print("\n" + "=" * 80)
    print("验证4: 加密杠杆清洗判定引擎")
    print("=" * 80)
    
    try:
        from quant_logic import CryptoLeverageCleaner
        
        cleaner = CryptoLeverageCleaner()
        
        # 测试资金费率检测
        anomaly = cleaner.check_funding_rate_anomaly(-0.0002)
        assert anomaly == True
        print(f"[PASS] 资金费率异常检测: {anomaly}")
        
        # 测试OI暴跌检测
        historical = [1000, 1100, 1200, 1300]
        result = cleaner.detect_oi_crash(1000, historical)
        assert result['crash_detected'] == True
        print(f"[PASS] OI暴跌检测: {result['drop_percentage']:.2f}%")
        
        # 测试去杠杆判定
        cleanup = cleaner.confirm_leverage_cleanup(0.0001, 20.0, 2.5, 3.0)
        assert cleanup == True
        print(f"[PASS] 去杠杆完成判定: {cleanup}")
        
        return True
    except Exception as e:
        print(f"[FAIL] 加密杠杆验证失败: {e}")
        return False


def verify_darkpool_verifier():
    """验证暗盘验证引擎"""
    print("\n" + "=" * 80)
    print("验证5: 暗盘三驾马车验证引擎")
    print("=" * 80)
    
    try:
        from quant_logic import DarkPoolVerifier
        
        verifier = DarkPoolVerifier()
        
        # 测试DIX检测
        dix_active = verifier.check_dix_threshold(50.0)
        assert dix_active == True
        print(f"[PASS] DIX阈值检测: {dix_active}")
        
        # 测试卖空比连续性
        short_data = [50.0, 48.0, 42.0]
        short_active = verifier.check_short_volume_consecutive(short_data)
        assert short_active == True
        print(f"[PASS] 卖空比连续性检测: {short_active}")
        
        # 测试三选二聚合
        agg = verifier.aggregate_darkpool_signals(True, True, False)
        assert agg['aggregated_signal'] == True
        print(f"[PASS] 三选二聚合: {agg['signal_count']}/3 signals")
        
        # 测试信号分值
        score = verifier.get_darkpool_score(True, True, False, True)
        assert score == 1.5
        print(f"[PASS] 暗盘信号分值: {score}")
        
        return True
    except Exception as e:
        print(f"[FAIL] 暗盘验证失败: {e}")
        return False


def verify_convenience_functions():
    """验证便捷函数"""
    print("\n" + "=" * 80)
    print("验证6: 便捷函数")
    print("=" * 80)
    
    try:
        from quant_logic import (
            calculate_single_option_gex,
            quick_vix_analysis,
            quick_leverage_check,
            quick_darkpool_check
        )
        
        # 测试单个期权GEX
        gex = calculate_single_option_gex(100, 105, 0.2, 0.25, 1000, 'CALL')
        assert gex > 0
        print(f"[PASS] calculate_single_option_gex: ${gex:,.2f}")
        
        # 测试快速VIX分析
        vix_result = quick_vix_analysis(15.0, 16.0)
        assert 'term_structure' in vix_result
        print(f"[PASS] quick_vix_analysis: {vix_result['term_structure']['state']}")
        
        # 测试快速杠杆检查
        leverage_result = quick_leverage_check(0.0001, 1000, [1100, 1200], 2.5, 3.0)
        assert 'signal_score' in leverage_result
        print(f"[PASS] quick_leverage_check: score={leverage_result['signal_score']}")
        
        # 测试快速暗盘检查
        darkpool_result = quick_darkpool_check(50.0, [48.0, 50.0], False, 0.8, 0.6)
        assert 'final_score' in darkpool_result
        print(f"[PASS] quick_darkpool_check: score={darkpool_result['final_score']}")
        
        return True
    except Exception as e:
        print(f"[FAIL] 便捷函数验证失败: {e}")
        return False


def main():
    """运行所有验证"""
    print("\n" + "=" * 80)
    print("Phase 4 量化逻辑层 - 快速验证")
    print("=" * 80 + "\n")
    
    results = []
    
    results.append(("模块导入", verify_imports()))
    results.append(("GEX计算引擎", verify_gex_calculator()))
    results.append(("VIX分析器", verify_vix_analyzer()))
    results.append(("加密杠杆清洗", verify_crypto_leverage_cleaner()))
    results.append(("暗盘验证引擎", verify_darkpool_verifier()))
    results.append(("便捷函数", verify_convenience_functions()))
    
    # 汇总结果
    print("\n" + "=" * 80)
    print("验证结果汇总")
    print("=" * 80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status} - {name}")
    
    print("-" * 80)
    print(f"总计: {passed}/{total} 通过")
    
    if passed == total:
        print("\nSUCCESS! 所有验证通过! Phase 4量化逻辑层已就绪!")
        return 0
    else:
        print(f"\nWARNING: {total - passed} 个验证失败,请检查错误信息")
        return 1


if __name__ == '__main__':
    sys.exit(main())
