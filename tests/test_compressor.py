"""压缩引擎单测"""
import pytest

from app.optimizer.compressor import compressor
from app.providers import ChatMessage


class TestCompressor:
    def test_count_tokens(self):
        text = "Hello world"
        count = compressor.count_tokens(text)
        assert count > 0

    def test_count_messages_tokens(self):
        msgs = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there!"),
        ]
        count = compressor.count_messages_tokens(msgs)
        assert count > 0

    def test_heuristic_keep_code(self):
        msg = ChatMessage(role="user", content="请帮我写一个 Python 函数计算斐波那契")
        decision = compressor._classify_by_heuristics(msg)
        assert decision.action == "keep"

    def test_heuristic_drop_greeting(self):
        msg = ChatMessage(role="user", content="好的，谢谢！")
        decision = compressor._classify_by_heuristics(msg)
        assert decision.action == "drop"

    def test_heuristic_summarize_long(self):
        long_text = "这是一段很长的文本" * 100  # 900 字符 > 500 阈值
        msg = ChatMessage(role="user", content=long_text)
        decision = compressor._classify_by_heuristics(msg)
        assert decision.action == "summarize"

    @pytest.mark.asyncio
    async def test_compress_no_op_when_short(self):
        msgs = [
            ChatMessage(role="system", content="You are helpful"),
            ChatMessage(role="user", content="Hi"),
        ]
        compressed, stats = await compressor.compress(msgs, target_tokens=1000)
        # 压缩未启用时返回原消息，stats 包含 original_tokens 等字段
        assert compressed == msgs
        assert stats["original_tokens"] == stats["compressed_tokens"]
        assert stats["saved_tokens"] == 0

    @pytest.mark.asyncio
    async def test_compress_reduces_tokens(self):
        # 构造长对话
        msgs = [ChatMessage(role="system", content="System prompt")]
        for i in range(20):
            msgs.append(ChatMessage(role="user" if i % 2 == 0 else "assistant",
                                     content=f"这是第 {i} 轮对话，包含一些普通文本内容。" * 5))
        compressed, stats = await compressor.compress(msgs, target_tokens=500)
        assert stats["saved_tokens"] > 0
        assert stats["saved_ratio"] > 0
        assert len(compressed) < len(msgs)

    @pytest.mark.asyncio
    async def test_compress_preserves_system_and_recent(self):
        msgs = [ChatMessage(role="system", content="Important system instruction")]
        for i in range(10):
            msgs.append(ChatMessage(role="user", content=f"User {i}"))
            msgs.append(ChatMessage(role="assistant", content=f"Assistant {i}"))
        compressed, _stats = await compressor.compress(msgs, target_tokens=300)
        # 系统消息必须保留
        assert any(m.role == "system" and "Important" in m.content for m in compressed)
        # 最近几轮必须保留
        assert any("User 9" in m.content for m in compressed)
        assert any("Assistant 9" in m.content for m in compressed)