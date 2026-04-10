from core.exceptions.http import BadRequestException
from machine.external.douyin import DouyinService
from machine.external.grok import GrokService
from machine.external.x_api import XService


class ContentController:
    """Handles fetching X tweets, Douyin videos, and rewriting with Grok LLM."""

    # ── Douyin ───────────────────────────────────────────────────────────

    @staticmethod
    async def fetch_douyin_trending(pages: int = 5, top: int = 10) -> list[dict]:
        return await DouyinService.fetch_trending(pages=pages, top=top)

    @staticmethod
    async def fetch_douyin_hot_keywords() -> dict:
        keywords = await DouyinService.fetch_hot_keywords()
        return {"keywords": keywords}

    # ── X/Twitter ────────────────────────────────────────────────────────

    @staticmethod
    async def fetch_tweet(url: str) -> dict:
        return await XService.fetch_tweet(url)

    @staticmethod
    async def fetch_user_tweets(username: str, count: int = 10) -> list[dict]:
        return await XService.fetch_user_tweets(username, count)

    @staticmethod
    async def rewrite(
        tweet_url: str | None = None,
        tweet_text: str | None = None,
        custom_prompt: str | None = None,
    ) -> dict:
        if not tweet_url and not tweet_text:
            raise BadRequestException(detail="Provide either tweet_url or tweet_text")

        original_text = tweet_text or ""

        if tweet_url:
            tweet = await XService.fetch_tweet(tweet_url)
            original_text = tweet["text"]

        if custom_prompt:
            rewritten = await GrokService.rewrite_custom(original_text, custom_prompt)
        else:
            rewritten = await GrokService.rewrite_for_facebook(original_text, tweet_url or "")

        return {
            "original_text": original_text,
            "rewritten_text": rewritten,
            "tweet_url": tweet_url,
        }
