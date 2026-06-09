# 多源共振项目 PRD 合规性完整审查报告

**审查日期**: 2026-06-09
**审查范围**: 基于 PRD 文档《多源共振暗盘与流动性微观结构盘中自动监控系统.md》与当前代码库完整对比
**审查结论**: **项目骨架与 PRD 高度对齐，核心量化逻辑已实现，但数据获取层存在关键缺口，部分模块停留在"可运行的存根"阶段，需人工审核后修复方可投入生产**

---

## 一、项目结构符合度总览

仓库分层清晰，与 PRD 描述的四大功能域完全对应：

| PRD 功能域 | 对应代码模块 | 覆盖状态 | 备注 |
| :-- | :-- | :-- | :-- |
| 做市商 Gamma 计算 | `quant_logic/gex_calculator.py` | ✅ 已实现 | Black-Scholes 模型完整 |
| VIX 期限结构分析 | `quant_logic/vix_analyzer.py` | ✅ 已实现 | Contango/Backwardation 判定准确 |
| 加密衍生品去杠杆判定 | `quant_logic/crypto_leverage_cleaner.py` | ✅ 已实现 | OI+费率+ELR 三合一 |
| 暗盘三驾马车验证 | `quant_logic/darkpool_verifier.py` | ✅ 已实现 | 投票机制正确 |
| 信号共振矩阵评分 | `signal_engine/resonance_scorer.py` | ✅ 已实现 | 满分5分机制完整 |
| 信号触发与状态机 | `signal_engine/signal_trigger.py` | ✅ 已实现 | 冷却期+持久化 |
| 数据抓取层 | `data_fetchers/` (7个文件) | ⚠️ 部分存根 | ChartExchange/Stockgrid/SqueezeMetrics 端点未验证 |
| 通知预警推送 | `notification/alert_sender.py` | ✅ 已实现 | Email/Telegram/Discord |
| 主调度器 | `main_scheduler.py` | ✅ 已实现 | 10个定时任务注册 |
| 异常容错降级 | `utils/fallback_manager.py` | ⚠️ 部分实现 | 三级降级框架存在，动态权重未实现 |

---

## 二、核心逻辑审查：符合 PRD ✅

### 2.1 信号共振矩阵（满分 5 分机制）✅

**文件**: [`signal_engine/resonance_scorer.py`](signal_engine/resonance_scorer.py:334-450)

`resonance_scorer.py` 完整实现了 PRD 第 4.1 节规定的四维度加权评分：

- **GEX 维度**：1.5 分（翻转线跨越给满分，IMPROVING 给 0.75 分）✅
- **VIX 期限结构**：1.0 分（回归 Contango + 斜率向下给满分）✅
- **加密去杠杆**：1.0 分（OI+费率+ELR 三合一确认给满分）✅
- **暗盘维度**：1.5 分（三选二 + DBMF 收复给满分）✅

触发门槛 LEVEL_3 ≥ 3.5 分、LEVEL_2 ≥ 3.0、LEVEL_1 ≥ 2.0，与 PRD 完全一致。

### 2.2 暗盘三驾马车验证 ✅

**文件**: [`quant_logic/darkpool_verifier.py`](quant_logic/darkpool_verifier.py:22-403)

`darkpool_verifier.py` 精确实现了 PRD 第 3.2 节的三维投票机制：

- DIX > 45% 基线判定 ✅ ([check_dix_threshold](quant_logic/darkpool_verifier.py:38))
- ChartExchange 场外卖空比连续 2 日 > 45% ✅ ([check_short_volume_consecutive](quant_logic/darkpool_verifier.py:71))
- Stockgrid 底背离（斜率转正 OR 底背离标志）✅ ([confirm_stockgrid_signal](quant_logic/darkpool_verifier.py:140))
- 三选二聚合机制 `aggregate_darkpool_signals()` ✅ ([aggregate_darkpool_signals](quant_logic/darkpool_verifier.py:197))

### 2.3 Hawkes Process 自激测算 ✅

**文件**: [`signal_engine/resonance_scorer.py`](signal_engine/resonance_scorer.py:452-575)

