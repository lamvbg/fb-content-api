"""
YouTube upload automation via Playwright CDP.

Connects to an anti-detect browser profile (already logged into YouTube)
and automates the YouTube Studio upload flow.
Uses sync Playwright in a thread to avoid Windows asyncio subprocess issues.

Selector strategy: ID/class first → aria-label → text fallback.
"""

import asyncio
import logging
import os
import time

from core.exceptions.http import ExternalAPIException
from machine.external.browser import BrowserService

logger = logging.getLogger(__name__)

YOUTUBE_STUDIO_URL = "https://studio.youtube.com"


def _click_first(page, selectors: list[str], *, timeout: int = 5000, label: str = "element"):
    """Try each selector in order, click the first one that works."""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            el.click(timeout=timeout)
            logger.info("Clicked %s via: %s", label, sel)
            return sel
        except Exception:
            continue
    raise Exception(f"Could not click {label} — tried: {selectors}")


def _click_first_js(page, selectors: list[str], *, label: str = "element"):
    """Try each selector via JS document.querySelector, click first match."""
    result = page.evaluate("""(selectors) => {
        for (const sel of selectors) {
            const el = document.querySelector(sel);
            if (el) { el.click(); return sel; }
        }
        return null;
    }""", selectors)
    if result:
        logger.info("Clicked %s via JS: %s", label, result)
    return result


