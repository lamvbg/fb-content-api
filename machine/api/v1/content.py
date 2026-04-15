from fastapi import APIRouter, Depends, Request

from core.response.base import SuccessResponse
from machine.controllers.content_controller import ContentController
from machine.providers.content_provider import get_content_controller
from machine.schemas.content import (
    DeleteVideoRequest,
    DeleteVideoResponse,
    DownloadDouyinVideoRequest,
    DownloadDouyinVideoResponse,
    DouyinVideoResponse,
    FetchDouyinUserRequest,
    FetchDouyinVideoDetailRequest,
    FetchMultiUserVideosRequest,
    FetchTrendingRequest,
    FetchTweetRequest,
    FetchUserTweetsRequest,
    GeneratePromptsRequest,
    GeneratePromptsResponse,
    GenerateVideoRequest,
    GenerateVideoResponse,
    HotKeywordsResponse,
    MergeVideosRequest,
    MergeVideosResponse,
    DeleteSessionResponse,
    PublishVideoRequest,
    PublishVideoResponse,
    ReviewVideoRequest,
    ReviewVideoResponse,
    RewriteRequest,
    RewriteResponse,
    SearchDouyinRequest,
    SessionSummary,
    SessionVideosResponse,
    SessionsListResponse,
    TweetResponse,
)

router = APIRouter(prefix="/content", tags=["Content"])


# ── Douyin ───────────────────────────────────────────────────────────────────

@router.post(
    "/douyin/trending",
    response_model=SuccessResponse[list[DouyinVideoResponse]],
    summary="Fetch trending Douyin videos — optionally filter by keyword",
)
async def fetch_douyin_trending(
    body: FetchTrendingRequest,
    controller: ContentController = Depends(get_content_controller),
):
    result = await controller.fetch_douyin_trending(
        pages=body.pages, top=body.top, keyword=body.keyword
    )
    return SuccessResponse(data=result)


@router.post(
    "/douyin/user-videos",
    response_model=SuccessResponse[list[DouyinVideoResponse]],
    summary="Fetch videos from a specific Douyin user",
)
async def fetch_douyin_user_videos(
    body: FetchDouyinUserRequest,
    controller: ContentController = Depends(get_content_controller),
):
    result = await controller.fetch_douyin_user_videos(
        sec_user_id=body.sec_user_id, count=body.count
    )
    return SuccessResponse(data=result)


@router.post(
    "/douyin/multi-user-videos",
    response_model=SuccessResponse[list[DouyinVideoResponse]],
    summary="Fetch latest videos from multiple Douyin users, ranked by score",
)
async def fetch_multi_user_videos(
    body: FetchMultiUserVideosRequest,
    controller: ContentController = Depends(get_content_controller),
):
    result = await controller.fetch_multi_user_videos(
        sec_user_ids=body.sec_user_ids,
        count_per_user=body.count_per_user,
        top=body.top,
        keyword=body.keyword,
    )
    return SuccessResponse(data=result)


@router.post(
    "/douyin/video-detail",
    response_model=SuccessResponse[DouyinVideoResponse],
    summary="Parse a Douyin video URL and return video details",
)
async def fetch_douyin_video_detail(
    body: FetchDouyinVideoDetailRequest,
    controller: ContentController = Depends(get_content_controller),
):
    result = await controller.fetch_douyin_video_detail(url=body.url)
    return SuccessResponse(data=result)


@router.post(
    "/douyin/download",
    response_model=SuccessResponse[DownloadDouyinVideoResponse],
    summary="Download a Douyin video and split into short segments (3-7s each)",
)
async def download_douyin_video(
    body: DownloadDouyinVideoRequest,
    request: Request,
    controller: ContentController = Depends(get_content_controller),
):
    result = await controller.download_douyin_video(
        url=body.url,
        segment_duration=body.segment_duration,
        max_segments=body.max_segments,
    )

    # Build download URLs for segments
    base_url = str(request.base_url).rstrip("/")
    sid = result["session_id"]
    for seg in result["segments"]:
        seg["download_url"] = f"{base_url}/downloads/{sid}/douyin/{seg['filename']}"
        del seg["path"]

    return SuccessResponse(data=result)


@router.post(
    "/douyin/search",
    response_model=SuccessResponse[list[DouyinVideoResponse]],
    summary="Search Douyin videos by keyword",
)
async def search_douyin_videos(
    body: SearchDouyinRequest,
    controller: ContentController = Depends(get_content_controller),
):
    result = await controller.search_douyin_videos(
        keyword=body.keyword, count=body.count, offset=body.offset
    )
    return SuccessResponse(data=result)


@router.get(
    "/douyin/hot-keywords",
    response_model=SuccessResponse[HotKeywordsResponse],
    summary="Fetch current hot search keywords from Douyin",
)
async def fetch_douyin_hot_keywords(
    controller: ContentController = Depends(get_content_controller),
):
    result = await controller.fetch_douyin_hot_keywords()
    return SuccessResponse(data=result)


