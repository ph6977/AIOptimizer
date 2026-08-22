"""评估运行器：llm-as-judge 对比压缩前后质量

支持两种模式：
1. HTTP 模式：通过网关（需配置真实 Provider Key）
2. 进程内 Mock 模式：直接调用 Mock ProviderAdapter（无需网关，用于 CI/快速验证）
"""

import asyncio
import json
import statistics
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import httpx

from app.core.config import settings
from app.eval.dataset import EvalCase, get_all_cases
from app.providers import ChatCompletionRequest, ChatMessage, ProviderFactory

JUDGE_PROMPT = """你是一个严格的 AI 回答质量评估员。请对比两个回答的质量，打分 1-5 分。

评估维度：
1. 准确性：事实是否正确，无幻觉
2. 完整性：是否覆盖了问题的关键点
3. 实用性：对用户是否有帮助，代码是否可运行
4. 清晰度：表达是否清晰、结构化

原始问题：
{question}

回答 A（无压缩/原始上下文）：
{answer_a}

回答 B（压缩后上下文）：
{answer_b}

请输出 JSON：
{{
  "score_a": 1-5,
  "score_b": 1-5,
  "winner": "A" 或 "B" 或 "tie",
  "reason": "简要说明判断理由"
}}"""


class Evaluator:
    def __init__(
        self,
        judge_model: str = "deepseek-chat",
        gateway_url: str | None = None,
        use_mock: bool = False,
    ) -> None:
        self.judge_model = judge_model
        self.gateway_url = (
            gateway_url or f"http://{settings.gateway_host}:{settings.gateway_port}"
        )
        self.use_mock = use_mock
        self.client = httpx.AsyncClient(timeout=60.0)

        # 进程内 Mock Provider（若启用）
        if self.use_mock:
            self._register_mock_provider()

    def _register_mock_provider(self) -> None:
        """注册进程内 Mock Provider"""
        from app.core.config import ProviderConfig, settings

        original_create = ProviderFactory.create

        def patched_create(cls: Any, provider_config: Any) -> Any:
            if provider_config.name == "mock":
                key = "mock:mock"
                if key not in cls._adapters:
                    cls._adapters[key] = self._create_mock_adapter()
                return cls._adapters[key]
            return original_create(provider_config)

        ProviderFactory.create = patched_create  # type: ignore[assignment]

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
        print("[Mock Mode] Mock Provider registered")

    def _create_mock_adapter(self) -> Any:
        """创建 Mock Adapter 实例"""
        from app.providers import (
            ChatCompletionRequest,
            ChatCompletionResponse,
            ModelInfo,
            ProviderAdapter,
        )

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

        class MockAdapter(ProviderAdapter):
            def __init__(self, **kwargs: Any) -> None:
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
                for kw, resp in MOCK_RESPONSES.items():
                    if kw in user_content:
                        return resp
                return "这是一个模拟回复。收到：" + user_content[:100]

            def _degrade_response(
                self, response_text: str, comp_stats: dict[str, Any]
            ) -> str:
                """模拟压缩导致的质量下降"""
                saved_ratio = comp_stats.get("saved_ratio", 0)
                if saved_ratio <= 0:
                    return response_text
                # 压缩越多，保留信息越少
                keep_ratio = 1 - saved_ratio * 0.6  # 最多丢 60% 信息
                keep_len = max(int(len(response_text) * keep_ratio), 50)
                degraded = response_text[:keep_len]
                # 添加降质标记
                if keep_len < len(response_text):
                    degraded += f" [压缩丢失 {saved_ratio:.0%} 信息]"
                return degraded

            async def chat_completion(
                self, request: ChatCompletionRequest
            ) -> ChatCompletionResponse:
                user_content = ""
                for m in reversed(request.messages):
                    if m.role == "user":
                        user_content = m.content
                        break
                response_text = self._pick_response(user_content)

                # 检测是否为压缩请求
                is_compressed = (
                    request.extra.get("compressed", False) if request.extra else False
                )
                comp_stats = (
                    request.extra.get("comp_stats", {}) if request.extra else {}
                )

                if is_compressed and comp_stats:
                    response_text = self._degrade_response(response_text, comp_stats)

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

            async def chat_completion_stream(
                self, request: ChatCompletionRequest
            ) -> AsyncIterator[str]:
                import asyncio
                import json as json_lib

                user_content = ""
                for m in reversed(request.messages):
                    if m.role == "user":
                        user_content = m.content
                        break
                response_text = self._pick_response(user_content)
                for i in range(0, len(response_text), 10):
                    chunk = response_text[i : i + 10]
                    yield f"data: {json_lib.dumps({'choices': [{'delta': {'content': chunk}, 'index': 0}]})}\n\n"
                    await asyncio.sleep(0.01)
                yield "data: [DONE]\n\n"

        return MockAdapter()

    async def get_response(
        self, messages: list[dict[str, Any]], use_compression: bool
    ) -> str:
        """获取回答：Mock 模式直接调用 Adapter，否则走 HTTP"""
        if self.use_mock:
            return await self._get_response_mock(messages, use_compression)

        # HTTP 模式（原逻辑）
        payload: dict[str, Any] = {
            "model": "auto" if use_compression else messages[-1].get("model", "auto"),
            "messages": messages,
            "temperature": 0.3,
            "stream": False,
        }
        if not use_compression:
            payload["model"] = "deepseek-chat"

        resp = await self.client.post(
            f"{self.gateway_url}/v1/chat/completions", json=payload
        )
        if resp.status_code != 200:
            return f"ERROR: {resp.text}"
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return str(content)

    async def _get_response_mock(
        self, messages: list[dict[str, Any]], use_compression: bool
    ) -> str:
        """进程内 Mock 调用：模拟压缩降质效果"""
        # 构造请求
        chat_messages = [
            ChatMessage(
                role=m["role"], content=m.get("content", ""), name=m.get("name")
            )
            for m in messages
        ]
        request = ChatCompletionRequest(
            model="mock-model",
            messages=chat_messages,
            temperature=0.3,
            stream=False,
        )

        if use_compression:
            from app.core.config import settings
            from app.optimizer.compressor import compressor
            from app.optimizer.prompt_enhancer import prompt_enhancer
            from app.optimizer.router import router

            # 压缩 - mock 模式强制极低 target + keep_recent=0 以强制触发压缩
            compressed_messages, comp_stats = await compressor.compress(
                chat_messages,
                target_tokens=10 if self.use_mock else settings.target_context_tokens,
                max_context_tokens=settings.max_context_tokens,
                keep_recent=0 if self.use_mock else None,
            )
            # 路由
            if settings.routing_enabled:
                if self.use_mock:
                    request.model = "mock-model"
                else:
                    providers = settings.get_providers()
                    routing_decision = router.route(request, providers)
                    request.model = routing_decision.model
            # 增强
            if settings.prompt_enhancement_enabled:
                compressed_messages = prompt_enhancer.enhance(compressed_messages)

            # 调用 adapter - mock 模式直接用 mock adapter，传入压缩标记
            if self.use_mock:
                adapter = self._create_mock_adapter()
            else:
                adapter = ProviderFactory.create(settings.get_providers()[0])
            req = ChatCompletionRequest(
                model=request.model,
                messages=compressed_messages,
                temperature=0.3,
                stream=False,
                extra={"compressed": True, "comp_stats": comp_stats},
            )
            resp = await adapter.chat_completion(req)
        else:
            # 无压缩：直接调用 adapter
            adapter = self._create_mock_adapter()
            resp = await adapter.chat_completion(request)

        content = (
            resp.choices[0].get("message", {}).get("content", "")
            if isinstance(resp.choices[0], dict)
            else resp.choices[0].message.content
        )
        return str(content)

    async def judge(
        self, question: str, answer_a: str, answer_b: str
    ) -> dict[str, Any]:
        prompt = JUDGE_PROMPT.format(
            question=question, answer_a=answer_a, answer_b=answer_b
        )

        if self.use_mock:
            # 改进的 Mock 评分：多维度启发式，允许 0 分
            def score_answer(ans: str, question: str) -> dict[str, Any]:
                # 长度得分 (0-2)
                length_score = min(len(ans) / 150, 2)
                # 关键词覆盖 (0-2)
                keywords = [
                    "代码",
                    "函数",
                    "实现",
                    "步骤",
                    "分析",
                    "总结",
                    "原理",
                    "示例",
                    "逻辑",
                    "原因",
                ]
                keyword_score = min(sum(1 for kw in keywords if kw in ans) * 0.3, 2)
                # 结构化得分 (0-1)
                structure_score = (
                    1
                    if any(
                        marker in ans
                        for marker in [
                            "1.",
                            "2.",
                            "步骤",
                            "首先",
                            "其次",
                            "最后",
                            "代码",
                            "```",
                        ]
                    )
                    else 0
                )
                # 相关性得分 (0-1)
                q_words = set(question.replace("?", "").replace("？", "").split())
                a_words = set(ans.replace("。", "").replace("，", "").split())
                relevance = min(len(q_words & a_words) * 0.2, 1)
                total = length_score + keyword_score + structure_score + relevance
                return {
                    "score": min(5, round(total)),  # 允许 0 分
                    "details": {
                        "length": length_score,
                        "keyword": keyword_score,
                        "structure": structure_score,
                        "relevance": relevance,
                    },
                }

            score_a_detail = score_answer(answer_a, question)
            score_b_detail = score_answer(answer_b, question)
            score_a = score_a_detail["score"]
            score_b = score_b_detail["score"]

            # 模拟压缩降质：如果 B 明显更短且包含"压缩丢失"标记，额外扣分
            if "[压缩丢失" in answer_b and len(answer_b) < len(answer_a) * 0.8:
                score_b = max(0, score_b - 1)

            winner = "A" if score_a > score_b else "B" if score_b > score_a else "tie"
            return {
                "score_a": score_a,
                "score_b": score_b,
                "winner": winner,
                "reason": f"Mock multi-dim scoring: A={score_a_detail}, B={score_b_detail}",
            }

        # HTTP 模式（需真实 Judge Key）
        prompt = JUDGE_PROMPT.format(
            question=question, answer_a=answer_a, answer_b=answer_b
        )
        payload = {
            "model": self.judge_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "stream": False,
        }
        resp = await self.client.post(
            f"{self.gateway_url}/v1/chat/completions", json=payload
        )
        if resp.status_code != 200:
            return {"error": resp.text}
        content = resp.json()["choices"][0]["message"]["content"]
        try:
            # 提取 JSON
            start = content.find("{")
            end = content.rfind("}") + 1
            return cast(dict[str, Any], json.loads(content[start:end]))
        except (json.JSONDecodeError, ValueError) as e:
            return {"error": f"Parse failed: {e}", "raw": content}

    async def evaluate_case(self, case: EvalCase) -> dict[str, Any]:
        """评估单个用例"""
        # 提取最后一条用户消息作为问题
        question = ""
        for m in reversed(case.messages):
            if m.get("role") == "user":
                question = m["content"]
                break

        print(f"  Evaluating {case.id} ({case.task_type})...")
        # 无压缩
        answer_a = await self.get_response(case.messages, use_compression=False)
        # 有压缩
        answer_b = await self.get_response(case.messages, use_compression=True)

        if answer_a.startswith("ERROR") or answer_b.startswith("ERROR"):
            return {
                "case_id": case.id,
                "error": "Gateway error",
                "answer_a": answer_a,
                "answer_b": answer_b,
            }

        judge_result = await self.judge(question, answer_a, answer_b)

        return {
            "case_id": case.id,
            "task_type": case.task_type,
            "score_a": judge_result.get("score_a"),
            "score_b": judge_result.get("score_b"),
            "winner": judge_result.get("winner"),
            "reason": judge_result.get("reason"),
            "answer_a_len": len(answer_a),
            "answer_b_len": len(answer_b),
        }

    async def run(self, cases: list[EvalCase] | None = None) -> dict[str, Any]:
        cases = cases or get_all_cases()
        results = []

        for case in cases:
            result = await self.evaluate_case(case)
            results.append(result)
            await asyncio.sleep(0.5)  # 限流

        await self.client.aclose()
        return self._aggregate(results)

    def _aggregate(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        valid = [r for r in results if "error" not in r]
        if not valid:
            return {"error": "No valid results"}

        scores_a: list[float] = []
        scores_b: list[float] = []
        for r in valid:
            if r.get("score_a") is not None:
                scores_a.append(float(r["score_a"]))
            if r.get("score_b") is not None:
                scores_b.append(float(r["score_b"]))

        winners: dict[str, int] = {"A": 0, "B": 0, "tie": 0}
        for r in valid:
            w = r.get("winner", "tie")
            winners[w] = winners.get(w, 0) + 1

        by_type: dict[str, dict[str, Any]] = {}
        for r in valid:
            t = r["task_type"]
            if t not in by_type:
                by_type[t] = {
                    "scores_a": [],
                    "scores_b": [],
                    "winners": {"A": 0, "B": 0, "tie": 0},
                }
            if r.get("score_a") is not None:
                by_type[t]["scores_a"].append(float(r["score_a"]))
            if r.get("score_b") is not None:
                by_type[t]["scores_b"].append(float(r["score_b"]))
            w = r.get("winner", "tie")
            by_type[t]["winners"][w] = by_type[t]["winners"].get(w, 0) + 1

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_cases": len(results),
            "valid_cases": len(valid),
            "avg_score_a": statistics.mean(scores_a) if scores_a else 0,
            "avg_score_b": statistics.mean(scores_b) if scores_b else 0,
            "score_diff": (
                (statistics.mean(scores_b) - statistics.mean(scores_a))
                if scores_a and scores_b
                else 0
            ),
            "winners": winners,
            "by_type": {
                t: {
                    "avg_a": statistics.mean(v["scores_a"]) if v["scores_a"] else 0,
                    "avg_b": statistics.mean(v["scores_b"]) if v["scores_b"] else 0,
                    "winners": v["winners"],
                }
                for t, v in by_type.items()
            },
            "details": results,
        }


