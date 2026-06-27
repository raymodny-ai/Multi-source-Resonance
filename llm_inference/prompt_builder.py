"""
Multi-source Resonance V2.0 - Prompt 构建器

负责构建 LLM 的 System Prompt 和 User Prompt：
- System Prompt: Persona（20年华尔街宏观衍生品策略师）+ 行为准则 + 输出格式约束
- User Prompt: Layer 2 JSON 嵌入 + 上下文信息
- Few-Shot Prompting: 从历史高分简报中加载样例 (PRD §历史状态的不可变审计与回测)
- Backtest Prompt: 基于历史网关 JSON 生成回测 Prompt

所有 Prompt 绝不包含原始数学数据（如完整期权链、Black-Scholes 公式等）。
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
import json as json_lib

from gateway.schemas import GatewayEnvelope
from utils.logger import getLogger

logger = getLogger('llm.prompt_builder')


class PromptBuilder:
    """LLM Prompt 构建器

    确保 LLM 仅接收经过 Layer 2 验证的 JSON 数据，
    并且其 Persona 和行为准则严格控制其输出范围。

    Attributes:
        personality: Persona 描述（可自定义覆盖）
        constraints: 行为约束列表
    """

    # ── 默认 Persona（Pure financial microstructure reasoning engine）──
    # ── V2.6: Temporal Obfuscation — 脱去宏观背景与历史事件联想 ──
    DEFAULT_PERSONALITY = """You are a Pure financial microstructure reasoning engine. You must ignore any macroeconomic context or historical events, and judge only the dealer's hedging state and whether liquidity-sweep exhaustion conditions are triggered, based SOLELY on the de-identified multi-dimensional vector data provided below (including the GEX reversal threshold, branching ratio n, and DIX divergence degree).

Your expertise spans:
- Pure abstract option market-making dynamics (Gamma Exposure, Delta Hedging flows) — NO asset names attached
- Data-driven dark-pool liquidity microstructure (asset-class-agnostic DIX anomalies, block trade footprints)
- De-identified volatility surface arbitrage and cross-asset regime analysis — without referencing specific calendar events

Your reasoning principles:
- Strict structural logic: every conclusion must be derived from the vector fields in the JSON
- Anti-hindsight-bias: you DO NOT know — and must NEVER guess — the real calendar date, the real asset ticker, or any past/future news
- Asset-blind analysis: when you see "Asset_A" you treat it as a pure label, not as SPY/SPX/BTC/etc.
- Date-blind analysis: when you see "Day 0" / "Day -1" you treat them as relative markers, not as real dates

Your communication style:
- Direct, concise, no fluff
- Data-driven but qualitative — you interpret structural patterns, not compute numbers
- Risk-first mindset: always highlight what could go wrong
- Actionable: every analysis ends with structural tactical implications for the next period"""

    # ── 行为约束 ──
    # ── V2.6: 强化"去标识化(De-identified)"盲测约束 ──
    DEFAULT_CONSTRAINTS = """CRITICAL BEHAVIORAL CONSTRAINTS — TEMPORAL OBFUSCATION ENABLED. VIOLATION OF ANY = DISQUALIFICATION:

1. ABSOLUTE TIME / ASSET BLIND TESTING:
   - You MUST NOT guess what real ticker "Asset_A" / "Asset_B" / "Asset_Unknown" stands for.
   - You MUST NOT associate "Day 0" / "Day -1" / "Day +1" with any real calendar date.
   - You MUST NOT recall, reference, or speculate about any news cycle, FOMC meeting, earnings release, geopolitical event, or macro timeline.
   - The obfuscated JSON is your ONLY ground truth.

2. ABSOLUTE TRUST IN PROVIDED DATA:
   - The JSON fields in the user prompt are the ONLY source of truth.
   - You MUST NOT recalculate, estimate, or second-guess any number.
   - If a field says "Extreme Confluence" with score 92, you accept it as ground truth.

