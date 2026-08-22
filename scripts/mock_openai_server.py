"""Mock OpenAI 兼容服务器：用于评估测试，返回确定性响应"""

import asyncio
import json

from aiohttp import web

MOCK_MODELS = {
    "object": "list",
    "data": [
        {"id": "mock-model", "object": "model", "owned_by": "mock"},
        {"id": "mock-model-vision", "object": "model", "owned_by": "mock"},
    ],
}

# 预设回复映射：根据关键词返回不同内容
MOCK_RESPONSES = {
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


def pick_response(user_content: str) -> str:
    for kw, resp in MOCK_RESPONSES.items():
        if kw in user_content:
            return resp
    return "这是一个模拟回复。收到：" + user_content[:100]


async def handle_models(request):
    return web.json_response(MOCK_MODELS)


async def handle_chat_completions(request):
    data = await request.json()
    messages = data.get("messages", [])
    stream = data.get("stream", False)
    model = data.get("model", "mock-model")

    # 提取最后一条用户消息
    user_content = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            user_content = m.get("content", "")
            break

    response_text = pick_response(user_content)

    if stream:
        # 模拟流式：逐字符 yield
        async def stream_gen():
            for chunk in [
                response_text[i : i + 10] for i in range(0, len(response_text), 10)
            ]:
                yield f"data: {json.dumps({'choices': [{'delta': {'content': chunk}, 'index': 0}]} )}\n\n"
                await asyncio.sleep(0.01)
            yield "data: [DONE]\n\n"

        return web.Response(
            body=stream_gen(),
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )
    else:
        resp = {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": response_text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": sum(len(m.get("content", "")) for m in messages) // 2,
                "completion_tokens": len(response_text) // 2,
                "total_tokens": 0,
            },
        }
        resp["usage"]["total_tokens"] = (
            resp["usage"]["prompt_tokens"] + resp["usage"]["completion_tokens"]
        )
        return web.json_response(resp)


app = web.Application()
app.router.add_get("/v1/models", handle_models)
app.router.add_get("/models", handle_models)  # 适配器请求路径
app.router.add_post("/v1/chat/completions", handle_chat_completions)

if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=8001)
