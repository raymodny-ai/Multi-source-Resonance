# Phase 5 信号引擎 - 快速参考手册

## 🚀 快速开始

### 1. 导入模块
```python
from signal_engine import ResonanceScorer, SignalStateMachine, format_alert_message
from datetime import datetime
import pytz
```

### 2. 初始化
```python
scorer = ResonanceScorer()
state_machine = SignalStateMachine(cooldown_minutes=30)
eastern = pytz.timezone('US/Eastern')
```

---

## 📊 评分API速查

### GEX维度评分
```python
result = scorer.calculate_gex_score(
    gex_local=-5e6,           # 本地估算GEX (美元)
    gex_calibrated=2e6,       # 校准后GEX (美元)
    flip_zone_crossed=True,   # 是否跨越翻转线
    gex_trend='IMPROVING'     # 'IMPROVING' | 'STABLE' | 'DETERIORATING'
)
# 返回: {'score': 1.5, 'state': 'POSITIVE', 'details': '...'}
```

**评分规则**:
- GEX翻正: **1.5分** (POSITIVE)
- GEX收敛: **0.75分** (CONVERGING)
- GEX恶化: **0.0分** (NEGATIVE)

---

### VIX维度评分
```python
result = scorer.calculate_vix_score(
    term_structure_ratio=0.95,  # VX1/VX2比值
    slope_direction='DOWN',     # 'UP' | 'DOWN'
    panic_premium=5.2           # 恐慌溢价百分比
)
# 返回: {'score': 1.0, 'state': 'CONTANGO', 'details': '...'}
```

**评分规则**:
- Backwardation > 1.15: **0.5分** (BACKWARDATION)
- Contango < 1.0 且斜率向下: **1.0分** (CONTANGO)
- 其他: **0.0分** (NEUTRAL)

---

### 加密维度评分
```python
result = scorer.calculate_crypto_score(
    oi_crash=True,                  # OI是否暴跌>15%
    funding_positive=True,          # 资金费率是否转正
    elr_safe=True,                  # ELR是否安全
    leverage_cleanup_confirmed=True # 去杠杆是否完成
)
# 返回: {'score': 1.0, 'state': 'CLEANUP_COMPLETE', 'details': '...'}
```

**评分规则**:
- 去杠杆完成: **1.0分** (CLEANUP_COMPLETE)
- 仅OI暴跌: **0.5分** (IN_PROGRESS)
- 高杠杆: **0.0分** (HIGH_LEVERAGE)

---

### 暗盘维度评分
```python
result = scorer.calculate_darkpool_score(
    dix_flag=True,              # DIX>45%信号
    short_ratio_flag=True,      # 卖空比>45%信号
    stockgrid_flag=False,       # Stockgrid拐点信号
    dbmf_recovery=True,         # DBMF均线收复
    aggregated_signal=True      # 三选二聚合信号
)
# 返回: {'score': 1.5, 'state': 'STRONG_ACCUMULATION', 'details': '...'}
```

**评分规则**:
- 三选二 + DBMF收复: **1.5分** (STRONG_ACCUMULATION)
- 仅三选二: **0.75分** (MODERATE)
- 其他: **0.0分** (WEAK)

---

### 综合共振评分
```python
resonance = scorer.calculate_total_score(gex, vix, crypto, darkpool)
# 返回: {
#     'total_score': 5.0,
#     'max_score': 5.0,
#     'resonance_pct': 100.0,
#     'alert_level': 'LEVEL_3',
#     'dimension_scores': {...},
#     'trigger_conditions': [...]
# }
```

**预警分级**:
- **LEVEL_3**: 总分 >= 3.5 (共振抄底信号) 🚨
- **LEVEL_2**: 3.0 <= 总分 < 3.5 (密切监控) ⚠️
- **LEVEL_1**: 2.0 <= 总分 < 3.0 (初步关注) 📊
- **NO_SIGNAL**: 总分 < 2.0

---

## 🔥 Hawkes Process测算

