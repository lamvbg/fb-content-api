"""
Grok (xAI) LLM service — rewrite X posts for Facebook using Grok API.
"""

import logging

import httpx

from core.exceptions.http import ExternalAPIException
from core.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

XAI_API_URL = "https://api.x.ai/v1/chat/completions"

SYSTEM_PROMPT = """Bạn là một chuyên gia viết nội dung mạng xã hội cho fanpage Facebook tiếng Việt về công nghệ.

Nhiệm vụ: Viết lại bài từ X/Twitter thành bài đăng Facebook hấp dẫn.

Quy tắc:
- Viết bằng tiếng Việt, tự nhiên, dễ hiểu
- Dòng đầu là hook thu hút (có thể dùng emoji phù hợp)
- Tóm tắt nội dung chính trong 2-4 câu ngắn gọn
- Cuối bài thêm 3-5 hashtag liên quan
- KHÔNG thêm link, KHÔNG ghi nguồn
- KHÔNG dùng markdown (**, ##, etc.)
- Giữ nguyên các thuật ngữ kỹ thuật bằng tiếng Anh (API, AI, LLM, etc.)
- Tổng độ dài: 100-300 từ"""


class GrokService:
    """Handles content rewriting using Grok LLM."""

    @classmethod
    async def rewrite_for_facebook(cls, tweet_text: str, tweet_url: str = "") -> str:
        if not settings.XAI_API_KEY:
            raise ExternalAPIException(detail="XAI_API_KEY not configured")

        user_prompt = f"Viết lại bài sau thành bài đăng Facebook:\n\n{tweet_text}"
        if tweet_url:
            user_prompt += f"\n\nNguồn: {tweet_url}"

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                XAI_API_URL,
                headers={
                    "Authorization": f"Bearer {settings.XAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.XAI_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 1024,
                },
                timeout=30,
            )

        if resp.status_code != 200:
            logger.error("Grok API error: %s %s", resp.status_code, resp.text[:200])
            raise ExternalAPIException(detail=f"Grok API error: {resp.status_code}")

        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise ExternalAPIException(detail=f"Unexpected Grok response: {e}")

    @classmethod
    async def rewrite_custom(cls, tweet_text: str, custom_prompt: str) -> str:
        if not settings.XAI_API_KEY:
            raise ExternalAPIException(detail="XAI_API_KEY not configured")

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                XAI_API_URL,
                headers={
                    "Authorization": f"Bearer {settings.XAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.XAI_MODEL,
                    "messages": [
                        {"role": "system", "content": custom_prompt},
                        {"role": "user", "content": tweet_text},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 1024,
                },
                timeout=30,
            )

        if resp.status_code != 200:
            raise ExternalAPIException(detail=f"Grok API error: {resp.status_code}")

        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise ExternalAPIException(detail=f"Unexpected Grok response: {e}")
