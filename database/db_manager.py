"""
多源共振监控系统 - 数据库管理器模块

提供SQLite数据库的完整CRUD操作支持，包括：
- GEX历史数据管理
- 暗盘指标存储
- 加密衍生品数据持久化
- 信号警报记录
- 系统配置管理

使用单例模式确保全局唯一数据库连接，支持WAL模式提升并发性能。

使用示例:
    from database.db_manager import DatabaseManager
    
    db = DatabaseManager()
    
    # 插入GEX记录
    db.insert_gex_record(
        timestamp=datetime.now(),
        gex_local=-1200000000.0,
        gex_calibrated=-1150000000.0
    )
    
    # 查询最新数据
    latest_gex = db.get_latest_gex()
    
    db.close()
"""

import sqlite3
import pandas as pd
import json
from pathlib import Path
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from utils.logger import getLogger
from utils.exceptions import DatabaseError
from config.settings import Config

logger = getLogger('database_manager')


class DatabaseManager:
    """SQLite数据库管理器(单例模式)
    
    提供线程安全的数据库访问接口，自动管理连接生命周期。
    所有写操作都包含事务管理，确保数据一致性。
    
    Attributes:
        db_path: 数据库文件路径
        connection: SQLite数据库连接对象
        
    Examples:
        >>> db = DatabaseManager()
        >>> with db:
        ...     db.insert_gex_record(...)
        >>> db.close()
    """
    
    _instance: Optional['DatabaseManager'] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        """单例模式实现"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, db_path: str = None):
        """初始化数据库连接
        
        Args:
            db_path: 数据库文件路径，默认从config.settings读取
            
        Raises:
            DatabaseError: 数据库初始化失败时抛出
        """
        if self._initialized:
            return
        
        # 确保从config读取,提供默认值
        from config.settings import Config
        self.db_path = db_path or getattr(Config, 'DATABASE_PATH', './database/monitoring.db')
        
        # 确保父目录存在
        from pathlib import Path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        self.connection = None
        self._initialize_db()
        DatabaseManager._initialized = True
        logger.info(f"数据库管理器初始化完成: {self.db_path}")
    
    def _initialize_db(self):
        """初始化数据库连接并创建表结构
        
        启用WAL模式提升并发读写性能，从schema.sql加载表定义。
        
        Raises:
            DatabaseError: 数据库连接或表创建失败时抛出
        """
        try:
            # 确保数据库目录存在
            db_dir = Path(self.db_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)
            
            # 建立数据库连接
            self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
            self.connection.row_factory = sqlite3.Row  # 支持字典式访问
            
            # 启用WAL模式提升并发性能
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA busy_timeout=5000")  # 5秒超时
            
            # 创建表结构
            self._create_tables()
            
            # v2.1 迁移: 为现有数据库添加暗盘预处理列
            self._migrate_v21_darkpool()

            # v2.3 迁移: 为 gex_snapshots 添加数据质量验证列
            self._migrate_gex_quality()
            
            logger.info(f"数据库初始化成功 (WAL模式): {self.db_path}")
            
        except sqlite3.Error as e:
            error_msg = f"数据库初始化失败: {e}"
            logger.error(error_msg)
            raise DatabaseError(
                error_code="DB_INIT_FAILED",
                details={"db_path": self.db_path, "error": str(e)}
            )
    
    def _create_tables(self):
        """从schema.sql创建所有表、索引和视图
        
        Raises:
            DatabaseError: schema文件读取或执行失败时抛出
        """
        try:
            schema_path = Path(__file__).parent / "schema.sql"
            
            if not schema_path.exists():
                raise FileNotFoundError(f"Schema文件不存在: {schema_path}")
            
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema_sql = f.read()
            
            self.connection.executescript(schema_sql)
            self.connection.commit()
            
            logger.info("数据库表结构创建成功")
            
        except Exception as e:
            error_msg = f"创建数据库表失败: {e}"
            logger.error(error_msg)
            raise DatabaseError(
                error_code="DB_CREATE_TABLES_FAILED",
                details={"error": str(e)}
            )
    
    def _migrate_v21_darkpool(self):
        """v2.1 迁移: 为现有数据库添加暗盘预处理列

        使用 ALTER TABLE ADD COLUMN 添加新列,
        如果列已存在则忽略错误 (SQLite 不支持 IF NOT EXISTS for ADD COLUMN)
        """
        new_columns = [
            ('v_net', 'REAL'),
            ('ema_fast_5', 'REAL'),
            ('ema_slow_20', 'REAL'),
            ('zero_cross_signal', 'TEXT'),
            ('momentum_reversal_signal', 'TEXT'),
        ]
        for col_name, col_type in new_columns:
            try:
                self.connection.execute(
                    f"ALTER TABLE dark_pool_metrics ADD COLUMN {col_name} {col_type}"
                )
                logger.info(f"v2.1 迁移: 添加列 dark_pool_metrics.{col_name}")
            except sqlite3.OperationalError:
                pass  # 列已存在, 跳过
        self.connection.commit()

    def _migrate_gex_quality(self):
        """v2.3 迁移: 为 gex_snapshots 添加数据质量验证列 (GEXDataQualityValidator 输出)

        新增列:
            quality_score:      综合质量分 (0-1, < 0.5 视为 invalid)
            data_lag_seconds:   snapshot timestamp 与当前时间的延迟 (秒)
            oi_coverage_pct:    OI 覆盖率 (与 yfinance 期权链作免费基准, 仅 SPY/QQQ/IWM 等)
        """
        new_columns = [
            ('quality_score', 'REAL DEFAULT 1.0'),
            ('data_lag_seconds', 'INTEGER'),
            ('oi_coverage_pct', 'REAL'),
        ]
        for col_name, col_type in new_columns:
            try:
                self.connection.execute(
                    f"ALTER TABLE gex_snapshots ADD COLUMN {col_name} {col_type}"
                )
                logger.info(f"v2.3 迁移: 添加列 gex_snapshots.{col_name}")
            except sqlite3.OperationalError:
                pass  # 列已存在, 跳过
        self.connection.commit()

    @contextmanager
    def _get_cursor(self):
        """获取游标的上下文管理器，自动处理事务提交/回滚
        
        Yields:
            sqlite3.Cursor: 数据库游标对象
            
        Examples:
            >>> with self._get_cursor() as cursor:
            ...     cursor.execute("INSERT INTO ...")
        """
        cursor = self.connection.cursor()
        try:
            yield cursor
            self.connection.commit()
            logger.debug("Database transaction committed")
        except Exception as e:
            self.connection.rollback()
            logger.error(f"Database transaction rolled back: {e}")
            raise
        finally:
            cursor.close()
    
    def _row_to_dict(self, row: sqlite3.Row) -> Optional[Dict[str, Any]]:
        """将sqlite3.Row转换为字典
        
        Args:
            row: SQLite行对象
            
        Returns:
            字典格式的 rowData，如果row为None则返回None
        """
        if row is None:
            return None
        return dict(row)
    
    # ============================================================
    # A. GEX历史操作
    # ============================================================
    
    def insert_gex_record(
        self,
        timestamp: datetime,
        gex_local: float,
        gex_calibrated: Optional[float] = None,
        alpha_factor: float = 1.0,
        put_wall_level: Optional[float] = None,
        flip_zone_lower: Optional[float] = None,
        flip_zone_upper: Optional[float] = None
    ) -> bool:
        """插入GEX历史记录
        
        Args:
            timestamp: 时间戳
            gex_local: 本地估算GEX值(美元)
            gex_calibrated: 校准后GEX值(美元)，可选
            alpha_factor: 修正系数α，默认1.0
            put_wall_level: Put Wall支撑点位，可选
            flip_zone_lower: Flip Zone下界，可选
            flip_zone_upper: Flip Zone上界，可选
            
        Returns:
            bool: 插入成功返回True，失败返回False
            
        Examples:
            >>> db.insert_gex_record(
            ...     timestamp=datetime.now(),
            ...     gex_local=-1200000000.0,
            ...     gex_calibrated=-1150000000.0,
            ...     alpha_factor=0.958
            ... )
            True
        """
        try:
            with self._get_cursor() as cursor:
                cursor.execute("""
                    INSERT OR REPLACE INTO gex_history 
                    (timestamp, gex_local, gex_calibrated, alpha_factor,
                     put_wall_level, flip_zone_lower, flip_zone_upper)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    timestamp.isoformat(),
                    gex_local,
                    gex_calibrated,
                    alpha_factor,
                    put_wall_level,
                    flip_zone_lower,
                    flip_zone_upper
                ))
            
            logger.debug(f"GEX记录插入成功: {timestamp}")
            return True
            
        except Exception as e:
            logger.error(f"插入GEX记录失败: {e}")
            return False
    
    def get_latest_gex(self) -> Optional[Dict[str, Any]]:
        """获取最新GEX记录
        
        Returns:
            字典格式的GEX记录，如果没有记录则返回None
            
        Examples:
            >>> latest = db.get_latest_gex()
            >>> if latest:
            ...     print(f"最新GEX: {latest['gex_local']}")
        """
        try:
            cursor = self.connection.execute("""
                SELECT * FROM gex_history
                ORDER BY timestamp DESC
                LIMIT 1
            """)
            
            row = cursor.fetchone()
            return self._row_to_dict(row)
            
        except Exception as e:
            logger.error(f"查询最新GEX失败: {e}")
            return None
    
    def get_gex_history(self, hours: int = 24) -> pd.DataFrame:
        """获取最近N小时的GEX历史
        
        Args:
            hours: 时间范围(小时)，默认24小时
            
        Returns:
            DataFrame格式的GEX历史数据
            
        Examples:
            >>> df = db.get_gex_history(hours=48)
            >>> print(df.head())
        """
        try:
            query = """
                SELECT * FROM gex_history
                WHERE timestamp >= datetime('now', '-' || ? || ' hours')
                ORDER BY timestamp DESC
            """
            
            df = pd.read_sql_query(query, self.connection, params=(hours,))
            logger.debug(f"获取GEX历史成功: {len(df)}条记录 ({hours}小时)")
            return df
            
        except Exception as e:
            logger.error(f"查询GEX历史失败: {e}")
            return pd.DataFrame()
    
    # ============================================================
    # B. 暗盘指标操作
    # ============================================================
    
    def insert_dark_pool_metrics(
        self,
        date: date,
        dix_value: Optional[float] = None,
        chartexchange_short_ratio: Optional[float] = None,
        stockgrid_20d_slope: Optional[float] = None,
        stockgrid_60d_slope: Optional[float] = None,
        stockgrid_divergence: bool = False,
        dbmf_ma5_recovery: bool = False,
        dix_signal: bool = False,
        short_ratio_signal: bool = False,
        stockgrid_signal: bool = False,
        aggregated_signal: bool = False,
        v_net: Optional[float] = None,
        ema_fast_5: Optional[float] = None,
        ema_slow_20: Optional[float] = None,
        zero_cross_signal: Optional[str] = None,
        momentum_reversal_signal: Optional[str] = None,
    ) -> bool:
        """插入暗盘指标记录
        
        Args:
            date: 日期
            dix_value: SqueezeMetrics DIX百分比，可选
            chartexchange_short_ratio: ChartExchange卖空比百分比，可选
            stockgrid_20d_slope: Stockgrid 20日净头寸斜率，可选
            stockgrid_60d_slope: Stockgrid 60日净头寸斜率，可选
            stockgrid_divergence: 底背离标志，默认False
            dbmf_ma5_recovery: DBMF均线收复标志，默认False
            dix_signal: DIX>45%信号，默认False
            short_ratio_signal: 卖空比>45%信号，默认False
            stockgrid_signal: Stockgrid拐点信号，默认False
            aggregated_signal: 三选二聚合信号，默认False
            v_net: 净做空量 (v2.1 暗盘预处理)
            ema_fast_5: EMA快线span=5 (v2.1)
            ema_slow_20: EMA慢线span=20 (v2.1)
            zero_cross_signal: 零轴穿越信号 (v2.1)
            momentum_reversal_signal: 动量反转信号 (v2.1)
            
        Returns:
            bool: 插入成功返回True，失败返回False
            
        Examples:
            >>> db.insert_dark_pool_metrics(
            ...     date=date.today(),
            ...     dix_value=46.8,
            ...     chartexchange_short_ratio=47.2,
            ...     aggregated_signal=True
            ... )
            True
        """
        try:
            with self._get_cursor() as cursor:
                cursor.execute("""
                    INSERT OR REPLACE INTO dark_pool_metrics 
                    (date, dix_value, chartexchange_short_ratio,
                     stockgrid_20d_slope, stockgrid_60d_slope,
                     stockgrid_divergence, dbmf_ma5_recovery,
                     dix_signal, short_ratio_signal, stockgrid_signal,
                     aggregated_signal,
                     v_net, ema_fast_5, ema_slow_20,
                     zero_cross_signal, momentum_reversal_signal,
                     updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    date.isoformat(),
                    dix_value,
                    chartexchange_short_ratio,
                    stockgrid_20d_slope,
                    stockgrid_60d_slope,
                    int(stockgrid_divergence),
                    int(dbmf_ma5_recovery),
                    int(dix_signal),
                    int(short_ratio_signal),
                    int(stockgrid_signal),
                    int(aggregated_signal),
                    v_net,
                    ema_fast_5,
                    ema_slow_20,
                    zero_cross_signal,
                    momentum_reversal_signal,
                ))
            
            logger.debug(f"暗盘指标插入成功: {date}")
            return True
            
        except Exception as e:
            logger.error(f"插入暗盘指标失败: {e}")
            return False
    
    def get_latest_dark_pool_metrics(self) -> Optional[Dict[str, Any]]:
        """获取最新暗盘指标
        
        Returns:
            字典格式的暗盘指标，如果没有记录则返回None
        """
        try:
            cursor = self.connection.execute("""
                SELECT * FROM dark_pool_metrics
                ORDER BY date DESC
                LIMIT 1
            """)
            
            row = cursor.fetchone()
            result = self._row_to_dict(row)
            
            # 将布尔值从int转换回bool
            if result:
                bool_fields = [
                    'stockgrid_divergence', 'dbmf_ma5_recovery',
                    'dix_signal', 'short_ratio_signal',
                    'stockgrid_signal', 'aggregated_signal'
                ]
                for field in bool_fields:
                    if field in result and result[field] is not None:
                        result[field] = bool(result[field])
            
            return result
            
        except Exception as e:
            logger.error(f"查询最新暗盘指标失败: {e}")
            return None
    
    def get_dark_pool_history(self, days: int = 30) -> pd.DataFrame:
        """获取最近N天暗盘历史
        
        Args:
            days: 时间范围(天)，默认30天
            
        Returns:
            DataFrame格式的暗盘历史数据
        """
        try:
            query = """
                SELECT * FROM dark_pool_metrics
                WHERE date >= date('now', '-' || ? || ' days')
                ORDER BY date DESC
            """
            
            df = pd.read_sql_query(query, self.connection, params=(days,))
            logger.debug(f"获取暗盘历史成功: {len(df)}条记录 ({days}天)")
            return df
            
        except Exception as e:
            logger.error(f"查询暗盘历史失败: {e}")
            return pd.DataFrame()
    
    # ============================================================
    # C. 加密衍生品操作
    # ============================================================
    
    def insert_crypto_derivatives(
        self,
        timestamp: datetime,
        btc_funding_rate: float,
        btc_oi: Optional[float] = None,
        oi_change_1h: Optional[float] = None,
        liquidation_spike: bool = False,
        cryptoquant_elr: Optional[float] = None,
        funding_anomaly: bool = False,
        oi_crash: bool = False,
        leverage_cleanup: bool = False
    ) -> bool:
        """插入加密衍生品记录
        
        Args:
            timestamp: 时间戳
            btc_funding_rate: BTC永续合约资金费率
            btc_oi: BTC全网持仓量(美元)，可选
            oi_change_1h: 1小时OI变化率(%)，可选
            liquidation_spike: 清算峰值标志，默认False
            cryptoquant_elr: CryptoQuant预估杠杆率，可选
            funding_anomaly: 费率异常(<-0.01%)，默认False
            oi_crash: OI断崖下跌(>15%)，默认False
            leverage_cleanup: 去杠杆完成标志，默认False
            
        Returns:
            bool: 插入成功返回True，失败返回False
            
        Examples:
            >>> db.insert_crypto_derivatives(
            ...     timestamp=datetime.now(),
            ...     btc_funding_rate=0.01,
            ...     btc_oi=15000000000.0,
            ...     oi_change_1h=-2.5,
            ...     funding_anomaly=False
            ... )
            True
        """
        try:
            with self._get_cursor() as cursor:
                cursor.execute("""
                    INSERT OR REPLACE INTO crypto_derivatives 
                    (timestamp, btc_funding_rate, btc_oi, oi_change_1h,
                     liquidation_spike, cryptoquant_elr,
                     funding_anomaly, oi_crash, leverage_cleanup)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    timestamp.isoformat(),
                    btc_funding_rate,
                    btc_oi,
                    oi_change_1h,
                    int(liquidation_spike),
                    cryptoquant_elr,
                    int(funding_anomaly),
                    int(oi_crash),
                    int(leverage_cleanup)
                ))
            
            logger.debug(f"加密衍生品记录插入成功: {timestamp}")
            return True
            
        except Exception as e:
            logger.error(f"插入加密衍生品记录失败: {e}")
            return False
    
    def get_latest_crypto_data(self) -> Optional[Dict[str, Any]]:
        """获取最新加密数据
        
        Returns:
            字典格式的加密数据，如果没有记录则返回None
        """
        try:
            cursor = self.connection.execute("""
                SELECT * FROM crypto_derivatives
                ORDER BY timestamp DESC
                LIMIT 1
            """)
            
            row = cursor.fetchone()
            result = self._row_to_dict(row)
            
            # 将布尔值从int转换回bool
            if result:
                bool_fields = [
                    'liquidation_spike', 'funding_anomaly',
                    'oi_crash', 'leverage_cleanup'
                ]
                for field in bool_fields:
                    if field in result and result[field] is not None:
                        result[field] = bool(result[field])
            
            return result
            
        except Exception as e:
            logger.error(f"查询最新加密数据失败: {e}")
            return None
    
    def get_crypto_history(self, hours: int = 24) -> pd.DataFrame:
        """获取加密历史数据
        
        Args:
            hours: 时间范围(小时)，默认24小时
            
        Returns:
            DataFrame格式的加密历史数据
        """
        try:
            query = """
                SELECT * FROM crypto_derivatives
                WHERE timestamp >= datetime('now', '-' || ? || ' hours')
                ORDER BY timestamp DESC
            """
            
            df = pd.read_sql_query(query, self.connection, params=(hours,))
            logger.debug(f"获取加密历史成功: {len(df)}条记录 ({hours}小时)")
            return df
            
        except Exception as e:
            logger.error(f"查询加密历史失败: {e}")
            return pd.DataFrame()
    
    # ============================================================
    # D. 信号警报操作
    # ============================================================
    
    def insert_signal_alert(
        self,
        trigger_time: datetime,
        total_score: float,
        gex_score: float = 0,
        vix_score: float = 0,
        crypto_score: float = 0,
        darkpool_score: float = 0,
        alert_level: str = "LEVEL_1",
        hawkes_branching_ratio: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> int:
        """插入信号警报记录
        
        Args:
            trigger_time: 触发时间
            total_score: 共振总分(0-5)
            gex_score: GEX维度得分，默认0
            vix_score: VIX维度得分，默认0
            crypto_score: 加密维度得分，默认0
            darkpool_score: 暗盘维度得分，默认0
            alert_level: 警报级别 (LEVEL_1/LEVEL_2/LEVEL_3)，默认LEVEL_1
            hawkes_branching_ratio: Hawkes分支比，可选
            details: JSON格式详细触发条件，可选
            
        Returns:
            int: 新插入记录的ID，失败返回-1
            
        Examples:
            >>> alert_id = db.insert_signal_alert(
            ...     trigger_time=datetime.now(),
            ...     total_score=4.8,
            ...     gex_score=1.5,
            ...     vix_score=1.0,
            ...     crypto_score=1.0,
            ...     darkpool_score=1.5,
            ...     alert_level="LEVEL_3",
            ...     hawkes_branching_ratio=0.65
            ... )
            >>> print(f"警报ID: {alert_id}")
        """
        try:
            # 将details字典序列化为JSON字符串
            details_json = json.dumps(details) if details else None
            
            with self._get_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO signal_alerts 
                    (trigger_time, total_score, gex_score, vix_score,
                     crypto_score, darkpool_score, alert_level,
                     hawkes_branching_ratio, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trigger_time.isoformat(),
                    total_score,
                    gex_score,
                    vix_score,
                    crypto_score,
                    darkpool_score,
                    alert_level,
                    hawkes_branching_ratio,
                    details_json
                ))
                
                # 获取最后插入的ID
                alert_id = cursor.lastrowid
            
            logger.info(f"信号警报插入成功 (ID: {alert_id}, Level: {alert_level})")
            return alert_id
            
        except Exception as e:
            logger.error(f"插入信号警报失败: {e}")
            return -1
    
    def get_recent_alerts(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最近N条警报
        
        Args:
            limit: 返回数量限制，默认10
            
        Returns:
            字典列表格式的警报记录
        """
        try:
            cursor = self.connection.execute("""
                SELECT * FROM signal_alerts
                ORDER BY trigger_time DESC
                LIMIT ?
            """, (limit,))
            
            rows = cursor.fetchall()
            alerts = []
            
            for row in rows:
                alert = self._row_to_dict(row)
                
                # 解析JSON格式的details
                if alert and alert.get('details'):
                    try:
                        alert['details'] = json.loads(alert['details'])
                    except json.JSONDecodeError:
                        alert['details'] = None
                
                # 转换布尔值
                if alert and 'acknowledged' in alert:
                    alert['acknowledged'] = bool(alert['acknowledged'])
                
                alerts.append(alert)
            
            logger.debug(f"获取最近警报成功: {len(alerts)}条记录")
            return alerts
            
        except Exception as e:
            logger.error(f"查询最近警报失败: {e}")
            return []
    
    def get_unacknowledged_alerts(self) -> List[Dict[str, Any]]:
        """获取未确认的警报
        
        Returns:
            字典列表格式的未确认警报记录
        """
        try:
            cursor = self.connection.execute("""
                SELECT * FROM signal_alerts
                WHERE acknowledged = 0
                ORDER BY trigger_time DESC
            """)
            
            rows = cursor.fetchall()
            alerts = []
            
            for row in rows:
                alert = self._row_to_dict(row)
                
                # 解析JSON格式的details
                if alert and alert.get('details'):
                    try:
                        alert['details'] = json.loads(alert['details'])
                    except json.JSONDecodeError:
                        alert['details'] = None
                
                # 转换布尔值
                if alert and 'acknowledged' in alert:
                    alert['acknowledged'] = bool(alert['acknowledged'])
                
                alerts.append(alert)
            
            logger.debug(f"获取未确认警报成功: {len(alerts)}条记录")
            return alerts
            
        except Exception as e:
            logger.error(f"查询未确认警报失败: {e}")
            return []
    
    def mark_alert_acknowledged(self, alert_id: int) -> bool:
        """标记警报为已确认
        
        Args:
            alert_id: 警报ID
            
        Returns:
            bool: 更新成功返回True，失败返回False
        """
        try:
            with self._get_cursor() as cursor:
                cursor.execute("""
                    UPDATE signal_alerts
                    SET acknowledged = 1
                    WHERE id = ?
                """, (alert_id,))
                
                # 检查是否有记录被更新
                if cursor.rowcount == 0:
                    logger.warning(f"警报ID {alert_id} 不存在")
                    return False
            
            logger.info(f"警报ID {alert_id} 已标记为确认")
            return True
            
        except Exception as e:
            logger.error(f"标记警报确认失败: {e}")
            return False
    
    # ============================================================
    # E. 系统配置操作
    # ============================================================
    
    def get_config_value(self, key: str, default: str = None) -> Optional[str]:
        """获取配置值
        
        Args:
            key: 配置键名
            default: 默认值，如果配置不存在则返回此值
            
        Returns:
            配置值字符串，如果不存在且未提供default则返回None
        """
        try:
            cursor = self.connection.execute("""
                SELECT value FROM system_config
                WHERE key = ?
            """, (key,))
            
            row = cursor.fetchone()
            
            if row:
                return row['value']
            return default
            
        except Exception as e:
            logger.error(f"获取配置值失败 (key={key}): {e}")
            return default
    
    def set_config_value(self, key: str, value: str, description: str = None) -> bool:
        """设置配置值
        
        Args:
            key: 配置键名
            value: 配置值
            description: 配置描述，可选
            
        Returns:
            bool: 设置成功返回True，失败返回False
        """
        try:
            with self._get_cursor() as cursor:
                cursor.execute("""
                    INSERT OR REPLACE INTO system_config 
                    (key, value, description, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                """, (key, value, description))
            
            logger.debug(f"配置值设置成功: {key}={value}")
            return True
            
        except Exception as e:
            logger.error(f"设置配置值失败 (key={key}): {e}")
            return False
    
    def update_alpha_factor(self, alpha: float) -> bool:
        """更新GEX校准系数α
        
        Args:
            alpha: 新的校准系数值
            
        Returns:
            bool: 更新成功返回True，失败返回False
        """
        return self.set_config_value(
            'alpha_factor',
            str(alpha),
            'GEX校准系数'
        )
    
    # ============================================================
    # G. 网关快照操作 (V2.0)
    # ============================================================

    def insert_gateway_snapshot(
        self,
        snapshot_date: date,
        pipeline_run_id: str,
        snapshot_json: str,
        schema_version: str = "2.0.0",
        data_quality_flag: str = "NORMAL",
        resonance_score: int = 0,
        processing_duration_ms: int = 0,
        interception_status: str = "pass_through",
    ) -> bool:
        """插入网关快照记录 (V2.0)

        存储每日穿过 Layer 2 网关的完整 JSON 信封，供审计和回测使用。

        Args:
            snapshot_date: 快照日期
            pipeline_run_id: 流水线运行 ID (UUID)
            snapshot_json: 完整 GatewayEnvelope JSON 字符串
            schema_version: Schema 版本号
            data_quality_flag: 数据质量标志 (NORMAL/DEGRADED/ERROR)
            resonance_score: 共振得分
            processing_duration_ms: 处理耗时 (毫秒)
            interception_status: 拦截状态 (pass_through/degraded/blocked)

        Returns:
            bool: 插入成功返回 True
        """
        try:
            with self._get_cursor() as cursor:
                cursor.execute("""
                    INSERT OR REPLACE INTO gateway_snapshots
                    (snapshot_date, pipeline_run_id, snapshot_json, schema_version,
                     data_quality_flag, resonance_score, processing_duration_ms,
                     interception_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    snapshot_date.isoformat(),
                    pipeline_run_id,
                    snapshot_json,
                    schema_version,
                    data_quality_flag,
                    resonance_score,
                    processing_duration_ms,
                    interception_status,
                ))

            logger.debug(f"网关快照插入成功: {snapshot_date} (run_id={pipeline_run_id[:8]}...)")
            return True

        except Exception as e:
            logger.error(f"插入网关快照失败: {e}")
            return False

    def get_gateway_snapshot_by_date(
        self, snapshot_date: date
    ) -> Optional[Dict[str, Any]]:
        """按日期获取网关快照

        Args:
            snapshot_date: 快照日期

        Returns:
            字典格式的网关快照，不存在则返回 None
        """
        try:
            cursor = self.connection.execute("""
                SELECT * FROM gateway_snapshots
                WHERE snapshot_date = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (snapshot_date.isoformat(),))

            row = cursor.fetchone()
            result = self._row_to_dict(row)

            if result and result.get('snapshot_json'):
                try:
                    result['snapshot_json'] = json.loads(result['snapshot_json'])
                except json.JSONDecodeError:
                    pass

            return result

        except Exception as e:
            logger.error(f"查询网关快照失败 (date={snapshot_date}): {e}")
            return None

    def get_gateway_snapshot_by_run_id(
        self, pipeline_run_id: str
    ) -> Optional[Dict[str, Any]]:
        """按流水线运行 ID 获取网关快照

        Args:
            pipeline_run_id: 流水线运行 ID

        Returns:
            字典格式的网关快照，不存在则返回 None
        """
        try:
            cursor = self.connection.execute("""
                SELECT * FROM gateway_snapshots
                WHERE pipeline_run_id = ?
                LIMIT 1
            """, (pipeline_run_id,))

            row = cursor.fetchone()
            result = self._row_to_dict(row)

            if result and result.get('snapshot_json'):
                try:
                    result['snapshot_json'] = json.loads(result['snapshot_json'])
                except json.JSONDecodeError:
                    pass

            return result

        except Exception as e:
            logger.error(f"查询网关快照失败 (run_id={pipeline_run_id[:8]}...): {e}")
            return None

    def get_gateway_snapshot_history(
        self, days: int = 90
    ) -> pd.DataFrame:
        """获取历史网关快照 (用于批量回测)

        Args:
            days: 回溯天数

        Returns:
            DataFrame 格式的网关快照历史
        """
        try:
            query = """
                SELECT * FROM gateway_snapshots
                WHERE snapshot_date >= date('now', '-' || ? || ' days')
                ORDER BY snapshot_date DESC
            """

            df = pd.read_sql_query(query, self.connection, params=(days,))
            logger.debug(f"获取网关快照历史成功: {len(df)}条记录 ({days}天)")
            return df

        except Exception as e:
            logger.error(f"查询网关快照历史失败: {e}")
            return pd.DataFrame()

    # ============================================================
    # H. 数据校验审计日志操作 (V2.0)
    # ============================================================

    def insert_validation_audit_entries(
        self,
        snapshot_date: date,
        pipeline_run_id: str,
        audit_entries: list,
        pass_rate_pct: float = 100.0,
    ) -> bool:
        """批量插入数据校验审计日志 (V2.0 数据校验防线)

        将 DataValidationPipeline 产生的所有审计条目持久化到不可变日志表。
        每个条目记录一条校验违规详情，关联到当次 Pipeline 运行。

        Args:
            snapshot_date: 快照日期
            pipeline_run_id: 流水线运行 ID (UUID)
            audit_entries: ValidationAuditEntry 对象列表
            pass_rate_pct: 当日校验总体通过率 (%)

        Returns:
            bool: 插入成功返回 True
        """
        if not audit_entries:
            return True  # 无违规，视为成功

        try:
            with self._get_cursor() as cursor:
                rows = []
                for entry in audit_entries:
                    rows.append((
                        snapshot_date.isoformat(),
                        pipeline_run_id,
                        getattr(entry, 'check_type', 'UNKNOWN'),
                        getattr(entry, 'severity', 'WARN'),
                        getattr(entry, 'field_name', ''),
                        getattr(entry, 'expected_range', ''),
                        getattr(entry, 'actual_value', ''),
                        getattr(entry, 'option_type', ''),
                        getattr(entry, 'strike', 0.0),
                        getattr(entry, 'expiry', ''),
                        pass_rate_pct,
                        getattr(entry, 'details', ''),
                    ))

                cursor.executemany("""
                    INSERT INTO validation_audit_log
                    (snapshot_date, pipeline_run_id, check_type, severity,
                     field_name, expected_range, actual_value, option_type,
                     strike, expiry, pass_rate_pct, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, rows)

            logger.info(f"审计日志插入成功: {len(rows)} 条 (date={snapshot_date}, run_id={pipeline_run_id[:8]}...)")
            return True

        except Exception as e:
            logger.error(f"插入审计日志失败: {e}")
            return False

    def get_validation_audit_by_date(
        self, snapshot_date: date
    ) -> list:
        """按日期获取校验审计日志

        Args:
            snapshot_date: 快照日期

        Returns:
            字典列表格式的审计条目
        """
        try:
            cursor = self.connection.execute("""
                SELECT * FROM validation_audit_log
                WHERE snapshot_date = ?
                ORDER BY created_at DESC
            """, (snapshot_date.isoformat(),))

            return [self._row_to_dict(row) for row in cursor.fetchall()]

        except Exception as e:
            logger.error(f"查询审计日志失败 (date={snapshot_date}): {e}")
            return []

    def get_validation_audit_by_run_id(
        self, pipeline_run_id: str
    ) -> list:
        """按流水线运行 ID 获取校验审计日志

        Args:
            pipeline_run_id: 流水线运行 ID

        Returns:
            字典列表格式的审计条目
        """
        try:
            cursor = self.connection.execute("""
                SELECT * FROM validation_audit_log
                WHERE pipeline_run_id = ?
                ORDER BY created_at DESC
            """, (pipeline_run_id,))

            return [self._row_to_dict(row) for row in cursor.fetchall()]

        except Exception as e:
            logger.error(f"查询审计日志失败 (run_id={pipeline_run_id[:8]}...): {e}")
            return []

    def get_recent_pass_rates(
        self, num_runs: int = 5
    ) -> list:
        """获取最近 N 次运行的校验通过率 (用于 95% 熔断判定)

        查询 v_daily_pass_rate 视图，返回最近 num_runs 次不同运行的通过率。

        Args:
            num_runs: 回溯的运行次数

        Returns:
            通过率浮点数列表 (0-100)，最近的在末尾
        """
        try:
            cursor = self.connection.execute("""
                SELECT DISTINCT pipeline_run_id, pass_rate_pct
                FROM v_daily_pass_rate
                ORDER BY snapshot_date DESC, pipeline_run_id DESC
                LIMIT ?
            """, (num_runs,))

            rows = cursor.fetchall()
            # 逆序使最近的排末尾 (匹配 historical_pass_rates)
            rates = [row['pass_rate_pct'] for row in reversed(rows)]
            return [r for r in rates if r is not None]

        except Exception as e:
            logger.error(f"查询近期通过率失败: {e}")
            return []

    # ============================================================
    # I. GEXMetrix 快照操作 (Phase 8)
    # ============================================================

    def insert_gex_snapshot(
        self,
        symbol: str,
        timestamp: datetime,
        filename: str,
        net_gex: Optional[float] = None,
        call_gex: Optional[float] = None,
        put_gex: Optional[float] = None,
        zero_gamma_level: Optional[float] = None,
        call_wall: Optional[float] = None,
        put_wall: Optional[float] = None,
        spot_price: Optional[float] = None,
        total_gamma: Optional[float] = None,
        file_size: Optional[int] = None,
    ) -> bool:
        """插入 GEXMetrix 快照摘要"""
        try:
            with self._get_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO gex_snapshots
                    (symbol, timestamp, filename, net_gex, call_gex, put_gex,
                     zero_gamma_level, call_wall, put_wall, spot_price,
                     total_gamma, file_size)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    symbol.upper(),
                    timestamp.isoformat() if isinstance(timestamp, datetime) else str(timestamp),
                    filename,
                    net_gex,
                    call_gex,
                    put_gex,
                    zero_gamma_level,
                    call_wall,
                    put_wall,
                    spot_price,
                    total_gamma,
                    file_size,
                ))
            logger.debug(f"GEX快照插入成功: {symbol} @ {timestamp}")
            return True
        except Exception as e:
            logger.error(f"插入GEX快照失败 ({symbol}): {e}")
            return False

    def get_gex_snapshot_latest(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取某标的最新 GEX 快照"""
        try:
            cursor = self.connection.execute("""
                SELECT * FROM gex_snapshots
                WHERE symbol = ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (symbol.upper(),))
            row = cursor.fetchone()
            return self._row_to_dict(row)
        except Exception as e:
            logger.error(f"查询GEX快照失败 ({symbol}): {e}")
            return None

    def get_gex_snapshot_history(
        self, symbol: str, days: int = 7
    ) -> List[Dict[str, Any]]:
        """获取某标的历史 Net GEX 时间序列"""
        try:
            cursor = self.connection.execute("""
                SELECT symbol, timestamp, net_gex, spot_price
                FROM gex_snapshots
                WHERE symbol = ?
                  AND timestamp >= datetime('now', '-' || ? || ' days')
                ORDER BY timestamp ASC
            """, (symbol.upper(), days))
            rows = cursor.fetchall()
            return [self._row_to_dict(r) for r in rows]
        except Exception as e:
            logger.error(f"查询GEX历史失败 ({symbol}, {days}d): {e}")
            return []

    def get_gex_snapshot_symbols(self) -> List[Dict[str, Any]]:
        """获取所有可用标的及数据新鲜度"""
        try:
            cursor = self.connection.execute("""
                SELECT symbol,
                       MAX(timestamp) as latest_timestamp,
                       COUNT(*) as snapshot_count
                FROM gex_snapshots
                GROUP BY symbol
                ORDER BY latest_timestamp DESC
            """)
            rows = cursor.fetchall()
            result = []
            for row in rows:
                d = self._row_to_dict(row)
                # 计算新鲜度 (分钟)
                try:
                    ts = d.get("latest_timestamp", "")
                    if ts:
                        from datetime import datetime as dt
                        latest_dt = dt.fromisoformat(str(ts))
                        age_minutes = (dt.now() - latest_dt).total_seconds() / 60
                        d["age_minutes"] = round(age_minutes, 1)
                except Exception:
                    d["age_minutes"] = None
                result.append(d)
            return result
        except Exception as e:
            logger.error(f"查询GEX标的列表失败: {e}")
            return []

    def get_gex_snapshot_levels(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取某标的关键价位 (Zero Gamma / Call Wall / Put Wall)"""
        try:
            cursor = self.connection.execute("""
                SELECT symbol, timestamp, spot_price,
                       zero_gamma_level, call_wall, put_wall,
                       net_gex
                FROM gex_snapshots
                WHERE symbol = ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (symbol.upper(),))
            row = cursor.fetchone()
            return self._row_to_dict(row)
        except Exception as e:
            logger.error(f"查询GEX价位失败 ({symbol}): {e}")
            return None

    def get_gex_snapshot_summary(self) -> Dict[str, Any]:
        """获取全局 GEXMetrix summary (从 gex_snapshots 表聚合)"""
        try:
            cursor = self.connection.execute("""
                SELECT COUNT(DISTINCT symbol) as total_symbols,
                       MAX(timestamp) as latest_update,
                       COUNT(*) as total_snapshots
                FROM gex_snapshots
            """)
            row = cursor.fetchone()
            summary = self._row_to_dict(row) or {}

            # 获取每个 symbol 的最新状态
            symbols = self.get_gex_snapshot_symbols()
            summary["symbols"] = symbols
            return summary
        except Exception as e:
            logger.error(f"查询GEX summary失败: {e}")
            return {"total_symbols": 0, "symbols": []}

    def clean_old_gex_snapshots(self, symbol: str, keep: int = 50) -> int:
        """清理旧快照，每个标的保留最近 N 个"""
        try:
            with self._get_cursor() as cursor:
                cursor.execute("""
                    DELETE FROM gex_snapshots
                    WHERE symbol = ?
                      AND id NOT IN (
                        SELECT id FROM gex_snapshots
                        WHERE symbol = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                      )
                """, (symbol.upper(), symbol.upper(), keep))
                deleted = cursor.rowcount
            if deleted > 0:
                logger.debug(f"清理GEX旧快照 {symbol}: {deleted} 条")
            return deleted
        except Exception as e:
            logger.error(f"清理GEX快照失败 ({symbol}): {e}")
            return 0

    # ============================================================
    # F. 数据库维护
    # ============================================================
    
    def backup_database(self, backup_path: str = None) -> str:
        """备份数据库
        
        Args:
            backup_path: 备份文件路径，如果为None则自动生成带时间戳的文件名
            
        Returns:
            str: 备份文件路径
            
        Raises:
            DatabaseError: 备份失败时抛出
        """
        try:
            if backup_path is None:
                # 自动生成备份文件名
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                backup_dir = Path(self.db_path).parent / "backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                backup_path = str(backup_dir / f"monitoring_backup_{timestamp}.db")
            
            # 确保备份目录存在
            Path(backup_path).parent.mkdir(parents=True, exist_ok=True)
            
            # 执行备份
            backup_conn = sqlite3.connect(backup_path)
            self.connection.backup(backup_conn)
            backup_conn.close()
            
            logger.info(f"数据库备份成功: {backup_path}")
            return backup_path
            
        except Exception as e:
            error_msg = f"数据库备份失败: {e}"
            logger.error(error_msg)
            raise DatabaseError(
                error_code="DB_BACKUP_FAILED",
                details={"backup_path": backup_path, "error": str(e)}
            )
    
    def clean_old_backups(self, keep_count: int = 7) -> int:
        """清理旧备份文件，仅保留最近 N 个
        
        Args:
            keep_count: 保留的最近备份数量 (默认 7)
            
        Returns:
            int: 删除的备份文件数量
        """
        try:
            backup_dir = Path(self.db_path).parent / "backups"
            if not backup_dir.exists():
                return 0
            
            # 收集所有备份文件
            backups = sorted(
                backup_dir.glob("monitoring_backup_*.db"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            
            # 删除超出保留数量的旧备份
            removed = 0
            for old_backup in backups[keep_count:]:
                try:
                    old_backup.unlink()
                    removed += 1
                    logger.info(f"已删除旧备份: {old_backup.name}")
                except Exception as del_err:
                    logger.warning(f"删除旧备份失败 {old_backup.name}: {del_err}")
            
            if removed > 0:
                logger.info(f"备份清理完成: 删除 {removed} 个旧备份, 保留 {min(keep_count, len(backups))} 个")
            return removed
        except Exception as e:
            logger.error(f"备份清理失败: {e}")
            return 0
    
    def vacuum_database(self) -> bool:
        """清理数据库碎片(VACUUM)
        
        重新组织数据库文件，回收未使用的空间。
        建议在大量删除操作后执行。
        
        Returns:
            bool: 清理成功返回True，失败返回False
        """
        try:
            self.connection.execute("VACUUM")
            logger.info("数据库碎片清理成功")
            return True
            
        except Exception as e:
            logger.error(f"数据库碎片清理失败: {e}")
            return False
    
    def get_database_stats(self) -> Dict[str, Any]:
        """获取数据库统计信息
        
        Returns:
            包含各表记录数的字典
        """
        try:
            stats = {}
            tables = [
                'gex_history', 'dark_pool_metrics',
                'crypto_derivatives', 'signal_alerts',
                'system_config'
            ]
            
            for table in tables:
                cursor = self.connection.execute(f"SELECT COUNT(*) as count FROM {table}")
                row = cursor.fetchone()
                stats[table] = row['count'] if row else 0
            
            # 获取数据库文件大小(仅适用于文件数据库)
            try:
                if self.db_path != ':memory:':
                    db_size = Path(self.db_path).stat().st_size
                    stats['database_size_bytes'] = db_size
                    stats['database_size_mb'] = round(db_size / (1024 * 1024), 2)
                else:
                    stats['database_size_bytes'] = 0
                    stats['database_size_mb'] = 0.0
            except Exception:
                stats['database_size_bytes'] = 0
                stats['database_size_mb'] = 0.0
            
            return stats
            
        except Exception as e:
            logger.error(f"获取数据库统计信息失败: {e}")
            return {}
    
    @staticmethod
    def _to_float(v, default=0.0) -> float:
        """安全转 float，兼容 dict/list 等异常类型"""
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                return default
        if isinstance(v, dict):
            # dict 本身不能转 float，尝试提取常见字段
            for key in ('premium_pct', 'premium_ratio', 'value', 'price', 'close', 'settle', 'vix_spot', 'spot'):
                if key in v:
                    return DatabaseManager._to_float(v[key], default)
            return default
        return default

    def insert_vix_analysis(self, timestamp, vix_spot, vx1, vx2, ratio, state, panic_premium):
        """写入VIX期限结构分析结果"""
        try:
            with self._get_cursor() as cursor:
                cursor.execute(
                    """INSERT INTO vix_analysis
                       (timestamp, vix_spot, vx1, vx2, term_structure_ratio, term_structure_state, panic_premium)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (timestamp.isoformat() if hasattr(timestamp, 'isoformat') else str(timestamp),
                     self._to_float(vix_spot), self._to_float(vx1), self._to_float(vx2),
                     self._to_float(ratio), str(state), self._to_float(panic_premium))
                )
            logger.info(f"VIX分析写入: ratio={self._to_float(ratio):.4f}, state={state}")
            return True
        except Exception as e:
            logger.error(f"VIX分析写入失败: {e}", exc_info=True)
            return False

    def get_latest_vix_analysis(self):
        """获取最新VIX分析记录"""
        try:
            with self._get_cursor() as cursor:
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='vix_analysis'"
                )
                if not cursor.fetchone():
                    return None
                cursor.execute(
                    "SELECT * FROM vix_analysis ORDER BY timestamp DESC LIMIT 1"
                )
                row = cursor.fetchone()
                return self._row_to_dict(row)
        except Exception as e:
            logger.error(f"查询最新VIX失败: {e}")
            return None

    def acknowledge_alert(self, alert_id: int) -> bool:
        """标记告警为已确认 (API别名)"""
        return self.mark_alert_acknowledged(alert_id)

    def acknowledge_signal(self, signal_id: int) -> bool:
        """标记信号为已确认"""
        return self.mark_alert_acknowledged(signal_id)

    def get_latest_signal(self):
        """获取最新信号记录"""
        try:
            with self._get_cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM signal_alerts ORDER BY trigger_time DESC LIMIT 1"
                )
                row = cursor.fetchone()
                return self._row_to_dict(row)
        except Exception as e:
            logger.error(f"查询最新信号失败: {e}")
            return None

    def get_alerts(self, page: int = 1, page_size: int = 20, level: str = None, acknowledged: bool = None):
        """分页获取告警列表"""
        try:
            where = []
            params = []
            if level and level != 'ALL':
                where.append("alert_level = ?")
                params.append(level)
            if acknowledged is not None:
                where.append("acknowledged = ?")
                params.append(1 if acknowledged else 0)
            where_clause = ("WHERE " + " AND ".join(where)) if where else ""
            offset = (page - 1) * page_size
            params.extend([page_size, offset])
            with self._get_cursor() as cursor:
                cursor.execute(
                    f"SELECT * FROM signal_alerts {where_clause} ORDER BY trigger_time DESC LIMIT ? OFFSET ?",
                    params
                )
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"查询告警列表失败: {e}")
            return []

    def get_alerts_count(self, level: str = None, acknowledged: bool = None):
        """获取告警总数"""
        try:
            where = []
            params = []
            if level and level != 'ALL':
                where.append("alert_level = ?")
                params.append(level)
            if acknowledged is not None:
                where.append("acknowledged = ?")
                params.append(1 if acknowledged else 0)
            where_clause = ("WHERE " + " AND ".join(where)) if where else ""
            with self._get_cursor() as cursor:
                cursor.execute(
                    f"SELECT COUNT(*) FROM signal_alerts {where_clause}", params
                )
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"查询告警总数失败: {e}")
            return 0

    def get_signal_history(self, days: int = 30, page: int = 1, page_size: int = 50):
        """分页获取信号历史"""
        try:
            offset = (page - 1) * page_size
            with self._get_cursor() as cursor:
                cursor.execute(
                    """SELECT * FROM signal_alerts
                       WHERE trigger_time >= datetime('now', '-' || ? || ' days')
                       ORDER BY trigger_time DESC LIMIT ? OFFSET ?""",
                    (days, page_size, offset)
                )
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"查询信号历史失败: {e}")
            return []

    def get_signal_count(self, days: int = 30):
        """获取信号总数"""
        try:
            with self._get_cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM signal_alerts WHERE trigger_time >= datetime('now', '-' || ? || ' days')",
                    (days,)
                )
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"查询信号总数失败: {e}")
            return 0

    def get_gex_history_days(self, days: int = 90):
        """按天数获取GEX历史 (API用)"""
        try:
            with self._get_cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM gex_history WHERE timestamp >= datetime('now', '-' || ? || ' days') ORDER BY timestamp ASC",
                    (days,)
                )
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"查询GEX历史失败: {e}")
            return []

    def get_vix_history(self, days: int = 90):
        """按天数获取VIX历史"""
        try:
            with self._get_cursor() as cursor:
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='vix_analysis'"
                )
                if not cursor.fetchone():
                    return []
                cursor.execute(
                    "SELECT * FROM vix_analysis WHERE timestamp >= datetime('now', '-' || ? || ' days') ORDER BY timestamp ASC",
                    (days,)
                )
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"查询VIX历史失败: {e}")
            return []

    def get_darkpool_history_list(self, days: int = 90):
        """按天数获取暗盘历史 (返回列表, API用)"""
        try:
            with self._get_cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM dark_pool_metrics WHERE date >= date('now', '-' || ? || ' days') ORDER BY date ASC",
                    (days,)
                )
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"查询暗盘历史失败: {e}")
            return []

    def close(self):
        """关闭数据库连接"""
        if self.connection:
            try:
                self.connection.close()
                logger.info("数据库连接已关闭")
            except Exception as e:
                logger.error(f"关闭数据库连接失败: {e}")
            finally:
                self.connection = None
                DatabaseManager._initialized = False
    
    # ============================================================
    # 上下文管理器支持
    # ============================================================
    
    def __enter__(self):
        """支持with语句"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出with语句时自动关闭连接"""
        self.close()
        return False  # 不抑制异常
