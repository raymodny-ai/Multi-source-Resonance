"""
Multi-source Resonance V2.0 - LLM Provider 抽象基类

定义统一的 LLM 调用接口，所有 Provider（OpenAI, Anthropic 等）需实现此接口。
V2.0 增强: 指数退避 + 随机 Jitter + 并发控制 (PRD §容错与降级机制)
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
import asyncio
import random
import time

logger = None  # 延迟绑定以避免循环导入

def _get_logger():
    global logger
    if logger is None:
        from utils.logger import getLogger
        logger = getLogger('llm.provider')
    return logger


@dataclass
class LLMResponse:
    """LLM 响应封装

    Attributes:
        content: LLM 返回的文本内容
        model: 使用的模型名称
        usage: Token 使用统计 {'prompt_tokens': int, 'completion_tokens': int, 'total_tokens': int}
        finish_reason: 完成原因 (stop / length / content_filter)
        latency_ms: 请求延迟 (毫秒)
        raw_response: 原始响应对象 (调试用)
    """
    content: str
    model: str = ""
    usage: Dict[str, int] = field(default_factory=dict)
    finish_reason: str = "stop"
    latency_ms: int = 0
    raw_response: Any = None

    @property
    def total_tokens(self) -> int:
        return self.usage.get('total_tokens', 0)

    @property
    def prompt_tokens(self) -> int:
        return self.usage.get('prompt_tokens', 0)

    @property
    def completion_tokens(self) -> int:
        return self.usage.get('completion_tokens', 0)

    def is_truncated(self) -> bool:
        """检查是否因 token 限制被截断"""
        return self.finish_reason == 'length'


class LLMProvider(ABC):
    """LLM Provider 抽象基类

    所有 LLM 服务适配器必须实现此接口。

    V2.0 增强:
    - 指数退避 + 随机 Jitter: 避免重试风暴 (retry storm)
    - 并发控制: 全局 Semaphore 限制并发 API 调用数
    - 速率限制 (Rate Limit) 感知: 429 响应自动等待 Retry-After

    子类需要实现:
    - _generate_impl(): 实际的 API 调用逻辑
    - model_name 属性: 返回模型名称
    """

    # 全局并发控制 (类级别 Semaphore)
    _global_semaphore: Optional[asyncio.Semaphore] = None
    _max_concurrent_requests: int = 3  # 默认最大并发数

    @classmethod
    def set_global_concurrency(cls, max_concurrent: int) -> None:
        """设置全局并发上限"""
        cls._max_concurrent_requests = max_concurrent
        cls._global_semaphore = asyncio.Semaphore(max_concurrent)

    @classmethod
    def _get_semaphore(cls) -> asyncio.Semaphore:
        """获取全局并发信号量 (延迟初始化)"""
        if cls._global_semaphore is None:
            cls._global_semaphore = asyncio.Semaphore(cls._max_concurrent_requests)
        return cls._global_semaphore

    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float = 0.3,
        max_tokens: int = 2000,
        timeout: int = 60,
        max_retries: int = 3,
        base_delay: float = 2.0,
        max_delay: float = 30.0,
    ):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_delay = base_delay  # 基础延迟 (秒)
        self.max_delay = max_delay  # 最大延迟上限 (秒)

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """返回 Provider 名称 (如 'openai', 'anthropic')"""
        ...

    @abstractmethod
    async def _generate_impl(
        self,
        prompt: str,
        system_prompt: str,
    ) -> LLMResponse:
        """实际 LLM API 调用实现

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词

        Returns:
            LLMResponse: 封装后的 LLM 响应
        """
        ...

    def _compute_backoff(self, attempt: int) -> float:
        """计算指数退避 + 随机 Jitter 的等待时间 (V2.0)

        公式: min(base_delay * 2^(attempt-1) + random(0, 1), max_delay)

        Args:
            attempt: 当前重试次数 (1-based)

        Returns:
            等待秒数 (float)
        """
        exponential = self.base_delay * (2 ** (attempt - 1))
        jitter = random.uniform(0, 1)  # 0~1秒随机抖动
        return min(exponential + jitter, self.max_delay)

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
    ) -> LLMResponse:
        """统一的 LLM 调用入口 (V2.0 增强版)

        包含指数退避 + Jitter 重试、并发控制、和超时处理。

        Args:
            prompt: 用户提示词 (注入 Layer 2 JSON)
            system_prompt: 系统提示词 (Persona + 行为准则)

        Returns:
            LLMResponse: 封装后的 LLM 响应

        Raises:
            RuntimeError: 所有重试耗尽后抛出
        """
        lg = _get_logger()
        last_error = None

        # 并发控制: 获取信号量 (确保不超出全局并发限制)
        semaphore = self._get_semaphore()
        async with semaphore:
            for attempt in range(1, self.max_retries + 1):
                try:
                    start_time = time.time()
                    response = await asyncio.wait_for(
                        self._generate_impl(prompt, system_prompt),
                        timeout=self.timeout,
                    )
                    response.latency_ms = int((time.time() - start_time) * 1000)
                    if attempt > 1:
                        lg.info(
                            f"{self.provider_name} 重试成功 (attempt {attempt}/{self.max_retries})"
                        )
                    return response

                except asyncio.TimeoutError:
                    last_error = TimeoutError(
                        f"{self.provider_name} 请求超时 (attempt {attempt}/{self.max_retries})"
                    )
                    if attempt < self.max_retries:
                        wait_sec = self._compute_backoff(attempt)
                        lg.warning(f"超时，{wait_sec:.1f}s 后重试...")
                        await asyncio.sleep(wait_sec)

                except Exception as e:
                    last_error = e
                    error_str = str(e).lower()
                    if attempt < self.max_retries:
                        # 速率限制特殊处理: 使用 Retry-After 或默认退避
                        if '429' in error_str or 'rate limit' in error_str:
                            wait_sec = self.max_delay  # 速率限制使用最大延迟
                            lg.warning(f"速率限制 (429)，{wait_sec:.1f}s 后重试...")
                        else:
                            wait_sec = self._compute_backoff(attempt)
                            lg.warning(
                                f"{self.provider_name} 错误: {type(e).__name__}，"
                                f"{wait_sec:.1f}s 后重试..."
                            )
                        await asyncio.sleep(wait_sec)

        raise RuntimeError(
            f"{self.provider_name} 调用失败 (重试{self.max_retries}次): {last_error}"
        )

    def is_available(self) -> bool:
        """检查 Provider 是否可用 (API Key 已配置)"""
        return bool(self.api_key and len(self.api_key) > 10)
