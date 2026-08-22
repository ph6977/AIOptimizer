"""进程内 Mock 评估运行器"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mock_provider import register_mock_provider

register_mock_provider()

import asyncio

from app.eval.run_eval import Evaluator


async def run():
    evaluator = Evaluator(use_mock=True)
    report = await evaluator.run()
    print("=== Evaluation Summary ===")
    print(f"Total cases: {report['total_cases']}")
    print(f"Valid: {report['valid_cases']}")
    print(f"Avg score (no compression): {report['avg_score_a']:.2f}")
    print(f"Avg score (with compression): {report['avg_score_b']:.2f}")
    print(f"Score diff (B-A): {report['score_diff']:.2f}")
    print(
        f"Winners: A={report['winners']['A']}, B={report['winners']['B']}, Tie={report['winners']['tie']}"
    )
    print("Report saved to: eval_reports/")


if __name__ == "__main__":
    asyncio.run(run())
