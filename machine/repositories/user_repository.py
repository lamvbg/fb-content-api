from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.repository.base import BaseRepository
from machine.models.user import User


class UserRepository(BaseRepository[User]):
    model = User

    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_by_facebook_id(self, facebook_id: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.facebook_id == facebook_id)
        )
        return result.scalar_one_or_none()

    async def upsert_from_facebook(
        self,
        facebook_id: str,
        name: str,
        email: str | None,
        picture_url: str | None,
        access_token: str,
        token_expires_in: int | None,
    ) -> User:
        user = await self.get_by_facebook_id(facebook_id)
        if user:
            return await self.update(
                user,
                name=name,
                email=email,
                picture_url=picture_url,
                facebook_access_token=access_token,
                facebook_token_expires_in=token_expires_in,
            )
        return await self.create(
            facebook_id=facebook_id,
            name=name,
            email=email,
            picture_url=picture_url,
            facebook_access_token=access_token,
            facebook_token_expires_in=token_expires_in,
        )
