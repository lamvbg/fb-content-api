"""
Upload a real video, reach the visibility page, then inspect ALL selectors.
Pauses at visibility page so you can see what happens.

Usage:
    python test_visibility_live.py <profile_id> <video_path>
"""
import asyncio
import io
import json
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from machine.external.browser import BrowserService

OUT = os.path.join(os.path.dirname(__file__), "yt_inspector")
os.makedirs(OUT, exist_ok=True)

STUDIO_URL = "https://studio.youtube.com"


def shot(page, name):
    try:
        page.screenshot(path=os.path.join(OUT, f"{name}.png"), timeout=8000)
        print(f"  [shot] {name}.png")
    except Exception as e:
        print(f"  [shot-fail] {e}")


def click_any(page, selectors, timeout=3000, label=""):
    for sel in selectors:
        try:
            page.locator(sel).first.click(timeout=timeout)
            print(f"  [clicked] {label} via: {sel}")
            return sel
        except Exception:
            pass
    # get_by_role fallback for buttons
    for name in selectors:
        if not name.startswith('[') and not name.startswith('#') and not name.startswith('button'):
            try:
                page.get_by_role("button", name=name, exact=False).first.click(timeout=timeout)
                print(f"  [clicked] {label} via get_by_role({name!r})")
                return f"role:{name}"
            except Exception:
                pass
    return None


