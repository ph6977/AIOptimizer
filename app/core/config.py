"""
配置管理模块
==============

本模块使用 Pydantic Settings 管理应用程序的所有配置。
支持从 .env 文件、环境变量、代码默认值三层配置源加载（优先级：环境变量 > .env > 默认值）。

配置分类：
1. 网关配置 - 服务监听地址、端口、工作进程数
2. 压缩引擎 - 启用开关、激进度、模型、上下文长度、保留策略
3. 评估 Judge - 模型、API Key、Base URL
3. 智能路由 - 启用开关、质量/成本权重
4. 提示词增强 - 启用开关
5. 用量记录 - 数据库路径
6. Provider 列表 - JSON 序列化存储，运行时动态增删

设计要点：
- 使用 Pydantic v2 的 BaseSettings 自动完成类型验证和转换
- ProviderConfig 作为嵌套模型，支持列表存储
- providers_json 使用 JSON 序列化存储 Provider 列表
- runtime_config 用于运行时临时配置（不持久化）
"""

import os
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderConfig(BaseSettings):
    """
    单个 AI Provider 的配置模型

    每个 Provider 代表一个 AI 服务商（如 OpenAI、DeepSeek、Claude 等）。
    所有字段都有默认值，支持通过 .env 或代码动态配置。
    """

    name: str
    """Provider 内部标识名，如 'openai', 'deepseek', 'anthropic' 等"""

    display_name: str
    """显示名称，用于 UI 显示，如 'OpenAI', 'DeepSeek'"""

    api_key: str = ""
    """API 密钥，用于认证，敏感信息建议通过 .env 配置"""

    base_url: str = ""
    """API 基础 URL，空字符串表示使用 Provider 的默认地址"""

    models: list[str] = Field(default_factory=list)
    """支持的模型列表，如 ['gpt-4o', 'gpt-4o-mini']"""

    enabled: bool = True
    """是否启用此 Provider，禁用后不参与路由和模型列表"""

    priority: int = 0
    """
    路由优先级，数值越小优先级越高
    用于路由决策时的加分项：优先级越高越容易被选中
    """

    extra: dict[str, Any] = Field(default_factory=dict)
    """扩展字段，用于存储 Provider 特有的额外配置"""


