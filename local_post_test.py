import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "x_state.json"
COMPOSE_URL = "https://x.com/compose/tweet"
TEST_TEXT = "LOCAL_X_POST_CLICK_TEST_123"


def visible(el):
    try:
        return bool(el.evaluate("""el => { const r=el.getBoundingClientRect(); const s=getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=='none' && s.visibility!=='hidden'; }""", timeout=1000))
    except Exception:
        return False


def editor_text(editor):
    try:
        return (editor.evaluate("el => (el.innerText || el.textContent || '').trim()", timeout=1000) or '').strip()
    except Exception:
        return ""


def find_editor(page):
    for selector in ['[data-testid="tweetTextarea_0"]','[contenteditable="true"][role="textbox"]','[contenteditable="true"]']:
        loc = page.locator(selector)
        for i in range(min(loc.count(), 10)):
            el = loc.nth(i)
            if visible(el):
                return el
    return None


def find_post_button(page):
    for selector in ['[data-testid="tweetButtonInline"]','[data-testid="tweetButton"]']:
        loc = page.locator(selector)
        for i in range(min(loc.count(), 10)):
            el = loc.nth(i)
            if visible(el):
                return el
    buttons = page.locator('button')
    for i in range(min(buttons.count(), 200)):
        el = buttons.nth(i)
        if not visible(el):
            continue
        try:
            aria = (el.get_attribute('aria-label') or '').strip()
            text = (el.inner_text(timeout=300) or '').strip()
            if aria in {'Post','Tweet'} or text in {'Post','Tweet'}:
                return el
        except Exception:
            pass
    return None


def button_state(button):
    if button is None:
        return None
    try:
        return {
            'testid': button.get_attribute('data-testid'),
            'aria_label': button.get_attribute('aria-label'),
            'disabled': button.is_disabled(timeout=1000),
            'aria_disabled': button.get_attribute('aria-disabled'),
            'text': (button.inner_text(timeout=500) or '').strip(),
        }
    except Exception as e:
        return {'error': repr(e)}


def main():
    print("X local POST diagnostic - BROWSER WILL STAY OPEN")
    print("IMPORTANT: this version types the test text but NEVER clicks Post automatically.")
    print("After typing is verified, click Post manually if you want.")
    print("The browser stays open until you press Ctrl+C in this terminal.")

    if not STATE_FILE.exists():
        print("ERROR: x_state.json not found.")
        sys.exit(1)
    json.loads(STATE_FILE.read_text(encoding='utf-8'))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, timeout=20000, args=["--disable-gpu", "--disable-dev-shm-usage"])
        context = browser.new_context(storage_state=str(STATE_FILE), viewport={"width":1440,"height":1000}, locale='en-US')
        page = context.new_page()
        page.set_default_timeout(5000)

        try:
            print("[1] Open compose")
            page.goto(COMPOSE_URL, wait_until='domcontentloaded', timeout=20000)
            page.wait_for_timeout(5000)

            editor = find_editor(page)
            if editor is None:
                print("ERROR: visible X editor not found")
                page.screenshot(path=str(BASE_DIR / 'debug_post_no_editor.png'), full_page=True)
                while True:
                    time.sleep(60)

            print("EDITOR FOUND")
            editor.scroll_into_view_if_needed(timeout=2000)
            editor.click(timeout=2000)
            editor.focus(timeout=2000)

            print("[2] Type:", TEST_TEXT)
            editor.press_sequentially(TEST_TEXT, delay=30, timeout=8000)
            page.wait_for_timeout(1000)

            editor = find_editor(page)
            actual = editor_text(editor) if editor else ''
            button = find_post_button(page)
            state = button_state(button)
            print("EDITOR TEXT:", repr(actual))
            print("TEXT VERIFIED:", TEST_TEXT in actual)
            print("POST BUTTON:", state)
            print("\n>>> 浏览器保持打开。现在你可以手工点击 Post。")
            print(">>> 程序不会自动点击，也不会自动关闭浏览器。")
            print(">>> 点击之后程序会继续监测页面变化、编辑器和错误提示。")

            previous = None
            while True:
                time.sleep(1)
                try:
                    editor = find_editor(page)
                    button = find_post_button(page)
                    current_text = editor_text(editor) if editor else ''
                    current_state = button_state(button)
                    alerts = []
                    try:
                        alerts = page.locator('[role="alert"]').all_inner_texts()
                    except Exception:
                        pass
                    current = (page.url, current_text, repr(current_state), tuple(alerts[:5]))
                    if current != previous:
                        print("\n[PAGE CHANGE]")
                        print("URL:", page.url)
                        print("EDITOR TEXT:", repr(current_text))
                        print("POST BUTTON:", current_state)
                        print("ALERTS:", alerts[:5])
                        previous = current
                except Exception as e:
                    print("\nBROWSER/PLAYWRIGHT EVENT:", type(e).__name__, repr(e))
                    print("Browser will remain open.")
                    time.sleep(2)

        except KeyboardInterrupt:
            print("\nCtrl+C received. Closing browser now.")
        except PlaywrightTimeoutError as e:
            print("PLAYWRIGHT TIMEOUT:", repr(e))
            try:
                page.screenshot(path=str(BASE_DIR / 'debug_post_timeout.png'), full_page=True)
            except Exception:
                pass
            print("Browser remains open. Press Ctrl+C to stop.")
            while True:
                time.sleep(60)
        except Exception as e:
            print("UNEXPECTED ERROR:", type(e).__name__, repr(e))
            try:
                page.screenshot(path=str(BASE_DIR / 'debug_post_exception.png'), full_page=True)
            except Exception:
                pass
            print("Browser remains open. Press Ctrl+C to stop.")
            while True:
                time.sleep(60)
        finally:
            context.close()
            browser.close()
            print("Browser closed.")


if __name__ == '__main__':
    main()