`estimate_hawkes_branching_ratio()` 中内置了简化 Hawkes 分支比计算，以价格跌幅与成交量激增的相关性作为代理指标，亚临界 < 0.7 / 临界 0.7~0.9 / 超临界 > 0.9 的分级与 PRD 预警模板示例一致。

### 2.4 告警消息格式化 ✅

**文件**: [`signal_engine/signal_trigger.py`](signal_engine/signal_trigger.py:319-396) 和 [`notification/alert_sender.py`](notification/alert_sender.py:289-366)

- `format_alert_message()` 生成符合 PRD 4.2 节模板的告警文本 ✅
- `AlertSender.format_level3_alert()` 提供 Markdown 格式的 LEVEL 3 告警 ✅

---

## 三、关键技术缺口与待办清单 ⚠️

以下问题按优先级排序，**高优先级问题必须修复后方可投入生产**。

### 🔴 高优先级（Critical - 阻塞生产部署）

#### C1. ChartExchange API 端点未通过真实抓包验证

**涉及文件**: [`data_fetchers/chartexchange_fetcher.py`](data_fetchers/chartexchange_fetcher.py:46-51, 126-132)

**问题描述**:
- 代码中明确标注了多处 `TODO` 注释，API 端点（如 `/api/v1/shortvolume/{symbol}`）为**猜测值**，并非通过实际 F12 抓包验证的真实端点
- 当前代码在无法命中任何候选端点时直接抛出 `DataFetchError`，生产环境下暗盘模块将大概率常态退化
- Mock 模式下生成的随机数据无法反映真实市场状况

**PRD 要求**:
> PRD 第 5.1 节："使用 requests 结合伪装的 User-Agent，直接请求其底层的 JSON 数据端点（通过浏览器 F12 抓包提炼其每日图表更新的底层 API）"

**建议修复方案**:
1. **立即行动**: 手动通过浏览器访问 https://chartexchange.com，打开 F12 Network 面板，筛选 XHR/Fetch 请求，找到真实的短卖量数据 API 端点
2. **代码修改**: 将验证后的端点写入 `config/settings.py` 的 `ChartExchangeEndpoints` 类
3. **增加自检**: 在系统启动时运行端点连通性测试，失败时直接进入降级模式
4. **⚠️ 重要补充**: 当所有端点均失败触发 DEGRADED 模式时，必须调用 `AlertSender` 发送**置顶 `[CRITICAL]` 告警**给所有通知渠道（Email/Telegram/Discord），而不仅仅是记录日志。PRD 第 6 节明确要求："并向用户发出置顶警告：[CRITICAL] 场外暗盘所有爬虫接口触发改版异常..."

**参考代码位置**:
```python
# config/settings.py 新增
class ChartExchangeEndpoints:
    SHORT_VOLUME = '/api/v1/shortvolume/{symbol}'  # 待替换为真实端点
    DAILY_DATA = '/data/daily/{symbol}/shortvol'   # 待替换

# data_fetchers/chartexchange_fetcher.py 修改
from config.settings import Config
api_url = Config.ChartExchangeEndpoints.SHORT_VOLUME.format(symbol=symbol)

# main_scheduler.py task_fetch_chartexchange() 异常处理补充
except DataFetchError as e:
    logger.error(f"ChartExchange抓取任务失败: {e}", exc_info=True)
    self.fallback_manager.record_failure('task_fetch_chartexchange')
    
    # ✅ 新增：检查是否触发极端退化，发送CRITICAL告警
    fallback_status = self.fallback_manager.handle_darkpool_fallback(
        squeezemetrics_success=self._check_dix_available(),
        chartexchange_success=False,
        stockgrid_success=self._check_stockgrid_available()
    )
    if fallback_status['mode'] == 'DEGRADED':
        critical_msg = "[CRITICAL] 场外暗盘所有爬虫接口触发改版异常，已退化为纯本地实时衍生品计算流模式，请及时排查前端结构。"
        try:
            self.alert_sender.send_multi_channel_alert(
                subject="[CRITICAL] 暗盘数据源全部失效",
                message=critical_msg,
                channels=['email', 'telegram', 'discord']
            )
        except Exception as alert_err:
            logger.critical(f"CRITICAL告警发送失败: {alert_err}")
```

