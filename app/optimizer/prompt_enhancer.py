"""提示词增强引擎"""

from app.optimizer.router import TaskType, router
from app.providers import ChatMessage

ENHANCED_SYSTEM_PROMPTS = {
    "chat": """你是一个有用、无害、诚实的 AI 助手。请用自然、专业的语言回答用户问题。""",
    "code": """你是一个资深软件工程师。请遵循以下原则：
1. 代码简洁、可读、可维护，遵循最佳实践
2. 优先使用标准库和成熟方案，避免过度设计
3. 必要时添加类型注解、文档字符串、错误处理
4. 不要编写不必要的代码（YAGNI 原则）
5. 如需假设，请明确说明假设条件""",
    "reasoning": """你是一个逻辑严密的推理助手。请：
1. 逐步展示推理过程，不要跳跃
2. 明确前提、假设、推论
3. 遇到不确定性时诚实说明
4. 使用结构化输出（步骤、结论、置信度）""",
    "vision": """你是一个视觉理解专家。请：
1. 详细描述图像关键信息
2. 区分观察到的事实与推测
3. 如涉及文字，请准确转录
4. 结构化输出：整体描述、关键细节、文字内容、异常/重点""",
    "creative": """你是一个创意写作助手。请：
1. 根据用户意图调整风格、语调、节奏
2. 避免模板化、套话、AI 感
3. 如有限制条件（字数、格式、关键词）严格遵守
4. 可提供多个版本供选择""",
    "analysis": """你是一个数据/文本分析师。请：
1. 先明确分析目标和方法
2. 结构化输出：背景、方法、发现、结论、建议
3. 区分事实、推断、观点
4. 量化指标优于定性描述""",
}


QUALITY_GUIDELINES = """

---
输出质量要求：
- 无废话、无重复、无矛盾
- 关键信息完整、准确
- 格式整洁、层级清晰
- 代码块标注语言、可直接运行
"""


class PromptEnhancer:
    """提示词增强器：按任务类型注入优化系统提示词"""

    def __init__(self) -> None:
        self.router = router

    def enhance(
        self, messages: list[ChatMessage], task_type: TaskType | None = None
    ) -> list[ChatMessage]:
        """增强消息列表：注入/替换系统提示词"""
        if not messages:
            return messages

        # 检测任务类型
        if task_type is None:
            task_type = self.router.detect_task_type(messages)

        # 获取增强系统提示词
        enhanced_system = (
            ENHANCED_SYSTEM_PROMPTS.get(task_type, ENHANCED_SYSTEM_PROMPTS["chat"])
            + QUALITY_GUIDELINES
        )

        # 查找现有系统消息
        has_system = any(m.role == "system" for m in messages)
        if has_system:
            # 替换/合并系统消息
            new_messages = []
            system_merged = False
            for m in messages:
                if m.role == "system" and not system_merged:
                    # 合并：原系统提示词 + 增强提示词
                    merged = f"{m.content}\n\n{enhanced_system}"
                    new_messages.append(ChatMessage(role="system", content=merged))
                    system_merged = True
                else:
                    new_messages.append(m)
            return new_messages
        else:
            # 插入新系统消息
            return [ChatMessage(role="system", content=enhanced_system)] + messages


prompt_enhancer = PromptEnhancer()
