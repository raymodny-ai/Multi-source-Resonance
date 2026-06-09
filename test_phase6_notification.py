"""
Phase 6 通知模块测试脚本
"""
from notification.alert_sender import AlertSender, create_alert_sender
from datetime import datetime

def test_import():
    """测试模块导入"""
    print("[PASS] 模块导入成功")
    return True

def test_instantiation():
    """测试实例化"""
    sender = create_alert_sender()
    print("[PASS] AlertSender实例化成功")
    return True

def test_format_level3_alert():
    """测试LEVEL 3告警格式化"""
    sender = AlertSender()
    
    # 构造测试数据
    test_resonance = {
        'total_score': 95,
        'max_score': 100,
        'dimension_scores': {
            'gex': {
                'details': '已翻正至+$150M',
                'state': 'POSITIVE'
            },
            'vix': {
                'details': '回归Contango(0.98)',
                'state': 'CONTANGO'
            },
            'darkpool': {
                'details': '强吸筹确认(3/3指标触发)',
                'state': 'STRONG_ACCUMULATION'
            },
            'crypto': {
                'details': '去杠杆完成',
                'state': 'CLEANUP_COMPLETE'
            }
        },
        'trigger_conditions': [
            'GEX > $100M',
            'VIX < 1.0',
            '暗盘吸筹强度 > 45',
            '加密杠杆率 < 2%'
        ]
    }
    
    test_hawkes = {
        'details': '分支比μ=0.85，自激效应显著'
    }
    
    current_time = datetime.now()
    put_wall_range = (5800, 5850)
    
    # 生成格式化消息
    result = sender.format_level3_alert(
        test_resonance, 
        test_hawkes, 
        current_time, 
        put_wall_range
    )
    
    # 验证关键内容
    assert 'SYSTEM ALERT' in result, "缺少SYSTEM ALERT标识"
    assert '95 / 100' in result, "缺少共振得分"
    assert 'Put Wall [5800 - 5850]' in result, "缺少Put Wall信息"
    assert '已翻正至+$150M' in result, "缺少GEX详情"
    assert '回归Contango(0.98)' in result, "缺少VIX详情"
    assert '强吸筹确认(3/3指标触发)' in result, "缺少暗盘详情"
    assert '去杠杆完成' in result, "缺少加密详情"
    assert '分支比μ=0.85' in result, "缺少Hawkes分析"
    
    print("[PASS] LEVEL 3告警格式化测试通过")
    print("\n生成的消息预览(前500字符):")
    print("=" * 80)
    # Windows控制台可能不支持emoji,使用replace处理
    preview = result[:500].replace('🚨', '[ALERT]').replace('⏰', '[TIME]').replace('📊', '[DATA]').replace('🏛️', '[DARKPOOL]').replace('🌐', '[CRYPTO]').replace('🤖', '[AI]').replace('✅', '[OK]').replace('🟢', '[GREEN]').replace('🟡', '[YELLOW]').replace('🔴', '[RED]')
    try:
        print(preview)
    except UnicodeEncodeError:
        print(preview.encode('gbk', 'ignore').decode('gbk'))
    print("...")
    print("=" * 80)
    
    return True

def test_config_loading():
    """测试配置加载"""
    from config.settings import Config
    
    # 验证配置字段存在
    assert hasattr(Config, 'SMTP_SERVER'), "缺少SMTP_SERVER配置"
    assert hasattr(Config, 'SMTP_PORT'), "缺少SMTP_PORT配置"
    assert hasattr(Config, 'EMAIL_SENDER'), "缺少EMAIL_SENDER配置"
    assert hasattr(Config, 'TELEGRAM_BOT_TOKEN'), "缺少TELEGRAM_BOT_TOKEN配置"
    assert hasattr(Config, 'DISCORD_WEBHOOK_URL'), "缺少DISCORD_WEBHOOK_URL配置"
    
    print("[PASS] 配置加载测试通过")
    print(f"  SMTP服务器: {Config.SMTP_SERVER}")
    print(f"  SMTP端口: {Config.SMTP_PORT}")
    print(f"  Discord Webhook: {'已配置' if Config.DISCORD_WEBHOOK_URL else '未配置'}")
    
    return True

if __name__ == "__main__":
    print("=" * 80)
    print("Phase 6 通知与展示层 - 功能验证")
    print("=" * 80)
    print()
    
    tests = [
        ("模块导入", test_import),
        ("实例化", test_instantiation),
        ("配置加载", test_config_loading),
        ("LEVEL 3告警格式化", test_format_level3_alert),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            print(f"\n[{test_name}]")
            if test_func():
                passed += 1
            else:
                failed += 1
                print(f"[FAIL] {test_name} 失败")
        except Exception as e:
            failed += 1
            print(f"[ERROR] {test_name} 异常: {e}")
    
    print("\n" + "=" * 80)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 80)
    
    if failed == 0:
        print("\n[PASS] Phase 6 所有测试通过!")
    else:
        print(f"\n[FAIL] 有 {failed} 个测试失败")
