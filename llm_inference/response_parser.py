"""
Multi-source Resonance V2.0 - LLM 响应解析器

从 LLM 输出中提取结构化策略简报，包含：
- Markdown 模块解析（五大模块提取）
- 幻觉检测（LLM 引用数值与注入 JSON 交叉验证）
- 输出校验
"""

import re
import json
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field

from gateway.schemas import GatewayEnvelope
from utils.logger import getLogger

logger = getLogger('llm.response_parser')


@dataclass
class StrategyBriefing:
    """策略简报结构化表示

    Attributes:
        overview: 宏观共振概览
        dealer_positioning: 做市商动力学
        dark_pool_flow: 暗盘资金流向
        volatility: VIX/波动率动态
        tactical_outlook: 次日战术建议
        is_degraded: 是否降级模式
        hallucination_flags: 幻觉检测标记
    """
    overview: str = ""
    dealer_positioning: str = ""
    dark_pool_flow: str = ""
    volatility: str = ""
    tactical_outlook: str = ""
    is_degraded: bool = False
    hallucination_flags: List[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """返回完整 Markdown 文本"""
        sections = []
        if self.overview:
            sections.append(self.overview)
        if self.dealer_positioning:
            sections.append(self.dealer_positioning)
        if self.dark_pool_flow:
            sections.append(self.dark_pool_flow)
        if self.volatility:
            sections.append(self.volatility)
        if self.tactical_outlook:
            sections.append(self.tactical_outlook)
        return "\n\n".join(sections)

    @property
    def has_hallucination(self) -> bool:
        """是否存在幻觉风险"""
        return len(self.hallucination_flags) > 0


class ResponseParser:
    """LLM 响应解析器

    解析 LLM 输出的 Markdown 策略简报，提取五大模块内容，
    并执行幻觉检测确保 LLM 未自行编造数值。
    """

    # 五大模块的 Markdown 标题匹配模式
    SECTION_PATTERNS = {
        'overview': re.compile(
            r'##\s*\d*\.?\s*(?:Macro\s*)?Resonance\s*Overview',
            re.IGNORECASE,
        ),
        'dealer_positioning': re.compile(
            r'##\s*\d*\.?\s*(?:Dealer\s*Positioning|Gamma\s*(?:Exposure|Profile)|Market\s*Maker\s*Dynamics)',
            re.IGNORECASE,
        ),
        'dark_pool_flow': re.compile(
            r'##\s*\d*\.?\s*(?:Dark\s*Pool|Institutional\s*Flow|Block\s*Trade|Accumulation)',
            re.IGNORECASE,
        ),
        'volatility': re.compile(
            r'##\s*\d*\.?\s*(?:Volatility|VIX|Vol\s*Landscape|Volatility\s*Surface)',
            re.IGNORECASE,
        ),
        'tactical_outlook': re.compile(
            r'##\s*\d*\.?\s*(?:Tactical\s*Outlook|Next\s*Session|Trading\s*Plan|Strategy)',
            re.IGNORECASE,
        ),
    }

    # 数值提取模式（用于幻觉检测）
    NUMERIC_PATTERNS = [
        re.compile(r'(?:score|intensity)[^\d]*(\d{1,3})', re.IGNORECASE),
        re.compile(r'(?:flip|gamma\s*flip)[^\d]*(\d{3,5}\.?\d*)', re.IGNORECASE),
        re.compile(r'(?:support|put\s*wall)[^\d]*(\d{3,5}\.?\d*)', re.IGNORECASE),
        re.compile(r'(?:resistance|call\s*wall)[^\d]*(\d{3,5}\.?\d*)', re.IGNORECASE),
    ]

    @classmethod
    def parse_strategy_briefing(cls, llm_output: str) -> StrategyBriefing:
        """解析 LLM 输出为结构化策略简报

        识别五大模块的 Markdown 章节并分别提取。

        Args:
            llm_output: LLM 原始输出文本

        Returns:
            StrategyBriefing: 结构化策略简报
        """
        briefing = StrategyBriefing()

        # 检查是否为降级/错误响应
        if "Unable to generate briefing" in llm_output or "data feed error" in llm_output.lower():
            briefing.is_degraded = True
            briefing.overview = llm_output
            logger.warning("检测到降级/错误响应")
            return briefing

        # 提取各模块
        sections = cls._split_sections(llm_output)

        for i, (section_header, section_content) in enumerate(sections):
            mapped_section = cls._map_section(section_header)
            if mapped_section == 'overview':
                briefing.overview = section_content
            elif mapped_section == 'dealer_positioning':
                briefing.dealer_positioning = section_content
            elif mapped_section == 'dark_pool_flow':
                briefing.dark_pool_flow = section_content
            elif mapped_section == 'volatility':
                briefing.volatility = section_content
            elif mapped_section == 'tactical_outlook':
                briefing.tactical_outlook = section_content

        # 如果未能解析到任何模块，保留原始输出
        if not any([
            briefing.overview, briefing.dealer_positioning,
            briefing.dark_pool_flow, briefing.volatility,
            briefing.tactical_outlook,
        ]):
            briefing.overview = llm_output
            logger.warning("未能解析任何结构化模块，保留原始输出")

        logger.info(
            f"策略简报解析完成: sections={sum(1 for s in [briefing.overview, briefing.dealer_positioning, briefing.dark_pool_flow, briefing.volatility, briefing.tactical_outlook] if s)}"
        )
        return briefing

    @classmethod
    def detect_hallucination(
        cls,
        llm_output: str,
        envelope: GatewayEnvelope,
    ) -> List[str]:
        """检测 LLM 输出中的幻觉（编造与注入 JSON 不一致的数值）

        对比 LLM 输出中引用的关键数值与原始 JSON 数据，
        标记不一致的引用。

        Args:
            llm_output: LLM 原始输出
            envelope: 原始网关信封（包含 ground truth 数据）

        Returns:
            幻觉标记列表，空列表表示通过检测
        """
        flags: List[str] = []
        snapshot = envelope.snapshot

        # 1. 共振得分检测
        score_match = re.search(r'(?:score|intensity)[^\d]*(\d{1,3})', llm_output, re.IGNORECASE)
        if score_match:
            mentioned_score = int(score_match.group(1))
            if abs(mentioned_score - snapshot.resonance_intensity_score) > 5:
                flags.append(
                    f"共振得分不一致: LLM提到{mentioned_score}, JSON={snapshot.resonance_intensity_score}"
                )

        # 2. Gamma Flip Level 检测
        flip_match = re.search(r'(?:flip)[^\d]*(\d{3,5}\.?\d*)', llm_output, re.IGNORECASE)
        if flip_match and snapshot.gamma_flip_level > 0:
            mentioned_flip = float(flip_match.group(1))
            if abs(mentioned_flip - snapshot.gamma_flip_level) / snapshot.gamma_flip_level > 0.02:
                flags.append(
                    f"Gamma Flip 不一致: LLM提到{mentioned_flip}, JSON={snapshot.gamma_flip_level}"
                )

        # 3. 支撑位检测
        support_match = re.search(r'(?:support|put\s*wall)[^\d]*(\d{3,5}\.?\d*)', llm_output, re.IGNORECASE)
        if support_match and snapshot.core_support_wall > 0:
            mentioned_support = float(support_match.group(1))
            if abs(mentioned_support - snapshot.core_support_wall) / snapshot.core_support_wall > 0.02:
                flags.append(
                    f"支撑位不一致: LLM提到{mentioned_support}, JSON={snapshot.core_support_wall}"
                )

        # 4. 阻力位检测
        resistance_match = re.search(r'(?:resistance|call\s*wall)[^\d]*(\d{3,5}\.?\d*)', llm_output, re.IGNORECASE)
        if resistance_match and snapshot.core_resistance_wall > 0:
            mentioned_resistance = float(resistance_match.group(1))
            if abs(mentioned_resistance - snapshot.core_resistance_wall) / snapshot.core_resistance_wall > 0.02:
                flags.append(
                    f"阻力位不一致: LLM提到{mentioned_resistance}, JSON={snapshot.core_resistance_wall}"
                )

        # 5. Black-Scholes 引用检测（严重的数学泄漏）
        bs_keywords = ['black-scholes', 'black scholes', 'd1', 'd2', 'N(d1)', 'N(d2)',
                       'standard normal', 'cumulative distribution']
        for kw in bs_keywords:
            if kw in llm_output.lower():
                flags.append(f"数学泄漏: LLM 引用了 '{kw}' (Black-Scholes 相关内容)")
                break

        # 6. 原始数据泄漏检测
        raw_data_keywords = ['option chain', 'option_chain', 'raw gex', 'full gex',
                            'greeks matrix', 'implied volatility surface']
        for kw in raw_data_keywords:
            if kw in llm_output.lower():
                flags.append(f"原始数据泄漏: LLM 引用了 '{kw}'")
                break

        if flags:
            logger.warning(f"幻觉检测: {len(flags)}个问题")
            for flag in flags:
                logger.warning(f"  ⚠️ {flag}")
        else:
            logger.info("幻觉检测通过 ✓")

        return flags

    # ──────────────────────────────────────────────
    # 私有方法
    # ──────────────────────────────────────────────

    @classmethod
    def _split_sections(cls, text: str) -> List[Tuple[str, str]]:
        """按 ## 标题分割 Markdown 文本"""
        sections: List[Tuple[str, str]] = []
        lines = text.split('\n')
        current_header = ""
        current_content: List[str] = []

        for line in lines:
            if line.strip().startswith('##'):
                if current_header or current_content:
                    sections.append((current_header, '\n'.join(current_content).strip()))
                current_header = line.strip()
                current_content = [line]
            else:
                current_content.append(line)

        if current_header or current_content:
            sections.append((current_header, '\n'.join(current_content).strip()))

        # 如果没有找到 ## 标题，整篇作为 overview
        if not sections:
            sections.append(("", text.strip()))

        return sections

    @classmethod
    def _map_section(cls, header: str) -> Optional[str]:
        """将 Markdown 标题映射到模块名"""
        if not header:
            return 'overview'
        for section_name, pattern in cls.SECTION_PATTERNS.items():
            if pattern.search(header):
                return section_name
        return None

    @staticmethod
    def extract_module(llm_output: str, module_name: str) -> str:
        """从 LLM 输出中提取指定模块内容

        Args:
            llm_output: LLM 原始输出
            module_name: 模块名 (overview/dealer_positioning/dark_pool_flow/volatility/tactical_outlook)

        Returns:
            模块文本内容
        """
        briefing = ResponseParser.parse_strategy_briefing(llm_output)
        return getattr(briefing, module_name, "")
