"""
Inspect visibility page selectors on the CURRENTLY OPEN browser.
Run while the automation is stuck on the visibility page.

Usage:
    python test_visibility_selectors.py <profile_id>
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


def shot(page, name):
    try:
        page.screenshot(path=os.path.join(OUT, f"{name}.png"), timeout=5000)
        print(f"  [shot] {name}.png")
    except Exception as e:
        print(f"  [shot-fail] {e}")


def run_sync(ws_endpoint):
    pw, browser, context, page = BrowserService.connect_sync(ws_endpoint)
    try:
        print(f"Current URL: {page.url}")
        shot(page, "vis_current")

        # Dump all radio buttons on page
        print("\n--- Radio buttons ---")
        radios = page.evaluate("""() => {
            return [...document.querySelectorAll(
                'tp-yt-paper-radio-button, input[type="radio"], [role="radio"]'
            )].map(el => ({
                tag: el.tagName,
                name: el.getAttribute('name') || el.getAttribute('aria-label'),
                id: el.id || null,
                checked: el.hasAttribute('checked') || el.getAttribute('aria-checked'),
                text: (el.textContent || '').trim().slice(0, 80),
                outerHTML: el.outerHTML.slice(0, 300),
            }));
        }""")
        for r in radios:
            print(f"  tag={r['tag']} name={r['name']!r} id={r['id']!r} text={r['text']!r}")
            print(f"    html: {r['outerHTML'][:200]}")

        # Dump all clickable items that look like schedule/visibility options
        print("\n--- Visibility section HTML ---")
        vis_html = page.evaluate("""() => {
            // Look for the visibility container
            const sels = [
                'ytcp-video-visibility-select',
                'ytcp-visibility-radios',
                '.ytcp-video-visibility-select',
                '[test-id="visibility-radios"]',
            ];
            for (const sel of sels) {
                const el = document.querySelector(sel);
                if (el) return { sel, html: el.outerHTML.slice(0, 1500) };
            }
            // fallback: look for Public/Cong khai text
            for (const el of document.querySelectorAll('*')) {
                const t = (el.textContent || '').trim();
                if (t.includes('Công khai') && el.children.length > 2 && el.children.length < 20) {
                    return { sel: 'text-scan', html: el.outerHTML.slice(0, 1500) };
                }
            }
            return null;
        }""")
        if vis_html:
            print(f"  Found via: {vis_html['sel']}")
            print(vis_html['html'])
        else:
            print("  Not found via any selector")

        # Dump schedule section
        print("\n--- Schedule section ---")
        sched_html = page.evaluate("""() => {
            // Look for Len lich / Schedule header
            const texts = ['Lên lịch', 'Schedule'];
            for (const el of document.querySelectorAll('*')) {
                const t = (el.textContent || '').trim().slice(0, 30);
                if (texts.some(x => t.startsWith(x)) && el.tagName !== 'BODY' && el.tagName !== 'HTML') {
                    return { tag: el.tagName, id: el.id, class: el.className.slice(0, 100), html: el.outerHTML.slice(0, 800) };
                }
            }
            return null;
        }""")
        if sched_html:
            print(json.dumps(sched_html, ensure_ascii=False, indent=2))

        # Test clicking Public radio
        print("\n--- Testing Public/Cong khai click ---")
        pub_sels = [
            'tp-yt-paper-radio-button[name="PUBLIC"]',
            '[name="PUBLIC"]',
            '#radioLabel:has-text("Công khai")',
            'label:has-text("Công khai")',
            ':has-text("Công khai") >> input[type="radio"]',
        ]
        for sel in pub_sels:
            try:
                visible = page.locator(sel).first.is_visible(timeout=1500)
                print(f"  [{'YES' if visible else 'no '}] {sel}")
            except Exception:
                print(f"  [to ] {sel}")

        # Test clicking Schedule section header
        print("\n--- Testing Len lich / Schedule click ---")
        sched_sels = [
            'ytcp-icon-button.ytcp-schedule-picker',
            '[aria-label*="lich"]',
            '[aria-label*="chedule"]',
            'ytcp-schedule-picker',
            '.ytcp-video-visibility-select paper-radio-button[name="SCHEDULE"]',
            'tp-yt-paper-radio-button[name="SCHEDULE"]',
        ]
        for sel in sched_sels:
            try:
                visible = page.locator(sel).first.is_visible(timeout=1500)
                print(f"  [{'YES' if visible else 'no '}] {sel}")
            except Exception:
                print(f"  [to ] {sel}")

        # Also check what role="region" or expandable sections exist
        print("\n--- Expandable sections ---")
        expands = page.evaluate("""() => {
            return [...document.querySelectorAll('[aria-expanded], [role="button"][class*="header"], ytcp-ve.ytcp-schedule-picker')]
                .slice(0, 15)
                .map(el => ({
                    tag: el.tagName,
                    ariaExpanded: el.getAttribute('aria-expanded'),
                    class: el.className.slice(0, 80),
                    text: (el.textContent || '').trim().slice(0, 60),
                    html: el.outerHTML.slice(0, 300),
                }));
        }""")
        for e in expands:
            print(f"  {e['tag']} expanded={e['ariaExpanded']!r} text={e['text']!r}")
            print(f"    {e['html'][:200]}")

        # Try clicking Len lich
        print("\n--- Attempt to click Len lich ---")
        clicked = page.evaluate("""() => {
            // Try finding schedule section header
            for (const el of document.querySelectorAll('*')) {
                const t = (el.textContent || '').trim().slice(0, 20);
                if ((t === 'Lên lịch' || t === 'Schedule') && el.tagName !== 'SCRIPT') {
                    el.click();
                    return { clicked: el.tagName + '#' + el.id + '.' + el.className.slice(0,40), text: t };
                }
            }
            return null;
        }""")
        print(f"  JS click result: {clicked}")
        time.sleep(1)
        shot(page, "vis_after_schedule_click")

        # Dump radio buttons again after click
        print("\n--- After schedule click: Expandable/date inputs ---")
        after = page.evaluate("""() => {
            const inputs = [...document.querySelectorAll('input[type="date"], input[type="time"], ytcp-date-picker, ytcp-time-picker')];
            return inputs.map(el => ({ tag: el.tagName, type: el.type, id: el.id, html: el.outerHTML.slice(0,200) }));
        }""")
        for a in after:
            print(f"  {a['tag']} type={a.get('type')!r} id={a['id']!r}")

    finally:
        with open(os.path.join(OUT, "visibility_results.json"), "w", encoding="utf-8") as f:
            json.dump({"url": page.url}, f)
        print(f"\nDone. Screenshots in: {OUT}")
        pw.stop()


async def main(profile_id: str):
    print(f"Connecting to: {profile_id}")
    ws_endpoint = await BrowserService.get_cdp_endpoint(profile_id)
    await asyncio.to_thread(run_sync, ws_endpoint)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_visibility_selectors.py <profile_id>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
