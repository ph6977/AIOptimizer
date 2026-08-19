"""上下文压缩引擎 v1：两阶段（分类→压缩）"""
import json
import tiktoken
from typing import Literal
from dataclasses import dataclass
from app.providers import ProviderFactory, ChatMessage, ChatCompletionRequest
from app.core.config import settings


CompressionAction = Literal["keep", "summarize", "drop"]


@dataclass
class CompressionDecision:
    action: CompressionAction
    reason: str
    summary: str | None = None


@dataclass
class MessageWithDecision:
    original: ChatMessage
    decision: CompressionDecision
    tokens: int


class Compressor:
    """上下文压缩器

    策略：
    1. 对旧消息进行分类：keep / summarize / drop
    2. 按预算保留：优先保留 keep，然后 summarize，最后 drop
    3. 滑动窗口 + 摘要缓冲区
    """

    # 关键信息判定关键词
    KEEP_KEYWORDS = [
        "代码", "函数", "类", "变量", "参数", "返回值", "错误", "异常", "bug",
        "决定", "结论", "方案", "架构", "设计", "接口", "API", "数据库", "表",
        "用户", "偏好", "习惯", "要求", "约束", "必须", "禁止", "注意",
        "密码", "token", "key", "secret", "配置", "环境变量",
        "文件", "路径", "目录", "行号", "版本", "提交", "分支",
    ]

    DROP_KEYWORDS = [
        "你好", "谢谢", "没问题", "好的", "明白", "理解", "收到",
        "哈哈", "呵呵", "emoji", "表情",
    ]

    def __init__(self):
        self.encoding = tiktoken.get_encoding("cl100k_base")
        self._judge_cache: dict[str, CompressionDecision] = {}

    def count_tokens(self, text: str) -> int:
        return len(self.encoding.encode(text))

    def count_messages_tokens(self, messages: list[ChatMessage]) -> int:
        total = 0
        for m in messages:
            total += self.count_tokens(m.role) + self.count_tokens(m.content)
            if m.name:
                total += self.count_tokens(m.name)
        return total + len(messages) * 4  # 角色开销

    def _classify_by_heuristics(self, message: ChatMessage) -> CompressionDecision:
        """启发式快速分类（不调用 LLM）"""
        content = message.content.lower()

        # 系统消息、开发者消息永远保留
        if message.role in ("system", "developer"):
            return CompressionDecision("keep", "系统/开发者消息")

        # 包含代码块、关键技术信息 -> keep
        if "```" in message.content or any(kw in content for kw in self.KEEP_KEYWORDS):
            return CompressionDecision("keep", "包含关键技术信息/代码")

        # 纯寒暄、确认类 -> drop
        if len(message.content) < 50 and any(kw in content for kw in self.DROP_KEYWORDS):
            return CompressionDecision("drop", "纯寒暄/确认类")

        # 长文本且非关键 -> summarize
        if len(message.content) > 500:
            return CompressionDecision("summarize", "长文本非关键内容")

        # 默认保留
        return CompressionDecision("keep", "默认保留")

    async def _classify_by_llm(self, message: ChatMessage, context_hint: str = "") -> CompressionDecision:
        """LLM-judge 精细分类（带缓存）"""
        cache_key = f"{message.role}:{hash(message.content)}"
        if cache_key in self._judge_cache:
            return self._judge_cache[cache_key]

        # 这里简化：实际应调用廉价模型做判断
        # 暂时回退到启发式
        decision = self._classify_by_heuristics(message)
        self._judge_cache[cache_key] = decision
        return decision

    async def compress(
        self,
        messages: list[ChatMessage],
        target_tokens: int | None = None,
        max_context_tokens: int | None = None,
    ) -> tuple[list[ChatMessage], dict]:
        """
        压缩消息列表

        Returns:
            (compressed_messages, stats)
            stats: {
                "original_tokens": int,
                "compressed_tokens": int,
                "saved_tokens": int,
                "saved_ratio": float,
                "kept": int,
                "summarized": int,
                "dropped": int,
            }
        """
        target = target_tokens or settings.target_context_tokens
        max_ctx = max_context_tokens or settings.max_context_tokens

        if not settings.compression_enabled:
            return messages, {"enabled": False}

        original_tokens = self.count_messages_tokens(messages)
        if original_tokens <= target:
            return messages, {
                "original_tokens": original_tokens,
                "compressed_tokens": original_tokens,
                "saved_tokens": 0,
                "saved_ratio": 0.0,
                "kept": len(messages),
                "summarized": 0,
                "dropped": 0,
            }

        # 从旧到新处理（保留最近的系统消息和最后几轮对话）
        system_messages = [m for m in messages if m.role == "system"]
        other_messages = [m for m in messages if m.role != "system"]

        # 保留最近 N 轮对话不压缩（默认保留最后 4 条非系统消息）
        keep_recent = 4
        to_compress = other_messages[:-keep_recent] if len(other_messages) > keep_recent else []
        recent_messages = other_messages[-keep_recent:] if len(other_messages) > keep_recent else other_messages

        if not to_compress:
            return messages, {
                "original_tokens": original_tokens,
                "compressed_tokens": original_tokens,
                "saved_tokens": 0,
                "saved_ratio": 0.0,
                "kept": len(messages),
                "summarized": 0,
                "dropped": 0,
            }

        # 分类阶段
        decisions: list[MessageWithDecision] = []
        for msg in to_compress:
            decision = await self._classify_by_llm(msg)
            tokens = self.count_tokens(msg.content) + self.count_tokens(msg.role)
            decisions.append(MessageWithDecision(msg, decision, tokens))

        # 预算分配：先计算必须保留的 tokens
        system_tokens = sum(self.count_tokens(m.content) + self.count_tokens(m.role) for m in system_messages)
        recent_tokens = sum(self.count_tokens(m.content) + self.count_tokens(m.role) for m in recent_messages)
        budget = target - system_tokens - recent_tokens

        if budget <= 0:
            # 预算不足，只保留系统消息和最近消息
            compressed = system_messages + recent_messages
            compressed_tokens = self.count_messages_tokens(compressed)
            return compressed, {
                "original_tokens": original_tokens,
                "compressed_tokens": compressed_tokens,
                "saved_tokens": original_tokens - compressed_tokens,
                "saved_ratio": (original_tokens - compressed_tokens) / original_tokens,
                "kept": len(system_messages) + len(recent_messages),
                "summarized": 0,
                "dropped": len(to_compress),
            }

        # 贪心策略：优先保留 keep，然后 summarize，最后 drop
        kept_msgs = []
        summarized_content = []
        dropped_count = 0

        for mw in decisions:
            if mw.decision.action == "keep" and mw.tokens <= budget:
                kept_msgs.append(mw.original)
                budget -= mw.tokens
            elif mw.decision.action == "summarize" and mw.tokens <= budget * 0.3:
                # 摘要只占用预算的 30%
                if mw.decision.summary:
                    summarized_content.append(mw.decision.summary)
                else:
                    # 简单摘要：取前 200 字符
                    summary = mw.original.content[:200] + "..." if len(mw.original.content) > 200 else mw.original.content
                    summarized_content.append(f"[摘要] {mw.original.role}: {summary}")
                budget -= mw.tokens // 3  # 摘要大约节省 2/3
            else:
                dropped_count += 1

        # 组装摘要消息
        summary_msgs = []
        if summarized_content:
            summary_text = "\n".join(summarized_content)
            summary_msgs.append(ChatMessage(role="system", content=f"[历史对话摘要]\n{summary_text}"))

        # 组装最终消息：系统 + 摘要 + 保留的旧消息 + 最近消息
        compressed = system_messages + summary_msgs + kept_msgs + recent_messages
        compressed_tokens = self.count_messages_tokens(compressed)

        stats = {
            "original_tokens": original_tokens,
            "compressed_tokens": compressed_tokens,
            "saved_tokens": original_tokens - compressed_tokens,
            "saved_ratio": (original_tokens - compressed_tokens) / original_tokens if original_tokens > 0 else 0,
            "kept": len(system_messages) + len(kept_msgs) + len(recent_messages),
            "summarized": len(summarized_content),
            "dropped": dropped_count,
            "details": [
                {"role": mw.original.role, "action": mw.decision.action, "reason": mw.decision.reason, "tokens": mw.tokens}
                for mw in decisions
            ],
        }

        return compressed, stats


# 单例
compressor = Compressor()