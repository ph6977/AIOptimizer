"""配置管理"""
import os
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderConfig(BaseSettings):
    """单个 Provider 的配置"""
    name: str
    display_name: str
    api_key: str = ""
    base_url: str = ""
    models: list[str] = Field(default_factory=list)
    enabled: bool = True
    priority: int = 0  # 路由优先级，数值越小优先级越高
    extra: dict[str, Any] = Field(default_factory=dict)


class Settings(BaseSettings):
    """全局设置"""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 网关
    gateway_host: str = "127.0.0.1"
    gateway_port: int = 8000
    gateway_workers: int = 1

    # 压缩引擎
    compression_enabled: bool = True
    compression_aggressiveness: float = 0.5  # 0-1，越大压缩越激进
    compression_model: str = "deepseek-chat"  # 用于 judge 的廉价模型
    max_context_tokens: int = 8192
    target_context_tokens: int = 4096

    # 路由
    routing_enabled: bool = True
    quality_vs_cost: float = 0.5  # 0=极致省钱，1=极致质量

    # 提示词增强
    prompt_enhancement_enabled: bool = True

    # 用量记录
    usage_db_path: str = ""

    # Provider 列表（JSON 存储，运行时动态增删）
    providers_json: str = "[]"

    def get_providers(self) -> list[ProviderConfig]:
        import json
        try:
            data = json.loads(self.providers_json)
            return [ProviderConfig(**p) for p in data]
        except Exception:
            return []

    def set_providers(self, providers: list[ProviderConfig]) -> None:
        import json
        self.providers_json = json.dumps([p.model_dump() for p in providers], ensure_ascii=False)

    def get_data_dir(self) -> Path:
        """获取数据目录"""
        if os.name == "nt":
            base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        else:
            base = Path.home() / ".local" / "share"
        return base / "AIOptimizer"


settings = Settings()

# 运行时动态配置（不持久化）
runtime_config: dict[str, Any] = {}