from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .logger import setup_logger

logger = setup_logger("xscrapper.tweet_store")

_DEFAULT_PATH = "data/tweets.json"


class TweetStore:
    """Persist scraped tweet data to a JSON file and prevent re-scraping."""

    def __init__(self, path: str = _DEFAULT_PATH) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._ids: set[str] = set()
        self._tweets: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._tweets = data if isinstance(data, list) else []
                self._ids = {t["tweet_id"] for t in self._tweets if "tweet_id" in t}
                logger.info("Loaded %d cached tweets from %s", len(self._tweets), self._path)
            except Exception as e:
                logger.warning("Failed to load tweet store, starting fresh: %s", e)
                self._tweets = []
                self._ids = set()

    def contains(self, tweet_id: str) -> bool:
        return tweet_id in self._ids

    def add(self, tweets: list[dict[str, Any]]) -> int:
        """Add new tweets (skips duplicates). Returns the count added."""
        new = [t for t in tweets if t.get("tweet_id") not in self._ids]
        if not new:
            return 0
        self._tweets.extend(new)
        self._ids.update(t["tweet_id"] for t in new)
        self._save()
        logger.info("Added %d new tweets to store (%d total)", len(new), len(self._tweets))
        return len(new)

    def _save(self) -> None:
        self._path.write_text(
            json.dumps(self._tweets, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def all(self) -> list[dict[str, Any]]:
        return list(self._tweets)

    @property
    def total(self) -> int:
        return len(self._tweets)