class Settings(BaseSettings):
    """
    全局应用设置

    使用 Pydantic v2 的 SettingsConfigDict 配置：
    - env_file: 从 .env 文件加载环境变量
    - env_file_encoding: 文件编码为 UTF-8
    - extra='ignore': 忽略未定义的额外字段，防止配置错误
    """

    model_config = SettingsConfigDict(
        env_file=".env",  # 配置文件路径
        env_file_encoding="utf-8",  # 编码格式
        extra="ignore",  # 忽略未定义字段
    )

    # ==================== 网关配置 ====================
    gateway_host: str = "127.0.0.1"
    """网关监听地址，默认本地回环，生产环境可改为 0.0.0.0"""

    gateway_port: int = 8000
    """网关监听端口，默认 8000"""

    gateway_workers: int = 1
    """工作进程数，uvicorn 的 workers 参数，建议生产环境设为 CPU 核心数"""

    # ==================== 压缩引擎配置 ====================
    compression_enabled: bool = True
    """是否启用上下文压缩，False 则直接透传原始上下文"""

    compression_aggressiveness: float = 0.5
    """
    压缩激进度 (0.0-1.0)，越大压缩越激进
    - 0.0: 保守，只删除明显冗余
    - 1.0: 激进，大幅压缩甚至牺牲部分信息
    """

    compression_model: str = "deepseek-chat"
    """用于 LLM Judge 评估的廉价模型名称"""

    max_context_tokens: int = 8192
    """最大上下文长度（token 数），超过此值触发压缩"""

    target_context_tokens: int = 4096
    """压缩目标 token 数，压缩后上下文不超过此值"""

    compression_keep_recent: int = 4
    """保留最近 N 条非系统消息不压缩，保证最近对话完整性"""

    compression_target_ratio: float = 0.5
    """目标压缩比，压缩后 token 数 / 原始 token 数，越小压缩越多"""

    compression_min_keep_tokens: int = 500
    """最少保留的 token 数，防止过度压缩导致上下文过短"""

    # ==================== 评估 Judge 配置 ====================
    judge_model: str = "deepseek-chat"
    """评估时使用的 Judge 模型名称"""

    judge_api_key: str = ""
    """Judge 模型的 API Key，配置后直接调用 DeepSeek API 进行评估"""

    judge_base_url: str = "https://api.deepseek.com/v1"
    """Judge 模型的 API Base URL"""

    # ==================== 智能路由配置 ====================
    routing_enabled: bool = True
    """是否启用智能路由，False 则使用第一个可用 Provider"""

    quality_vs_cost: float = 0.5
    """
    质量 vs 成本权重 (0.0-1.0)
    - 0.0: 极致省钱，优先选择便宜模型
    - 1.0: 极致质量，优先选择能力强的模型
    - 0.5: 平衡模式
    """

    # ==================== 提示词增强配置 ====================
    prompt_enhancement_enabled: bool = True
    """是否启用提示词增强，根据任务类型自动注入优化系统提示词"""

    # ==================== 用量记录配置 ====================
    usage_db_path: str = ""
    """用量统计 SQLite 数据库路径，空则自动使用数据目录"""

    # ==================== Provider 列表（运行时动态管理） ====================
    providers_json: str = "[]"
    """
    Provider 列表的 JSON 序列化字符串
    运行时通过 GUI 动态增删改，不直接编辑此字段
    """

    def get_providers(self) -> list[ProviderConfig]:
        """
        从 JSON 字符串反序列化 Provider 列表

        返回:
            ProviderConfig 对象列表，解析失败返回空列表
        """
        import json

        try:
            data = json.loads(self.providers_json)
            if data:
                return [ProviderConfig(**p) for p in data]
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        # 如果没有保存的 Provider，从环境变量加载默认列表
        return self._get_default_providers()

    def _get_default_providers(self) -> list[ProviderConfig]:
        """从环境变量/.env 加载默认 Provider 列表"""
        env_keys = self._load_env_keys()
        return [
            ProviderConfig(
                name="openai",
                display_name="OpenAI",
                api_key=env_keys.get("OPENAI_API_KEY", ""),
                base_url="https://api.openai.com/v1",
                models=["gpt-4o", "gpt-4o-mini"],
                enabled=True,
                priority=0,
            ),
            ProviderConfig(
                name="deepseek",
                display_name="DeepSeek",
                api_key=env_keys.get("DEEPSEEK_API_KEY", ""),
                base_url="https://api.deepseek.com/v1",
                models=["deepseek-chat", "deepseek-reasoner"],
                enabled=True,
                priority=0,
            ),
            ProviderConfig(
                name="glm",
                display_name="Zhipu GLM",
                api_key=env_keys.get("GLM_API_KEY", ""),
                base_url="https://open.bigmodel.cn/api/paas/v4",
                models=["glm-4", "glm-4v"],
                enabled=True,
                priority=0,
            ),
            ProviderConfig(
                name="qwen",
                display_name="Alibaba Qwen",
                api_key=env_keys.get("QWEN_API_KEY", ""),
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                models=["qwen-max", "qwen-plus", "qwen-turbo"],
                enabled=True,
                priority=0,
            ),
            ProviderConfig(
                name="kimi",
                display_name="Moonshot Kimi",
                api_key=env_keys.get("KIMI_API_KEY", ""),
                base_url="https://api.moonshot.cn/v1",
                models=["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
                enabled=True,
                priority=0,
            ),
            ProviderConfig(
                name="ollama",
                display_name="Ollama (本地)",
                api_key="",
                base_url="http://localhost:11434/v1",
                models=["llama3.1", "qwen2.5", "deepseek-r1"],
                enabled=True,
                priority=0,
            ),
        ]

    @staticmethod
    def _load_env_keys() -> dict[str, str]:
        """仅从 .env 文件读取 API Key（不依赖系统环境变量）"""
        result: dict[str, str] = {}

        env_path = Path(".env")
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if key.endswith("_API_KEY"):
                    result[key] = value.strip()

        return result

    def set_providers(self, providers: list[ProviderConfig]) -> None:
        """
        将 Provider 列表序列化为 JSON 字符串存储

        参数:
            providers: ProviderConfig 对象列表
        """
        import json

        self.providers_json = json.dumps(
            [p.model_dump() for p in providers], ensure_ascii=False
        )

    def get_data_dir(self) -> Path:
        """
        获取应用数据目录路径

        Windows: %APPDATA%\\AIOptimizer
        Linux/macOS: ~/.local/share/AIOptimizer

        返回目录 Path 对象，目录不存在会在首次使用时自动创建
        """
        if os.name == "nt":
            # Windows: 使用 APPDATA 环境变量
            base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        else:
            # Linux/macOS: 使用 XDG 标准目录
            base = Path.home() / ".local" / "share"
        return base / "AIOptimizer"


# 全局设置单例实例，全程使用此对象访问配置
settings = Settings()

# 运行时动态配置（不持久化，仅内存中临时存储）
runtime_config: dict[str, Any] = {}
