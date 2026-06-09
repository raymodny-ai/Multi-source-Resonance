# Phase 7 快速参考指南

## 🚀 快速启动

```python
from main_scheduler import create_and_start_scheduler

# 一行代码启动系统
create_and_start_scheduler()
```

---

## 📦 核心模块

### 1. MainScheduler

**导入**:
```python
from main_scheduler import MainScheduler, create_and_start_scheduler
```

**基本用法**:
```python
# 方式1: 直接启动（阻塞）
create_and_start_scheduler()

# 方式2: 手动控制
scheduler = MainScheduler()
scheduler.start()  # 阻塞运行

# 停止调度器（在另一个线程中调用）
scheduler.shutdown()
```

**查询任务状态**:
```python
scheduler = MainScheduler()
status = scheduler.get_task_status()
for job_id, info in status.items():
    print(f"{job_id}: {info['name']} - 下次运行: {info['next_run_time']}")
```

---

### 2. FallbackManager

**导入**:
```python
from utils.fallback_manager import FallbackManager, handle_fetch_errors
```

**降级逻辑**:
```python
fallback = FallbackManager()

# 检查暗盘数据源状态
result = fallback.handle_darkpool_fallback(
    squeezemetrics_success=True,   # SqueezeMetrics是否成功
    chartexchange_success=False,   # ChartExchange是否成功
    stockgrid_success=True         # Stockgrid是否成功
)

print(result['mode'])              # 'PARTIAL'
print(result['available_sources']) # ['SqueezeMetrics', 'Stockgrid']
print(result['warning_level'])     # 'WARNING'
```

**失败记录与熔断**:
```python
fallback = FallbackManager()

# 记录失败
fallback.record_failure('fetch_dix')

# 检查状态
status = fallback.get_module_status('fetch_dix')
print(status)
# {'failure_count': 1, 'is_circuit_broken': False, 'status': 'DEGRADED'}

# 重置（成功后调用）
fallback.reset_failure_count('fetch_dix')
```

**重试装饰器**:
```python
from utils.fallback_manager import handle_fetch_errors

@handle_fetch_errors(max_retries=3)
async def fetch_spy_price():
    response = await session.get('https://api.example.com/price')
    return await response.json()

# 自动重试3次，失败后返回None
price = await fetch_spy_price()
if price is None:
    print("获取失败，已触发熔断")
```

---

## ⏰ 任务时间表

### 盘中任务 (美东时间 9:30-16:00)

| 任务ID | 名称 | 频率 | 说明 |
|--------|------|------|------|
| `calculate_gex` | 计算GEX敞口 | 每15分钟 | 从Tradier获取期权链 |
| `analyze_vix` | VIX期限结构分析 | 每15分钟 | 检测Contango/Backwardation |
| `monitor_crypto` | 加密市场监控 | 每5分钟 | BTC资金费率和OI |
| `check_dbmf` | DBMF均线收复检测 | 每15分钟 | 暗盘流动性信号 |
| `evaluate_resonance` | 共振评估与信号触发 | 每15分钟 | 综合评分并告警 |

### 盘后任务 (美东时间)

| 任务ID | 名称 | 时间 | 说明 |
|--------|------|------|------|
| `fetch_dix` | 获取DIX指标 | 20:30 | SqueezeMetrics暗盘指数 |
| `fetch_chartexchange` | 抓取卖空比 | 20:35 | ChartExchange场外卖空数据 |
| `fetch_stockgrid` | 抓取净头寸 | 20:40 | Stockgrid机构持仓 |
| `update_alpha` | 更新α系数 | 21:00 | GEX校准系数 |
| `backup_database` | 数据库备份 | 21:30 | SQLite备份到backups目录 |

---

## 🔧 配置参数

### 调度器配置

在 `config/settings.py` 中调整：

```python
# 盘中抓取间隔（秒）
INTRADAY_FETCH_INTERVAL = 900  # 15分钟

# 信号冷却时间（分钟）
SIGNAL_COOLDOWN_MINUTES = 30

# 最大重试次数
MAX_RETRIES = 3

# 熔断阈值（连续失败次数）
CIRCUIT_BREAK_THRESHOLD = 5
```

### 修改任务频率

编辑 `main_scheduler.py` 中的 `setup_intraday_tasks()` 方法：

```python
# 改为每10分钟执行
self.scheduler.add_job(
    self.task_calculate_gex,
    trigger='cron',
    minute='*/10',  # 修改这里
    hour='9-16',
    ...
)
```

---

## 🐛 故障排查

### 问题1: 调度器无法启动

**症状**: 导入时卡住或报错

