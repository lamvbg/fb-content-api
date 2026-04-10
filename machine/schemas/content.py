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
    pages: int = Field(default=5, ge=1, le=20, description="Number of feed pages to fetch (each ~10 videos)")
    top: int = Field(default=10, ge=1, le=50, description="Number of top videos to return")


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
