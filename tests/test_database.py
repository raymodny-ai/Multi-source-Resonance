#!/usr/bin/env python3
"""
多源共振监控系统 - 数据库功能测试

该脚本测试数据库管理器的所有核心功能：
1. GEX历史数据的插入和查询
2. 暗盘指标的CRUD操作
3. 加密衍生品数据管理
4. 信号警报的完整生命周期
5. 系统配置的读写
6. 数据库维护功能

使用方法:
    python tests/test_database.py
"""

import sys
from pathlib import Path
from datetime import datetime, date, timedelta
import time

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from database.db_manager import DatabaseManager
from utils.logger import getLogger

logger = getLogger('test_database')


def test_gex_operations(db: DatabaseManager) -> bool:
    """测试GEX历史操作
    
    Args:
        db: 数据库管理器实例
        
    Returns:
        bool: 所有测试通过返回True
    """
    logger.info("\n--- 测试GEX历史操作 ---")
    
    try:
        # 测试1: 插入GEX记录
        now = datetime.now()
        result = db.insert_gex_record(
            timestamp=now,
            gex_local=-1200000000.0,
            gex_calibrated=-1150000000.0,
            alpha_factor=0.958,
            put_wall_level=4500.0,
            flip_zone_lower=4480.0,
            flip_zone_upper=4520.0
        )
        
        assert result == True, "GEX插入失败"
        logger.info("[OK] GEX插入测试通过")
        
        # 等待一小段时间确保时间戳不同
        time.sleep(0.1)
        
        # 测试2: 插入第二条记录
        now2 = datetime.now()
        result2 = db.insert_gex_record(
            timestamp=now2,
            gex_local=-1100000000.0,
            gex_calibrated=-1050000000.0,
            alpha_factor=0.955
        )
        
        assert result2 == True, "第二条GEX记录插入失败"
        logger.info("[OK] 第二条GEX记录插入成功")
        
        # 测试3: 查询最新GEX
        latest = db.get_latest_gex()
        assert latest is not None, "查询最新GEX失败"
        assert abs(latest['gex_local'] - (-1100000000.0)) < 0.01, "最新GEX值不匹配"
        assert abs(latest['alpha_factor'] - 0.955) < 0.001, "alpha_factor不匹配"
        logger.info(f"[OK] GEX查询测试通过 (gex_local={latest['gex_local']})")
        
        # 测试4: 获取GEX历史
        history_df = db.get_gex_history(hours=24)
        assert len(history_df) >= 2, f"GEX历史记录数量不足: {len(history_df)}"
        logger.info(f"[OK] GEX历史查询测试通过 ({len(history_df)}条记录)")
        
        return True
        
    except AssertionError as e:
        logger.error(f"[FAIL] GEX测试失败: {e}")
        return False
    except Exception as e:
        logger.error(f"[ERROR] GEX测试异常: {e}", exc_info=True)
        return False


def test_dark_pool_operations(db: DatabaseManager) -> bool:
    """测试暗盘指标操作
    
    Args:
        db: 数据库管理器实例
        
    Returns:
        bool: 所有测试通过返回True
    """
    logger.info("\n--- 测试暗盘指标操作 ---")
    
    try:
        # 测试1: 插入暗盘指标
        today = date.today()
        result = db.insert_dark_pool_metrics(
            date=today,
            dix_value=46.8,
            chartexchange_short_ratio=47.2,
            stockgrid_20d_slope=0.85,
            stockgrid_60d_slope=0.92,
            stockgrid_divergence=True,
            dbmf_ma5_recovery=False,
            dix_signal=True,
            short_ratio_signal=True,
            stockgrid_signal=False,
            aggregated_signal=True
        )
        
        assert result == True, "暗盘指标插入失败"
        logger.info("[OK] 暗盘指标插入测试通过")
        
        # 测试2: 查询最新暗盘指标
        latest = db.get_latest_dark_pool_metrics()
        assert latest is not None, "查询最新暗盘指标失败"
        assert abs(latest['dix_value'] - 46.8) < 0.01, "DIX值不匹配"
        assert latest['stockgrid_divergence'] == True, "底背离标志不匹配"
        assert latest['aggregated_signal'] == True, "聚合信号不匹配"
        logger.info(f"[OK] 暗盘指标查询测试通过 (DIX={latest['dix_value']}%)")
        
        # 测试3: 获取暗盘历史
        history_df = db.get_dark_pool_history(days=30)
        assert len(history_df) >= 1, f"暗盘历史记录数量不足: {len(history_df)}"
        logger.info(f"[OK] 暗盘历史查询测试通过 ({len(history_df)}条记录)")
        
        return True
        
    except AssertionError as e:
        logger.error(f"[FAIL] 暗盘指标测试失败: {e}")
        return False
    except Exception as e:
        logger.error(f"[ERROR] 暗盘指标测试异常: {e}", exc_info=True)
        return False


