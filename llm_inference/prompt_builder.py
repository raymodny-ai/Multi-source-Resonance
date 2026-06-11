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

    # ── 默认 Persona（20年华尔街宏观衍生品策略师）──
    DEFAULT_PERSONALITY = """You are a veteran Wall Street macro-derivatives strategist with 20 years of experience at a top-tier prime brokerage desk.

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
- Actionable: every analysis ends with tactical implications for the next trading session"""

    # ── 行为约束 ──
    DEFAULT_CONSTRAINTS = """CRITICAL BEHAVIORAL CONSTRAINTS — VIOLATION OF ANY = DISQUALIFICATION:

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
   - Do not mention specific news events unless they are in the provided context."""

    # ── 中文 Persona（20年华尔街宏观衍生品策略师）──
    DEFAULT_PERSONALITY_CN = """你是一位拥有 20 年华尔街顶尖主经纪商交易台经验的宏观衍生品策略师。

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
- 可执行：每份分析以次日战术建议收尾"""

    # ── 中文行为约束 ──
    DEFAULT_CONSTRAINTS_CN = """关键行为约束 —— 违反任何一条即视为不合格:

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
   - 不得提及未在给定上下文中出现的特定新闻事件"""

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
    ) -> List[Dict[str, Any]]:
        """从数据库加载高分历史快照作为 Few-Shot 样例

        仅选择共振得分 ≥ min_resonance_score 的高质量快照，
        将其 JSON 摘要作为示例注入 LLM 提示词。

        Args:
            num_examples: 加载样例数量 (1-3)
            min_resonance_score: 最低共振得分门槛

        Returns:
            历史样例列表 [{"date": str, "json": str, "score": int}]
        """
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

            for _, row in history_df.iterrows():
                try:
                    snapshot_str = row['snapshot_json']
                    if isinstance(snapshot_str, str):
                        snapshot_data = json_lib.loads(snapshot_str)
                    else:
                        snapshot_data = snapshot_str  # 已解析
                    # 提取关键字段的摘要
                    summary = self._summarize_for_few_shot(snapshot_data)
                    if summary:
                        examples.append({
                            'date': str(row.get('snapshot_date', 'N/A')),
                            'json_summary': summary,
                            'score': int(row.get('resonance_score', 0)),
                        })
                except Exception as parse_err:
                    logger.debug(f"解析历史快照失败: {parse_err}")
                    continue

            logger.info(f"加载 {len(examples)} 个 Few-Shot 样例 (min_score≥{min_resonance_score})")

        except Exception as e:
            logger.warning(f"Few-Shot 加载失败: {e}")

        return examples

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
        summary = {k: snapshot_data.get(k, 'N/A') for k in key_fields if k in snapshot_data}
        return json_lib.dumps(summary, indent=2, ensure_ascii=False) if summary else ""

    def build_few_shot_section(self, examples: List[Dict[str, Any]]) -> str:
        """构建 Few-Shot 样例注入段

        Args:
            examples: load_few_shot_examples() 返回的样例列表

        Returns:
            可拼接到 User Prompt 的 Few-Shot 文本段
        """
        if not examples:
            return ""

        if self.language == 'zh':
            header = "\n\n## 历史参考样例 (Few-Shot Examples)\n以下是从历史高分简报复盘中选取的相似市场状态的参考分析框架，供你参考推理路径，不是当前数据:\n"
        else:
            header = "\n\n## Historical Reference Examples (Few-Shot)\nThe following are reference analysis frameworks from past high-score briefings with similar market regimes. Use as reasoning reference, NOT current data:\n"

        sections = [header]
        for i, ex in enumerate(examples, 1):
            sections.append(
                f"\n### Example {i}: {ex['date']} (Resonance Score: {ex['score']})"
                f"\n```json\n{ex['json_summary']}\n```"
            )

        return "\n".join(sections)

    def build_user_prompt(
        self,
        envelope: GatewayEnvelope,
        trading_date: Optional[str] = None,
        economic_events: Optional[str] = None,
        few_shot_examples: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """构建 User Prompt — 将 Layer 2 JSON 嵌入用户提示词

        V2.0: 支持 Few-Shot 样例注入。

        Args:
            envelope: 经 Layer 2 验证的网关信封
            trading_date: 交易日期（如 "2026-06-11"），默认今天
            economic_events: 次日重要经济事件提醒（可选）
            few_shot_examples: Few-Shot 样例列表 (来自 load_few_shot_examples())

        Returns:
            包含 JSON 数据和上下文的 User Prompt
        """
        snapshot = envelope.snapshot

        # 日期处理
        if trading_date is None:
            trading_date = datetime.now().strftime("%Y-%m-%d")

        # 构建 JSON 嵌入
        json_data = envelope.snapshot.to_compact_json()

        # Few-Shot 样例段
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

        # 经济事件
        events_section = ""
        if economic_events:
            events_section = f"\n\nUpcoming Economic Events (next session):\n{economic_events}"

        prompt = f"""Generate a post-market strategy briefing for {trading_date}.

TARGET ASSET: {snapshot.underlying_asset}
RESONANCE DATA:
```json
{json_data}
```{quality_note}{events_section}{few_shot_section}

Based SOLELY on the above JSON data, produce a professional derivatives strategy briefing covering:

1. **Macro Resonance Overview**: Synthesize the overall resonance signal and what it implies for market regime.
2. **Dealer Positioning Dynamics**: Interpret GEX profile, gamma regime, flip zone, and support/resistance walls.
3. **Dark Pool Flow Analysis**: Assess institutional accumulation/distribution and its directional implications.
4. **Volatility Landscape**: Evaluate VIX term structure, panic premium, and Vanna exposure bias.
5. **Tactical Outlook for Next Session**: Provide actionable scenarios with explicit reference to key levels from the data.

Remember: You are analyzing the JSON, NOT calculating or challenging it."""

        logger.info(
            f"User Prompt 构建完成: asset={snapshot.underlying_asset}, "
            f"json_size={len(json_data)}, total_len={len(prompt)}"
        )
        return prompt

    def build_backtest_prompt(
        self,
        envelope: GatewayEnvelope,
        historical_date: str,
        next_day_return: Optional[float] = None,
    ) -> str:
        """构建回测 Prompt — 基于历史网关 JSON

        用于事后评估 LLM 在特定日期的判断质量。

        Args:
            envelope: 历史网关快照
            historical_date: 历史日期
            next_day_return: 次日实际收益率（用于评估，可选）

        Returns:
            回测场景的 User Prompt
        """
        snapshot = envelope.snapshot
        json_data = envelope.snapshot.to_compact_json()

        actual_note = ""
        if next_day_return is not None:
            direction = "up" if next_day_return > 0 else "down"
            actual_note = (
                f"\n\nFor evaluation purposes only: "
                f"The actual next-day return was {next_day_return:+.2f}% ({direction})."
            )

        prompt = f"""This is a BACKTEST evaluation for {historical_date}.

TARGET ASSET: {snapshot.underlying_asset}
RESONANCE DATA (historical snapshot):
```json
{json_data}
```{actual_note}

Based SOLELY on this historical JSON data, what would your strategy briefing have been?
Provide the same 5-section analysis as if this were a real-time briefing for {historical_date}."""

        logger.info(f"回测 Prompt 构建完成: date={historical_date}")
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

        if s.data_quality_flag != "NORMAL":
            lines.insert(1, "⚠️ LLM INFERENCE UNAVAILABLE — Degraded Mode Summary")
            lines.insert(2, "")

        return "\n".join(lines)