def run_sync(ws_endpoint, video_path):
    pw, browser, context, page = BrowserService.connect_sync(ws_endpoint)
    try:
        # Navigate
        print("[1] Navigate...")
        try:
            page.goto(STUDIO_URL, wait_until="commit", timeout=15000)
        except Exception:
            pass  # interrupted redirect is OK
        try:
            page.wait_for_url("**/studio.youtube.com/**", timeout=20000)
        except Exception:
            pass
        page.wait_for_load_state("domcontentloaded", timeout=10000)
        time.sleep(2)
        if "studio.youtube.com" not in page.url:
            print(f"[FAIL] Not logged in: {page.url}")
            return

        # Click Create
        print("[2] Create button...")
        for sel in ['[aria-label="Tạo"]', '[aria-label="Create"]', 'button:has-text("Tạo")', 'button:has-text("Create")']:
            try:
                page.locator(sel).first.click(timeout=2000)
                print(f"  OK: {sel}")
                break
            except Exception:
                pass
        time.sleep(1)

        # Click upload item
        print("[3] Upload item...")
        for sel in ['tp-yt-paper-item[test-id="upload"]', 'tp-yt-paper-item:has-text("Tải video lên")', 'tp-yt-paper-item:has-text("Upload video")']:
            try:
                page.locator(sel).first.click(timeout=2500)
                print(f"  OK: {sel}")
                break
            except Exception:
                pass
        time.sleep(2)

        # Set file
        print("[4] Set file...")
        page.locator('input[type="file"]').set_input_files(video_path)
        print(f"  File: {os.path.basename(video_path)}")

        # Wait for title textarea
        print("[5] Waiting for upload dialog...")
        try:
            page.wait_for_selector("#title-textarea, ytcp-mention-textbox", timeout=20000)
        except Exception:
            print("  [WARN] title-textarea not found")
        time.sleep(2)
        shot(page, "step5_dialog")

        # Dump title element HTML
        title_info = page.evaluate("""() => {
            const t = document.querySelector('#title-textarea, ytcp-mention-textbox[label], ytcp-social-suggestions-textbox');
            if (!t) return 'not found';
            return { tag: t.tagName, id: t.id, label: t.getAttribute('label'), html: t.outerHTML.slice(0, 400) };
        }""")
        print(f"  Title el: {json.dumps(title_info, ensure_ascii=False)}")

        # Type title
        try:
            page.locator("#title-textarea #textbox, #title-textarea [contenteditable]").first.click(timeout=3000)
            page.keyboard.press("Control+a")
            page.keyboard.type("Test Upload Inspector", delay=30)
        except Exception as e:
            print(f"  [WARN] title type: {e}")

        # Click "Not made for kids" — REQUIRED before Next
        print("[5b] Answering 'Not made for kids'...")
        kids_done = False
        kids_sel = 'tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]'
        try:
            el = page.locator(kids_sel).first
            el.scroll_into_view_if_needed(timeout=5000)
            el.click(timeout=5000)
            kids_done = True
            print("  OK: scroll+click")
        except Exception as e:
            print(f"  FAIL: scroll+click: {e}")
        if not kids_done:
            try:
                page.locator(kids_sel).first.click(force=True, timeout=3000)
                kids_done = True
                print("  OK: force=True")
            except Exception as e:
                print(f"  FAIL: force: {e}")
        if not kids_done:
            for name in ["Không, nội dung này không dành cho trẻ em", "No, it's not made for kids"]:
                try:
                    page.get_by_role("radio", name=name, exact=False).first.click(timeout=3000)
                    kids_done = True
                    print(f"  OK: get_by_role({name!r})")
                    break
                except Exception:
                    pass
        print(f"  Kids done: {kids_done}")

        # Verify it's checked
        checked = page.evaluate(f"""() => {{
            const el = document.querySelector('{kids_sel}');
            return el ? el.getAttribute('aria-checked') : 'not found';
        }}""")
        print(f"  aria-checked after click: {checked}")
        time.sleep(1)

        # Click Next x3
        print("[6] Next x3 (waiting for enabled)...")
        for i in range(3):
            try:
                page.locator('#next-button:not([disabled])').wait_for(state='visible', timeout=20000)
                print(f"  Next {i+1}: button enabled")
            except Exception:
                print(f"  Next {i+1}: timeout waiting for enabled")
            clicked = None
            for sel in ["#next-button", "ytcp-button#next-button"]:
                try:
                    page.locator(sel).first.click(timeout=8000)
                    clicked = sel
                    break
                except Exception:
                    pass
            if not clicked:
                try:
                    page.get_by_role("button", name="Tiếp theo", exact=False).first.click(timeout=5000)
                    clicked = "role:Tiếp theo"
                except Exception:
                    pass
            if not clicked:
                try:
                    page.get_by_role("button", name="Next", exact=False).first.click(timeout=5000)
                    clicked = "role:Next"
                except Exception:
                    pass
            print(f"  Next {i+1}: {clicked or 'FAILED'}")
            time.sleep(3)

        shot(page, "step6_visibility")

        # ── VISIBILITY PAGE INSPECTION ──
        print("\n=== VISIBILITY PAGE INSPECTION ===")
        time.sleep(1)

        # All buttons on visibility page
        print("\n[A] All buttons:")
        btns = page.evaluate("""() => {
            return [...document.querySelectorAll('button, ytcp-button, [role="button"]')]
                .map(el => ({
                    tag: el.tagName,
                    id: el.id,
                    aria: el.getAttribute('aria-label'),
                    disabled: el.hasAttribute('disabled') || el.getAttribute('aria-disabled'),
                    text: (el.textContent || '').trim().slice(0, 60),
                }))
                .filter(b => b.text || b.aria);
        }""")
        for b in btns:
            print(f"  {b['tag']} id={b['id']!r} aria={b['aria']!r} disabled={b['disabled']} text={b['text']!r}")

        # Radio buttons
        print("\n[B] Radio buttons:")
        radios = page.evaluate("""() => {
            return [...document.querySelectorAll('tp-yt-paper-radio-button, [role="radio"], input[type="radio"]')]
                .map(el => ({
                    tag: el.tagName,
                    name: el.getAttribute('name'),
                    id: el.id,
                    checked: el.getAttribute('aria-checked'),
                    text: (el.textContent || '').trim().slice(0, 60),
                    html: el.outerHTML.slice(0, 300),
                }));
        }""")
        for r in radios:
            print(f"  {r['tag']} name={r['name']!r} checked={r['checked']!r} text={r['text']!r}")
            print(f"    {r['html'][:200]}")

        # Schedule section
        print("\n[C] Schedule/Len lich section:")
        sched = page.evaluate("""() => {
            // Look for Len lich header
            const allEls = [...document.querySelectorAll('*')];
            for (const el of allEls) {
                const t = (el.textContent || '').trim().slice(0, 25);
                if ((t === 'Lên lịch' || t === 'Schedule') && el.children.length > 0 && el.children.length < 15) {
                    return {
                        tag: el.tagName,
                        id: el.id,
                        class: el.className.slice(0, 100),
                        html: el.outerHTML.slice(0, 600),
                        parentTag: el.parentElement ? el.parentElement.tagName : null,
                        parentClass: el.parentElement ? el.parentElement.className.slice(0, 100) : null,
                        parentHTML: el.parentElement ? el.parentElement.outerHTML.slice(0, 800) : null,
                    };
                }
            }
            return null;
        }""")
        if sched:
            print(json.dumps(sched, ensure_ascii=False, indent=2))
        else:
            print("  Schedule section NOT found in DOM")

        # Done/Luu button
        print("\n[D] Done/Luu button:")
        done_el = page.evaluate("""() => {
            // Look for Luu / Save button
            for (const el of document.querySelectorAll('button, ytcp-button, [role="button"]')) {
                const t = (el.textContent || '').trim();
                const aria = el.getAttribute('aria-label') || '';
                if (t === 'Lưu' || t === 'Save' || t === 'Done' || aria.includes('Lưu') || aria.includes('Save')) {
                    return {
                        tag: el.tagName,
                        id: el.id,
                        class: el.className.slice(0, 100),
                        aria: aria,
                        text: t,
                        disabled: el.getAttribute('disabled') || el.getAttribute('aria-disabled'),
                        html: el.outerHTML.slice(0, 400),
                    };
                }
            }
            // Also check shadow DOM via role
            return null;
        }""")
        if done_el:
            print(json.dumps(done_el, ensure_ascii=False, indent=2))
        else:
            print("  Luu/Save button NOT found via JS querySelector")

        # Test get_by_role for Luu button
        print("\n[E] get_by_role test for Luu/Save:")
        for name in ["Lưu", "Save", "Done", "Publish"]:
            try:
                visible = page.get_by_role("button", name=name, exact=True).first.is_visible(timeout=2000)
                print(f"  [{'YES' if visible else 'no '}] get_by_role(button, {name!r})")
            except Exception:
                print(f"  [to ] get_by_role(button, {name!r})")

        # Try clicking Len lich
        print("\n[F] Try expand Len lich...")
        # First click PUBLIC so "Lưu hoặc xuất bản" is selected, then expand "Lên lịch"
        sched_expanded = page.evaluate("""() => {
            const texts = ['Lên lịch', 'Schedule'];
            const allEls = [...document.querySelectorAll('*')];
            for (const el of allEls) {
                const t = (el.textContent || '').trim().slice(0, 15);
                if (texts.some(x => t === x) && el.tagName !== 'SCRIPT' && el.tagName !== 'STYLE') {
                    el.click();
                    return { clicked: el.tagName + ' ' + el.className.slice(0,60), text: t };
                }
            }
            return null;
        }""")
        print(f"  JS click: {sched_expanded}")
        time.sleep(2)  # Wait for expansion animation
        shot(page, "step7_after_sched_click")

        # Check for date/time inputs after expand — try Playwright locators (pierce shadow DOM)
        print("\n[G] Date/time components (Playwright locators):")
        ytcp_tags = [
            'ytcp-date-picker',
            'ytcp-time-of-day-picker',
            'ytcp-schedule-picker',
            'ytcp-date-time-picker',
        ]
        for tag in ytcp_tags:
            try:
                count = page.locator(tag).count()
                print(f"  {tag}: count={count}")
                if count > 0:
                    try:
                        visible = page.locator(tag).first.is_visible(timeout=2000)
                        print(f"    visible={visible}")
                        html = page.locator(tag).first.evaluate("el => el.outerHTML.slice(0, 400)")
                        print(f"    html: {html[:300]}")
                    except Exception as e:
                        print(f"    err: {e}")
            except Exception as e:
                print(f"  {tag}: err={e}")

        print("\n[G2] DOM scan for ytcp-* and inputs inside schedule section:")
        dom_result = page.evaluate("""() => {
            // Find the schedule section container
            const sched = document.querySelector('ytcp-schedule-picker') ||
                           document.querySelector('[class*="schedule"]') ||
                           null;
            const results = {
                schedContainer: sched ? sched.tagName + '#' + sched.id + ' html:' + sched.outerHTML.slice(0, 500) : null,
                allYtcpTags: [...new Set([...document.querySelectorAll('*')]
                    .filter(el => el.tagName.startsWith('YTCP-'))
                    .map(el => el.tagName))],
                allInputs: [...document.querySelectorAll('input')]
                    .filter(el => el.type !== 'hidden')
                    .map(el => ({ tag: el.tagName, type: el.type, id: el.id, aria: el.getAttribute('aria-label'), html: el.outerHTML.slice(0, 300) })),
            };
            return results;
        }""")
        print(f"  ytcp tags in DOM: {dom_result['allYtcpTags']}")
        print(f"  schedule container: {dom_result['schedContainer']}")
        print(f"  all non-hidden inputs ({len(dom_result['allInputs'])}):")
        for inp in dom_result['allInputs']:
            print(f"    {inp['tag']} type={inp['type']!r} id={inp['id']!r} aria={inp['aria']!r}")
            print(f"      {inp['html'][:200]}")

        print("\n[G3] Try interacting with date/time via Playwright:")
        # Try clicking date picker button
        for sel in ['ytcp-date-picker', 'ytcp-date-picker button', '#datepicker-label', '[aria-label*="date" i]', '[aria-label*="ngày" i]']:
            try:
                visible = page.locator(sel).first.is_visible(timeout=1500)
                text = page.locator(sel).first.text_content(timeout=1500) or ""
                print(f"  [{'YES' if visible else 'no '}] {sel!r} text={text.strip()[:60]!r}")
            except Exception:
                print(f"  [to ] {sel!r}")

        # Try clicking time picker
        for sel in ['ytcp-time-of-day-picker', 'ytcp-time-of-day-picker input', '#time-of-day-input', '[aria-label*="time" i]', '[aria-label*="giờ" i]']:
            try:
                visible = page.locator(sel).first.is_visible(timeout=1500)
                text = page.locator(sel).first.text_content(timeout=1500) or ""
                print(f"  [{'YES' if visible else 'no '}] {sel!r} text={text.strip()[:60]!r}")
            except Exception:
                print(f"  [to ] {sel!r}")

        print("\n=== DONE. Check yt_inspector/ screenshots ===")
        print("Press Ctrl+C or close this script when done inspecting the browser.")
        time.sleep(30)  # Keep page open for manual inspection

    finally:
        with open(os.path.join(OUT, "visibility_live.json"), "w", encoding="utf-8") as f:
            json.dump({"done": True}, f)
        pw.stop()


async def main(profile_id: str, video_path: str):
    ws_endpoint = await BrowserService.get_cdp_endpoint(profile_id)
    await asyncio.to_thread(run_sync, ws_endpoint, video_path)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python test_visibility_live.py <profile_id> <video_path>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
