# 数据库管理器快速参考

## 导入方式

```python
from database import DatabaseManager
# 或
from database.db_manager import DatabaseManager
```

## 初始化

```python
# 使用默认配置路径
db = DatabaseManager()

# 指定自定义路径
db = DatabaseManager(db_path="./custom_db.sqlite")

# 使用内存数据库(测试用)
db = DatabaseManager(db_path=":memory:")

# 上下文管理器(推荐)
with DatabaseManager() as db:
    # 自动关闭连接
    pass
```

## GEX历史操作

### 插入记录
```python
from datetime import datetime

result = db.insert_gex_record(
    timestamp=datetime.now(),
    gex_local=-1200000000.0,           # 必需
    gex_calibrated=-1150000000.0,      # 可选
    alpha_factor=0.958,                # 可选,默认1.0
    put_wall_level=4500.0,             # 可选
    flip_zone_lower=4480.0,            # 可选
    flip_zone_upper=4520.0             # 可选
)
# 返回: True/False
```

### 查询最新记录
```python
latest = db.get_latest_gex()
# 返回: dict 或 None
# 示例: {'timestamp': '2026-06-09T11:00:00', 'gex_local': -1200000000.0, ...}

if latest:
    print(f"GEX: {latest['gex_local']}")
```

### 获取历史记录
```python
import pandas as pd

df = db.get_gex_history(hours=24)
# 返回: DataFrame
# 列: timestamp, gex_local, gex_calibrated, alpha_factor, ...

print(df.head())
print(f"记录数: {len(df)}")
```

## 暗盘指标操作

### 插入记录
```python
from datetime import date

result = db.insert_dark_pool_metrics(
    date=date.today(),                      # 必需
    dix_value=46.8,                         # 可选
    chartexchange_short_ratio=47.2,         # 可选
    stockgrid_20d_slope=0.85,               # 可选
    stockgrid_60d_slope=0.92,               # 可选
    stockgrid_divergence=True,              # 可选,默认False
    dbmf_ma5_recovery=False,                # 可选,默认False
    dix_signal=True,                        # 可选,默认False
    short_ratio_signal=True,                # 可选,默认False
    stockgrid_signal=False,                 # 可选,默认False
    aggregated_signal=True                  # 可选,默认False
)
# 返回: True/False
```

### 查询最新记录
```python
latest = db.get_latest_dark_pool_metrics()
# 返回: dict 或 None

if latest:
    print(f"DIX: {latest['dix_value']}%")
    print(f"聚合信号: {latest['aggregated_signal']}")
```

### 获取历史记录
```python
df = db.get_dark_pool_history(days=30)
# 返回: DataFrame
```

## 加密衍生品操作

### 插入记录
```python
result = db.insert_crypto_derivatives(
    timestamp=datetime.now(),
    btc_funding_rate=0.01,              # 必需
    btc_oi=15000000000.0,               # 可选
    oi_change_1h=-2.5,                  # 可选
    liquidation_spike=False,            # 可选,默认False
    cryptoquant_elr=3.2,                # 可选
    funding_anomaly=False,              # 可选,默认False
    oi_crash=False,                     # 可选,默认False
    leverage_cleanup=False              # 可选,默认False
)
# 返回: True/False
```

### 查询最新记录
```python
latest = db.get_latest_crypto_data()
# 返回: dict 或 None

if latest:
    print(f"资金费率: {latest['btc_funding_rate']}")
    print(f"费率异常: {latest['funding_anomaly']}")
```

### 获取历史记录
```python
df = db.get_crypto_history(hours=24)
# 返回: DataFrame
```

## 信号警报操作

### 插入警报
```python
alert_id = db.insert_signal_alert(
    trigger_time=datetime.now(),
    total_score=4.8,                    # 必需, 0-5
    gex_score=1.5,                      # 可选,默认0
    vix_score=1.0,                      # 可选,默认0
    crypto_score=1.0,                   # 可选,默认0
    darkpool_score=1.5,                 # 可选,默认0
    alert_level="LEVEL_3",              # 可选,默认"LEVEL_1"
                                        # 可选值: LEVEL_1, LEVEL_2, LEVEL_3
    hawkes_branching_ratio=0.65,        # 可选
    details={                           # 可选,会自动JSON序列化
        "condition": "strong_resonance",
        "tickers": ["SPY", "QQQ"]
    }
)
# 返回: int (新记录ID), 失败返回-1

print(f"警报ID: {alert_id}")
```

### 获取最近警报
```python
alerts = db.get_recent_alerts(limit=10)
# 返回: list[dict]

for alert in alerts:
    print(f"时间: {alert['trigger_time']}")
    print(f"级别: {alert['alert_level']}")
    print(f"总分: {alert['total_score']}")
    print(f"详情: {alert['details']}")  # 已自动JSON解析为dict
```

### 获取未确认警报
```python
unack_alerts = db.get_unacknowledged_alerts()
# 返回: list[dict]

print(f"未确认警报数: {len(unack_alerts)}")
```

