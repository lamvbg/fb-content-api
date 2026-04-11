"""
Grok Chat API — Python port of grok_chatbox.js.

Streams chat responses from grok.com web API (cookie-based session).
Used to generate video prompts from crawled content.
"""

import asyncio
import json
import logging
import re
import ssl
from base64 import b64encode
from os import urandom
from uuid import uuid4

import httpx

from core.exceptions.http import ExternalAPIException
from core.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _build_headers(cookies: str, user_agent: str) -> dict:
    trace_id = urandom(16).hex()
    span_id = urandom(8).hex()
    return {
        "Accept": "*/*",
        "Content-Type": "application/json",
        "Cookie": cookies,
        "Origin": "https://grok.com",
        "Referer": "https://grok.com/",
        "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "sentry-trace": f"{trace_id}-{span_id}-0",
        "traceparent": f"00-{trace_id}-{span_id}-00",
        "User-Agent": user_agent,
        "x-statsig-id": "ZTpUeXBlRXJyb3I6IENhbm5vdCByZWFkIHByb3BlcnRpZXMgb2YgdW5kZWZpbmVkIChyZWFkaW5nICdjaGlsZE5vZGVzJyk=",
        "x-xai-request-id": str(uuid4()),
    }


def _parse_json_at(text: str, start: int) -> tuple[dict, int]:
    """Parse one JSON object from `text` starting at `start`."""
    depth = 0
    in_str = False
    esc = False
    obj_start = start
    for i in range(start, len(text)):
        c = text[i]
        if esc:
            esc = False
            continue
        if c == "\\" and in_str:
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[obj_start : i + 1]), i + 1
    raise ValueError("Incomplete JSON")


