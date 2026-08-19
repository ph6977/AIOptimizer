"""评估运行器：llm-as-judge 对比压缩前后质量"""
import asyncio
import json
import statistics
from datetime import datetime
from pathlib import Path

import httpx

from app.core.config import settings
from app.eval.dataset import EvalCase, get_all_cases

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
    def __init__(self, judge_model: str = "deepseek-chat", gateway_url: str | None = None):
        self.judge_model = judge_model
        self.gateway_url = gateway_url or f"http://{settings.gateway_host}:{settings.gateway_port}"
        self.client = httpx.AsyncClient(timeout=60.0)

    async def get_response(self, messages: list[dict], use_compression: bool) -> str:
        """通过网关获取回答"""
        payload = {
            "model": "auto" if use_compression else messages[-1].get("model", "auto"),
            "messages": messages,
            "temperature": 0.3,
            "stream": False,
        }
        if not use_compression:
            payload["model"] = "deepseek-chat"  # 固定基准模型

        resp = await self.client.post(f"{self.gateway_url}/v1/chat/completions", json=payload)
        if resp.status_code != 200:
            return f"ERROR: {resp.text}"
        data = resp.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")

    async def judge(self, question: str, answer_a: str, answer_b: str) -> dict:
        """LLM-as-judge 评分"""
        prompt = JUDGE_PROMPT.format(question=question, answer_a=answer_a, answer_b=answer_b)
        payload = {
            "model": self.judge_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "stream": False,
        }
        resp = await self.client.post(f"{self.gateway_url}/v1/chat/completions", json=payload)
        if resp.status_code != 200:
            return {"error": resp.text}
        try:
            content = resp.json()["choices"][0]["message"]["content"]
            # 提取 JSON
            start = content.find("{")
            end = content.rfind("}") + 1
            return json.loads(content[start:end])
        except Exception as e:
            return {"error": f"Parse failed: {e}", "raw": content}

    async def evaluate_case(self, case: EvalCase) -> dict:
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
            return {"case_id": case.id, "error": "Gateway error", "answer_a": answer_a, "answer_b": answer_b}

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

    async def run(self, cases: list[EvalCase] | None = None) -> dict:
        cases = cases or get_all_cases()
        results = []

        for case in cases:
            result = await self.evaluate_case(case)
            results.append(result)
            await asyncio.sleep(0.5)  # 限流

        await self.client.aclose()
        return self._aggregate(results)

    def _aggregate(self, results: list[dict]) -> dict:
        valid = [r for r in results if "error" not in r]
        if not valid:
            return {"error": "No valid results"}

        scores_a = [r["score_a"] for r in valid if r.get("score_a")]
        scores_b = [r["score_b"] for r in valid if r.get("score_b")]

        winners = {"A": 0, "B": 0, "tie": 0}
        for r in valid:
            w = r.get("winner", "tie")
            winners[w] = winners.get(w, 0) + 1

        by_type = {}
        for r in valid:
            t = r["task_type"]
            if t not in by_type:
                by_type[t] = {"scores_a": [], "scores_b": [], "winners": {"A": 0, "B": 0, "tie": 0}}
            if r.get("score_a"):
                by_type[t]["scores_a"].append(r["score_a"])
            if r.get("score_b"):
                by_type[t]["scores_b"].append(r["score_b"])
            w = r.get("winner", "tie")
            by_type[t]["winners"][w] = by_type[t]["winners"].get(w, 0) + 1

        return {
            "timestamp": datetime.now().isoformat(),
            "total_cases": len(results),
            "valid_cases": len(valid),
            "avg_score_a": statistics.mean(scores_a) if scores_a else 0,
            "avg_score_b": statistics.mean(scores_b) if scores_b else 0,
            "score_diff": (statistics.mean(scores_b) - statistics.mean(scores_a)) if scores_a and scores_b else 0,
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


async def main():
    print("Starting evaluation...")
    evaluator = Evaluator()
    report = await evaluator.run()

    # 保存报告
    out_dir = Path("eval_reports")
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 打印摘要
    print("\n=== Evaluation Summary ===")
    print(f"Total cases: {report['total_cases']}")
    print(f"Valid: {report['valid_cases']}")
    print(f"Avg score (no compression): {report['avg_score_a']:.2f}")
    print(f"Avg score (with compression): {report['avg_score_b']:.2f}")
    print(f"Score diff (B-A): {report['score_diff']:.2f}")
    print(f"Winners: A={report['winners']['A']}, B={report['winners']['B']}, Tie={report['winners']['tie']}")
    print(f"\nReport saved to: {out_file}")

    # 生成 Markdown 摘要
    md_file = out_dir / f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(f"# 评估报告 {report['timestamp']}\n\n")
        f.write(f"- 总用例: {report['total_cases']}\n")
        f.write(f"- 有效用例: {report['valid_cases']}\n")
        f.write(f"- 平均分 (无压缩): {report['avg_score_a']:.2f}\n")
        f.write(f"- 平均分 (有压缩): {report['avg_score_b']:.2f}\n")
        f.write(f"- 分数差 (B-A): {report['score_diff']:.2f}\n")
        f.write(f"- 胜负: A胜 {report['winners']['A']}, B胜 {report['winners']['B']}, 平局 {report['winners']['tie']}\n\n")
        f.write("## 分类别详情\n\n")
        f.writelines(f"- {t}: 无压缩 {v['avg_a']:.2f}, 有压缩 {v['avg_b']:.2f}, A胜 {v['winners']['A']}, B胜 {v['winners']['B']}, 平 {v['winners']['tie']}\n" for t, v in report["by_type"].items())
    print(f"Markdown saved to: {md_file}")


if __name__ == "__main__":
    asyncio.run(main())