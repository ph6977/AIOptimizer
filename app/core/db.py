"""数据库层"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite

from app.core.config import settings

DB_PATH: Path | None = None


async def init_db() -> None:
    global DB_PATH
    data_dir = settings.get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    DB_PATH = data_dir / "usage.db"
    settings.usage_db_path = str(DB_PATH)

    # Windows: 使用原始字符串路径，避免 URI 参数问题
    db_path_str = str(DB_PATH)
    print(f"[DEBUG] DB_PATH={DB_PATH}, str={db_path_str}")  # 调试
    async with aiosqlite.connect(db_path_str) as db:
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
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage_logs(timestamp)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_usage_session ON usage_logs(session_id)
        """)
        await db.commit()


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    if DB_PATH is None:
        await init_db()
    db_path_str = str(DB_PATH)
    async with aiosqlite.connect(db_path_str) as db:
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


async def get_usage_stats(days: int = 7) -> dict[str, Any]:
    """获取用量统计"""
    async with get_db() as db:
        # 总览
        total = await db.execute_fetchall(
            """
            SELECT
                COUNT(*) as requests,
                SUM(total_tokens) as total_tokens,
                SUM(cost_usd) as total_cost,
                SUM(CASE WHEN compressed THEN saved_tokens ELSE 0 END) as saved_tokens
            FROM usage_logs
            WHERE timestamp >= datetime('now', ?)
        """,
            (f"-{days} days",),
        )

        # 按 Provider 分组
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

        # 按模型分组
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

        # 每日趋势
        daily = await db.execute_fetchall(
            """
            SELECT
                date(timestamp) as day,
                COUNT(*) as requests,
                SUM(total_tokens) as tokens,
                SUM(cost_usd) as cost
            FROM usage_logs
            WHERE timestamp >= datetime('now', ?)
            GROUP BY date(timestamp)
            ORDER BY day
        """,
            (f"-{days} days",),
        )

        total_list = list(total)
        return {
            "summary": dict(total_list[0]) if total_list else {},
            "by_provider": [dict(r) for r in by_provider],
            "by_model": [dict(r) for r in by_model],
            "daily": [dict(r) for r in daily],
        }
