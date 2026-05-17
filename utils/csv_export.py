from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .logger import setup_logger

logger = setup_logger("xscrapper.csv")


class CSVExporter:
    FIELDS = [
        "tweet_id", "author_username", "author_display_name", "post_text",
        "post_url", "timestamp", "likes", "reposts", "replies", "views",
        "worth_applying", "confidence", "reason", "category", "sentiment",
    ]

    def __init__(self, export_path: str = "exports/leads.csv") -> None:
        self.path = Path(export_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def export(self, tweet: dict[str, Any], decision: dict[str, Any]) -> None:
        file_exists = self.path.exists()
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.FIELDS, extrasaction="ignore")
            if not file_exists:
                writer.writeheader()
            row = {**tweet, **decision}
            writer.writerow(row)
        logger.info("Exported lead to CSV: %s", tweet.get("tweet_id", "unknown"))