### 标记为已确认
```python
success = db.mark_alert_acknowledged(alert_id=1)
# 返回: True/False
```

## 系统配置操作

### 读取配置
```python
alpha = db.get_config_value('alpha_factor')
# 返回: str 或 None

# 带默认值
value = db.get_config_value('nonexistent_key', default='default_val')
# 返回: 'default_val'
```

### 写入配置
```python
success = db.set_config_value(
    key='my_config',
    value='some_value',
    description='我的配置项'  # 可选
)
# 返回: True/False
```

### 更新Alpha系数
```python
success = db.update_alpha_factor(1.05)
# 返回: True/False
```

## 数据库维护

### 备份数据库
```python
# 自动生成带时间戳的备份
backup_path = db.backup_database()
# 返回: str (备份文件路径)
# 示例: 'database/backups/monitoring_backup_20260609_110916.db'

# 指定备份路径
backup_path = db.backup_database('./my_backup.db')
```

### 清理碎片
```python
success = db.vacuum_database()
# 返回: True/False
# 建议在大量删除操作后执行
```

### 获取统计信息
```python
stats = db.get_database_stats()
# 返回: dict

print(stats)
# 示例输出:
# {
#     'gex_history': 100,
#     'dark_pool_metrics': 30,
#     'crypto_derivatives': 500,
#     'signal_alerts': 25,
#     'system_config': 3,
#     'database_size_bytes': 73728,
#     'database_size_mb': 0.07
# }
```

### 关闭连接
```python
db.close()
# 如果使用with语句,会自动调用
```

## 常见模式

### 模式1: 完整工作流程
```python
from database import DatabaseManager
from datetime import datetime

db = DatabaseManager()

try:
    # 1. 插入数据
    db.insert_gex_record(
        timestamp=datetime.now(),
        gex_local=-1200000000.0
    )
    
    # 2. 查询数据
    latest = db.get_latest_gex()
    
    # 3. 触发警报
    if latest and latest['gex_local'] < -1000000000:
        db.insert_signal_alert(
            trigger_time=datetime.now(),
            total_score=3.5,
            alert_level="LEVEL_2"
        )
        
finally:
    db.close()
```

### 模式2: 使用上下文管理器(推荐)
```python
from database import DatabaseManager

with DatabaseManager() as db:
    # 所有操作自动在事务中
    db.insert_gex_record(...)
    db.insert_dark_pool_metrics(...)
    
    # 退出with块时自动提交并关闭
```

### 模式3: 批量数据处理
```python
import pandas as pd

with DatabaseManager() as db:
    # 获取历史数据进行分析
    gex_df = db.get_gex_history(hours=48)
    darkpool_df = db.get_dark_pool_history(days=7)
    
    # 使用pandas进行分析
    avg_gex = gex_df['gex_local'].mean()
    print(f"平均GEX: {avg_gex}")
```

### 模式4: 定期备份
```python
from datetime import datetime

with DatabaseManager() as db:
    # 在执行重要操作前备份
    backup_path = db.backup_database()
    print(f"备份完成: {backup_path}")
    
    # 执行数据更新
    db.insert_gex_record(...)
```

## 错误处理

所有写操作方法(insert_*)失败时返回`False`,不会抛出异常:

```python
result = db.insert_gex_record(...)
if not result:
    print("插入失败,请检查日志")
```

读操作方法失败时返回安全默认值:
- `get_latest_*()` → `None`
- `get_*_history()` → 空DataFrame
- `get_recent_alerts()` → 空列表
- `get_config_value()` → `default`参数或`None`

## 性能提示

1. **批量插入**: 当前每次insert都是独立事务,大量数据建议循环调用
2. **查询优化**: 已创建索引,按时间查询性能良好
3. **WAL模式**: 已启用,支持并发读写
4. **内存数据库**: 测试时使用`:memory:`路径,速度更快

## 数据类型映射

| SQLite类型 | Python类型 | 说明 |
|-----------|-----------|------|
| DATETIME | str | ISO 8601格式 |
| REAL | float | 浮点数 |
| INTEGER | int/bool | bool存储为0/1 |
| TEXT | str | 字符串/JSON |

**注意**: 布尔字段从数据库读取时会自动从int转换为bool。

## 调试技巧

### 查看原始SQL
修改`db_manager.py`中的`_get_cursor()`方法,添加日志:

```python
@contextmanager
def _get_cursor(self):
    cursor = self.connection.cursor()
    try:
        yield cursor
        self.connection.commit()
        logger.debug("事务提交成功")  # 添加这行
    except Exception as e:
        self.connection.rollback()
        logger.error(f"事务回滚: {e}")
        raise
    finally:
        cursor.close()
```

### 检查表结构
```python
cursor = db.connection.execute("PRAGMA table_info(gex_history)")
for row in cursor.fetchall():
    print(row)
```

### 查看索引
```python
cursor = db.connection.execute("SELECT * FROM sqlite_master WHERE type='index'")
for row in cursor.fetchall():
    print(row['name'])
```

---

**最后更新**: 2026-06-09  
**版本**: 1.0
