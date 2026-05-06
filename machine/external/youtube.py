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
        schedule_time: str | None = None,
        timezone: str | None = None,
    ) -> dict:
        if not os.path.exists(video_path):
            raise ExternalAPIException(detail=f"Video file not found: {video_path}")

        ws_endpoint = await BrowserService.get_cdp_endpoint(profile_id)

        try:
            return await asyncio.to_thread(
                cls._upload_sync,
                ws_endpoint, video_path, title, description, tags, visibility,
                schedule_time, timezone,
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
        schedule_time: str | None = None,
        timezone: str | None = None,
    ) -> dict:
        """Synchronous YouTube upload — runs in a thread."""
        pw = None
        debug_dir = os.path.dirname(video_path)

        try:
            pw, browser, context, page = BrowserService.connect_sync(ws_endpoint)

            # ── 1. Navigate to YouTube Studio ──
            # Some profiles redirect / → /channel/{id}, others load directly.
            # Use "commit" (first byte) to avoid interrupted-navigation errors, then
            # wait_for_url to confirm we actually landed on Studio before proceeding.
            page.goto(YOUTUBE_STUDIO_URL, wait_until="commit", timeout=15000)
            page.wait_for_url("**/studio.youtube.com/**", timeout=20000)
            # YouTube Studio has persistent WebSockets — "networkidle" never fires.
            # Use domcontentloaded + fixed sleep instead.
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            time.sleep(3)

            # Check login — some profiles redirect to Google accounts.google.com
            if "accounts.google.com" in page.url or "studio.youtube.com" not in page.url:
                raise ExternalAPIException(
                    detail=f"Profile not logged into YouTube — URL: {page.url}. Please log in first."
                )

            # Dismiss onboarding / welcome dialog (first-time visit)
            cls._dismiss_onboarding(page)

            # Tell Chrome not to translate this page (some profiles trigger Chrome's
            # translate popup which can interfere). Also click the page body to
            # dismiss any open browser-level popups (translate, security warnings).
            try:
                page.evaluate("""() => {
                    document.documentElement.setAttribute('translate', 'no');
                    document.documentElement.lang = document.documentElement.lang || 'vi';
                }""")
                # Click a neutral spot on the page — dismisses popups anchored
                # outside the viewport (e.g. Chrome's translate prompt).
                page.locator('body').click(
                    position={'x': 50, 'y': 400}, timeout=2000, force=True,
                )
                time.sleep(0.5)
            except Exception:
                pass

            try:
                page.screenshot(path=os.path.join(debug_dir, "_debug_studio.png"), timeout=5000)
            except Exception:
                pass
            logger.info("URL: %s", page.url)

            # ── 2. Open upload dialog ──
            # PRIMARY: dashboard's #upload-icon opens an HTML upload-file-picker
            # page (NOT a native picker) — has a regular <input type="file">
            # inside <ytcp-uploads-file-picker>. Just one click then proceed
            # with normal set_input_files in step 3.
            icon_clicked = False
            for sel in ['#upload-icon', '[test-id="upload-icon-url"]']:
                try:
                    page.locator(sel).first.click(timeout=2500, force=True)
                    icon_clicked = True
                    logger.info("Clicked upload-icon: %s", sel)
                    break
                except Exception:
                    pass

            # FALLBACK: classic Create button → Upload video item flow.
            if not icon_clicked:
                logger.info("upload-icon not clickable — falling back to Create dropdown")
                clicked = cls._click_create_button(page)
                if clicked:
                    try:
                        page.screenshot(path=os.path.join(debug_dir, "_debug_dropdown.png"), timeout=5000)
                    except Exception:
                        pass
                    time.sleep(0.5)
                    cls._click_upload_item(page)
            time.sleep(1)

            # ── 3. Set file via input[type="file"] ──
            # The file input lives inside <ytcp-uploads-file-picker> with
            # display:none + opacity:0 + tabindex="-1" — but set_input_files
            # works fine on hidden inputs. Wait for attached + longer timeout
            # for large video files.
            file_input = page.locator('input[type="file"][name="Filedata"], input[type="file"]')
            file_input.first.wait_for(state='attached', timeout=20000)
            file_input.first.set_input_files(video_path, timeout=120000)
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

            # ── 7. Select "Not made for kids" ── REQUIRED field, must succeed
            not_kids_clicked = False
            kids_sel = 'tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]'
            try:
                el = page.locator(kids_sel).first
                el.scroll_into_view_if_needed(timeout=5000)
                el.click(timeout=5000)
                not_kids_clicked = True
                logger.info("Selected NOT made for kids")
            except Exception:
                pass
            if not not_kids_clicked:
                # Force click — needed when element has tabindex="-1"
                try:
                    page.locator(kids_sel).first.click(force=True, timeout=3000)
                    not_kids_clicked = True
                    logger.info("Selected NOT made for kids (force)")
                except Exception:
                    pass
            if not not_kids_clicked:
                # get_by_role fallback
                for name in [
                    "Không, nội dung này không dành cho trẻ em",
                    "No, it's not made for kids",
                    "Not made for kids",
                ]:
                    try:
                        page.get_by_role("radio", name=name, exact=False).first.click(timeout=3000)
                        not_kids_clicked = True
                        logger.info("Selected NOT made for kids via role(%r)", name)
                        break
                    except Exception:
                        pass
            if not not_kids_clicked:
                raise ExternalAPIException(
                    detail="Could not answer 'Made for kids' question — required field. Check profile."
                )
            time.sleep(1)

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
            # Each Next is disabled while the corresponding step is processing.
            # Step 3 → 4 (Checks: copyright + ad suitability) can take 1–2 minutes.
            # Wait long enough for the button to become enabled.
            for step in range(3):
                # Step 3 (index 2) runs Checks — needs much longer wait.
                wait_timeout = 180000 if step == 2 else 60000
                try:
                    page.locator('#next-button:not([disabled])').wait_for(
                        state='visible', timeout=wait_timeout
                    )
                except Exception:
                    logger.warning("Next button still disabled after %ds at step %d",
                                   wait_timeout / 1000, step + 1)
                _click_first(page, [
                    "#next-button",
                    "ytcp-button#next-button",
                    'button[aria-label*="tiếp" i]',
                    'button[aria-label*="next" i]',
                ], timeout=15000, label=f"Next ({step+1}/3)")
                time.sleep(3)

            # ── 10. Set visibility or schedule ──
            time.sleep(2)
            try:
                page.screenshot(path=os.path.join(debug_dir, "_debug_visibility.png"), timeout=5000)
            except Exception:
                pass

            if schedule_time:
                # "Lên lịch" (VN) / "Schedule" (EN) is a COLLAPSIBLE SECTION — not a radio.
                # JS text-scan click is the only reliable way to expand it (confirmed working).
                # Date/time pickers are inside shadow DOM; page.locator() pierces it.
                try:
                    sched_clicked = page.evaluate("""() => {
                        const targets = ['Lên lịch', 'Schedule'];
                        for (const el of document.querySelectorAll('*')) {
                            const t = (el.textContent || '').trim().slice(0, 15);
                            if (targets.some(x => t === x) &&
                                    el.tagName !== 'SCRIPT' && el.tagName !== 'STYLE') {
                                el.click();
                                return true;
                            }
                        }
                        return false;
                    }""")
                    if not sched_clicked:
                        raise Exception("Could not find 'Lên lịch' / 'Schedule' section header")
                    time.sleep(2)  # wait for expansion animation

                    from datetime import datetime
                    dt = datetime.fromisoformat(schedule_time)

                    # 2026 YT Studio structure (confirmed from live DOM):
                    #   ytcp-visibility-scheduler[model="{date:{...}, ...}"]
                    #     ytcp-datetime-picker
                    #       ytcp-text-dropdown-trigger#datepicker-trigger (opens calendar — no input inside)
                    #       ytcp-form-input-container#time-of-day-container > input (time field)
                    #       ytcp-button#timezone-select-button
                    #
                    # Calendar popup has NO text input — only a day grid. Navigating
                    # the grid is fragile; instead set the Polymer model directly
                    # via scheduler.set('model.date', ...) which triggers data binding.
                    date_set = False
                    try:
                        result = page.evaluate(
                            """(target) => {
                                const sched = document.querySelector('ytcp-visibility-scheduler');
                                if (!sched) return { ok: false, msg: 'no scheduler' };
                                if (typeof sched.set !== 'function') return { ok: false, msg: 'no Polymer set()' };
                                try {
                                    sched.set('model.date', target);
                                    return { ok: true };
                                } catch (e) {
                                    return { ok: false, msg: String(e) };
                                }
                            }""",
                            # Polymer model uses 0-indexed month (JS Date convention)
                            {"year": dt.year, "month": dt.month - 1, "day": dt.day},
                        )
                        if result.get('ok'):
                            date_set = True
                            logger.info("Set schedule date via Polymer: %s", dt.strftime('%Y-%m-%d'))
                        else:
                            logger.warning("Polymer date set failed: %s", result.get('msg'))
                    except Exception as e:
                        logger.warning("Could not set schedule date: %s", e)

                    # Time — input lives inside #time-of-day-container
                    time_set = False
                    try:
                        time_input = page.locator(
                            '#time-of-day-container input:not([type="hidden"])'
                        ).first
                        time_input.wait_for(state='visible', timeout=5000)
                        time_input.click(click_count=3, timeout=3000)
                        page.keyboard.type(dt.strftime('%H:%M'), delay=30)
                        time_input.press('Tab')
                        time.sleep(0.5)
                        time_set = True
                        logger.info("Set schedule time: %s", dt.strftime('%H:%M'))
                    except Exception as e:
                        logger.warning("Could not set schedule time: %s", e)

                    if not (date_set and time_set):
                        logger.warning(
                            "Schedule incomplete (date=%s time=%s) — video may save as draft",
                            date_set, time_set,
                        )

                    # Timezone (optional, best-effort)
                    # The dropdown is a scrollable list — no search field.
                    # Look for the matching item by text; press Escape to close if not found.
                    # The timezone button has aria-disabled="false" but is wrapped in
                    # the same backdrop-filter-experiment overlay that blocks normal
                    # clicks (intercepts pointer events). Use force=True to bypass.
                    if timezone:
                        tz_opened = False
                        for force in [False, True]:
                            try:
                                page.locator('#timezone-select-button').first.click(
                                    timeout=3000, force=force,
                                )
                                tz_opened = True
                                logger.info("Opened timezone picker (force=%s)", force)
                                break
                            except Exception:
                                pass
                        if not tz_opened:
                            logger.warning("Could not open timezone picker — using browser default")
                        else:
                            time.sleep(0.5)
                            tz_name = timezone.replace('_', ' ').split('/')[-1]  # e.g. "Ho Chi Minh"

                            # Compute GMT offset for the given IANA timezone name as
                            # a fallback search string. YT Studio shows two formats:
                            #   "(GMT+0700)" for Local Time, "(GMT+07:00)" for cities.
                            search_terms = [tz_name]
                            try:
                                from zoneinfo import ZoneInfo
                                from datetime import datetime as _dt
                                offset = _dt.now(ZoneInfo(timezone)).utcoffset()
                                if offset is not None:
                                    mins = int(offset.total_seconds() // 60)
                                    sign = '+' if mins >= 0 else '-'
                                    h, m = divmod(abs(mins), 60)
                                    search_terms += [
                                        f"GMT{sign}{h:02d}:{m:02d}",  # "(GMT+07:00)"
                                        f"GMT{sign}{h:02d}{m:02d}",   # "(GMT+0700)"
                                    ]
                            except Exception:
                                pass

                            tz_clicked = False
                            for term in search_terms:
                                try:
                                    page.locator(
                                        f'tp-yt-paper-item:has-text("{term}")'
                                    ).first.click(timeout=2000)
                                    tz_clicked = True
                                    logger.info("Set timezone via term: %s", term)
                                    break
                                except Exception:
                                    pass
                            if not tz_clicked:
                                page.keyboard.press('Escape')
                                time.sleep(0.3)
                                logger.warning(
                                    "Timezone not in list (tried %s) — using browser default",
                                    search_terms,
                                )

                    logger.info("Scheduled for: %s %s", schedule_time, timezone or "")
                except Exception as e:
                    raise ExternalAPIException(detail=f"Could not set schedule — {e}")
            else:
                vis_map = {
                    "public":   ("PUBLIC",   "Công khai",     "Public"),
                    "unlisted": ("UNLISTED", "Không công khai","Unlisted"),
                    "private":  ("PRIVATE",  "Riêng tư",      "Private"),
                }
                vis_name, vis_vi, vis_en = vis_map.get(visibility, vis_map["public"])
                vis_set = False
                try:
                    vis_btn = page.locator(f'tp-yt-paper-radio-button[name="{vis_name}"]').first
                    vis_btn.scroll_into_view_if_needed(timeout=3000)
                    vis_btn.click(timeout=5000)
                    vis_set = True
                    logger.info("Visibility: %s", vis_name)
                except Exception:
                    pass
                if not vis_set:
                    try:
                        page.locator(f'tp-yt-paper-radio-button[name="{vis_name}"]').first.click(
                            force=True, timeout=3000
                        )
                        vis_set = True
                        logger.info("Visibility (force): %s", vis_name)
                    except Exception:
                        pass
                if not vis_set:
                    for label_text in [vis_vi, vis_en]:
                        try:
                            page.get_by_role("radio", name=label_text, exact=False).first.click(timeout=3000)
                            vis_set = True
                            logger.info("Visibility via role(%r)", label_text)
                            break
                        except Exception:
                            pass
                if not vis_set:
                    logger.warning("Could not set visibility — using YouTube default")

            time.sleep(1)

            # ── 11. Wait for upload to complete ──
            # The done-button starts hidden/disabled. It becomes enabled when the upload
            # finishes processing. Wait for it to appear enabled (up to 5 min).
            logger.info("Waiting for upload to complete (done-button enabled)...")
            try:
                page.wait_for_selector(
                    '#done-button:not([disabled]):not([hidden]), '
                    '#schedule-button:not([disabled]):not([hidden])',
                    timeout=300000,
                )
                logger.info("done-button is now enabled")
            except Exception:
                logger.warning("done-button never became enabled — trying to click anyway")

            # ── 12. Get video URL (before Done closes the dialog) ──
            video_url = cls._extract_video_url(page)
            logger.info("Video URL before Done: %r", video_url)

            # ── 13. Click Save/Publish/Done button ──
            # done-button inner <button> has aria-label="Lưu" / "Save".
            # Confirmed from inspection: id="done-button", inner button has aria="Lưu".
            try:
                page.locator('#done-button').click(timeout=10000)
                logger.info("Clicked done-button via #done-button")
            except Exception:
                # Fallback: click inner button by aria-label
                clicked = False
                for aria in ["Lưu", "Save", "Done", "Schedule", "Lên lịch"]:
                    try:
                        page.locator(f'button[aria-label="{aria}"]').first.click(timeout=5000)
                        logger.info("Clicked done via button[aria-label=%r]", aria)
                        clicked = True
                        break
                    except Exception:
                        pass
                if not clicked:
                    try:
                        page.locator('#schedule-button').click(timeout=5000)
                        clicked = True
                    except Exception:
                        pass
                if not clicked:
                    raise Exception("Could not click Save/Done button")
            time.sleep(3)

            # Try once more after Done (URL sometimes appears on the success screen)
            if not video_url:
                video_url = cls._extract_video_url(page)
            if not video_url:
                raise ExternalAPIException(detail="Upload completed but could not extract video URL — check debug screenshots")

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
                "status": "scheduled" if schedule_time else "published",
                "visibility": "scheduled" if schedule_time else visibility,
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
    def _click_create_button(page) -> bool:
        """Click the Create/Tạo header button. Confirmed selectors from 2026 UI inspection."""
        T = 2000

        # 1. Class — locale-independent, most stable in 2026 UI
        try:
            page.locator('.ytcpAppHeaderCreateIcon').first.click(timeout=T)
            logger.info("Clicked Create via .ytcpAppHeaderCreateIcon")
            return True
        except Exception:
            pass

        # 2. aria-label — language-specific fallback
        for sel in ['[aria-label="Tạo"]', '[aria-label="Create"]']:
            try:
                page.locator(sel).first.click(timeout=T)
                logger.info("Clicked Create via aria-label: %s", sel)
                return True
            except Exception:
                pass

        # 2. button text
        for name in ["Tạo", "Create"]:
            try:
                page.locator(f'button:has-text("{name}")').first.click(timeout=T)
                logger.info("Clicked Create via button:has-text(%r)", name)
                return True
            except Exception:
                pass

        # 4. get_by_role (pierces Shadow DOM)
        for name in ["Tạo", "Create"]:
            for exact in [True, False]:
                try:
                    page.get_by_role("button", name=name, exact=exact).first.click(timeout=T)
                    logger.info("Clicked Create via get_by_role(%r, exact=%s)", name, exact)
                    return True
                except Exception:
                    pass

        # 5. force=True — bypass "receives events" check.
        # YT A/B test "ytcpButtonShapeImpl--enable-backdrop-filter-experiment" adds a
        # <div.ytSpecTouchFeedbackShapeFill> overlay (position:absolute, inset:0) on top
        # of the button that intercepts pointer events on some accounts.
        for sel in ['.ytcpAppHeaderCreateIcon', '[aria-label="Tạo"]', '[aria-label="Create"]']:
            try:
                page.locator(sel).first.click(timeout=T, force=True)
                logger.info("Clicked Create via FORCE: %s", sel)
                return True
            except Exception:
                pass

        # 6. JS fallback — direct .click() bypasses overlay entirely
        clicked = page.evaluate("""() => {
            for (const el of document.querySelectorAll('button, ytcp-button, [role="button"]')) {
                const t = (el.textContent || el.getAttribute('aria-label') || '').trim();
                if (t === 'Tạo' || t === 'Create' || t.startsWith('Tạo') || t.startsWith('Create')) {
                    el.click(); return t;
                }
            }
            return null;
        }""")
        if clicked:
            logger.info("Clicked Create via JS: %r", clicked)
            return True

        logger.error("Could not find Create/Tao button")
        return False

    @staticmethod
    def _click_upload_item(page) -> bool:
        """Click 'Tải video lên' / 'Upload video' in the Create dropdown."""
        T = 3000

        # 1. test-id attribute — most stable, confirmed 2026 (testId="upload")
        for sel in ['tp-yt-paper-item[test-id="upload"]', '[test-id="upload"]']:
            try:
                page.locator(sel).first.click(timeout=T)
                logger.info("Clicked upload via test-id: %s", sel)
                return True
            except Exception:
                pass

        # 2. Text match
        for text in ["Tải video lên", "Upload video", "Upload videos"]:
            for tag in ["tp-yt-paper-item", "ytcp-text-menu-item", '[role="menuitem"]']:
                try:
                    page.locator(f'{tag}:has-text("{text}")').first.click(timeout=T)
                    logger.info("Clicked upload via %s:has-text(%r)", tag, text)
                    return True
                except Exception:
                    pass

        # 3. get_by_role menuitem
        for text in ["Tải video lên", "Upload video", "Upload videos"]:
            try:
                page.get_by_role("menuitem", name=text, exact=False).first.click(timeout=T)
                logger.info("Clicked upload via get_by_role(menuitem, %r)", text)
                return True
            except Exception:
                pass

        # 4. JS scan
        clicked = page.evaluate("""() => {
            const texts = ['Tải video lên', 'Upload video', 'Upload videos'];
            for (const el of document.querySelectorAll('tp-yt-paper-item, [role="menuitem"]')) {
                const t = (el.textContent || '').trim();
                if (texts.some(x => t.includes(x))) { el.click(); return t; }
            }
            return null;
        }""")
        if clicked:
            logger.info("Clicked upload via JS: %r", clicked)
            return True

        logger.error("Could not click Upload dropdown item")
        return False

    @staticmethod
    def _dismiss_onboarding(page):
        """Dismiss first-time welcome / onboarding dialogs."""
        for sel in [
            'button:has-text("Continue")',
            'button:has-text("Tiếp tục")',
            'button:has-text("Got it")',
            'button:has-text("Đã hiểu")',
            'ytcp-button:has-text("Continue")',
            'ytcp-button:has-text("Tiếp tục")',
            '#dismiss-button',
            '#close-button',
        ]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=1000):
                    el.click()
                    time.sleep(1)
            except Exception:
                continue

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
            "ytcp-video-info a",
            "a.video-url-fadeable",
            "span.video-url-fadeable a",
            'a[href*="youtu.be"]',
            'a[href*="youtube.com/watch"]',
            'a[href*="youtube.com/shorts"]',
        ]:
            try:
                link = page.locator(sel).first
                href = link.get_attribute("href", timeout=3000) or ""
                if href:
                    return href
            except Exception:
                continue
        # JS fallback — scan all anchors for a YouTube video URL
        try:
            href = page.evaluate("""() => {
                for (const a of document.querySelectorAll('a[href]')) {
                    const h = a.getAttribute('href');
                    if (h && (h.includes('youtu.be/') || h.includes('/watch?v=') || h.includes('/shorts/')))
                        return h;
                }
                return null;
            }""")
            if href:
                return href
        except Exception:
            pass
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
