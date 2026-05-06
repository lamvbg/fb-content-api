"""
Video download and split service.
Downloads Douyin videos and optionally splits them into short segments.
"""

import asyncio
import logging
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

import httpx

from core.exceptions.http import ExternalAPIException

logger = logging.getLogger(__name__)

# Use imageio-ffmpeg's bundled ffmpeg binary
try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG = "ffmpeg"

DOWNLOAD_DIR = Path("downloads")


def _safe_filename(s: str, max_len: int = 50) -> str:
    s = re.sub(r'[\\/:*?"<>|#\n\r\t]', "_", s)
    return s[:max_len].strip("_. ") or "video"


def _get_video_duration(filepath: str) -> float:
    """Get video duration in seconds using ffmpeg."""
    try:
        result = subprocess.run(
            [FFMPEG, "-i", filepath],
            capture_output=True, timeout=30,
        )
        stderr = result.stderr.decode("utf-8", errors="replace")
        import re as _re
        m = _re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", stderr)
        if m:
            h, mi, s, ms = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            return h * 3600 + mi * 60 + s + ms / 100
    except Exception as e:
        logger.warning("ffmpeg duration error: %s", e)
    return 0.0


def _get_video_dimensions(filepath: str) -> tuple[int, int]:
    """Get video width and height using ffmpeg."""
    try:
        result = subprocess.run(
            [FFMPEG, "-i", filepath],
            capture_output=True, timeout=30,
        )
        stderr = result.stderr.decode("utf-8", errors="replace")
        import re as _re
        m = _re.search(r"(\d{2,5})x(\d{2,5})", stderr)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception as e:
        logger.warning("ffmpeg dimensions error: %s", e)
    return 0, 0


def _crop_to_9_16(filepath: str) -> str:
    """Crop video to 9:16 portrait ratio using center crop. Returns path to result file."""
    w, h = _get_video_dimensions(filepath)
    if w <= 0 or h <= 0:
        return filepath

    target_ratio = 9 / 16
    current_ratio = w / h

    if abs(current_ratio - target_ratio) < 0.01:
        return filepath

    if current_ratio > target_ratio:
        new_w = int(h * 9 / 16)
        new_w -= new_w % 2
        new_h = h - (h % 2)
        crop_filter = f"crop={new_w}:{new_h}"
    else:
        new_h = int(w * 16 / 9)
        new_h -= new_h % 2
        new_w = w - (w % 2)
        crop_filter = f"crop={new_w}:{new_h}"

    base = Path(filepath)
    out_path = str(base.parent / f"{base.stem}_916{base.suffix}")
    try:
        result = subprocess.run(
            [FFMPEG, "-y", "-i", filepath,
             "-vf", crop_filter,
             "-c:v", "libx264", "-preset", "fast", "-crf", "23",
             "-c:a", "aac", "-b:a", "128k",
             "-movflags", "+faststart",
             out_path],
            capture_output=True, timeout=120,
        )
        if result.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            os.remove(filepath)
            logger.info("Cropped %s → 9:16 %s", filepath, out_path)
            return out_path
        else:
            logger.warning("ffmpeg crop failed: %s", result.stderr.decode("utf-8", errors="replace")[:300])
    except Exception as e:
        logger.warning("ffmpeg crop error: %s", e)
    return filepath


def _split_video(
    filepath: str,
    segment_duration: int = 5,
    max_segments: int = 5,
) -> list[str]:
    """Split video into segments of given duration.

    Args:
        filepath: Path to source video.
        segment_duration: Duration per segment in seconds (3-7).
        max_segments: Maximum number of segments to produce (4-5).

    Returns:
        List of file paths for the produced segments.
    """
    duration = _get_video_duration(filepath)
    if duration <= 0:
        return [filepath]

    segment_duration = max(3, min(7, segment_duration))
    max_segments = max(1, min(10, max_segments))

    # If video is short enough, no splitting needed
    if duration <= segment_duration:
        return [filepath]

    base = Path(filepath)
    output_dir = base.parent
    stem = base.stem

    segments = []
    for i in range(max_segments):
        start = i * segment_duration
        if start >= duration:
            break

        out_path = str(output_dir / f"{stem}_seg{i + 1}.mp4")
        try:
            subprocess.run(
                [FFMPEG, "-y", "-ss", str(start), "-i", filepath,
                 "-t", str(segment_duration), "-c", "copy",
                 "-avoid_negative_ts", "make_zero", out_path],
                capture_output=True, timeout=60,
            )
            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                segments.append(out_path)
        except Exception as e:
            logger.warning("ffmpeg split error at segment %d: %s", i + 1, e)

    return segments if segments else [filepath]