3. NO MATHEMATICAL COMPUTATION (vector-derived only):
   - DO NOT reference Black-Scholes, delta formulas, or any pricing model.
   - DO NOT attempt to derive implied volatility, gamma, or any greek.
   - DO NOT mention standard deviations, probability distributions, or quantitative models.
   - You are a qualitative logical reasoning engine over multi-dimensional microstructure vectors — NOT a quantitative calculator.

4. FORMAT REQUIREMENTS:
   - Output in clean Markdown with clear section headers.
   - Each section must have a ## header.
   - Use bullet points for key observations.
   - End with a "## Structural Outlook for Day +1" section.

5. DATA FIDELITY:
   - When referencing a number from the JSON, keep it EXACTLY as provided.
   - If data quality is DEGRADED, note "⚠️ Data Confidence: Reduced" at the top.
   - If data quality is ERROR, respond with "Unable to generate briefing: data feed error."

6. NO SPECULATION BEYOND STRUCTURED DATA:
   - Do not invent narratives unsupported by the JSON vector fields.
   - Do not predict exact price levels beyond the provided support/resistance walls.
   - Do not mention specific news events or macro catalysts — they are intentionally absent from this context."""

    # ── 中文 Persona（Pure financial microstructure reasoning engine）──
    # ── V2.6: 时间混淆测试 — 脱去宏观背景与历史事件联想 ──
    DEFAULT_PERSONALITY_CN = """你是一个纯粹的金融微观结构推理引擎。请忽略任何宏观经济背景或历史事件，仅根据以下提供的去标识化多维向量数据（包含 GEX 反转阈值、分支比 $n$、DIX 背离度），判断当前市场做市商的对冲状态，并评估是否触发了流动性清算衰竭的特征条件。

你的专业领域涵盖：
- 纯抽象维度的期权做市动力学（Gamma 暴露、Delta 对冲流量）—— 不绑定任何真实资产名称
- 数据驱动的暗池流动性微观结构（无资产偏见的 DIX 异常、大宗交易足迹）
- 去标识化的波动率曲面套利与跨资产体制分析 —— 不关联任何具体日历事件

你的推理原则：
- 严格的结构性逻辑：每一条结论都必须从 JSON 向量字段中推导
- 反"后见之明偏差"：你不知道 —— 也绝不能猜测 —— 真实的日历日期、真实的资产代码，或任何过去/未来的新闻
- 资产盲测分析：当你看到 "Asset_A" 时，将其视为纯粹的标签，而不是 SPY/SPX/BTC 等
- 时间盲测分析：当你看到 "Day 0" / "Day -1" 时，将其视为相对标记，而不是真实日期

你的沟通风格：
- 直接、精炼、无赘述
- 数据驱动但定性分析 —— 你解读结构性模式，而非计算数字
- 风险优先导向：始终突出可能出错的环节
- 可执行：每份分析以下一期的结构性战术建议收尾"""

    # ── 中文行为约束 ──
    # ── V2.6: 强化"去标识化(De-identified)"盲测约束 ──
    DEFAULT_CONSTRAINTS_CN = """关键行为约束 —— 时间混淆测试已启用。违反任何一条即视为不合格:

1. 绝对的无时间/无资产上下文盲测:
   - 禁止猜测 Asset_A、Asset_B、Asset_Unknown 等占位符对应的真实标的资产
   - 禁止联想 Day 0、Day -1、Day +1 对应的真实日历日期或任何相关联的新闻事件
   - 禁止回忆、引用或推测任何新闻周期、FOMC 会议、财报发布、地缘事件、或宏观时间线
   - 去标识化的 JSON 是你唯一的事实来源

2. 对提供数据的绝对信任:
   - 用户提示词中的 JSON 字段是唯一的事实来源
   - 不得重新计算、估计或质疑任何数值
   - 如果字段显示"Extreme Confluence"且得分 92，你应无条件接受

3. 禁止非向量衍生的数学推导:
   - 不得引用 Black-Scholes、Delta 公式或任何定价模型
   - 不得尝试推导隐含波动率、Gamma 或任何希腊字母
   - 不得提及标准差、概率分布或量化模型
   - 你是一个基于多维微观结构向量的定性逻辑推理引擎，而非定量计算器

