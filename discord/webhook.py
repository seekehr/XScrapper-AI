from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from utils.config import Config
from utils.database import Database
from utils.logger import setup_logger

logger = setup_logger("xscrapper.discord")

CATEGORY_COLORS = {
    "AI Automation": 0x7C3AED,
    "SaaS Development": 0x2563EB,
    "Full Stack": 0x059669,
    "Chatbot": 0xD97706,
    "Technical Hiring": 0xDC2626,
    "Consulting": 0x6366F1,
    "Other": 0x6B7280,
}


class DiscordWebhook:
    def __init__(self, config: Config, db: Database) -> None:
        self.config = config
        self.db = db

    def _build_embed(self, tweet: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
        category = decision.get("category", "Other")
        confidence = decision.get("confidence", 0.0)
        sentiment = decision.get("sentiment", "neutral")

        confidence_bar = "█" * int(confidence * 10) + "░" * (10 - int(confidence * 10))

        return {
            "title": f"🎯 Lead Found — {category}",
            "color": CATEGORY_COLORS.get(category, 0x6B7280),
            "fields": [
                {
                    "name": "Author",
                    "value": f"**{tweet.get('author_display_name', 'Unknown')}** (@{tweet.get('author_username', '?')})",
                    "inline": True,
                },
                {
                    "name": "Confidence",
                    "value": f"`{confidence_bar}` {confidence:.0%}",
                    "inline": True,
                },
                {
                    "name": "Sentiment",
                    "value": sentiment.capitalize(),
                    "inline": True,
                },
                {
                    "name": "Post",
                    "value": (tweet.get("post_text", "")[:900] or "No text"),
                    "inline": False,
                },
                {
                    "name": "AI Reason",
                    "value": decision.get("reason", "No reason provided"),
                    "inline": False,
                },
                {
                    "name": "Engagement",
                    "value": (
                        f"❤️ {tweet.get('likes', 0)}  "
                        f"🔁 {tweet.get('reposts', 0)}  "
                        f"💬 {tweet.get('replies', 0)}  "
                        f"👁️ {tweet.get('views', 0)}"
                    ),
                    "inline": False,
                },
                {
                    "name": "Link",
                    "value": tweet.get("post_url", "N/A"),
                    "inline": False,
                },
            ],
            "footer": {"text": f"XScrapperAI • {category}"},
        }

    async def send(
        self, tweet: dict[str, Any], decision: dict[str, Any], keyword: str = ""
    ) -> bool:
        tweet_id = tweet.get("tweet_id", "")
        if await self.db.is_webhook_sent(tweet_id):
            logger.debug("Webhook already sent for tweet %s, skipping", tweet_id)
            return False

        webhook_url = self.config.keyword_webhooks.get(keyword, self.config.discord_webhook)
        if not webhook_url:
            logger.warning("No webhook URL configured")
            return False

        embed = self._build_embed(tweet, decision)
        payload = {"embeds": [embed]}

        for attempt in range(self.config.max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(webhook_url, json=payload) as resp:
                        if resp.status == 204:
                            await self.db.mark_webhook_sent(tweet_id)
                            logger.info("Webhook sent for tweet %s", tweet_id)
                            return True
                        if resp.status == 429:
                            retry_after = (await resp.json()).get("retry_after", 5)
                            logger.warning("Rate limited, waiting %ss", retry_after)
                            await asyncio.sleep(retry_after)
                            continue
                        logger.warning("Webhook returned %d for tweet %s", resp.status, tweet_id)
            except Exception as e:
                logger.error("Webhook error (attempt %d): %s", attempt + 1, e)

            if attempt < self.config.max_retries - 1:
                await asyncio.sleep(self.config.retry_delay_seconds)

        return False

    async def send_batch(
        self,
        tweets: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
        keyword: str = "",
    ) -> int:
        sent_count = 0
        for decision in decisions:
            if not decision.get("worth_applying", False):
                continue
            idx = decision.get("_global_index", decision.get("post_index", -1))
            if idx < 0 or idx >= len(tweets):
                continue
            tweet = tweets[idx]
            success = await self.send(tweet, decision, keyword)
            if success:
                sent_count += 1
            await asyncio.sleep(1)
        return sent_count