```python
hawkes = scorer.estimate_hawkes_branching_ratio(
    recent_price_changes=[-0.5, -0.8, -1.2, -0.3, -0.6],  # 价格变化 (%)
    recent_volumes=[1e6, 1.5e6, 2e6, 1.2e6, 1.8e6],       # 成交量
    window_minutes=60                                       # 时间窗口
)
# 返回: {
#     'branching_ratio': 0.84,
#     'state': 'CRITICAL',
#     'self_excitation_intensity': 84.0,
#     'details': '...'
# }
```

**状态判定**:
- 分支比 < 0.7: **SUBCRITICAL** (亚临界衰竭)
- 分支比 0.7~0.9: **CRITICAL** (临界状态)
- 分支比 > 0.9: **SUPERCRITICAL** (超临界恐慌)

---

## ⚙️ 状态机API

### 检查并触发告警
```python
now = datetime.now(eastern)
trigger = state_machine.check_and_trigger(resonance, now)

if trigger['should_alert']:
    print(f"触发告警! 级别: {trigger['alert_level']}")
    print(f"原因: {trigger['reason']}")
else:
    print(f"跳过告警: {trigger['reason']}")
    print(f"剩余冷却时间: {trigger['cooldown_remaining']}分钟")
```

### 获取状态摘要
```python
summary = state_machine.get_state_summary()
print(f"当前状态: {summary['current_state']}")
print(f"总告警次数: {summary['total_alerts']}")
print(f"最近告警: {summary['recent_alerts']}")
```

### 重置状态机
```python
state_machine.reset()
```

### 辅助方法
```python
# 检查是否在冷却期
if state_machine.is_in_cooldown(now):
    remaining = state_machine.get_cooldown_remaining(now)
    print(f"冷却中，剩余{remaining}分钟")
```

---

## 📧 告警消息格式化

```python
message = format_alert_message(resonance, hawkes, now)
print(message)
```

**输出示例**:
```
🚨 [SYSTEM ALERT] 流动性清算衰竭:多因子共振抄底信号触发
⏰ 触发时间:2026-06-09 11:40:20 EST
当前共振得分:5.0 / 5.0(100.0%)

📊 美股微观结构与价格行为
• 做市商GEX:GEX已翻正至+$2.0M, 做市商自动托底对冲激活
• VIX期限结构:VIX回归Contango(0.95), 恐慌退潮确认

🏛️ 华尔街暗盘大资金追踪
• 暗盘吸筹:暗盘强吸筹确认(2/3指标触发 + DBMF收复)

🌐 加密金丝雀多源校验
• 杠杆清洗:加密市场去杠杆完成,费率转正+OI清洗+ELR安全

🤖 系统量化提示
基于Hawkes Process测算,分支比0.84处于临界状态, 警惕恐慌蔓延

✅ 触发条件:
  - GEX: GEX已翻正至+$2.0M, 做市商自动托底对冲激活
  - VIX: VIX回归Contango(0.95), 恐慌退潮确认
  - CRYPTO: 加密市场去杠杆完成,费率转正+OI清洗+ELR安全
  - DARKPOOL: 暗盘强吸筹确认(2/3指标触发 + DBMF收复)
```

---

## 🔄 完整工作流程

```python
from signal_engine import ResonanceScorer, SignalStateMachine, format_alert_message
from datetime import datetime
import pytz

# 1. 初始化
scorer = ResonanceScorer()
state_machine = SignalStateMachine(cooldown_minutes=30)
eastern = pytz.timezone('US/Eastern')

# 2. 获取数据 (从各个数据源)
gex_data = fetch_gex_data()        # 实现你的数据获取逻辑
vix_data = fetch_vix_data()
crypto_data = fetch_crypto_data()
darkpool_data = fetch_darkpool_data()
price_volume_data = fetch_market_data()

# 3. 计算各维度评分
gex_score = scorer.calculate_gex_score(**gex_data)
vix_score = scorer.calculate_vix_score(**vix_data)
crypto_score = scorer.calculate_crypto_score(**crypto_data)
darkpool_score = scorer.calculate_darkpool_score(**darkpool_data)

# 4. 计算共振总分
resonance = scorer.calculate_total_score(gex_score, vix_score, crypto_score, darkpool_score)

# 5. Hawkes Process测算
hawkes = scorer.estimate_hawkes_branching_ratio(
    recent_price_changes=price_volume_data['prices'],
    recent_volumes=price_volume_data['volumes']
)

# 6. 检查是否触发告警
now = datetime.now(eastern)
trigger = state_machine.check_and_trigger(resonance, now)

# 7. 发送告警 (如果触发)
if trigger['should_alert']:
    message = format_alert_message(resonance, hawkes, now)
    send_notification(message)  # 实现你的通知发送逻辑
    print(f"✅ 告警已发送: {trigger['alert_level']}")
else:
    print(f"⏸️  跳过告警: {trigger['reason']}")
```

