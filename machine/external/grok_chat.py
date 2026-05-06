"""
Grok Chat API — Python port of grok_chatbox.js.

Streams chat responses from grok.com web API (cookie-based session).
Used to generate video prompts from crawled content.
"""

import asyncio
import json
import logging
import os
import re
import ssl
from base64 import b64encode
from os import urandom
from pathlib import Path
from uuid import uuid4

import httpx

from core.exceptions.http import ExternalAPIException
from core.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

DOWNLOADS_DIR = Path("downloads")

KOL_IMAGE_PROMPT = (
    "Initiating the PersonaFusion-vX.03 protocol: Using accurate facial recognition "
    "obtained from the attached reference image (or from a user-provided face) without "
    "editing, the reference logo is printed on the left chest of the character's shirt, "
    "and the logo is printed in a small size, not large. "
    "A hyper-realistic, extremely sharp image, captured with a modern smartphone, "
    "characterized by digital clarity, was taken with an iPhone 15 Pro. The image shows "
    "a person styled like a professional model, the character's clothing changed to a new, "
    "modern and fashionable style. The setting is a tourist location in a random country. "
    "The entire scene is displayed with an extremely large depth of field, ensuring "
    "everything from the rough texture of the foreground to the distant architecture is "
    "sharp, without background blurring or bokeh effects. The hyper-realistic digital "
    "texture displays sharp fabric details on clothing, along with a natural, soft skin "
    "texture with visible pores, completely free of film grain. Bright and even lighting, "
    "characteristic of modern HDR processing technology on smartphones, brightens dark "
    "areas to avoid overly deep blacks and creates a vibrant, realistic atmosphere. Colors "
    "are natural and vivid, with smooth, fresh skin tones and accurately reproduced "
    "clothing images, as well as the yellow hue of the background, complemented by subtle "
    "digital noise, highlighting the sense of modern photography."
)


def build_kol_video_prompt(content: str, language: str = "hàn quốc", extra: str = "") -> str:
    extra_instruction = f"\n\nYêu cầu bổ sung: {extra.strip()}" if extra and extra.strip() else ""
    return (
        "Hãy đóng vai một người có hơn 20 năm kinh nghiệm trong lĩnh vực marketing "
        "chuyên phân tích đối thủ và bài viết của đối thủ, và hãy phân tích nội dung "
        "tôi gửi sau đây để tạo cho tôi 1 prompt lời thoại duy nhất với nội dung đã "
        "được phân tích kỹ lưỡng, mở đầu hook đúng trọng tâm nội dung và nói câu gây "
        "bất ngờ và gây tò mò cho người xem, tạo nội dung sao cho lời thoại thật hấp "
        "dẫn và phải bắt buộc người xem phải tương tác và thích video của tôi, CTA sẽ "
        "kêu gọi mọi người nhớ thích video và đăng ký kênh để ủng hộ và đừng quên tải "
        "app và nhập mã mời để tham gia vào Interlink Network, lời thoại sẽ viết bằng "
        f"ngôn ngữ tiếng anh, còn lời thoại thì sẽ viết hoàn toàn ngôn ngữ {language} "
        "chuẩn chính tả, video chỉ có 1 cảnh duy nhất không chuyển cảnh, và không hiện "
        "bất cứ hiệu ứng gì hay chữ xuất hiện trong video, hạn chế sử dụng các từ nhạy "
        "cảm và vi phạm chính sách của youtube năm 2026 như là về tiền hoặc là kiếm "
        "tiền, tránh các từ ngữ nhạy cảm dẫn đến video bị flop tụt view, prompt phải "
        "viết liền mạch 1 đoạn, lời thoại cần nói cử chỉ và biểu cảm thân thiện và "
        f"lời thoại chỉ tầm 200 ký tự.{extra_instruction}\n\n"
        f"Nội dung cần phân tích:\n{content}"
    )


