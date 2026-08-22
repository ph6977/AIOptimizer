"""进程内 Mock Provider：直接注册到 ProviderFactory，用于评估测试"""
from typing import Any, AsyncIterator, ClassVar

from app.providers import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    ModelInfo,
    ProviderAdapter,
    ProviderFactory,
)


class MockProviderAdapter(ProviderAdapter):
    """纯内存 Mock 适配器，返回预设响应"""

    # 预设回复映射
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

    def __init__(self, **kwargs):
        super().__init__(api_key="mock", base_url="", **kwargs)

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def default_base_url(self) -> str:
        return ""

    def _get_headers(self) -> dict[str, str]:
        return {}

    async def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo("mock-model", "Mock Model", 8192, 0.0, 0.0, ["chat"]),
            ModelInfo("mock-model-vision", "Mock Vision Model", 8192, 0.0, 0.0, ["chat", "vision"]),
        ]

    def _pick_response(self, user_content: str) -> str:
        for kw, resp in self.MOCK_RESPONSES.items():
            if kw in user_content:
                return resp
        return "这是一个模拟回复。收到：" + user_content[:100]

    async def chat_completion(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        # 提取最后一条用户消息
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
            choices=[{
                "index": 0,
                "message": {"role": "assistant", "content": response_text},
                "finish_reason": "stop",
            }],
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        )

    async def chat_completion_stream(self, request: ChatCompletionRequest) -> AsyncIterator[str]:
        import json
        import asyncio

        user_content = ""
        for m in reversed(request.messages):
            if m.role == "user":
                user_content = m.content
                break

        response_text = self._pick_response(user_content)

        # 模拟流式：分块 yield
        for i in range(0, len(response_text), 10):
            chunk = response_text[i:i+10]
            yield f"data: {json.dumps({'choices': [{'delta': {'content': chunk}, 'index': 0}]})}\n\n"
            await asyncio.sleep(0.01)
        yield "data: [DONE]\n\n"


def register_mock_provider():
    """将 Mock Provider 注册到工厂（运行时生效）"""
    from app.core.config import ProviderConfig, settings

    # 创建 mock provider 配置
    mock_config = ProviderConfig(
        name="mock",
        display_name="Mock Provider",
        api_key="mock",
        base_url="",
        models=["mock-model", "mock-model-vision"],
        enabled=True,
        priority=0,
    )

    # 直接替换工厂的创建逻辑：单例缓存 mock adapter
    original_create = ProviderFactory.create

    @classmethod
    def patched_create(cls, provider_config: ProviderConfig):  # type: ignore[misc]
        if provider_config.name == "mock":
            key = "mock:mock"
            if key not in cls._adapters:
                cls._adapters[key] = MockProviderAdapter()
            return cls._adapters[key]
        return original_create(provider_config)

    ProviderFactory.create = patched_create  # type: ignore[assignment]

    # 更新运行时配置
    settings.set_providers([mock_config])
    print("Mock Provider 注册完成")


if __name__ == "__main__":
    register_mock_provider()