4. 不可发散的格式要求:
   - 以干净的 Markdown 格式输出，含清晰的章节标题
   - 每个章节必须使用 ## 标题
   - 关键观察使用项目符号
   - 以"## Day +1 结构性展望"章节收尾

5. 数据保真度:
   - 引用 JSON 中的数字时必须保持原样
   - 如果数据质量为 DEGRADED，在顶部标注"⚠️ 数据置信度：降低"
   - 如果数据质量为 ERROR，回复"无法生成简报：数据源错误"

6. 不超越结构化数据的推测:
   - 不得编造 JSON 向量字段中未支持的叙事
   - 不得预测超出给定支撑/阻力墙范围的精确价格位
   - 不得提及具体的新闻事件或宏观催化剂 —— 它们在本上下文中已被刻意剥离"""

    def __init__(
        self,
        personality: Optional[str] = None,
        constraints: Optional[str] = None,
        language: str = "en",
        db_manager=None,
    ):
        """初始化 Prompt 构建器

        Args:
            personality: 自定义 Persona (覆盖默认值)
            constraints: 自定义行为约束 (覆盖默认值)
            language: 语言偏好 'en' (英文) 或 'zh' (中文)
            db_manager: DatabaseManager 实例 (用于加载 Few-Shot 样例)
        """
        self.language = language
        if personality:
            self.personality = personality
            self.constraints = constraints or self.DEFAULT_CONSTRAINTS
        elif language == 'zh':
            self.personality = self.DEFAULT_PERSONALITY_CN
            self.constraints = constraints or self.DEFAULT_CONSTRAINTS_CN
        else:
            self.personality = personality or self.DEFAULT_PERSONALITY
            self.constraints = constraints or self.DEFAULT_CONSTRAINTS
        self._db = db_manager

    def build_system_prompt(self) -> str:
        """构建 System Prompt

        注入 Persona + 行为准则 + 输出格式约束。
        LLM 在整个对话中持续受此约束。

        Returns:
            完整的 System Prompt 字符串
        """
        prompt = f"""{self.personality}

---

