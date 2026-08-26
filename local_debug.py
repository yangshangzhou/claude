import json
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "x_state.json"
HOME_URL = "https://x.com/home"
COMPOSE_URL = "https://x.com/compose/tweet"


def visible(el):
    try:
        return bool(el.evaluate("""el => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
        }""", timeout=1000))
    except Exception:
        return False


def dump_dom(page, label):
    print(f"\n========== {label} ==========")
    print("URL:", page.url)
    try:
        print("TITLE:", page.title())
    except Exception as e:
        print("TITLE ERROR:", repr(e))

    try:
        info = page.evaluate("""() => ({
            readyState: document.readyState,
            htmlLength: document.documentElement?.outerHTML?.length || 0,
            bodyExists: !!document.body,
            bodyChildren: document.body?.children?.length || 0,
            bodyTextLength: document.body?.innerText?.length || 0
        })""")
        print("PAGE:", json.dumps(info, ensure_ascii=False))
    except Exception as e:
        print("PAGE ERROR:", repr(e))

    try:
        testids = page.locator("[data-testid]").evaluate_all("""els => Array.from(new Set(
            els.map(e => e.getAttribute('data-testid')).filter(Boolean)
        ))""")
        print("DATA-TESTIDS:", json.dumps(testids[:200], ensure_ascii=False))
    except Exception as e:
        print("TESTID ERROR:", repr(e))

    try:
        editors = page.locator('[contenteditable="true"]')
        print("CONTENTEDITABLE COUNT:", editors.count())
        for i in range(min(editors.count(), 20)):
            el = editors.nth(i)
            print(" EDITOR", i, {
                "visible": visible(el),
                "tag": el.evaluate("e => e.tagName"),
                "role": el.get_attribute("role"),
                "testid": el.get_attribute("data-testid"),
                "aria_label": el.get_attribute("aria-label"),
                "text": (el.inner_text(timeout=500) if visible(el) else "")[:200],
            })
    except Exception as e:
        print("EDITOR ERROR:", repr(e))

    try:
        buttons = page.locator("button")
        count = buttons.count()
        print("BUTTON COUNT:", count)
        for i in range(min(count, 150)):
            el = buttons.nth(i)
            if not visible(el):
                continue
            try:
                print(" BUTTON", i, {
                    "text": (el.inner_text(timeout=300) or "").strip()[:100],
                    "aria_label": el.get_attribute("aria-label"),
                    "testid": el.get_attribute("data-testid"),
                    "disabled": el.is_disabled(timeout=300),
                })
            except Exception:
                pass
    except Exception as e:
        print("BUTTON ERROR:", repr(e))


def click_compose_entry(page):
    print("\n========== FIND COMPOSE ENTRY ==========")
    selectors = [
        '[data-testid="SideNav_NewTweet_Button"]',
        'a[href="/compose/post"]',
        'a[href="/compose/tweet"]',
        '[data-testid="tweetButtonInline"]',
    ]
    for selector in selectors:
        try:
            loc = page.locator(selector)
            count = loc.count()
            print("selector", selector, "count", count)
            for i in range(min(count, 5)):
                el = loc.nth(i)
                if visible(el):
                    print("FOUND VISIBLE:", selector, i)
                    el.click(timeout=3000)
                    return True
        except Exception as e:
            print("selector error", selector, repr(e))
    return False


def main():
    print("X Playwright local diagnostic")
    print("Python:", sys.version)
    print("Project:", BASE_DIR)
    print("State file:", STATE_FILE)

    if not STATE_FILE.exists():
        print("ERROR: x_state.json was not found.")
        print("Put x_state.json in the same directory as local_debug.py.")
        sys.exit(1)

    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        print("Storage state loaded. Keys:", list(state.keys()))
    except Exception as e:
        print("ERROR: cannot read x_state.json:", repr(e))
        sys.exit(1)

    with sync_playwright() as p:
        print("\nLaunching visible Chromium...")
        browser = p.chromium.launch(
            headless=False,
            timeout=20000,
            args=["--disable-gpu", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            storage_state=str(STATE_FILE),
            viewport={"width": 1440, "height": 1000},
            locale="en-US",
        )
        page = context.new_page()
        page.set_default_timeout(5000)

        try:
            print("\n[1/5] Opening X home...")
            page.goto(HOME_URL, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(5000)
            dump_dom(page, "HOME")
            page.screenshot(path=str(BASE_DIR / "debug_home.png"), full_page=True)
            print("Screenshot: debug_home.png")

            print("\n[2/5] Looking for compose entry...")
            clicked = click_compose_entry(page)
            print("Compose entry clicked:", clicked)
            page.wait_for_timeout(4000)
            dump_dom(page, "AFTER_COMPOSE_ENTRY")
            page.screenshot(path=str(BASE_DIR / "debug_after_compose.png"), full_page=True)
            print("Screenshot: debug_after_compose.png")

            print("\n[3/5] Opening direct compose URL as comparison...")
            page.goto(COMPOSE_URL, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(5000)
            dump_dom(page, "DIRECT_COMPOSE_URL")
            page.screenshot(path=str(BASE_DIR / "debug_direct_compose.png"), full_page=True)
            print("Screenshot: debug_direct_compose.png")

            print("\n[4/5] Checking likely editor selectors...")
            selectors = [
                '[data-testid="tweetTextarea_0"]',
                'div[contenteditable="true"][role="textbox"]',
                '[role="textbox"][contenteditable="true"]',
                '[contenteditable="true"]',
                'textarea',
            ]
            for selector in selectors:
                try:
                    loc = page.locator(selector)
                    print(selector, "count=", loc.count())
                    for i in range(min(loc.count(), 5)):
                        print("  ", i, "visible=", visible(loc.nth(i)))
                except Exception as e:
                    print(selector, "ERROR", repr(e))

            print("\n[5/5] Diagnostic complete.")
            print("The browser will remain open for 10 seconds so you can inspect it.")
            time.sleep(10)
        except PlaywrightTimeoutError as e:
            print("PLAYWRIGHT TIMEOUT:", repr(e))
        except Exception as e:
            print("UNEXPECTED ERROR:", type(e).__name__, repr(e))
        finally:
            context.close()
            browser.close()
            print("Browser closed.")


if __name__ == "__main__":
    main()
