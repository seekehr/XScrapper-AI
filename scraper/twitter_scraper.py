from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote_plus

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from utils.config import Config
from utils.database import Database
from utils.logger import setup_logger

logger = setup_logger("xscrapper.scraper")


@dataclass
class Tweet:
    tweet_id: str = ""
    post_text: str = ""
    author_username: str = ""
    author_display_name: str = ""
    post_url: str = ""
    timestamp: str = ""
    likes: int = 0
    reposts: int = 0
    replies: int = 0
    views: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tweet_id": self.tweet_id,
            "post_text": self.post_text,
            "author_username": self.author_username,
            "author_display_name": self.author_display_name,
            "post_url": self.post_url,
            "timestamp": self.timestamp,
            "likes": self.likes,
            "reposts": self.reposts,
            "replies": self.replies,
            "views": self.views,
        }


def _parse_metric(text: str) -> int:
    """Parse engagement metrics like '1.2K', '3M', '450'."""
    if not text:
        return 0
    text = text.strip().replace(",", "")
    multipliers = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    for suffix, mult in multipliers.items():
        if text.upper().endswith(suffix):
            try:
                return int(float(text[:-1]) * mult)
            except ValueError:
                return 0
    try:
        return int(text)
    except ValueError:
        return 0


class TwitterScraper:
    def __init__(self, config: Config, db: Database) -> None:
        self.config = config
        self.db = db
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._proxy_index = 0

    def _next_proxy(self) -> dict[str, str] | None:
        if not self.config.proxy_list:
            return None
        proxy_url = self.config.proxy_list[self._proxy_index % len(self.config.proxy_list)]
        self._proxy_index += 1
        return {"server": proxy_url}

    async def start(self) -> None:
        pw = await async_playwright().start()
        launch_args: dict[str, Any] = {"headless": self.config.headless}
        proxy = self._next_proxy()
        if proxy:
            launch_args["proxy"] = proxy
        self._browser = await pw.chromium.launch(**launch_args)
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        if self.config.x_auth_token:
            await self._context.add_cookies([
                {
                    "name": "auth_token",
                    "value": self.config.x_auth_token,
                    "domain": ".x.com",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "None",
                },
            ])
        logger.info("Browser started (headless=%s)", self.config.headless)

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
            self._context = None
        logger.info("Browser stopped")

    async def _human_delay(self, low: float = 1.0, high: float = 3.0) -> None:
        await asyncio.sleep(random.uniform(low, high))

    async def scrape_keyword(self, keyword: str) -> list[Tweet]:
        assert self._context is not None
        page = await self._context.new_page()
        tweets: list[Tweet] = []
        try:
            encoded = quote_plus(keyword)
            url = f"https://x.com/search?q={encoded}&src=typed_query&f=live"
            logger.info("Scraping keyword: '%s'", keyword)

            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await self._human_delay(2.0, 4.0)

            # Wait for tweets to render
            try:
                await page.wait_for_selector('article[data-testid="tweet"]', timeout=15_000)
            except Exception:
                logger.warning("No tweets found for keyword '%s', page may require login", keyword)
                return tweets

            seen_ids: set[str] = set()
            scroll_attempts = 0
            max_scrolls = self.config.scrape_limit_per_keyword // 3 + 5

            while len(tweets) < self.config.scrape_limit_per_keyword and scroll_attempts < max_scrolls:
                articles = await page.query_selector_all('article[data-testid="tweet"]')

                for article in articles:
                    if len(tweets) >= self.config.scrape_limit_per_keyword:
                        break
                    tweet = await self._extract_tweet(article, page)
                    if not tweet or not tweet.tweet_id:
                        continue
                    if tweet.tweet_id in seen_ids:
                        continue
                    if await self.db.is_tweet_processed(tweet.tweet_id):
                        continue
                    if tweet.likes < self.config.minimum_post_likes:
                        continue
                    if tweet.views < self.config.minimum_post_views:
                        continue
                    seen_ids.add(tweet.tweet_id)
                    tweets.append(tweet)

                await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
                await self._human_delay(1.5, 3.5)
                scroll_attempts += 1

            logger.info("Scraped %d tweets for keyword '%s'", len(tweets), keyword)
        except Exception as e:
            logger.error("Error scraping keyword '%s': %s", keyword, e)
        finally:
            await page.close()

        return tweets

    async def _extract_tweet(self, article: Any, page: Page) -> Tweet | None:
        try:
            tweet = Tweet()

            # Extract tweet link to get ID and username
            links = await article.query_selector_all('a[href*="/status/"]')
            for link in links:
                href = await link.get_attribute("href")
                if href and "/status/" in href:
                    match = re.search(r"/([^/]+)/status/(\d+)", href)
                    if match:
                        tweet.author_username = match.group(1)
                        tweet.tweet_id = match.group(2)
                        tweet.post_url = f"https://x.com{href}"
                        break

            if not tweet.tweet_id:
                return None

            # Display name
            display_el = await article.query_selector('div[data-testid="User-Name"] a span')
            if display_el:
                tweet.author_display_name = (await display_el.inner_text()).strip()

            # Tweet text
            text_el = await article.query_selector('div[data-testid="tweetText"]')
            if text_el:
                tweet.post_text = (await text_el.inner_text()).strip()

            # Timestamp
            time_el = await article.query_selector("time")
            if time_el:
                tweet.timestamp = await time_el.get_attribute("datetime") or ""

            # Engagement metrics
            groups = await article.query_selector_all('div[role="group"] button')
            metric_values: list[int] = []
            for btn in groups:
                aria = await btn.get_attribute("aria-label") or ""
                nums = re.findall(r"[\d,.]+[KMB]?", aria)
                metric_values.append(_parse_metric(nums[0]) if nums else 0)

            if len(metric_values) >= 1:
                tweet.replies = metric_values[0]
            if len(metric_values) >= 2:
                tweet.reposts = metric_values[1]
            if len(metric_values) >= 3:
                tweet.likes = metric_values[2]
            if len(metric_values) >= 4:
                tweet.views = metric_values[3]

            return tweet
        except Exception as e:
            logger.debug("Failed to extract tweet: %s", e)
            return None

    async def scrape_all_keywords(self) -> list[Tweet]:
        all_tweets: list[Tweet] = []
        for keyword in self.config.keywords:
            tweets = await self.scrape_keyword(keyword)
            for t in tweets:
                await self.db.mark_tweet_processed(t.tweet_id, keyword)
            all_tweets.extend(tweets)
            await self._human_delay(3.0, 7.0)
        logger.info("Total tweets scraped across all keywords: %d", len(all_tweets))
        return all_tweets
