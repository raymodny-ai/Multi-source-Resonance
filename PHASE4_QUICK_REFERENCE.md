# Phase 4 量化逻辑层 - 快速参考

## 快速开始

### 导入模块
```python
from quant_logic import (
    GEXCalculator,
    VIXAnalyzer, 
    CryptoLeverageCleaner,
    DarkPoolVerifier
)
```

---

## 1. GEX计算引擎

### 初始化
```python
calc = GEXCalculator()
```

### 计算单个期权Delta和Gamma
```python
delta = calc.calculate_delta(
    strike=100,
    spot=105,
    volatility=0.2,
    time_to_expiry=0.25,  # 年
    option_type='CALL'
)

gamma = calc.calculate_gamma(
    strike=100,
    spot=105,
    volatility=0.2,
    time_to_expiry=0.25
)
```

### 计算投资组合GEX
```python
import pandas as pd

option_chain = pd.DataFrame({
    'strike': [95, 100, 105],
    'type': ['CALL', 'CALL', 'PUT'],
    'expiry': ['2024-01-19'] * 3,
    'bid': [10.0, 5.0, 3.0],
    'ask': [10.5, 5.5, 3.5],
    'volume': [100, 200, 150],
    'open_interest': [1000, 2000, 1500],
    'implied_volatility': [0.25, 0.2, 0.22],
    'days_to_expiry': [30, 30, 30]
})

gex_result = calc.calculate_portfolio_gex(option_chain, spot_price=105.0)

# 结果
print(f"总GEX: ${gex_result['total_gex']:,.2f}")
print(f"净GEX: ${gex_result['net_gex']:,.2f}")
```

### 识别Flip Zone
```python
gex_profile = {100: -500000, 105: -100000, 110: 200000}
flip_zone = calc.identify_flip_zone(gex_profile)

print(f"翻转区间: [{flip_zone['flip_zone_lower']}, {flip_zone['flip_zone_upper']}]")
print(f"精确翻转点: ${flip_zone['flip_point']:.2f}")
```

### 寻找Put Wall
```python
put_wall = calc.find_put_wall(gex_result['gex_by_strike'])
print(f"Put Wall支撑位: ${put_wall}")
```

### 校准系数
```python
alpha = GEXCalculator.calibrate_alpha(local_gex=1000000, official_gex=1200000)
calibrated_gex = GEXCalculator.apply_calibration(gex_local=1000000, alpha=alpha)
```

---

## 2. VIX期限结构分析器

### 初始化
```python
analyzer = VIXAnalyzer()
```

### 分析期限结构
```python
result = analyzer.analyze_term_structure(vx1=15.0, vx2=16.0)

print(f"状态: {result['state']}")  # CONTANGO/BACKWARDATION/NEUTRAL
print(f"比值: {result['ratio']:.3f}")
print(f"是否极端Backwardation: {result['is_extreme_backwardation']}")
```

### 计算恐慌溢价
```python
panic = analyzer.calculate_panic_premium(vix_spot=15.0, vx1=18.0)

print(f"恐慌溢价: {panic['premium_pct']:.2f}%")
print(f"是否恐慌: {panic['is_panic']}")
```

### 计算VIX信号分值
```python
score = analyzer.get_vix_score(vx1=14.0, vx2=16.0, slope_direction='DOWN')
# 返回值: 0.0 (无信号), 0.5 (左侧枯竭), 1.0 (右侧确认)
```

### 市场状态解释
```python
interpretation = analyzer.interpret_term_structure(vx1=15.0, vx2=16.0)
print(interpretation)
```

### 快速分析
```python
from quant_logic import quick_vix_analysis

result = quick_vix_analysis(vx1=18.0, vx2=16.0, vix_spot=15.0)
```

---

## 3. 加密杠杆清洗判定引擎

### 初始化
```python
cleaner = CryptoLeverageCleaner()
```

### 检测资金费率异常
```python
is_anomaly = cleaner.check_funding_rate_anomaly(funding_rate=-0.0002)
# True表示费率 < -0.01%,需激活清算监控
```

