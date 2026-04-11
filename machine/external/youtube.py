"""
YouTube upload automation via Playwright CDP.

Connects to an anti-detect browser profile (already logged into YouTube)
and automates the YouTube Studio upload flow.
Uses sync Playwright in a thread to avoid Windows asyncio subprocess issues.
"""

import asyncio
import logging
import os
import time

from core.exceptions.http import ExternalAPIException
from machine.external.browser import BrowserService

logger = logging.getLogger(__name__)

YOUTUBE_STUDIO_URL = "https://studio.youtube.com"


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

        # Resolve CDP endpoint (async — uses httpx)
        ws_endpoint = await BrowserService.get_cdp_endpoint(profile_id)

        # Run the entire browser automation synchronously in a thread
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
        try:
            pw, browser, context, page = BrowserService.connect_sync(ws_endpoint)

            # Navigate to YouTube Studio
            page.goto(YOUTUBE_STUDIO_URL, wait_until="networkidle", timeout=30000)
            time.sleep(2)

            # Dismiss onboarding/welcome screen if present (e.g. "Tiếp tục" / "Continue")
            try:
                onboard_btn = page.locator(
                    'button:has-text("Tiếp tục"), button:has-text("Continue"), '
                    'ytcp-button:has-text("Tiếp tục"), ytcp-button:has-text("Continue")'
                )
                onboard_btn.first.click(timeout=5000)
                logger.info("Dismissed onboarding screen")
                page.wait_for_load_state("networkidle", timeout=10000)
                time.sleep(2)
            except Exception:
                pass  # No onboarding screen — continue normally

            # Debug: save screenshot to see current state
            debug_dir = os.path.dirname(video_path)
            page.screenshot(path=os.path.join(debug_dir, "_debug_before_create.png"))
            logger.info("Current URL: %s", page.url)
            logger.info("Page title: %s", page.title())

            # Try direct "Upload video" button on dashboard first (works in both EN/VI)
            direct_upload = page.locator(
                'button:has-text("Tải video lên"), button:has-text("Upload video")'
            )
            try:
                direct_upload.first.click(timeout=5000)
                logger.info("Clicked direct upload button on dashboard")
                time.sleep(2)
            except Exception:
                # Fallback: Create button (Tạo / Create) > Upload videos
                create_btn = page.locator(
                    '[aria-label="Tạo"], [aria-label="Create"], '
                    '#create-icon, ytcp-button#create-icon'
                )
                create_btn.first.click(timeout=10000)
                time.sleep(1)

                upload_item = page.locator(
                    'tp-yt-paper-item:has-text("Tải video lên"), '
                    'tp-yt-paper-item:has-text("Upload videos"), '
                    '#text-item-0'
                )
                upload_item.first.click(timeout=10000)
                time.sleep(2)

            # Upload file via file chooser
            file_input = page.locator('input[type="file"]')
            file_input.set_input_files(video_path)
            logger.info("File selected for upload: %s", video_path)

            # Wait for upload dialog to appear (title textbox)
            page.wait_for_selector(
                'ytcp-social-suggestions-textbox#title-textarea, '
                '#textbox[contenteditable="true"]',
                timeout=30000,
            )
            time.sleep(2)

            # Set title — use the first contenteditable textbox in the title area
            title_box = page.locator(
                'ytcp-social-suggestions-textbox#title-textarea #textbox, '
                '#textbox[aria-label*="title" i], '
                '#textbox[aria-label*="tiêu đề" i]'
            ).first
            title_box.click()
            title_box.fill("")
            title_box.type(title, delay=30)
            logger.info("Title set: %s", title[:50])

            # Set description — the second contenteditable textbox
            desc_box = page.locator(
                'ytcp-social-suggestions-textbox#description-textarea #textbox, '
                '#textbox[aria-label*="description" i], '
                '#textbox[aria-label*="người xem" i]'
            ).first
            desc_box.click()
            desc_box.type(description, delay=20)
            logger.info("Description set")

            # Dismiss any popup dialogs (e.g. policy notice "Đóng" / "Close")
            try:
                dismiss_btn = page.locator(
                    'button:has-text("Đóng"), button:has-text("Close"), '
                    'button:has-text("Dismiss"), button:has-text("Got it")'
                )
                dismiss_btn.first.click(timeout=3000)
                logger.info("Dismissed popup dialog")
                time.sleep(1)
            except Exception:
                pass

            # Select "Not made for kids" (required by YouTube)
            try:
                not_for_kids = page.locator(
                    'tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"], '
                    '#radioLabel:has-text("Không, nội dung này không dành cho trẻ em"), '
                    '#radioLabel:has-text("No, it\'s not made for kids")'
                )
                not_for_kids.first.click(timeout=5000)
                logger.info("Selected: Not made for kids")
                time.sleep(1)
            except Exception:
                logger.warning("Could not select kids setting — skipping")

            # Set tags if provided (More options / Hiện thêm > Tags)
            if tags:
                show_more = page.locator(
                    'ytcp-button#toggle-button, '
                    'button:has-text("Show more"), button:has-text("Hiện thêm")'
                )
                try:
                    show_more.first.click(timeout=5000)
                    time.sleep(1)
                    tags_input = page.locator(
                        'input[aria-label="Tags"], input[aria-label="Thẻ"], '
                        'ytcp-form-input-container#tags-container input'
                    ).first
                    tags_input.click()
                    tags_input.type(",".join(tags), delay=20)
                except Exception:
                    logger.warning("Could not set tags — skipping")

            # Click "Next" through the steps (Details > Video elements > Checks > Visibility)
            for step in range(3):
                next_btn = page.locator('#next-button, ytcp-button#next-button').first
                next_btn.click()
                time.sleep(3)
                logger.info("Clicked Next (step %d/3)", step + 1)

            # Wait for visibility page to load
            time.sleep(2)
            page.screenshot(path=os.path.join(debug_dir, "_debug_visibility.png"))

            # Set visibility — scroll to and click the correct radio button
            visibility_map = {
                "public": [
                    'tp-yt-paper-radio-button[name="PUBLIC"]',
                    '#radioLabel:has-text("Công khai")',
                    '#radioLabel:has-text("Public")',
                ],
                "unlisted": [
                    'tp-yt-paper-radio-button[name="UNLISTED"]',
                    '#radioLabel:has-text("Không công khai")',
                    '#radioLabel:has-text("Unlisted")',
                ],
                "private": [
                    'tp-yt-paper-radio-button[name="PRIVATE"]',
                    '#radioLabel:has-text("Riêng tư")',
                    '#radioLabel:has-text("Private")',
                ],
            }
            selectors = visibility_map.get(visibility, visibility_map["public"])
            vis_clicked = False
            for sel in selectors:
                try:
                    btn = page.locator(sel).first
                    btn.scroll_into_view_if_needed(timeout=3000)
                    btn.click(timeout=5000)
                    vis_clicked = True
                    logger.info("Visibility set to %s using selector: %s", visibility, sel)
                    break
                except Exception:
                    continue
            if not vis_clicked:
                logger.warning("Could not set visibility — will use YouTube default")
            time.sleep(1)

            # Wait for upload to finish processing
            logger.info("Waiting for upload to complete...")
            try:
                page.wait_for_selector(
                    '.progress-label:has-text("Checks complete"), '
                    '.progress-label:has-text("Upload complete"), '
                    '.progress-label:has-text("Đã kiểm tra xong"), '
                    '.progress-label:has-text("Đã tải lên xong"), '
                    'a.video-url-fadeable, '
                    'span.video-url-fadeable',
                    timeout=300000,  # 5 minutes
                )
            except Exception:
                logger.warning("Upload progress check timed out — attempting to publish anyway")

            # Extract video URL if available
            video_url = ""
            try:
                link_el = page.locator('a.video-url-fadeable, span.video-url-fadeable a').first
                video_url = link_el.get_attribute("href", timeout=5000) or ""
            except Exception:
                pass

            # Click Publish/Save
            publish_btn = page.locator('#done-button, ytcp-button#done-button').first
            publish_btn.click()
            time.sleep(3)
            logger.info("Clicked Publish/Done")

            # Try to get video URL from success dialog
            if not video_url:
                try:
                    link_el = page.locator(
                        'a[href*="youtu.be"], a[href*="youtube.com/video"], '
                        '.video-url-fadeable a'
                    ).first
                    video_url = link_el.get_attribute("href", timeout=10000) or ""
                except Exception:
                    pass

            # Extract video ID from URL
            video_id = ""
            if video_url:
                if "youtu.be/" in video_url:
                    video_id = video_url.split("youtu.be/")[-1].split("?")[0]
                elif "video/" in video_url:
                    video_id = video_url.split("video/")[-1].split("/")[0].split("?")[0]

            # Close success dialog if present
            try:
                close_btn = page.locator(
                    'ytcp-button#close-button, [aria-label="Close"]'
                ).first
                close_btn.click(timeout=3000)
            except Exception:
                pass

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
