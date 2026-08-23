"""
数据库层模块
==============

本模块提供异步 SQLite 数据库操作，用于存储和查询 API 调用的用量统计。

设计要点：
- 使用 aiosqlite 实现异步数据库操作，避免阻塞事件循环
- 使用异步上下文管理器管理数据库连接生命周期
- 数据库文件存储在用户数据目录（Windows: %APPDATA%\\AIOptimizer）
- 表结构设计：
  - usage_logs: 记录每次 API 调用的详细用量信息
  - 索引优化：按时间戳和会话 ID 建立索引，加速统计查询

表结构 (usage_logs):
- id: 自增主键
- timestamp: 记录时间戳（自动默认当前时间）
- provider: Provider 名称
- model: 模型名称
- request_tokens: 请求 token 数
- response_tokens: 响应 token 数
- total_tokens: 总 token 数
- cost_usd: 估算成本（美元）
- compressed: 是否启用了压缩
- original_tokens: 压缩前原始 token 数
- saved_tokens: 节省的 token 数
- request_id: 请求唯一标识（用于关联请求/响应）
- session_id: 会话 ID（用于会话级统计）

索引：
- idx_usage_timestamp: 按时间戳查询优化
- idx_usage_session: 按会话 ID 查询优化
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite

from app.core.config import settings

# 全局数据库路径，延迟初始化
DB_PATH: Path | None = None


async def init_db() -> None:
    """
    初始化数据库：创建目录、表结构和索引
    
    此函数在应用启动时调用一次，确保数据库就绪。
    使用全局变量 DB_PATH 缓存数据库文件路径。
    """
    global DB_PATH
    # 获取数据目录并确保存在
    data_dir = settings.get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    DB_PATH = data_dir / "usage.db"
    # 同步配置对象中的路径
    settings.usage_db_path = str(DB_PATH)

    # Windows: 使用原始字符串路径，避免 URI 参数解析问题
    # aiosqlite 在 Windows 上不支持 file:// URI 格式，需使用原始路径
    db_path_str = str(DB_PATH)
    print(f"[DEBUG] DB_PATH={DB_PATH}, str={db_path_str}")  # 调试输出
    
    async with aiosqlite.connect(db_path_str) as db:
        # 创建用量日志表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS usage_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,  -- 自增主键
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,  -- 记录时间
                provider TEXT NOT NULL,                    -- Provider 名称
                model TEXT NOT NULL,                       -- 模型名称
                request_tokens INTEGER NOT NULL,           -- 请求 token 数
                response_tokens INTEGER NOT NULL,          -- 响应 token 数
                total_tokens INTEGER NOT NULL,             -- 总 token 数
                cost_usd REAL DEFAULT 0,                   -- 估算成本(美元)
                compressed BOOLEAN DEFAULT 0,              -- 是否压缩
                original_tokens INTEGER DEFAULT 0,         -- 压缩前 token 数
                saved_tokens INTEGER DEFAULT 0,            -- 节省 token 数
                request_id TEXT,                           -- 请求 ID
                session_id TEXT                            -- 会话 ID
            )
        """)
        # 创建时间戳索引，优化按时间范围查询
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage_logs(timestamp)
        """)
        # 创建会话 ID 索引，优化会话级统计查询
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_usage_session ON usage_logs(session_id)
        """)
        await db.commit()


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    """
    获取数据库连接的异步上下文管理器
    
    用法:
        async with get_db() as db:
            await db.execute(...)
    
    机制:
    - 首次调用时自动初始化数据库
    - 设置 row_factory 为 aiosqlite.Row，支持按列名访问
    - 退出上下文时自动关闭连接
    
    返回:
        AsyncIterator[aiosqlite.Connection]: 异步数据库连接迭代器
    """
    if DB_PATH is None:
        await init_db()
    db_path_str = str(DB_PATH)
    async with aiosqlite.connect(db_path_str) as db:
        # 设置行工厂，使查询结果可按列名访问 (row['column_name'])
        db.row_factory = aiosqlite.Row
        yield db


