"""Provider 适配器基类"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, ClassVar

import httpx

from app.core.config import ProviderConfig


@dataclass
class ModelInfo:
    id: str
    display_name: str
    context_window: int
    input_cost_per_1k: float = 0.0
    output_cost_per_1k: float = 0.0
    capabilities: list[str] = field(default_factory=lambda: ["chat"])


@dataclass
class ChatMessage:
    role: str
    content: str
    name: str | None = None


@dataclass
class ChatCompletionRequest:
    model: str
    messages: list[ChatMessage]
    temperature: float = 0.7
    max_tokens: int | None = None
    stream: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatCompletionResponse:
    id: str
    model: str
    choices: list[dict[str, Any]]
    usage: dict[str, Any] | None = None
    created: int = 0


class ProviderAdapter(ABC):
    """Provider 适配器抽象基类"""

    def __init__(self, api_key: str, base_url: str = "", **kwargs: Any) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.client: httpx.AsyncClient | None = None
        self._models_cache: list[ModelInfo] | None = None

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider 标识名"""

    @property
    @abstractmethod
    def default_base_url(self) -> str:
        """默认基础 URL"""

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """获取可用模型列表"""

    @abstractmethod
    async def chat_completion(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        """非流式聊天完成"""

    @abstractmethod
    async def chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[str]:
        """流式聊天完成，逐行 yield SSE 格式数据"""
        if False:
            yield ""

    def _get_client(self) -> httpx.AsyncClient:
        if self.client is None or self.client.is_closed:
            headers = self._get_headers()
            self.client = httpx.AsyncClient(
                base_url=self.base_url or self.default_base_url,
                headers=headers,
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
        return self.client

    @abstractmethod
    def _get_headers(self) -> dict[str, str]:
        """获取请求头"""

    async def close(self) -> None:
        if self.client and not self.client.is_closed:
            await self.client.aclose()

    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """估算成本（美元）"""
        models = self._models_cache or []
        for m in models:
            if m.id == model:
                return (input_tokens / 1000) * m.input_cost_per_1k + (
                    output_tokens / 1000
                ) * m.output_cost_per_1k
        return 0.0


class OpenAICompatibleAdapter(ProviderAdapter):
    """OpenAI 兼容协议适配器（OpenAI/DeepSeek/GLM/Qwen/Kimi/Ollama 等）"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "",
        provider_name: str = "openai_compat",
        model_overrides: dict[str, ModelInfo] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(api_key, base_url, **kwargs)
        self._provider_name = provider_name
        self._model_overrides = model_overrides or {}

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def default_base_url(self) -> str:
        return "https://api.openai.com/v1"

    def _get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def list_models(self) -> list[ModelInfo]:
        if self._models_cache is not None:
            return self._models_cache

        client = self._get_client()
        try:
            resp = await client.get("/models")
            resp.raise_for_status()
            data = resp.json()
            models = []
            for m in data.get("data", []):
                model_id = m.get("id", "")
                override_obj = self._model_overrides.get(model_id)
                if override_obj:
                    models.append(
                        ModelInfo(
                            id=model_id,
                            display_name=override_obj.display_name,
                            context_window=override_obj.context_window,
                            input_cost_per_1k=override_obj.input_cost_per_1k,
                            output_cost_per_1k=override_obj.output_cost_per_1k,
                            capabilities=override_obj.capabilities,
                        )
                    )
                else:
                    models.append(
                        ModelInfo(
                            id=model_id,
                            display_name=model_id,
                            context_window=4096,
                            input_cost_per_1k=0.0,
                            output_cost_per_1k=0.0,
                            capabilities=["chat"],
                        )
                    )
            self._models_cache = models
            return models
        except (httpx.HTTPStatusError, httpx.RequestError):
            # 回退：返回配置的模型
            return list(self._model_overrides.values())

    async def chat_completion(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        client = self._get_client()
        payload = request.__dict__.copy()
        payload["messages"] = [
            {
                "role": m.role,
                "content": m.content,
                **({"name": m.name} if m.name else {}),
            }
            for m in request.messages
        ]
        resp = await client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return ChatCompletionResponse(**data)

    async def chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[str]:
        client = self._get_client()
        payload = request.__dict__.copy()
        payload["messages"] = [
            {
                "role": m.role,
                "content": m.content,
                **({"name": m.name} if m.name else {}),
            }
            for m in request.messages
        ]
        payload["stream"] = True

        async with client.stream("POST", "/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.strip():
                    yield line + "\n\n"


class AnthropicAdapter(ProviderAdapter):
    """Anthropic Claude 适配器（转 OpenAI 兼容格式）"""

    def __init__(self, api_key: str, base_url: str = "", **kwargs: Any) -> None:
        super().__init__(api_key, base_url, **kwargs)

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def default_base_url(self) -> str:
        return "https://api.anthropic.com/v1"

    def _get_headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def _convert_messages(
        self, messages: list[ChatMessage]
    ) -> tuple[str, list[dict[str, Any]]]:
        """将 OpenAI 格式转为 Anthropic 格式，返回 system prompt 和 messages"""
        system = ""
        converted = []
        for m in messages:
            if m.role == "system":
                system += m.content + "\n"
            else:
                converted.append({"role": m.role, "content": m.content})
        return system.strip(), converted

    async def list_models(self) -> list[ModelInfo]:
        # Anthropic 没有 /models 端点，返回已知模型
        if self._models_cache is not None:
            return self._models_cache
        self._models_cache = [
            ModelInfo(
                "claude-3-5-sonnet-20241022",
                "Claude 3.5 Sonnet",
                200000,
                3.0,
                15.0,
                ["chat", "vision", "reasoning"],
            ),
            ModelInfo(
                "claude-3-5-haiku-20241022",
                "Claude 3.5 Haiku",
                200000,
                0.8,
                4.0,
                ["chat", "vision", "reasoning"],
            ),
            ModelInfo(
                "claude-3-opus-20240229",
                "Claude 3 Opus",
                200000,
                15.0,
                75.0,
                ["chat", "vision", "reasoning"],
            ),
        ]
        return self._models_cache

    async def chat_completion(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        client = self._get_client()
        system, messages = self._convert_messages(request.messages)

        payload = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens or 4096,
            "temperature": request.temperature,
        }
        if system:
            payload["system"] = system

        resp = await client.post("/messages", json=payload)
        resp.raise_for_status()
        data = resp.json()

        # 转回 OpenAI 格式
        return ChatCompletionResponse(
            id=data.get("id", ""),
            model=request.model,
            choices=[
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": data.get("content", [{}])[0].get("text", ""),
                    },
                    "finish_reason": data.get("stop_reason", "stop"),
                }
            ],
            usage={
                "prompt_tokens": data.get("usage", {}).get("input_tokens", 0),
                "completion_tokens": data.get("usage", {}).get("output_tokens", 0),
                "total_tokens": data.get("usage", {}).get("input_tokens", 0)
                + data.get("usage", {}).get("output_tokens", 0),
            },
        )

    async def chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[str]:
        client = self._get_client()
        system, messages = self._convert_messages(request.messages)

        payload = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens or 4096,
            "temperature": request.temperature,
            "stream": True,
        }
        if system:
            payload["system"] = system

        async with client.stream("POST", "/messages", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        yield "data: [DONE]\n\n"
                        break
                    # 这里简化处理：直接透传，实际需转换格式
                    yield f"data: {data_str}\n\n"


class GeminiAdapter(ProviderAdapter):
    """Google Gemini 适配器（转 OpenAI 兼容格式）"""

    def __init__(self, api_key: str, base_url: str = "", **kwargs: Any) -> None:
        super().__init__(api_key, base_url, **kwargs)

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def default_base_url(self) -> str:
        return "https://generativelanguage.googleapis.com/v1beta"

    def _get_headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def _convert_messages(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        """转为 Gemini 格式"""
        converted = []
        for m in messages:
            role = "user" if m.role == "user" else "model"
            converted.append({"role": role, "parts": [{"text": m.content}]})
        return converted

    async def list_models(self) -> list[ModelInfo]:
        if self._models_cache is not None:
            return self._models_cache
        self._models_cache = [
            ModelInfo(
                "gemini-1.5-pro",
                "Gemini 1.5 Pro",
                1000000,
                0.0,
                0.0,
                ["chat", "vision", "reasoning"],
            ),
            ModelInfo(
                "gemini-1.5-flash",
                "Gemini 1.5 Flash",
                1000000,
                0.0,
                0.0,
                ["chat", "vision", "reasoning"],
            ),
            ModelInfo("gemini-1.0-pro", "Gemini 1.0 Pro", 32768, 0.0, 0.0, ["chat"]),
        ]
        return self._models_cache

    async def chat_completion(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        client = self._get_client()
        messages = self._convert_messages(request.messages)

        payload = {
            "contents": messages,
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens or 4096,
            },
        }

        url = f"/models/{request.model}:generateContent?key={self.api_key}"
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        candidates = data.get("candidates", [])
        content = ""
        if candidates:
            content = (
                candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            )

        return ChatCompletionResponse(
            id=data.get("name", "").split("/")[-1] if "name" in data else "",
            model=request.model,
            choices=[
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            usage={
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },  # Gemini 不直接返回 token 数
        )

    async def chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[str]:
        # 简化：复用非流式
        resp = await self.chat_completion(request)
        # 模拟流式输出
        import json

        yield f"data: {json.dumps(resp.__dict__)}\n\n"
        yield "data: [DONE]\n\n"


class ProviderFactory:
    """Provider 工厂"""

    _adapters: ClassVar[dict[str, ProviderAdapter]] = {}

    @classmethod
    def create(cls, provider_config: "ProviderConfig") -> ProviderAdapter:
        key = f"{provider_config.name}:{provider_config.api_key[:8]}"
        if key in cls._adapters:
            return cls._adapters[key]

        adapter: ProviderAdapter
        if provider_config.name in (
            "openai",
            "deepseek",
            "glm",
            "qwen",
            "kimi",
            "ollama",
        ):
            # OpenAI 兼容协议
            model_overrides = cls._get_model_overrides(provider_config.name)
            adapter = OpenAICompatibleAdapter(
                api_key=provider_config.api_key,
                base_url=provider_config.base_url,
                provider_name=provider_config.name,
                model_overrides=model_overrides,
            )
        elif provider_config.name == "anthropic":
            adapter = AnthropicAdapter(
                api_key=provider_config.api_key,
                base_url=provider_config.base_url,
            )
        elif provider_config.name == "gemini":
            adapter = GeminiAdapter(
                api_key=provider_config.api_key,
                base_url=provider_config.base_url,
            )
        else:
            raise ValueError(f"Unknown provider: {provider_config.name}")

        cls._adapters[key] = adapter
        return adapter

    @classmethod
    def _get_model_overrides(cls, provider: str) -> dict[str, ModelInfo]:
        """各 Provider 的模型元数据"""
        overrides = {
            "openai": {
                "gpt-4o": ModelInfo(
                    "gpt-4o",
                    "GPT-4o",
                    128000,
                    5.0,
                    15.0,
                    ["chat", "vision", "function_calling"],
                ),
                "gpt-4o-mini": ModelInfo(
                    "gpt-4o-mini",
                    "GPT-4o Mini",
                    128000,
                    0.15,
                    0.6,
                    ["chat", "vision", "function_calling"],
                ),
                "gpt-4-turbo": ModelInfo(
                    "gpt-4-turbo",
                    "GPT-4 Turbo",
                    128000,
                    10.0,
                    30.0,
                    ["chat", "vision", "function_calling"],
                ),
                "gpt-3.5-turbo": ModelInfo(
                    "gpt-3.5-turbo",
                    "GPT-3.5 Turbo",
                    16384,
                    0.5,
                    1.5,
                    ["chat", "function_calling"],
                ),
            },
            "deepseek": {
                "deepseek-chat": ModelInfo(
                    "deepseek-chat",
                    "DeepSeek V3",
                    64000,
                    0.14,
                    0.28,
                    ["chat", "reasoning"],
                ),
                "deepseek-reasoner": ModelInfo(
                    "deepseek-reasoner",
                    "DeepSeek R1",
                    64000,
                    0.55,
                    2.19,
                    ["chat", "reasoning"],
                ),
            },
            "glm": {
                "glm-4": ModelInfo(
                    "glm-4",
                    "GLM-4",
                    128000,
                    0.1,
                    0.1,
                    ["chat", "vision", "function_calling"],
                ),
                "glm-4v": ModelInfo(
                    "glm-4v", "GLM-4V", 128000, 0.1, 0.1, ["chat", "vision"]
                ),
            },
            "qwen": {
                "qwen-max": ModelInfo(
                    "qwen-max",
                    "Qwen-Max",
                    32768,
                    0.04,
                    0.12,
                    ["chat", "vision", "function_calling"],
                ),
                "qwen-plus": ModelInfo(
                    "qwen-plus",
                    "Qwen-Plus",
                    32768,
                    0.008,
                    0.03,
                    ["chat", "function_calling"],
                ),
                "qwen-turbo": ModelInfo(
                    "qwen-turbo", "Qwen-Turbo", 8192, 0.004, 0.012, ["chat"]
                ),
            },
            "kimi": {
                "moonshot-v1-8k": ModelInfo(
                    "moonshot-v1-8k", "Kimi 8K", 8192, 0.012, 0.012, ["chat"]
                ),
                "moonshot-v1-32k": ModelInfo(
                    "moonshot-v1-32k", "Kimi 32K", 32768, 0.024, 0.024, ["chat"]
                ),
                "moonshot-v1-128k": ModelInfo(
                    "moonshot-v1-128k", "Kimi 128K", 131072, 0.06, 0.06, ["chat"]
                ),
            },
            "ollama": {
                "llama3.1": ModelInfo(
                    "llama3.1", "Llama 3.1", 128000, 0.0, 0.0, ["chat"]
                ),
                "qwen2.5": ModelInfo("qwen2.5", "Qwen 2.5", 32768, 0.0, 0.0, ["chat"]),
                "deepseek-r1": ModelInfo(
                    "deepseek-r1", "DeepSeek R1", 32768, 0.0, 0.0, ["chat", "reasoning"]
                ),
            },
        }
        return overrides.get(provider, {})

    @classmethod
    async def close_all(cls) -> None:
        for adapter in cls._adapters.values():
            await adapter.close()
        cls._adapters.clear()
