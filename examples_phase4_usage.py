"""
Phase 4 量化逻辑层 - 使用示例

本文件展示如何使用4个核心量化模块进行实际分析。
"""

import sys
import os
import pandas as pd
import numpy as np

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from quant_logic import (
    GEXCalculator,
    VIXAnalyzer,
    CryptoLeverageCleaner,
    DarkPoolVerifier
)


def example_gex_analysis():
    """示例1: GEX敞口分析"""
    print("=" * 80)
    print("示例1: Gamma敞口(GEX)分析")
    print("=" * 80)
    
    calc = GEXCalculator()
    
    # 构建期权链数据
    option_chain = pd.DataFrame({
        'strike': [90, 95, 100, 105, 110, 115],
        'type': ['CALL', 'CALL', 'CALL', 'PUT', 'PUT', 'PUT'],
        'expiry': ['2024-01-19'] * 6,
        'bid': [15.0, 10.0, 5.0, 3.0, 1.5, 0.5],
        'ask': [15.5, 10.5, 5.5, 3.5, 2.0, 1.0],
        'volume': [50, 100, 200, 150, 80, 30],
        'open_interest': [500, 1000, 2000, 1500, 800, 300],
        'implied_volatility': [0.30, 0.25, 0.20, 0.22, 0.25, 0.30],
        'days_to_expiry': [30, 30, 30, 30, 30, 30]
    })
    
    spot_price = 102.5
    
    # 计算组合GEX
    gex_result = calc.calculate_portfolio_gex(option_chain, spot_price)
    
    print(f"\n标的价格: ${spot_price}")
    print(f"总GEX敞口: ${gex_result['total_gex']:,.2f}")
    print(f"Call端GEX: ${gex_result['call_gex']:,.2f}")
    print(f"Put端GEX: ${gex_result['put_gex']:,.2f}")
    print(f"净GEX: ${gex_result['net_gex']:,.2f}")
    
    # 识别Flip Zone
    flip_zone = calc.identify_flip_zone(gex_result['gex_by_strike'])
    print(f"\nFlip Zone: [{flip_zone['flip_zone_lower']}, {flip_zone['flip_zone_upper']}]")
    print(f"精确翻转点: ${flip_zone['flip_point']:.2f}")
    
    # 寻找Put Wall
    put_wall = calc.find_put_wall(gex_result['gex_by_strike'])
    if put_wall > 0:
        print(f"Put Wall支撑位: ${put_wall}")
    
    print("\n" + "-" * 80 + "\n")


def example_vix_analysis():
    """示例2: VIX期限结构分析"""
    print("=" * 80)
    print("示例2: VIX期限结构分析")
    print("=" * 80)
    
    analyzer = VIXAnalyzer()
    
    # 场景1: 正常Contango市场
    print("\n[场景1] 正常Contango市场")
    vx1, vx2 = 14.5, 16.0
    result = analyzer.analyze_term_structure(vx1, vx2)
    print(f"VX1={vx1}, VX2={vx2}")
    print(f"状态: {result['state']}")
    print(f"期限结构比值: {result['ratio']:.3f}")
    print(analyzer.interpret_term_structure(vx1, vx2))
    
    # 场景2: Backwardation恐慌市场
    print("\n[场景2] Backwardation恐慌市场")
    vx1, vx2 = 22.0, 18.5
    result = analyzer.analyze_term_structure(vx1, vx2)
    panic = analyzer.calculate_panic_premium(vix_spot=19.0, vx1=vx1)
    print(f"VX1={vx1}, VX2={vx2}")
    print(f"状态: {result['state']}")
    print(f"恐慌溢价: {panic['premium_pct']:.2f}%")
    print(f"是否恐慌: {'是' if panic['is_panic'] else '否'}")
    
    # 场景3: 信号分值计算
    print("\n[场景3] VIX信号分值")
    score = analyzer.get_vix_score(vx1=13.5, vx2=16.0, slope_direction='DOWN')
    print(f"回归Contango + 斜率向下: 分值={score}")
    
    print("\n" + "-" * 80 + "\n")


def example_crypto_leverage():
    """示例3: 加密杠杆清洗判定"""
    print("=" * 80)
    print("示例3: 加密市场杠杆清洗判定")
    print("=" * 80)
    
    cleaner = CryptoLeverageCleaner()
    
    # 模拟去杠杆过程数据
    historical_oi = [
        50000, 51000, 52000, 53000, 54000, 55000,
        56000, 57000, 58000, 59000, 60000, 61000
    ]
    current_oi = 48000  # OI暴跌
    funding_rate = 0.0001  # 费率转正
    elr_current = 2.3
    elr_historical_avg = 3.0
    
    print(f"\n当前持仓量: {current_oi:,}")
    print(f"历史峰值: {max(historical_oi):,}")
    print(f"资金费率: {funding_rate*100:.4f}%")
    print(f"当前ELR: {elr_current}")
    print(f"历史平均ELR: {elr_historical_avg}")
    
    # 综合分析
    analysis = cleaner.analyze_leverage_state(
        funding_rate=funding_rate,
        current_oi=current_oi,
        historical_oi_list=historical_oi,
        elr_current=elr_current,
        elr_historical_avg=elr_historical_avg
    )
    
    print(f"\nOI下跌幅度: {analysis['oi_analysis']['drop_percentage']:.2f}%")
    print(f"检测到暴跌: {'是' if analysis['oi_analysis']['crash_detected'] else '否'}")
    print(f"去杠杆阶段: {analysis['stage']}")
    print(f"信号分值: {analysis['signal_score']}")
    print(f"清理确认: {'是' if analysis['cleanup_confirmed'] else '否'}")
    
    print("\n" + "-" * 80 + "\n")


