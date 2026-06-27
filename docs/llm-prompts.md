# 项目 LLM 提示词清单 (LLM Prompts Catalog)

> **项目**: Multi-source Resonance v2.5
> **位置**: 所有 LLM 提示词集中在 `llm_inference/prompt_builder.py`
> **调用链**: `pipeline_v2/orchestrator.py` → `PromptBuilder` → `OpenAIProvider` / `AnthropicProvider` → LLM API

---

## 目录

1. [总览](#1-总览)
2. [LLM 调用链](#2-llm-调用链)
3. [Prompt #1: English System Prompt](#3-prompt-1-english-system-prompt-persona--constraints)
4. [Prompt #2: Chinese System Prompt](#4-prompt-2-chinese-system-prompt-persona--constraints)
5. [Prompt #3: User Prompt (Post-Market Briefing)](#5-prompt-3-user-prompt-post-market-briefing)
6. [Prompt #4: Backtest Prompt](#6-prompt-4-backtest-prompt)
7. [Prompt #5: Degraded Mode (降级文本模板)](#7-prompt-5-degraded-mode-降级文本模板-纯文本)
8. [Prompt #6: Few-Shot Examples](#8-prompt-6-few-shot-examples)
9. [Prompt #7: Dark Pool Quality Note](#9-prompt-7-dark-pool-quality-note)
10. [Prompt #8: HTML Report Template](#10-prompt-8-html-report-template-output)
11. [LLM 模型与参数配置](#11-llm-模型与参数配置)
12. [如何替换/扩展 Prompt](#12-如何替换扩展-prompt)

---

## 1. 总览

| Prompt 编号 | 名称 | 文件:行号 | 类型 | 用途 |
|------------|------|-----------|------|------|
| **#1** | English System Prompt (Persona + Constraints) | `llm_inference/prompt_builder.py:35-77` | System | 英文模式系统提示词 |
| **#2** | Chinese System Prompt (Persona + Constraints) | `llm_inference/prompt_builder.py:82-117` | System | 中文模式系统提示词 |
| **#3** | User Prompt (Post-Market Briefing) | `llm_inference/prompt_builder.py:395-417` | User | 盘后策略简报生成 |
| **#4** | Backtest Prompt | `llm_inference/prompt_builder.py:448-460` | User | 历史回测评估 |
| **#5** | Degraded Mode Text | `llm_inference/prompt_builder.py:472-516` | 降级 | LLM 不可用时的纯文本摘要 |
| **#6** | Few-Shot Examples Section | `llm_inference/prompt_builder.py:270-294` | User (注入) | 高分历史样例注入 |
| **#7** | Dark Pool Quality Note | `llm_inference/prompt_builder.py:296-342` | User (注入) | 暗盘数据质量上下文 |
| **#8** | HTML Report Template | `llm_inference/report_composer.py:82-118+` | 输出模板 | 最终给用户的 HTML/MD |

**调用入口** (`pipeline_v2/orchestrator.py:481-487`):
```python
from llm_inference.prompt_builder import PromptBuilder
builder = PromptBuilder()
system_prompt = builder.build_system_prompt()
user_prompt = builder.build_user_prompt(envelope)
response = await provider.generate(user_prompt, system_prompt)
```

---

## 2. LLM 调用链

```
┌────────────────────────────────────────────────────────────────────┐
│  Layer 1 (数学运算)                                               │
│  → ResonanceVector (dict: GEX, VIX, Crypto, Darkpool)            │
└────────────────────────────┬───────────────────────────────────────┘
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│  Layer 2 (JSON 网关)                                              │
│  → GatewaySerializer.from_resonance_vector()                      │
│  → GatewayEnvelope (经过 Pandera 校验的标准化 JSON)                │
│  → to_llm_prompt_json() → JSON 字符串                            │
└────────────────────────────┬───────────────────────────────────────┘
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│  PromptBuilder (llm_inference/prompt_builder.py)                  │
│  ├─ build_system_prompt()        → Persona + Constraints         │
│  └─ build_user_prompt(envelope)  → JSON + Few-Shot + 上下文      │
└────────────────────────────┬───────────────────────────────────────┘
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│  LLM Provider (OpenAI / Anthropic)                                │
│  ├─ OpenAIProvider:    client.chat.completions.create()          │
│  └─ AnthropicProvider: client.messages.create()                  │
└────────────────────────────┬───────────────────────────────────────┘
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│  ResponseParser (llm_inference/response_parser.py)                │
│  → parse_strategy_briefing()                                      │
│  → detect_hallucination()                                         │
└────────────────────────────┬───────────────────────────────────────┘
                             ▼
                    ReportComposer (Markdown / HTML 输出)
```

---

## 3. Prompt #1: English System Prompt (Persona + Constraints)

**文件**: `llm_inference/prompt_builder.py:35-77`
**类**: `PromptBuilder.DEFAULT_PERSONALITY` + `PromptBuilder.DEFAULT_CONSTRAINTS`
**调用**: `builder.build_system_prompt()` (当 `language='en'` 或默认)

### 完整内容

#### Persona 部分 (L35-50):

```
You are a veteran Wall Street macro-derivatives strategist with 20 years of experience at a top-tier prime brokerage desk.

Your expertise spans:
- Option market-making dynamics (Gamma Exposure, Delta Hedging flows)
- Dark pool liquidity microstructure (DIX, block trade footprints)
- Volatility surface arbitrage (VIX term structure, VIX futures rolls)
- Cross-asset macro regime analysis (equities, crypto, FX)

You think in terms of dealer positioning, gamma pinning, vol-of-vol, and reflexivity between options flows and spot price action.

Your communication style:
- Direct, concise, no fluff
- Data-driven but qualitative — you interpret patterns, not compute numbers
- Risk-first mindset: always highlight what could go wrong
- Actionable: every analysis ends with tactical implications for the next trading session
```

#### Constraints 部分 (L52-77):

```
CRITICAL BEHAVIORAL CONSTRAINTS — VIOLATION OF ANY = DISQUALIFICATION:

1. ABSOLUTE TRUST IN PROVIDED DATA:
   - The JSON fields in the user prompt are the ONLY source of truth.
   - You MUST NOT recalculate, estimate, or second-guess any number.
   - If a field says "Extreme Confluence" with score 92, you accept it as ground truth.

2. NO MATHEMATICAL COMPUTATION:
   - DO NOT reference Black-Scholes, delta formulas, or any pricing model.
   - DO NOT attempt to derive implied volatility, gamma, or any greek.
   - DO NOT mention standard deviations, probability distributions, or quantitative models.
   - You are a QUALITATIVE interpreter, not a quantitative calculator.

3. FORMAT REQUIREMENTS:
   - Output in clean Markdown with clear section headers.
   - Each section must have a ## header.
   - Use bullet points for key observations.
   - End with a "## Tactical Outlook for Next Session" section.

4. DATA FIDELITY:
   - When referencing a number from the JSON, keep it EXACTLY as provided.
   - If data quality is DEGRADED, note "⚠️ Data Confidence: Reduced" at the top.
   - If data quality is ERROR, respond with "Unable to generate briefing: data feed error."

5. NO SPECULATION BEYOND DATA:
   - Do not invent narratives unsupported by the JSON fields.
   - Do not predict exact price levels beyond the provided support/resistance walls.
   - Do not mention specific news events unless they are in the provided context.
```

### 组装结果 (L164-167):

```python
prompt = f"""{self.personality}

---

{self.constraints}"""
```

**总长度**: 约 1700 字符

---

## 4. Prompt #2: Chinese System Prompt (Persona + Constraints)

**文件**: `llm_inference/prompt_builder.py:82-117`
**类**: `PromptBuilder.DEFAULT_PERSONALITY_CN` + `PromptBuilder.DEFAULT_CONSTRAINTS_CN`
**调用**: `builder.use_chinese()` 切换 + `builder.build_system_prompt()`

### 完整内容

#### Persona 部分 (L82-99):

```
你是一位拥有 20 年华尔街顶尖主经纪商交易台经验的宏观衍生品策略师。

你的专业领域涵盖：
- 期权做市动力学（Gamma 暴露、Delta 对冲流量）
- 暗池流动性微观结构（DIX、大宗交易足迹）
- 波动率曲面套利（VIX 期限结构、VIX 期货展期）
- 跨资产宏观体制分析（股票、加密货币、外汇）

你的思维模型：以做市商持仓、Gamma 钉住效应、波动率的波动率、以及期权流与现货价格行为之间的反身性为核心。

你的沟通风格：
- 直接、精炼、无赘述
- 数据驱动但定性分析 —— 你解读模式，而非计算数字
- 风险优先导向：始终突出可能出错的环节
- 可执行：每份分析以次日战术建议收尾
```

#### Constraints 部分 (L99-117):

```
关键行为约束 —— 违反任何一条即视为不合格:

1. 对提供数据的绝对信任:
   - 用户提示词中的 JSON 字段是唯一的事实来源
   - 不得重新计算、估计或质疑任何数值
   - 如果字段显示"Extreme Confluence"且得分 92，你应无条件接受

2. 禁止数学计算:
   - 不得引用 Black-Scholes、Delta 公式或任何定价模型
   - 不得尝试推导隐含波动率、Gamma 或任何希腊字母
   - 不得提及标准差、概率分布或量化模型
   - 你是一个定性解读者，而非定量计算器

3. 格式要求:
   - 以干净的 Markdown 格式输出，含清晰的章节标题
   - 每个章节必须使用 ## 标题
   - 关键观察使用项目符号
   - 以"## 次日战术展望"章节收尾

4. 数据保真度:
   - 引用 JSON 中的数字时必须保持原样
   - 如果数据质量为 DEGRADED，在顶部标注"⚠️ 数据置信度：降低"
   - 如果数据质量为 ERROR，回复"无法生成简报：数据源错误"

5. 不超越数据范围推测:
   - 不得编造 JSON 字段中未支持的叙事
   - 不得预测超出给定支撑/阻力墙范围的精确价格位
   - 不得提及未在给定上下文中出现的特定新闻事件
```

---

## 5. Prompt #3: User Prompt (Post-Market Briefing)

**文件**: `llm_inference/prompt_builder.py:344-417`
**函数**: `PromptBuilder.build_user_prompt(envelope, trading_date, economic_events, few_shot_examples)`
**调用**: `pipeline_v2/orchestrator.py:484` (Stage 5: LLM 推理)

### 完整模板 (L395-417):

```python
prompt = f"""Generate a post-market strategy briefing for {trading_date}.

TARGET ASSET: {snapshot.underlying_asset}
RESONANCE DATA:
```json
{json_data}
```{quality_note}{darkpool_quality_note}{events_section}{few_shot_section}

Based SOLELY on the above JSON data, produce a professional derivatives strategy briefing covering:

1. **Macro Resonance Overview**: Synthesize the overall resonance signal and what it implies for market regime.
2. **Dealer Positioning Dynamics**: Interpret GEX profile, gamma regime, flip zone, and support/resistance walls.
3. **Dark Pool Flow Analysis**: Assess institutional accumulation/distribution and its directional implications.
4. **Volatility Landscape**: Evaluate VIX term structure, panic premium, and Vanna exposure bias.
5. **Tactical Outlook for Next Session**: Provide actionable scenarios with explicit reference to key levels from the data.

Remember: You are analyzing the JSON, NOT calculating or challenging it."""
```

### 5 个章节结构 (硬约束):

| # | 章节 | 内容指引 |
|---|------|----------|
| 1 | **Macro Resonance Overview** | 综合共振信号,市场体制含义 |
| 2 | **Dealer Positioning Dynamics** | 解读 GEX profile / gamma regime / flip zone / support-resistance walls |
| 3 | **Dark Pool Flow Analysis** | 评估机构累积/派发,方向含义 |
| 4 | **Volatility Landscape** | VIX 期限结构 / panic premium / Vanna exposure bias |
| 5 | **Tactical Outlook for Next Session** | 可执行场景,显式引用数据中的关键位 |

### 注入字段:

- `{trading_date}` — 交易日期 (默认今天)
- `{snapshot.underlying_asset}` — 标的 (SPY/SPX/...)
- `{json_data}` — Layer 2 完整 JSON (`envelope.snapshot.to_compact_json()`)
- `{quality_note}` — 数据质量警告 (DEGRADED/ERROR 时插入)
- `{darkpool_quality_note}` — 暗盘逐源质量上下文
- `{events_section}` — 次日重要经济事件 (可选)
- `{few_shot_section}` — Few-Shot 样例 (高分历史快照)

### 数据质量警告 (L364-371):

```python
if snapshot.data_quality_flag == "DEGRADED":
    quality_note = (
        "\n\n⚠️ **Data Confidence: Reduced** — "
        f"Missing dimensions: {', '.join(snapshot.missing_dimensions)}. "
        "Interpret with caution."
    )
elif snapshot.data_quality_flag == "ERROR":
    quality_note = "\n\n❌ **CRITICAL: Data Feed Error detected.** Provide only a brief status summary."
```

---

## 6. Prompt #4: Backtest Prompt

**文件**: `llm_inference/prompt_builder.py:419-460`
**函数**: `PromptBuilder.build_backtest_prompt(envelope, historical_date, next_day_return)`
**用途**: 事后评估 LLM 在特定历史日期的判断质量

### 完整模板 (L448-460):

```python
prompt = f"""This is a BACKTEST evaluation for {historical_date}.

TARGET ASSET: {snapshot.underlying_asset}
RESONANCE DATA (historical snapshot):
```json
{json_data}
```{actual_note}

Based SOLELY on this historical JSON data, what would your strategy briefing have been?
Provide the same 5-section analysis as if this were a real-time briefing for {historical_date}."""
```

### 注入字段:

- `{historical_date}` — 历史日期
- `{snapshot.underlying_asset}` — 标的
- `{json_data}` — 该日期的历史 JSON 快照
- `{actual_note}` — 实际次日收益率(评估用,可选):
  ```
  For evaluation purposes only: The actual next-day return was {next_day_return:+.2f}% ({direction}).
  ```

**与 Prompt #3 的差异**: 不需要 few-shot / economic events / quality_note,但可注入实际次日收益作为 ground truth。

---

## 7. Prompt #5: Degraded Mode (降级文本模板, 纯文本)

**文件**: `llm_inference/prompt_builder.py:472-516`
**函数**: `PromptBuilder.build_degraded_mode_prompt(envelope)`
**用途**: 当 LLM API 不可用时,直接从 Layer 2 JSON 生成文本供通知分发
**调用**: `pipeline_v2/orchestrator.py:785`

### 完整内容 (L473-516):

```python
lines = [
    f"📊 Multi-source Resonance — {s.underlying_asset} Post-Market Snapshot",
    f"📅 {s.timestamp}",
    "",
    f"🎯 Resonance Score: {s.resonance_intensity_score}/100 ({s.resonance_signal_state})",
    "",
    "─── Dealer Positioning ───",
    f"  Gamma Regime: {s.net_gamma_regime}",
    f"  Gamma Flip Level: {s.gamma_flip_level}",
    f"  Flip Proximity: {s.gamma_flip_proximity_pct:+.2f}%",
    f"  Support Wall: {s.core_support_wall} ({s.support_wall_strength})",
    f"  Resistance Wall: {s.core_resistance_wall}",
    "",
    "─── Dark Pool ───",
    f"  DIX Status: {s.dark_pool_dix_status}",
    f"  Accumulation: {s.dark_pool_accumulation_regime}",
    f"  DIX Percentile: {s.dix_percentile}%",
    "",
    "─── Volatility ───",
    f"  VIX Term Structure: {s.vix_term_structure_state}",
    f"  Panic Premium: {s.vix_panic_premium_pct:+.2f}%",
    f"  Vanna Bias: {s.vanna_exposure_bias}",
    "",
    "─── Crypto Canary ───",
    f"  Leverage State: {s.crypto_leverage_state}",
    f"  OI Change: {s.crypto_oi_change_pct:+.2f}%",
    "",
    "─── Hawkes Process ───",
    f"  Branching State: {s.hawkes_branching_state} (ratio={s.hawkes_branching_ratio:.2f})",
    "",
    f"📋 Data Quality: {s.data_quality_flag}",
]

if s.missing_dimensions:
    lines.append(f"⚠️ Missing: {', '.join(s.missing_dimensions)}")

if s.darkpool_source_status:
    lines.append(f"📡 Dark Pool Sources: {s.darkpool_source_status}")
    lines.append(f"   Degradation Mode: {s.darkpool_degradation_mode}")
```

**关键设计**: 无 LLM 调用,纯文本摘要,保证通知系统在 LLM 不可用时仍能运转。

---

## 8. Prompt #6: Few-Shot Examples

**文件**: `llm_inference/prompt_builder.py:189-294`
**函数**: `PromptBuilder.load_few_shot_examples()` + `build_few_shot_section()`
**设计**: PRD §历史状态的不可变审计 — 从历史高分简报中加载样例,提升 LLM 推理一致性

### 8.1 加载函数 (L189-252)

```python
def load_few_shot_examples(
    self,
    num_examples: int = 2,
    min_resonance_score: int = 70,
) -> List[Dict[str, Any]]:
    """从数据库加载高分历史快照作为 Few-Shot 样例

    仅选择共振得分 ≥ min_resonance_score 的高质量快照，
    将其 JSON 摘要作为示例注入 LLM 提示词。
    """
```

**关键参数**:
- `num_examples`: 加载样例数量 (1-3)
- `min_resonance_score`: 最低共振得分门槛 (默认 70)

**数据来源**: `gateway_snapshots` 表 (`self._db.get_gateway_snapshot_history(days=90)`)

### 8.2 摘要函数 (L254-268)

```python
def _summarize_for_few_shot(self, snapshot_data: dict) -> str:
    """将历史快照压缩为 Few-Shot 可注入的简短 JSON 摘要

    仅保留对 LLM 推理有参考价值的 8-10 个关键字段。
    """
    key_fields = [
        'resonance_intensity_score', 'resonance_signal_state',
        'net_gamma_regime', 'gamma_flip_level',
        'core_support_wall', 'core_resistance_wall',
        'dark_pool_dix_status', 'dark_pool_accumulation_regime',
        'vix_term_structure_state', 'vanna_exposure_bias',
        'crypto_leverage_state', 'hawkes_branching_state',
    ]
```

**12 个关键字段**,压缩后 JSON 注入 User Prompt。

### 8.3 注入段模板 (L270-294)

**中文**:
```python
header = "\n\n## 历史参考样例 (Few-Shot Examples)\n以下是从历史高分简报复盘中选取的相似市场状态的参考分析框架，供你参考推理路径，不是当前数据:\n"
```

**英文**:
```python
header = "\n\n## Historical Reference Examples (Few-Shot)\nThe following are similar high-score market state snapshots from historical briefings, included as reference frameworks for your reasoning path. They are NOT current data:\n"
```

每个样例格式:
```
### Example {i}: {date} (Score: {score}/100)
```json
{json_summary}
```
```

---

## 9. Prompt #7: Dark Pool Quality Note

**文件**: `llm_inference/prompt_builder.py:296-342`
**函数**: `PromptBuilder._build_darkpool_quality_note(snapshot)`
**规范**: V2.0 §5 暗盘逐源质量上下文

### 完整内容 (L298-342):

```python
def _build_darkpool_quality_note(self, snapshot) -> str:
    """构建暗池数据质量上下文 — PRD §5 规范"""
    if not snapshot.darkpool_source_status:
        return ""

    # 检查源完整度
    sources = snapshot.darkpool_source_status
    total_sources = len(sources)
    online_sources = sum(1 for s in sources if s.get('status') == 'ONLINE')
    offline_sources = total_sources - online_sources

    if offline_sources == 0:
        return ""  # 全部正常,无需提示

    # 构造降级提示
    notes = []
    notes.append(f"\n\n📡 **Dark Pool Data Sources ({online_sources}/{total_sources} online):**")

    for src in sources:
        name = src.get('name', 'unknown')
        status = src.get('status', 'OFFLINE')
        avail = src.get('availability_pct', 0)
        notes.append(f"  - {name}: {status} ({avail:.0f}% availability)")

    if offline_sources > 0:
        notes.append(f"\n⚠️ **Degradation Mode**: {snapshot.darkpool_degradation_mode}")
        notes.append(f"  - Impact: {snapshot.darkpool_impact_summary}")

    return "\n".join(notes)
```

**关键设计**:
- 全部 ONLINE → 返回空(不污染 prompt)
- 部分 OFFLINE → 列出每个源 + 降级模式 + 影响摘要

**示例输出**:
```
📡 **Dark Pool Data Sources (2/4 online):**
  - SqueezeMetrics: ONLINE (100% availability)
  - FINRA: OFFLINE (0% availability)
  - ChartExchange: ONLINE (85% availability)
  - Stockgrid: OFFLINE (0% availability)

⚠️ **Degradation Mode**: PARTIAL
  - Impact: Short interest signal may be unreliable due to FINRA feed down
```

---

## 10. Prompt #8: HTML Report Template (输出)

**文件**: `llm_inference/report_composer.py:82-118+`
**类**: `ReportComposer`
**用途**: 把 LLM 输出 + JSON 包装成最终 HTML/Markdown 报告(这不是给 LLM 的,是给用户的)

### Markdown 模板 (L82-118):

```python
report = f"""# {self.branding} — Daily Strategy Briefing

**Date**: {now.strftime('%Y-%m-%d')}
**Asset**: {snapshot.underlying_asset}
**Pipeline Run**: `{pipeline_run_id[:8] if pipeline_run_id else 'N/A'}...`
**Generated**: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}
**Schema Version**: {envelope.schema_version}
{quality_warning}
---

## 📊 Resonance Summary

| Metric | Value |
|--------|-------|
| Resonance Score | **{snapshot.resonance_intensity_score}/100** ({snapshot.resonance_signal_state}) |
| Data Quality | {snapshot.data_quality_flag} |
| Available Dimensions | {snapshot.available_dimensions}/4 |

---

## 🎯 Key Levels

| Level | Price | Strength |
|-------|-------|----------|
| Gamma Flip | {snapshot.gamma_flip_level} | Proximity: {snapshot.gamma_flip_proximity_pct:+.2f}% |
...
```

(完整模板约 200 行,涵盖 Resonance / Key Levels / GEX / Dark Pool / VIX / Crypto / Hawkes / Strategy Briefing 等章节)

### HTML 包装 (L194+):

```python
wrapper = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{self.branding} — Daily Briefing</title>
  <style>...</style>
</head>
<body>
{report_body}
</body>
</html>"""
```

---

## 11. LLM 模型与参数配置

**文件**: `config/settings.py:74-94`

| 字段 | 默认值 | 环境变量 | 说明 |
|------|--------|----------|------|
| `LLM_PROVIDER` | `'openai'` | `LLM_PROVIDER` | `'openai'` / `'anthropic'` / `'local'` |
| `OPENAI_API_KEY` | `''` | `OPENAI_API_KEY` | OpenAI Key |
| `OPENAI_MODEL` | `'gpt-4o'` | `OPENAI_MODEL` | 模型名 (gpt-4o, gpt-4-turbo, gpt-3.5-turbo) |
| `OPENAI_ORGANIZATION` | `''` | `OPENAI_ORGANIZATION` | 可选 Org ID |
| `OPENAI_BASE_URL` | `''` | `OPENAI_BASE_URL` | 可选代理 |
| `ANTHROPIC_API_KEY` | `''` | `ANTHROPIC_API_KEY` | Anthropic Key |
| `ANTHROPIC_MODEL` | `'claude-sonnet-4-20250514'` | `ANTHROPIC_MODEL` | Claude 模型名 |
| `ANTHROPIC_BASE_URL` | `''` | `ANTHROPIC_BASE_URL` | 可选代理 |
| `LLM_TEMPERATURE` | `0.3` | `LLM_TEMPERATURE` | 采样温度 (低 = 稳定) |
| `LLM_MAX_TOKENS` | `2000` | `LLM_MAX_TOKENS` | 最大输出 tokens |
| `LLM_TIMEOUT` | `60` | `LLM_TIMEOUT` | 超时秒 |
| `LLM_MAX_RETRIES` | `3` | `LLM_MAX_RETRIES` | 重试次数 |

### 采样参数 (openai_provider.py / anthropic_provider.py):

```python
# OpenAI
temperature=0.3,
max_tokens=2000,
top_p=0.95,
frequency_penalty=0.0,
presence_penalty=0.0,

# Anthropic
temperature=0.3,
max_tokens=2000,
# (Claude 不暴露 top_p/frequency_penalty/presence_penalty)
```

### 调用消息格式:

**OpenAI** (openai_provider.py:108-114):
```python
messages = []
if system_prompt:
    messages.append({"role": "system", "content": system_prompt})
messages.append({"role": "user", "content": prompt})

response = await client.chat.completions.create(
    model=self.model,
    messages=messages,
    temperature=self.temperature,
    max_tokens=self.max_tokens,
    top_p=0.95,
    frequency_penalty=0.0,
    presence_penalty=0.0,
)
```

**Anthropic** (anthropic_provider.py:97-114):
```python
# Claude 的 system prompt 是通过单独参数传递的
kwargs = {
    'model': self.model,
    'max_tokens': self.max_tokens,
    'temperature': self.temperature,
    'messages': [{"role": "user", "content": prompt}],
}
if system_prompt:
    kwargs['system'] = system_prompt

response = await client.messages.create(**kwargs)
```

---

## 12. 如何替换/扩展 Prompt

### 12.1 切换语言 (运行时)

```python
builder = PromptBuilder()         # 英文 (默认)
builder.use_chinese()              # 切换到中文
system_prompt = builder.build_system_prompt()
```

### 12.2 自定义 Persona / Constraints

```python
builder = PromptBuilder(
    personality="You are a hedge fund risk manager...",  # 覆盖默认
    constraints="""MY CUSTOM CONSTRAINTS:
1. ...
""",
    language='en',
)
```

### 12.3 注入 Few-Shot 样例

```python
examples = builder.load_few_shot_examples(num_examples=3, min_resonance_score=80)
user_prompt = builder.build_user_prompt(envelope, few_shot_examples=examples)
```

### 12.4 切换 LLM Provider

```bash
# .env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-20250514
```

```python
from llm_inference.openai_provider import OpenAIProvider
from llm_inference.anthropic_provider import AnthropicProvider

provider = OpenAIProvider(api_key='sk-...', model='gpt-4o')
# or
provider = AnthropicProvider(api_key='sk-ant-...', model='claude-sonnet-4-20250514')

response = await provider.generate(user_prompt, system_prompt)
```

### 12.5 添加新的 User Prompt 模板

修改 `llm_inference/prompt_builder.py`,在 `PromptBuilder` 类加新方法:

```python
def build_intraday_alert_prompt(self, envelope: GatewayEnvelope) -> str:
    """盘中告警 Prompt (新增)"""
    snapshot = envelope.snapshot
    json_data = snapshot.to_compact_json()
    return f"""Generate an intraday alert for {snapshot.underlying_asset}...

RESONANCE DATA:
```json
{json_data}
```

Focus on:
1. 实时 gamma regime 变化
2. 暗池瞬时异动
3. VIX 期限结构突变
4. 加密市场冲击
5. 当日战术动作
"""
```

### 12.6 切换 Prompt 版本 (灰度)

可以在 `PromptBuilder` 加版本号:

```python
PROMPT_VERSION = "v2.5"

def build_system_prompt(self) -> str:
    if self.language == 'zh':
        return f"[PROMPT_VERSION: {PROMPT_VERSION}]\n\n{self.DEFAULT_PERSONALITY_CN}\n\n---\n\n{self.DEFAULT_CONSTRAINTS_CN}"
    else:
        return f"[PROMPT_VERSION: {PROMPT_VERSION}]\n\n{self.DEFAULT_PERSONALITY}\n\n---\n\n{self.DEFAULT_CONSTRAINTS}"
```

---

## 附录: Prompt 设计哲学 (PRD §3)

摘自 `Multi-source Resonance V2.0 解耦金融运算与LLM推理.md`:

> **第二层：上下文网关层（JSON 序列化纽带与拦截器）**
> - JSON 字典的结构化封装与契约定义
> - **消除幻觉风险与极致降低 Token 消耗**
> - 拦截器机制与数据异常清洗

> **第三层：大语言模型推理层（Prompt 注入与生成）**
> - 身份预设 (Persona) 与 Prompt 工程注入
> - **预训练金融逻辑的应用与对冲路径推理**
> - 结构化输出：策略简报与市场情绪解读

### 核心设计原则

1. **JSON 是唯一事实来源**: LLM 不得重新计算任何数字,只能解读 JSON
2. **强制 5 章节结构**: Macro / Dealer / DarkPool / Volatility / Tactical
3. **零数学公式**: 禁止引用 Black-Scholes / Delta / 标准差 / 概率分布
4. **Markdown 输出**: 统一格式,便于前端展示
5. **降级机制**: LLM 不可用 → 纯文本模板 (Prompt #5)
6. **Few-Shot 注入**: 历史高分简报作为示例
7. **数据质量警告**: DEGRADED / ERROR 显式标记
8. **暗池质量上下文**: 源完整度 + 降级模式

---

**维护者**: Raylan · **最后更新**: 2026-06-28