**预计工作量**: 2-4 小时（含抓包验证 + 代码修改 + 测试）

---

#### C2. Stockgrid XHR 拦截规则与 DOM 选择器未适配真实网站

**涉及文件**: [`data_fetchers/stockgrid_fetcher.py`](data_fetchers/stockgrid_fetcher.py:258-260, 285, 339-340)

**问题描述**:
- XHR 拦截逻辑依赖 URL 中含有 `'darkpool'` 或 `'netposition'` 关键字（第 259 行），这是推测值
- DOM 降级解析的 CSS 选择器 `.darkpool-chart, .net-position-table`（第 285 行）同样是推测值
- PRD 要求使用 Playwright 拦截真实 XHR 响应，但未经实际验证的选择器在 Stockgrid 改版后将立刻失效

**PRD 要求**:
> PRD 第 5.1 节："配置 Playwright 异步无头浏览器（Headless Mode），在美股盘后固定时间（晚上 20:30）模拟访问其 Dark Pool 板块，解析 DOM 结构或直接拦截 XHR 响应获取 net_position 数组"

**建议修复方案**:
1. **立即行动**: 手动访问 https://stockgrid.io/darkpool/SPY，使用浏览器 DevTools 记录 XHR 请求 URL 模式和 DOM 结构
2. **配置外置**: 将 XHR URL 匹配规则和 DOM 选择器抽出到 `config/settings.py` 的 `StockgridAdapter` 类，支持热更新
3. **⚠️ 重要补充 - 集成 tenacity 重试机制**: PRD 第 6 节明确要求对所有网页解析模块强制封装 `tenacity` 装饰器，设定指数退避（5s→15s→45s）+ User-Agent 随机切换。当前 `chartexchange_fetcher.py` 已实现此机制（见第 90-95 行），但 `stockgrid_fetcher.py` **缺失**该容错层，必须补上以保持对称性
4. **增加监控**: 添加 DOM 结构哈希值检测，页面改版时自动发出 WARNING 日志

**参考代码位置**:
```python
# config/settings.py 新增
class StockgridAdapter:
    XHR_URL_PATTERN = 'api/darkpool'  # 待替换为真实模式
    DOM_SELECTOR_CHART = '.darkpool-chart'  # 待替换
    DOM_SELECTOR_TABLE = '.net-position-table'  # 待替换

# data_fetchers/stockgrid_fetcher.py 修改
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from utils.exceptions import DataFetchError

class StockgridFetcher:
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=5, max=45),
        retry=retry_if_exception_type((TimeoutError, ConnectionError)),
        reraise=True
    )
    async def scrape_net_position_history(self, symbol: str = 'SPY', ...):
        # 原有逻辑...
        if Config.StockgridAdapter.XHR_URL_PATTERN in url:
            # 拦截逻辑
        await page.wait_for_selector(Config.StockgridAdapter.DOM_SELECTOR_CHART, timeout=10000)
```

**预计工作量**: 3-5 小时（含网站分析 + 代码重构 + 测试）

---

#### C3. SqueezeMetrics DIX 接口无官方 API 支持

**涉及文件**: [`data_fetchers/squeezemetrics_fetcher.py`](data_fetchers/squeezemetrics_fetcher.py)

**问题描述**:
- 代码访问的端点 `/monitor/dix` 和 `/monitor/gex` 是推测路径
- SqueezeMetrics 官方并未公开商业 API，当前代码在无 Mock 模式下无法正常工作
- DIX 是三驾马车中权重最高的基准维度（PRD 第 3.2 节维度一）

**PRD 要求**:
> PRD 第 3.2 节："每日收盘后自动获取 DIX。若 DIX > 45%，系统标记大资金在暗盘的潜在买入意向"