def test_crypto_operations(db: DatabaseManager) -> bool:
    """测试加密衍生品操作
    
    Args:
        db: 数据库管理器实例
        
    Returns:
        bool: 所有测试通过返回True
    """
    logger.info("\n--- 测试加密衍生品操作 ---")
    
    try:
        # 测试1: 插入加密数据
        now = datetime.now()
        result = db.insert_crypto_derivatives(
            timestamp=now,
            btc_funding_rate=0.01,
            btc_oi=15000000000.0,
            oi_change_1h=-2.5,
            liquidation_spike=False,
            cryptoquant_elr=3.2,
            funding_anomaly=False,
            oi_crash=False,
            leverage_cleanup=False
        )
        
        assert result == True, "加密数据插入失败"
        logger.info("[OK] 加密数据插入测试通过")
        
        # 等待一小段时间
        time.sleep(0.1)
        
        # 测试2: 插入第二条记录（带异常标志）
        now2 = datetime.now()
        result2 = db.insert_crypto_derivatives(
            timestamp=now2,
            btc_funding_rate=-0.015,  # 负费率异常
            btc_oi=12000000000.0,
            oi_change_1h=-18.5,  # OI断崖下跌
            liquidation_spike=True,
            cryptoquant_elr=2.8,
            funding_anomaly=True,
            oi_crash=True,
            leverage_cleanup=True
        )
        
        assert result2 == True, "第二条加密数据插入失败"
        logger.info("[OK] 第二条加密数据插入成功（含异常标志）")
        
        # 测试3: 查询最新加密数据
        latest = db.get_latest_crypto_data()
        assert latest is not None, "查询最新加密数据失败"
        assert abs(latest['btc_funding_rate'] - (-0.015)) < 0.001, "资金费率不匹配"
        assert latest['funding_anomaly'] == True, "费率异常标志不匹配"
        assert latest['oi_crash'] == True, "OI崩溃标志不匹配"
        logger.info(f"[OK] 加密数据查询测试通过 (funding_rate={latest['btc_funding_rate']})")
        
        # 测试4: 获取加密历史
        history_df = db.get_crypto_history(hours=24)
        assert len(history_df) >= 2, f"加密历史记录数量不足: {len(history_df)}"
        logger.info(f"[OK] 加密历史查询测试通过 ({len(history_df)}条记录)")
        
        return True
        
    except AssertionError as e:
        logger.error(f"[FAIL] 加密数据测试失败: {e}")
        return False
    except Exception as e:
        logger.error(f"[ERROR] 加密数据测试异常: {e}", exc_info=True)
        return False


