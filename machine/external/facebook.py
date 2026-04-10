import logging
from urllib.parse import urlencode

import httpx

from core.exceptions.http import ExternalAPIException
from core.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class FacebookService:
    """Handles all direct communication with the Facebook Graph API."""

    BASE_URL = settings.FACEBOOK_GRAPH_API_URL

    # ── OAuth ──────────────────────────────────────────────

    @staticmethod
    def get_login_url() -> str:
        params = urlencode(
            {
                "client_id": settings.FACEBOOK_APP_ID,
                "redirect_uri": settings.FACEBOOK_REDIRECT_URI,
                "scope": "pages_manage_posts,pages_read_engagement,pages_show_list,pages_read_user_content,public_profile",
                "response_type": "code",
            }
        )
        return f"https://www.facebook.com/v21.0/dialog/oauth?{params}"

    @classmethod
    async def exchange_code_for_token(cls, code: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{cls.BASE_URL}/oauth/access_token",
                params={
                    "client_id": settings.FACEBOOK_APP_ID,
                    "client_secret": settings.FACEBOOK_APP_SECRET,
                    "redirect_uri": settings.FACEBOOK_REDIRECT_URI,
                    "code": code,
                },
            )
        data = resp.json()
        if "error" in data:
            logger.error("Facebook token exchange error: %s", data["error"])
            raise ExternalAPIException(
                detail=data["error"].get("message", "Token exchange failed")
            )
        return data  # {access_token, token_type, expires_in}

    @classmethod
    async def get_long_lived_token(cls, short_token: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{cls.BASE_URL}/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": settings.FACEBOOK_APP_ID,
                    "client_secret": settings.FACEBOOK_APP_SECRET,
                    "fb_exchange_token": short_token,
                },
            )
        data = resp.json()
        if "error" in data:
            raise ExternalAPIException(
                detail=data["error"].get("message", "Long-lived token exchange failed")
            )
        return data

    # ── User profile ───────────────────────────────────────

    @classmethod
    async def get_user_profile(cls, access_token: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{cls.BASE_URL}/me",
                params={
                    "fields": "id,name,email,picture.type(large)",
                    "access_token": access_token,
                },
            )
        data = resp.json()
        if "error" in data:
            raise ExternalAPIException(
                detail=data["error"].get("message", "Failed to get user profile")
            )
        return data

    # ── Pages ──────────────────────────────────────────────

    @classmethod
    async def get_user_pages(cls, access_token: str) -> list[dict]:
        pages = []
        url = f"{cls.BASE_URL}/me/accounts"
        params = {
            "fields": "id,name,category,access_token,picture.type(large)",
            "access_token": access_token,
            "limit": 100,
        }
        async with httpx.AsyncClient() as client:
            while url:
                resp = await client.get(url, params=params)
                data = resp.json()
                if "error" in data:
                    raise ExternalAPIException(
                        detail=data["error"].get("message", "Failed to get pages")
                    )
                for page in data.get("data", []):
                    picture_url = None
                    if pic := page.get("picture", {}).get("data", {}):
                        picture_url = pic.get("url")
                    pages.append(
                        {
                            "id": page["id"],
                            "name": page["name"],
                            "category": page.get("category"),
                            "access_token": page.get("access_token"),
                            "picture_url": picture_url,
                        }
                    )
                paging = data.get("paging", {})
                url = paging.get("next")
                params = {}  # next URL already contains params
        return pages

    # ── Posts ──────────────────────────────────────────────

    @classmethod
    async def create_page_post(
        cls,
        page_id: str,
        page_access_token: str,
        message: str,
        link: str | None = None,
        published: bool = True,
    ) -> dict:
        payload = {
            "message": message,
            "published": published,
            "access_token": page_access_token,
        }
        if link:
            payload["link"] = link

        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{cls.BASE_URL}/{page_id}/feed", data=payload)
        data = resp.json()
        if "error" in data:
            raise ExternalAPIException(
                detail=data["error"].get("message", "Failed to create post")
            )
        return data

    @classmethod
    async def schedule_page_post(
        cls,
        page_id: str,
        page_access_token: str,
        message: str,
        scheduled_publish_time: int,
        link: str | None = None,
    ) -> dict:
        payload = {
            "message": message,
            "published": False,
            "scheduled_publish_time": scheduled_publish_time,
            "access_token": page_access_token,
        }
        if link:
            payload["link"] = link

        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{cls.BASE_URL}/{page_id}/feed", data=payload)
        data = resp.json()
        if "error" in data:
            raise ExternalAPIException(
                detail=data["error"].get("message", "Failed to schedule post")
            )
        return data

    @classmethod
    async def get_page_posts(
        cls, page_id: str, page_access_token: str, limit: int = 25
    ) -> list[dict]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{cls.BASE_URL}/{page_id}/feed",
                params={
                    "fields": "id,message,created_time,full_picture,permalink_url",
                    "access_token": page_access_token,
                    "limit": limit,
                },
            )
        data = resp.json()
        if "error" in data:
            raise ExternalAPIException(
                detail=data["error"].get("message", "Failed to get posts")
            )
        return data.get("data", [])

    # ── Test Users & Roles ─────────────────────────────────

    @classmethod
    async def _get_app_access_token(cls) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{cls.BASE_URL}/oauth/access_token",
                params={
                    "client_id": settings.FACEBOOK_APP_ID,
                    "client_secret": settings.FACEBOOK_APP_SECRET,
                    "grant_type": "client_credentials",
                },
            )
        data = resp.json()
        if "error" in data:
            raise ExternalAPIException(
                detail=data["error"].get("message", "Failed to get app token")
            )
        return data["access_token"]

    @classmethod
    async def create_test_user(
        cls,
        installed: bool = True,
        name: str | None = None,
        permissions: str = "pages_manage_posts,pages_read_engagement,pages_show_list",
    ) -> dict:
        app_token = await cls._get_app_access_token()
        payload: dict = {
            "installed": str(installed).lower(),
            "permissions": permissions,
            "access_token": app_token,
        }
        if name:
            payload["name"] = name

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{cls.BASE_URL}/{settings.FACEBOOK_APP_ID}/accounts/test-users",
                data=payload,
            )
        data = resp.json()
        if "error" in data:
            raise ExternalAPIException(
                detail=data["error"].get("message", "Failed to create test user")
            )
        return data

    @classmethod
    async def get_test_users(cls) -> list[dict]:
        app_token = await cls._get_app_access_token()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{cls.BASE_URL}/{settings.FACEBOOK_APP_ID}/accounts/test-users",
                params={"access_token": app_token},
            )
        data = resp.json()
        if "error" in data:
            raise ExternalAPIException(
                detail=data["error"].get("message", "Failed to get test users")
            )
        return data.get("data", [])

    @classmethod
    async def delete_test_user(cls, test_user_id: str) -> bool:
        app_token = await cls._get_app_access_token()
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{cls.BASE_URL}/{test_user_id}",
                params={"access_token": app_token},
            )
        data = resp.json()
        if isinstance(data, dict) and "error" in data:
            raise ExternalAPIException(
                detail=data["error"].get("message", "Failed to delete test user")
            )
        return True

    @classmethod
    async def assign_app_role(cls, user_id: str, role: str) -> bool:
        app_token = await cls._get_app_access_token()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{cls.BASE_URL}/{settings.FACEBOOK_APP_ID}/roles",
                data={
                    "user": user_id,
                    "role": role,
                    "access_token": app_token,
                },
            )
        data = resp.json()
        if isinstance(data, dict) and "error" in data:
            raise ExternalAPIException(
                detail=data["error"].get("message", "Failed to assign role")
            )
        return True
