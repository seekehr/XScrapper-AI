from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


@dataclass
class Config:
    keywords: list[str] = field(default_factory=list)
    scrape_limit_per_keyword: int = 30
    batch_size: int = 15
    headless: bool = True
    poll_interval_seconds: int = 300
    discord_webhook: str = ""
    gemini_api_key: str = ""
    x_auth_token: str = ""
    minimum_post_likes: int = 0
    minimum_post_views: int = 0
    max_post_age_hours: int = 24
    proxy_list: list[str] = field(default_factory=list)
    csv_export_path: str = "exports/leads.csv"
    db_path: str = "data/xscrapper.db"
    max_retries: int = 3
    retry_delay_seconds: int = 5
    keyword_webhooks: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path = "settings.json") -> Config:
        # Load .env.local first, fall back to .env
        load_dotenv(".env.local")
        load_dotenv(".env")

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Settings file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)

        config = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

        # Environment variables override settings.json for secrets
        config.gemini_api_key = os.getenv("GEMINI_API_KEY", config.gemini_api_key)
        config.discord_webhook = os.getenv("DISCORD_WEBHOOK", config.discord_webhook)
        config.x_auth_token = os.getenv("X_AUTH_TOKEN", config.x_auth_token)

        return config

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.keywords:
            errors.append("No keywords configured")
        if not self.gemini_api_key:
            errors.append("gemini_api_key is required")
        if not self.discord_webhook:
            errors.append("discord_webhook is required")
        if not self.x_auth_token:
            errors.append("x_auth_token is required for authenticated scraping")
        return errors
