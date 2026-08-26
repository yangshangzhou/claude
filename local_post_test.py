import json
import sys
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


def find_post_button(page):
    # X normally uses tweetButtonInline inside the compose dialog.
    for selector in ['[data-testid="tweetButtonInline"]', '[data-testid="tweetButton"]']:
        loc = page.locator(selector)
        for i in range(min(loc.count(), 10)):
            el = loc.nth(i)
            if visible(el):
                return el

    # Fallback: visible button whose accessible/text name is Post/Tweet.
    buttons = page.locator('button')
    for i in range(buttons.count()):
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


def main():
    print("X local POST click diagnostic")
    print("Python:", sys.version)
    print("State file:", STATE_FILE)

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
            print("\n[1] Open compose")
            page.goto(COMPOSE_URL, wait_until='domcontentloaded', timeout=20000)
            page.wait_for_timeout(5000)

            editor = page.locator('[data-testid="tweetTextarea_0"]').first
            if editor.count() == 0 or not visible(editor):
                print("ERROR: tweetTextarea_0 not found/visible")
                page.screenshot(path=str(BASE_DIR / 'debug_post_no_editor.png'), full_page=True)
                return

            print("EDITOR FOUND")
            editor.scroll_into_view_if_needed(timeout=2000)
            editor.click(timeout=2000)
            editor.focus(timeout=2000)

            print("[2] Type:", TEST_TEXT)
            editor.press_sequentially(TEST_TEXT, delay=30, timeout=8000)
            page.wait_for_timeout(1000)

            actual = editor_text(editor)
            print("EDITOR TEXT:", repr(actual))
            if TEST_TEXT not in actual:
                print("STOP: text verification failed. Post was NOT clicked.")
                page.screenshot(path=str(BASE_DIR / 'debug_post_typing_failed.png'), full_page=True)
                return

            print("TEXT VERIFIED: True")

            print("[3] Find enabled Post button")
            button = find_post_button(page)
            if button is None:
                print("STOP: Post button not found. Post was NOT clicked.")
                page.screenshot(path=str(BASE_DIR / 'debug_post_button_missing.png'), full_page=True)
                return

            print("POST BUTTON:", {
                'testid': button.get_attribute('data-testid'),
                'aria_label': button.get_attribute('aria-label'),
                'disabled': button.is_disabled(timeout=1000),
                'aria_disabled': button.get_attribute('aria-disabled'),
                'text': (button.inner_text(timeout=500) or '').strip(),
            })

            if button.is_disabled(timeout=1000) or button.get_attribute('aria-disabled') == 'true':
                print("STOP: Post button is disabled. Post was NOT clicked.")
                return

            # Final verification immediately before the one and only click.
            final_text = editor_text(editor)
            if TEST_TEXT not in final_text:
                print("STOP: text changed before click. Post was NOT clicked.")
                return

            print("[4] CLICK POST ONCE")
            button.scroll_into_view_if_needed(timeout=2000)
            button.click(timeout=5000, force=True)

            print("CLICK RETURNED WITHOUT PLAYWRIGHT ERROR")
            page.wait_for_timeout(2500)

            # Do not click again. Diagnose the result of the first click.
            editor_count = page.locator('[data-testid="tweetTextarea_0"]').count()
            remaining_text = ''
            if editor_count:
                try:
                    remaining_text = editor_text(page.locator('[data-testid="tweetTextarea_0"]').first)
                except Exception:
                    pass

            alerts = []
            try:
                alerts = page.locator('[role="alert"]').all_inner_texts()
            except Exception:
                pass

            print("\n========== CLICK RESULT ==========")
            print("URL:", page.url)
            print("EDITOR COUNT:", editor_count)
            print("REMAINING EDITOR TEXT:", repr(remaining_text))
            print("ALERTS:", alerts[:10])

            if editor_count == 0 or not remaining_text:
                print("RESULT: compose editor disappeared/cleared after click. This strongly indicates the post was submitted.")
            else:
                print("RESULT: editor is still present after the click. The first click did not visibly complete the post; NO SECOND CLICK WAS PERFORMED.")

            page.screenshot(path=str(BASE_DIR / 'debug_after_post_click.png'), full_page=True)
            print("Screenshot: debug_after_post_click.png")

            # No timer. Keep the browser open until the user explicitly finishes inspection.
            input("\n测试已经执行完毕。浏览器不会自动关闭；检查完成后按 Enter 关闭浏览器：")

        except PlaywrightTimeoutError as e:
            print("PLAYWRIGHT TIMEOUT:", repr(e))
            page.screenshot(path=str(BASE_DIR / 'debug_post_timeout.png'), full_page=True)
            input("\n发生 Playwright 超时。浏览器保持打开；检查完成后按 Enter 关闭：")
        except Exception as e:
            print("UNEXPECTED ERROR:", type(e).__name__, repr(e))
            page.screenshot(path=str(BASE_DIR / 'debug_post_exception.png'), full_page=True)
            input("\n发生异常。浏览器保持打开；检查完成后按 Enter 关闭：")
        finally:
            context.close()
            browser.close()
            print("Browser closed.")


if __name__ == '__main__':
    main()
