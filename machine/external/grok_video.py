"""
Grok Video Generation — Python port of grokApi.js.

Generates videos via grok.com web API (unofficial, cookie-based session).
Supports: text-to-video, optional upscale to HD.
"""

import asyncio
import json
import logging
import os
import re
import ssl
from base64 import b64encode
from pathlib import Path
from random import choice
from uuid import uuid4

import httpx

from core.exceptions.http import ExternalAPIException
from core.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

DOWNLOADS_DIR = Path("downloads")

# ── Statsig ID generator ────────────────────────────────────────────────────

_STATSIG_ERRORS = [
    "Cannot read properties of undefined (reading 'childNodes')",
    "Cannot read properties of null (reading 'stableID')",
    "Cannot read properties of undefined (reading 'stableID')",
    "Cannot set properties of undefined (setting 'stableID')",
    "Cannot read properties of null (reading 'childNodes')",
    "Cannot read properties of undefined (reading 'getItem')",
    "Cannot read properties of null (reading 'getItem')",
]


def _generate_statsig_id() -> str:
    msg = choice(_STATSIG_ERRORS)
    return b64encode(f"e:TypeError: {msg}".encode()).decode()


# ── JSON stream parser ───────────────────────────────────────────────────────

def _parse_json_at(text: str, start: int) -> tuple[dict, int]:
    """Parse a single JSON object starting at position `start`.
    Returns (value, end_position)."""
    depth = 0
    in_string = False
    escape = False
    obj_start = start

    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\" and in_string:
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c in ("{", "["):
            if depth == 0:
                obj_start = i
            depth += 1
        elif c in ("}", "]"):
            depth -= 1
            if depth == 0:
                value = json.loads(text[obj_start : i + 1])
                return value, i + 1

    raise ValueError("Incomplete JSON")


# ── GrokVideoService ─────────────────────────────────────────────────────────

