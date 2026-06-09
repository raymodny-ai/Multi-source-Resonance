#!/usr/bin/env python3
"""
多源共振监控系统 - 数据库初始化脚本

该脚本用于：
1. 创建SQLite数据库文件
2. 初始化所有表结构、索引和视图
3. 插入默认配置数据
4. 验证表结构完整性

使用方法:
    python database/init_db.py
"""

import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from database.db_manager import DatabaseManager
from utils.logger import getLogger

logger = getLogger('init_db')


def verify_table_structure(db: DatabaseManager) -> bool:
    """验证数据库表结构完整性
    
    Args:
        db: 数据库管理器实例
        
    Returns:
        bool: 所有表都存在返回True，否则返回False
    """
    required_tables = [
        'gex_history',
        'dark_pool_metrics',
        'crypto_derivatives',
        'signal_alerts',
        'system_config'
    ]
    
    all_exist = True
    
    for table in required_tables:
        cursor = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,)
        )
        
        if cursor.fetchone():
            logger.info(f"[OK] 表 {table} 创建成功")
        else:
            logger.error(f"[FAIL] 表 {table} 创建失败")
            all_exist = False
    
    return all_exist


def verify_indexes(db: DatabaseManager) -> bool:
    """验证索引是否创建成功
    
    Args:
        db: 数据库管理器实例
        
    Returns:
        bool: 所有索引都存在返回True，否则返回False
    """
    required_indexes = [
        'idx_gex_timestamp',
        'idx_darkpool_date',
        'idx_crypto_timestamp',
        'idx_alert_time',
        'idx_alert_level'
    ]
    
    all_exist = True
    
    for index in required_indexes:
        cursor = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            (index,)
        )
        
        if cursor.fetchone():
            logger.debug(f"[OK] 索引 {index} 创建成功")
        else:
            logger.warning(f"[WARN] 索引 {index} 不存在")
            all_exist = False
    
    return all_exist


def verify_views(db: DatabaseManager) -> bool:
    """验证视图是否创建成功
    
    Args:
        db: 数据库管理器实例
        
    Returns:
        bool: 所有视图都存在返回True，否则返回False
    """
    required_views = [
        'v_latest_gex',
        'v_latest_darkpool',
        'v_latest_crypto',
        'v_unacknowledged_alerts'
    ]
    
    all_exist = True
    
    for view in required_views:
        cursor = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='view' AND name=?",
            (view,)
        )
        
        if cursor.fetchone():
            logger.debug(f"[OK] 视图 {view} 创建成功")
        else:
            logger.warning(f"[WARN] 视图 {view} 不存在")
            all_exist = False
    
    return all_exist


def verify_default_config(db: DatabaseManager) -> bool:
    """验证默认配置是否正确插入
    
    Args:
        db: 数据库管理器实例
        
    Returns:
        bool: 所有默认配置都存在返回True，否则返回False
    """
    required_configs = ['alpha_factor', 'last_dix_update', 'db_version']
    
    all_exist = True
    
    for key in required_configs:
        value = db.get_config_value(key)
        
        if value is not None:
            logger.debug(f"[OK] 配置 {key}={value}")
        else:
            logger.warning(f"[WARN] 配置 {key} 不存在")
            all_exist = False
    
    return all_exist


def main():
    """初始化数据库主函数"""
    logger.info("=" * 60)
    logger.info("开始初始化多源共振监控系统数据库")
    logger.info("=" * 60)
    
    db = None
    
    try:
        # 创建数据库管理器（会自动初始化）
        db = DatabaseManager()
        logger.info("[OK] 数据库连接建立成功")
        
        # 验证表结构
        logger.info("\n--- 验证表结构 ---")
        tables_ok = verify_table_structure(db)
        
        # 验证索引
        logger.info("\n--- 验证索引 ---")
        indexes_ok = verify_indexes(db)
        
        # 验证视图
        logger.info("\n--- 验证视图 ---")
        views_ok = verify_views(db)
        
        # 验证默认配置
        logger.info("\n--- 验证默认配置 ---")
        config_ok = verify_default_config(db)
        
        # 获取数据库统计信息
        logger.info("\n--- 数据库统计信息 ---")
        stats = db.get_database_stats()
        for table, count in stats.items():
            if table != 'database_size_bytes' and table != 'database_size_mb':
                logger.info(f"  {table}: {count} 条记录")
        
        logger.info(f"  数据库大小: {stats.get('database_size_mb', 0)} MB")
        
        # 总结
        logger.info("\n" + "=" * 60)
        if tables_ok and indexes_ok and views_ok and config_ok:
            logger.info("[SUCCESS] 数据库初始化成功！所有组件验证通过")
            logger.info("=" * 60)
            return 0
        else:
            logger.error("[FAIL] 数据库初始化完成，但部分组件验证失败")
            logger.error("=" * 60)
            return 1
            
    except Exception as e:
        logger.error(f"[ERROR] 数据库初始化失败: {e}", exc_info=True)
        logger.error("=" * 60)
        return 1
        
    finally:
        if db:
            db.close()
            logger.info("数据库连接已关闭")


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
