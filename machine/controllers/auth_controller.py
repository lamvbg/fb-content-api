from datetime import datetime, timedelta, timezone

from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from core.controller.base import BaseController
from core.settings import get_settings
from machine.external.facebook import FacebookService
from machine.repositories.user_repository import UserRepository
from machine.schemas.auth import TokenResponse

settings = get_settings()


class AuthController(BaseController):
    def __init__(self, session: AsyncSession):
        super().__init__(session)
        self.user_repo = UserRepository(session)

    @staticmethod
    def get_facebook_login_url() -> str:
        return FacebookService.get_login_url()

    async def facebook_callback(self, code: str) -> TokenResponse:
        # Exchange code for short-lived token
        token_data = await FacebookService.exchange_code_for_token(code)
        short_token = token_data["access_token"]

        # Exchange for long-lived token
        long_token_data = await FacebookService.get_long_lived_token(short_token)
        access_token = long_token_data["access_token"]
        expires_in = long_token_data.get("expires_in")

        # Get user profile
        profile = await FacebookService.get_user_profile(access_token)
        picture_url = None
        if pic_data := profile.get("picture", {}).get("data", {}):
            picture_url = pic_data.get("url")

        # Upsert user
        user = await self.user_repo.upsert_from_facebook(
            facebook_id=profile["id"],
            name=profile["name"],
            email=profile.get("email"),
            picture_url=picture_url,
            access_token=access_token,
            token_expires_in=expires_in,
        )

        # Create JWT
        jwt_token = self._create_jwt(user.id)

        return TokenResponse(
            access_token=jwt_token,
            user_id=user.id,
            name=user.name,
        )

    @staticmethod
    def _create_jwt(user_id: str) -> str:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.JWT_EXPIRATION_MINUTES
        )
        payload = {"sub": user_id, "exp": expire}
        return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    @staticmethod
    def verify_jwt(token: str) -> str:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise ValueError("Invalid token")
        return user_id
