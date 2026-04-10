from sqlalchemy.ext.asyncio import AsyncSession

from core.controller.base import BaseController
from core.exceptions.http import NotFoundException
from machine.external.facebook import FacebookService
from machine.models.user import User
from machine.repositories.fanpage_repository import FanpageRepository
from machine.repositories.user_repository import UserRepository
from machine.schemas.fanpage import (
    CreatePostRequest,
    CreatePostResponse,
    FanpageResponse,
    FanpageSyncResponse,
    PostResponse,
    SchedulePostRequest,
)


class FanpageController(BaseController):
    def __init__(self, session: AsyncSession):
        super().__init__(session)
        self.user_repo = UserRepository(session)
        self.fanpage_repo = FanpageRepository(session)

    async def _get_user(self, user_id: str) -> User:
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundException(detail="User not found")
        return user

    async def sync_fanpages(self, user_id: str) -> FanpageSyncResponse:
        user = await self._get_user(user_id)
        pages_data = await FacebookService.get_user_pages(user.facebook_access_token)
        synced = await self.fanpage_repo.sync_fanpages(user_id, pages_data)
        return FanpageSyncResponse(
            synced=len(synced),
            fanpages=[FanpageResponse.model_validate(p) for p in synced],
        )

    async def get_fanpages(self, user_id: str) -> list[FanpageResponse]:
        fanpages = await self.fanpage_repo.get_by_user_id(user_id)
        return [FanpageResponse.model_validate(p) for p in fanpages]

    async def get_fanpage(self, user_id: str, fanpage_id: str) -> FanpageResponse:
        fanpage = await self.fanpage_repo.get_by_id(fanpage_id)
        if not fanpage or fanpage.user_id != user_id:
            raise NotFoundException(detail="Fanpage not found")
        return FanpageResponse.model_validate(fanpage)

    async def create_post(
        self, user_id: str, fanpage_id: str, body: CreatePostRequest
    ) -> CreatePostResponse:
        fanpage = await self.fanpage_repo.get_by_id(fanpage_id)
        if not fanpage or fanpage.user_id != user_id:
            raise NotFoundException(detail="Fanpage not found")
        result = await FacebookService.create_page_post(
            page_id=fanpage.facebook_page_id,
            page_access_token=fanpage.page_access_token,
            message=body.message,
            link=body.link,
            published=body.published,
        )
        return CreatePostResponse(post_id=result["id"], message=body.message)

    async def schedule_post(
        self, user_id: str, fanpage_id: str, body: SchedulePostRequest
    ) -> CreatePostResponse:
        fanpage = await self.fanpage_repo.get_by_id(fanpage_id)
        if not fanpage or fanpage.user_id != user_id:
            raise NotFoundException(detail="Fanpage not found")
        result = await FacebookService.schedule_page_post(
            page_id=fanpage.facebook_page_id,
            page_access_token=fanpage.page_access_token,
            message=body.message,
            scheduled_publish_time=body.scheduled_publish_time,
            link=body.link,
        )
        return CreatePostResponse(post_id=result["id"], message=body.message)

    async def get_posts(
        self, user_id: str, fanpage_id: str, limit: int = 25
    ) -> list[PostResponse]:
        fanpage = await self.fanpage_repo.get_by_id(fanpage_id)
        if not fanpage or fanpage.user_id != user_id:
            raise NotFoundException(detail="Fanpage not found")
        posts = await FacebookService.get_page_posts(
            page_id=fanpage.facebook_page_id,
            page_access_token=fanpage.page_access_token,
            limit=limit,
        )
        return [PostResponse(**p) for p in posts]
