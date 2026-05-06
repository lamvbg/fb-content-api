"""
YouTube Studio UI Inspector - run before updating selectors.

Usage:
    cd C:\\Users\\ADMIN\\fb-content-api
    python test_youtube_selectors.py <profile_id>

Output saved to: C:\\Users\\ADMIN\\fb-content-api\\yt_inspector\\
"""
import asyncio
import io
import json
import os
import sys
import time

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from machine.external.browser import BrowserService

OUT = os.path.join(os.path.dirname(__file__), "yt_inspector")
os.makedirs(OUT, exist_ok=True)

STUDIO_URL = "https://studio.youtube.com"
R = {}


def shot(page, name):
    p = os.path.join(OUT, f"{name}.png")
    try:
        page.screenshot(path=p, timeout=5000, full_page=False)
        print(f"  [shot] {name}.png")
    except Exception as e:
        print(f"  [shot-fail] {name}: {e}")


def try_click(page, sel, timeout=2500, method="css"):
    try:
        if method == "role":
            n, exact = sel
            page.get_by_role("button", name=n, exact=exact).first.click(timeout=timeout)
        else:
            page.locator(sel).first.click(timeout=timeout)
        return True
    except Exception:
        return False


def dump_buttons(page):
    return page.evaluate("""() => {
        return [...document.querySelectorAll('button, ytcp-button, [role="button"]')]
            .map(el => ({
                tag: el.tagName,
                id: el.id || null,
                ariaLabel: el.getAttribute('aria-label'),
                text: (el.textContent || '').trim().slice(0, 80),
            }))
            .filter(b => b.text || b.ariaLabel)
            .slice(0, 40);
    }""")


def dump_menu_items(page):
    return page.evaluate("""() => {
        const sels = ['tp-yt-paper-item', 'ytcp-text-menu-item', '[role="menuitem"]', 'li'];
        const items = [];
        for (const sel of sels) {
            for (const el of document.querySelectorAll(sel)) {
                const t = (el.textContent || '').trim();
                if (t) items.push({ tag: el.tagName, testId: el.getAttribute('test-id'), text: t.slice(0, 100) });
            }
        }
        return items.slice(0, 30);
    }""")


