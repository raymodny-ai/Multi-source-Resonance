# API 端点抓包验证指南

本指南帮助您快速验证 ChartExchange 和 Stockgrid 的真实 API 端点，以便完成 C1 和 C2 修复任务。

---

## C1: ChartExchange 端点验证

### 步骤 1: 打开浏览器开发者工具

1. 访问 https://chartexchange.com
2. 按 `F12` 打开开发者工具
3. 切换到 **Network** (网络) 标签页
4. 勾选 **Preserve log** (保留日志)
5. 在过滤器中输入 `xhr` 或 `fetch`，仅显示 API 请求

### 步骤 2: 查找短卖量数据请求

1. 在页面中找到 SPY 或 QQQ 的 Short Volume 图表/表格
2. 观察 Network 面板中出现的请求
3. 寻找包含以下关键词的请求:
   - `shortvolume`
   - `short-volume`
   - `off-exchange`
   - `api/v1`

### 步骤 3: 记录真实端点

找到请求后，记录以下信息:

```
完整 URL: https://chartexchange.com/api/xxx/yyy
请求方法: GET / POST
请求参数: symbol=SPY, date=2026-06-08 等
响应格式: JSON 结构示例
```

**示例响应结构**:
```json
{
  "date": "2026-06-08",
  "symbol": "SPY",
  "off_exchange_short_volume": 45000000,
  "off_exchange_total_volume": 95000000,
  "short_ratio": 47.37
}
```

### 步骤 4: 更新代码

将验证后的端点写入 `config/settings.py`:

```python
class ChartExchangeEndpoints:
    SHORT_VOLUME = '/api/v1/shortvolume/{symbol}'  # 替换为真实端点
    DAILY_DATA = '/data/daily/{symbol}/shortvol'   # 如有多个端点，全部记录
```

---

## C2: Stockgrid 端点验证

### 步骤 1: 访问 Dark Pool 页面

1. 访问 https://stockgrid.io/darkpool/SPY
2. 按 `F12` 打开开发者工具
3. 切换到 **Network** 标签页
4. 勾选 **Preserve log**

### 步骤 2: 查找净头寸数据请求

1. 观察页面加载时的 XHR 请求
2. 寻找包含以下关键词的请求:
   - `darkpool`
   - `netposition`
   - `net-position`
   - `api`

### 步骤 3: 记录 XHR URL 模式

找到请求后，记录:

```
完整 URL: https://stockgrid.io/api/darkpool/netposition?symbol=SPY&period=20
请求方法: GET
请求参数: symbol, period 等
响应格式: JSON 数组或对象
```

**示例响应结构**:
```json
{
  "symbol": "SPY",
  "period": 20,
  "net_position": [1000000, 1200000, 1500000, ...]
}
```

### 步骤 4: 记录 DOM 选择器

如果 XHR 拦截失败，需要降级为 DOM 解析：

1. 在 Elements 标签页中，右键点击净头寸图表/表格
2. 选择 "Copy selector" 或手动记录 CSS 类名
3. 记录关键元素的选择器:

```css
/* 图表容器 */
.darkpool-chart-container

/* 数据表格 */
.net-position-table

/* 具体数值单元格 */
.net-position-value
```

### 步骤 5: 更新代码

将验证后的规则写入 `config/settings.py`:

```python
class StockgridAdapter:
    XHR_URL_PATTERN = 'api/darkpool'  # 替换为真实模式
    DOM_SELECTOR_CHART = '.darkpool-chart-container'  # 替换为真实选择器
    DOM_SELECTOR_TABLE = '.net-position-table'  # 替换为真实选择器
```

---

## 验证清单

完成抓包后，请确认以下事项:

- [ ] ChartExchange 短卖量 API 端点已验证
- [ ] ChartExchange 响应字段名已记录
- [ ] Stockgrid XHR URL 模式已验证
- [ ] Stockgrid DOM 选择器已记录
- [ ] 两个网站的端点均已填入 `config/settings.py`

---

## 常见问题

### Q: 如果网站使用 WebSocket 而非 HTTP 请求？
A: 在 Network 面板中切换到 **WS** (WebSocket) 标签页，观察消息帧中的数据格式。

### Q: 如果数据是通过 JavaScript 动态生成的？
A: 使用 Sources 标签页设置断点，或在 Console 中执行 `document.querySelector()` 测试选择器。

### Q: 如果遇到反爬机制（403/429）？
A: 记录此时的 User-Agent 和 Request Headers，后续在代码中复用这些头部信息。

---

**预计耗时**: 每个网站 15-30 分钟，总计 30-60 分钟

完成后，即可继续执行 C1 和 C2 的代码修复工作。