---

## 🎯 常见场景

### 场景1: 首次检测到强共振信号
```python
# 所有维度都达到最高分
gex = {'score': 1.5, 'state': 'POSITIVE', 'details': '...'}
vix = {'score': 1.0, 'state': 'CONTANGO', 'details': '...'}
crypto = {'score': 1.0, 'state': 'CLEANUP_COMPLETE', 'details': '...'}
darkpool = {'score': 1.5, 'state': 'STRONG_ACCUMULATION', 'details': '...'}

resonance = scorer.calculate_total_score(gex, vix, crypto, darkpool)
# total_score: 5.0, alert_level: LEVEL_3
```

### 场景2: 部分维度触发
```python
# 只有GEX和暗盘触发
gex = {'score': 1.5, 'state': 'POSITIVE', 'details': '...'}
vix = {'score': 0.0, 'state': 'NEUTRAL', 'details': '...'}
crypto = {'score': 0.0, 'state': 'HIGH_LEVERAGE', 'details': '...'}
darkpool = {'score': 0.75, 'state': 'MODERATE', 'details': '...'}

resonance = scorer.calculate_total_score(gex, vix, crypto, darkpool)
# total_score: 2.25, alert_level: LEVEL_1
```

### 场景3: 冷却期内重复检测
```python
# 第一次触发
trigger1 = state_machine.check_and_trigger(resonance, now)
# should_alert: True

# 5分钟后再次检测
later = now + timedelta(minutes=5)
trigger2 = state_machine.check_and_trigger(resonance, later)
# should_alert: False, cooldown_remaining: 25
```

---

## ⚠️ 注意事项

1. **时区处理**: 所有时间使用EST (美东时间)
   ```python
   eastern = pytz.timezone('US/Eastern')
   now = datetime.now(eastern)
   ```

2. **异常处理**: 所有评分方法都有内置异常处理，失败时返回安全默认值
   ```python
   try:
       result = scorer.calculate_gex_score(...)
   except Exception as e:
       logger.error(f"评分失败: {e}")
   ```

3. **数据验证**: Hawkes Process需要至少10个数据点
   ```python
   if len(prices) < 10 or len(volumes) < 10:
       # 返回 INSUFFICIENT_DATA 状态
   ```

4. **冷却时间调整**: 根据市场波动性调整冷却时间
   ```python
   # 高波动市场: 缩短冷却时间
   sm = SignalStateMachine(cooldown_minutes=15)
   
   # 低波动市场: 延长冷却时间
   sm = SignalStateMachine(cooldown_minutes=60)
   ```

---

## 📚 相关文档

- [Phase 5 完成报告](PHASE5_COMPLETION_REPORT.md)
- [使用示例](examples_phase5_signal_engine.py)
- [测试套件](tests/test_phase5_signal_engine.py)
- [PRD 4.2节 - 告警消息模板](多源共振暗盘与流动性微观结构盘中自动监控系统.md)

---

## 🔍 调试技巧

### 查看详细日志
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 检查状态机内部状态
```python
summary = state_machine.get_state_summary()
print(summary)
```

### 手动重置状态机
```python
state_machine.reset()
```

### 测试单个维度评分
```python
# 单独测试GEX评分
gex = scorer.calculate_gex_score(-5e6, 2e6, True, 'IMPROVING')
print(f"GEX评分: {gex['score']}, 状态: {gex['state']}")
```

---

**最后更新**: 2026-06-09  
**版本**: Phase 5 v1.0