def run_sync(ws_endpoint):
    pw, browser, context, page = BrowserService.connect_sync(ws_endpoint)
    try:
        # 1. Navigate
        print("\n[1] Navigating to YouTube Studio...")
        page.goto(STUDIO_URL, wait_until="commit", timeout=15000)
        try:
            page.wait_for_url("**/studio.youtube.com/**", timeout=20000)
        except Exception:
            pass
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass
        time.sleep(2)

        shot(page, "01_loaded")
        R["url"] = page.url
        R["logged_in"] = "studio.youtube.com" in page.url and "accounts.google.com" not in page.url

        if not R["logged_in"]:
            print(f"  [FAIL] NOT LOGGED IN -- URL: {page.url}")
            print("  Please log in to YouTube for this profile first.")
            return

        print(f"  [OK] Logged in: {page.url}")

        # 2. Find Create/Tao button
        print("\n[2] Looking for Create button...")
        R["buttons_on_page"] = dump_buttons(page)
        for b in R["buttons_on_page"]:
            t = (b.get("text") or "") + (b.get("ariaLabel") or "")
            if any(x in t for x in ["Create", "Upload", "Tạo", "Tải"]):
                print(f"  -> Found: tag={b['tag']} id={b['id']} aria={b['ariaLabel']!r} text={b['text']!r}")

        CREATE_SELS = [
            "ytcp-button#create-icon",
            "#create-icon",
            '[aria-label="Create"]',
            '[aria-label="Tạo"]',
            'button:has-text("Create")',
            'button:has-text("Tạo")',
        ]
        R["create_sel_test"] = {}
        for sel in CREATE_SELS:
            try:
                visible = page.locator(sel).first.is_visible(timeout=1500)
                R["create_sel_test"][sel] = visible
                status = "[YES]" if visible else "[ no]"
                print(f"  {status} visible: {sel}")
            except Exception:
                R["create_sel_test"][sel] = False
                print(f"  [timeout] {sel}")

        # 3. Click Create
        print("\n[3] Clicking Create button...")
        create_clicked_via = None
        for sel in CREATE_SELS:
            if try_click(page, sel):
                create_clicked_via = sel
                break
        if not create_clicked_via:
            for n, exact in [("Create", True), ("Tạo", True), ("Create", False), ("Tạo", False)]:
                if try_click(page, (n, exact), method="role"):
                    create_clicked_via = f"get_by_role({n!r}, exact={exact})"
                    break
        if not create_clicked_via:
            res = page.evaluate("""() => {
                for (const el of document.querySelectorAll('button, ytcp-button, [role="button"]')) {
                    const t = (el.textContent || el.getAttribute('aria-label') || '').trim();
                    if (t === 'Create' || t === 'Tạo' || t.startsWith('Create') || t.startsWith('Tạo')) {
                        el.click(); return t;
                    }
                }
                return null;
            }""")
            create_clicked_via = f"JS:{res}" if res else None

        R["create_clicked_via"] = create_clicked_via
        status = "[OK]" if create_clicked_via else "[FAIL]"
        print(f"  {status} {create_clicked_via or 'FAILED - could not click Create'}")
        time.sleep(1)
        shot(page, "02_after_create_click")

        # 4. Dropdown items
        print("\n[4] Dropdown menu items...")
        R["dropdown_items"] = dump_menu_items(page)
        for item in R["dropdown_items"]:
            print(f"  -> [{item['tag']}] testId={item.get('testId')!r} text={item['text']!r}")

        # 5. Click Upload item
        print("\n[5] Clicking Upload video item...")
        upload_clicked_via = None
        upload_texts = ["Tải video lên", "Upload video", "Upload videos"]
        for text in upload_texts:
            for tag in ["tp-yt-paper-item", "ytcp-text-menu-item", '[role="menuitem"]']:
                if try_click(page, f'{tag}:has-text("{text}")'):
                    upload_clicked_via = f'{tag}:has-text("{text}")'
                    break
            if upload_clicked_via:
                break
        if not upload_clicked_via:
            for text in upload_texts:
                try:
                    page.get_by_role("menuitem", name=text, exact=False).first.click(timeout=2500)
                    upload_clicked_via = f"get_by_role(menuitem, {text!r})"
                    break
                except Exception:
                    pass

        R["upload_clicked_via"] = upload_clicked_via
        status = "[OK]" if upload_clicked_via else "[FAIL]"
        print(f"  {status} {upload_clicked_via or 'FAILED'}")
        time.sleep(2)
        shot(page, "03_upload_dialog")

        # 6. Inspect upload dialog
        print("\n[6] Upload dialog elements...")
        R["dialog"] = page.evaluate("""() => {
            const fileInput = document.querySelector('input[type="file"]');
            const titleEl = document.querySelector('#title-textarea, ytcp-mention-textbox');
            const descEl  = document.querySelector('#description-textarea');
            const nextBtn = document.querySelector('#next-button, ytcp-button#next-button');
            return {
                fileInput: fileInput ? 'FOUND' : 'not found',
                titleTag: titleEl ? (titleEl.tagName + (titleEl.id ? '#'+titleEl.id : '')) : 'not found',
                titleLabel: titleEl ? titleEl.getAttribute('label') : null,
                titleHTML: titleEl ? titleEl.outerHTML.slice(0, 500) : null,
                descTag: descEl ? (descEl.tagName + (descEl.id ? '#'+descEl.id : '')) : 'not found',
                nextBtnFound: nextBtn ? 'FOUND' : 'not found',
            };
        }""")
        print(json.dumps(R["dialog"], ensure_ascii=False, indent=2))

        if R["dialog"].get("fileInput") != "FOUND":
            print("  [WARN] File input NOT found -- waiting...")
            time.sleep(3)
            shot(page, "03b_upload_dialog_wait")

        print("\n[DONE] Check yt_inspector/ for screenshots + results.json")

    finally:
        with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as f:
            json.dump(R, f, ensure_ascii=False, indent=2)
        print(f"\nResults: {OUT}\\results.json")
        pw.stop()


async def main(profile_id: str):
    print(f"Connecting to profile: {profile_id}")
    ws_endpoint = await BrowserService.get_cdp_endpoint(profile_id)
    await asyncio.to_thread(run_sync, ws_endpoint)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_youtube_selectors.py <profile_id>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