**⚠️ 关键修正**: SqueezeMetrics 官网实际上以**公开 CSV 文件格式**提供 DIX/GEX 数据下载（`https://squeezemetrics.com/monitor/static/DIX.csv`），并不需要 Playwright 无头浏览器渲染。原报告建议的 Playwright 方案虽然可行，但选择了更复杂的实现路径，增加了不必要的浏览器实例开销，反而与 PRD 第 5.1 节"保障系统不依赖高昂接口、追求鲁棒性"的精神背道而驰。

**正确修复方案**:
1. **✅ 推荐方案 - CSV 直接下载**: 使用 `requests` 直接下载 `https://squeezemetrics.com/monitor/static/DIX.csv`，解析 CSV 获取最新 DIX 值。此方案轻量、稳定、不受 JavaScript 动态渲染影响
2. **备选方案 - 页面解析**: 仅当 CSV 端点失效时，才降级为 Playwright 页面解析
3. **合并任务**: DIX 的 CSV 下载可与 Stockgrid 的异步抓取并行执行（无需共用浏览器实例），进一步减少总耗时

**参考代码位置**:
```python
# data_fetchers/squeezemetrics_fetcher.py 修改
import requests
import csv
from io import StringIO

class SqueezeMetricsFetcher:
    DIX_CSV_URL = 'https://squeezemetrics.com/monitor/static/DIX.csv'
    
    def get_daily_dix(self) -> Optional[float]:
        """通过CSV直接下载获取DIX值"""
        try:
            response = requests.get(
                self.DIX_CSV_URL,
                timeout=Config.REQUEST_TIMEOUT,
                headers={'User-Agent': 'Mozilla/5.0 ...'}
            )
            response.raise_for_status()
            
            # 解析CSV（格式：Date,DIX）
            csv_data = StringIO(response.text)
            reader = csv.reader(csv_data)
            next(reader)  # 跳过表头
            
            # 获取最新一行（最近日期）
            latest_row = next(reader)
            dix_value = float(latest_row[1])
            
            logger.info(f"DIX获取成功: {dix_value}%")
            return dix_value
            
        except Exception as e:
            logger.error(f"CSV下载失败: {e}，尝试备选方案...")
            # 可降级为Playwright方案
            return None

# main_scheduler.py task_fetch_dix() 简化
async def task_fetch_dix(self):
    loop = asyncio.get_event_loop()
    dix_value = await loop.run_in_executor(
        self.executor,
        self.squeezemetrics_fetcher.get_daily_dix
    )
    # 后续逻辑不变...
```

**预计工作量**: 2-3 小时（含CSV格式验证 + 代码修改 + 测试，比原方案节省2-3小时）

---

### 🟡 中优先级（Warning - 影响信号准确性）

#### W1. Stockgrid 20d/60d 斜率计算存在 Bug

**涉及文件**: [`data_fetchers/stockgrid_fetcher.py`](data_fetchers/stockgrid_fetcher.py:419-499)，特别是第 478-479 行

**问题描述**:
```python
# 当前代码（第 478-479 行）
result = {
    'divergence': divergence,
    'slope_20d': float(position_slope),  # ❌ 使用全量序列的斜率
    'slope_60d': float(position_slope),  # ❌ 与 slope_20d 相同！
    ...
}
```

`slope_20d` 和 `slope_60d` 两个字段被赋予了**同一个**斜率值（`float(position_slope)`），没有分别对不同时间窗口切片进行计算。这与 PRD 第 3.2 节要求的"20日和60日累积净头寸趋势线"形成双周期验证的逻辑相悖。

**PRD 要求**:
> PRD 第 3.2 节："提取 Stockgrid 中针对 SPY/QQQ 过去 20、60、120 个交易日内的累积美元买入/卖出倾向曲线...当 20 日和 60 日累积净头寸趋势线在底部形成底背离、斜率转正（拐头向上）时..."

**建议修复方案**:
对传入的完整净头寸序列分别取最后 20 个和最后 60 个数据点做独立的 `polyfit` 拟合，返回两个独立斜率值。

