"""实时质量评估模块：每次请求后异步评估质量分"""

from typing import Any


async def evaluate_quality(
    question: str,
    answer: str,
    request_id: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    """
    评估单个回答的质量

    参数:
        question: 用户问题
        answer: AI 回答
        request_id: 请求 ID
        session_id: 会话 ID

    返回:
        包含 score (1-5) 和 reason 的字典
    """
    # 简化评估：基于启发式规则
    score = _heuristic_score(question, answer)
    reason = _generate_reason(question, answer, score)

    return {
        "score": score,
        "reason": reason,
        "request_id": request_id,
        "session_id": session_id,
    }


async def evaluate_quality_pair(
    question: str,
    answer_original: str,
    answer_compressed: str,
    request_id: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    """
    评估一对回答的质量对比（用于压缩前后对比）

    参数:
        question: 用户问题
        answer_original: 无压缩回答
        answer_compressed: 有压缩回答
        request_id: 请求 ID
        session_id: 会话 ID

    返回:
        包含 score_original, score_compressed, winner, reason 的字典
    """
    score_original = _heuristic_score(question, answer_original)
    score_compressed = _heuristic_score(question, answer_compressed)

    if score_original > score_compressed:
        winner = "A"
    elif score_compressed > score_original:
        winner = "B"
    else:
        winner = "tie"

    reason = f"原始回答得分 {score_original}，压缩后得分 {score_compressed}"

    return {
        "score_original": score_original,
        "score_compressed": score_compressed,
        "winner": winner,
        "reason": reason,
        "request_id": request_id,
        "session_id": session_id,
    }


def _heuristic_score(question: str, answer: str) -> int:
    """基于启发式规则计算质量分 (1-5)"""
    if not answer:
        return 1

    score = 3  # 基础分

    # 长度评分
    if len(answer) > 200:
        score += 1
    if len(answer) > 500:
        score += 1

    # 关键词覆盖
    keywords = ["代码", "函数", "实现", "步骤", "分析", "总结", "原理", "示例"]
    keyword_count = sum(1 for kw in keywords if kw in answer)
    if keyword_count >= 3:
        score += 1

    # 结构化评分
    if any(marker in answer for marker in ["1.", "2.", "步骤", "首先", "其次"]):
        score += 1

    # 限制在 1-5 范围内
    return max(1, min(5, score))


def _generate_reason(question: str, answer: str, score: int) -> str:
    """生成评估理由"""
    reasons = []

    if len(answer) < 50:
        reasons.append("回答过短")
    elif len(answer) > 500:
        reasons.append("回答详细")

    if any(kw in answer for kw in ["代码", "```", "function"]):
        reasons.append("包含代码示例")

    if any(marker in answer for marker in ["1.", "2.", "步骤"]):
        reasons.append("结构清晰")

    if not reasons:
        reasons.append("一般质量")

    return "；".join(reasons)
