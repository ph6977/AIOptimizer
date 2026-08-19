"""FastAPI 网关：OpenAI 兼容代理 + 优化管线"""
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.config import settings
from app.core.db import init_db, log_usage
from app.optimizer.compressor import compressor
from app.optimizer.prompt_enhancer import prompt_enhancer
from app.optimizer.router import RoutingDecision, router
from app.providers import ChatCompletionRequest, ChatMessage, ProviderFactory


@asynccontextmanager
async def lifespan(app: FastAPI):
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


def parse_chat_request(data: dict) -> ChatCompletionRequest:
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
        extra={k: v for k, v in data.items() if k not in ("model", "messages", "temperature", "max_tokens", "stream")},
    )


def build_provider_configs() -> list:
    """从设置构建 Provider 配置列表"""
    return settings.get_providers()


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/v1/models")
async def list_models():
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
                all_models.append({
                    "id": f"{p.name}/{m.id}",
                    "object": "model",
                    "owned_by": p.name,
                    "provider": p.name,
                    "display_name": m.display_name,
                    "context_window": m.context_window,
                })
        except Exception:
            continue
    return {"object": "list", "data": all_models}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """核心代理端点：压缩 → 路由 → 增强 → 转发"""
    time.time()
    request_id = str(uuid.uuid4())[:8]
    session_id = request.headers.get("x-session-id", "default")

    try:
        body = await request.json()
    except Exception:
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
        chat_request.messages = compressed_messages

    # 2. 智能路由
    routing_decision: RoutingDecision | None = None
    if settings.routing_enabled and not original_model:
        routing_decision = router.route(chat_request, providers)
        chat_request.model = routing_decision.model
        selected_provider_name = routing_decision.provider
    else:
        # 使用指定模型或第一个可用
        selected_provider_name = original_model.split("/")[0] if "/" in original_model else providers[0].name
        chat_request.model = original_model.split("/")[-1] if "/" in original_model else providers[0].models[0]

    # 找到选中的 Provider 配置
    provider_config = next((p for p in providers if p.name == selected_provider_name), None)
    if not provider_config or not provider_config.api_key:
        raise HTTPException(503, f"Provider {selected_provider_name} not available")

    # 3. 提示词增强
    if settings.prompt_enhancement_enabled:
        chat_request.messages = prompt_enhancer.enhance(chat_request.messages)

    # 创建适配器并转发
    adapter = ProviderFactory.create(provider_config)

    # 记录原始 token 数（用于计算节省量）
    original_tokens = sum(
        compressor.count_tokens(m.content) + compressor.count_tokens(m.role)
        for m in chat_request.messages
    ) if "original_tokens" not in compression_stats else compression_stats.get("original_tokens", 0)

    try:
        if chat_request.stream:
            # 流式响应
            async def stream_generator():
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
                    "X-Compression": "enabled" if compression_stats.get("enabled") else "disabled",
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

            # 添加优化元信息到响应
            response_dict = response.__dict__.copy()
            response_dict["optimization"] = {
                "compression": compression_stats,
                "routing": {
                    "provider": selected_provider_name,
                    "model": chat_request.model,
                    "reason": routing_decision.reason if routing_decision else "manual",
                } if routing_decision else None,
            }
            return JSONResponse(response_dict, headers={"X-Request-ID": request_id})

    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"Upstream error: {e.response.text}")
    except Exception as e:
        raise HTTPException(500, f"Gateway error: {e!s}")


@app.get("/v1/usage/stats")
async def usage_stats(days: int = 7):
    """用量统计 API（供 GUI 调用）"""
    from app.core.db import get_usage_stats
    return await get_usage_stats(days)


@app.get("/v1/config")
async def get_config():
    """获取当前配置（脱敏）"""
    providers = settings.get_providers()
    safe_providers = []
    for p in providers:
        safe_providers.append({
            "name": p.name,
            "display_name": p.display_name,
            "enabled": p.enabled,
            "models": p.models,
            "has_key": bool(p.api_key),
            "priority": p.priority,
        })
    return {
        "gateway": {"host": settings.gateway_host, "port": settings.gateway_port},
        "compression": {
            "enabled": settings.compression_enabled,
            "aggressiveness": settings.compression_aggressiveness,
            "max_context": settings.max_context_tokens,
            "target_context": settings.target_context_tokens,
        },
        "routing": {"enabled": settings.routing_enabled, "quality_vs_cost": settings.quality_vs_cost},
        "prompt_enhancement": {"enabled": settings.prompt_enhancement_enabled},
        "providers": safe_providers,
    }


@app.post("/v1/config")
async def update_config(config: dict):
    """更新配置（运行时生效，不持久化）"""
    for key, value in config.items():
        if hasattr(settings, key):
            setattr(settings, key, value)
    return {"status": "ok", "message": "Config updated (runtime only)"}