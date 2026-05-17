from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from utils.config import Config
from utils.logger import setup_logger

logger = setup_logger("xscrapper.ai")


class GeminiFilter:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._system_prompt: str = ""
        self._client = genai.Client(api_key=config.gemini_api_key)

    def load_system_prompt(self, path: str | Path = "system_prompt.txt") -> None:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"System prompt not found: {p}")
        self._system_prompt = p.read_text(encoding="utf-8").strip()
        logger.info("Loaded system prompt (%d chars)", len(self._system_prompt))

    def _build_user_prompt(self, tweets: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for i, t in enumerate(tweets):
            lines.append(
                f"[{i}] @{t.get('author_username', '?')} "
                f"({t.get('author_display_name', '?')}): "
                f"{t.get('post_text', '')[:500]} "
                f"| Likes: {t.get('likes', 0)} | Views: {t.get('views', 0)} "
                f"| Reposts: {t.get('reposts', 0)}"
            )
        return "\n".join(lines)

    async def analyze_batch(self, tweets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not tweets:
            return []
        if not self._system_prompt:
            self.load_system_prompt()

        user_prompt = self._build_user_prompt(tweets)

        for attempt in range(self.config.max_retries):
            try:
                response = await asyncio.to_thread(
                    self._client.models.generate_content,
                    model="gemini-2.5-flash",
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=self._system_prompt,
                        temperature=0.1,
                        response_mime_type="application/json",
                    ),
                )

                text = response.text.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

                results: list[dict[str, Any]] = json.loads(text)
                logger.info("Gemini analyzed batch of %d tweets, got %d results", len(tweets), len(results))
                return results

            except json.JSONDecodeError as e:
                logger.warning("Gemini returned invalid JSON (attempt %d): %s", attempt + 1, e)
            except Exception as e:
                logger.error("Gemini API error (attempt %d): %s", attempt + 1, e)

            if attempt < self.config.max_retries - 1:
                delay = self.config.retry_delay_seconds * (attempt + 1)
                logger.info("Retrying in %ds...", delay)
                await asyncio.sleep(delay)

        logger.error("All Gemini retries exhausted for batch of %d tweets", len(tweets))
        return []

    async def analyze_all(self, tweets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        all_results: list[dict[str, Any]] = []
        batch_size = self.config.batch_size

        for i in range(0, len(tweets), batch_size):
            batch = tweets[i : i + batch_size]
            logger.info("Processing batch %d-%d of %d", i, i + len(batch), len(tweets))
            results = await self.analyze_batch(batch)

            for r in results:
                r["_global_index"] = i + r.get("post_index", 0)
            all_results.extend(results)

            if i + batch_size < len(tweets):
                await asyncio.sleep(2)

        return all_results
