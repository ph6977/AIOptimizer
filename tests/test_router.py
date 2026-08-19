"""路由器单测"""
from app.optimizer.router import router
from app.providers import ChatMessage


class MockProviderConfig:
    def __init__(self, name, display_name, api_key, base_url, models, enabled=True, priority=0):
        self.name = name
        self.display_name = display_name
        self.api_key = api_key
        self.base_url = base_url
        self.models = models
        self.enabled = enabled
        self.priority = priority


class TestRouter:
    def test_detect_task_type_code(self):
        msgs = [ChatMessage(role="user", content="请帮我写一个 Python 函数实现快速排序")]
        task = router.detect_task_type(msgs)
        assert task == "code"

    def test_detect_task_type_reasoning(self):
        msgs = [ChatMessage(role="user", content="请推导一下这个数学公式的证明过程")]
        task = router.detect_task_type(msgs)
        assert task == "reasoning"

    def test_estimate_difficulty(self):
        # 简单消息
        easy = [ChatMessage(role="user", content="你好")]
        assert router.estimate_difficulty(easy) < 0.3
        # 复杂消息：超长文本 + 多轮（总长 > 10000 字符）
        long_text = "请详细实现一个支持分布式事务的微服务架构，包含服务注册、配置中心、网关、熔断、限流、链路追踪等核心组件" * 50
        hard = [ChatMessage(role="user", content=long_text)] * 10
        assert router.estimate_difficulty(hard) > 0.5

    def test_detect_task_type_vision(self):
        msgs = [ChatMessage(role="user", content="请帮我看这张图片里有什么")]
        task = router.detect_task_type(msgs)
        assert task == "vision"

    def test_detect_task_type_default_chat(self):
        msgs = [ChatMessage(role="user", content="你好，今天天气怎么样？")]
        task = router.detect_task_type(msgs)
        assert task == "chat"

    def test_route_selects_provider(self):
        providers = [
            MockProviderConfig("deepseek", "DeepSeek", "key1", "", ["deepseek-chat"]),
            MockProviderConfig("openai", "OpenAI", "key2", "", ["gpt-4o"]),
        ]
        request = type('Request', (), {
            'model': '',
            'messages': [ChatMessage(role="user", content="写个快排")],
            'temperature': 0.7,
        })()
        decision = router.route(request, providers)
        assert decision.provider in ("deepseek", "openai")
        assert decision.model in ("deepseek-chat", "gpt-4o")
        assert decision.confidence > 0

    def test_route_prefers_lower_priority(self):
        providers = [
            MockProviderConfig("deepseek", "DeepSeek", "k1", "", ["deepseek-chat"], priority=10),
            MockProviderConfig("openai", "OpenAI", "k2", "", ["gpt-4o"], priority=0),
        ]
        request = type('Request', (), {
            'model': '',
            'messages': [ChatMessage(role="user", content="hello")],
        })()
        decision = router.route(request, providers)
        assert decision.provider == "openai"  # priority 0 优先

    def test_route_fallback_when_no_model(self):
        providers = [MockProviderConfig("deepseek", "DeepSeek", "k", "", ["deepseek-chat"])]
        request = type('Request', (), {
            'model': '',
            'messages': [ChatMessage(role="user", content="hi")],
        })()
        decision = router.route(request, providers)
        assert decision.provider == "deepseek"
        assert decision.model == "deepseek-chat"