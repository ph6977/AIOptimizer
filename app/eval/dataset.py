"""评估数据集"""
from dataclasses import dataclass
from typing import Literal


TaskType = Literal["chat", "code", "reasoning", "vision", "creative", "analysis"]


@dataclass
class EvalCase:
    id: str
    task_type: TaskType
    messages: list[dict]
    expected_keywords: list[str] = None
    min_quality_score: float = 3.0

    def __post_init__(self):
        if self.expected_keywords is None:
            self.expected_keywords = []


EVAL_CASES = [
    EvalCase("chat_01", "chat", [{"role": "user", "content": "你好，请介绍一下 Python 的装饰器"}], ["装饰器", "函数", "@", "语法糖"]),
    EvalCase("chat_02", "chat", [{"role": "user", "content": "解释一下什么是 RESTful API"}], ["REST", "HTTP", "资源", "状态码"]),
    EvalCase("chat_03", "chat", [{"role": "user", "content": "如何在 Linux 下查看端口占用？"}], ["netstat", "ss", "lsof", "端口", "进程"]),
    EvalCase("code_01", "code", [{"role": "user", "content": "写一个 Python 类实现单例模式"}], ["__new__", "_instance", "classmethod", "threading"]),
    EvalCase("code_02", "code", [{"role": "user", "content": "实现一个 LRU 缓存，要求 O(1) 时间复杂度"}], ["OrderedDict", "get", "put", "双向链表", "哈希表"]),
    EvalCase("code_03", "code", [{"role": "user", "content": "用 Python 写一个异步 HTTP 客户端，支持重试和超时"}], ["aiohttp", "async", "retry", "timeout", "ClientSession"]),
    EvalCase("code_04", "code", [{"role": "user", "content": "重构这段代码使其更符合 Python 惯用写法：\nfor i in range(len(items)):\n    if items[i] > 0:\n        result.append(items[i] * 2)"}], ["列表推导式", "item", "简洁", "Pythonic"]),
    EvalCase("reasoning_01", "reasoning", [{"role": "user", "content": "如果所有 A 都是 B，所有 B 都是 C，那么所有 A 都是 C 吗？请解释"}], ["逻辑", "传递性", "三段论", "正确"]),
    EvalCase("reasoning_02", "reasoning", [{"role": "user", "content": "一个池塘里有睡莲，每天面积翻倍，第 30 天覆盖整个池塘，第几天覆盖一半？"}], ["29", "第 29 天", "指数增长", "翻倍"]),
    EvalCase("reasoning_03", "reasoning", [{"role": "user", "content": "三个数的和是 20，积是 90，这三个数是什么？"}], ["2", "3", "15", "因式分解"]),
    EvalCase("creative_01", "creative", [{"role": "user", "content": "写一首关于程序员加班的五言绝句"}], ["代码", "屏幕", "深夜", "键盘", "五言", "绝句"]),
    EvalCase("creative_02", "creative", [{"role": "user", "content": "用幽默的口吻写一段产品经理和程序员的对话"}], ["需求", "上线", "改需求", "重构", "幽默"]),
    EvalCase("analysis_01", "analysis", [{"role": "user", "content": "对比 Python 和 Go 在并发处理上的优劣势"}], ["GIL", "协程", "goroutine", "channel", "线程", "内存"]),
    EvalCase("analysis_02", "analysis", [{"role": "user", "content": "分析这段代码的时间复杂度和空间复杂度：\ndef foo(n):\n    if n <= 1: return n\n    return foo(n-1) + foo(n-2)"}], ["O(2^n)", "指数级", "递归", "重复计算", "斐波那契"]),
    EvalCase("multi_01", "chat", [
        {"role": "user", "content": "我想学习机器学习，从哪里开始？"},
        {"role": "assistant", "content": "建议从 Python 基础、数学基础入手..."},
        {"role": "user", "content": "推荐几本入门书籍"}
    ], ["《机器学习实战》", "《统计学习方法》", "《深度学习》", "入门"]),
    EvalCase("multi_02", "code", [
        {"role": "user", "content": "写一个 FastAPI 的用户注册接口"},
        {"role": "assistant", "content": "from fastapi import FastAPI...\n@app.post('/register')\nasync def register(user: UserCreate):..."},
        {"role": "user", "content": "加上密码加密和 JWT 认证"}
    ], ["bcrypt", "hash", "jwt", "token", "Bearer", "过期时间"]),
]


def get_cases_by_type(task_type: TaskType) -> list[EvalCase]:
    return [c for c in EVAL_CASES if c.task_type == task_type]


def get_all_cases() -> list[EvalCase]:
    return EVAL_CASES