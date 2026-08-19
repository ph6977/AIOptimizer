"""智能模型路由"""

from dataclasses import dataclass
from typing import ClassVar, Literal

from app.core.config import ProviderConfig, settings
from app.providers import ChatCompletionRequest, ChatMessage, ModelInfo, ProviderFactory

TaskType = Literal["chat", "code", "reasoning", "vision", "creative", "analysis"]


@dataclass
class RoutingDecision:
    provider: str
    model: str
    reason: str
    confidence: float


class Router:
    """智能路由器：按任务类型、难度、成本/质量偏好选择模型"""

    # 任务类型关键词
    TASK_KEYWORDS: ClassVar[dict[str, list[str]]] = {
        "code": [
            "代码",
            "函数",
            "类",
            "编程",
            "实现",
            "重构",
            "调试",
            "bug",
            "语法",
            "算法",
            "数据结构",
        ],
        "reasoning": [
            "推理",
            "逻辑",
            "证明",
            "推导",
            "分析",
            "思考",
            "复杂",
            "难题",
            "数学",
            "物理",
        ],
        "vision": ["图片", "图像", "截图", "看图", "识别", "OCR", "视觉", "画面"],
        "creative": ["写作", "创作", "故事", "诗歌", "文案", "润色", "扩写", "改写"],
        "analysis": ["分析", "总结", "提取", "对比", "评估", "归纳", "报告", "数据"],
    }

    # 模型能力评分（0-1）
    MODEL_CAPABILITY: ClassVar[dict[str, dict[str, float]]] = {
        # OpenAI
        "gpt-4o": {
            "chat": 0.95,
            "code": 0.95,
            "reasoning": 0.95,
            "vision": 0.9,
            "creative": 0.9,
            "analysis": 0.9,
        },
        "gpt-4o-mini": {
            "chat": 0.85,
            "code": 0.85,
            "reasoning": 0.8,
            "vision": 0.8,
            "creative": 0.8,
            "analysis": 0.8,
        },
        "gpt-4-turbo": {
            "chat": 0.9,
            "code": 0.9,
            "reasoning": 0.9,
            "vision": 0.85,
            "creative": 0.85,
            "analysis": 0.85,
        },
        "gpt-3.5-turbo": {
            "chat": 0.75,
            "code": 0.7,
            "reasoning": 0.65,
            "vision": 0.0,
            "creative": 0.7,
            "analysis": 0.7,
        },
        # DeepSeek
        "deepseek-chat": {
            "chat": 0.9,
            "code": 0.9,
            "reasoning": 0.85,
            "vision": 0.0,
            "creative": 0.8,
            "analysis": 0.85,
        },
        "deepseek-reasoner": {
            "chat": 0.8,
            "code": 0.85,
            "reasoning": 0.95,
            "vision": 0.0,
            "creative": 0.7,
            "analysis": 0.9,
        },
        # GLM
        "glm-4": {
            "chat": 0.88,
            "code": 0.85,
            "reasoning": 0.8,
            "vision": 0.8,
            "creative": 0.8,
            "analysis": 0.8,
        },
        "glm-4v": {
            "chat": 0.85,
            "code": 0.8,
            "reasoning": 0.75,
            "vision": 0.9,
            "creative": 0.8,
            "analysis": 0.8,
        },
        # Qwen
        "qwen-max": {
            "chat": 0.85,
            "code": 0.8,
            "reasoning": 0.75,
            "vision": 0.8,
            "creative": 0.8,
            "analysis": 0.75,
        },
        "qwen-plus": {
            "chat": 0.8,
            "code": 0.75,
            "reasoning": 0.7,
            "vision": 0.0,
            "creative": 0.75,
            "analysis": 0.7,
        },
        "qwen-turbo": {
            "chat": 0.7,
            "code": 0.65,
            "reasoning": 0.6,
            "vision": 0.0,
            "creative": 0.65,
            "analysis": 0.6,
        },
        # Kimi
        "moonshot-v1-8k": {
            "chat": 0.7,
            "code": 0.6,
            "reasoning": 0.6,
            "vision": 0.0,
            "creative": 0.7,
            "analysis": 0.6,
        },
        "moonshot-v1-32k": {
            "chat": 0.75,
            "code": 0.65,
            "reasoning": 0.65,
            "vision": 0.0,
            "creative": 0.75,
            "analysis": 0.65,
        },
        "moonshot-v1-128k": {
            "chat": 0.8,
            "code": 0.7,
            "reasoning": 0.7,
            "vision": 0.0,
            "creative": 0.8,
            "analysis": 0.7,
        },
        # Anthropic
        "claude-3-5-sonnet-20241022": {
            "chat": 0.95,
            "code": 0.95,
            "reasoning": 0.95,
            "vision": 0.9,
            "creative": 0.9,
            "analysis": 0.9,
        },
        "claude-3-5-haiku-20241022": {
            "chat": 0.85,
            "code": 0.85,
            "reasoning": 0.8,
            "vision": 0.8,
            "creative": 0.8,
            "analysis": 0.8,
        },
        # Gemini
        "gemini-1.5-pro": {
            "chat": 0.9,
            "code": 0.9,
            "reasoning": 0.9,
            "vision": 0.9,
            "creative": 0.85,
            "analysis": 0.9,
        },
        "gemini-1.5-flash": {
            "chat": 0.8,
            "code": 0.8,
            "reasoning": 0.75,
            "vision": 0.8,
            "creative": 0.8,
            "analysis": 0.75,
        },
    }

    def __init__(self) -> None:
        self.factory = ProviderFactory

    def detect_task_type(self, messages: list[ChatMessage]) -> TaskType:
        """检测任务类型"""
        # 取最后一条用户消息
        last_user_msg = ""
        for m in reversed(messages):
            if getattr(m, "role", "") == "user":
                last_user_msg = getattr(m, "content", "")
                break

        if not last_user_msg:
            return "chat"

        content = last_user_msg.lower()
        scores = {task: 0 for task in self.TASK_KEYWORDS}
        for task, keywords in self.TASK_KEYWORDS.items():
            for kw in keywords:
                if kw in content:
                    scores[task] += 1

        # 返回得分最高的任务类型
        best_task = max(scores.items(), key=lambda x: x[1])[0]
        return best_task if scores[best_task] > 0 else "chat"  # type: ignore[return-value]

    def estimate_difficulty(self, messages: list[ChatMessage]) -> float:
        """估算任务难度 (0-1)"""
        total_len = sum(len(m.content) for m in messages)
        msg_count = len(messages)

        # 基于长度和轮数估算
        length_score = min(total_len / 10000, 1.0)
        complexity_score = min(msg_count / 20, 1.0)

        return (length_score + complexity_score) / 2

    def get_available_models(
        self, providers: list[ProviderConfig]
    ) -> list[tuple[str, str, ModelInfo]]:
        """获取所有可用的 (provider, model_id, ModelInfo)"""
        results = []
        for p in providers:
            if not p.enabled or not p.api_key:
                continue
            for model_id in p.models:
                # 从 ProviderFactory 获取 ModelInfo
                overrides = self.factory._get_model_overrides(p.name)
                model_info = overrides.get(model_id)
                if model_info:
                    results.append((p.name, model_id, model_info))
        return results

    def route(
        self, request: ChatCompletionRequest, providers: list[ProviderConfig]
    ) -> RoutingDecision:
        """路由决策"""
        if not settings.routing_enabled or not providers:
            # 回退：第一个可用 provider 的第一个模型
            for p in providers:
                if p.enabled and p.api_key and p.models:
                    return RoutingDecision(p.name, p.models[0], "回退选择", 0.5)
            raise ValueError("No available providers")

        # 检测任务类型
        task_type = self.detect_task_type(request.messages)
        difficulty = self.estimate_difficulty(request.messages)

        # 获取候选模型
        candidates = self.get_available_models(providers)
        if not candidates:
            raise ValueError("No models available")

        # 评分
        best_score = -1.0
        best_choice: tuple[str, str, ModelInfo, float] | None = None

        for provider_name, model_id, model_info in candidates:
            capability = self.MODEL_CAPABILITY.get(model_id, {})
            task_score = capability.get(task_type, 0.5)

            # 难度匹配：难任务需要高能力模型
            difficulty_match = 1 - abs(task_score - difficulty)

            # 成本因子
            cost = model_info.input_cost_per_1k + model_info.output_cost_per_1k
            cost_factor = 1 / (1 + cost * 100) if cost > 0 else 1.0

            # 综合评分
            quality_weight = settings.quality_vs_cost
            cost_weight = 1 - quality_weight

            score = (
                quality_weight * task_score * difficulty_match
                + cost_weight * cost_factor
            )

            # Provider 优先级加成
            provider_config = next(
                (p for p in providers if p.name == provider_name), None
            )
            if provider_config:
                score += (10 - provider_config.priority) * 0.01

            if score > best_score:
                best_score = score
                best_choice = (provider_name, model_id, model_info, score)

        if best_choice:
            provider_name, model_id, model_info, score = best_choice
            return RoutingDecision(
                provider=provider_name,
                model=model_id,
                reason=f"任务类型:{task_type}, 难度:{difficulty:.2f}, 评分:{score:.2f}",
                confidence=min(score, 1.0),
            )

        # 兜底
        provider_name_fallback: str
        model_id_fallback: str
        provider_name_fallback, model_id_fallback, _ = candidates[0]
        return RoutingDecision(
            provider_name_fallback, model_id_fallback, "兜底选择", 0.3
        )


router = Router()
