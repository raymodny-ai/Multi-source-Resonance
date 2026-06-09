"""
项目基础架构验证脚本

该脚本用于验证Phase 1基础架构是否正确创建，包括：
- 目录结构检查
- 关键文件存在性检查
- Python版本检查
- 依赖包导入测试
- 日志模块功能测试
"""

import sys
from pathlib import Path


def check_python_version():
    """检查Python版本是否符合要求"""
    print("=" * 60)
    print("1. Python版本检查")
    print("=" * 60)
    
    version = sys.version_info
    print(f"当前Python版本: {version.major}.{version.minor}.{version.micro}")
    
    if version.major >= 3 and version.minor >= 10:
        print("✓ Python版本符合要求 (>= 3.10)")
        return True
    else:
        print("✗ Python版本不符合要求，需要 >= 3.10")
        return False


def check_directory_structure():
    """检查目录结构是否完整"""
    print("\n" + "=" * 60)
    print("2. 目录结构检查")
    print("=" * 60)
    
    required_dirs = [
        'data_fetchers',
        'quant_logic',
        'signal_engine',
        'notification',
        'utils',
        'tests',
        'config',
        'database',
        'logs',
    ]
    
    base_path = Path(__file__).parent
    all_exist = True
    
    for dir_name in required_dirs:
        dir_path = base_path / dir_name
        if dir_path.exists() and dir_path.is_dir():
            print(f"✓ {dir_name}/")
        else:
            print(f"✗ {dir_name}/ - 缺失")
            all_exist = False
    
    return all_exist


def check_files():
    """检查关键文件是否存在"""
    print("\n" + "=" * 60)
    print("3. 关键文件检查")
    print("=" * 60)
    
    required_files = [
        'requirements.txt',
        'config/__init__.py',
        'config/settings.py',
        'config/.env.example',
        'utils/__init__.py',
        'utils/logger.py',
        'utils/exceptions.py',
        'data_fetchers/__init__.py',
        'quant_logic/__init__.py',
        'signal_engine/__init__.py',
        'notification/__init__.py',
        'tests/__init__.py',
        'database/__init__.py',
    ]
    
    base_path = Path(__file__).parent
    all_exist = True
    
    for file_name in required_files:
        file_path = base_path / file_name
        if file_path.exists() and file_path.is_file():
            print(f"✓ {file_name}")
        else:
            print(f"✗ {file_name} - 缺失")
            all_exist = False
    
    return all_exist


def test_imports():
    """测试核心模块导入"""
    print("\n" + "=" * 60)
    print("4. 模块导入测试")
    print("=" * 60)
    
    modules_to_test = [
        ('config.settings', '配置管理模块'),
        ('utils.logger', '日志模块'),
        ('utils.exceptions', '异常模块'),
    ]
    
    all_success = True
    
    for module_name, description in modules_to_test:
        try:
            __import__(module_name)
            print(f"✓ {description} ({module_name})")
        except ImportError as e:
            print(f"✗ {description} ({module_name}) - 导入失败: {e}")
            all_success = False
    
    return all_success


def test_logger():
    """测试日志模块功能"""
    print("\n" + "=" * 60)
    print("5. 日志模块功能测试")
    print("=" * 60)
    
    try:
        from utils.logger import getLogger
        
        # 创建测试logger
        logger = getLogger('test_verification')
        
        # 测试各级别日志
        logger.debug('这是一条DEBUG级别的测试日志')
        logger.info('这是一条INFO级别的测试日志')
        logger.warning('这是一条WARNING级别的测试日志')
        logger.error('这是一条ERROR级别的测试日志')
        
        print("✓ 日志模块功能正常")
        print("  - 日志已写入 logs/app_*.log")
        print("  - 错误日志已写入 logs/error_*.log")
        return True
        
    except Exception as e:
        print(f"✗ 日志模块测试失败: {e}")
        return False


def test_exceptions():
    """测试自定义异常"""
    print("\n" + "=" * 60)
    print("6. 自定义异常测试")
    print("=" * 60)
    
    try:
        from utils.exceptions import (
            DataFetchError,
            CalculationError,
            SignalTriggerError,
            DatabaseError,
        )
        
        # 测试异常创建和属性
        exc = DataFetchError(
            "测试错误",
            error_code="TEST_ERROR",
            details={"test": "value"}
        )
        
        assert exc.error_code == "TEST_ERROR"
        assert exc.details == {"test": "value"}
        assert "TEST_ERROR" in str(exc)
        
        print("✓ 自定义异常功能正常")
        print(f"  - 异常类: DataFetchError, CalculationError, SignalTriggerError, DatabaseError")
        print(f"  - 异常属性: error_code, details, message")
        return True
        
    except Exception as e:
        print(f"✗ 自定义异常测试失败: {e}")
        return False


def main():
    """主验证函数"""
    print("\n" + "🔍 多源共振监控系统 - Phase 1 基础架构验证")
    print("=" * 60)
    
    results = []
    
    # 执行各项检查
    results.append(("Python版本", check_python_version()))
    results.append(("目录结构", check_directory_structure()))
    results.append(("关键文件", check_files()))
    results.append(("模块导入", test_imports()))
    results.append(("日志功能", test_logger()))
    results.append(("异常系统", test_exceptions()))
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("验证结果汇总")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{name:15s}: {status}")
    
    print("-" * 60)
    print(f"总计: {passed}/{total} 项通过")
    
    if passed == total:
        print("\n🎉 所有验证通过！Phase 1 基础架构创建成功！")
        print("\n下一步:")
        print("1. 复制 config/.env.example 为 config/.env")
        print("2. 在 config/.env 中填写您的API密钥")
        print("3. 运行 pip install -r requirements.txt 安装依赖")
        print("4. 继续开发Phase 2功能模块")
    else:
        print("\n⚠️  部分验证失败，请检查上述错误信息")
    
    print("=" * 60 + "\n")
    
    return passed == total


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
