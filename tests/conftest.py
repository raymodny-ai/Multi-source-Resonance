"""pytest 共享 fixtures"""
import os
import pytest
from pathlib import Path
import sys

# V2.5 P1: 在测试环境中放宽 OI 门控, 兼容历史测试数据
os.environ.setdefault('OI_GATE_THRESHOLD', '100')

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db_manager import DatabaseManager


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    """创建临时数据库路径"""
    db_file = tmp_path / "test_monitoring.db"
    return str(db_file)


@pytest.fixture
def db(tmp_path: Path) -> DatabaseManager:
    """创建临时数据库实例"""
    db_file = tmp_path / "test_monitoring.db"
    db_manager = DatabaseManager(db_path=str(db_file))
    yield db_manager
    # 清理
    db_manager.close()