# ── X/Twitter ────────────────────────────────────────────────────────────────

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


# ── Grok Video Generation ────────────────────────────────────────────────────

@router.post(
    "/grok/generate-video",
    response_model=SuccessResponse[GenerateVideoResponse],
    summary="Generate a video from a text prompt using Grok",
)
async def generate_video(
    body: GenerateVideoRequest,
    request: Request,
    controller: ContentController = Depends(get_content_controller),
):
    result = await controller.generate_video(
        prompt=body.prompt,
        session_id=body.session_id,
        ratio=body.ratio,
        length=body.length,
        res=body.res,
        upscale=body.upscale,
    )

    # Build download URL if file was saved locally
    base_url = str(request.base_url).rstrip("/")
    if result.get("local_filename") and body.session_id:
        result["download_url"] = f"{base_url}/downloads/{body.session_id}/grok/{result['local_filename']}"
    elif result.get("local_filename"):
        result["download_url"] = f"{base_url}/downloads/{result['local_filename']}"
    else:
        result["download_url"] = ""

    return SuccessResponse(data=result)


# ── Video Library (session-based) ────────────────────────────────────────────

@router.get(
    "/sessions",
    response_model=SuccessResponse[SessionsListResponse],
    summary="List all sessions in the downloads directory",
)
async def list_sessions(
    request: Request,
    controller: ContentController = Depends(get_content_controller),
):
    base_url = str(request.base_url).rstrip("/")
    sessions = controller.list_sessions()
    for s in sessions:
        sid = s["session_id"]
        s["merged_urls"] = [
            f"{base_url}/downloads/{sid}/{fname}"
            for fname in s["merged_files"]
        ]
    return SuccessResponse(data={"sessions": sessions})


@router.get(
    "/videos/{session_id}",
    response_model=SuccessResponse[SessionVideosResponse],
    summary="List all videos in a session, grouped by source (douyin/grok)",
)
async def list_session_videos(
    session_id: str,
    request: Request,
    controller: ContentController = Depends(get_content_controller),
):
    result = controller.list_session_videos(session_id)
    base_url = str(request.base_url).rstrip("/")
    for f in result["douyin"]:
        f["download_url"] = f"{base_url}/downloads/{session_id}/douyin/{f['filename']}"
    for f in result["grok"]:
        f["download_url"] = f"{base_url}/downloads/{session_id}/grok/{f['filename']}"
    return SuccessResponse(data=result)


@router.post(
    "/videos/merge",
    response_model=SuccessResponse[MergeVideosResponse],
    summary="Merge videos within a session (prefix filenames with source, e.g. 'douyin/file.mp4')",
)
async def merge_videos(
    body: MergeVideosRequest,
    request: Request,
    controller: ContentController = Depends(get_content_controller),
):
    result = await controller.merge_videos(
        session_id=body.session_id, filenames=body.filenames,
    )
    base_url = str(request.base_url).rstrip("/")
    result["download_url"] = f"{base_url}/downloads/{body.session_id}/{result['filename']}"
    return SuccessResponse(data=result)


@router.post(
    "/videos/delete",
    response_model=SuccessResponse[DeleteVideoResponse],
    summary="Delete video files within a session (prefix filenames with source, e.g. 'douyin/file.mp4')",
)
async def delete_videos(
    body: DeleteVideoRequest,
    controller: ContentController = Depends(get_content_controller),
):
    result = controller.delete_videos(
        session_id=body.session_id, filenames=body.filenames,
    )
    return SuccessResponse(data=result)


@router.delete(
    "/videos/session/{session_id}",
    response_model=SuccessResponse[DeleteSessionResponse],
    summary="Delete an entire session and all its videos",
)
async def delete_session(
    session_id: str,
    controller: ContentController = Depends(get_content_controller),
):
    result = controller.delete_session(session_id)
    return SuccessResponse(data=result)


# ── Video Review ─────────────────────────────────────────────────────────

@router.post(
    "/videos/review",
    response_model=SuccessResponse[ReviewVideoResponse],
    summary="Review a video using Grok AI content moderation (extracts frames and sends to Grok)",
)
async def review_video(
    body: ReviewVideoRequest,
    controller: ContentController = Depends(get_content_controller),
):
    result = await controller.review_video(
        session_id=body.session_id,
        filename=body.filename,
        criteria=body.criteria,
        fps=body.fps,
        max_frames=body.max_frames,
    )
    return SuccessResponse(data=result)


# ── Grok Prompts ─────────────────────────────────────────────────────────