**参考修复代码**:
```python
# data_fetchers/stockgrid_fetcher.py detect_bottom_divergence() 修复
def detect_bottom_divergence(
    self,
    net_position_series: List[float],
    price_series: List[float]
) -> Dict[str, Any]:
    try:
        if len(net_position_series) < 60 or len(price_series) < 60:
            logger.warning("数据点不足60个，无法计算双周期斜率")
            return {...}

        x = np.arange(len(net_position_series))

        # 分别计算20日和60日窗口的斜率
        if len(net_position_series) >= 60:
            recent_60 = net_position_series[-60:]
            x_60 = np.arange(60)
            slope_60d = float(np.polyfit(x_60, recent_60, 1)[0])
        else:
            slope_60d = float(np.polyfit(x, net_position_series, 1)[0])

        if len(net_position_series) >= 20:
            recent_20 = net_position_series[-20:]
            x_20 = np.arange(20)
            slope_20d = float(np.polyfit(x_20, recent_20, 1)[0])
        else:
            slope_20d = slope_60d  #  fallback

        # 价格趋势判断（使用相同窗口）
        if len(price_series) >= 60:
            recent_price_60 = price_series[-60:]
            price_slope = float(np.polyfit(np.arange(60), recent_price_60, 1)[0])
        else:
            price_slope = float(np.polyfit(x, price_series, 1)[0])

        position_trend = 'up' if slope_20d > 0 else ('down' if slope_20d < 0 else 'flat')
        price_trend = 'up' if price_slope > 0 else ('down' if price_slope < 0 else 'flat')

        # 底背离：价格下跌但净头寸上升
        divergence = (price_trend == 'down' and position_trend == 'up')

        return {
            'divergence': divergence,
            'slope_20d': slope_20d,
            'slope_60d': slope_60d,
            'price_trend': price_trend,
            'position_trend': position_trend
        }
    except Exception as e:
        logger.error(f"检测底背离失败: {str(e)}", exc_info=True)
        return {...}
```

**预计工作量**: 1-2 小时（含单元测试）

---

#### W2. 异常降级逻辑未完整实现 PRD 第 6 节

**涉及文件**: [`signal_engine/resonance_scorer.py`](signal_engine/resonance_scorer.py:334-450)，[`utils/fallback_manager.py`](utils/fallback_manager.py:48-115)

**问题描述**:
PRD 第 6 节规定了三级降级机制：
1. **完整运行模式**: 同时轮询三方数据进行交集确认
2. **轻度网络故障容错**: 若某源抓取失败，自动放弃该校验，将判定权交给其他两源，**权重不作调减**
3. **极端全解析失败退化**: 所有暗盘源失效时，暗盘板块得分降为 0，退化为纯 GEX+DBMF 模式

当前代码对单源失败的处理是统一赋 0 分（见 `darkpool_verifier.py` 第 300-304 行），**没有实现"权重不作调减、暂时交由其他两源判定"**的动态权重重分配逻辑。

**PRD 要求**:
> PRD 第 6 节："若 ChartExchange 抓取失败而 SqueezeMetrics 运行正常，系统自动放弃"场外卖空比"的校验，将暗盘板块的判定权临时交给 DIX 基础分 + Stockgrid 趋势线，权重不作调减"

**建议修复方案**:
在 `resonance_scorer.py` 中引入"可用数据源位掩码"参数，当某维度数据源标记为不可用时，动态调整该维度的满分上限和触发门槛。

