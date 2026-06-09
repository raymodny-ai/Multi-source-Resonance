"""
Phase 7 系统集成与调度器 - 快速验证脚本

简化版本，只验证核心功能
"""

import sys
from utils.fallback_manager import FallbackManager, handle_fetch_errors


def test_imports():
    """测试模块导入"""
    print("=" * 60)
    print("Phase 7 快速验证")
    print("=" * 60)
    
    print("\n[1] 测试模块导入:")
    try:
        from main_scheduler import MainScheduler, create_and_start_scheduler
        print("  - MainScheduler: OK")
        
        from utils.fallback_manager import FallbackManager, handle_fetch_errors
        print("  - FallbackManager: OK")
        
        print("  [PASS]")
        return True
    except Exception as e:
        print(f"  [FAIL] {e}")
        return False


def test_fallback_logic():
    """测试降级逻辑"""
    print("\n[2] 测试FallbackManager降级逻辑:")
    
    fallback = FallbackManager()
    
    # FULL模式
    result = fallback.handle_darkpool_fallback(True, True, True)
    assert result['mode'] == 'FULL'
    print("  - FULL模式: OK")
    
    # PARTIAL模式
    result = fallback.handle_darkpool_fallback(True, False, True)
    assert result['mode'] == 'PARTIAL'
    print("  - PARTIAL模式: OK")
    
    # DEGRADED模式
    result = fallback.handle_darkpool_fallback(False, False, False)
    assert result['mode'] == 'DEGRADED'
    print("  - DEGRADED模式: OK")
    
    print("  [PASS]")
    return True


def test_circuit_breaker():
    """测试熔断机制"""
    print("\n[3] 测试熔断机制:")
    
    fallback = FallbackManager()
    
    # 记录5次失败
    for i in range(5):
        fallback.record_failure('test_module')
    
    # 检查是否熔断
    status = fallback.get_module_status('test_module')
    assert status['is_circuit_broken'] == True
    print("  - 熔断触发: OK")
    
    # 重置
    fallback.reset_failure_count('test_module')
    status = fallback.get_module_status('test_module')
    assert status['status'] == 'HEALTHY'
    print("  - 熔断解除: OK")
    
    print("  [PASS]")
    return True


def test_scheduler_structure():
    """测试调度器结构（不启动）"""
    print("\n[4] 测试MainScheduler结构:")
    
    try:
        from main_scheduler import MainScheduler
        
        # 创建实例但不启动
        scheduler = MainScheduler()
        print("  - 实例化: OK")
        
        # 检查关键组件
        assert hasattr(scheduler, 'scheduler')
        assert hasattr(scheduler, 'db')
        assert hasattr(scheduler, 'fallback_manager')
        print("  - 组件初始化: OK")
        
        # 设置任务（不启动）
        scheduler.setup_intraday_tasks()
        scheduler.setup_afterhours_tasks()
        
        jobs = scheduler.scheduler.get_jobs()
        print(f"  - 任务数量: {len(jobs)}个")
        
        # 关闭
        scheduler.shutdown()
        print("  - 优雅关闭: OK")
        
        print("  [PASS]")
        return True
    except Exception as e:
        print(f"  [FAIL] {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """运行所有测试"""
    results = []
    
    results.append(test_imports())
    results.append(test_fallback_logic())
    results.append(test_circuit_breaker())
    results.append(test_scheduler_structure())
    
    print("\n" + "=" * 60)
    if all(results):
        print("[SUCCESS] 所有测试通过!")
        print("=" * 60)
        print("\n验证完成:")
        print("[OK] 模块导入正常")
        print("[OK] FallbackManager降级逻辑正确")
        print("[OK] 熔断机制工作正常")
        print("[OK] MainScheduler可正常初始化和配置")
        print("\n系统已准备好投入运行!")
        return 0
    else:
        print("[ERROR] 部分测试失败")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
