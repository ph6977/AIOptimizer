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
  - compression_logs: 记录每条消息的压缩决策详情
  - quality_scores: 记录每次请求的质量评估结果
  - 索引优化：按时间戳和会话 ID 建立索引，加速统计查询
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                request_tokens INTEGER NOT NULL,
                response_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL,
                cost_usd REAL DEFAULT 0,
                compressed BOOLEAN DEFAULT 0,
                original_tokens INTEGER DEFAULT 0,
                saved_tokens INTEGER DEFAULT 0,
                request_id TEXT,
                session_id TEXT
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

        # 创建压缩决策日志表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS compression_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                session_id TEXT,
                message_index INTEGER NOT NULL,
                role TEXT NOT NULL,
                action TEXT NOT NULL,
                reason TEXT,
                original_tokens INTEGER DEFAULT 0,
                saved_tokens INTEGER DEFAULT 0,
                original_content TEXT,
                summary_content TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_compression_request ON compression_logs(request_id)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_compression_session ON compression_logs(session_id)
        """)

        # 创建质量评估表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS quality_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                session_id TEXT,
                score_original INTEGER,
                score_compressed INTEGER,
                winner TEXT,
                reason TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_quality_request ON quality_scores(request_id)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_quality_session ON quality_scores(session_id)
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
                request_tokens + response_tokens,
                cost_usd,
                1 if compressed else 0,
                original_tokens,
                saved_tokens,
                request_id,
                session_id,
            ),
        )
        await db.commit()


async def log_compression_decisions(
    request_id: str,
    session_id: str,
    decisions: list[dict[str, Any]],
) -> None:
    """
    记录压缩决策详情

    参数:
        request_id: 请求唯一标识
        session_id: 会话 ID
        decisions: 压缩决策列表，每项包含:
            - message_index: 消息索引
            - role: 消息角色
            - action: 动作 (keep/summarize/drop)
            - reason: 分类原因
            - original_tokens: 原始 token 数
            - saved_tokens: 节省 token 数
            - original_content: 原文内容
            - summary_content: 摘要内容
    """
    async with get_db() as db:
        for i, d in enumerate(decisions):
            await db.execute(
                """
                INSERT INTO compression_logs
                (request_id, session_id, message_index, role, action, reason,
                 original_tokens, saved_tokens, original_content, summary_content)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    session_id,
                    d.get("message_index", i),
                    d.get("role", ""),
                    d.get("action", "keep"),
                    d.get("reason", ""),
                    d.get("original_tokens", 0),
                    d.get("saved_tokens", 0),
                    d.get("original_content", ""),
                    d.get("summary_content", ""),
                ),
            )
        await db.commit()


async def log_quality_score(
    request_id: str,
    session_id: str,
    score_original: int | None = None,
    score_compressed: int | None = None,
    winner: str = "tie",
    reason: str = "",
) -> None:
    """
    记录质量评估结果

    参数:
        request_id: 请求唯一标识
        session_id: 会话 ID
        score_original: 无压缩回答得分 (1-5)
        score_compressed: 有压缩回答得分 (1-5)
        winner: 胜者 (A/B/tie)
        reason: 评估理由
    """
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO quality_scores
            (request_id, session_id, score_original, score_compressed, winner, reason)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (request_id, session_id, score_original, score_compressed, winner, reason),
        )
        await db.commit()


async def get_compression_details(
    request_id: str | None = None,
    session_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    查询压缩决策详情

    参数:
        request_id: 按请求 ID 过滤
        session_id: 按会话 ID 过滤
        limit: 返回条数限制

    返回:
        压缩决策列表
    """
    async with get_db() as db:
        query = "SELECT * FROM compression_logs WHERE 1=1"
        params: list[Any] = []

        if request_id:
            query += " AND request_id = ?"
            params.append(request_id)
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = await db.execute_fetchall(query, params)
        return [dict(r) for r in rows]


async def get_quality_scores(
    request_id: str | None = None,
    session_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    查询质量评估记录

    参数:
        request_id: 按请求 ID 过滤
        session_id: 按会话 ID 过滤
        limit: 返回条数限制

    返回:
        质量评估记录列表
    """
    async with get_db() as db:
        query = "SELECT * FROM quality_scores WHERE 1=1"
        params: list[Any] = []

        if request_id:
            query += " AND request_id = ?"
            params.append(request_id)
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = await db.execute_fetchall(query, params)
        return [dict(r) for r in rows]


async def get_sessions(
    days: int = 7,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    查询会话列表（按 session_id 分组）

    参数:
        days: 查询天数
        limit: 返回会话数限制

    返回:
        会话列表，每个会话包含汇总信息
    """
    async with get_db() as db:
        rows = await db.execute_fetchall(
            """
            SELECT
                session_id,
                COUNT(*) as request_count,
                SUM(total_tokens) as total_tokens,
                SUM(cost_usd) as total_cost,
                SUM(CASE WHEN compressed THEN saved_tokens ELSE 0 END) as saved_tokens,
                MIN(timestamp) as first_request,
                MAX(timestamp) as last_request,
                GROUP_CONCAT(DISTINCT provider) as providers,
                GROUP_CONCAT(DISTINCT model) as models
            FROM usage_logs
            WHERE timestamp >= datetime('now', ?)
              AND session_id IS NOT NULL
              AND session_id != ''
            GROUP BY session_id
            ORDER BY last_request DESC
            LIMIT ?
            """,
            (f"-{days} days", limit),
        )
        return [dict(r) for r in rows]


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