**参考修复代码**:
```python
# signal_engine/resonance_scorer.py 新增方法
def calculate_darkpool_score_with_fallback(
    self,
    dix_flag: bool,
    short_ratio_flag: bool,
    stockgrid_flag: bool,
    dbmf_recovery: bool,
    available_sources: Dict[str, bool] = None  # 新增：可用数据源标记
) -> Dict[str, any]:
    """
    支持降级逻辑的暗盘评分
    
    Args:
        available_sources: {'dix': True, 'short_ratio': False, 'stockgrid': True}
                          标记哪些数据源可用
    """
    if available_sources is None:
        available_sources = {'dix': True, 'short_ratio': True, 'stockgrid': True}

    # 仅统计可用源的触发数
    active_count = 0
    if available_sources.get('dix', False) and dix_flag:
        active_count += 1
    if available_sources.get('short_ratio', False) and short_ratio_flag:
        active_count += 1
    if available_sources.get('stockgrid', False) and stockgrid_flag:
        active_count += 1

    # 计算可用源的总数
    total_available = sum(1 for v in available_sources.values() if v)

    # 动态调整阈值：至少需要 ceil(total_available * 2/3) 个源触发
    import math
    required_count = max(1, math.ceil(total_available * 2 / 3))

    signal_count = sum([dix_flag, short_ratio_flag, stockgrid_flag])

    # 根据可用源数量动态评分
    if total_available == 3:
        # 完整模式：三选二 + DBMF = 1.5分
        if active_count >= 2 and dbmf_recovery:
            score = 1.5
            state = 'STRONG_ACCUMULATION'
        elif active_count >= 2:
            score = 0.75
            state = 'MODERATE'
        else:
            score = 0.0
            state = 'WEAK'
    elif total_available >= 1:
        # 部分降级：按比例调整
        base_score = 0.75 * (total_available / 3)
        if active_count >= required_count and dbmf_recovery:
            score = 1.5 * (total_available / 3)
            state = 'STRONG_ACCUMULATION (DEGRADED)'
        elif active_count >= required_count:
            score = base_score
            state = 'MODERATE (DEGRADED)'
        else:
            score = 0.0
            state = 'WEAK'
    else:
        # 极端退化：暗盘得分为0
        score = 0.0
        state = 'DEGRADED_TO_GEX_DBMF'

    details = f"暗盘信号({active_count}/{total_available}可用源触发)"

    return {
        'score': round(score, 2),
        'state': state,
        'details': details
    }
```

**预计工作量**: 3-4 小时（含集成测试）

---

#### W3. 共振评分中各维度数据缺失处理不完善

**涉及文件**: [`main_scheduler.py`](main_scheduler.py:545-687)，特别是 `task_evaluate_resonance()` 方法

**问题描述**:
在 `task_evaluate_resonance()` 中，当某个维度的最新数据缺失时（如 `latest_gex` 为 None），代码直接 `return` 跳过本轮评估（第 573-576 行）。这导致即使其他三个维度都正常，也无法产生信号。

**建议修复方案**:
改为部分评估模式，缺失的维度记 0 分，但仍计算其他维度的总分。同时记录 WARNING 日志。

**参考修复代码**:
```python
# main_scheduler.py task_evaluate_resonance() 修改
async def task_evaluate_resonance(self):
    try:
        # 获取最新数据
        latest_gex = await loop.run_in_executor(self.db_executor, self.db.get_latest_gex)
        latest_crypto = await loop.run_in_executor(self.db_executor, self.db.get_latest_crypto_data)
        latest_darkpool = await loop.run_in_executor(self.db_executor, self.db.get_latest_dark_pool_metrics)
        latest_vix = await loop.run_in_executor(self.db_executor, self.db.get_latest_vix_analysis)

        # 不再直接 return，而是记录警告并继续
        missing_dims = []
        if not latest_gex:
            missing_dims.append('GEX')
            logger.warning("GEX数据缺失，该维度记0分")
        if not latest_vix:
            missing_dims.append('VIX')
            logger.warning("VIX数据缺失，该维度记0分")
        # ... 对其他维度同样处理

        if len(missing_dims) >= 3:
            logger.error(f"超过3个维度数据缺失，跳过本轮评估: {missing_dims}")
            return

        # 计算各维度分值，缺失的记0分
        gex_score = self.resonance_scorer.calculate_gex_score(...) if latest_gex else {'score': 0.0, 'state': 'MISSING', 'details': '数据缺失'}
        # ... 对其他维度同样处理
```

**预计工作量**: 2-3 小时

---

### 🔵 低优先级（Info - 优化建议）

#### I1. Hawkes 分支比实现方式与 PRD 语义存在偏差

**涉及文件**: [`signal_engine/resonance_scorer.py`](signal_engine/resonance_scorer.py:452-575)

