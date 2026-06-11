# 多源共振监控系统 — Multi-source Resonance

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://python.org)
[![React](https://img.shields.io/badge/React-18+-61dafb)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-green)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ed)](https://docker.com)
[![Status](https://img.shields.io/badge/Production-Ready-success)](#)

> 基于 **WebSocket + EventBus Push 实时流** 的多维度金融监控系统。搭载 **React 仪表盘**、**FastAPI REST 后端**、**三层解耦 V2.0 架构** 和 **LLM 推理**，实时追踪美股暗盘资金、做市商 Gamma 敞口、VIX 期限结构、加密杠杆清洗及跨资产共振，通过四维度共振评分自动识别"流动性清算衰竭"级抄底信号，多渠道推送告警。

---

## 目录

- [核心能力](#核心能力)
- [系统架构](#系统架构)
- [目录结构](#目录结构)
- [数据源矩阵](#数据源矩阵)
- [V2.0 三层解耦架构](#v20-三层解耦架构)
- [核心模块详解](#核心模块详解)
- [前端仪表盘](#前端仪表盘)
- [快速开始](#快速开始)
- [Docker 部署](#docker-部署)
- [API 端点](#api-端点)
- [测试](#测试)
- [架构演进](#架构演进)
- [监控标的](#监控标的)
- [许可证](#许可证)

---

## 核心能力

| 能力 | 描述 |
|------|------|
| **实时数据流** | Hyperliquid DEX WebSocket 长连接 Push，EventBus pub/sub 事件驱动 |
| **四维共振评分** | GEX + VIX + Crypto + Darkpool，满分 5.0，LEVEL_3 阈值 3.5 |
| **Hawkes AR(1)** | OLS 自回归建模，替代 corrcoef 实现精确自激分支比测算 |
| **跨资产共振** | 加密 vs 股票联动分析，跨资产套利信号识别 |
| **暗盘 EMA 预处理** | 净做空量 EMA-5/EMA-20 双线降噪，零轴穿越/动量反转拐点检测 |
| **数据校验防线** | Pandera 模式验证 + Greeks 边界检查 + Put-Call Parity + 套利检测 + Isolation Forest |
| **BS 向量化引擎** | py-vollib-vectorized 实现批量 Greeks 计算 |
| **三层解耦 V2.0** | Layer1 数学计算 → Layer2 JSON 网关 → Layer3 LLM 推理 |
| **LLM 推理** | OpenAI GPT-4o / Anthropic Claude 自动化报告生成 |
| **回测引擎** | 历史信号回放、绩效指标（Sharpe/MaxDD/WinRate） |
| **前端 Web UI** | React + TypeScript 仪表盘、告警中心、GEX 曲线、跨资产热力图、共振仪表 |
| **多渠道告警** | Email (SMTP) + Telegram Bot + Discord Webhook 并发推送 |
| **Docker 部署** | 多阶段构建 + docker-compose + Nginx + Prometheus + Grafana |
| **降级容错** | Hyperliquid → CCData 降级、yfinance → FINRA 降级 |

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                          数据源层                                    │
│  Hyperliquid WS │ SqueezeMetrics │ CBOE VIX │ AXLFI │ yfinance │ FINRA │
└────────┬────────┴───────┬────────┴────┬─────┴───┬────┴────┬──────┴──────┘
         │                │             │         │         │
         ▼                ▼             ▼         ▼         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    EventBus (asyncio.Queue Pub/Sub)                   │
│  10 个 Topic: funding_rate | OI | GEX | VIX | darkpool | short ...  │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      SignalPipeline (事件驱动)                        │
│         数据到达 → 维度评估 → 四维就绪 → 共振评分 → 告警              │
└───────┬─────────────────────────────┬───────────────────────────────┘
        │                             │
        ▼                             ▼
┌───────────────────┐    ┌──────────────────────────────┐
│   量化逻辑层       │    │       信号引擎                │
│ GEX · VIX ·       │    │ ResonanceScorer (0~5.0)      │
│ Crypto · Darkpool │    │ SignalStateMachine (冷却30min)│
│ BS Engine ·       │    │                              │
│ CrossAsset ·      │    │                              │
│ DataValidator     │    │                              │
└───────┬───────────┘    └──────────────┬───────────────┘
        │                              │
        ▼                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    V2.0 三层解耦流水线 (盘后)                         │
│  Layer 1 (数学) → Layer 2 (JSON 网关) → Layer 3 (LLM 推理)          │
└─────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         输出层                                       │
│  Email · Telegram · Discord │ SQLite │ FastAPI REST │ React 前端     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 目录结构

```
Multi-source Resonance/
├── api_server.py                   # ★ FastAPI REST 后端 (1000+ 行)
├── main_stream.py                  # ★ Push 实时流入口
├── main_scheduler.py               # [DEPRECATED] 旧 Pull 入口
│
├── data_stream/                    # Push 实时流架构
│   ├── event_bus.py                # 异步事件总线 (10 个 Topic)
│   ├── hyperliquid_stream.py       # Hyperliquid DEX WebSocket 连接器
│   ├── signal_pipeline.py          # 事件驱动信号管线 (核心)
│   ├── rest_poll_scheduler.py      # 非WS源轻量轮询调度器
│   └── stream_engine.py            # 统一流引擎
│
├── data_fetchers/                  # 数据获取器
│   ├── hyperliquid_fetcher.py      # Hyperliquid DEX REST (降级备选)
│   ├── ccdata_fetcher.py           # CCData CEX REST (降级备选)
│   ├── axlfi_fetcher.py            # AXLFI 暗盘净头寸 ★
│   ├── squeezemetrics_fetcher.py   # SqueezeMetrics DIX/GEX CSV
│   ├── yahoo_finance_fetcher.py    # yfinance 做空数据 + CBOE VIX
│   ├── finra_fetcher.py            # FINRA 管道文件短卖比
│   ├── dbmf_fetcher.py             # DBMF ETF 动量监控
│   ├── batch_loader.py             # 盘后批量加载器 (V2.0)
│   ├── coinglass_fetcher.py        # [DEPRECATED] Coinglass 聚合
│   ├── stockgrid_fetcher.py        # [DEPRECATED] Stockgrid 爬虫
│   └── tradier_fetcher.py          # Tradier 期权链
│
├── quant_logic/                    # 量化计算逻辑
│   ├── gex_calculator.py           # Gamma Exposure 计算
│   ├── vix_analyzer.py             # VIX 期限结构分析
│   ├── crypto_leverage_cleaner.py  # 加密杠杆清洗判定
│   ├── darkpool_verifier.py        # 暗盘三驾马车验证
│   ├── darkpool_preprocessor.py    # 暗盘 EMA 降噪预处理 (v2.1)
│   ├── bs_engine.py                # Black-Scholes 向量化引擎 (V2.0)
│   ├── data_validator.py           # 综合数据校验流水线 (V2.0)
│   ├── cross_asset.py              # 跨资产共振引擎 (P2-1)
│   └── dimension_reducer.py        # 多因子降维 (V2.0)
│
├── signal_engine/                  # 信号引擎
│   ├── resonance_scorer.py         # 共振评分 (Hawkes AR(1) + EMA 加成)
│   └── signal_trigger.py           # 信号状态机 + 冷却期管理
│
├── gateway/                        # Layer 2: JSON 上下文网关 (V2.0)
│   ├── schemas.py                  # ResonanceSnapshot / GatewayEnvelope
│   ├── serializer.py               # Layer1 → Pydantic → JSON
│   ├── validator.py                # Schema/范围/NaN 合规校验
│   └── interceptor.py              # 数据质量门禁 + 熔断
│
├── llm_inference/                  # Layer 3: LLM 推理 (V2.0)
│   ├── base.py                     # 推理基类
│   ├── openai_provider.py          # OpenAI GPT-4o
│   ├── anthropic_provider.py       # Anthropic Claude
│   ├── prompt_builder.py           # 报告 Prompt 构建器
│   ├── report_composer.py          # 多资产汇总报告
│   └── response_parser.py          # LLM 响应解析
│
├── pipeline_v2/                    # V2.0 端到端批处理流水线
│   ├── orchestrator.py             # 流水线编排器 (6 阶段)
│   └── monitor.py                  # 运行监控与日志
│
├── backtest_engine/                # 回测引擎 (P3)
│   ├── signal_replay.py            # 历史信号回放
│   ├── performance.py              # 绩效指标 (Sharpe/MaxDD/WinRate)
│   └── report.py                   # 回测报告生成
│
├── notification/                   # 告警推送
│   └── alert_sender.py             # Email/Telegram/Discord 多渠道
│
├── database/                       # 数据持久化
│   ├── db_manager.py               # SQLite WAL 模式管理器
│   └── schema.sql                  # 4 表 + 多视图
│
├── frontend/                       # React + TypeScript 前端
│   ├── src/pages/
│   │   ├── Dashboard.tsx           # 主仪表盘
│   │   ├── AlertCenter.tsx         # 告警中心 (复盘/CSV导出)
│   │   └── SystemStatus.tsx        # 系统状态监控
│   ├── src/components/
│   │   ├── CrossAssetHeatmap.tsx   # 跨资产热力图
│   │   ├── GEXCurveChart.tsx       # GEX 曲线图
│   │   ├── HistoricalTrend.tsx     # 历史趋势
│   │   └── ResonanceGauge.tsx      # 共振仪表盘
│   └── src/api/                    # React Query hooks
│
├── deploy/                         # 部署配置
│   ├── nginx.conf                  # Nginx 反向代理 + WS/SSE/限速
│   ├── prometheus.yml              # Prometheus 指标采集
│   ├── docker-compose.yml          # Docker Compose 编排
│   └── Dockerfile                  # 多阶段构建 (Node + Python)
│
├── tests/                          # 测试
│   ├── test_phase5_signal_engine.py
│   ├── test_backtest_engine.py
│   ├── test_pipeline_integration.py
│   ├── test_layer2_*.py            # Layer 2 网关测试
│   └── conftest.py
│
├── utils/                          # 工具模块
│   ├── logger.py                   # 分级日志
│   ├── exceptions.py               # 自定义异常层次
│   └── fallback_manager.py         # 降级管理器
│
├── config/
│   ├── settings.py                 # Config / StreamConfig / DataFetchConfig
│   └── .env.example                # 环境变量模板
│
├── verify_setup.py                 # 安装验证
├── verify_fetchers.py              # 数据获取器验证
├── run_pipeline_v2.py              # V2.0 流水线启动脚本
└── requirements.txt                # Python 依赖
```

---

## 数据源矩阵

| 维度 | 子指标 | 主源 | 降级源 | 方式 | 频率 |
|------|--------|------|--------|------|------|
| **GEX/DIX** | GEX 总敞口、DIX 暗盘强度 | SqueezeMetrics CSV | — | REST 轮询 | 15min |
| **VIX** | 期限结构 (VX1/VX2)、恐慌溢价 | CBOE 官方 (vix_utils) | — | REST 轮询 | 15min |
| **Crypto** | BTC 资金费率、持仓量 | **Hyperliquid DEX WS** | CCData REST | **WebSocket Push** | 实时 |
| **Darkpool** | 暗盘净头寸、底背离 | **AXLFI API** | — | REST 轮询 | 15min |
| **做空** | shortFloat/ShortRatio | **yfinance** (免费) | FINRA 管道 | 盘后 | 日频 |
| **DBMF** | MA5 均线收复 | yfinance | — | REST 轮询 | 15min |

全部数据源 **免费**，无需付费 API Key 即可运行核心功能。

---

## V2.0 三层解耦架构

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 1: 数学计算层                                             │
│  BS Greeks 向量化 → 数据校验 (5道防线) → 多因子降维               │
│  输出: ResonanceVector (数值向量)                                 │
├─────────────────────────────────────────────────────────────────┤
│  Layer 2: JSON 上下文网关                                         │
│  Serializer → Pydantic 验证 → Interceptor (质量门禁+熔断)         │
│  输出: GatewayEnvelope (LLM-ready JSON)                           │
├─────────────────────────────────────────────────────────────────┤
│  Layer 3: LLM 推理                                                │
│  Prompt 构建 → OpenAI/Anthropic 推理 → 响应解析 → 报告合成         │
│  输出: Markdown 分析报告                                          │
└─────────────────────────────────────────────────────────────────┘
```

**严格责任制原则**：Layer 1 永不因 LLM 格式需求改变数学实现；Layer 2 对上下文进行防火墙隔离，确保误入 JSON 的数值不超过安全范围；Layer 3 仅消费 Layer 2 输出的 JSON。

---

## 核心模块详解

### 1. 数据流层 (`data_stream/`)

#### EventBus — 异步事件总线

```python
from data_stream.event_bus import EventBus, Topics

bus = EventBus()
await bus.start()
await bus.subscribe(Topics.CRYPTO_FUNDING_RATE, on_funding_update)
await bus.publish(Topics.CRYPTO_FUNDING_RATE, {"rate": -0.000125, "coin": "BTC"})
```

10 个预定义 Topic：`crypto.funding_rate` | `crypto.open_interest` | `gex.update` | `vix.term_structure` | `darkpool.axlfi` | `short_volume.spy` | `dbmf.recovery` | `data.source_error` | `data.source_recovered` | `system.shutdown`

#### HyperliquidStream — WebSocket 实时连接器

- 端点：`wss://api.hyperliquid.xyz/ws`
- 订阅：`activeAssetData` (BTC)，推送 `funding` / `openInterest` / `markPx` / `premium`
- 自动重连：指数退避 1s → 60s 上限
- Ping/Pong 保活：每 30s

#### SignalPipeline — 事件驱动信号管线

```
Hyperliquid WS → funding_rate ─┐
Hyperliquid WS → open_interest ┤→ Crypto 维度就绪 ─┐
RESTPoll → gex.update ────────→ GEX 维度就绪 ──────┤
RESTPoll → vix.term_structure → VIX 维度就绪 ──────┤→ 共振评分 → 告警
RESTPoll → darkpool.axlfi ────┐                     │
RESTPoll → short_volume.spy ──┤→ Darkpool 维度就绪 ┘
RESTPoll → dbmf.recovery ─────┘
```

防抖间隔：30 秒最小评分间隔。

### 2. 量化逻辑层 (`quant_logic/`)

| 类 | 功能 | 输出 |
|----|------|------|
| `GEXCalculator` | Gamma Exposure 计算、α 校准 | GEX 敞口值 |
| `VIXAnalyzer` | 期限结构 Contango/Backwardation 判定 | 结构比率、恐慌溢价 |
| `CryptoLeverageCleaner` | OI 暴跌检测、资金费率异常、ELR 判定 | 去杠杆完成标志 |
| `DarkPoolVerifier` | 暗盘底背离信号验证 | 净流入确认 |
| `DarkPoolPreprocessor` | EMA-5/EMA-20 双线降噪 + 零轴穿越/动量反转 | 拐点信号加成 |
| `VectorizedBSEngine` | py-vollib-vectorized BS 批量 Greeks | (delta, gamma, vega, theta, rho) |
| `DataValidationPipeline` | 5 道校验防线 | ValidationResult + AuditEntry |
| `CrossAssetResonanceEngine` | 加密 vs 股票跨资产联动 | 跨资产共振信号 |

### 3. 信号引擎 (`signal_engine/`)

#### ResonanceScorer — 共振评分

| 维度 | 满分 | 关键条件 |
|------|------|---------|
| **GEX** | 1.5 分 | GEX 由负翻正 |
| **VIX** | 1.0 分 | 回归 Contango 且斜率向下 |
| **Crypto** | 1.0 分 | OI 暴跌 + 费率转正 + 去杠杆完成 |
| **Darkpool** | 1.5 分 | 三选二聚合 + DBMF 收复 + EMA 加成 |
| **总分** | **5.0 分** | |

**Hawkes AR(1)**：OLS 自回归系数作为自激分支比代理，解决 corrcoef 在低流动性环境"全亚临界"问题。

预警级别：

| 级别 | 阈值 | 行为 |
|------|------|------|
| **LEVEL_3** | ≥3.5 | 全维度共振，Email + Telegram + Discord |
| **LEVEL_2** | ≥3.0 | 密切监控，Email + Discord |
| **LEVEL_1** | ≥2.0 | 初步关注，仅 Email |
| **NO_SIGNAL** | <2.0 | 无信号 |

### 4. 告警推送 (`notification/alert_sender.py`)

```python
from notification.alert_sender import create_alert_sender

sender = create_alert_sender()
sender.send_multi_channel_alert(
    subject="[LEVEL_3] 共振抄底信号触发",
    message=alert_message,
    channels=['email', 'telegram', 'discord']
)
```

### 5. 数据库 (`database/`)

SQLite (WAL 模式)，4 张核心表：

| 表名 | 用途 |
|------|------|
| `gex_history` | GEX 历史估算与校准 |
| `dark_pool_metrics` | DIX、做空比、暗盘斜率、DBMF 收复 |
| `crypto_derivatives` | 资金费率、OI、清算标志、杠杆率 |
| `signal_alerts` | 共振信号触发日志 (含得分明细、Hawkes 分支比) |

### 6. 降级链路

```
Hyperliquid DEX WebSocket (首选, 免费)
    ↓ 连接断开
CCData REST API (Free Tier)

yfinance short interest (首选, 免费)
    ↓ 获取失败
FINRA 管道文件 (CNMSshvol{date}.txt)

SqueezeMetrics CSV (稳定, 公开)
AXLFI 暗盘 API (免费公开)
CBOE VIX (vix_utils, 官方)
```

---

## 前端仪表盘

| 页面 | 路由 | 功能 |
|------|------|------|
| **Dashboard** | `/` | 实时共振评分、四维度状态、GEX 曲线、历史趋势 |
| **AlertCenter** | `/alerts` | 告警列表、Incident 复盘标记、CSV/JSON 导出 |
| **SystemStatus** | `/status` | WebSocket 连接状态、数据源健康、内存/CPU 指标 |

核心组件：

- `ResonanceGauge` — 共振评分仪表盘 (0~5.0)
- `GEXCurveChart` — Gamma Exposure 实时曲线
- `CrossAssetHeatmap` — 加密 vs 股票跨资产热力图
- `HistoricalTrend` — 多维度历史趋势图

技术栈：React 18 + TypeScript + TanStack Query + Recharts + Tailwind CSS

---

## 快速开始

### 环境要求

- Python ≥ 3.10 (推荐 3.12)
- Node.js ≥ 18 (仅前端开发)
- Windows / Linux / macOS

### 安装

```bash
# 1. 克隆仓库
git clone https://github.com/raymodny-ai/Multi-source-Resonance.git
cd Multi-source-Resonance

# 2. 安装 Python 依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp config/.env.example config/.env
# 编辑 config/.env 填入可选的 API Key

# 4. 初始化数据库
python -c "from database.db_manager import DatabaseManager; DatabaseManager().initialize()"

# 5. 构建前端 (可选，生产模式需要)
cd frontend && npm install && npm run build && cd ..

# 6. 验证安装
python verify_setup.py
```

### 启动

```bash
# Push 实时流架构 (推荐)
python main_stream.py

# FastAPI REST API + 前端
python api_server.py
# 访问 http://localhost:8524

# V2.0 盘后批处理流水线
python run_pipeline_v2.py

# 运行测试
pytest tests/ -v
```

### 最低配置

无需任何 API Key 即可运行核心监控：

| 数据源 | 是否需要 Key | 方式 |
|--------|-------------|------|
| Hyperliquid DEX | ❌ 免费 | WebSocket 实时 |
| SqueezeMetrics | ❌ 公开 CSV | REST 轮询 |
| CBOE VIX | ❌ vix_utils | REST 轮询 |
| AXLFI 暗盘 | ❌ 公开 API | REST 轮询 |
| yfinance 做空 | ❌ 免费 | 盘后日频 |
| FINRA | ❌ 官方公开 | 盘后日频 |
| CCData | 可选 | Free Tier 10万次/月 |
| OpenAI/Anthropic | 可选 | LLM 推理增强 |

---

## Docker 部署

```bash
# 生产模式 (后端 + 前端构建产物 + Nginx)
docker compose --profile full up -d

# 仅应用 (8524 端口)
docker compose up -d app

# 开发模式 (热重载)
docker compose --profile dev up -d app-dev

# 监控套件 (Prometheus + Grafana)
docker compose --profile monitoring up -d prometheus grafana
```

服务端口：
- `8524` — FastAPI 后端
- `80` — Nginx 反向代理 (仅 full profile)
- `9090` — Prometheus
- `3000` — Grafana

---

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/status` | 系统状态 (CPU/内存/连接) |
| `GET` | `/api/signals` | 共振信号列表 |
| `GET` | `/api/signals/{id}` | 信号详情 |
| `GET` | `/api/incidents` | Incident 告警列表 |
| `GET` | `/api/incidents/{id}` | Incident 详情 |
| `PUT` | `/api/incidents/{id}/review` | 标记 Incident 已复盘 |
| `GET` | `/api/incidents/{id}/export` | 导出 Incident JSON 报告 |
| `GET` | `/api/dashboard` | 仪表盘汇总数据 |
| `GET` | `/api/stream/signals` | SSE 信号推送流 |
| `WS` | `/ws` | WebSocket 实时连接 |

---

## 测试

```bash
# 全量回归
pytest tests/ -v

# 信号引擎测试
pytest tests/test_phase5_signal_engine.py -v

# 回测引擎测试
pytest tests/test_backtest_engine.py -v

# 集成测试
pytest tests/test_pipeline_integration.py -v

# TypeScript 类型检查
cd frontend && npx tsc --noEmit
```

---

## 架构演进

| 版本 | 架构 | 状态 |
|------|------|------|
| **v1** (Phase 1-7) | APScheduler Pull 定时轮询 (`main_scheduler.py`) | DEPRECATED |
| **v2** (Current) | WebSocket + EventBus Push 实时流 (`main_stream.py`) | Active |
| **v2.0** | 三层解耦 (Layer1 数学 → Layer2 网关 → Layer3 LLM) | Active |
| **v2.1** | Hawkes AR(1) 优化 + P2 前端增强 + C1/C2 数据源闭环 | Latest |

### v1 → v2 核心变化

- **数据获取**：cron job → WebSocket 长连接 + EventBus 推送
- **调度器**：APScheduler → `asyncio.create_task` + `asyncio.sleep`
- **信号评估**：固定间隔批处理 → 数据到达即时触发
- **做空数据**：FMP → yfinance (免费)
- **加密数据**：CCXT/Coinglass → Hyperliquid DEX WebSocket (免费)
- **暗盘数据**：ChartExchange/Stockgrid → AXLFI (免费 API)
- **Hawkes 模型**：corrcoef → AR(1) OLS 自回归
- **V2.0 新增**：BS 向量化、数据校验防线、LLM 推理、跨资产共振、回测引擎

---

## 监控标的

`SPY` `QQQ` `IWM` `AAPL` `MSFT` `NVDA` `TSLA` `AMD`

---

## 许可证

本项目仅供学习和研究使用。

---

**当前版本**: v2.1  
**最后更新**: 2026-06-09  
**入口文件**: `main_stream.py` | `api_server.py` | `run_pipeline_v2.py`