async def log_usage(
    provider: str,
    model: str,
    request_tokens: int,
    response_tokens: int,
    cost_usd: float = 0.0,
    compressed: bool = False,
    original_tokens: int = 0,
    saved_tokens: int = 0,
    request_id: str = "",
    session_id: str = "",
) -> None:
    """
    记录一次 API 调用的用量信息
    
    参数:
        provider: Provider 名称 (如 'openai', 'deepseek')
        model: 模型名称 (如 'gpt-4o', 'deepseek-chat')
        request_tokens: 请求消耗的 token 数
        response_tokens: 响应消耗的 token 数
        cost_usd: 估算成本(美元)，默认 0
        compressed: 是否启用了压缩，默认 False
        original_tokens: 压缩前原始 token 数，默认 0
        saved_tokens: 节省的 token 数，默认 0
        request_id: 请求唯一标识，用于关联请求/响应
        session_id: 会话 ID，用于会话级统计
    """
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO usage_logs
            (provider, model, request_tokens, response_tokens, total_tokens, cost_usd,
             compressed, original_tokens, saved_tokens, request_id, session_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                provider,
                model,
                request_tokens,
                response_tokens,
                request_tokens + response_tokens,  # 总 token = 请求 + 响应
                cost_usd,
                1 if compressed else 0,  # SQLite 无布尔类型，用 0/1 存储
                original_tokens,
                saved_tokens,
                request_id,
                session_id,
            ),
        )
        await db.commit()


async def get_usage_stats(days: int = 7) -> dict[str, Any]:
    """
    获取指定天数内的用量统计数据
    
    返回结构:
    {
        "summary": {总请求数, 总token, 总成本, 节省token},
        "by_provider": [{provider, requests, tokens, cost}, ...],
        "by_model": [{model, requests, tokens, cost}, ...],
        "daily": [{day, requests, tokens, cost}, ...]
    }
    
    参数:
        days: 统计天数，默认 7 天
    
    返回:
        包含汇总、分 Provider、分模型、每日趋势的字典
    """
    async with get_db() as db:
        # ===== 1. 总览统计 =====
        total = await db.execute_fetchall(
            """
            SELECT
                COUNT(*) as requests,              -- 总请求数
                SUM(total_tokens) as total_tokens, -- 总 token 数
                SUM(cost_usd) as total_cost,       -- 总成本
                SUM(CASE WHEN compressed THEN saved_tokens ELSE 0 END) as saved_tokens  -- 节省 token
            FROM usage_logs
            WHERE timestamp >= datetime('now', ?)
        """,
            (f"-{days} days",),  # SQLite 日期运算：N 天前
        )

        # ===== 2. 按 Provider 分组统计 =====
        by_provider = await db.execute_fetchall(
            """
            SELECT
                provider,
                COUNT(*) as requests,
                SUM(total_tokens) as tokens,
                SUM(cost_usd) as cost
            FROM usage_logs
            WHERE timestamp >= datetime('now', ?)
            GROUP BY provider
            """,
            (f"-{days} days",),
        )

        # ===== 3. 按模型分组统计 =====
        by_model = await db.execute_fetchall(
            """
            SELECT
                model,
                COUNT(*) as requests,
                SUM(total_tokens) as tokens,
                SUM(cost_usd) as cost
            FROM usage_logs
            WHERE timestamp >= datetime('now', ?)
            GROUP BY model
            """,
            (f"-{days} days",),
        )

        # ===== 4. 每日趋势统计 =====
        daily = await db.execute_fetchall(
            """
            SELECT
                date(timestamp) as day,    -- 日期
                COUNT(*) as requests,      -- 当日请求数
                SUM(total_tokens) as tokens,  -- 当日 token 数
                SUM(cost_usd) as cost      -- 当日成本
            FROM usage_logs
            WHERE timestamp >= datetime('now', ?)
            GROUP BY date(timestamp)
            ORDER BY day
            """,
            (f"-{days} days",),
        )

        # 转换为可序列化的字典列表
        total_list = list(total)
        return {
            "summary": dict(total_list[0]) if total_list else {},
            "by_provider": [dict(r) for r in by_provider],
            "by_model": [dict(r) for r in by_model],
            "daily": [dict(r) for r in daily],
        }