@router.post(
    "/grok/generate-prompts",
    response_model=SuccessResponse[GeneratePromptsResponse],
    summary="Generate video prompts from content using Grok chat",
)
async def generate_prompts(
    body: GeneratePromptsRequest,
    controller: ContentController = Depends(get_content_controller),
):
    prompts = await controller.generate_prompts(
        content=body.content, count=body.count, style=body.style,
    )
    return SuccessResponse(data={"prompts": prompts})


# ── Grok Rewrite ─────────────────────────────────────────────────────────────

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


# ── Publish Video ────��────────────────────��─────────────────────────────────

@router.post(
    "/videos/publish",
    response_model=SuccessResponse[PublishVideoResponse],
    summary="Publish a video to YouTube (or other platforms) via browser automation",
)
async def publish_video(
    body: PublishVideoRequest,
    controller: ContentController = Depends(get_content_controller),
):
    result = await controller.publish_video(
        session_id=body.session_id,
        filename=body.filename,
        profile_id=body.profile_id,
        platform=body.platform,
        title=body.title,
        description=body.description,
        tags=body.tags,
        visibility=body.visibility,
    )
    return SuccessResponse(data=result)


@router.get(
    "/browser/profiles",
    summary="List all browser profiles from local anti-detect browser API",
)
async def list_browser_profiles():
    """Proxy to local browser API — returns profile list using configured BROWSER_API_URL."""
    import httpx
    from fastapi import HTTPException
    from machine.external.browser import BrowserService
    from core.settings import get_settings
    s = get_settings()
    try:
        data = await BrowserService._api_get("/profiles")
        return SuccessResponse(data=data)
    except (httpx.ConnectError, httpx.TimeoutException):
        raise HTTPException(
            status_code=503,
            detail=f"Cannot connect to browser API at {s.BROWSER_API_URL}. Make sure the anti-detect browser tool is running."
        )


@router.get(
    "/browser/health",
    summary="Check if local anti-detect browser API is reachable",
)
async def browser_health():
    import httpx
    from core.settings import get_settings
    s = get_settings()
    url = s.BROWSER_API_URL.replace("/api", "").rstrip("/") + "/health"
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(url)
        return SuccessResponse(data={"available": resp.status_code < 500, "url": s.BROWSER_API_URL})
    except Exception:
        return SuccessResponse(data={"available": False, "url": s.BROWSER_API_URL})


@router.get(
    "/browser/test/{profile_id}",
    summary="Test browser profile connection — launch, connect CDP, verify YouTube login",
)
async def test_browser_connection(profile_id: str):
    import asyncio
    import time as _time
    from machine.external.browser import BrowserService

    try:
        ws_endpoint = await BrowserService.get_cdp_endpoint(profile_id)

        def _test_sync():
            pw, _browser, _context, page = BrowserService.connect_sync(ws_endpoint)
            try:
                url = page.url
                title = page.title()

                page.goto("https://studio.youtube.com", wait_until="networkidle", timeout=30000)
                _time.sleep(2)
                yt_url = page.url
                yt_title = page.title()
                logged_in = "studio.youtube.com" in yt_url and "accounts.google" not in yt_url

                return {
                    "profile_id": profile_id,
                    "connected": True,
                    "initial_url": url,
                    "initial_title": title,
                    "youtube_url": yt_url,
                    "youtube_title": yt_title,
                    "youtube_logged_in": logged_in,
                }
            finally:
                pw.stop()

        result = await asyncio.to_thread(_test_sync)
        return SuccessResponse(data=result)
    except Exception as e:
        import traceback
        return SuccessResponse(data={
            "profile_id": profile_id,
            "connected": False,
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        })


# ── App Settings (browser API URL) ───────────────────────────────────────────

@router.get("/settings", summary="Get current app settings")
async def get_app_settings():
    from core.settings import get_settings
    s = get_settings()
    return SuccessResponse(data={"browser_api_url": s.BROWSER_API_URL})


@router.post("/settings", summary="Update app settings (writes to .env, reloads config)")
async def update_app_settings(body: dict):
    import os
    import re
    from core.settings import get_settings

    browser_api_url = (body.get("browser_api_url") or "").strip()
    if not browser_api_url:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="browser_api_url is required")

    # Read/create .env in cwd
    env_path = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_path):
        content = open(env_path, "r", encoding="utf-8").read()
    else:
        content = ""

    key = "BROWSER_API_URL"
    new_line = f'{key}={browser_api_url}'
    if re.search(rf'^{key}\s*=', content, re.MULTILINE):
        content = re.sub(rf'^{key}\s*=.*$', new_line, content, flags=re.MULTILINE)
    else:
        content = content.rstrip("\n") + "\n" + new_line + "\n"

    with open(env_path, "w", encoding="utf-8") as f:
        f.write(content)

    # Reload settings cache
    get_settings.cache_clear()

    s = get_settings()
    return SuccessResponse(data={"browser_api_url": s.BROWSER_API_URL, "saved": True})