def test_signal_alert_operations(db: DatabaseManager) -> bool:
    """测试信号警报操作
    
    Args:
        db: 数据库管理器实例
        
    Returns:
        bool: 所有测试通过返回True
    """
    logger.info("\n--- 测试信号警报操作 ---")
    
    try:
        # 测试1: 插入LEVEL_1警报
        now = datetime.now()
        alert_id_1 = db.insert_signal_alert(
            trigger_time=now,
            total_score=2.5,
            gex_score=0.8,
            vix_score=0.5,
            crypto_score=0.7,
            darkpool_score=0.5,
            alert_level="LEVEL_1",
            hawkes_branching_ratio=0.35,
            details={"condition": "basic_resonance", "tickers": ["SPY"]}
        )
        
        assert alert_id_1 > 0, f"LEVEL_1警报插入失败 (返回ID: {alert_id_1})"
        logger.info(f"[OK] LEVEL_1警报插入测试通过 (ID: {alert_id_1})")
        
        # 等待一小段时间
        time.sleep(0.1)
        
        # 测试2: 插入LEVEL_3警报
        now2 = datetime.now()
        alert_id_2 = db.insert_signal_alert(
            trigger_time=now2,
            total_score=4.8,
            gex_score=1.5,
            vix_score=1.0,
            crypto_score=1.0,
            darkpool_score=1.5,
            alert_level="LEVEL_3",
            hawkes_branching_ratio=0.65,
            details={
                "condition": "strong_resonance",
                "tickers": ["SPY", "QQQ"],
                "gex_calibrated": -1150000000.0,
                "dix_value": 46.8
            }
        )
        
        assert alert_id_2 > 0, f"LEVEL_3警报插入失败 (返回ID: {alert_id_2})"
        logger.info(f"[OK] LEVEL_3警报插入测试通过 (ID: {alert_id_2})")
        
        # 测试3: 获取最近警报
        recent_alerts = db.get_recent_alerts(limit=5)
        assert len(recent_alerts) >= 2, f"最近警报数量不足: {len(recent_alerts)}"
        assert recent_alerts[0]['alert_level'] == "LEVEL_3", "最新警报级别不匹配"
        assert isinstance(recent_alerts[0]['details'], dict), "details未正确解析为字典"
        logger.info(f"[OK] 最近警报查询测试通过 ({len(recent_alerts)}条记录)")
        
        # 测试4: 获取未确认警报
        unack_alerts = db.get_unacknowledged_alerts()
        assert len(unack_alerts) >= 2, f"未确认警报数量不足: {len(unack_alerts)}"
        logger.info(f"[OK] 未确认警报查询测试通过 ({len(unack_alerts)}条记录)")
        
        # 测试5: 标记警报为已确认
        ack_result = db.mark_alert_acknowledged(alert_id_1)
        assert ack_result == True, "标记警报确认失败"
        logger.info(f"[OK] 警报确认标记测试通过 (ID: {alert_id_1})")
        
        # 测试6: 验证确认后未确认列表减少
        unack_alerts_after = db.get_unacknowledged_alerts()
        assert len(unack_alerts_after) == len(unack_alerts) - 1, "确认后未确认列表未更新"
        logger.info(f"[OK] 警报确认状态验证通过 (剩余{len(unack_alerts_after)}条未确认)")
        
        return True
        
    except AssertionError as e:
        logger.error(f"[FAIL] 信号警报测试失败: {e}")
        return False
    except Exception as e:
        logger.error(f"[ERROR] 信号警报测试异常: {e}", exc_info=True)
        return False


def test_config_operations(db: DatabaseManager) -> bool:
    """测试系统配置操作
    
    Args:
        db: 数据库管理器实例
        
    Returns:
        bool: 所有测试通过返回True
    """
    logger.info("\n--- 测试系统配置操作 ---")
    
    try:
        # 测试1: 读取默认配置
        alpha = db.get_config_value('alpha_factor')
        assert alpha is not None, "无法读取alpha_factor配置"
        logger.info(f"[OK] 读取默认配置成功 (alpha_factor={alpha})")
        
        # 测试2: 更新配置
        update_result = db.set_config_value(
            'test_config',
            'test_value',
            '测试配置项'
        )
        assert update_result == True, "配置更新失败"
        logger.info("[OK] 配置更新测试通过")
        
        # 测试3: 读取更新的配置
        test_value = db.get_config_value('test_config')
        assert test_value == 'test_value', "读取的配置值不匹配"
        logger.info(f"[OK] 配置读取验证通过 (test_config={test_value})")
        
        # 测试4: 更新alpha_factor
        alpha_update = db.update_alpha_factor(1.05)
        assert alpha_update == True, "alpha_factor更新失败"
        
        new_alpha = db.get_config_value('alpha_factor')
        assert new_alpha == '1.05', f"alpha_factor更新后值不匹配: {new_alpha}"
        logger.info(f"[OK] alpha_factor更新测试通过 (新值={new_alpha})")
        
        # 测试5: 读取不存在的配置（使用默认值）
        nonexistent = db.get_config_value('nonexistent_key', default='default_val')
        assert nonexistent == 'default_val', "默认值返回不正确"
        logger.info("[OK] 默认值测试通过")
        
        return True
        
    except AssertionError as e:
        logger.error(f"[FAIL] 配置操作测试失败: {e}")
        return False
    except Exception as e:
        logger.error(f"[ERROR] 配置操作测试异常: {e}", exc_info=True)
        return False


