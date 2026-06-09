"""
多源共振监控系统 - Phase 5 信号引擎使用示例

本示例展示如何使用 ResonanceScorer 和 SignalStateMachine 进行：
1. 多维度信号评分
2. Hawkes Process 自激抛售测算
3. 共振总分计算与预警分级
4. 信号触发状态机管理
5. 告警消息格式化输出
"""

from datetime import datetime
import pytz

from signal_engine.resonance_scorer import ResonanceScorer
from signal_engine.signal_trigger import SignalStateMachine, format_alert_message


def example_basic_scoring():
    """示例1: 基础评分功能"""
    print("=" * 80)
    print("示例1: 基础评分功能")
    print("=" * 80)
    
    scorer = ResonanceScorer()
    
    # GEX维度评分
    print("\n【GEX维度评分】")
    gex_result = scorer.calculate_gex_score(
        gex_local=-5e6,
        gex_calibrated=2e6,
        flip_zone_crossed=True,
        gex_trend='IMPROVING'
    )
    print(f"  分值: {gex_result['score']}")
    print(f"  状态: {gex_result['state']}")
    print(f"  详情: {gex_result['details']}")
    
    # VIX维度评分
    print("\n【VIX维度评分】")
    vix_result = scorer.calculate_vix_score(
        term_structure_ratio=0.95,
        slope_direction='DOWN',
        panic_premium=5.2
    )
    print(f"  分值: {vix_result['score']}")
    print(f"  状态: {vix_result['state']}")
    print(f"  详情: {vix_result['details']}")
    
    # 加密维度评分
    print("\n【加密维度评分】")
    crypto_result = scorer.calculate_crypto_score(
        oi_crash=True,
        funding_positive=True,
        elr_safe=True,
        leverage_cleanup_confirmed=True
    )
    print(f"  分值: {crypto_result['score']}")
    print(f"  状态: {crypto_result['state']}")
    print(f"  详情: {crypto_result['details']}")
    
    # 暗盘维度评分
    print("\n【暗盘维度评分】")
    darkpool_result = scorer.calculate_darkpool_score(
        dix_flag=True,
        short_ratio_flag=True,
        stockgrid_flag=False,
        dbmf_recovery=True,
        aggregated_signal=True
    )
    print(f"  分值: {darkpool_result['score']}")
    print(f"  状态: {darkpool_result['state']}")
    print(f"  详情: {darkpool_result['details']}")


def example_total_resonance():
    """示例2: 综合共振评分与预警分级"""
    print("\n" + "=" * 80)
    print("示例2: 综合共振评分与预警分级")
    print("=" * 80)
    
    scorer = ResonanceScorer()
    
    # 模拟各维度数据
    gex = scorer.calculate_gex_score(-5e6, 2e6, True, 'IMPROVING')
    vix = scorer.calculate_vix_score(0.95, 'DOWN', 5.2)
    crypto = scorer.calculate_crypto_score(True, True, True, True)
    darkpool = scorer.calculate_darkpool_score(True, True, False, True, True)
    
    # 计算总分
    result = scorer.calculate_total_score(gex, vix, crypto, darkpool)
    
    print(f"\n共振总分: {result['total_score']}/{result['max_score']}")
    print(f"共振百分比: {result['resonance_pct']}%")
    print(f"预警级别: {result['alert_level']}")
    
    print(f"\n触发的条件:")
    for condition in result['trigger_conditions']:
        print(f"  - {condition}")


def example_hawkes_process():
    """示例3: Hawkes Process 自激抛售测算"""
    print("\n" + "=" * 80)
    print("示例3: Hawkes Process 自激抛售测算")
    print("=" * 80)
    
    scorer = ResonanceScorer()
    
    # 模拟恐慌抛售数据 (价格下跌伴随成交量激增)
    print("\n场景A: 恐慌抛售 (高相关性)")
    prices_panic = [-1.5, -2.0, -1.8, -2.5, -1.2, -1.9, -2.3, -1.7, -2.1, -1.6]
    volumes_panic = [2e6, 3e6, 2.8e6, 3.5e6, 2.2e6, 3.2e6, 3.8e6, 2.9e6, 3.3e6, 2.7e6]
    
    hawkes_panic = scorer.estimate_hawkes_branching_ratio(prices_panic, volumes_panic)
    print(f"  分支比: {hawkes_panic['branching_ratio']}")
    print(f"  状态: {hawkes_panic['state']}")
    print(f"  自激强度: {hawkes_panic['self_excitation_intensity']}%")
    print(f"  详情: {hawkes_panic['details']}")
    
    # 模拟正常波动数据 (低相关性)
    print("\n场景B: 正常波动 (低相关性)")
    prices_normal = [-0.5, -0.3, -0.2, -0.4, -0.1, -0.3, -0.2, -0.5, -0.1, -0.2]
    volumes_normal = [1e6, 1.1e6, 1.05e6, 1.2e6, 1.0e6, 1.15e6, 1.08e6, 1.25e6, 1.02e6, 1.1e6]
    
    hawkes_normal = scorer.estimate_hawkes_branching_ratio(prices_normal, volumes_normal)
    print(f"  分支比: {hawkes_normal['branching_ratio']}")
    print(f"  状态: {hawkes_normal['state']}")
    print(f"  自激强度: {hawkes_normal['self_excitation_intensity']}%")
    print(f"  详情: {hawkes_normal['details']}")