def _build_headers(cookies: str, user_agent: str) -> dict:
    trace_id = urandom(16).hex()
    span_id = urandom(8).hex()
    return {
        "Accept": "*/*",
        "Content-Type": "application/json",
        "Cookie": cookies,
        "Origin": "https://grok.com",
        "Referer": "https://grok.com/",
        "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
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
        s = get_settings()
        cookies = s.GROK_COOKIES.strip()
        if not cookies:
            raise ExternalAPIException(detail="GROK_COOKIES not configured")
        ua = s.GROK_USER_AGENT.strip()
        if not ua:
            raise ExternalAPIException(detail="GROK_USER_AGENT not configured in .env")
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

    # ── KOL Image Generation ─────────────────────────────────────────

    @staticmethod
    def _crop_image_to_9_16(image_path: str) -> str:
        """Center-crop image to 9:16 portrait ratio. Returns path (may be a new file)."""
        try:
            from PIL import Image
            img = Image.open(image_path)
            w, h = img.size
            target_ratio = 9 / 16
            current_ratio = w / h

            if abs(current_ratio - target_ratio) < 0.01:
                return image_path

            if current_ratio > target_ratio:
                new_w = int(h * 9 / 16)
                left = (w - new_w) // 2
                img = img.crop((left, 0, left + new_w, h))
            else:
                new_h = int(w * 16 / 9)
                top = (h - new_h) // 2
                img = img.crop((0, top, w, top + new_h))

            base, ext = os.path.splitext(image_path)
            out_path = f"{base}_916{ext}"
            img.save(out_path)
            logger.info("Cropped image to 9:16: %s → %s", image_path, out_path)
            return out_path
        except Exception as e:
            logger.warning("Image crop to 9:16 failed: %s", e)
            return image_path

    @classmethod
    async def generate_kol_image(
        cls,
        image_path: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """Generate a KOL-styled image using Grok image generation.

        Optionally accepts a reference face image to incorporate into the generated image.
        Returns dict with local_filename, image_url, download_url.
        """
        cookies, ua = cls._get_config()
        headers = _build_headers(cookies, ua)

        file_ids: list[str] = []
        if image_path:
            image_path = await asyncio.to_thread(cls._crop_image_to_9_16, image_path)
            fid = await cls._upload_image(image_path)
            file_ids.append(fid)

        body = {
            "temporary": True,
            "message": KOL_IMAGE_PROMPT,
            "fileAttachments": file_ids,
            "imageAttachments": [],
            "disableSearch": False,
            "enableImageGeneration": True,
            "returnImageBytes": False,
            "enableImageStreaming": True,
            "imageGenerationCount": 1,
            "forceConcise": False,
            "toolOverrides": {},
            "enableSideBySide": True,
            "sendFinalMetadata": True,
            "isReasoning": False,
            "disableTextFollowUps": False,
            "responseMetadata": {},
            "disableMemory": False,
            "forceSideBySide": False,
            "isAsyncChat": False,
            "disableSelfHarmShortCircuit": False,
            "modeId": "imagine",
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
                raise ExternalAPIException(detail=f"Grok image generation error: {e}")

        if resp.status_code == 429:
            raise ExternalAPIException(detail="Grok account out of credits (429)")
        if resp.status_code == 403:
            raise ExternalAPIException(detail="Grok 403 — cookies expired. Update GROK_COOKIES.")
        if resp.status_code != 200:
            raise ExternalAPIException(detail=f"Grok image generation HTTP {resp.status_code}")

        # Parse stream for generated image URLs
        text = resp.text
        image_url: str = ""
        asset_id: str = ""
        pos = 0

        logger.warning("=== Grok imagine raw response (first 800): %s", text[:800])
        print(f"[GROK DEBUG] status={resp.status_code} len={len(text)} first800={text[:800]}", flush=True)

        while pos < len(text):
            while pos < len(text) and text[pos].isspace():
                pos += 1
            if pos >= len(text):
                break
            try:
                chunk, pos = _parse_json_at(text, pos)
            except (ValueError, json.JSONDecodeError):
                break

            r = (chunk.get("result") or {}).get("response")
            if not r:
                r = chunk.get("response") or {}

            # Log interesting chunks for debugging
            if r:
                interesting_keys = [k for k in r if k not in (
                    "userResponse", "progressReport", "isThinking", "isSoftStop", "responseId"
                )]
                if interesting_keys:
                    logger.warning("=== Grok response keys: %s", list(r.keys()))
                    for ik in interesting_keys:
                        logger.warning("=== Grok[%s] = %s", ik, str(r[ik])[:500])

            # cardAttachment.jsonData contains the generated image
            card = r.get("cardAttachment") or {}
            json_data_str = card.get("jsonData") or ""
            if json_data_str:
                try:
                    card_data = json.loads(json_data_str)
                    image_chunk = card_data.get("image_chunk") or {}
                    chunk_url = image_chunk.get("imageUrl") or ""
                    progress = image_chunk.get("progress", 0)
                    if chunk_url and progress == 100 and not image_url:
                        # relative path → prepend CDN base
                        if not chunk_url.startswith("http"):
                            chunk_url = f"https://assets.grok.com/{chunk_url.lstrip('/')}"
                        image_url = chunk_url
                        asset_id = image_chunk.get("imageUuid") or ""
                        logger.warning("KOL image URL from cardAttachment (progress=100): %s", image_url)
                except Exception as e:
                    logger.warning("cardAttachment parse error: %s", e)

        # Fallback: regex scan raw text for image URLs
        if not image_url:
            found = re.findall(
                r'https?://[^\s"\'\\]+\.(?:jpg|jpeg|png|webp)(?:[^\s"\'\\]*)?',
                text
            )
            if found:
                image_url = found[0]
                logger.info("KOL image URL via regex fallback: %s", image_url)

        if not image_url:
            logger.warning("=== Grok imagine FULL response (%d chars): %s", len(text), text[:3000])
            print(f"[GROK DEBUG] NO IMAGE URL. full={text[:3000]}", flush=True)
            raise ExternalAPIException(detail="Grok image generation returned no image URL")

        # Download and save image
        if session_id:
            out_dir = DOWNLOADS_DIR / session_id / "grok"
        else:
            out_dir = DOWNLOADS_DIR / "kol_images"
        out_dir.mkdir(parents=True, exist_ok=True)

        ext = ".jpg"
        if ".png" in image_url.lower():
            ext = ".png"
        filename = f"kol_{asset_id or 'image'}{ext}"
        save_path = out_dir / filename

        full_url = image_url if image_url.startswith("http") else f"https://assets.grok.com/{image_url.lstrip('/')}"
        ssl_ctx2 = ssl.create_default_context()
        ssl_ctx2.check_hostname = False
        ssl_ctx2.verify_mode = ssl.CERT_NONE

        downloaded = False
        async with httpx.AsyncClient(verify=ssl_ctx2, timeout=60) as client:
            try:
                dl_resp = await client.get(
                    full_url,
                    headers={"User-Agent": ua, "Referer": "https://grok.com/", "Cookie": cookies},
                )
                if dl_resp.status_code == 200 and len(dl_resp.content) > 500:
                    save_path.write_bytes(dl_resp.content)
                    downloaded = True
                    logger.info("KOL image saved: %s (%d bytes)", save_path, len(dl_resp.content))
                    # Crop generated image to 9:16
                    cropped = await asyncio.to_thread(
                        GrokChatService._crop_image_to_9_16, str(save_path)
                    )
                    if cropped != str(save_path):
                        save_path = Path(cropped)
                        filename = save_path.name
            except Exception as e:
                logger.warning("KOL image download failed: %s", e)

        return {
            "local_filename": filename if downloaded else "",
            "local_path": str(save_path) if downloaded else "",
            "image_url": image_url,
            "asset_id": asset_id,
        }

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

