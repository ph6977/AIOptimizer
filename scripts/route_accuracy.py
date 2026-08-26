"""路由准确率统计：router.detect_task_type vs 数据集标注"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.eval.dataset import EVAL_CASES
from app.optimizer.router import router
from app.providers import ChatMessage


def main() -> None:
    correct = 0
    misses: list[tuple[str, str, str]] = []

    for case in EVAL_CASES:
        messages = [
            ChatMessage(role=m["role"], content=m.get("content", ""))
            for m in case.messages
        ]
        predicted = router.detect_task_type(messages)
        expected = case.task_type
        status = "PASS" if predicted == expected else "FAIL"
        if predicted == expected:
            correct += 1
        else:
            misses.append((case.id, expected, predicted))
        print(f"  [{status}] {case.id:<14} expected={expected:<10} predicted={predicted}")

    total = len(EVAL_CASES)
    acc = correct / total
    print(f"\nAccuracy: {correct}/{total} = {acc:.0%} (target >= 80%)")
    if misses:
        print("Misses:")
        for case_id, exp, pred in misses:
            print(f"  {case_id}: {exp} -> {pred}")
    sys.exit(0 if acc >= 0.8 else 1)


if __name__ == "__main__":
    main()
