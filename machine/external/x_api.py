"""
X (Twitter) GraphQL API client — fetch tweets and user timelines.
Ported from fb-news skill.
"""

import json
import logging
import re
from datetime import datetime, timezone

import httpx

from core.exceptions.http import ExternalAPIException
from core.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Endpoints ────────────────────────────────────────────────────────────────

API_USER_TWEETS = "https://x.com/i/api/graphql/FOlovQsiHGDls3c0Q_HaSQ/UserTweets"
API_TWEET_DETAIL = "https://x.com/i/api/graphql/zy39CwTyYhU-_0LP7dljjg/TweetResultByRestId"
API_USER_BY_SCREEN_NAME = "https://x.com/i/api/graphql/xmU6X_CKVnQ5lSrCbAmJsg/UserByScreenName"

BEARER = (
    "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

FEAT_USER_TWEETS = {
    "rweb_video_screen_enabled": False,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "responsive_web_profile_redirect_enabled": False,
    "rweb_tipjar_consumption_enabled": False,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": True,
    "responsive_web_jetfuel_frame": True,
    "responsive_web_grok_share_attachment_enabled": True,
    "responsive_web_grok_annotations_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "content_disclosure_indicator_enabled": True,
    "content_disclosure_ai_generated_indicator_enabled": True,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": False,
    "responsive_web_grok_image_annotation_enabled": True,
    "responsive_web_grok_imagine_annotation_enabled": True,
    "responsive_web_grok_community_note_auto_translation_is_enabled": False,
    "responsive_web_enhance_cards_enabled": False,
}

FEAT_TWEET_DETAIL = {
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": True,
    "responsive_web_jetfuel_frame": True,
    "responsive_web_grok_share_attachment_enabled": True,
    "responsive_web_grok_annotations_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": False,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
    "verified_phone_label_enabled": False,
    "rweb_tipjar_consumption_enabled": False,
}

FEAT_USER_BY_SCREEN_NAME = {
    "hidden_profile_subscriptions_enabled": True,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "rweb_tipjar_consumption_enabled": False,
    "verified_phone_label_enabled": False,
    "subscriptions_verification_info_is_identity_verified_enabled": True,
    "subscriptions_verification_info_verified_since_enabled": True,
    "highlights_tweets_tab_ui_enabled": True,
    "responsive_web_twitter_article_notes_tab_enabled": True,
    "subscriptions_feature_can_gift_premium": True,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
}

FIELD_TOGGLES = {
    "withArticleRichContentState": True,
    "withArticlePlainText": False,
}


# ── Cookie parser ────────────────────────────────────────────────────────────

def parse_cookies(raw: str) -> dict:
    """Parse cookie string (semicolon-separated or JSON array) into dict."""
    raw = raw.strip()
    if not raw:
        return {}

    try:
        items = json.loads(raw)
        if isinstance(items, list):
            return {item["name"]: item["value"] for item in items if "name" in item}
    except Exception:
        pass

    cookies: dict = {}
    for part in raw.split(";"):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            cookies[k.strip()] = v.strip().strip('"')
    return cookies


# ── Helpers ──────────────────────────────────────────────────────────────────

def _headers(cookies: dict, referer: str = "https://x.com/") -> dict:
    return {
        "accept": "*/*",
        "accept-language": "vi-VN,vi;q=0.9,en-US;q=0.6,en;q=0.5",
        "authorization": BEARER,
        "content-type": "application/json",
        "referer": referer,
        "x-csrf-token": cookies.get("ct0", ""),
        "x-twitter-active-user": "yes",
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-client-language": "en",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/146.0.0.0 Safari/537.36"
        ),
    }


def _parse_time(created_at: str) -> str:
    try:
        dt = datetime.strptime(created_at, "%a %b %d %H:%M:%S +0000 %Y")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except Exception:
        return created_at


def _extract_media(extended_entities: dict | None) -> tuple[str, str, str, str]:
    if not extended_entities:
        return "none", "", "", ""

    for m in extended_entities.get("media", []):
        mtype = m.get("type", "")
        thumbnail = m.get("media_url_https", "")

        if mtype in ("video", "animated_gif"):
            variants = m.get("video_info", {}).get("variants", [])
            m3u8 = next(
                (v["url"] for v in variants if v.get("content_type") == "application/x-mpegURL"),
                None,
            )
            mp4s = [v for v in variants if v.get("content_type") == "video/mp4" and "bitrate" in v]
            best_mp4 = max(mp4s, key=lambda v: int(v["bitrate"]))["url"] if mp4s else ""
            media_src = m3u8 or best_mp4
            return "video", media_src, thumbnail, best_mp4

        if mtype == "photo":
            url = thumbnail + "?format=jpg&name=large"
            return "image", url, thumbnail, ""

    return "none", "", "", ""


def _parse_tweet_result(result: dict, post_url: str) -> dict:
    legacy = result["legacy"]
    user_result = result["core"]["user_results"]["result"]
    user_legacy = user_result["legacy"]
    user_core = user_result.get("core", {})
    views = result.get("views", {})

    try:
        view_count = int(views.get("count", 0))
    except Exception:
        view_count = 0

    media_type, media_src, media_poster, media_mp4 = _extract_media(legacy.get("extended_entities"))

    return {
        "username": user_core.get("screen_name", ""),
        "post_url": post_url,
        "text": legacy.get("full_text", ""),
        "lang": legacy.get("lang", ""),
        "datetime_utc": _parse_time(legacy.get("created_at", "")),
        "views": view_count,
        "likes": legacy.get("favorite_count", 0),
        "retweets": legacy.get("retweet_count", 0),
        "replies": legacy.get("reply_count", 0),
        "quotes": legacy.get("quote_count", 0),
        "bookmarks": legacy.get("bookmark_count", 0),
        "followers": user_legacy.get("followers_count", 0),
        "media_type": media_type,
        "media_src": media_src,
        "media_poster": media_poster,
        "media_mp4": media_mp4,
    }