{self.constraints}"""

        logger.debug(f"System Prompt 长度: {len(prompt)} 字符")
        return prompt

    def use_chinese(self) -> None:
        """切换到中文 Persona 和约束 (V2.0)"""
        self.language = 'zh'
        self.personality = self.DEFAULT_PERSONALITY_CN
        self.constraints = self.DEFAULT_CONSTRAINTS_CN
        logger.info("PromptBuilder 已切换为中文模式")

    @property
    def is_chinese(self) -> bool:
        """是否使用中文模式"""
        return self.language == 'zh'

    # ──────────────────────────────────────────────
    # Few-Shot Prompting (V2.0 PRD §历史状态的不可变审计)
    # ──────────────────────────────────────────────

    def load_few_shot_examples(
        self,
        num_examples: int = 2,
        min_resonance_score: int = 70,
        current_real_date: Optional['date'] = None,
    ) -> List[Dict[str, Any]]:
        """从数据库加载高分历史快照作为 Few-Shot 样例

        仅选择共振得分 ≥ min_resonance_score 的高质量快照，
        将其 JSON 摘要作为示例注入 LLM 提示词。

        V2.6: Temporal Obfuscation
            - 历史 snapshot_date 被转换为相对 Day -X (而非真实日期)
            - 历史 underlying_asset 被映射为 Asset_A/Asset_B (与当前脱敏一致)
            - 必须传 current_real_date 才能正确计算 Day 偏移

        Args:
            num_examples: 加载样例数量 (1-3)
            min_resonance_score: 最低共振得分门槛
            current_real_date: 当前真实日期 (V2.6 用于 Day 偏移计算)

        Returns:
            历史样例列表 [{
                "date": "Day -45",           # V2.6: 相对时间
                "original_date": "2026-05-14", # V2.6: 真实日期 (供内部审计,不会注入 prompt)
                "asset_label": "Asset_A",     # V2.6: 脱敏资产
                "json_summary": str,          # 已脱敏 JSON
                "score": int
            }]
        """
        from datetime import date as _date

        if current_real_date is None:
            current_real_date = _date.today()

        examples = []
        if self._db is None:
            logger.debug("无数据库连接，跳过 Few-Shot 加载")
            return examples

        try:
            history_df = self._db.get_gateway_snapshot_history(days=90)
            if history_df.empty:
                logger.debug("历史快照为空，跳过 Few-Shot")
                return examples

            # 筛选高分快照
            if 'resonance_score' in history_df.columns:
                history_df = history_df[history_df['resonance_score'] >= min_resonance_score]
            if 'snapshot_json' not in history_df.columns:
                return examples

            # 按得分降序取前 N
            if 'resonance_score' in history_df.columns:
                history_df = history_df.sort_values('resonance_score', ascending=False)
            history_df = history_df.head(num_examples)

            # V2.6: 引入 ASSET_OBFUSCATION_MAP 用于历史快照脱敏
            from gateway.serializer import ASSET_OBFUSCATION_MAP

            for _, row in history_df.iterrows():
                try:
                    snapshot_str = row['snapshot_json']
                    if isinstance(snapshot_str, str):
                        snapshot_data = json_lib.loads(snapshot_str)
                    else:
                        snapshot_data = snapshot_str  # 已解析

                    # ── V2.6: 历史快照脱敏 (Day 偏移 + Asset 匿名) ──
                    # 1. 资产代码脱敏
                    hist_asset = snapshot_data.get('underlying_asset', '')
                    obfuscated_asset = ASSET_OBFUSCATION_MAP.get(hist_asset, "Asset_Unknown")
                    snapshot_data['underlying_asset'] = obfuscated_asset

                    # 2. 历史日期转相对偏移
                    hist_date_raw = row.get('snapshot_date', None)
                    if hist_date_raw is not None:
                        try:
                            if isinstance(hist_date_raw, str):
                                hist_date = _date.fromisoformat(hist_date_raw.split('T')[0])
                            else:
                                hist_date = hist_date_raw
                            day_offset = (current_real_date - hist_date).days
                            relative_marker = f"Day {day_offset:+d}"   # "Day -45" / "Day +0"
                        except (ValueError, TypeError) as e:
                            logger.debug(f"历史日期解析失败,使用默认 Day -X: {e}")
                            relative_marker = "Day -X"
                    else:
                        relative_marker = "Day -X"

                    # 提取关键字段的摘要 (含脱敏后的数据)
                    summary = self._summarize_for_few_shot(snapshot_data)
                    if summary:
                        examples.append({
                            'date': relative_marker,                              # V2.6 脱敏后
                            'original_date': str(hist_date_raw or 'N/A'),        # 审计用,不会注入
                            'asset_label': obfuscated_asset,                      # V2.6 脱敏后
                            'json_summary': summary,
                            'score': int(row.get('resonance_score', 0)),
                        })
                except Exception as parse_err:
                    logger.debug(f"解析历史快照失败: {parse_err}")
                    continue

            logger.info(
                f"加载 {len(examples)} 个 Few-Shot 样例 (V2.6 脱敏, min_score≥{min_resonance_score})"
            )

        except Exception as e:
            logger.warning(f"Few-Shot 加载失败: {e}")

        return examples

    def _summarize_for_few_shot(self, snapshot_data: dict) -> str:
        """将历史快照压缩为 Few-Shot 可注入的简短 JSON 摘要

        仅保留对 LLM 推理有参考价值的 8-10 个关键字段。
        V2.6: 调用方传入的 snapshot_data 应已被脱敏 (Asset_X + Day X 形式)。
        """
        key_fields = [
            'resonance_intensity_score', 'resonance_signal_state',
            'net_gamma_regime', 'gamma_flip_level',
            'core_support_wall', 'core_resistance_wall',
            'dark_pool_dix_status', 'dark_pool_accumulation_regime',
            'vix_term_structure_state', 'vanna_exposure_bias',
            'crypto_leverage_state', 'hawkes_branching_state',
        ]
        summary = {k: snapshot_data.get(k, 'N/A') for k in key_fields if k in snapshot_data}
        return json_lib.dumps(summary, indent=2, ensure_ascii=False) if summary else ""

    def build_few_shot_section(self, examples: List[Dict[str, Any]]) -> str:
        """构建 Few-Shot 样例注入段

        V2.6: examples 中 date 字段已是相对时间 (Day -X),asset_label 是脱敏标签。
        header 文本也同步强化"去标识化"声明。

        Args:
            examples: load_few_shot_examples() 返回的样例列表

        Returns:
            可拼接到 User Prompt 的 Few-Shot 文本段
        """
        if not examples:
            return ""

        if self.language == 'zh':
            header = "\n\n## 结构化参考样例 (Few-Shot References)\n以下是从相似多维向量状态中提取的去标识化历史参考分析，供你参考纯粹的逻辑推理路径。它们反映的是 Day -X 的状态:\n"
        else:
            header = "\n\n## De-identified Reference Examples (Few-Shot)\nThe following are anonymized historical reference analyses extracted from similar multi-dimensional vector states. Use as reference for pure logical reasoning paths. They reflect Day -X states:\n"

        sections = [header]
        for i, ex in enumerate(examples, 1):
            sections.append(
                f"\n### Example {i}: {ex['date']} (Resonance Score: {ex['score']})"
                f"\n```json\n{ex['json_summary']}\n```"
            )

        return "\n".join(sections)

    def _build_darkpool_quality_note(self, snapshot) -> str:
        """构建暗盘逐源质量上下文提示 (规范 §5)

        当暗盘数据源出现降级时，为 LLM 注入逐源状态细节，
        帮助策略师准确评估数据置信度。
        """
        if not snapshot.darkpool_source_status:
            return ""

        status = snapshot.darkpool_source_status
        mode = snapshot.darkpool_degradation_mode

        if mode == "NORMAL":
            return ""

        lines = ["\n\n📡 **Dark Pool Data Source Status**:"]

        source_labels = {
            "axlfi": "AXLFI (暗盘净头寸)",
            "squeezemetrics": "SqueezeMetrics (DIX/GEX)",
            "stockgrid": "Stockgrid (已下线)",
        }

        for src, state in status.items():
            label = source_labels.get(src, src)
            if state == "OK":
                lines.append(f"  ✅ {label}: ONLINE")
            elif state == "DEGRADED_NETWORK":
                lines.append(f"  ⚠️ {label}: DEGRADED (网络延迟/降级)")
            elif state == "UNAVAILABLE":
                lines.append(f"  ❌ {label}: OFFLINE")
            elif state == "STRUCTURE_CHANGED":
                lines.append(f"  🔧 {label}: STRUCTURE CHANGED (需适配器更新)")
            elif state == "CONTRACT_VIOLATION":
                lines.append(f"  📋 {label}: DATA CONTRACT VIOLATION")
            else:
                lines.append(f"  ❓ {label}: {state}")

        if mode == "FALLBACK_ONLY_GEX":
            lines.append("\n⚠️ **ALL dark pool sources are unavailable.** "
                         "Resonance is relying solely on GEX+VIX+Crypto dimensions.")
            lines.append("Dark pool analysis in this briefing is UNRELIABLE.")
        elif mode == "DEGRADED":
            lines.append("\n⚠️ **One or more dark pool sources are degraded.** "
                         "Cross-verify dark pool signals with extra caution.")

        return "\n".join(lines)

    def build_user_prompt(
        self,
        envelope: GatewayEnvelope,
        trading_date: Optional[str] = None,           # V2.6: deprecated, kept for backward compat
        economic_events: Optional[str] = None,        # V2.6: deprecated, intentionally ignored (anti-hindsight)
        few_shot_examples: Optional[List[Dict[str, Any]]] = None,
        relative_time_marker: str = "Day 0",          # V2.6: relative time, NEVER a real date
        obfuscated_asset: Optional[str] = None,       # V2.6: obfuscated asset label (e.g. "Asset_A")
        obfuscated_json_data: Optional[str] = None,   # V2.6: pre-obfuscated JSON string
    ) -> str:
        """构建 User Prompt — 将 Layer 2 脱敏 JSON 嵌入用户提示词

        V2.0: 支持 Few-Shot 样例注入。
        V2.6: 时间混淆测试 (Temporal Obfuscation Testing)
            - 移除真实日期 trading_date (默认相对 Day 0)
            - 移除 economic_events 注入 (会泄露宏观时间线)
            - 资产代码强制匿名为 Asset_A / Asset_B
            - JSON 字符串调用方需先经 to_obfuscated_json() 处理
            - 旧参数保留但 deprecated,新调用方传 relative_time_marker + obfuscated_*

        Args:
            envelope: 经 Layer 2 验证的网关信封 (内部字段仍可用,仅作回退)
            trading_date: (DEPRECATED V2.6) 真实交易日期,将被忽略
            economic_events: (DEPRECATED V2.6) 经济事件,将被忽略
            few_shot_examples: Few-Shot 样例列表 (来自 load_few_shot_examples())
            relative_time_marker: 相对时间标记 (默认 "Day 0")
            obfuscated_asset: 脱敏资产标签 (默认 "Asset_A")
            obfuscated_json_data: 脱敏 JSON 字符串 (调用方需传入)

        Returns:
            包含脱敏 JSON 数据和相对时间上下文的 User Prompt
        """
        snapshot = envelope.snapshot

        # ── V2.6 时间混淆: 强制使用相对时间 + 脱敏资产 ──
        if obfuscated_asset is None:
            obfuscated_asset = "Asset_A"   # 默认标签,绝不暴露真实代码

        if obfuscated_json_data is None:
            # 调用方未传入脱敏 JSON,使用原始 (违反混淆原则,记录警告)
            logger.warning(
                "build_user_prompt: 未传入 obfuscated_json_data,正在使用原始 JSON。"
                "建议调用方使用 GatewaySerializer.to_obfuscated_json() 预脱敏。"
            )
            obfuscated_json_data = envelope.snapshot.to_compact_json()
        else:
            logger.debug(
                f"build_user_prompt: 使用脱敏 JSON ({len(obfuscated_json_data)} bytes), "
                f"asset={obfuscated_asset}, relative_time={relative_time_marker}"
            )

        # Few-Shot 样例段 (内部已脱敏)
        few_shot_section = self.build_few_shot_section(few_shot_examples or [])

        # 数据质量标志处理
        quality_note = ""
        if snapshot.data_quality_flag == "DEGRADED":
            quality_note = (
                "\n\n⚠️ **Data Confidence: Reduced** — "
                f"Missing dimensions: {', '.join(snapshot.missing_dimensions)}. "
                "Interpret with caution."
            )
        elif snapshot.data_quality_flag == "ERROR":
            quality_note = "\n\n❌ **CRITICAL: Data Feed Error detected.** Provide only a brief status summary."

        # 暗盘逐源质量上下文 (规范 §5)
        darkpool_quality_note = self._build_darkpool_quality_note(snapshot)

        # ── V2.6: events_section 已移除,经济事件是宏观时间线的泄露源 ──
        # (保留代码位但永远为空字符串)
        events_section = ""

        prompt = f"""Generate a purely structural market state briefing for {relative_time_marker} (Current Target Period).

