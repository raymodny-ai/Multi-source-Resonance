"""
Multi-source Resonance V2.0 - Layer 3 LLM 推理层

LLM 仅基于 Layer 2 的结构化 JSON 输入进行定性金融逻辑推理，
绝不接触原始数据（期权链、逐笔暗盘记录等）。

数据流:
    Layer 2 (GatewayEnvelope) → Prompt Builder → LLM Provider
    → Response Parser → Report Composer → Notification

核心组件:
- LLMProvider (抽象基类): 统一的 LLM 调用接口
- OpenAIProvider: OpenAI GPT 系列适配器
- AnthropicProvider: Anthropic Claude 系列适配器
- PromptBuilder: System/User/Backtest Prompt 构建器
- ResponseParser: LLM 输出解析与幻觉检测
- ReportComposer: Markdown/HTML/Telegram 策略简报生成
"""

from llm_inference.base import LLMProvider
from llm_inference.openai_provider import OpenAIProvider
from llm_inference.anthropic_provider import AnthropicProvider
from llm_inference.prompt_builder import PromptBuilder
from llm_inference.response_parser import ResponseParser
from llm_inference.report_composer import ReportComposer

__all__ = [
    'LLMProvider',
    'OpenAIProvider',
    'AnthropicProvider',
    'PromptBuilder',
    'ResponseParser',
    'ReportComposer',
]
