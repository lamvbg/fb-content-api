from pydantic import BaseModel, Field


# ── Douyin ───────────────────────────────────────────────────────────────────

class DouyinVideoResponse(BaseModel):
    aweme_id: str
    desc: str
    created_at: str
    nickname: str
    digg_count: int
    comment_count: int
    share_count: int
    collect_count: int
    cover: str
    video_url: str
    douyin_url: str
    score: int


class FetchTrendingRequest(BaseModel):
    pages: int = Field(default=5, ge=1, le=20, description="Number of feed pages to fetch (each ~2 videos)")
    top: int = Field(default=10, ge=1, le=50, description="Number of top videos to return")
    keyword: str | None = Field(default=None, description="Optional keyword filter (matches desc or nickname)")


class FetchDouyinUserRequest(BaseModel):
    sec_user_id: str = Field(..., description="Douyin user sec_uid (from profile URL)")
    count: int = Field(default=10, ge=1, le=30, description="Number of videos")


class FetchMultiUserVideosRequest(BaseModel):
    sec_user_ids: list[str] = Field(..., min_length=1, description="List of Douyin user sec_uid values")
    count_per_user: int = Field(default=5, ge=1, le=20, description="Number of videos to fetch per user")
    top: int = Field(default=10, ge=1, le=50, description="Number of top videos to return (ranked by score)")
    keyword: str | None = Field(default=None, description="Optional keyword filter (matches desc or nickname)")


class FetchDouyinVideoDetailRequest(BaseModel):
    url: str = Field(..., description="Douyin video URL (short link v.douyin.com/xxx or full link douyin.com/video/xxx)")


class DownloadDouyinVideoRequest(BaseModel):
    url: str = Field(..., description="Douyin video URL (short or full link)")
    segment_duration: int = Field(default=5, ge=3, le=7, description="Duration per segment in seconds")
    max_segments: int = Field(default=5, ge=1, le=10, description="Maximum number of segments")


class VideoSegment(BaseModel):
    filename: str
    duration: float
    size_mb: float
    download_url: str


class DownloadDouyinVideoResponse(BaseModel):
    session_id: str
    video_info: DouyinVideoResponse
    original_filename: str
    original_duration: float
    original_size_mb: float
    segment_count: int
    segments: list[VideoSegment]


class SearchDouyinRequest(BaseModel):
    keyword: str = Field(..., description="Search query string")
    count: int = Field(default=10, ge=1, le=20, description="Number of results")
    offset: int = Field(default=0, ge=0, description="Pagination offset")


class HotKeywordsResponse(BaseModel):
    keywords: list[str]


# ── X/Twitter Tweets ─────────────────────────────────────────────────────────

class TweetResponse(BaseModel):
    username: str
    post_url: str
    text: str
    lang: str
    datetime_utc: str
    views: int
    likes: int
    retweets: int
    replies: int
    quotes: int
    bookmarks: int
    followers: int
    media_type: str
    media_src: str
    media_poster: str
    media_mp4: str


class FetchTweetRequest(BaseModel):
    url: str = Field(..., description="X/Twitter post URL")


class FetchUserTweetsRequest(BaseModel):
    username: str = Field(..., description="X/Twitter username (e.g. @elonmusk or elonmusk)")
    count: int = Field(default=10, ge=1, le=50, description="Number of tweets to fetch")


# ── Grok Rewrite ─────────────────────────────────────────────────────────────

class RewriteRequest(BaseModel):
    tweet_url: str | None = Field(default=None, description="X/Twitter post URL to fetch and rewrite")
    tweet_text: str | None = Field(default=None, description="Raw tweet text to rewrite (if no URL)")
    custom_prompt: str | None = Field(default=None, description="Custom system prompt for Grok (optional)")


class RewriteResponse(BaseModel):
    original_text: str
    rewritten_text: str
    tweet_url: str | None = None


# ── Grok KOL Image Generation ────────────────────────────────────────────────

class GenerateKOLImageRequest(BaseModel):
    image_path: str | None = Field(default=None, description="Local path to a reference face image (optional)")
    session_id: str | None = Field(default=None, description="Session ID — saves image into that session's grok/ folder")


class GenerateKOLImageResponse(BaseModel):
    local_filename: str
    local_path: str
    image_url: str
    asset_id: str
    download_url: str


# ── Grok Video Generation ───────────────────────────────────────────────────