TARGET ASSET: {obfuscated_asset}
DE-IDENTIFIED RESONANCE DATA:
```json
{obfuscated_json_data}
```{quality_note}{darkpool_quality_note}{events_section}{few_shot_section}

Based SOLELY on the above anonymized JSON vector data, produce a professional microstructure strategy briefing covering:

1. **Microstructure Resonance Overview**: Synthesize the overall resonance signal without referencing macro regimes.
2. **Dealer Positioning Dynamics**: Interpret GEX profile, gamma regime, and abstract support/resistance walls.
3. **Liquidity Flow & Exhaustion Analysis**: Assess accumulation distribution and explicitly evaluate if conditions for liquidity sweep exhaustion are triggered.
4. **Volatility Landscape**: Evaluate structural panic premium and Vanna exposure bias.
5. **Structural Outlook for {relative_time_marker} + 1**: Provide actionable, pure-price-action scenarios based explicitly on the data's key levels.

Remember: You are analyzing the structural JSON. Do not guess the asset. Do not guess the date."""

        logger.info(
            f"User Prompt 构建完成 (V2.6 obfuscated): "
            f"asset_label={obfuscated_asset}, relative_time={relative_time_marker}, "
            f"json_size={len(obfuscated_json_data)}, total_len={len(prompt)}"
        )
        return prompt

    def build_backtest_prompt(
        self,
        envelope: GatewayEnvelope,
        historical_date: str,
        next_day_return: Optional[float] = None,
        current_real_date: Optional['date'] = None,
        obfuscated_asset: Optional[str] = None,
        obfuscated_json_data: Optional[str] = None,
    ) -> str:
        """构建回测 Prompt — 基于历史网关 JSON

        用于事后评估 LLM 在特定日期的判断质量。

        V2.6: Temporal Obfuscation
            - historical_date 转换为 Day -X (相对 current_real_date)
            - 历史快照调用 GatewaySerializer.to_obfuscated_json() 脱敏
            - 评估目的 actual_note 保留,但不暴露真实资产

        Args:
            envelope: 历史网关快照
            historical_date: 历史日期 (传入用于 Day 偏移计算,但不直接用于 prompt)
            next_day_return: 次日实际收益率（用于评估，可选）
            current_real_date: 当前真实日期 (V2.6 用于计算 Day 偏移)
            obfuscated_asset: 脱敏资产标签
            obfuscated_json_data: 脱敏 JSON 字符串

        Returns:
            回测场景的 User Prompt (脱敏)
        """
        from datetime import date as _date, datetime as _datetime

        snapshot = envelope.snapshot

        # V2.6: 脱敏资产
        if obfuscated_asset is None:
            obfuscated_asset = "Asset_A"

        # V2.6: 脱敏 JSON
        if obfuscated_json_data is None:
            logger.warning(
                "build_backtest_prompt: 未传入 obfuscated_json_data,使用原始 JSON。"
            )
            obfuscated_json_data = snapshot.to_compact_json()

        # V2.6: 历史日期转相对 Day 偏移
        if current_real_date is None:
            current_real_date = _date.today()

        try:
            if isinstance(historical_date, str):
                hist_date = _date.fromisoformat(historical_date.split('T')[0])
            elif isinstance(historical_date, _datetime):
                hist_date = historical_date.date()
            else:
                hist_date = historical_date
            day_offset = (current_real_date - hist_date).days
            relative_marker = f"Day {day_offset:+d}"
        except (ValueError, TypeError):
            relative_marker = "Day -X"

        actual_note = ""
        if next_day_return is not None:
            direction = "up" if next_day_return > 0 else "down"
            actual_note = (
                f"\n\nFor evaluation purposes only: "
                f"The actual next-day return was {next_day_return:+.2f}% ({direction})."
            )

        prompt = f"""This is a BACKTEST evaluation for {relative_marker}.

TARGET ASSET: {obfuscated_asset}
DE-IDENTIFIED RESONANCE DATA (historical snapshot):
```json
{obfuscated_json_data}
```{actual_note}

Based SOLELY on this anonymized JSON vector data, what would your strategy briefing have been?
Provide the same 5-section analysis as if this were a real-time briefing for {relative_marker}.

Remember: You are analyzing the structural JSON. Do not guess the asset. Do not guess the date."""

        logger.info(
            f"回测 Prompt 构建完成 (V2.6 obfuscated): relative_time={relative_marker}, "
            f"asset={obfuscated_asset}"
        )
        return prompt

    def build_degraded_mode_prompt(
        self,
        envelope: GatewayEnvelope,
    ) -> str:
        """构建降级模式 Prompt — LLM 不可用时的纯文本摘要

        当 LLM API 不可用时，直接从 Layer 2 JSON 生成文本供通知分发。

        Args:
            envelope: 网关信封

        Returns:
            纯文本格式的关键指标摘要
        """
        s = envelope.snapshot

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

        if s.data_quality_flag != "NORMAL":
            lines.insert(1, "⚠️ LLM INFERENCE UNAVAILABLE — Degraded Mode Summary")
            lines.insert(2, "")

        return "\n".join(lines)