### 检测OI断崖式下跌
```python
historical_oi = [1000, 1050, 1100, 1200, 1300, 1350]
result = cleaner.detect_oi_crash(current_oi=1000, historical_oi_list=historical_oi)

print(f"检测到暴跌: {result['crash_detected']}")
print(f"下跌幅度: {result['drop_percentage']:.2f}%")
```

### 综合判定去杠杆完成
```python
cleanup = cleaner.confirm_leverage_cleanup(
    funding_rate=0.0001,      # 费率转正
    oi_drop_pct=20.0,          # OI下跌20%
    elr_current=2.5,           # 当前ELR
    elr_historical_avg=3.0     # 历史平均ELR
)
# 返回True表示三条件同时满足
```

### 计算加密信号分值
```python
score = cleaner.get_crypto_score(
    oi_crash=True,
    funding_positive=True,
    elr_safe=True
)
# 返回值: 0.0 (无信号), 0.5 (清算中), 1.0 (完成)
```

### 综合分析
```python
analysis = cleaner.analyze_leverage_state(
    funding_rate=0.0001,
    current_oi=48000,
    historical_oi_list=[50000, 55000, 60000, 61000],
    elr_current=2.3,
    elr_historical_avg=3.0
)

print(f"阶段: {analysis['stage']}")  # NORMAL/IN_PROGRESS/COMPLETED
print(f"分值: {analysis['signal_score']}")
```

### 快速检查
```python
from quant_logic import quick_leverage_check

result = quick_leverage_check(funding_rate, current_oi, historical_oi, elr_current, elr_avg)
```

---

## 4. 暗盘三驾马车验证引擎

### 初始化
```python
verifier = DarkPoolVerifier()
```

### DIX阈值检测
```python
dix_active = verifier.check_dix_threshold(dix_value=50.0)
# True表示DIX > 45%
```

### 卖空比连续性检测
```python
short_data = [50.0, 48.0, 42.0]  # 最近3天数据
short_active = verifier.check_short_volume_consecutive(short_data)
# True表示连续2天 > 45%
```

### Stockgrid信号确认
```python
stockgrid_active = verifier.confirm_stockgrid_signal(
    divergence_flag=False,
    slope_20d=0.85,
    slope_60d=0.62
)
# True表示底背离或双周期斜率均为正
```

### 三选二聚合
```python
aggregation = verifier.aggregate_darkpool_signals(
    dix_flag=True,
    short_ratio_flag=True,
    stockgrid_flag=False
)

print(f"触发信号数: {aggregation['signal_count']}")
print(f"聚合信号: {aggregation['aggregated_signal']}")  # >=2为True
```

### 计算暗盘信号分值
```python
score = verifier.get_darkpool_score(
    dix_flag=True,
    short_ratio_flag=True,
    stockgrid_flag=False,
    dbmf_recovery=True
)
# 返回值: 0.0 (无信号), 0.75 (三选二), 1.5 (三选二+DBMF)
```

### 完整验证流程
```python
result = verifier.full_verification(
    dix_value=52.0,
    short_volume_days=[48.0, 50.0, 46.0],
    divergence_flag=False,
    slope_20d=0.85,
    slope_60d=0.62,
    dbmf_recovery=True
)

print(f"最终分值: {result['final_score']}")
print(f"信号强度: {result['signal_strength']}")  # WEAK/MODERATE/VERY STRONG
```

### 快速检查
```python
from quant_logic import quick_darkpool_check

result = quick_darkpool_check(dix, short_volumes, divergence, slope_20, slope_60, dbmf_recovered)
```

---

## 多维度共振矩阵示例

