from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.repository.base import BaseRepository
from machine.models.fanpage import Fanpage


class FanpageRepository(BaseRepository[Fanpage]):
    model = Fanpage

    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_by_user_id(self, user_id: str) -> list[Fanpage]:
        result = await self.session.execute(
            select(Fanpage).where(Fanpage.user_id == user_id)
        )
        return list(result.scalars().all())

    async def get_by_facebook_page_id(
        self, facebook_page_id: str, user_id: str
    ) -> Fanpage | None:
        result = await self.session.execute(
            select(Fanpage).where(
                Fanpage.facebook_page_id == facebook_page_id,
                Fanpage.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def sync_fanpages(
        self, user_id: str, pages_data: list[dict]
    ) -> list[Fanpage]:
        synced = []
        for page in pages_data:
            existing = await self.get_by_facebook_page_id(page["id"], user_id)
            if existing:
                updated = await self.update(
                    existing,
                    name=page.get("name", existing.name),
                    category=page.get("category"),
                    page_access_token=page.get("access_token"),
                    picture_url=page.get("picture_url"),
                )
                synced.append(updated)
            else:
                created = await self.create(
                    facebook_page_id=page["id"],
                    name=page.get("name", ""),
                    category=page.get("category"),
                    page_access_token=page.get("access_token"),
                    picture_url=page.get("picture_url"),
                    user_id=user_id,
                )
                synced.append(created)
        return synced
