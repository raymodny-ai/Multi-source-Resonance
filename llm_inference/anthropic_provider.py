"""
Multi-source Resonance V2.0 - Anthropic Provider

封装 Anthropic Claude 系列模型 (claude-sonnet-4-20250514, claude-3-opus 等)。
支持重试、超时处理。
"""

from typing import Optional
from llm_inference.base import LLMProvider, LLMResponse
from utils.logger import getLogger

logger = getLogger('llm.anthropic')


class AnthropicProvider(LLMProvider):
    """Anthropic Claude 系列适配器

    使用 anthropic 库的异步接口。

    Usage:
        provider = AnthropicProvider(
            api_key="sk-ant-...",
            model="claude-sonnet-4-20250514",
            temperature=0.3,
            max_tokens=2000,
        )
        response = await provider.generate(
            prompt="...JSON data...",
            system_prompt="You are a derivatives strategist...",
        )
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        temperature: float = 0.3,
        max_tokens: int = 2000,
        timeout: int = 60,
        base_url: Optional[str] = None,
    ):
        super().__init__(
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        self.base_url = base_url
        self._client = None

    @property
    def provider_name(self) -> str:
        return "anthropic"

    def _get_client(self):
        """懒加载 Anthropic 客户端"""
        if self._client is None:
            try:
                import anthropic
                client_kwargs = {
                    'api_key': self.api_key,
                    'timeout': float(self.timeout),
                }
                if self.base_url:
                    client_kwargs['base_url'] = self.base_url
                self._client = anthropic.AsyncAnthropic(**client_kwargs)
                logger.info(f"Anthropic 客户端初始化完成: model={self.model}")
            except ImportError:
                raise ImportError(
                    "anthropic 库未安装。请执行: pip install anthropic>=0.25.0"
                )
            except Exception as e:
                logger.error(f"Anthropic 客户端初始化失败: {e}")
                raise
        return self._client

    async def _generate_impl(
        self,
        prompt: str,
        system_prompt: str = "",
    ) -> LLMResponse:
        """Anthropic Messages API 调用"""
        client = self._get_client()

        # Claude 的 system prompt 是通过单独参数传递的
        kwargs = {
            'model': self.model,
            'max_tokens': self.max_tokens,
            'temperature': self.temperature,
            'messages': [{"role": "user", "content": prompt}],
        }

        if system_prompt:
            kwargs['system'] = system_prompt

        logger.info(
            f"Anthropic 请求: model={self.model}, "
            f"system_prompt_len={len(system_prompt)}, prompt_len={len(prompt)}"
        )

        response = await client.messages.create(**kwargs)

        content_blocks = response.content
        text_content = ""
        for block in content_blocks:
            if hasattr(block, 'text'):
                text_content += block.text

        usage = {
            'prompt_tokens': response.usage.input_tokens if response.usage else 0,
            'completion_tokens': response.usage.output_tokens if response.usage else 0,
            'total_tokens': (
                (response.usage.input_tokens + response.usage.output_tokens)
                if response.usage else 0
            ),
        }

        logger.info(
            f"Anthropic 响应: tokens={usage['total_tokens']}, "
            f"finish={response.stop_reason}"
        )

        return LLMResponse(
            content=text_content,
            model=self.model,
            usage=usage,
            finish_reason=response.stop_reason or "end_turn",
        )
