"""
多源共振监控系统 - 数据库模块

负责数据存储和管理，包括：
- SQLite数据库操作
- 历史信号记录
- 性能指标存储

主要类:
    DatabaseManager: SQLite数据库管理器(单例模式)

使用示例:
    from database import DatabaseManager
    
    db = DatabaseManager()
    latest_gex = db.get_latest_gex()
    db.close()
"""

from database.db_manager import DatabaseManager

__all__ = ['DatabaseManager']
