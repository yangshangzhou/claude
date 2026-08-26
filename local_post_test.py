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
        return bool(el.evaluate("""el => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
        }""", timeout=1000))
    except Exception:
        return False


def editor_text(editor):
    try:
        return (editor.evaluate("el => (el.innerText || el.textContent || '').trim()", timeout=1000) or '').strip()
    except Exception:
        return ""


def find_editor(page):
    selectors = [
        '[data-testid="tweetTextarea_0"]',
        '[contenteditable="true"][role="textbox"]',
        '[contenteditable="true"]',
    ]
    for selector in selectors:
        loc = page.locator(selector)
        for i in range(min(loc.count(), 10)):
            el = loc.nth(i)
            if visible(el):
                return el
    return None


def find_post_button(page):
    for selector in ['[data-testid="tweetButtonInline"]', '[data-testid="tweetButton"]']:
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
            if aria in {'Post', 'Tweet'} or text in {'Post', 'Tweet'}:
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


def button_enabled(state):
    if not state or 'error' in state:
        return False
    return state.get('disabled') is False and state.get('aria_disabled') != 'true'


def print_state(page, label):
    editor = find_editor(page)
    button = find_post_button(page)
    text = editor_text(editor) if editor else ''
    state = button_state(button)
    print(f"\n--- {label} ---")
    print("URL:", page.url)
    print("EDITOR FOUND:", bool(editor))
    print("EDITOR TEXT:", repr(text))
    print("POST BUTTON:", state)
    return editor, button, text, state


def main():
    print("X local POST diagnostic - AUTO CLICK ENABLED")
    print("The script will type the test text, verify it, wait for X to enable Post, then click Post automatically.")
    print("The browser will remain open after the click so we can inspect the result.")
    print("Press Ctrl+C when you want to stop the test.")

    if not STATE_FILE.exists():
        print("ERROR: x_state.json not found.")
        sys.exit(1)
    json.loads(STATE_FILE.read_text(encoding='utf-8'))

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            timeout=20000,
            args=["--disable-gpu", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            storage_state=str(STATE_FILE),
            viewport={"width": 1440, "height": 1000},
            locale='en-US',
        )
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

            print("EDITOR FOUND:", editor.get_attribute('data-testid'))
            editor.scroll_into_view_if_needed(timeout=2000)
            editor.click(timeout=2000)
            editor.focus(timeout=2000)

            # Important: use Playwright fill() for contenteditable so the browser
            # dispatches the input events that X/React uses to enable the Post button.
            print("[2] Fill:", TEST_TEXT)
            editor.fill(TEST_TEXT, timeout=8000)
            page.wait_for_timeout(1500)

            editor, button, actual, state = print_state(page, "AFTER FILL")

            if TEST_TEXT not in actual:
                print("STOP: text verification failed. Nothing will be clicked.")
                page.screenshot(path=str(BASE_DIR / 'debug_post_typing_failed.png'), full_page=True)
                while True:
                    time.sleep(60)

            print("TEXT VERIFIED: True")
            print("POST BUTTON AFTER FILL:", state)

            # Give X a few seconds to update React state. Do not click a disabled button.
            print("[3] Waiting for X to enable Post...")
            enabled = False
            for attempt in range(20):
                page.wait_for_timeout(500)
                button = find_post_button(page)
                state = button_state(button)
                print(f"  check {attempt + 1}/20:", state)
                if button_enabled(state):
                    enabled = True
                    break

            if not enabled:
                print("STOP: X kept Post disabled. Nothing will be clicked.")
                print("This means the text is visible in the DOM, but X has not accepted it as a valid compose input.")
                page.screenshot(path=str(BASE_DIR / 'debug_post_button_disabled.png'), full_page=True)
                while True:
                    time.sleep(60)

            print("POST BUTTON ENABLED: True")
            print("[4] AUTO CLICKING POST NOW")
            button.scroll_into_view_if_needed(timeout=2000)
            button.click(timeout=5000)
            print("POST CLICK SENT")

            # Keep browser alive and observe the result. Do not close automatically.
            previous = None
            deadline = time.time() + 30
            while time.time() < deadline:
                page.wait_for_timeout(1000)
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

            print("\n=== POST CLICK TEST FINISHED ===")
            print("Browser remains open. Press Ctrl+C to close it.")
            while True:
                time.sleep(60)

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
