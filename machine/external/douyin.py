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
from machine.external.abogus import ABogus

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Constants ────────────────────────────────────────────────────────────────

FEED_URL = "https://www.douyin.com/aweme/v1/web/tab/feed/"
USER_POST_URL = "https://www.douyin.com/aweme/v1/web/aweme/post/"
HOT_SEARCH_URL = "https://www.douyin.com/aweme/v1/web/hot/search/list/"
VIDEO_DETAIL_URL = "https://www.douyin.com/aweme/v1/web/aweme/detail/"

# Regex patterns to extract aweme_id from various Douyin URL formats
_AWEME_ID_PATTERNS = [
    re.compile(r"video/([^/?]+)"),       # douyin.com/video/7372484719365098803
    re.compile(r"[?&]vid=(\d+)"),        # douyin.com/user/xxx?vid=7285950278132616463
    re.compile(r"note/([^/?]+)"),        # douyin.com/note/xxx (image posts)
    re.compile(r"modal_id=(\d+)"),       # douyin.com/discover?modal_id=xxx
]

_UA_GENERAL = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
# A-Bogus ua_code is hardcoded for Chrome/90 — detail API must use this UA
_UA_ABOGUS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/90.0.4430.212 Safari/537.36"
)

HEADERS_BASE = {
    "User-Agent": _UA_GENERAL,
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
    async def fetch_trending(
        cls, pages: int = 5, top: int = 10, keyword: str | None = None
    ) -> list[dict]:
        """Fetch trending videos, ranked by engagement score.

        Args:
            pages: Number of feed pages to fetch (each ~2 videos). Max 20.
            top: Number of top videos to return. Max 50.
            keyword: Optional filter — only return videos matching keyword in desc or nickname.
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

        # Optional keyword filter
        if keyword:
            kw_lower = keyword.lower()
            videos = [
                v for v in videos
                if kw_lower in v["desc"].lower() or kw_lower in v["nickname"].lower()
            ]

        videos.sort(key=lambda v: v["score"], reverse=True)
        return videos[:top]

    @classmethod
    async def fetch_user_videos(
        cls, sec_user_id: str, count: int = 10
    ) -> list[dict]:
        """Fetch videos from a specific Douyin user.

        Args:
            sec_user_id: The sec_uid from the user's profile URL.
            count: Number of videos to return (max 30).
        """
        count = min(count, 30)
        cookie = cls._get_cookie()

        params = {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "sec_user_id": sec_user_id,
            "max_cursor": "0",
            "locate_query": "false",
            "show_live_replay_strategy": "1",
            "need_time_list": "1",
            "time_list_query": "0",
            "whale_cut_token": "",
            "cut_version": "1",
            "count": str(count),
            "publish_video_strategy_type": "2",
            "version_code": "170400",
            "version_name": "17.4.0",
            "cookie_enabled": "true",
            "screen_width": "1920",
            "screen_height": "1080",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "browser_version": "131.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "engine_version": "131.0.0.0",
            "os_name": "Windows",
            "os_version": "10",
            "cpu_core_num": "12",
            "device_memory": "8",
            "platform": "PC",
            "downlink": "10",
            "effective_type": "4g",
            "round_trip_time": "50",
            "msToken": "",
        }

        a_bogus = ABogus.generate(params)
        query = "&".join(f"{k}={v}" for k, v in params.items())
        full_url = f"{USER_POST_URL}?{query}&a_bogus={a_bogus}"

        headers = {**HEADERS_BASE, "Cookie": cookie, "User-Agent": _UA_ABOGUS}
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        async with httpx.AsyncClient(headers=headers, verify=ssl_ctx, timeout=15) as client:
            try:
                resp = await client.get(full_url)
                if resp.status_code != 200:
                    raise ExternalAPIException(
                        detail=f"Douyin user posts error: HTTP {resp.status_code}"
                    )
                data = resp.json()
            except ExternalAPIException:
                raise
            except Exception as e:
                raise ExternalAPIException(detail=f"Douyin user posts error: {e}")

        raw_list = data.get("aweme_list") or []
        seen: set[str] = set()
        videos: list[dict] = []
        for item in raw_list:
            p = _parse_aweme(item)
            if p and p["aweme_id"] not in seen:
                seen.add(p["aweme_id"])
                p["score"] = 0
                videos.append(p)

        # API already returns newest first — keep that order
        return videos[:count]

    @classmethod
    async def fetch_multi_user_videos(
        cls,
        sec_user_ids: list[str],
        count_per_user: int = 5,
        top: int = 10,
        keyword: str | None = None,
    ) -> list[dict]:
        """Fetch latest videos from multiple users, sorted by newest first."""
        import asyncio

        tasks = [
            cls.fetch_user_videos(uid, count=count_per_user)
            for uid in sec_user_ids
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        seen: set[str] = set()
        all_videos: list[dict] = []
        for r in results:
            if isinstance(r, Exception):
                logger.warning("Failed to fetch user videos: %s", r)
                continue
            for v in r:
                if v["aweme_id"] not in seen:
                    seen.add(v["aweme_id"])
                    all_videos.append(v)

        if keyword:
            kw_lower = keyword.lower()
            all_videos = [
                v for v in all_videos
                if kw_lower in v["desc"].lower() or kw_lower in v["nickname"].lower()
            ]

        # Sort by created_at descending (newest first)
        all_videos.sort(key=lambda v: v["created_at"], reverse=True)
        return all_videos[:top]

    @classmethod
    async def _resolve_aweme_id(cls, url: str) -> str:
        """Resolve a Douyin URL (short or full) to an aweme_id."""
        cookie = cls._get_cookie()
        async with cls._make_client(cookie) as client:
            try:
                resp = await client.get(url, follow_redirects=True)
                final_url = str(resp.url)
            except Exception as e:
                raise ExternalAPIException(detail=f"Failed to resolve Douyin URL: {e}")

        for pattern in _AWEME_ID_PATTERNS:
            m = pattern.search(final_url)
            if m:
                return m.group(1)

        raise ExternalAPIException(
            detail=f"Could not extract aweme_id from URL: {final_url}"
        )

    @classmethod
    async def fetch_video_detail(cls, url: str) -> dict:
        """Fetch detailed info for a single Douyin video by URL.

        Supports short links (v.douyin.com/xxx) and full links
        (douyin.com/video/xxx, douyin.com/note/xxx, etc.).
        """
        aweme_id = await cls._resolve_aweme_id(url)
        cookie = cls._get_cookie()

        params = {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "aweme_id": aweme_id,
            "version_code": "290100",
            "version_name": "29.1.0",
            "cookie_enabled": "true",
            "screen_width": "1920",
            "screen_height": "1080",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "browser_version": "90.0.4430.212",
            "browser_online": "true",
            "engine_name": "Blink",
            "engine_version": "90.0.4430.212",
            "os_name": "Windows",
            "os_version": "10",
            "cpu_core_num": "12",
            "device_memory": "8",
            "platform": "PC",
            "downlink": "10",
            "effective_type": "4g",
            "round_trip_time": "50",
            "msToken": "",
        }

        a_bogus = ABogus.generate(params)
        query = "&".join(f"{k}={v}" for k, v in params.items())
        full_url = f"{VIDEO_DETAIL_URL}?{query}&a_bogus={a_bogus}"

        headers = {**HEADERS_BASE, "Cookie": cookie, "User-Agent": _UA_ABOGUS}
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        async with httpx.AsyncClient(headers=headers, verify=ssl_ctx, timeout=15) as client:
            try:
                resp = await client.get(full_url)
                if resp.status_code != 200:
                    raise ExternalAPIException(
                        detail=f"Douyin video detail error: HTTP {resp.status_code}"
                    )
                data = resp.json()
            except ExternalAPIException:
                raise
            except Exception as e:
                raise ExternalAPIException(detail=f"Douyin video detail error: {e}")

        aweme = data.get("aweme_detail")
        if not aweme:
            raise ExternalAPIException(detail="Video not found or unavailable")

        parsed = _parse_aweme(aweme)
        if not parsed:
            raise ExternalAPIException(detail="Failed to parse video data")

        parsed["score"] = int(_score(parsed))
        return parsed

    @classmethod
    async def download_video(
        cls, url: str, segment_duration: int = 5, max_segments: int = 5,
    ) -> dict:
        """Download a Douyin video by URL and split into short segments.

        Creates a new session folder for this download.
        """
        from machine.external.video_processor import download_and_split
        import uuid

        detail = await cls.fetch_video_detail(url)
        video_url = detail.get("video_url", "")
        if not video_url:
            raise ExternalAPIException(detail="No downloadable video URL found")

        cookie = cls._get_cookie()
        filename = detail.get("desc") or detail.get("aweme_id", "video")
        session_id = uuid.uuid4().hex[:12]

        result = await download_and_split(
            video_url=video_url,
            filename=filename,
            cookie=cookie,
            segment_duration=segment_duration,
            max_segments=max_segments,
            session_id=session_id,
        )
        result["video_info"] = detail
        return result

    @classmethod
    async def search_videos(
        cls, keyword: str, count: int = 10, offset: int = 0
    ) -> list[dict]:
        """Search Douyin videos by keyword.

        Args:
            keyword: Search query string.
            count: Number of results (max 20).
            offset: Pagination offset.
        """
        count = min(count, 20)
        cookie = cls._get_cookie()

        params = {
            "keyword": keyword,
            "count": str(count),
            "offset": str(offset),
            "search_id": "",
            "channel": "channel_pc_web",
            "search_source": "normal_search",
            "query_correct_type": "1",
            "is_filter_search": "0",
            "device_platform": "webapp",
            "aid": "6383",
            "version_code": "290100",
            "version_name": "29.1.0",
            "cookie_enabled": "true",
            "screen_width": "1920",
            "screen_height": "1080",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "browser_version": "90.0.4430.212",
            "browser_online": "true",
            "engine_name": "Blink",
            "engine_version": "90.0.4430.212",
            "os_name": "Windows",
            "os_version": "10",
            "cpu_core_num": "12",
            "device_memory": "8",
            "platform": "PC",
            "downlink": "10",
            "effective_type": "4g",
            "round_trip_time": "50",
            "msToken": "",
        }

        a_bogus = ABogus.generate(params)
        query = "&".join(f"{k}={v}" for k, v in params.items())
        search_url = "https://www.douyin.com/aweme/v1/web/search/item/"
        full_url = f"{search_url}?{query}&a_bogus={a_bogus}"

        headers = {**HEADERS_BASE, "Cookie": cookie, "User-Agent": _UA_ABOGUS}
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        async with httpx.AsyncClient(headers=headers, verify=ssl_ctx, timeout=15) as client:
            try:
                resp = await client.get(full_url)
                if resp.status_code != 200:
                    raise ExternalAPIException(
                        detail=f"Douyin search error: HTTP {resp.status_code}"
                    )
                data = resp.json()
            except ExternalAPIException:
                raise
            except Exception as e:
                raise ExternalAPIException(detail=f"Douyin search error: {e}")

        # Douyin may require captcha verification for search
        nil_info = data.get("search_nil_info") or {}
        if nil_info.get("search_nil_type") == "verify_check":
            raise ExternalAPIException(
                detail="Douyin search requires captcha verification. "
                "Please update DOUYIN_COOKIES with a fresh session cookie "
                "from a browser where you have completed a search."
            )

        raw_list = data.get("aweme_list") or data.get("data") or []
        seen: set[str] = set()
        videos: list[dict] = []
        for item in raw_list:
            aweme = item.get("aweme_info") or item
            p = _parse_aweme(aweme)
            if p and p["aweme_id"] not in seen:
                seen.add(p["aweme_id"])
                p["score"] = int(_score(p))
                videos.append(p)

        return videos[:count]

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
