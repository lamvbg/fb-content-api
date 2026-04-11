"""
Content Pipeline — orchestrates the full flow:
  1. Crawl Douyin video → split into segments
  2. User selects/removes segments
  3. Generate Grok video from prompt (based on crawled content)
  4. Human reviews → approve/reject
  5. Merge selected Douyin segment(s) + Grok video → final output
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from core.exceptions.http import BadRequestException, ExternalAPIException
from machine.external.douyin import DouyinService
from machine.external.grok_video import GrokVideoService
from machine.external.video_processor import (
    DOWNLOAD_DIR,
    _get_video_duration,
    merge_videos,
)

logger = logging.getLogger(__name__)


class PipelineStatus(str, Enum):
    CREATED = "created"                    # Douyin video downloaded + split
    SEGMENTS_SELECTED = "segments_selected"  # User picked segments
    VIDEO_GENERATED = "video_generated"    # Grok video ready for review
    APPROVED = "approved"                  # Human approved
    REJECTED = "rejected"                  # Human rejected
    MERGED = "merged"                      # Final video merged


# In-memory pipeline store (keyed by pipeline_id)
_pipelines: dict[str, dict] = {}


def _get_pipeline(pipeline_id: str) -> dict:
    p = _pipelines.get(pipeline_id)
    if not p:
        raise BadRequestException(detail=f"Pipeline '{pipeline_id}' not found")
    return p


class PipelineService:
    """Manages the content creation pipeline."""

    @classmethod
    async def create(
        cls,
        douyin_url: str,
        segment_duration: int = 5,
        max_segments: int = 5,
    ) -> dict:
        """Step 1: Download Douyin video, split into segments.

        Returns pipeline state with segments for user to select.
        """
        # Fetch video detail (includes desc, stats, etc.)
        detail = await DouyinService.fetch_video_detail(douyin_url)
        video_url = detail.get("video_url", "")
        if not video_url:
            raise ExternalAPIException(detail="No downloadable video URL found")

        # Download + split
        from machine.external.video_processor import download_and_split

        cookie = DouyinService._get_cookie()
        filename = detail.get("desc") or detail.get("aweme_id", "video")

        split_result = await download_and_split(
            video_url=video_url,
            filename=filename,
            cookie=cookie,
            segment_duration=segment_duration,
            max_segments=max_segments,
        )

        pipeline_id = uuid.uuid4().hex[:12]

        # Build segment list with indices and selection state
        segments = []
        for i, seg in enumerate(split_result["segments"]):
            segments.append({
                "index": i,
                "filename": seg["filename"],
                "path": seg["path"],
                "duration": seg["duration"],
                "size_mb": seg["size_mb"],
                "selected": True,  # all selected by default
            })

        pipeline = {
            "pipeline_id": pipeline_id,
            "status": PipelineStatus.CREATED,
            "created_at": datetime.now(timezone.utc).isoformat(),
            # Douyin source
            "douyin_detail": detail,
            "original_filename": split_result["original_filename"],
            "original_path": split_result["original_path"],
            "original_duration": split_result["original_duration"],
            "original_size_mb": split_result["original_size_mb"],
            # Segments
            "segments": segments,
            # Grok video (filled later)
            "grok_prompt": None,
            "grok_video": None,
            # Final merged
            "merged_video": None,
        }

        _pipelines[pipeline_id] = pipeline
        return pipeline

    @classmethod
    def get(cls, pipeline_id: str) -> dict:
        """Get current pipeline state."""
        return _get_pipeline(pipeline_id)

    @classmethod
    def list_all(cls) -> list[dict]:
        """List all pipelines (summary only)."""
        result = []
        for p in _pipelines.values():
            result.append({
                "pipeline_id": p["pipeline_id"],
                "status": p["status"],
                "created_at": p["created_at"],
                "douyin_desc": (p["douyin_detail"] or {}).get("desc", "")[:80],
                "segment_count": len(p["segments"]),
                "selected_count": sum(1 for s in p["segments"] if s["selected"]),
            })
        return result

    @classmethod
    def select_segments(
        cls,
        pipeline_id: str,
        selected_indices: list[int] | None = None,
        removed_indices: list[int] | None = None,
    ) -> dict:
        """Step 2: Select which segments to keep or remove.

        Provide either selected_indices (keep these) or
        removed_indices (remove these, keep the rest).
        """
        pipeline = _get_pipeline(pipeline_id)

        if selected_indices is not None:
            for seg in pipeline["segments"]:
                seg["selected"] = seg["index"] in selected_indices
        elif removed_indices is not None:
            for seg in pipeline["segments"]:
                seg["selected"] = seg["index"] not in removed_indices
        else:
            raise BadRequestException(
                detail="Provide either selected_indices or removed_indices"
            )

        # Validate at least one segment is selected
        if not any(s["selected"] for s in pipeline["segments"]):
            raise BadRequestException(detail="At least one segment must be selected")

        pipeline["status"] = PipelineStatus.SEGMENTS_SELECTED
        return pipeline

    @classmethod
    async def generate_video(
        cls,
        pipeline_id: str,
        prompt: str,
        ratio: str = "16:9",
        length: int = 6,
        res: str = "480p",
        upscale: bool = True,
    ) -> dict:
        """Step 3: Generate Grok video from prompt.

        The prompt should describe the character/content for the video.
        User can reference the crawled Douyin content in their prompt.
        """
        pipeline = _get_pipeline(pipeline_id)

        if pipeline["status"] not in (
            PipelineStatus.CREATED,
            PipelineStatus.SEGMENTS_SELECTED,
            PipelineStatus.VIDEO_GENERATED,  # allow re-generation
            PipelineStatus.REJECTED,          # allow retry after rejection
        ):
            raise BadRequestException(
                detail=f"Cannot generate video in status '{pipeline['status']}'"
            )

        result = await GrokVideoService.generate_video(
            prompt=prompt,
            ratio=ratio,
            length=length,
            res=res,
            upscale=upscale,
        )

        pipeline["grok_prompt"] = prompt
        pipeline["grok_video"] = result
        pipeline["status"] = PipelineStatus.VIDEO_GENERATED
        return pipeline

    @classmethod
    def review(cls, pipeline_id: str, approved: bool) -> dict:
        """Step 4: Human approves or rejects the generated content."""
        pipeline = _get_pipeline(pipeline_id)

        if pipeline["status"] != PipelineStatus.VIDEO_GENERATED:
            raise BadRequestException(
                detail=f"Cannot review in status '{pipeline['status']}'. "
                "Generate video first."
            )

        pipeline["status"] = (
            PipelineStatus.APPROVED if approved else PipelineStatus.REJECTED
        )
        return pipeline

    @classmethod
    async def merge(cls, pipeline_id: str) -> dict:
        """Step 5: Merge selected Douyin segments + Grok video → final output."""
        pipeline = _get_pipeline(pipeline_id)

        if pipeline["status"] != PipelineStatus.APPROVED:
            raise BadRequestException(
                detail=f"Cannot merge in status '{pipeline['status']}'. "
                "Pipeline must be approved first."
            )

        # Collect selected Douyin segment paths
        douyin_paths = [
            s["path"] for s in pipeline["segments"] if s["selected"]
        ]

        # Grok video path
        grok_video = pipeline.get("grok_video") or {}
        grok_filename = grok_video.get("local_filename", "")
        grok_path = str(DOWNLOAD_DIR / grok_filename) if grok_filename else ""

        if not grok_path or not os.path.exists(grok_path):
            raise ExternalAPIException(
                detail="Grok video file not found. Re-generate the video."
            )

        # Validate Douyin segments exist
        valid_douyin = [p for p in douyin_paths if os.path.exists(p)]
        if not valid_douyin:
            raise ExternalAPIException(
                detail="Selected Douyin segments not found on disk."
            )

        # Merge: Douyin segments first, then Grok video
        all_paths = valid_douyin + [grok_path]

        output_filename = f"final_{pipeline_id}.mp4"
        merged_path = await asyncio.to_thread(
            merge_videos, all_paths, output_filename
        )

        duration = _get_video_duration(merged_path)
        size_mb = os.path.getsize(merged_path) / 1024 / 1024

        pipeline["merged_video"] = {
            "filename": os.path.basename(merged_path),
            "path": merged_path,
            "duration": round(duration, 1),
            "size_mb": round(size_mb, 2),
        }
        pipeline["status"] = PipelineStatus.MERGED
        return pipeline

    @classmethod
    def delete(cls, pipeline_id: str) -> bool:
        """Delete a pipeline from memory."""
        if pipeline_id in _pipelines:
            del _pipelines[pipeline_id]
            return True
        return False