def example_darkpool_verification():
    """示例4: 暗盘三驾马车验证"""
    print("=" * 80)
    print("示例4: 暗盘机构资金验证")
    print("=" * 80)
    
    verifier = DarkPoolVerifier()
    
    # 模拟数据
    dix_value = 52.0
    short_volume_days = [48.0, 50.0, 46.0, 44.0, 42.0]
    divergence_flag = False
    slope_20d = 0.85
    slope_60d = 0.62
    dbmf_recovery = True
    
    print(f"\nDIX值: {dix_value}%")
    print(f"最近5日卖空比: {short_volume_days}")
    print(f"底背离: {'是' if divergence_flag else '否'}")
    print(f"20日斜率: {slope_20d}")
    print(f"60日斜率: {slope_60d}")
    print(f"DBMF收复: {'是' if dbmf_recovery else '否'}")
    
    # 完整验证
    result = verifier.full_verification(
        dix_value=dix_value,
        short_volume_days=short_volume_days,
        divergence_flag=divergence_flag,
        slope_20d=slope_20d,
        slope_60d=slope_60d,
        dbmf_recovery=dbmf_recovery
    )
    
    print(f"\n--- 验证结果 ---")
    print(f"DIX信号: {'激活' if result['dix']['active'] else '未激活'}")
    print(f"卖空比信号: {'激活' if result['short_volume']['active'] else '未激活'}")
    print(f"Stockgrid信号: {'激活' if result['stockgrid']['active'] else '未激活'}")
    print(f"触发信号数: {result['aggregation']['signal_count']}/3")
    print(f"聚合信号: {'是' if result['aggregation']['aggregated_signal'] else '否'}")
    print(f"最终分值: {result['final_score']}")
    print(f"信号强度: {result['signal_strength']}")
    
    print("\n" + "-" * 80 + "\n")


def example_multi_dimension_resonance():
    """示例5: 多维度共振矩阵"""
    print("=" * 80)
    print("示例5: 多维度共振矩阵综合评分")
    print("=" * 80)
    
    # 初始化所有分析器
    gex_calc = GEXCalculator()
    vix_analyzer = VIXAnalyzer()
    crypto_cleaner = CryptoLeverageCleaner()
    darkpool_verifier = DarkPoolVerifier()
    
    # 假设各维度数据
    print("\n[输入数据]")
    
    # 1. GEX维度
    option_chain = pd.DataFrame({
        'strike': [100, 105, 110],
        'type': ['CALL', 'PUT', 'PUT'],
        'expiry': ['2024-01-19'] * 3,
        'bid': [5.0, 3.0, 1.0],
        'ask': [5.5, 3.5, 1.5],
        'volume': [100, 150, 80],
        'open_interest': [1000, 1500, 800],
        'implied_volatility': [0.2, 0.22, 0.25],
        'days_to_expiry': [30, 30, 30]
    })
    gex_result = gex_calc.calculate_portfolio_gex(option_chain, 105.0)
    gex_score = 1.0 if gex_result['net_gex'] > 0 else 0.5
    print(f"GEX维度: 净GEX=${gex_result['net_gex']:,.0f}, 分值={gex_score}")
    
    # 2. VIX维度
    vix_score = vix_analyzer.get_vix_score(vx1=14.0, vx2=16.0, slope_direction='DOWN')
    print(f"VIX维度: 分值={vix_score}")
    
    # 3. 加密维度
    crypto_score = crypto_cleaner.get_crypto_score(
        oi_crash=True, funding_positive=True, elr_safe=True
    )
    print(f"加密维度: 分值={crypto_score}")
    
    # 4. 暗盘维度
    darkpool_score = darkpool_verifier.get_darkpool_score(
        dix_flag=True, short_ratio_flag=True, stockgrid_flag=False, dbmf_recovery=True
    )
    print(f"暗盘维度: 分值={darkpool_score}")
    
    # 计算共振总分
    total_score = gex_score + vix_score + crypto_score + darkpool_score
    max_score = 1.0 + 1.0 + 1.0 + 1.5  # 最大可能分值
    resonance_pct = (total_score / max_score) * 100
    
    print(f"\n{'='*60}")
    print(f"共振总分: {total_score:.2f} / {max_score:.2f}")
    print(f"共振强度: {resonance_pct:.1f}%")
    
    if resonance_pct >= 75:
        print("信号等级: STRONG BUY (强烈买入)")
    elif resonance_pct >= 50:
        print("信号等级: MODERATE BUY (中等买入)")
    elif resonance_pct >= 25:
        print("信号等级: WEAK SIGNAL (弱信号)")
    else:
        print("信号等级: NO SIGNAL (无信号)")
    
    print(f"{'='*60}\n")


def main():
    """运行所有示例"""
    print("\n" + "=" * 80)
    print("Phase 4 量化逻辑层 - 使用示例")
    print("=" * 80 + "\n")
    
    try:
        example_gex_analysis()
        example_vix_analysis()
        example_crypto_leverage()
        example_darkpool_verification()
        example_multi_dimension_resonance()
        
        print("=" * 80)
        print("所有示例运行完成!")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
