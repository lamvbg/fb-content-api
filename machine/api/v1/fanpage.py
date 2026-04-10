from fastapi import APIRouter, Depends, Query

from core.response.base import SuccessResponse
from machine.controllers.fanpage_controller import FanpageController
from machine.models.user import User
from machine.providers.auth_provider import get_current_user
from machine.providers.fanpage_provider import get_fanpage_controller
from machine.schemas.fanpage import (
    CreatePostRequest,
    CreatePostResponse,
    FanpageResponse,
    FanpageSyncResponse,
    PostResponse,
    SchedulePostRequest,
)

router = APIRouter(prefix="/fanpages", tags=["Fanpages"])


@router.post(
    "/sync",
    response_model=SuccessResponse[FanpageSyncResponse],
    summary="Sync fanpages from Facebook to local DB",
)
async def sync_fanpages(
    current_user: User = Depends(get_current_user),
    controller: FanpageController = Depends(get_fanpage_controller),
):
    result = await controller.sync_fanpages(current_user.id)
    return SuccessResponse(data=result)


@router.get(
    "/",
    response_model=SuccessResponse[list[FanpageResponse]],
    summary="List all synced fanpages",
)
async def list_fanpages(
    current_user: User = Depends(get_current_user),
    controller: FanpageController = Depends(get_fanpage_controller),
):
    result = await controller.get_fanpages(current_user.id)
    return SuccessResponse(data=result)


@router.get(
    "/{fanpage_id}",
    response_model=SuccessResponse[FanpageResponse],
    summary="Get a specific fanpage with its access token",
)
async def get_fanpage(
    fanpage_id: str,
    current_user: User = Depends(get_current_user),
    controller: FanpageController = Depends(get_fanpage_controller),
):
    result = await controller.get_fanpage(current_user.id, fanpage_id)
    return SuccessResponse(data=result)


@router.post(
    "/{fanpage_id}/posts",
    response_model=SuccessResponse[CreatePostResponse],
    summary="Publish a post to a fanpage",
)
async def create_post(
    fanpage_id: str,
    body: CreatePostRequest,
    current_user: User = Depends(get_current_user),
    controller: FanpageController = Depends(get_fanpage_controller),
):
    result = await controller.create_post(current_user.id, fanpage_id, body)
    return SuccessResponse(data=result)


@router.post(
    "/{fanpage_id}/posts/schedule",
    response_model=SuccessResponse[CreatePostResponse],
    summary="Schedule a post to a fanpage",
)
async def schedule_post(
    fanpage_id: str,
    body: SchedulePostRequest,
    current_user: User = Depends(get_current_user),
    controller: FanpageController = Depends(get_fanpage_controller),
):
    result = await controller.schedule_post(current_user.id, fanpage_id, body)
    return SuccessResponse(data=result)


@router.get(
    "/{fanpage_id}/posts",
    response_model=SuccessResponse[list[PostResponse]],
    summary="Get posts from a fanpage",
)
async def get_posts(
    fanpage_id: str,
    limit: int = Query(25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    controller: FanpageController = Depends(get_fanpage_controller),
):
    result = await controller.get_posts(current_user.id, fanpage_id, limit)
    return SuccessResponse(data=result)
