from pydantic import BaseModel, Field


# ── Segment ──────────────────────────────────────────────────────────────────

class SegmentInfo(BaseModel):
    index: int
    filename: str
    duration: float
    size_mb: float
    selected: bool
    download_url: str = ""


# ── Requests ─────────────────────────────────────────────────────────────────

class CreatePipelineRequest(BaseModel):
    douyin_url: str = Field(..., description="Douyin video URL (short or full)")
    segment_duration: int = Field(default=5, ge=3, le=7, description="Seconds per segment")
    max_segments: int = Field(default=5, ge=1, le=10, description="Max segments to produce")


class SelectSegmentsRequest(BaseModel):
    selected_indices: list[int] | None = Field(
        default=None,
        description="Segment indices to KEEP (others will be deselected)",
    )
    removed_indices: list[int] | None = Field(
        default=None,
        description="Segment indices to REMOVE (others stay selected)",
    )


class GeneratePipelineVideoRequest(BaseModel):
    prompt: str = Field(..., description="Text prompt for Grok video generation")
    ratio: str = Field(default="16:9", description="Aspect ratio: '1:1', '16:9', or '9:16'")
    length: int = Field(default=6, description="Video length: 6 or 10 seconds")
    res: str = Field(default="480p", description="Resolution: '480p' or '720p'")
    upscale: bool = Field(default=True, description="Upscale to HD")


class ReviewRequest(BaseModel):
    approved: bool = Field(..., description="True to approve, False to reject")


# ── Responses ────────────────────────────────────────────────────────────────

class DouyinSourceInfo(BaseModel):
    aweme_id: str
    desc: str
    nickname: str
    douyin_url: str


class GrokVideoInfo(BaseModel):
    post_id: str
    video_url: str
    hd_video_url: str
    local_filename: str
    download_url: str = ""


class MergedVideoInfo(BaseModel):
    filename: str
    duration: float
    size_mb: float
    download_url: str = ""


class PipelineResponse(BaseModel):
    pipeline_id: str
    status: str
    created_at: str
    # Douyin source
    douyin_source: DouyinSourceInfo | None = None
    original_duration: float = 0
    original_size_mb: float = 0
    # Segments
    segments: list[SegmentInfo] = []
    # Grok
    grok_prompt: str | None = None
    grok_video: GrokVideoInfo | None = None
    # Merged
    merged_video: MergedVideoInfo | None = None


class PipelineSummary(BaseModel):
    pipeline_id: str
    status: str
    created_at: str
    douyin_desc: str = ""
    segment_count: int = 0
    selected_count: int = 0
