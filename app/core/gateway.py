"""FastAPI 网关：OpenAI 兼容代理 + 优化管线"""

import asyncio
import json
import os
import traceback
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, ClassVar

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.config import ProviderConfig, settings
from app.core.db import (
    get_compression_details,
    get_quality_scores,
    get_sessions,
    init_db,
    log_compression_decisions,
    log_quality_score,
    log_usage,
    set_session_tags,
    toggle_bookmark,
)
from app.eval.quality import evaluate_quality_pair
from app.optimizer.compressor import compressor
from app.optimizer.prompt_enhancer import prompt_enhancer
from app.optimizer.router import RoutingDecision, router
from app.providers import ChatCompletionRequest, ChatMessage, ProviderFactory


class MockProviderAdapter:
    """进程内 Mock 适配器：用于测试评估"""

    MOCK_RESPONSES: ClassVar[dict[str, str]] = {
        "装饰器": "Python 装饰器是一个函数，它接收另一个函数作为参数并返回一个新函数。常用语法：@decorator。核心原理是高阶函数 + 闭包。典型用途：日志、计时、权限检查、缓存。",
        "RESTful": "RESTful API 是基于 HTTP 协议的架构风格：资源用名词表示（/users）、HTTP 动词表达操作（GET/POST/PUT/DELETE）、状态码表达结果（200/201/404/500）。核心原则：无状态、统一接口、资源导向。",
        "端口占用": "Linux 查看端口占用：`ss -tlnp` 或 `netstat -tlnp` 或 `lsof -i:PORT`。其中 ss 更现代、速度更快。输出包含进程 PID 和程序名，便于定位并 kill。",
        "单例": "Python 单例模式实现：重写 __new__ 方法，用类变量 _instance 存储实例，配合 threading.Lock 保证线程安全。也可用元类或模块级变量（天然单例）。",
        "LRU": "LRU 缓存 O(1) 实现：哈希表 + 双向链表。哈希表键为 key、值为链表节点；链表头部为最近使用、尾部为最久未用。get/put 操作移动节点到头部，满容量时删尾部。Python 标准库：functools.lru_cache。",
        "异步 HTTP": "aiohttp 异步客户端：ClientSession 复用连接池，async with session.get() 自动释放。重试可用 tenacity 或手写指数退避。超时用 aiohttp.ClientTimeout(total=..., connect=...)。",
        "斐波那契": "斐波那契数列：fib(0)=0, fib(1)=1, fib(n)=fib(n-1)+fib(n-2)。递归指数级 O(2^n)，记忆化/动态规划 O(n)，矩阵快速幂 O(log n)。",
        "逻辑传递": "若所有 A 是 B，所有 B 是 C，则所有 A 是 C。这是三段论的传递性，形式逻辑有效。前提真则结论必真。",
        "睡莲": "第 29 天。每天翻倍，第 30 天满，则第 29 天是一半。指数增长特性：倒数第二天覆盖一半。",
        "三个数": "三个数是 2, 3, 15。2+3+15=20，2*3*15=90。由因式分解 90=2*3*3*5，尝试组合得解。",
        "五言绝句": "代码满屏飞，屏幕照夜归。深夜敲键响，键盘伴我醉。",
        "产品经理": "产品经理：这需求很简单，上线前加个按钮。程序员：按钮在哪？产品经理：右上角。程序员：右上角有用户头像。产品经理：那就左下角。程序员：左下角是版权声明。产品经理：那你决定吧，反正下周上线。",
        "Python Go": "Python 并发：GIL 限制多线程 CPU 密集型，用 multiprocessing 或 asyncio 协程（适合 IO 密集）。Go 并发：goroutine 轻量级线程，channel 通信，原生并行，适合 CPU+IO 混合。内存：Go 更低、启动更快。",
        "复杂度": "foo(n) 是递归斐波那契，时间复杂度 O(2^n) 指数级，空间 O(n) 栈深度。重复计算导致指数爆炸。优化：记忆化 O(n)、迭代 O(n)、矩阵快速幂 O(log n)。",
    }

    def __init__(self) -> None:
        pass

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def default_base_url(self) -> str:
        return ""

    def _get_headers(self) -> dict[str, str]:
        return {}

    async def list_models(self) -> list[Any]:
        from app.providers import ModelInfo

        return [
            ModelInfo("mock-model", "Mock Model", 8192, 0.0, 0.0, ["chat"]),
            ModelInfo(
                "mock-model-vision",
                "Mock Vision Model",
                8192,
                0.0,
                0.0,
                ["chat", "vision"],
            ),
        ]

    def _pick_response(self, user_content: str) -> str:
        for kw, resp in self.MOCK_RESPONSES.items():
            if kw in user_content:
                return resp
        return "这是一个模拟回复。收到：" + user_content[:100]

    async def chat_completion(self, request: Any) -> Any:
        from app.providers import ChatCompletionResponse

        user_content = ""
        for m in reversed(request.messages):
            if m.role == "user":
                user_content = m.content
                break
        response_text = self._pick_response(user_content)
        prompt_tokens = sum(len(m.content) for m in request.messages) // 2
        completion_tokens = len(response_text) // 2
        return ChatCompletionResponse(
            id="chatcmpl-mock",
            model=request.model,
            choices=[
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": response_text},
                    "finish_reason": "stop",
                }
            ],
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        )

    async def chat_completion_stream(self, request: Any) -> Any:
        import asyncio
        import json

        user_content = ""
        for m in reversed(request.messages):
            if m.role == "user":
                user_content = m.content
                break
        response_text = self._pick_response(user_content)
        for i in range(0, len(response_text), 10):
            chunk = response_text[i : i + 10]
            yield f"data: {json.dumps({'choices': [{'delta': {'content': chunk}, 'index': 0}]})}\n\n"
            await asyncio.sleep(0.01)
        yield "data: [DONE]\n\n"