# ── Public API ───────────────────────────────────────────────────────────────

class XService:
    """Handles fetching tweets from X (Twitter) via GraphQL API."""

    @staticmethod
    def _load_cookies() -> dict:
        if not settings.X_COOKIES:
            raise ExternalAPIException(detail="X_COOKIES not configured in .env")
        return parse_cookies(settings.X_COOKIES)

    @classmethod
    async def lookup_user(cls, username: str) -> dict:
        cookies = cls._load_cookies()
        clean = username.strip().lstrip("@")

        if clean.isdigit():
            return {"user_id": clean, "screen_name": None}

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                API_USER_BY_SCREEN_NAME,
                params={
                    "variables": json.dumps({"screen_name": clean, "withSafetyModeUserFields": True}),
                    "features": json.dumps(FEAT_USER_BY_SCREEN_NAME),
                    "fieldToggles": json.dumps({"withAuxiliaryUserLabels": False}),
                },
                headers=_headers(cookies, f"https://x.com/{clean}"),
                cookies=cookies,
                timeout=15,
            )

        if resp.status_code != 200:
            raise ExternalAPIException(detail=f"X API error: {resp.status_code}")

        data = resp.json()
        user_id = data.get("data", {}).get("user", {}).get("result", {}).get("rest_id")
        if not user_id:
            raise ExternalAPIException(detail=f"User @{clean} not found on X")

        return {"user_id": user_id, "screen_name": clean}

    @classmethod
    async def fetch_user_tweets(cls, username: str, count: int = 10) -> list[dict]:
        cookies = cls._load_cookies()
        user_info = await cls.lookup_user(username)
        user_id = user_info["user_id"]
        screen_name = user_info["screen_name"]
        sn = screen_name or user_id
        referer = f"https://x.com/{sn}" if screen_name else "https://x.com/"

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                API_USER_TWEETS,
                params={
                    "variables": json.dumps({
                        "userId": user_id,
                        "count": count,
                        "includePromotedContent": True,
                        "withQuickPromoteEligibilityTweetFields": True,
                        "withVoice": True,
                    }),
                    "features": json.dumps(FEAT_USER_TWEETS),
                    "fieldToggles": json.dumps({"withArticlePlainText": False}),
                },
                headers=_headers(cookies, referer),
                cookies=cookies,
                timeout=15,
            )

        if resp.status_code != 200:
            raise ExternalAPIException(detail=f"X API error: {resp.status_code}")

        tweets = []
        pinned_ids: set = set()

        try:
            instructions = (
                resp.json()["data"]["user"]["result"]["timeline"]["timeline"]["instructions"]
            )
            for instr in instructions:
                if instr.get("type") == "TimelinePinEntry":
                    pid = (
                        instr.get("entry", {})
                        .get("content", {})
                        .get("itemContent", {})
                        .get("tweet_results", {})
                        .get("result", {})
                        .get("legacy", {})
                        .get("id_str")
                    )
                    if pid:
                        pinned_ids.add(pid)
                    continue

                for entry in instr.get("entries", []):
                    item = entry.get("content", {}).get("itemContent", {})
                    if item.get("itemType") != "TimelineTweet":
                        continue
                    res = item.get("tweet_results", {}).get("result", {})
                    if res.get("__typename") != "Tweet":
                        continue
                    tid = res.get("legacy", {}).get("id_str")
                    if not tid or tid in pinned_ids:
                        continue

                    author_sn = (
                        res.get("core", {})
                        .get("user_results", {})
                        .get("result", {})
                        .get("core", {})
                        .get("screen_name", sn)
                    )
                    post_url = f"https://x.com/{author_sn}/status/{tid}"

                    try:
                        tweets.append(_parse_tweet_result(res, post_url))
                    except Exception:
                        pass
        except Exception as e:
            logger.error("Parse UserTweets error: %s", e)

        return tweets

    @classmethod
    async def fetch_tweet(cls, post_url: str) -> dict:
        cookies = cls._load_cookies()
        match = re.search(r"/status/(\d+)", post_url)
        if not match:
            raise ExternalAPIException(detail=f"Invalid tweet URL: {post_url}")

        tweet_id = match.group(1)

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                API_TWEET_DETAIL,
                params={
                    "variables": json.dumps({
                        "tweetId": tweet_id,
                        "includePromotedContent": True,
                        "withBirdwatchNotes": True,
                        "withVoice": True,
                        "withCommunity": True,
                    }),
                    "features": json.dumps(FEAT_TWEET_DETAIL),
                    "fieldToggles": json.dumps(FIELD_TOGGLES),
                },
                headers=_headers(cookies, post_url),
                cookies=cookies,
                timeout=15,
            )

        if resp.status_code != 200:
            raise ExternalAPIException(detail=f"X API error: {resp.status_code}")

        try:
            result = resp.json()["data"]["tweetResult"]["result"]
            return _parse_tweet_result(result, post_url)
        except Exception as e:
            raise ExternalAPIException(detail=f"Failed to parse tweet: {e}")
