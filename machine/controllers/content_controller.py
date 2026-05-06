import asyncio
import gc
import os
import shutil
import time
from pathlib import Path

from core.exceptions.http import BadRequestException
from machine.external.douyin import DouyinService
from machine.external.grok import GrokService
from machine.external.grok_chat import GrokChatService, build_kol_video_prompt
from machine.external.grok_video import GrokVideoService
from machine.external.video_processor import DOWNLOAD_DIR, _get_video_duration, extract_frames, merge_videos
from machine.external.x_api import XService
from machine.external.youtube import YouTubeService


class ContentController:
    """Handles fetching X tweets, Douyin videos, and rewriting with Grok LLM."""

    # ── Douyin ───────────────────────────────────────────────────────────

    @staticmethod
    async def fetch_douyin_trending(
        pages: int = 5, top: int = 10, keyword: str | None = None
    ) -> list[dict]:
        return await DouyinService.fetch_trending(pages=pages, top=top, keyword=keyword)

    @staticmethod
    async def fetch_douyin_user_videos(sec_user_id: str, count: int = 10) -> list[dict]:
        return await DouyinService.fetch_user_videos(sec_user_id=sec_user_id, count=count)

    @staticmethod
    async def fetch_multi_user_videos(
        sec_user_ids: list[str], count_per_user: int = 5,
        top: int = 10, keyword: str | None = None,
    ) -> list[dict]:
        return await DouyinService.fetch_multi_user_videos(
            sec_user_ids=sec_user_ids, count_per_user=count_per_user,
            top=top, keyword=keyword,
        )

    @staticmethod
    async def fetch_douyin_video_detail(url: str) -> dict:
        return await DouyinService.fetch_video_detail(url=url)

    @staticmethod
    async def download_douyin_video(
        url: str, segment_duration: int = 5, max_segments: int = 5,
    ) -> dict:
        return await DouyinService.download_video(
            url=url, segment_duration=segment_duration, max_segments=max_segments,
        )

    @staticmethod
    async def search_douyin_videos(
        keyword: str, count: int = 10, offset: int = 0
    ) -> list[dict]:
        return await DouyinService.search_videos(
            keyword=keyword, count=count, offset=offset
        )

    @staticmethod
    async def fetch_douyin_hot_keywords() -> dict:
        keywords = await DouyinService.fetch_hot_keywords()
        return {"keywords": keywords}

    # ── X/Twitter ────────────────────────────────────────────────────────

    @staticmethod
    async def fetch_tweet(url: str) -> dict:
        return await XService.fetch_tweet(url)

    @staticmethod
    async def fetch_user_tweets(username: str, count: int = 10) -> list[dict]:
        return await XService.fetch_user_tweets(username, count)

    # ── Grok KOL Image ─────────────────────────────────────────────────

    @staticmethod
    async def generate_kol_image(
        image_path: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        return await GrokChatService.generate_kol_image(
            image_path=image_path,
            session_id=session_id,
        )

    # ── Grok Video ─────────────────────────────────────────────────────

    @staticmethod
    async def generate_video(
        prompt: str | None = None,
        content: str | None = None,
        image_path: str | None = None,
        session_id: str | None = None,
        ratio: str = "16:9", length: int = 6,
        res: str = "480p", upscale: bool = True,
    ) -> dict:
        if content and not prompt:
            prompt = build_kol_video_prompt(content)
        if not prompt:
            raise BadRequestException(detail="Either 'prompt' or 'content' must be provided")
        return await GrokVideoService.generate_video(
            prompt=prompt, ratio=ratio, length=length, res=res,
            upscale=upscale, session_id=session_id, image_path=image_path,
        )

    # ── Video Library (session-based) ─────────────────────────────────

    @staticmethod
    def list_sessions() -> list[dict]:
        """Scan downloads/ and return a summary of every session directory."""
        from datetime import datetime
        sessions = []
        if not DOWNLOAD_DIR.exists():
            return sessions
        for session_dir in sorted(DOWNLOAD_DIR.iterdir(), reverse=True):
            if not session_dir.is_dir():
                continue
            created_at = datetime.fromtimestamp(session_dir.stat().st_ctime).isoformat()
            douyin_count = len(list((session_dir / "douyin").glob("*.mp4"))) if (session_dir / "douyin").exists() else 0
            grok_count = len(list((session_dir / "grok").glob("*.mp4"))) if (session_dir / "grok").exists() else 0
            merged = sorted(session_dir.glob("merged_*.mp4"))
            sessions.append({
                "session_id": session_dir.name,
                "created_at": created_at,
                "douyin_count": douyin_count,
                "grok_count": grok_count,
                "merged_files": [f.name for f in merged],
                "merged_urls": [],   # filled in by the router with base_url
            })
        return sessions

    @staticmethod
    def _list_mp4(directory: Path) -> list[dict]:
        """List .mp4 files in a directory with metadata."""
        if not directory.exists():
            return []
        files = []
        for f in sorted(directory.glob("*.mp4")):
            size_mb = f.stat().st_size / 1024 / 1024
            duration = _get_video_duration(str(f))
            files.append({
                "filename": f.name,
                "size_mb": round(size_mb, 2),
                "duration": round(duration, 1),
            })
        return files

    @staticmethod
    def list_session_videos(session_id: str) -> dict:
        """List all videos in a session, grouped by source."""
        session_dir = DOWNLOAD_DIR / session_id
        if not session_dir.exists():
            raise BadRequestException(detail=f"Session {session_id} not found")

        douyin_files = ContentController._list_mp4(session_dir / "douyin")
        for f in douyin_files:
            f["source"] = "douyin"

        grok_files = ContentController._list_mp4(session_dir / "grok")
        for f in grok_files:
            f["source"] = "grok"

        return {
            "session_id": session_id,
            "douyin": douyin_files,
            "grok": grok_files,
        }

    @staticmethod
    async def merge_videos(session_id: str, filenames: list[str]) -> dict:
        """Merge video files within a session."""
        session_dir = DOWNLOAD_DIR / session_id
        paths = []
        for name in filenames:
            p = session_dir / name
            if not p.exists():
                raise BadRequestException(detail=f"File not found: {name}")
            paths.append(str(p))

        merged_path = await asyncio.to_thread(
            merge_videos, paths, session_id,
        )
        merged_file = Path(merged_path)
        size_mb = merged_file.stat().st_size / 1024 / 1024
        duration = _get_video_duration(merged_path)
        return {
            "filename": merged_file.name,
            "size_mb": round(size_mb, 2),
            "duration": round(duration, 1),
        }

    @staticmethod
    def delete_videos(session_id: str, filenames: list[str]) -> dict:
        """Delete video files within a session."""
        session_dir = DOWNLOAD_DIR / session_id
        deleted = []
        not_found = []
        for name in filenames:
            p = session_dir / name
            if p.exists():
                p.unlink()
                deleted.append(name)
            else:
                not_found.append(name)
        return {"deleted": deleted, "not_found": not_found}

    @staticmethod
    def delete_session(session_id: str) -> dict:
        """Delete an entire session directory."""
        session_dir = DOWNLOAD_DIR / session_id
        if not session_dir.exists():
            raise BadRequestException(detail=f"Session {session_id} not found")

        def _on_rm_error(_func, path, _exc_info):
            """Handle locked files on Windows (e.g. StaticFiles mount)."""
            try:
                os.chmod(path, 0o777)
                gc.collect()
                time.sleep(0.1)
                os.unlink(path)
            except OSError:
                pass  # will be retried or skipped

        shutil.rmtree(session_dir, onexc=_on_rm_error)
        return {"session_id": session_id, "deleted": True}

    # ── Grok Prompts ────────────────────────────────────────────────────

    @staticmethod
    async def generate_prompts(
        content: str, count: int = 5, style: str | None = None
    ) -> list[str]:
        return await GrokChatService.generate_prompts(
            content=content, count=count, style=style,
        )

    # ── Grok Video Review ──────────────────────────────────────────────

    @staticmethod
    async def review_video(
        session_id: str,
        filename: str,
        criteria: str,
        fps: float = 1.0,
        max_frames: int = 15,
    ) -> dict:
        """Extract frames from a video and send to Grok for content review."""
        video_path = DOWNLOAD_DIR / session_id / filename
        if not video_path.exists():
            raise BadRequestException(detail=f"Video not found: {filename}")

        frames_dir = DOWNLOAD_DIR / session_id / "frames"
        try:
            frame_paths = await asyncio.to_thread(
                extract_frames, str(video_path), str(frames_dir), fps, max_frames,
            )
            result = await GrokChatService.review_video(frame_paths, criteria)
            result["filename"] = filename
            result["frame_count"] = len(frame_paths)
            return result
        finally:
            if frames_dir.exists():
                shutil.rmtree(frames_dir, ignore_errors=True)

    # ── Grok Rewrite ─────────────────────────────────────────────────────

    @staticmethod
    async def rewrite(
        tweet_url: str | None = None,
        tweet_text: str | None = None,
        custom_prompt: str | None = None,
    ) -> dict:
        if not tweet_url and not tweet_text:
            raise BadRequestException(detail="Provide either tweet_url or tweet_text")

        original_text = tweet_text or ""

        if tweet_url:
            tweet = await XService.fetch_tweet(tweet_url)
            original_text = tweet["text"]

        if custom_prompt:
            rewritten = await GrokService.rewrite_custom(original_text, custom_prompt)
        else:
            rewritten = await GrokService.rewrite_for_facebook(original_text, tweet_url or "")

        return {
            "original_text": original_text,
            "rewritten_text": rewritten,
            "tweet_url": tweet_url,
        }

    # ── Publish Video ─────────────────────────────────────────────────

    @staticmethod
    async def publish_video(
        session_id: str,
        filename: str,
        profile_id: str,
        platform: str = "youtube",
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        visibility: str = "public",
        schedule_time: str | None = None,
        timezone: str | None = None,
    ) -> dict:
        """Publish a video to a platform via browser automation."""
        video_path = DOWNLOAD_DIR / session_id / filename
        if not video_path.exists():
            raise BadRequestException(detail=f"Video not found: {filename}")

        # Auto-generate metadata if not provided
        if not title or not description or not tags:
            generated = await GrokChatService.chat(
                f"Generate YouTube video metadata for a short video.\n"
                f"Video filename: {filename}\n\n"
                f"Respond in this exact JSON format, no other text:\n"
                f'{{"title": "catchy title under 100 chars", '
                f'"description": "engaging description 2-3 sentences", '
                f'"tags": ["tag1", "tag2", "tag3", "tag4", "tag5"]}}',
                force_concise=True,
            )
            import json
            import re
            try:
                match = re.search(r"\{[\s\S]*\}", generated.get("message", ""))
                if match:
                    meta = json.loads(match.group())
                    title = title or meta.get("title", filename)
                    description = description or meta.get("description", "")
                    tags = tags or meta.get("tags", [])
            except (json.JSONDecodeError, ValueError):
                pass

        title = title or filename
        description = description or ""

        abs_path = str(video_path.resolve())

        if platform == "youtube":
            return await YouTubeService.upload_video(
                profile_id=profile_id,
                video_path=abs_path,
                title=title,
                description=description,
                tags=tags,
                visibility=visibility,
                schedule_time=schedule_time,
                timezone=timezone,
            )

        raise BadRequestException(detail=f"Unsupported platform: {platform}")