class YouTubeService:
    """Automates YouTube video upload via browser automation."""

    @classmethod
    async def upload_video(
        cls,
        profile_id: str,
        video_path: str,
        title: str,
        description: str,
        tags: list[str] | None = None,
        visibility: str = "public",
    ) -> dict:
        if not os.path.exists(video_path):
            raise ExternalAPIException(detail=f"Video file not found: {video_path}")

        ws_endpoint = await BrowserService.get_cdp_endpoint(profile_id)

        try:
            return await asyncio.to_thread(
                cls._upload_sync, ws_endpoint, video_path, title, description, tags, visibility,
            )
        finally:
            try:
                await BrowserService.close_profile(profile_id)
            except Exception:
                logger.warning("Could not close browser profile %s", profile_id)

    @classmethod
    def _upload_sync(
        cls,
        ws_endpoint: str,
        video_path: str,
        title: str,
        description: str,
        tags: list[str] | None,
        visibility: str,
    ) -> dict:
        """Synchronous YouTube upload — runs in a thread."""
        pw = None
        debug_dir = os.path.dirname(video_path)

        try:
            pw, browser, context, page = BrowserService.connect_sync(ws_endpoint)

            # ── 1. Navigate to YouTube Studio ──
            page.goto(YOUTUBE_STUDIO_URL, wait_until="networkidle", timeout=30000)
            time.sleep(2)

            # Dismiss onboarding dialog (first-time visit)
            cls._dismiss_onboarding(page)

            page.screenshot(path=os.path.join(debug_dir, "_debug_studio.png"))
            logger.info("URL: %s", page.url)

            # ── 2. Open upload dialog ──
            # JS click: ID/class first → aria-label fallback → text fallback
            clicked = _click_first_js(page, [
                # ID / class
                "#create-icon",
                "ytcp-icon-button#create-icon",
                "ytcp-button#create-icon",
                "ytcp-hotkey-icon-button",
                # aria-label (localized)
                'button[aria-label="Tạo"]',
                'button[aria-label="Create"]',
                'button[title="Tạo"]',
                'button[title="Create"]',
            ], label="Create button")
            time.sleep(1)

            if clicked:
                page.screenshot(path=os.path.join(debug_dir, "_debug_dropdown.png"))
                # Click Upload videos: ID first → text fallback
                try:
                    _click_first(page, [
                        "#text-item-0",
                        'tp-yt-paper-item[test-id="upload-beta"]',
                        "tp-yt-paper-item:first-child",
                    ], timeout=5000, label="Upload dropdown item")
                except Exception:
                    _click_first(page, [
                        'tp-yt-paper-item:has-text("Tải video lên")',
                        'tp-yt-paper-item:has-text("Upload videos")',
                        'tp-yt-paper-item:has-text("Upload video")',
                    ], timeout=5000, label="Upload dropdown item (text)")
                time.sleep(1)
            else:
                # Fallback: direct upload button on dashboard
                _click_first(page, [
                    "#select-files-button",
                    "#upload-icon",
                    'button:has-text("Tải video lên")',
                    'button:has-text("Upload video")',
                ], timeout=8000, label="Direct upload button")
                time.sleep(1)

            # ── 3. Set file via input[type="file"] ──
            file_input = page.locator('input[type="file"]')
            file_input.set_input_files(video_path)
            logger.info("File selected: %s", os.path.basename(video_path))

            # Wait for upload dialog title input
            page.wait_for_selector(
                "#title-textarea, "
                "ytcp-social-suggestions-textbox#title-textarea, "
                '#textbox[contenteditable="true"]',
                timeout=30000,
            )
            time.sleep(2)

            # ── 4. Set title ──
            _click_first(page, [
                # Nested ID path (most stable)
                "#title-textarea #child-input #textbox",
                # Component + ID
                "ytcp-social-suggestions-textbox#title-textarea #textbox",
                # aria-label fallback
                '#textbox[aria-label*="title" i]',
                '#textbox[aria-label*="tiêu đề" i]',
            ], timeout=5000, label="Title textbox")
            title_box = page.locator(":focus").first
            title_box.press("Control+a")
            title_box.type(title, delay=30)
            logger.info("Title: %s", title[:60])

            # ── 5. Set description ──
            _click_first(page, [
                "#description-textarea #child-input #textbox",
                "ytcp-social-suggestions-textbox#description-textarea #textbox",
                '#textbox[aria-label*="description" i]',
                '#textbox[aria-label*="người xem" i]',
            ], timeout=5000, label="Description textbox")
            desc_box = page.locator(":focus").first
            desc_box.type(description, delay=20)
            logger.info("Description set")

            # ── 6. Dismiss popups ──
            cls._dismiss_popup(page)

            # ── 7. Select "Not made for kids" ──
            try:
                _click_first(page, [
                    'tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]',
                    '#radioLabel:has-text("Không, nội dung này không dành cho trẻ em")',
                    '#radioLabel:has-text("No, it\'s not made for kids")',
                ], timeout=5000, label="Not made for kids")
                time.sleep(1)
            except Exception:
                logger.warning("Could not select kids setting")

            # ── 8. Tags ──
            if tags:
                try:
                    _click_first(page, [
                        "#toggle-button",
                        "ytcp-video-metadata-editor #toggle-button",
                        'button:has-text("Hiện thêm")',
                        'button:has-text("Show more")',
                    ], timeout=5000, label="Show more")
                    time.sleep(1)

                    _click_first(page, [
                        "#chip-bar #text-input",
                        "#tags-container .text-input",
                        "ytcp-form-input-container#tags-container input",
                        'input[aria-label="Tags"]',
                        'input[aria-label="Thẻ"]',
                    ], timeout=5000, label="Tags input")
                    tags_input = page.locator(":focus").first
                    tags_input.type(",".join(tags), delay=20)
                    logger.info("Tags set")
                except Exception:
                    logger.warning("Could not set tags")

            # ── 9. Click Next × 3 ──
            for step in range(3):
                _click_first(page, [
                    "#next-button",
                    "ytcp-button#next-button",
                ], timeout=10000, label=f"Next ({step+1}/3)")
                time.sleep(3)

            # ── 10. Set visibility ──
            time.sleep(2)
            page.screenshot(path=os.path.join(debug_dir, "_debug_visibility.png"))

            vis_map = {
                "public": ("PUBLIC", "Công khai", "Public"),
                "unlisted": ("UNLISTED", "Không công khai", "Unlisted"),
                "private": ("PRIVATE", "Riêng tư", "Private"),
            }
            vis_name, vis_vi, vis_en = vis_map.get(visibility, vis_map["public"])

            try:
                vis_btn = page.locator(f'tp-yt-paper-radio-button[name="{vis_name}"]').first
                vis_btn.scroll_into_view_if_needed(timeout=3000)
                vis_btn.click(timeout=5000)
                logger.info("Visibility: %s (by name attr)", vis_name)
            except Exception:
                # Fallback: text-based
                try:
                    _click_first(page, [
                        f'#radioLabel:has-text("{vis_vi}")',
                        f'#radioLabel:has-text("{vis_en}")',
                    ], timeout=5000, label=f"Visibility ({vis_en})")
                except Exception:
                    logger.warning("Could not set visibility — using YouTube default")

            time.sleep(1)

            # ── 11. Wait for upload to complete ──
            logger.info("Waiting for upload to complete...")
            try:
                page.wait_for_selector(
                    ".ytcp-video-info a, "
                    "span.video-url-fadeable, "
                    "a.video-url-fadeable, "
                    'span.progress-label:has-text("complete"), '
                    'span.progress-label:has-text("xong")',
                    timeout=300000,
                )
            except Exception:
                logger.warning("Upload progress timed out — publishing anyway")

            # ── 12. Get video URL ──
            video_url = cls._extract_video_url(page)

            # ── 13. Click Done/Publish ──
            _click_first(page, [
                "#done-button",
                "ytcp-button#done-button",
                ".done-button",
            ], timeout=10000, label="Done/Publish")
            time.sleep(3)

            # Try again if URL wasn't available before publish
            if not video_url:
                video_url = cls._extract_video_url(page)

            # ── 14. Handle processing / success dialogs ──
            try:
                page.locator(".ytcp-uploads-still-processing-dialog #close-button").click(timeout=3000)
            except Exception:
                pass
            try:
                _click_first(page, [
                    "#close-button",
                    "ytcp-button#close-button",
                    'ytcp-button[aria-label="Close"]',
                ], timeout=3000, label="Close dialog")
            except Exception:
                pass

            video_id = cls._extract_video_id(video_url)

            return {
                "platform": "youtube",
                "video_url": video_url,
                "video_id": video_id,
                "title": title,
                "status": "published",
                "visibility": visibility,
            }

        except ExternalAPIException:
            raise
        except Exception as e:
            logger.error("YouTube upload failed: %s", e, exc_info=True)
            raise ExternalAPIException(detail=f"YouTube upload failed: {e}")
        finally:
            if pw:
                try:
                    pw.stop()
                except Exception:
                    pass

    # ── Helper methods ──────────────────────────────────────────────────

    @staticmethod
    def _dismiss_onboarding(page):
        """Dismiss first-time YouTube Studio onboarding dialog via JS."""
        try:
            page.evaluate("""() => {
                const dialog = document.querySelector(
                    'ytcp-uploads-onboarding-dialog, ytcp-dialog'
                );
                if (dialog) {
                    const btn = dialog.querySelector('ytcp-button, button');
                    if (btn) btn.click();
                }
            }""")
            time.sleep(1)
        except Exception:
            pass

    @staticmethod
    def _dismiss_popup(page):
        """Dismiss any info/policy popup dialogs."""
        time.sleep(1)
        # JS approach (ID-based)
        try:
            page.evaluate("""() => {
                const btns = document.querySelectorAll(
                    'ytcp-dialog #close-button, ytcp-dialog #dismiss-button'
                );
                btns.forEach(b => b.click());
            }""")
            time.sleep(0.5)
        except Exception:
            pass
        # Playwright fallback (text-based)
        for sel in [
            'button:has-text("Đóng")',
            'button:has-text("Close")',
            'button:has-text("Got it")',
            'button:has-text("Dismiss")',
        ]:
            try:
                page.locator(sel).first.click(timeout=1000)
                time.sleep(0.5)
                break
            except Exception:
                continue

    @staticmethod
    def _extract_video_url(page) -> str:
        """Extract video URL from the upload dialog."""
        for sel in [
            ".ytcp-video-info a",
            "a.video-url-fadeable",
            "span.video-url-fadeable a",
            'a[href*="youtu.be"]',
            'a[href*="youtube.com/shorts"]',
        ]:
            try:
                link = page.locator(sel).first
                href = link.get_attribute("href", timeout=3000) or ""
                if href:
                    return href
            except Exception:
                continue
        return ""

    @staticmethod
    def _extract_video_id(video_url: str) -> str:
        if not video_url:
            return ""
        if "youtu.be/" in video_url:
            return video_url.split("youtu.be/")[-1].split("?")[0]
        if "video/" in video_url:
            return video_url.split("video/")[-1].split("/")[0].split("?")[0]
        if "shorts/" in video_url:
            return video_url.split("shorts/")[-1].split("?")[0]
        return ""
