import json
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "x_state.json"
HOME_URL = "https://x.com/home"
COMPOSE_URL = "https://x.com/compose/tweet"
TEST_TEXT = "LOCAL_X_TYPE_TEST_123"


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
    return None


def button_state(button):
    if button is None:
        return None
    try:
        return {
            'testid': button.get_attribute('data-testid'),
            'disabled': button.is_disabled(timeout=1000),
            'aria_disabled': button.get_attribute('aria-disabled'),
            'text': (button.inner_text(timeout=500) or '').strip(),
        }
    except Exception as e:
        return {'error': repr(e)}


def enabled(state):
    return bool(state and state.get('disabled') is False and state.get('aria_disabled') != 'true')


def snapshot(page):
    editor = find_editor(page)
    button = find_post_button(page)
    alerts = []
    try:
        alerts = page.locator('[role="alert"]').all_inner_texts()
    except Exception:
        pass
    return {
        'url': page.url,
        'editor_found': bool(editor),
        'editor_text': editor_text(editor) if editor else '',
        'post_button': button_state(button),
        'alerts': alerts[:10],
    }


def find_compose_entry(page):
    selectors = [
        '[data-testid="SideNav_NewTweet_Button"]',
        'a[href="/compose/post"]',
        'a[href="/compose/tweet"]',
    ]
    for selector in selectors:
        try:
            loc = page.locator(selector)
            for i in range(min(loc.count(), 10)):
                el = loc.nth(i)
                if visible(el):
                    return el
        except Exception:
            pass
    return None


def wait_for_editor(page, seconds=15):
    deadline = time.time() + seconds
    while time.time() < deadline:
        editor = find_editor(page)
        if editor:
            return editor
        page.wait_for_timeout(500)
    return None


def main():
    print("X local REAL keyboard typing -> AUTO POST diagnostic")
    print("This version uses keyboard.type(), not fill() or insert_text().")
    print("It waits for X to enable Post before clicking.")
    print("After clicking, the browser stays open. Ctrl+C closes it.")

    if not STATE_FILE.exists():
        print("ERROR: x_state.json not found.")
        sys.exit(1)
    try:
        json.loads(STATE_FILE.read_text(encoding='utf-8'))
    except Exception as e:
        print("ERROR: invalid x_state.json:", repr(e))
        sys.exit(1)

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
            print("\n[1] Opening X home...")
            page.goto(HOME_URL, wait_until='domcontentloaded', timeout=20000)
            page.wait_for_timeout(4000)

            editor = find_editor(page)
            if editor is None:
                entry = find_compose_entry(page)
                if entry:
                    print("Clicking compose entry...")
                    entry.click(timeout=3000)
                    editor = wait_for_editor(page, 15)
                else:
                    print("Compose entry not found; trying direct compose URL...")
                    page.goto(COMPOSE_URL, wait_until='domcontentloaded', timeout=20000)
                    editor = wait_for_editor(page, 15)

            if editor is None:
                print("ERROR: editor not found")
                print("URL:", page.url)
                page.screenshot(path=str(BASE_DIR / 'debug_type_no_editor.png'), full_page=True)
                while True:
                    time.sleep(60)

            print("EDITOR FOUND:", editor.get_attribute('data-testid'))
            editor.click(timeout=3000)
            page.wait_for_timeout(300)
            print("ACTIVE ELEMENT:", page.evaluate("""() => { const e=document.activeElement; return e ? {tag:e.tagName,testid:e.getAttribute('data-testid'),role:e.getAttribute('role'),editable:e.getAttribute('contenteditable')} : null; }"""))

            print("\n[2] Typing with keyboard.type():", TEST_TEXT)
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.wait_for_timeout(500)
            page.keyboard.type(TEST_TEXT, delay=120)
            page.wait_for_timeout(1000)

            editor = find_editor(page)
            actual = editor_text(editor) if editor else ''
            button = find_post_button(page)
            state = button_state(button)
            print("--- AFTER KEYBOARD.TYPE ---")
            print("EDITOR TEXT:", repr(actual))
            print("TEXT VERIFIED:", TEST_TEXT in actual)
            print("POST BUTTON:", state)

            if TEST_TEXT not in actual:
                print("STOP: text verification failed. Nothing will be clicked.")
                page.screenshot(path=str(BASE_DIR / 'debug_type_text_failed.png'), full_page=True)
                while True:
                    time.sleep(60)

            print("\n[3] Waiting for X React state to enable Post...")
            post_enabled = False
            for attempt in range(40):
                page.wait_for_timeout(500)
                button = find_post_button(page)
                state = button_state(button)
                print(f"  check {attempt+1}/40:", state)
                if enabled(state):
                    post_enabled = True
                    break

            if not post_enabled:
                print("STOP: Post remained disabled after keyboard.type(). Nothing will be clicked.")
                page.screenshot(path=str(BASE_DIR / 'debug_type_post_disabled.png'), full_page=True)
                while True:
                    time.sleep(60)

            print("POST BUTTON ENABLED: True")
            print("\n[4] AUTO CLICKING POST NOW")
            button.scroll_into_view_if_needed(timeout=2000)
            button.click(timeout=5000)
            print("POST CLICK SENT")

            print("\n[5] Monitoring result. Browser will remain open.")
            previous = None
            while True:
                page.wait_for_timeout(1000)
                current = snapshot(page)
                key = (current['url'], current['editor_found'], current['editor_text'], repr(current['post_button']), tuple(current['alerts']))
                if key != previous:
                    print("\n[PAGE STATE CHANGE]")
                    print("URL:", current['url'])
                    print("EDITOR FOUND:", current['editor_found'])
                    print("EDITOR TEXT:", repr(current['editor_text']))
                    print("POST BUTTON:", current['post_button'])
                    print("ALERTS:", current['alerts'])
                    print("-" * 60)
                    previous = key
        except KeyboardInterrupt:
            print("\nCtrl+C received. Closing browser.")
        except Exception as e:
            print("UNEXPECTED ERROR:", type(e).__name__, repr(e))
            try:
                page.screenshot(path=str(BASE_DIR / 'debug_type_exception.png'), full_page=True)
            except Exception:
                pass
            while True:
                time.sleep(60)
        finally:
            context.close()
            browser.close()
            print("Browser closed.")


if __name__ == '__main__':
    main()