async def main() -> None:
    print("Starting evaluation (mock mode)...")
    evaluator = Evaluator(use_mock=True)
    report = await evaluator.run()

    # 保存报告
    out_dir = Path("eval_reports")
    out_dir.mkdir(exist_ok=True)
    out_file = (
        out_dir / f"eval_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    )
    out_file.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 打印摘要
    print("\n=== Evaluation Summary ===")
    print(f"Total cases: {report['total_cases']}")
    print(f"Valid: {report['valid_cases']}")
    print(f"Avg score (no compression): {report['avg_score_a']:.2f}")
    print(f"Avg score (with compression): {report['avg_score_b']:.2f}")
    print(f"Score diff (B-A): {report['score_diff']:.2f}")
    print(
        f"Winners: A={report['winners']['A']}, B={report['winners']['B']}, Tie={report['winners']['tie']}"
    )
    print(f"\nReport saved to: {out_file}")

    # 生成 Markdown 摘要
    md_file = (
        out_dir / f"eval_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.md"
    )
    md_lines = [
        f"# 评估报告 {report['timestamp']}\n\n",
        f"- 总用例: {report['total_cases']}\n",
        f"- 有效用例: {report['valid_cases']}\n",
        f"- 平均分 (无压缩): {report['avg_score_a']:.2f}\n",
        f"- 平均分 (有压缩): {report['avg_score_b']:.2f}\n",
        f"- 分数差 (B-A): {report['score_diff']:.2f}\n",
        f"- 胜负: A胜 {report['winners']['A']}, B胜 {report['winners']['B']}, 平局 {report['winners']['tie']}\n\n",
        "## 分类别详情\n\n",
    ]
    md_lines.extend(
        f"- {t}: 无压缩 {v['avg_a']:.2f}, 有压缩 {v['avg_b']:.2f}, A胜 {v['winners']['A']}, B胜 {v['winners']['B']}, 平 {v['winners']['tie']}\n"
        for t, v in report["by_type"].items()
    )
    md_content = "".join(md_lines)
    md_file.write_text(md_content, encoding="utf-8")
    print(f"Markdown saved to: {md_file}")


if __name__ == "__main__":
    asyncio.run(main())