def _register_mock_provider() -> None:
    """注册 Mock Provider 到工厂（测试模式）"""
    if os.getenv("AIOPTIMIZER_TEST_MODE") != "1":
        return
    from app.core.config import ProviderConfig, settings
    from app.providers import ModelInfo, ProviderFactory

    original_create = ProviderFactory.create

    def patched_create(provider_config: Any) -> Any:
        if provider_config.name == "mock":
            key = "mock:mock"
            if key not in ProviderFactory._adapters:
                ProviderFactory._adapters[key] = MockProviderAdapter()  # type: ignore[assignment]
            return ProviderFactory._adapters[key]
        return original_create(provider_config)

    ProviderFactory.create = patched_create  # type: ignore[assignment]

    # 注册 Mock 模型元数据
    original_get_overrides = ProviderFactory._get_model_overrides

    def patched_get_overrides(provider: str) -> dict[str, ModelInfo]:
        if provider == "mock":
            return {
                "mock-model": ModelInfo(
                    id="mock-model",
                    display_name="Mock Model",
                    context_window=8192,
                    input_cost_per_1k=0.0,
                    output_cost_per_1k=0.0,
                ),
                "mock-model-vision": ModelInfo(
                    id="mock-model-vision",
                    display_name="Mock Vision Model",
                    context_window=8192,
                    input_cost_per_1k=0.0,
                    output_cost_per_1k=0.0,
                ),
            }
        return original_get_overrides(provider)

    ProviderFactory._get_model_overrides = patched_get_overrides  # type: ignore[assignment]

    mock_config = ProviderConfig(
        name="mock",
        display_name="Mock Provider",
        api_key="mock",
        base_url="",
        models=["mock-model", "mock-model-vision"],
        enabled=True,
        priority=0,
    )
    settings.set_providers([mock_config])
    print("[Test Mode] Mock Provider + model overrides registered")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    _register_mock_provider()
    await init_db()
    yield
    await ProviderFactory.close_all()


