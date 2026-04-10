"""
Douyin trending video scraper — async version using httpx.
Ported from douyin-trending skill.
"""

import asyncio
import json
import logging
import re
import ssl
from datetime import datetime, timezone

import httpx

from core.exceptions.http import ExternalAPIException
from core.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Constants ────────────────────────────────────────────────────────────────

FEED_URL = "https://www.douyin.com/aweme/v1/web/tab/feed/"
HOT_SEARCH_URL = "https://www.douyin.com/aweme/v1/web/hot/search/list/"

HEADERS_BASE = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.douyin.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_cookie(raw: str) -> str:
    """Parse Netscape cookie file or raw cookie string."""
    raw = raw.strip()
    if not raw:
        return ""
    # If it contains tabs, it's Netscape format
    if "\t" in raw:
        pairs = []
        for line in raw.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 7 and parts[5]:
                pairs.append(f"{parts[5]}={parts[6]}")
        return "; ".join(pairs)
    return raw


def _extract_video_url(video: dict) -> str:
    """Extract best quality video URL from aweme.video."""
    for key in ["play_addr_h264", "play_addr", "play_addr_265"]:
        obj = video.get(key) or {}
        urls = obj.get("url_list") or []
        if not urls:
            continue
        for u in urls:
            if "douyin.com/aweme/v1/play" in u:
                return u
        return urls[0]
    for br in (video.get("bit_rate") or []):
        urls = (br.get("play_addr") or {}).get("url_list") or []
        if not urls:
            continue
        for u in urls:
            if "douyin.com/aweme/v1/play" in u:
                return u
        return urls[0]
    return ""


def _parse_aweme(aweme: dict) -> dict | None:
    """Transform raw aweme JSON into structured video dict."""
    aweme_id = aweme.get("aweme_id") or aweme.get("id")
    if not aweme_id:
        return None

    stats = aweme.get("statistics") or {}
    author = aweme.get("author") or {}
    video = aweme.get("video") or {}

    cover = ""
    for ck in ["cover", "origin_cover"]:
        urls = (video.get(ck) or {}).get("url_list") or []
        if urls:
            cover = urls[0]
            break

    create_time = aweme.get("create_time")
    created_at = ""
    if create_time:
        try:
            created_at = datetime.fromtimestamp(
                int(create_time), tz=timezone.utc
            ).isoformat()
        except Exception:
            pass

    return {
        "aweme_id": aweme_id,
        "desc": (aweme.get("desc") or "").strip(),
        "created_at": created_at,
        "nickname": author.get("nickname") or "",
        "digg_count": stats.get("digg_count") or 0,
        "comment_count": stats.get("comment_count") or 0,
        "share_count": stats.get("share_count") or 0,
        "collect_count": stats.get("collect_count") or 0,
        "cover": cover,
        "video_url": _extract_video_url(video),
        "douyin_url": f"https://www.douyin.com/video/{aweme_id}",
    }


def _score(v: dict) -> float:
    return (
        v["digg_count"] * 5.0
        + v["comment_count"] * 3.0
        + v["share_count"] * 10.0
        + v["collect_count"] * 8.0
    )


# ── Public API ───────────────────────────────────────────────────────────────

class DouyinService:
    """Fetches trending videos and hot keywords from Douyin."""

    @staticmethod
    def _get_cookie() -> str:
        cookie = _parse_cookie(settings.DOUYIN_COOKIES)
        if not cookie:
            raise ExternalAPIException(detail="DOUYIN_COOKIES not configured in .env")
        return cookie

    @staticmethod
    def _make_client(cookie: str) -> httpx.AsyncClient:
        headers = {**HEADERS_BASE, "Cookie": cookie}
        # Disable SSL verification (Douyin CDN issues)
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        return httpx.AsyncClient(headers=headers, verify=ssl_ctx, timeout=15)

    @classmethod
    async def _fetch_feed_page(
        cls, client: httpx.AsyncClient, page: int
    ) -> list[dict]:
        try:
            resp = await client.get(
                FEED_URL,
                params={
                    "device_platform": "webapp",
                    "aid": "6383",
                    "count": "10",
                    "max_cursor": str(page * 10),
                    "pull_type": "0" if page == 0 else "2",
                },
            )
            if resp.status_code != 200:
                logger.warning("Douyin feed page %d: HTTP %d", page, resp.status_code)
                return []
            data = resp.json()
            return data.get("aweme_list") or []
        except Exception as e:
            logger.warning("Douyin feed page %d error: %s", page, e)
            return []

    @classmethod
    async def fetch_trending(cls, pages: int = 5, top: int = 10) -> list[dict]:
        """Fetch trending videos, ranked by engagement score.

        Args:
            pages: Number of feed pages to fetch (each ~10 videos). Max 20.
            top: Number of top videos to return. Max 50.
        """
        pages = min(pages, 20)
        top = min(top, 50)
        cookie = cls._get_cookie()

        async with cls._make_client(cookie) as client:
            all_raw: list[dict] = []
            for page in range(pages):
                items = await cls._fetch_feed_page(client, page)
                all_raw.extend(items)
                if page < pages - 1:
                    await asyncio.sleep(0.35)

        # Parse + dedup + rank
        seen: set[str] = set()
        videos: list[dict] = []
        for item in all_raw:
            p = _parse_aweme(item)
            if p and p["aweme_id"] not in seen:
                seen.add(p["aweme_id"])
                p["score"] = int(_score(p))
                videos.append(p)

        videos.sort(key=lambda v: v["score"], reverse=True)
        return videos[:top]

    @classmethod
    async def fetch_hot_keywords(cls) -> list[str]:
        """Fetch current hot search keywords from Douyin."""
        cookie = cls._get_cookie()

        async with cls._make_client(cookie) as client:
            try:
                resp = await client.get(
                    HOT_SEARCH_URL,
                    params={
                        "device_platform": "webapp",
                        "aid": "6383",
                        "source": "6",
                        "detail_list": "1",
                    },
                )
                if resp.status_code != 200:
                    return []
                data = resp.json()
                word_list = (data.get("data") or {}).get("word_list") or []
                return [
                    item.get("word", "")
                    for item in word_list
                    if item.get("word")
                ][:20]
            except Exception as e:
                logger.warning("Douyin hot keywords error: %s", e)
                return []
