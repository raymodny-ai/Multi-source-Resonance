"""
Multi-source Resonance V2.0 - OpenAI Provider

封装 OpenAI GPT 系列模型 (gpt-4o, gpt-4-turbo, gpt-3.5-turbo 等)。
支持重试、超时、Rate Limit 处理。
"""

from typing import Optional
from llm_inference.base import LLMProvider, LLMResponse
from utils.logger import getLogger

logger = getLogger('llm.openai')


class OpenAIProvider(LLMProvider):
    """OpenAI GPT 系列适配器

    使用 openai 库的异步接口，支持流式响应关闭（批处理场景）。

    Usage:
        provider = OpenAIProvider(
            api_key="sk-...",
            model="gpt-4o",
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
        model: str = "gpt-4o",
        temperature: float = 0.3,
        max_tokens: int = 2000,
        timeout: int = 60,
        organization: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        super().__init__(
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        self.organization = organization
        self.base_url = base_url
        self._client = None

    @property
    def provider_name(self) -> str:
        return "openai"

    def _get_client(self):
        """懒加载 OpenAI 客户端"""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
                client_kwargs = {'api_key': self.api_key, 'timeout': self.timeout}
                if self.organization:
                    client_kwargs['organization'] = self.organization
                if self.base_url:
                    client_kwargs['base_url'] = self.base_url
                self._client = AsyncOpenAI(**client_kwargs)
                logger.info(f"OpenAI 客户端初始化完成: model={self.model}")
            except ImportError:
                raise ImportError(
                    "openai 库未安装。请执行: pip install openai>=1.30.0"
                )
            except Exception as e:
                logger.error(f"OpenAI 客户端初始化失败: {e}")
                raise
        return self._client

    async def _generate_impl(
        self,
        prompt: str,
        system_prompt: str = "",
    ) -> LLMResponse:
        """OpenAI Chat Completions API 调用"""
        client = self._get_client()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        logger.info(
            f"OpenAI 请求: model={self.model}, "
            f"system_prompt_len={len(system_prompt)}, prompt_len={len(prompt)}"
        )

        response = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            top_p=0.95,
            frequency_penalty=0.0,
            presence_penalty=0.0,
        )

        choice = response.choices[0]
        usage = {
            'prompt_tokens': response.usage.prompt_tokens if response.usage else 0,
            'completion_tokens': response.usage.completion_tokens if response.usage else 0,
            'total_tokens': response.usage.total_tokens if response.usage else 0,
        }

        logger.info(
            f"OpenAI 响应: tokens={usage['total_tokens']}, "
            f"finish={choice.finish_reason}"
        )

        return LLMResponse(
            content=choice.message.content or "",
            model=self.model,
            usage=usage,
            finish_reason=choice.finish_reason or "stop",
        )