**解决**:
```bash
# 检查依赖
py -m pip install -r requirements.txt

# 检查数据库
ls ./database/monitoring.db

# 查看详细日志
cat ./logs/app_YYYYMMDD.log
```

### 问题2: 任务未执行

**症状**: 日志中没有任务执行记录

**检查**:
```python
scheduler = MainScheduler()
scheduler.setup_intraday_tasks()
scheduler.setup_afterhours_tasks()

# 查看所有任务
for job in scheduler.scheduler.get_jobs():
    print(f"{job.id}: {job.next_run_time}")
```

### 问题3: 熔断频繁触发

**症状**: 日志中出现大量 `[CIRCUIT BREAK]` 消息

**解决**:
1. 检查API密钥配置
2. 检查网络连接
3. 临时提高熔断阈值：
```python
fallback.should_circuit_break('module_name', threshold=10)
```

### 问题4: 时区错误

**症状**: 任务在不期望的时间执行

**解决**:
```python
import pytz
from datetime import datetime

# 确认当前美东时间
eastern = pytz.timezone('US/Eastern')
print(datetime.now(eastern))
```

---

## 📊 监控与调试

### 查看实时日志

```bash
# Windows PowerShell
Get-Content ./logs/app_YYYYMMDD.log -Wait -Tail 50

# Linux/Mac
tail -f ./logs/app_YYYYMMDD.log
```

### 查询数据库

```python
from database.db_manager import DatabaseManager

db = DatabaseManager()

# 查看最新GEX记录
latest_gex = db.get_latest_gex()
print(latest_gex)

# 查看今日信号
from datetime import date
alerts = db.get_signal_alerts_by_date(date.today())
print(f"今日信号数: {len(alerts)}")

db.close()
```

### 测试单个任务

```python
import asyncio
from main_scheduler import MainScheduler

async def test_single_task():
    scheduler = MainScheduler()
    
    # 单独执行GEX计算任务
    await scheduler.task_calculate_gex()
    
    # 检查结果
    latest_gex = scheduler.db.get_latest_gex()
    print(f"Latest GEX: {latest_gex}")

asyncio.run(test_single_task())
```

---

## 🎯 常用场景

### 场景1: 临时禁用某个任务

```python
scheduler = MainScheduler()
scheduler.setup_intraday_tasks()
scheduler.setup_afterhours_tasks()

# 移除特定任务
scheduler.scheduler.remove_job('monitor_crypto')

scheduler.start()
```

### 场景2: 手动触发任务

```python
import asyncio
from main_scheduler import MainScheduler

async def manual_trigger():
    scheduler = MainScheduler()
    
    # 手动执行共振评估
    await scheduler.task_evaluate_resonance()

asyncio.run(manual_trigger())
```

### 场景3: 自定义降级策略

```python
from utils.fallback_manager import FallbackManager

class CustomFallbackManager(FallbackManager):
    def handle_darkpool_fallback(self, *args, **kwargs):
        result = super().handle_darkpool_fallback(*args, **kwargs)
        
        # 添加自定义逻辑
        if result['mode'] == 'DEGRADED':
            # 发送紧急通知
            self.send_emergency_alert()
        
        return result
    
    def send_emergency_alert(self):
        print("🚨 紧急通知: 所有暗盘数据源失效!")
```

---

## 📚 API参考

### MainScheduler

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `__init__()` | 无 | - | 初始化调度器 |
| `setup_intraday_tasks()` | 无 | - | 设置盘中任务 |
| `setup_afterhours_tasks()` | 无 | - | 设置盘后任务 |
| `start()` | 无 | - | 启动调度器（阻塞） |
| `shutdown()` | 无 | - | 关闭调度器 |
| `get_task_status()` | 无 | `Dict[str, Any]` | 获取所有任务状态 |

### FallbackManager

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `handle_darkpool_fallback()` | 3个bool | `dict` | 暗盘降级逻辑 |
| `record_failure()` | module_name: str | - | 记录失败 |
| `should_circuit_break()` | module_name: str, threshold: int | bool | 检查熔断 |
| `reset_failure_count()` | module_name: str | - | 重置计数 |
| `get_module_status()` | module_name: str | dict | 获取状态 |
| `clear_all_failures()` | 无 | - | 清除所有记录 |

---

## 💡 最佳实践

1. **始终使用异步**: 所有网络IO操作使用`async/await`
2. **独立异常处理**: 每个任务独立的try-except
3. **合理设置超时**: 避免任务长时间阻塞
4. **定期检查日志**: 监控任务执行状态
5. **备份数据库**: 每日自动备份，定期手动验证
6. **测试降级逻辑**: 模拟数据源失败场景
7. **监控熔断状态**: 及时发现系统性问题

---

**最后更新**: 2026-06-09  
**版本**: v1.0
