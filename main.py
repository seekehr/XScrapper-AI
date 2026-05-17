"""XScrapperAI — Monitor X.com for leads, filter with Gemini, notify via Discord."""

from __future__ import annotations

import asyncio
import signal
import sys
from typing import Any

from ai.gemini_filter import GeminiFilter
from discord.webhook import DiscordWebhook
from scraper.twitter_scraper import TwitterScraper
from utils.config import Config
from utils.csv_export import CSVExporter
from utils.database import Database
from utils.logger import setup_logger

logger = setup_logger("xscrapper")


class XScrapperAI:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.db = Database(config.db_path)
        self.scraper = TwitterScraper(config, self.db)
        self.ai = GeminiFilter(config)
        self.webhook = DiscordWebhook(config, self.db)
        self.csv = CSVExporter(config.csv_export_path)
        self._running = True

    async def run_cycle(self) -> None:
        logger.info("=== Starting scrape cycle ===")

        tweets = await self.scraper.scrape_all_keywords()
        if not tweets:
            logger.info("No new tweets found this cycle")
            return

        tweet_dicts = [t.to_dict() for t in tweets]
        logger.info("Analyzing %d tweets with Gemini...", len(tweet_dicts))

        decisions = await self.ai.analyze_all(tweet_dicts)
        logger.info("Received %d AI decisions", len(decisions))

        worth_count = 0
        for decision in decisions:
            idx = decision.get("_global_index", decision.get("post_index", -1))
            if 0 <= idx < len(tweet_dicts):
                await self.db.save_ai_decision(tweet_dicts[idx]["tweet_id"], decision)
                if decision.get("worth_applying", False):
                    worth_count += 1
                    self.csv.export(tweet_dicts[idx], decision)

        logger.info("Found %d worth-applying leads out of %d tweets", worth_count, len(tweets))

        sent = await self.webhook.send_batch(tweet_dicts, decisions)
        logger.info("Sent %d Discord notifications", sent)

        stats = await self.db.get_stats()
        logger.info(
            "Stats — processed: %d, decisions: %d, webhooks: %d",
            stats.get("processed_tweets", 0),
            stats.get("ai_decisions", 0),
            stats.get("webhook_sent", 0),
        )

    async def run(self) -> None:
        self.ai.load_system_prompt()
        await self.db.connect()
        await self.scraper.start()

        try:
            while self._running:
                try:
                    await self.run_cycle()
                except Exception as e:
                    logger.error("Cycle error: %s", e, exc_info=True)

                if not self._running:
                    break
                logger.info("Sleeping %ds until next cycle...", self.config.poll_interval_seconds)
                await asyncio.sleep(self.config.poll_interval_seconds)
        finally:
            await self.scraper.stop()
            await self.db.close()
            logger.info("XScrapperAI shut down")

    def stop(self) -> None:
        self._running = False


async def main() -> None:
    config = Config.load("settings.json")

    warnings = config.validate()
    if warnings:
        for w in warnings:
            logger.warning("Config: %s", w)
        if any("required" in w for w in warnings):
            logger.error("Fix required config errors before running")
            sys.exit(1)

    app = XScrapperAI(config)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, app.stop)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
