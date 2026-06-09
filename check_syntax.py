"""
简单的语法检查脚本 - 验证所有fetcher模块的Python语法是否正确
"""

import py_compile
import sys
from pathlib import Path


def check_syntax(file_path: str) -> bool:
    """检查单个文件的Python语法
    
    Args:
        file_path: Python文件路径
        
    Returns:
        bool: True表示语法正确
    """
    try:
        py_compile.compile(file_path, doraise=True)
        print(f"✅ {Path(file_path).name}: 语法正确")
        return True
    except py_compile.PyCompileError as e:
        print(f"❌ {Path(file_path).name}: 语法错误 - {e}")
        return False


def main():
    """主函数"""
    print("=" * 80)
    print("多源共振监控系统 - Phase 2 语法检查")
    print("=" * 80)
    print()
    
    # 获取data_fetchers目录下的所有.py文件
    fetchers_dir = Path(__file__).parent / "data_fetchers"
    py_files = sorted(fetchers_dir.glob("*.py"))
    
    if not py_files:
        print(f"❌ 未找到任何Python文件: {fetchers_dir}")
        return 1
    
    print(f"发现 {len(py_files)} 个Python文件\n")
    
    results = []
    for py_file in py_files:
        result = check_syntax(str(py_file))
        results.append(result)
    
    print()
    print("=" * 80)
    passed = sum(results)
    total = len(results)
    
    if passed == total:
        print(f"🎉 所有 {total} 个文件语法检查通过！")
    else:
        print(f"⚠️  {passed}/{total} 个文件通过，{total - passed} 个文件存在语法错误")
    
    print("=" * 80)
    
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