**问题描述**:
PRD 提到基于 Hawkes Process 测算"全网自激抛售的分支比"，参考的是事件驱动的点过程模型。而当前实现以价格跌幅和成交量的线性相关系数作为分支比代理（第 524 行 `np.corrcoef`），在低流动性时段或成交量稀疏环境中，相关系数可能出现负值被 `max(0, corr)` 截断为 0，导致所有时段都判定为"亚临界"而失去区分度。

**建议优化方案**:
可用滑动窗口内的"跌幅自回归系数"（即当期跌幅对下一期跌幅的 AR(1) 系数）替代相关系数作为更稳健的代理指标。

**参考优化代码**:
```python
# signal_engine/resonance_scorer.py estimate_hawkes_branching_ratio() 优化
# 使用 AR(1) 自回归系数替代相关系数
from statsmodels.tsa.ar_model import AutoReg

if len(recent_price_changes) >= 20:
    # 拟合 AR(1) 模型
    model = AutoReg(recent_price_changes, lags=1, trend='n')
    result = model.fit()
    branching_ratio = abs(result.params[1])  # AR(1) 系数绝对值
    branching_ratio = min(1.0, branching_ratio)  # 截断到 [0, 1]
else:
    # 数据不足时使用简化方法
    ...
```

**预计工作量**: 4-6 小时（含回测验证）

---

#### I2. 告警发送未集成到主调度器

**涉及文件**: [`main_scheduler.py`](main_scheduler.py:648-675)，[`notification/alert_sender.py`](notification/alert_sender.py)

**问题描述**:
在 `task_evaluate_resonance()` 中，当触发告警时（第 648 行），代码仅记录日志（第 674-675 行），**并未实际调用 `AlertSender` 发送邮件/Telegram/Discord 通知**。

**当前代码**:
```python
# main_scheduler.py 第 674-675 行
logger.warning(f"🚨 {resonance_result['alert_level']} 信号触发! 总分: {resonance_result['total_score']}")
logger.info(f"告警详情: {alert_message[:200]}...")
# ❌ 缺少实际的告警发送调用
```

**建议修复方案**:
在 `MainScheduler.__init__()` 中初始化 `AlertSender`，在 `task_evaluate_resonance()` 中调用发送方法。

**参考修复代码**:
```python
# main_scheduler.py __init__() 新增
from notification.alert_sender import AlertSender
self.alert_sender = AlertSender()

# main_scheduler.py task_evaluate_resonance() 修改
if trigger_result['should_alert']:
    # 格式化告警消息
    alert_message = format_alert_message(resonance_result, hawkes_result, current_time)

    # 存入数据库
    await loop.run_in_executor(...)

    # ✅ 新增：发送多渠道告警
    try:
        level3_message = self.alert_sender.format_level3_alert(
            resonance_result, hawkes_result, current_time, put_wall_range
        )
        results = self.alert_sender.send_multi_channel_alert(
            subject=f"[{resonance_result['alert_level']}] 共振抄底信号",
            message=level3_message,
            channels=['email', 'telegram']  # 从配置读取
        )
        logger.info(f"告警发送结果: {results}")
    except Exception as e:
        logger.error(f"告警发送失败: {e}", exc_info=True)
```

**预计工作量**: 1-2 小时

---

#### I3. 配置文件缺少 Discord Webhook URL 默认值

**涉及文件**: [`config/settings.py`](config/settings.py:58)

**问题描述**:
`DISCORD_WEBHOOK_URL` 没有默认值，且未在 `validate()` 方法中检查其完整性。

**建议修复**:
```python
# config/settings.py validate() 方法补充
if not cls.DISCORD_WEBHOOK_URL:
    warnings.append("Discord Webhook URL未配置,Discord告警将禁用")
```

**预计工作量**: 0.5 小时

---

#### I4. 数据库备份任务未实现清理旧备份

**涉及文件**: [`main_scheduler.py`](main_scheduler.py:877-895)

**问题描述**:
`task_backup_database()` 仅执行备份，未实现旧备份文件的定期清理，长期运行可能导致磁盘空间耗尽。

**建议修复**:
增加保留最近 N 个备份或删除超过 M 天的备份的逻辑。