class GenerateVideoRequest(BaseModel):
    prompt: str | None = Field(default=None, description="Text prompt describing the video (legacy mode)")
    content: str | None = Field(default=None, description="Source content for KOL dialogue generation — auto-builds the KOL video prompt")
    image_path: str | None = Field(default=None, description="Local path to KOL image from /grok/generate-kol-image (required for KOL mode)")
    session_id: str | None = Field(default=None, description="Session ID from Douyin download — saves video into that session's grok/ folder")
    ratio: str = Field(default="9:16", description="Aspect ratio: '1:1', '16:9', or '9:16'")
    length: int = Field(default=6, description="Video length in seconds: 6 or 10")
    res: str = Field(default="480p", description="Resolution: '480p' or '720p'")
    upscale: bool = Field(default=True, description="Upscale to HD after generation")


class GenerateVideoResponse(BaseModel):
    post_id: str
    video_post_id: str | None = None
    video_url: str
    hd_video_url: str
    local_filename: str
    download_url: str


# ── Video Library (downloads) ────────────────────────────────────────────────

class VideoFileInfo(BaseModel):
    source: str  # "douyin" or "grok"
    filename: str
    size_mb: float
    duration: float
    download_url: str


class SessionVideosResponse(BaseModel):
    session_id: str
    douyin: list[VideoFileInfo]
    grok: list[VideoFileInfo]


class MergeVideosRequest(BaseModel):
    session_id: str = Field(..., description="Session ID")
    filenames: list[str] = Field(
        ..., min_length=2,
        description="List of filenames to merge (in order) — prefix with source, e.g. 'douyin/file.mp4'",
    )


class MergeVideosResponse(BaseModel):
    filename: str
    duration: float
    size_mb: float
    download_url: str


class DeleteVideoRequest(BaseModel):
    session_id: str = Field(..., description="Session ID")
    filenames: list[str] = Field(
        ..., min_length=1,
        description="List of filenames to delete — prefix with source, e.g. 'douyin/file.mp4'",
    )


class DeleteVideoResponse(BaseModel):
    deleted: list[str]
    not_found: list[str]


# ── Grok Prompt Generation ──────────────────────────────────────────────────

class GeneratePromptsRequest(BaseModel):
    content: str = Field(..., description="Source content to generate video prompts from")
    count: int = Field(default=5, ge=1, le=20, description="Number of prompts to generate")
    style: str | None = Field(default=None, description="Optional style hint (e.g. 'cinematic', 'funny', 'dramatic')")


class GeneratePromptsResponse(BaseModel):
    prompts: list[str]


# ── Video Review ────────────────────────────────────────────────────────────

class ReviewVideoRequest(BaseModel):
    session_id: str = Field(..., description="Session ID containing the video")
    filename: str = Field(..., description="Video filename within the session (e.g. 'merged_abc.mp4' or 'douyin/file.mp4')")
    criteria: str = Field(..., description="Review criteria for the content moderator")
    fps: float = Field(default=1.0, ge=0.1, le=5.0, description="Frames to extract per second")
    max_frames: int = Field(default=15, ge=1, le=30, description="Maximum number of frames to send to Grok")


class ReviewVideoResponse(BaseModel):
    filename: str
    frame_count: int
    passed: bool
    score: int
    feedback: str
    issues: list[str]
    raw_response: str


# ── Session List ─────────────────────────────────────────────────────────────

class SessionSummary(BaseModel):
    session_id: str
    created_at: str
    douyin_count: int
    grok_count: int
    merged_files: list[str]   # merged_*.mp4 filenames at session root
    merged_urls: list[str]    # download URLs for merged files


class SessionsListResponse(BaseModel):
    sessions: list[SessionSummary]


class DeleteSessionResponse(BaseModel):
    session_id: str
    deleted: bool


# ── Publish ─────────────────────────────────────────────────────────────────

class PublishVideoRequest(BaseModel):
    session_id: str = Field(..., description="Session ID containing the video")
    filename: str = Field(..., description="Video filename (e.g. 'merged_abc.mp4')")
    profile_id: str = Field(..., description="Browser profile ID (must be logged into target platform)")
    platform: str = Field(default="youtube", description="Target platform: 'youtube'")
    title: str | None = Field(default=None, description="Video title (auto-generated if empty)")
    description: str | None = Field(default=None, description="Video description (auto-generated if empty)")
    tags: list[str] | None = Field(default=None, description="Tags/keywords (auto-generated if empty)")
    visibility: str = Field(default="public", description="Visibility: 'public', 'unlisted', or 'private'")
    schedule_time: str | None = Field(default=None, description="ISO datetime to schedule: 'YYYY-MM-DDTHH:MM:00'")
    timezone: str | None = Field(default=None, description="IANA timezone name e.g. 'Asia/Ho_Chi_Minh'")


class PublishVideoResponse(BaseModel):
    platform: str
    video_url: str
    video_id: str
    title: str
    status: str
    visibility: str