class GrokChatService:
    """Chat with Grok via grok.com web API."""

    CHAT_URL = "https://grok.com/rest/app-chat/conversations/new"

    @classmethod
    def _get_config(cls) -> tuple[str, str]:
        cookies = settings.GROK_COOKIES.strip()
        if not cookies:
            raise ExternalAPIException(detail="GROK_COOKIES not configured")
        ua = settings.GROK_USER_AGENT.strip() or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/146.0.0.0 Safari/537.36"
        )
        return cookies, ua

    @classmethod
    async def chat(
        cls,
        message: str,
        is_reasoning: bool = False,
        force_concise: bool = False,
        file_attachments: list[str] | None = None,
    ) -> dict:
        """Send a message to Grok and return the full response.

        Returns:
            Dict with conversation_id, response_id, message, model.
        """
        cookies, ua = cls._get_config()
        headers = _build_headers(cookies, ua)

        body = {
            "temporary": True,
            "message": message,
            "fileAttachments": file_attachments or [],
            "imageAttachments": [],
            "disableSearch": False,
            "enableImageGeneration": False,
            "returnImageBytes": False,
            "returnRawGrokInXaiRequest": False,
            "enableImageStreaming": False,
            "imageGenerationCount": 0,
            "forceConcise": force_concise,
            "toolOverrides": {},
            "enableSideBySide": True,
            "sendFinalMetadata": True,
            "isReasoning": is_reasoning,
            "disableTextFollowUps": False,
            "responseMetadata": {},
            "disableMemory": False,
            "forceSideBySide": False,
            "isAsyncChat": False,
            "disableSelfHarmShortCircuit": False,
            "modeId": "auto",
            "enable420": False,
        }

        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        async with httpx.AsyncClient(verify=ssl_ctx, timeout=180) as client:
            try:
                resp = await client.post(
                    cls.CHAT_URL, headers=headers,
                    content=json.dumps(body),
                )
            except Exception as e:
                raise ExternalAPIException(detail=f"Grok chat error: {e}")

        if resp.status_code == 429:
            raise ExternalAPIException(detail="Grok account out of credits (429)")
        if resp.status_code == 403:
            raise ExternalAPIException(detail="Grok 403 — cookies expired. Update GROK_COOKIES.")
        if resp.status_code != 200:
            raise ExternalAPIException(detail=f"Grok chat HTTP {resp.status_code}")

        # Parse streaming NDJSON response
        text = resp.text
        conversation_id = None
        response_id = None
        full_message = ""
        model = None
        pos = 0

        while pos < len(text):
            while pos < len(text) and text[pos].isspace():
                pos += 1
            if pos >= len(text):
                break
            try:
                chunk, pos = _parse_json_at(text, pos)
            except (ValueError, json.JSONDecodeError):
                break

            # Conversation created
            conv = (chunk.get("result") or {}).get("conversation")
            if conv:
                conversation_id = conv.get("conversationId")
                continue

            r = (chunk.get("result") or {}).get("response")
            if not r:
                continue

            if r.get("responseId"):
                response_id = r["responseId"]

            # Tokens (skip thinking, only collect final)
            if "token" in r:
                if not r.get("isThinking"):
                    full_message += r["token"]
                continue

            # Model info
            mr = r.get("modelResponse")
            if mr:
                model = mr.get("model") or model

        return {
            "conversation_id": conversation_id,
            "response_id": response_id,
            "message": full_message.strip(),
            "model": model,
        }

    @classmethod
    async def generate_prompts(
        cls,
        content: str,
        count: int = 5,
        style: str | None = None,
    ) -> list[str]:
        """Use Grok chat to generate video prompts from content.

        Args:
            content: Source content (e.g. Douyin video description).
            count: Number of prompts to generate.
            style: Optional style hint (e.g. "cinematic", "funny", "dramatic").

        Returns:
            List of prompt strings.
        """
        style_hint = f" Style: {style}." if style else ""

        message = (
            f"Generate exactly {count} short video prompts (in English) "
            f"for AI video generation based on this content:\n\n"
            f'"""\n{content}\n"""\n\n'
            f"Requirements:\n"
            f"- Each prompt should be a vivid, detailed scene description (1-2 sentences)\n"
            f"- Include visual details: lighting, camera angle, mood, action\n"
            f"- Suitable for 6-10 second video clips\n"
            f"- Each prompt on a new line, numbered 1. 2. 3. etc.\n"
            f"- No explanations, just the prompts\n"
            f"{style_hint}"
        )

        result = await cls.chat(message, force_concise=True)
        raw = result.get("message", "")

        # Parse numbered list
        prompts = []
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            # Remove numbering: "1. ", "1) ", "- ", etc.
            import re
            cleaned = re.sub(r"^\d+[.)]\s*", "", line)
            cleaned = re.sub(r"^[-*]\s*", "", cleaned)
            cleaned = cleaned.strip().strip('"').strip("'")
            if cleaned and len(cleaned) > 10:
                prompts.append(cleaned)

        return prompts[:count]

    # ── Image upload & Video review ──────────────────────────────────

    UPLOAD_URL = "https://grok.com/rest/app-chat/upload-file"

    @classmethod
    async def _upload_image(cls, image_path: str) -> str:
        """Upload an image to Grok via JSON base64. Returns fileMetadataId."""
        cookies, ua = cls._get_config()
        headers = _build_headers(cookies, ua)

        with open(image_path, "rb") as f:
            b64 = b64encode(f.read()).decode()

        filename = image_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        payload = {
            "fileName": filename,
            "fileMimeType": "image/jpeg",
            "content": b64,
        }

        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        async with httpx.AsyncClient(verify=ssl_ctx, timeout=60) as client:
            try:
                resp = await client.post(
                    cls.UPLOAD_URL, headers=headers,
                    content=json.dumps(payload),
                )
            except Exception as e:
                raise ExternalAPIException(detail=f"Grok image upload error: {e}")

        if resp.status_code != 200:
            logger.warning("Grok upload %d: %s", resp.status_code, resp.text[:300])
            raise ExternalAPIException(
                detail=f"Grok image upload failed: HTTP {resp.status_code}"
            )

        data = resp.json()
        logger.info("Grok upload response: %s", json.dumps(data)[:500])

        file_id = data.get("fileMetadataId") or data.get("id") or data.get("fileId")
        if not file_id:
            raise ExternalAPIException(detail=f"No fileMetadataId in upload response: {data}")
        return file_id

    @classmethod
    async def review_video(
        cls,
        frame_paths: list[str],
        criteria: str,
    ) -> dict:
        """Upload video frames to Grok and request content review.

        Returns:
            Dict with passed, score, feedback, issues, raw_response.
        """
        # Upload frames, collect fileMetadataId values
        file_ids = []
        for path in frame_paths:
            fid = await cls._upload_image(path)
            file_ids.append(fid)
            await asyncio.sleep(0.3)

        message = (
            f"You are a professional video content moderator. "
            f"I am sending you {len(frame_paths)} frames extracted from a video "
            f"(approximately 1 frame per second).\n\n"
            f"Review the video based on these criteria:\n"
            f"{criteria}\n\n"
            f"Respond ONLY with this exact JSON format, no other text:\n"
            f'{{"pass": true, "score": 8, "feedback": "detailed feedback here", '
            f'"issues": ["issue1", "issue2"]}}\n\n'
            f"- pass: true if video meets criteria, false otherwise\n"
            f"- score: 1-10 quality rating\n"
            f"- feedback: detailed explanation\n"
            f"- issues: list of specific issues found (empty list if none)"
        )

        result = await cls.chat(
            message, file_attachments=file_ids, force_concise=True,
        )
        raw = result.get("message", "")

        # Try to parse JSON from response
        parsed = {"passed": False, "score": 0, "feedback": raw, "issues": []}
        try:
            match = re.search(r"\{[\s\S]*\}", raw)
            if match:
                data = json.loads(match.group())
                parsed["passed"] = bool(data.get("pass", False))
                parsed["score"] = int(data.get("score", 0))
                parsed["feedback"] = str(data.get("feedback", raw))
                parsed["issues"] = [str(i) for i in data.get("issues", [])]
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Could not parse Grok review JSON: %s", e)

        parsed["raw_response"] = raw
        return parsed