```python
from quant_logic import (
    GEXCalculator,
    VIXAnalyzer,
    CryptoLeverageCleaner,
    DarkPoolVerifier
)

# 初始化所有分析器
gex_calc = GEXCalculator()
vix_analyzer = VIXAnalyzer()
crypto_cleaner = CryptoLeverageCleaner()
darkpool_verifier = DarkPoolVerifier()

# 1. GEX维度评分
gex_result = gex_calc.calculate_portfolio_gex(option_chain_df, spot_price)
gex_score = 1.0 if gex_result['net_gex'] > 0 else 0.5

# 2. VIX维度评分
vix_score = vix_analyzer.get_vix_score(vx1=14.0, vx2=16.0, slope_direction='DOWN')

# 3. 加密维度评分
crypto_score = crypto_cleaner.get_crypto_score(
    oi_crash=True, funding_positive=True, elr_safe=True
)

# 4. 暗盘维度评分
darkpool_score = darkpool_verifier.get_darkpool_score(
    dix_flag=True, short_ratio_flag=True, stockgrid_flag=False, dbmf_recovery=True
)

# 计算共振总分
total_score = gex_score + vix_score + crypto_score + darkpool_score
max_score = 4.5  # 1.0 + 1.0 + 1.0 + 1.5
resonance_pct = (total_score / max_score) * 100

print(f"共振强度: {resonance_pct:.1f}%")

if resonance_pct >= 75:
    print("信号等级: STRONG BUY")
elif resonance_pct >= 50:
    print("信号等级: MODERATE BUY")
else:
    print("信号等级: WEAK SIGNAL")
```

---

## 常见参数说明

### GEX计算参数
- `volatility`: 隐含波动率,范围0.01~5.0 (1%~500%)
- `time_to_expiry`: 到期时间,单位为年 (30天 = 30/365 ≈ 0.082)
- `option_type`: 'CALL' 或 'PUT'

### VIX分析参数
- `vx1`: 近月期货价格
- `vx2`: 次月期货价格
- `slope_direction`: 'UP' 或 'DOWN'

### 加密杠杆参数
- `funding_rate`: 资金费率,小数形式 (-0.0001 = -0.01%)
- `historical_oi_list`: 过去1小时OI列表,每5分钟一个点
- `elr_current`: CryptoQuant预估杠杆率
- `elr_historical_avg`: ELR历史均值

### 暗盘验证参数
- `dix_value`: SqueezeMetrics DIX百分比值 (0-100)
- `days_data`: 卖空比历史数据,按时间倒序排列
- `divergence_flag`: 底背离标志 (True/False)
- `slope_20d`: 20日净头寸趋势线斜率
- `slope_60d`: 60日净头寸趋势线斜率
- `dbmf_recovery`: DBMF均线收复标志 (True/False)

---

## 错误处理

### 除零保护
所有除法操作都有除零检查,返回安全默认值:
```python
# 如果vx2=0,ratio默认为1.0
result = analyzer.analyze_term_structure(vx1=15.0, vx2=0)
```

### None值处理
```python
# DIX=None时返回False
dix_active = verifier.check_dix_threshold(dix_value=None)
```

### 空数据处理
```python
# 空DataFrame返回全0结果
empty_result = calc.calculate_portfolio_gex(pd.DataFrame(), 100.0)
```

---

## 日志级别

- **DEBUG**: 正常计算过程
- **INFO**: 关键事件(信号激活、状态变化)
- **WARNING**: 异常情况(费率异常、OI暴跌、恐慌状态)
- **ERROR**: 系统错误

### 调整日志级别
```python
from utils.logger import setLogLevel

setLogLevel('DEBUG')  # 显示所有日志
setLogLevel('WARNING')  # 仅显示警告和错误
```

---

## 性能提示

### 向量化运算
使用Pandas DataFrame批量计算,避免Python循环:
```python
# ✅ 推荐: 向量化
gex_result = calc.calculate_portfolio_gex(option_chain_df, spot_price)

# ❌ 不推荐: 逐个计算
for idx, row in option_chain_df.iterrows():
    gamma = calc.calculate_gamma(...)
```

### 缓存结果
对于重复计算,建议缓存结果:
```python
from functools import lru_cache

@lru_cache(maxsize=128)
def cached_gamma(strike, spot, vol, tte):
    return calc.calculate_gamma(strike, spot, vol, tte)
```

---

## 测试运行

```bash
# 运行所有测试
py tests/test_phase4_quant_logic.py

# 运行使用示例
py examples_phase4_usage.py
```

---

## 更多信息

- 详细文档: `PHASE4_COMPLETION_REPORT.md`
- 完整示例: `examples_phase4_usage.py`
- 测试用例: `tests/test_phase4_quant_logic.py`