async def download_douyin_video(
    video_url: str,
    filename: str,
    cookie: str,
    session_id: str | None = None,
) -> str:
    """Download video from Douyin CDN.

    Returns:
        Path to downloaded file.
    """
    if not video_url:
        raise ExternalAPIException(detail="No video URL available")

    if session_id:
        out_dir = DOWNLOAD_DIR / session_id / "douyin"
    else:
        out_dir = DOWNLOAD_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_filename(filename)
    out_path = str(out_dir / f"{safe_name}_{uuid.uuid4().hex[:8]}.mp4")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.douyin.com/",
    }
    if cookie:
        headers["Cookie"] = cookie

    import ssl
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    async with httpx.AsyncClient(
        headers=headers, verify=ssl_ctx, timeout=300, follow_redirects=True
    ) as client:
        try:
            async with client.stream("GET", video_url) as resp:
                if resp.status_code != 200:
                    raise ExternalAPIException(
                        detail=f"Video download failed: HTTP {resp.status_code}"
                    )
                with open(out_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=256 * 1024):
                        f.write(chunk)
        except ExternalAPIException:
            raise
        except Exception as e:
            if os.path.exists(out_path):
                os.remove(out_path)
            raise ExternalAPIException(detail=f"Video download failed: {e}")

    size = os.path.getsize(out_path)
    if size == 0:
        os.remove(out_path)
        raise ExternalAPIException(detail="Downloaded file is empty")

    logger.info("Downloaded %s (%.1f MB)", out_path, size / 1024 / 1024)
    return out_path


def merge_videos(
    video_paths: list[str],
    session_id: str | None = None,
    output_filename: str | None = None,
) -> str:
    """Merge multiple video files into one using FFmpeg concat demuxer.

    Automatically re-encodes to ensure compatibility between different
    sources (e.g. Douyin clip + Grok generated video).

    Args:
        video_paths: List of paths to video files (in order).
        session_id: Session to save merged file into.
        output_filename: Optional output filename. Auto-generated if None.

    Returns:
        Path to the merged output file.
    """
    if not video_paths:
        raise ExternalAPIException(detail="No video files to merge")
    if len(video_paths) == 1:
        return video_paths[0]

    # Validate all inputs exist
    for p in video_paths:
        if not os.path.exists(p):
            raise ExternalAPIException(detail=f"Video file not found: {p}")

    if session_id:
        out_dir = DOWNLOAD_DIR / session_id
    else:
        out_dir = DOWNLOAD_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    if not output_filename:
        output_filename = f"merged_{uuid.uuid4().hex[:8]}.mp4"
    output_path = str(out_dir / output_filename)

    # Build filter_complex: normalize each input to 1080x1920 @ 30fps then concat
    # This fixes A/V desync caused by mismatched timebase/fps between Douyin & Grok clips
    n = len(video_paths)
    target_w, target_h, target_fps = 1080, 1920, 30

    input_args = []
    for p in video_paths:
        input_args += ["-i", p]

    # Per-input filter: scale-pad to 9:16, force 30fps, reset SAR
    filter_parts = []
    for i in range(n):
        vf = (
            f"[{i}:v]"
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"fps={target_fps},setsar=1,setpts=PTS-STARTPTS"
            f"[v{i}]"
        )
        af = f"[{i}:a]aresample=44100,asetpts=PTS-STARTPTS[a{i}]"
        filter_parts.append(vf)
        filter_parts.append(af)

    # concat
    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(n))
    filter_parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[vout][aout]")
    filter_complex = ";".join(filter_parts)

    cmd = [
        FFMPEG, "-y",
        *input_args,
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=600)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            logger.error("FFmpeg merge error: %s", stderr[:800])
            raise ExternalAPIException(detail="Video merge failed")

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise ExternalAPIException(detail="Merged video file is empty")

        logger.info(
            "Merged %d videos → %s (%.1f MB)",
            n, output_path,
            os.path.getsize(output_path) / 1024 / 1024,
        )
        return output_path

    except ExternalAPIException:
        raise
    except Exception as e:
        raise ExternalAPIException(detail=f"Merge error: {e}")