app = FastAPI(
    title="AIOptimizer Gateway",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def parse_chat_request(data: dict[str, Any]) -> ChatCompletionRequest:
    """解析请求为内部格式"""
    messages = [
        ChatMessage(role=m["role"], content=m.get("content", ""), name=m.get("name"))
        for m in data.get("messages", [])
    ]
    return ChatCompletionRequest(
        model=data.get("model", ""),
        messages=messages,
        temperature=data.get("temperature", 0.7),
        max_tokens=data.get("max_tokens"),
        stream=data.get("stream", False),
        extra={
            k: v
            for k, v in data.items()
            if k not in ("model", "messages", "temperature", "max_tokens", "stream")
        },
    )


def build_provider_configs() -> list[ProviderConfig]:
    """从设置构建 Provider 配置列表"""
    return settings.get_providers()


def _infer_provider(model: str, providers: list[ProviderConfig]) -> str:
    """从模型名推断所属 provider 名称"""
    model_lower = model.lower()
    # 按特征匹配
    keyword_map: dict[str, list[str]] = {
        "deepseek": ["deepseek"],
        "openai": ["gpt", "o1", "o3", "o4"],
        "glm": ["glm"],
        "qwen": ["qwen"],
        "kimi": ["moonshot", "kimi"],
        "ollama": ["llama", "mistral", "codellama", "phi", "gemma", "qwen2"],
        "anthropic": ["claude"],
        "gemini": ["gemini"],
    }
    for provider_name, keywords in keyword_map.items():
        if any(kw in model_lower for kw in keywords):
            # 确认该 provider 确实存在且有 key
            matched = next(
                (p for p in providers if p.name == provider_name and p.api_key), None
            )
            if matched:
                return provider_name
    # 回退到第一个有 key 的 provider
    for p in providers:
        if p.api_key:
            return p.name
    return providers[0].name if providers else "openai"


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


@app.get("/v1/models")
async def list_models() -> dict[str, Any]:
    """聚合所有 Provider 的模型列表"""
    providers = build_provider_configs()
    all_models = []
    for p in providers:
        if not p.enabled or not p.api_key:
            continue
        try:
            adapter = ProviderFactory.create(p)
            models = await adapter.list_models()
            for m in models:
                all_models.append(
                    {
                        "id": f"{p.name}/{m.id}",
                        "object": "model",
                        "owned_by": p.name,
                        "provider": p.name,
                        "display_name": m.display_name,
                        "context_window": m.context_window,
                    }
                )
        except httpx.HTTPError:
            continue
    return {"object": "list", "data": all_models}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    """核心代理端点：压缩 → 路由 → 增强 → 转发"""
    request_id = str(uuid.uuid4())[:8]
    session_id = request.headers.get("x-session-id", "default")

    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(400, "Invalid JSON")

    # 解析请求
    chat_request = parse_chat_request(body)
    original_model = chat_request.model

    # 获取可用 Provider
    providers = build_provider_configs()
    if not providers:
        raise HTTPException(503, "No providers configured")

    # 1. 上下文压缩
    compression_stats = {"enabled": False}
    if settings.compression_enabled and len(chat_request.messages) > 1:
        compressed_messages, compression_stats = await compressor.compress(
            chat_request.messages,
            target_tokens=settings.target_context_tokens,
            max_context_tokens=settings.max_context_tokens,
        )
        # 记录压缩决策到数据库
        if compression_stats.get("details"):
            await log_compression_decisions(
                request_id=request_id,
                session_id=session_id,
                decisions=compression_stats["details"],
            )
        chat_request.messages = compressed_messages

    # 2. 智能路由
    routing_decision: RoutingDecision | None = None
    if settings.routing_enabled and not original_model:
        routing_decision = router.route(chat_request, providers)
        chat_request.model = routing_decision.model
        selected_provider_name = routing_decision.provider
    else:
        # 使用指定模型或第一个可用
        if "/" in original_model:
            selected_provider_name = original_model.split("/")[0]
            chat_request.model = original_model.split("/")[-1]
        else:
            # 没有 provider/ 前缀，尝试从模型名推断 provider
            selected_provider_name = _infer_provider(original_model, providers)
            chat_request.model = original_model

    # 找到选中的 Provider 配置
    provider_config = next(
        (p for p in providers if p.name == selected_provider_name), None
    )
    if not provider_config or not provider_config.api_key:
        raise HTTPException(503, f"Provider {selected_provider_name} not available")

    # 3. 提示词增强
    if settings.prompt_enhancement_enabled:
        chat_request.messages = prompt_enhancer.enhance(chat_request.messages)

    # 创建适配器并转发
    adapter = ProviderFactory.create(provider_config)

    # 记录原始 token 数（用于计算节省量）
    original_tokens = (
        sum(
            compressor.count_tokens(m.content) + compressor.count_tokens(m.role)
            for m in chat_request.messages
        )
        if "original_tokens" not in compression_stats
        else compression_stats.get("original_tokens", 0)
    )

    try:
        if chat_request.stream:
            # 流式响应
            async def stream_generator() -> AsyncIterator[str]:
                total_response_tokens = 0
                async for chunk in adapter.chat_completion_stream(chat_request):
                    # 简单统计响应 token（粗略）
                    if "content" in chunk:
                        total_response_tokens += len(chunk) // 4
                    yield chunk

                # 记录用量
                await log_usage(
                    provider=provider_config.name,
                    model=chat_request.model,
                    request_tokens=original_tokens,
                    response_tokens=total_response_tokens,
                    compressed=compression_stats.get("enabled", False),
                    original_tokens=compression_stats.get("original_tokens", 0),
                    saved_tokens=compression_stats.get("saved_tokens", 0),
                    request_id=request_id,
                    session_id=session_id,
                )

            return StreamingResponse(
                stream_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Request-ID": request_id,
                    "X-Compression": (
                        "enabled" if compression_stats.get("enabled") else "disabled"
                    ),
                },
            )
        else:
            # 非流式响应
            response = await adapter.chat_completion(chat_request)

            # 记录用量
            usage = response.usage or {}
            await log_usage(
                provider=provider_config.name,
                model=chat_request.model,
                request_tokens=usage.get("prompt_tokens", original_tokens),
                response_tokens=usage.get("completion_tokens", 0),
                compressed=compression_stats.get("enabled", False),
                original_tokens=compression_stats.get("original_tokens", 0),
                saved_tokens=compression_stats.get("saved_tokens", 0),
                request_id=request_id,
                session_id=session_id,
            )

            # 异步评估质量（不阻塞响应）
            async def _eval_quality() -> None:
                try:
                    # 获取用户问题
                    question = ""
                    for m in reversed(chat_request.messages):
                        if m.role == "user":
                            question = m.content
                            break

                    # 获取回答内容
                    choice = response.choices[0] if response.choices else None
                    answer = ""
                    if choice:
                        if isinstance(choice, dict):
                            answer = choice.get("message", {}).get("content", "")
                        else:
                            answer = choice.message.content

                    if question and answer:
                        quality_result = await evaluate_quality_pair(
                            question=question,
                            answer_original=answer,
                            answer_compressed=answer,
                            request_id=request_id,
                            session_id=session_id,
                        )
                        await log_quality_score(
                            request_id=request_id,
                            session_id=session_id,
                            score_original=quality_result.get("score_original"),
                            score_compressed=quality_result.get("score_compressed"),
                            winner=quality_result.get("winner", "tie"),
                            reason=quality_result.get("reason", ""),
                        )
                except (ValueError, KeyError, TypeError) as e:
                    print(f"[Quality Eval ERROR] {e}")

            asyncio.create_task(_eval_quality())

            # 添加优化元信息到响应
            response_dict = response.__dict__.copy()
            response_dict["optimization"] = {
                "compression": compression_stats,
                "routing": (
                    {
                        "provider": selected_provider_name,
                        "model": chat_request.model,
                        "reason": (
                            routing_decision.reason if routing_decision else "manual"
                        ),
                    }
                    if routing_decision
                    else None
                ),
            }
            return JSONResponse(response_dict, headers={"X-Request-ID": request_id})

    except httpx.HTTPStatusError as e:
        raise HTTPException(
            e.response.status_code, f"Upstream error: {e.response.text}"
        ) from e
    except httpx.RequestError as e:
        raise HTTPException(502, f"Upstream unreachable: {e!s}") from e
    except Exception as e:
        # Log full traceback for debugging
        print(f"[Gateway ERROR] {traceback.format_exc()}")
        raise HTTPException(500, f"Gateway error: {e!s}") from e


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global exception handler to ensure proper JSON error responses"""
    print(f"[Global ERROR] {request.url} - {traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {exc!s}", "path": str(request.url)},
    )


@app.get("/v1/usage/stats")
async def usage_stats(days: int = 7) -> dict[str, Any]:
    """用量统计 API（供 GUI 调用）"""
    from app.core.db import get_usage_stats

    return await get_usage_stats(days)


@app.get("/v1/config")
async def get_config() -> dict[str, Any]:
    """获取当前配置（脱敏）"""
    providers = settings.get_providers()
    safe_providers = []
    for p in providers:
        safe_providers.append(
            {
                "name": p.name,
                "display_name": p.display_name,
                "enabled": p.enabled,
                "models": p.models,
                "has_key": bool(p.api_key),
                "priority": p.priority,
            }
        )
    return {
        "gateway": {"host": settings.gateway_host, "port": settings.gateway_port},
        "compression": {
            "enabled": settings.compression_enabled,
            "aggressiveness": settings.compression_aggressiveness,
            "max_context": settings.max_context_tokens,
            "target_context": settings.target_context_tokens,
        },
        "routing": {
            "enabled": settings.routing_enabled,
            "quality_vs_cost": settings.quality_vs_cost,
        },
        "prompt_enhancement": {"enabled": settings.prompt_enhancement_enabled},
        "providers": safe_providers,
    }


@app.post("/v1/config")
async def update_config(config: dict[str, Any]) -> dict[str, str]:
    """更新配置（运行时生效，不持久化）"""
    for key, value in config.items():
        if hasattr(settings, key):
            setattr(settings, key, value)
    return {"status": "ok", "message": "Config updated (runtime only)"}


@app.get("/v1/compression/details")
async def compression_details(
    request_id: str | None = None,
    session_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """查询压缩决策详情"""
    details = await get_compression_details(request_id, session_id, limit)
    return {"details": details, "total": len(details)}


@app.get("/v1/quality/scores")
async def quality_scores(
    request_id: str | None = None,
    session_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """查询质量评估记录"""
    scores = await get_quality_scores(request_id, session_id, limit)
    return {"scores": scores, "total": len(scores)}


@app.get("/v1/sessions")
async def sessions(
    days: int = 7,
    limit: int = 50,
) -> dict[str, Any]:
    """查询会话列表"""
    session_list = await get_sessions(days, limit)
    return {"sessions": session_list, "total": len(session_list)}


@app.post("/v1/sessions/{session_id}/bookmark")
async def bookmark_session(session_id: str) -> dict[str, Any]:
    """切换会话书签状态"""
    new_state = await toggle_bookmark(session_id)
    return {"session_id": session_id, "bookmarked": new_state}


@app.post("/v1/sessions/{session_id}/tags")
async def update_session_tags(request: Request, session_id: str) -> dict[str, Any]:
    """设置会话标签"""
    body = await request.json()
    tags = body.get("tags", "")
    await set_session_tags(session_id, tags)
    return {"session_id": session_id, "tags": tags}
