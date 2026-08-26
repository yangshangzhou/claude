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


def typing_test(page, text="LOCAL_X_TYPING_TEST"):
    """Find the real X editor, type text, verify it, then inspect Post without clicking."""
    print("\n========== TYPING TEST (NO POST CLICK) ==========")
    editor_selector = '[data-testid="tweetTextarea_0"]'
    editor = page.locator(editor_selector).first

    if editor.count() == 0 or not visible(editor):
        print("EDITOR NOT FOUND:", editor_selector)
        return False

    print("EDITOR FOUND:", {
        "selector": editor_selector,
        "role": editor.get_attribute("role"),
        "contenteditable": editor.get_attribute("contenteditable"),
    })

    try:
        editor.scroll_into_view_if_needed(timeout=2000)
        editor.click(timeout=2000)
        editor.focus(timeout=2000)
    except Exception as e:
        print("EDITOR FOCUS FAILED:", repr(e))
        return False

    active = page.evaluate("""() => {
        const el = document.activeElement;
        return {
            tag: el?.tagName || null,
            testid: el?.getAttribute('data-testid') || null,
            role: el?.getAttribute('role') || null,
            contenteditable: el?.getAttribute('contenteditable') || null
        };
    }""")
    print("ACTIVE ELEMENT:", json.dumps(active, ensure_ascii=False))

    print("Typing:", text)
    try:
        editor.press_sequentially(text, delay=30, timeout=8000)
    except Exception as e:
        print("PRESS_SEQUENTIALLY FAILED:", repr(e))
        return False

    page.wait_for_timeout(1000)

    actual = editor.inner_text(timeout=1000).strip()
    html = editor.inner_html(timeout=1000)
    print("EDITOR TEXT AFTER TYPING:", repr(actual))
    print("TEXT VERIFIED:", text in actual)
    print("EDITOR HTML:", html[:1000])

    # Only AFTER text is verified do we inspect the Post button.
    button = page.locator('[data-testid="tweetButtonInline"]').first
    if button.count() == 0:
        button = page.locator('[data-testid="tweetButton"]').first
    print("POST BUTTON COUNT:", button.count())
    if button.count() > 0 and visible(button):
        print("POST BUTTON:", {
            "testid": button.get_attribute("data-testid"),
            "aria_label": button.get_attribute("aria-label"),
            "disabled": button.is_disabled(timeout=1000),
        })
    else:
        print("POST BUTTON NOT FOUND/NOT VISIBLE")

    print("IMPORTANT: Post button was NOT clicked.")
    page.screenshot(path=str(BASE_DIR / "debug_after_typing.png"), full_page=True)
    print("Screenshot: debug_after_typing.png")
    return text in actual


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
            print("\n[1/4] Opening X home...")
            page.goto(HOME_URL, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(5000)
            dump_dom(page, "HOME")
            page.screenshot(path=str(BASE_DIR / "debug_home.png"), full_page=True)

            print("\n[2/4] Opening compose...")
            clicked = click_compose_entry(page)
            print("Compose entry clicked:", clicked)
            page.wait_for_timeout(3000)
            dump_dom(page, "AFTER_COMPOSE_ENTRY")

            print("\n[3/4] Direct compose URL comparison...")
            page.goto(COMPOSE_URL, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(5000)
            dump_dom(page, "DIRECT_COMPOSE_URL")

            print("\n[4/4] REAL EDITOR TYPING TEST...")
            ok = typing_test(page, "LOCAL_X_TYPING_TEST_123")
            print("\nFINAL TYPING RESULT:", ok)
            print("The browser will remain open for 30 seconds. Do NOT click Post manually during this test.")
            time.sleep(30)
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
