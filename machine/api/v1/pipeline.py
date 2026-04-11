from fastapi import APIRouter, Request

from core.response.base import SuccessResponse
from machine.external.pipeline import PipelineService
from machine.schemas.pipeline import (
    CreatePipelineRequest,
    GeneratePipelineVideoRequest,
    GrokVideoInfo,
    MergedVideoInfo,
    PipelineResponse,
    PipelineSummary,
    ReviewRequest,
    SegmentInfo,
    SelectSegmentsRequest,
    DouyinSourceInfo,
)

router = APIRouter(prefix="/pipeline", tags=["Pipeline"])


def _build_response(pipeline: dict, base_url: str) -> PipelineResponse:
    """Convert internal pipeline dict to API response with download URLs."""
    detail = pipeline.get("douyin_detail") or {}

    segments = []
    for seg in pipeline.get("segments", []):
        segments.append(SegmentInfo(
            index=seg["index"],
            filename=seg["filename"],
            duration=seg["duration"],
            size_mb=seg["size_mb"],
            selected=seg["selected"],
            download_url=f"{base_url}/downloads/{seg['filename']}",
        ))

    grok_video = None
    gv = pipeline.get("grok_video")
    if gv:
        grok_video = GrokVideoInfo(
            post_id=gv.get("post_id", ""),
            video_url=gv.get("video_url", ""),
            hd_video_url=gv.get("hd_video_url", ""),
            local_filename=gv.get("local_filename", ""),
            download_url=(
                f"{base_url}/downloads/{gv['local_filename']}"
                if gv.get("local_filename") else ""
            ),
        )

    merged_video = None
    mv = pipeline.get("merged_video")
    if mv:
        merged_video = MergedVideoInfo(
            filename=mv["filename"],
            duration=mv["duration"],
            size_mb=mv["size_mb"],
            download_url=f"{base_url}/downloads/{mv['filename']}",
        )

    return PipelineResponse(
        pipeline_id=pipeline["pipeline_id"],
        status=pipeline["status"],
        created_at=pipeline["created_at"],
        douyin_source=DouyinSourceInfo(
            aweme_id=detail.get("aweme_id", ""),
            desc=detail.get("desc", ""),
            nickname=detail.get("nickname", ""),
            douyin_url=detail.get("douyin_url", ""),
        ) if detail else None,
        original_duration=pipeline.get("original_duration", 0),
        original_size_mb=pipeline.get("original_size_mb", 0),
        segments=segments,
        grok_prompt=pipeline.get("grok_prompt"),
        grok_video=grok_video,
        merged_video=merged_video,
    )


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=SuccessResponse[list[PipelineSummary]],
    summary="List all pipelines",
)
async def list_pipelines():
    return SuccessResponse(data=PipelineService.list_all())


@router.post(
    "/create",
    response_model=SuccessResponse[PipelineResponse],
    summary="Step 1: Download Douyin video and split into segments",
)
async def create_pipeline(body: CreatePipelineRequest, request: Request):
    pipeline = await PipelineService.create(
        douyin_url=body.douyin_url,
        segment_duration=body.segment_duration,
        max_segments=body.max_segments,
    )
    base_url = str(request.base_url).rstrip("/")
    return SuccessResponse(data=_build_response(pipeline, base_url))


@router.get(
    "/{pipeline_id}",
    response_model=SuccessResponse[PipelineResponse],
    summary="Get pipeline state",
)
async def get_pipeline(pipeline_id: str, request: Request):
    pipeline = PipelineService.get(pipeline_id)
    base_url = str(request.base_url).rstrip("/")
    return SuccessResponse(data=_build_response(pipeline, base_url))


@router.post(
    "/{pipeline_id}/select-segments",
    response_model=SuccessResponse[PipelineResponse],
    summary="Step 2: Select or remove segments (keep/remove by index)",
)
async def select_segments(
    pipeline_id: str, body: SelectSegmentsRequest, request: Request,
):
    pipeline = PipelineService.select_segments(
        pipeline_id=pipeline_id,
        selected_indices=body.selected_indices,
        removed_indices=body.removed_indices,
    )
    base_url = str(request.base_url).rstrip("/")
    return SuccessResponse(data=_build_response(pipeline, base_url))


@router.post(
    "/{pipeline_id}/generate-video",
    response_model=SuccessResponse[PipelineResponse],
    summary="Step 3: Generate Grok video from prompt",
)
async def generate_pipeline_video(
    pipeline_id: str, body: GeneratePipelineVideoRequest, request: Request,
):
    pipeline = await PipelineService.generate_video(
        pipeline_id=pipeline_id,
        prompt=body.prompt,
        ratio=body.ratio,
        length=body.length,
        res=body.res,
        upscale=body.upscale,
    )
    base_url = str(request.base_url).rstrip("/")
    return SuccessResponse(data=_build_response(pipeline, base_url))


@router.post(
    "/{pipeline_id}/review",
    response_model=SuccessResponse[PipelineResponse],
    summary="Step 4: Approve or reject the generated content",
)
async def review_pipeline(
    pipeline_id: str, body: ReviewRequest, request: Request,
):
    pipeline = PipelineService.review(
        pipeline_id=pipeline_id,
        approved=body.approved,
    )
    base_url = str(request.base_url).rstrip("/")
    return SuccessResponse(data=_build_response(pipeline, base_url))


@router.post(
    "/{pipeline_id}/merge",
    response_model=SuccessResponse[PipelineResponse],
    summary="Step 5: Merge selected Douyin segments + Grok video → final output",
)
async def merge_pipeline(pipeline_id: str, request: Request):
    pipeline = await PipelineService.merge(pipeline_id=pipeline_id)
    base_url = str(request.base_url).rstrip("/")
    return SuccessResponse(data=_build_response(pipeline, base_url))


@router.delete(
    "/{pipeline_id}",
    summary="Delete a pipeline",
)
async def delete_pipeline(pipeline_id: str):
    deleted = PipelineService.delete(pipeline_id)
    return SuccessResponse(data={"deleted": deleted})