**预计工作量**: 1-2 小时

---

## 四、待办清单汇总（Todo List）

| 优先级 | 编号 | 问题描述 | 涉及文件 | 预计工作量 | 状态 |
| :-- | :-- | :-- | :-- | :-- | :-- |
| 🔴 高 | C1 | ChartExchange API 端点未验证 + CRITICAL告警缺失 | `chartexchange_fetcher.py`, `settings.py`, `main_scheduler.py` | 2-4h | ⏳ 待审核 |
| 🔴 高 | C2 | Stockgrid XHR/DOM 选择器未验证 + tenacity重试缺失 | `stockgrid_fetcher.py`, `settings.py` | 3-5h | ⏳ 待审核 |
| 🔴 高 | C3 | SqueezeMetrics CSV下载实现（修正：无需Playwright） | `squeezemetrics_fetcher.py` | 2-3h | ⏳ 待审核 |
| 🟡 中 | W1 | Stockgrid 20d/60d 斜率 Bug | `stockgrid_fetcher.py` | 1-2h | ⏳ 待审核 |
| 🟡 中 | W2 | 降级逻辑未实现动态权重 | `resonance_scorer.py`, `fallback_manager.py` | 3-4h | ⏳ 待审核 |
| 🟡 中 | W3 | 数据缺失处理不完善 | `main_scheduler.py` | 2-3h | ⏳ 待审核 |
| 🔵 低 | I1 | Hawkes 分支比实现偏差 | `resonance_scorer.py` | 4-6h | ⏳ 待审核 |
| 🔵 低 | I2 | 告警发送未集成 | `main_scheduler.py`, `alert_sender.py` | 1-2h | ⏳ 待审核 |
| 🔵 低 | I3 | Discord 配置检查缺失 | `settings.py` | 0.5h | ⏳ 待审核 |
| 🔵 低 | I4 | 备份清理未实现 | `main_scheduler.py` | 1-2h | ⏳ 待审核 |

**总计预计工作量**: 19-36 小时（C3修正后节省2-3小时）

---

## 五、修复优先级建议

### 第一阶段：打通数据链路（必须完成）
- **C1**: ChartExchange 端点抓包验证
- **C2**: Stockgrid XHR/DOM 规则验证
- **C3**: SqueezeMetrics 页面解析实现

**目标**: 确保三个暗盘数据源能够真实获取数据，系统可以脱离 Mock 模式运行。

### 第二阶段：修复核心 Bug（强烈建议）
- **W1**: Stockgrid 双周期斜率计算修复
- **W2**: 降级逻辑动态权重实现
- **W3**: 数据缺失处理优化

**目标**: 确保信号评分逻辑准确，避免因代码 Bug 导致误判。

### 第三阶段：优化与完善（可选）
- **I1-I4**: 各项优化建议

**目标**: 提升系统鲁棒性和用户体验。

---

## 六、总体评价

项目在**架构设计和量化逻辑层面**与 PRD 高度对齐，模块划分清晰、评分机制准确、容错框架已搭建。核心短板集中在**数据获取层的"最后一公里"**——三个外部数据源（ChartExchange、Stockgrid、SqueezeMetrics）均依赖未经验证的推测端点，是系统当前无法投入真实盘中运行的根本原因。

**建议行动路线**:
1. **优先**通过浏览器抓包将 ChartExchange 和 Stockgrid 的真实端点固化
2. **其次**修复 `slope_20d/60d` Bug 和降级权重重分配逻辑
3. **最后**逐步实施各项优化建议

**生产部署前置条件**:
- ✅ 所有高优先级问题（C1-C3）已修复并通过测试
- ✅ 至少一种通知渠道（Email/Telegram）已配置并可正常发送
- ✅ 系统在 Mock 模式下完整运行过至少一个交易日周期

---

**审查人**: Qoder AI Assistant
**审查依据**: PRD 文档《多源共振暗盘与流动性微观结构盘中自动监控系统.md》v1.0
**下一步**: 等待人工审核本 Todo List，确认后进入修复阶段
