import json
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "x_state.json"
HOME_URL = "https://x.com/home"
COMPOSE_URL = "https://x.com/compose/tweet"


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


def main():
    print("X local MANUAL typing diagnostic")
    print("Program will NOT type, fill, click Post, or close the browser automatically.")
    print("You will type manually. The program only observes the editor and Post button.")
    print("Press Ctrl+C when you are finished.")

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
            page.wait_for_timeout(5000)

            editor = find_editor(page)
            if editor is None:
                entry = find_compose_entry(page)
                print("HOME EDITOR FOUND:", bool(editor))
                print("COMPOSE ENTRY FOUND:", bool(entry))
                if entry:
                    print("Clicking X compose entry...")
                    entry.click(timeout=3000)
                    page.wait_for_timeout(3000)
                else:
                    print("No compose entry found. Trying direct compose URL as fallback...")
                    page.goto(COMPOSE_URL, wait_until='domcontentloaded', timeout=20000)
                    page.wait_for_timeout(5000)

                editor = find_editor(page)

            if editor is None:
                print("ERROR: editor not found after home->compose flow")
                print("URL:", page.url)
                try:
                    print("DIAGNOSTICS:", page.evaluate("""() => ({readyState:document.readyState, htmlLength:document.documentElement?.outerHTML?.length||0, bodyChildren:document.body?.children?.length||0})"""))
                except Exception:
                    pass
                page.screenshot(path=str(BASE_DIR / 'debug_manual_no_editor.png'), full_page=True)
                while True:
                    time.sleep(60)

            print("EDITOR FOUND:", editor.get_attribute('data-testid'))
            print("ACTIVE ELEMENT BEFORE MANUAL INPUT:", page.evaluate("""() => {
                const e=document.activeElement;
                return e ? {tag:e.tagName,testid:e.getAttribute('data-testid'),role:e.getAttribute('role'),editable:e.getAttribute('contenteditable')} : null;
            }"""))
            print("\n>>> 现在请你手工点击编辑器，然后输入一个字符，例如 A。")
            print(">>> 程序不会输入任何字符，也不会点击 Post。")
            print(">>> 程序每 500ms 检查一次编辑器和 Post 按钮。")
            print(">>> 浏览器不会自动关闭。按 Ctrl+C 结束。\n")

            previous = None
            while True:
                page.wait_for_timeout(500)
                current = snapshot(page)
                key = (
                    current['url'],
                    current['editor_found'],
                    current['editor_text'],
                    repr(current['post_button']),
                    tuple(current['alerts']),
                )
                if key != previous:
                    print("[PAGE STATE CHANGE]")
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
                page.screenshot(path=str(BASE_DIR / 'debug_manual_exception.png'), full_page=True)
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