def test_database_maintenance(db: DatabaseManager) -> bool:
    """测试数据库维护功能
    
    Args:
        db: 数据库管理器实例
        
    Returns:
        bool: 所有测试通过返回True
    """
    logger.info("\n--- 测试数据库维护功能 ---")
    
    try:
        # 测试1: 获取数据库统计信息
        stats = db.get_database_stats()
        assert 'gex_history' in stats, "统计信息缺少gex_history"
        assert 'dark_pool_metrics' in stats, "统计信息缺少dark_pool_metrics"
        assert 'crypto_derivatives' in stats, "统计信息缺少crypto_derivatives"
        assert 'signal_alerts' in stats, "统计信息缺少signal_alerts"
        assert 'database_size_mb' in stats, "统计信息缺少数据库大小"
        
        logger.info(f"[OK] 数据库统计信息查询测试通过")
        logger.info(f"   - GEX记录数: {stats['gex_history']}")
        logger.info(f"   - 暗盘记录数: {stats['dark_pool_metrics']}")
        logger.info(f"   - 加密记录数: {stats['crypto_derivatives']}")
        logger.info(f"   - 警报记录数: {stats['signal_alerts']}")
        logger.info(f"   - 数据库大小: {stats['database_size_mb']} MB")
        
        # 测试2: VACUUM清理
        vacuum_result = db.vacuum_database()
        assert vacuum_result == True, "VACUUM清理失败"
        logger.info("[OK] 数据库碎片清理测试通过")
        
        # 测试3: 备份数据库
        backup_path = db.backup_database()
        assert Path(backup_path).exists(), f"备份文件不存在: {backup_path}"
        assert Path(backup_path).stat().st_size > 0, "备份文件大小为0"
        logger.info(f"[OK] 数据库备份测试通过 (备份路径: {backup_path})")
        
        return True
        
    except AssertionError as e:
        logger.error(f"[FAIL] 数据库维护测试失败: {e}")
        return False
    except Exception as e:
        logger.error(f"[ERROR] 数据库维护测试异常: {e}", exc_info=True)
        return False


def test_context_manager(db_path: str) -> bool:
    """测试上下文管理器支持
    
    Args:
        db_path: 数据库文件路径
        
    Returns:
        bool: 测试通过返回True
    """
    logger.info("\n--- 测试上下文管理器 ---")
    
    try:
        # 使用with语句
        with DatabaseManager(db_path=db_path) as db:
            # 在上下文中执行操作
            result = db.insert_gex_record(
                timestamp=datetime.now(),
                gex_local=-1000000000.0
            )
            assert result == True, "上下文管理器中插入失败"
        
        logger.info("[OK] 上下文管理器测试通过")
        return True
        
    except Exception as e:
        logger.error(f"[ERROR] 上下文管理器测试失败: {e}", exc_info=True)
        return False


def run_all_tests():
    """运行所有数据库测试"""
    logger.info("=" * 70)
    logger.info("开始运行数据库功能测试套件")
    logger.info("=" * 70)
    
    # 使用内存数据库进行测试（快速且不影响实际数据）
    test_db_path = ":memory:"
    
    all_passed = True
    test_results = {}
    
    try:
        # 创建测试数据库
        db = DatabaseManager(db_path=test_db_path)
        logger.info("[OK] 测试数据库初始化成功 (内存模式)")
        
        # 运行各项测试
        tests = [
            ("GEX历史操作", lambda: test_gex_operations(db)),
            ("暗盘指标操作", lambda: test_dark_pool_operations(db)),
            ("加密衍生品操作", lambda: test_crypto_operations(db)),
            ("信号警报操作", lambda: test_signal_alert_operations(db)),
            ("系统配置操作", lambda: test_config_operations(db)),
            ("数据库维护", lambda: test_database_maintenance(db)),
        ]
        
        for test_name, test_func in tests:
            result = test_func()
            test_results[test_name] = result
            all_passed = all_passed and result
        
        # 单独测试上下文管理器（需要新的数据库实例）
        context_result = test_context_manager(test_db_path)
        test_results["上下文管理器"] = context_result
        all_passed = all_passed and context_result
        
        # 打印测试结果汇总
        logger.info("\n" + "=" * 70)
        logger.info("测试结果汇总:")
        logger.info("=" * 70)
        
        for test_name, result in test_results.items():
            status = "[PASS]" if result else "[FAIL]"
            logger.info(f"  {test_name}: {status}")
        
        logger.info("=" * 70)
        
        if all_passed:
            logger.info("[SUCCESS] 所有数据库测试通过！")
            logger.info("=" * 70)
            return 0
        else:
            logger.error("[FAIL] 部分测试失败，请检查日志")
            logger.info("=" * 70)
            return 1
            
    except Exception as e:
        logger.error(f"[ERROR] 测试执行异常: {e}", exc_info=True)
        logger.info("=" * 70)
        return 1
        
    finally:
        if 'db' in locals():
            db.close()
            logger.info("测试数据库连接已关闭")


if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)