def example_signal_state_machine():
    """示例4: 信号触发状态机"""
    print("\n" + "=" * 80)
    print("示例4: 信号触发状态机")
    print("=" * 80)
    
    scorer = ResonanceScorer()
    sm = SignalStateMachine(cooldown_minutes=30)
    eastern = pytz.timezone('US/Eastern')
    
    # 准备共振结果
    gex = scorer.calculate_gex_score(-5e6, 2e6, True, 'IMPROVING')
    vix = scorer.calculate_vix_score(0.95, 'DOWN', 5.2)
    crypto = scorer.calculate_crypto_score(True, True, True, True)
    darkpool = scorer.calculate_darkpool_score(True, True, False, True, True)
    resonance = scorer.calculate_total_score(gex, vix, crypto, darkpool)
    
    now = datetime.now(eastern)
    
    # 第一次检查 - 应该触发
    print("\n【时间点1: 首次检测】")
    trigger1 = sm.check_and_trigger(resonance, now)
    print(f"  是否触发: {trigger1['should_alert']}")
    print(f"  原因: {trigger1['reason']}")
    print(f"  状态: {sm.current_state}")
    
    # 第二次检查 (5分钟后) - 应处于冷却期
    print("\n【时间点2: 5分钟后 (冷却期)】")
    later = now + timedelta(minutes=5)
    trigger2 = sm.check_and_trigger(resonance, later)
    print(f"  是否触发: {trigger2['should_alert']}")
    print(f"  原因: {trigger2['reason']}")
    print(f"  剩余冷却时间: {trigger2['cooldown_remaining']}分钟")
    
    # 第三次检查 (35分钟后) - 冷却期结束，可以再次触发
    print("\n【时间点3: 35分钟后 (冷却期结束)】")
    much_later = now + timedelta(minutes=35)
    trigger3 = sm.check_and_trigger(resonance, much_later)
    print(f"  是否触发: {trigger3['should_alert']}")
    print(f"  原因: {trigger3['reason']}")
    print(f"  累计告警次数: {len(sm.alert_history)}")
    
    # 查看状态摘要
    print("\n【状态机摘要】")
    summary = sm.get_state_summary()
    print(f"  当前状态: {summary['current_state']}")
    print(f"  总告警次数: {summary['total_alerts']}")
    print(f"  最近告警: {len(summary['recent_alerts'])}条")


def example_format_alert():
    """示例5: 格式化告警消息"""
    print("\n" + "=" * 80)
    print("示例5: 格式化告警消息")
    print("=" * 80)
    
    scorer = ResonanceScorer()
    eastern = pytz.timezone('US/Eastern')
    
    # 准备完整数据
    gex = scorer.calculate_gex_score(-5e6, 2e6, True, 'IMPROVING')
    vix = scorer.calculate_vix_score(0.95, 'DOWN', 5.2)
    crypto = scorer.calculate_crypto_score(True, True, True, True)
    darkpool = scorer.calculate_darkpool_score(True, True, False, True, True)
    resonance = scorer.calculate_total_score(gex, vix, crypto, darkpool)
    
    # Hawkes测算
    prices = [-0.5, -0.8, -1.2, -0.3, -0.6, -0.9, -1.5, -0.4, -0.7, -1.1]
    volumes = [1e6, 1.5e6, 2e6, 1.2e6, 1.8e6, 2.5e6, 3e6, 1.3e6, 2.2e6, 2.8e6]
    hawkes = scorer.estimate_hawkes_branching_ratio(prices, volumes)
    
    # 格式化消息
    now = datetime.now(eastern)
    message = format_alert_message(resonance, hawkes, now)
    
    print("\n生成的告警消息:")
    print("-" * 80)
    print(message)
    print("-" * 80)


if __name__ == '__main__':
    from datetime import timedelta
    
    # 配置日志
    import logging
    import sys
    
    # Windows控制台UTF-8支持
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 运行所有示例
    example_basic_scoring()
    example_total_resonance()
    example_hawkes_process()
    example_signal_state_machine()
    example_format_alert()
    
    print("\n" + "=" * 80)
    print("所有示例执行完毕!")
    print("=" * 80)