class GrokVideoService:
    """Generates videos using Grok's web API (grok.com)."""

    BASE_URL = "https://grok.com"

    @classmethod
    def _get_config(cls) -> tuple[str, str]:
        """Return (cookies, user_agent) from settings."""
        s = get_settings()
        cookies = s.GROK_COOKIES.strip()
        if not cookies:
            raise ExternalAPIException(detail="GROK_COOKIES not configured in .env")
        ua = s.GROK_USER_AGENT.strip()
        if not ua:
            raise ExternalAPIException(detail="GROK_USER_AGENT not configured in .env")
        return cookies, ua

    @classmethod
    def _make_headers(
        cls, cookies: str, user_agent: str, statsig_id: str, req_id: str,
        referer: str | None = None,
    ) -> dict:
        return {
            "Origin": "https://grok.com",
            "Referer": referer or "https://grok.com/imagine",
            "Content-Type": "application/json",
            "Accept": "*/*",
            "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "User-Agent": user_agent,
            "Cookie": cookies,
            "x-statsig-id": statsig_id,
            "x-xai-request-id": req_id,
        }

    @classmethod
    def _make_client(cls) -> httpx.AsyncClient:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        return httpx.AsyncClient(verify=ssl_ctx, timeout=180)

    @classmethod
    async def _request(
        cls, method: str, endpoint: str, payload: dict | None,
        cookies: str, user_agent: str, statsig_id: str,
        referer: str | None = None, retries: int = 3,
    ) -> httpx.Response | None:
        url = f"{cls.BASE_URL}{endpoint}"
        req_id = str(uuid4())
        headers = cls._make_headers(cookies, user_agent, statsig_id, req_id, referer)

        async with cls._make_client() as client:
            for attempt in range(1, retries + 1):
                try:
                    resp = await client.request(
                        method, url, headers=headers,
                        content=json.dumps(payload) if payload else None,
                    )
                    if resp.status_code == 429:
                        raise ExternalAPIException(
                            detail="Grok account out of credits (429). Try again later."
                        )
                    if resp.status_code != 200:
                        logger.warning(
                            "Grok %s %d: %s", endpoint, resp.status_code,
                            resp.text[:300],
                        )
                        if resp.status_code == 403:
                            raise ExternalAPIException(
                                detail="Grok 403 — cookies or session expired. Update GROK_COOKIES."
                            )
                        return None
                    return resp
                except ExternalAPIException:
                    raise
                except Exception as e:
                    logger.warning("Grok request error (attempt %d/%d): %s", attempt, retries, e)
                    if attempt < retries:
                        await asyncio.sleep(5)

        return None

    UPLOAD_URL = "https://grok.com/rest/app-chat/upload-file"

    @classmethod
    async def _upload_image(cls, image_path: str, cookies: str, user_agent: str) -> str:
        """Upload a local image to Grok. Returns fileMetadataId."""
        with open(image_path, "rb") as f:
            b64 = b64encode(f.read()).decode()

        filename = image_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
        mime = "image/png" if ext == "png" else "image/jpeg"
        payload = {"fileName": filename, "fileMimeType": mime, "content": b64}

        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        req_id = str(uuid4())
        headers = cls._make_headers(cookies, user_agent, _generate_statsig_id(), req_id)
        headers["Referer"] = "https://grok.com/"

        async with httpx.AsyncClient(verify=ssl_ctx, timeout=60) as client:
            resp = await client.post(
                cls.UPLOAD_URL, headers=headers, content=json.dumps(payload),
            )
        if resp.status_code != 200:
            raise ExternalAPIException(detail=f"Grok image upload failed: HTTP {resp.status_code}")
        data = resp.json()
        file_id = data.get("fileMetadataId") or data.get("id") or data.get("fileId")
        if not file_id:
            raise ExternalAPIException(detail=f"No fileMetadataId in Grok upload response: {data}")
        logger.info("Uploaded KOL image to Grok: %s", file_id)
        return file_id

    # ── Core API calls ────────────────────────────────────────────────────

    @classmethod
    async def _create_media_post(
        cls, prompt: str, cookies: str, user_agent: str, statsig_id: str,
        media_type: str = "MEDIA_POST_TYPE_VIDEO",
    ) -> str:
        """Create a media post, return post ID."""
        payload = {"mediaType": media_type, "prompt": prompt}
        resp = await cls._request(
            "POST", "/rest/media/post/create", payload,
            cookies, user_agent, statsig_id,
        )
        if not resp:
            raise ExternalAPIException(detail="Failed to create Grok media post")

        data = resp.json()
        post_id = (data.get("post") or {}).get("id")
        if not post_id:
            raise ExternalAPIException(detail="No post ID in Grok media post response")
        return post_id

    @classmethod
    async def _start_conversation(
        cls, prompt: str, parent_post_id: str,
        cookies: str, user_agent: str, statsig_id: str,
        ratio: str = "16:9", length: int = 6, res: str = "480p",
        file_attachment_ids: list[str] | None = None,
    ) -> tuple[str | None, str | None]:
        """Start video generation conversation.
        Returns (video_url, video_post_id)."""
        message = f"{prompt} --mode=custom"

        payload = {
            "temporary": True,
            "modelName": "grok-3",
            "message": message,
            "fileAttachments": file_attachment_ids or [],
            "toolOverrides": {"videoGen": True},
            "enableSideBySide": True,
            "responseMetadata": {
                "experiments": [],
                "modelConfigOverride": {
                    "modelMap": {
                        "videoGenModelConfig": {
                            "parentPostId": parent_post_id,
                            "aspectRatio": ratio,
                            "videoLength": length,
                            "resolutionName": res,
                        },
                    },
                },
            },
        }

        resp = await cls._request(
            "POST", "/rest/app-chat/conversations/new", payload,
            cookies, user_agent, statsig_id,
        )
        if not resp:
            return None, None

        text = resp.text
        video_url = None
        video_post_id = None
        pos = 0

        while pos < len(text):
            # Skip whitespace
            while pos < len(text) and text[pos].isspace():
                pos += 1
            if pos >= len(text):
                break
            try:
                value, pos = _parse_json_at(text, pos)
                stream_resp = (
                    (value.get("result") or {})
                    .get("response", {})
                    .get("streamingVideoGenerationResponse", {})
                )
                if stream_resp.get("progress") == 100 and stream_resp.get("videoUrl"):
                    video_url = stream_resp["videoUrl"]
                    video_post_id = (
                        stream_resp.get("videoPostId")
                        or stream_resp.get("assetId")
                    )
                elif stream_resp.get("videoPostId") and not video_post_id:
                    video_post_id = stream_resp["videoPostId"]
            except (ValueError, json.JSONDecodeError):
                break

        return video_url, video_post_id

    @classmethod
    async def _upscale_video(
        cls, video_id: str,
        cookies: str, user_agent: str, statsig_id: str,
    ) -> str | None:
        """Upscale video to HD. Returns HD URL or None."""
        payload = {"videoId": video_id}
        referer = f"https://grok.com/imagine/post/{video_id}"
        resp = await cls._request(
            "POST", "/rest/media/video/upscale", payload,
            cookies, user_agent, statsig_id, referer=referer,
        )
        if not resp:
            return None
        try:
            data = resp.json()
            return data.get("hdMediaUrl")
        except Exception:
            return None

    @classmethod
    async def _download_video(
        cls, url: str, save_path: Path,
        cookies: str, user_agent: str,
    ) -> bool:
        """Download video file from Grok CDN."""
        full_url = url if url.startswith("http") else f"https://assets.grok.com/{url.lstrip('/')}"
        if "?" not in full_url:
            full_url += "?cache=1"

        # Wait for Grok video processing
        await asyncio.sleep(5)

        headers = {
            "User-Agent": user_agent,
            "Referer": "https://grok.com/",
            "Cookie": cookies,
        }

        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        async with httpx.AsyncClient(verify=ssl_ctx, timeout=60) as client:
            try:
                resp = await client.get(full_url, headers=headers)
                if resp.status_code == 200:
                    content_type = resp.headers.get("content-type", "")
                    if "text/html" not in content_type and len(resp.content) > 1000:
                        save_path.write_bytes(resp.content)
                        logger.info("Downloaded video: %s (%d bytes)", save_path, len(resp.content))
                        return True
            except Exception as e:
                logger.warning("Download failed: %s", e)

        return False

    # ── Public API ────────────────────────────────────────────────────────

    @classmethod
    async def generate_video(
        cls,
        prompt: str,
        ratio: str = "16:9",
        length: int = 6,
        res: str = "480p",
        upscale: bool = True,
        session_id: str | None = None,
        image_path: str | None = None,
    ) -> dict:
        """Generate a video from a text prompt using Grok.

        Args:
            prompt: Text description of the video to generate.
            ratio: Aspect ratio — '1:1', '16:9', or '9:16'.
            length: Video length in seconds — 6 or 10.
            res: Resolution — '480p' or '720p'.
            upscale: Whether to upscale to HD after generation.

        Returns:
            Dict with post_id, video_url, hd_video_url, local_path, download_url.
        """
        cookies, user_agent = cls._get_config()
        statsig_id = _generate_statsig_id()

        # Upload reference KOL image if provided
        file_attachment_ids: list[str] = []
        if image_path:
            logger.info("Uploading KOL reference image: %s", image_path)
            fid = await cls._upload_image(image_path, cookies, user_agent)
            file_attachment_ids.append(fid)

        # 1. Create media post
        logger.info("Creating media post for prompt: %s", prompt[:50])
        post_id = await cls._create_media_post(prompt, cookies, user_agent, statsig_id)
        logger.info("Media post created: %s", post_id)

        await asyncio.sleep(5)

        # 2. Start video generation conversation
        logger.info("Starting video generation: ratio=%s length=%d res=%s", ratio, length, res)
        video_url, video_post_id = await cls._start_conversation(
            prompt, post_id, cookies, user_agent, statsig_id,
            ratio=ratio, length=length, res=res,
            file_attachment_ids=file_attachment_ids or None,
        )

        if not video_url and not video_post_id:
            raise ExternalAPIException(detail="Video generation failed — no video URL returned")

        # 3. Upscale if requested
        hd_url = None
        if upscale and post_id:
            await asyncio.sleep(5)
            logger.info("Upscaling video: %s", post_id)
            hd_url = await cls._upscale_video(post_id, cookies, user_agent, statsig_id)
            if hd_url:
                logger.info("HD URL: %s", hd_url)

        # 4. Download video
        download_url_source = hd_url or video_url
        if not download_url_source and post_id:
            download_url_source = f"https://assets.grok.com/users/{post_id}/video.mp4"

        local_filename = f"grok_{post_id}{'_hd' if hd_url else ''}.mp4"
        if session_id:
            out_dir = DOWNLOADS_DIR / session_id / "grok"
        else:
            out_dir = DOWNLOADS_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        local_path = out_dir / local_filename

        downloaded = False
        if download_url_source:
            downloaded = await cls._download_video(
                download_url_source, local_path, cookies, user_agent,
            )

        result = {
            "post_id": post_id,
            "video_post_id": video_post_id,
            "video_url": video_url or "",
            "hd_video_url": hd_url or "",
            "local_filename": local_filename if downloaded else "",
        }

        return result
