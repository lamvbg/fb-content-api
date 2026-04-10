from fastapi import APIRouter, Depends

from core.response.base import SuccessResponse
from machine.controllers.content_controller import ContentController
from machine.providers.content_provider import get_content_controller
from machine.schemas.content import (
    FetchTweetRequest,
    FetchUserTweetsRequest,
    RewriteRequest,
    RewriteResponse,
    TweetResponse,
)

router = APIRouter(prefix="/content", tags=["X Content & Grok Rewrite"])


@router.post(
    "/x/tweet",
    response_model=SuccessResponse[TweetResponse],
    summary="Fetch a single tweet by URL",
)
async def fetch_tweet(
    body: FetchTweetRequest,
    controller: ContentController = Depends(get_content_controller),
):
    result = await controller.fetch_tweet(body.url)
    return SuccessResponse(data=result)


@router.post(
    "/x/user-tweets",
    response_model=SuccessResponse[list[TweetResponse]],
    summary="Fetch latest tweets from an X user",
)
async def fetch_user_tweets(
    body: FetchUserTweetsRequest,
    controller: ContentController = Depends(get_content_controller),
):
    result = await controller.fetch_user_tweets(body.username, body.count)
    return SuccessResponse(data=result)


@router.post(
    "/rewrite",
    response_model=SuccessResponse[RewriteResponse],
    summary="Rewrite X tweet content for Facebook using Grok LLM",
)
async def rewrite_content(
    body: RewriteRequest,
    controller: ContentController = Depends(get_content_controller),
):
    result = await controller.rewrite(
        tweet_url=body.tweet_url,
        tweet_text=body.tweet_text,
        custom_prompt=body.custom_prompt,
    )
    return SuccessResponse(data=result)
