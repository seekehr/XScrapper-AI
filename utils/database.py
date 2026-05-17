from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from .logger import setup_logger

logger = setup_logger("xscrapper.db")


class Database:
    def __init__(self, db_path: str = "data/xscrapper.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(str(self.db_path))
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._create_tables()
        logger.info("Database connected at %s", self.db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def _create_tables(self) -> None:
        assert self._db is not None
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS processed_tweets (
                tweet_id   TEXT PRIMARY KEY,
                keyword    TEXT NOT NULL,
                scraped_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ai_decisions (
                tweet_id       TEXT PRIMARY KEY,
                worth_applying INTEGER NOT NULL,
                confidence     REAL NOT NULL,
                reason         TEXT NOT NULL,
                category       TEXT NOT NULL,
                sentiment      TEXT DEFAULT 'neutral',
                decided_at     TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS webhook_sent (
                tweet_id TEXT PRIMARY KEY,
                sent_at  TEXT NOT NULL
            );
        """)
        await self._db.commit()

    async def is_tweet_processed(self, tweet_id: str) -> bool:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT 1 FROM processed_tweets WHERE tweet_id = ?", (tweet_id,)
        )
        return await cursor.fetchone() is not None

    async def mark_tweet_processed(self, tweet_id: str, keyword: str) -> None:
        assert self._db is not None
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT OR IGNORE INTO processed_tweets (tweet_id, keyword, scraped_at) VALUES (?, ?, ?)",
            (tweet_id, keyword, now),
        )
        await self._db.commit()

    async def save_ai_decision(self, tweet_id: str, decision: dict[str, Any]) -> None:
        assert self._db is not None
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """INSERT OR REPLACE INTO ai_decisions
               (tweet_id, worth_applying, confidence, reason, category, sentiment, decided_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                tweet_id,
                int(decision.get("worth_applying", False)),
                decision.get("confidence", 0.0),
                decision.get("reason", ""),
                decision.get("category", "Other"),
                decision.get("sentiment", "neutral"),
                now,
            ),
        )
        await self._db.commit()

    async def is_webhook_sent(self, tweet_id: str) -> bool:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT 1 FROM webhook_sent WHERE tweet_id = ?", (tweet_id,)
        )
        return await cursor.fetchone() is not None

    async def mark_webhook_sent(self, tweet_id: str) -> None:
        assert self._db is not None
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT OR IGNORE INTO webhook_sent (tweet_id, sent_at) VALUES (?, ?)",
            (tweet_id, now),
        )
        await self._db.commit()

    async def get_stats(self) -> dict[str, int]:
        assert self._db is not None
        stats: dict[str, int] = {}
        for table in ("processed_tweets", "ai_decisions", "webhook_sent"):
            cursor = await self._db.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
            row = await cursor.fetchone()
            stats[table] = row[0] if row else 0
        return stats