def extract_frames(
    video_path: str,
    output_dir: str,
    fps: float = 1.0,
    max_frames: int = 20,
) -> list[str]:
    """Extract frames from a video using FFmpeg.

    Args:
        video_path: Path to source video.
        fps: Frames per second to extract.
        max_frames: Maximum number of frames.

    Returns:
        Sorted list of extracted JPG file paths.
    """
    if not os.path.exists(video_path):
        raise ExternalAPIException(detail=f"Video not found: {video_path}")

    os.makedirs(output_dir, exist_ok=True)

    # Adjust fps if it would produce too many frames
    duration = _get_video_duration(video_path)
    if duration > 0 and duration * fps > max_frames:
        fps = max_frames / duration

    out_pattern = os.path.join(output_dir, "frame_%04d.jpg")
    cmd = [
        FFMPEG, "-y", "-i", video_path,
        "-vf", f"fps={fps:.4f}",
        "-frames:v", str(max_frames),
        "-q:v", "2",
        out_pattern,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            logger.error("FFmpeg frame extraction error: %s", stderr[:500])
    except Exception as e:
        raise ExternalAPIException(detail=f"Frame extraction failed: {e}")

    frames = sorted(
        str(p) for p in Path(output_dir).glob("frame_*.jpg")
        if p.stat().st_size > 0
    )

    if not frames:
        raise ExternalAPIException(detail="No frames extracted from video")

    logger.info("Extracted %d frames from %s", len(frames), video_path)
    return frames


async def download_and_split(
    video_url: str,
    filename: str,
    cookie: str,
    segment_duration: int = 5,
    max_segments: int = 5,
    session_id: str | None = None,
) -> dict:
    """Download a Douyin video and split into short segments.

    Returns:
        Dict with original file path, segment paths, and metadata.
    """
    original_path = await download_douyin_video(video_url, filename, cookie, session_id=session_id)

    duration = _get_video_duration(original_path)
    size_mb = os.path.getsize(original_path) / 1024 / 1024

    # Split into segments
    segment_paths = await asyncio.to_thread(
        _split_video, original_path, segment_duration, max_segments
    )

    # Delete original if it was actually split into separate segments
    if len(segment_paths) > 1 or (segment_paths and segment_paths[0] != original_path):
        try:
            os.remove(original_path)
            logger.info("Removed original after split: %s", original_path)
        except OSError as e:
            logger.warning("Could not remove original: %s", e)

    # Crop each segment to 9:16 portrait ratio
    segment_paths = [
        await asyncio.to_thread(_crop_to_9_16, path)
        for path in segment_paths
    ]

    segments = []
    for path in segment_paths:
        seg_duration = _get_video_duration(path)
        seg_size = os.path.getsize(path) / 1024 / 1024
        segments.append({
            "filename": os.path.basename(path),
            "path": path,
            "duration": round(seg_duration, 1),
            "size_mb": round(seg_size, 2),
        })

    return {
        "session_id": session_id or "",
        "original_filename": os.path.basename(original_path),
        "original_path": original_path,
        "original_duration": round(duration, 1),
        "original_size_mb": round(size_mb, 2),
        "segment_count": len(segments),
        "segments": segments,
    }
