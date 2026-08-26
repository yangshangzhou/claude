import json
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "x_state.json"
HOME_URL = "https://x.com/home"
COMPOSE_URL = "https://x.com/compose/post"
TEXT = "有些美，不必喧哗。\n一眼心动，便足以让寻常的时光，留下温柔的痕迹。"


def visible(el):
    try:
        return bool(el.evaluate("""el => { const r=el.getBoundingClientRect(); const s=getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=='none' && s.visibility!=='hidden'; }""", timeout=1000))
    except Exception:
        return False


def find_editor(page):
    for selector in [
        '[data-testid="tweetTextarea_0"]',
        '[contenteditable="true"][role="textbox"]',
        '[contenteditable="true"]',
    ]:
        loc = page.locator(selector)
        for i in range(min(loc.count(), 10)):
            el = loc.nth(i)
            if visible(el):
                return el
    return None


def editor_text(editor):
    try:
        return (editor.evaluate("el => (el.innerText || el.textContent || '').trim()", timeout=1000) or '').strip()
    except Exception:
        return ""


def find_post_button(page):
    for selector in ['[data-testid="tweetButtonInline"]', '[data-testid="tweetButton"]']:
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
            "testid": button.get_attribute("data-testid"),
            "disabled": button.is_disabled(timeout=1000),
            "aria_disabled": button.get_attribute("aria-disabled"),
            "text": (button.inner_text(timeout=500) or "").strip(),
        }
    except Exception as e:
        return {"error": repr(e)}


def enabled(state):
    return bool(state and state.get("disabled") is False and state.get("aria_disabled") != "true")


def wait_for_editor(page, seconds=15):
    deadline = time.time() + seconds
    while time.time() < deadline:
        editor = find_editor(page)
        if editor:
            return editor
        page.wait_for_timeout(500)
    return None


def open_compose(page):
    page.goto(HOME_URL, wait_until="domcontentloaded", timeout=20000)
    page.wait_for_timeout(3000)
    editor = find_editor(page)
    if editor:
        return editor

    # Prefer the visible Post/compose entry if available.
    for selector in [
        '[data-testid="SideNav_NewTweet_Button"]',
        'a[href="/compose/post"]',
        'a[href="/compose/tweet"]',
    ]:
        loc = page.locator(selector)
        for i in range(min(loc.count(), 10)):
            el = loc.nth(i)
            if visible(el):
                try:
                    el.click(timeout=3000)
                    editor = wait_for_editor(page, 15)
                    if editor:
                        return editor
                except Exception:
                    pass

    page.goto(COMPOSE_URL, wait_until="domcontentloaded", timeout=20000)
    return wait_for_editor(page, 15)


def find_file_inputs(page):
    loc = page.locator('input[type="file"]')
    return [loc.nth(i) for i in range(loc.count())]


def image_uploaded(page):
    # X normally creates a blob/data preview after the local file is accepted.
    try:
        if page.locator('input[type="file"]').evaluate_all(
            "els => els.some(e => e.files && e.files.length > 0)"
        ):
            return True
    except Exception:
        pass

    for selector in [
        'img[src^="blob:"]',
        'img[src^="data:"]',
        '[data-testid="tweetPhoto"]',
    ]:
        try:
            loc = page.locator(selector)
            for i in range(min(loc.count(), 20)):
                if visible(loc.nth(i)):
                    return True
        except Exception:
            pass
    return False


def main():
    if len(sys.argv) < 2:
        print('用法: py local_image_post_test.py "D:\\path\\test.png"')
        raise SystemExit(2)

    image_path = Path(sys.argv[1]).expanduser().resolve()
    if not image_path.is_file():
        print("图片不存在:", image_path)
        raise SystemExit(2)

    if not STATE_FILE.exists():
        print("ERROR: x_state.json not found")
        raise SystemExit(1)

    try:
        json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print("ERROR: invalid x_state.json:", repr(e))
        raise SystemExit(1)

    print("X LOCAL IMAGE POST TEST - BROWSER VISIBLE")
    print("IMAGE:", image_path)
    print("TEXT:", TEXT)
    print("程序会在本机打开可见 Chrome，并执行：")
    print("打开 X -> 上传图片 -> 验证图片 -> 输入文字 -> 验证文字 -> 等待 Post 启用 -> 自动点击 Post")
    print("发布后浏览器保持打开；Ctrl+C 才会关闭。")

    with sync_playwright() as p:
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
        page.set_default_timeout(7000)

        try:
            print("\n[1] Opening X compose...")
            editor = open_compose(page)
            if editor is None:
                print("ERROR: editor not found")
                print("URL:", page.url)
                page.screenshot(path=str(BASE_DIR / "debug_image_no_editor.png"), full_page=True)
                while True:
                    time.sleep(60)

            print("EDITOR FOUND:", editor.get_attribute("data-testid"))
            print("URL:", page.url)

            print("\n[2] Finding file input...")
            inputs = find_file_inputs(page)
            print("FILE INPUT COUNT:", len(inputs))
            if not inputs:
                print("ERROR: X file input not found")
                page.screenshot(path=str(BASE_DIR / "debug_image_no_file_input.png"), full_page=True)
                while True:
                    time.sleep(60)

            file_input = inputs[0]
            print("Uploading:", image_path.name)
            file_input.set_input_files(str(image_path), timeout=10000)
            page.wait_for_timeout(1500)

            print("IMAGE UPLOADED:", image_uploaded(page))
            print("FILE INPUT STATE:", page.locator('input[type="file"]').evaluate_all("els => els.map(e => e.files ? Array.from(e.files).map(f => ({name:f.name,type:f.type,size:f.size})) : [])"))

            if not image_uploaded(page):
                print("STOP: image upload could not be verified. Nothing will be posted.")
                page.screenshot(path=str(BASE_DIR / "debug_image_upload_failed.png"), full_page=True)
                while True:
                    time.sleep(60)

            print("\n[3] Typing text with real keyboard events...")
            editor = find_editor(page)
            editor.click(timeout=3000)
            page.keyboard.type(TEXT, delay=35)
            page.wait_for_timeout(1000)
            actual = editor_text(editor)
            print("EDITOR TEXT:", repr(actual))
            print("TEXT VERIFIED:", TEXT in actual)

            if TEXT not in actual:
                print("STOP: text verification failed. Nothing will be clicked.")
                page.screenshot(path=str(BASE_DIR / "debug_image_text_failed.png"), full_page=True)
                while True:
                    time.sleep(60)

            print("\n[4] Waiting for X to enable Post...")
            post_enabled = False
            for attempt in range(40):
                page.wait_for_timeout(500)
                button = find_post_button(page)
                state = button_state(button)
                print(f"  check {attempt + 1}/40:", state)
                if enabled(state):
                    post_enabled = True
                    break

            if not post_enabled:
                print("STOP: Post remained disabled. Nothing will be clicked.")
                page.screenshot(path=str(BASE_DIR / "debug_image_post_disabled.png"), full_page=True)
                while True:
                    time.sleep(60)

            print("\n[5] POST BUTTON ENABLED")
            button = find_post_button(page)
            print("POST BUTTON:", button_state(button))
            button.scroll_into_view_if_needed(timeout=3000)
            page.wait_for_timeout(300)
            print("AUTO CLICKING POST...")
            button.click(timeout=7000)
            print("POST CLICK SENT")

            print("\n[6] Monitoring result. Browser remains open.")
            previous = None
            while True:
                page.wait_for_timeout(1000)
                editor_now = find_editor(page)
                button_now = find_post_button(page)
                alerts = []
                try:
                    alerts = page.locator('[role="alert"]').all_inner_texts()
                except Exception:
                    pass
                state = {
                    "url": page.url,
                    "editor_text": editor_text(editor_now) if editor_now else "",
                    "post_button": button_state(button_now),
                    "alerts": alerts[:10],
                }
                key = repr(state)
                if key != previous:
                    print("\n[PAGE STATE CHANGE]")
                    print(json.dumps(state, ensure_ascii=False, indent=2))
                    print("-" * 60)
                    previous = key

        except KeyboardInterrupt:
            print("\nCtrl+C received. Closing browser.")
        except Exception as e:
            print("UNEXPECTED ERROR:", type(e).__name__, repr(e))
            try:
                page.screenshot(path=str(BASE_DIR / "debug_image_exception.png"), full_page=True)
            except Exception:
                pass
            while True:
                time.sleep(60)
        finally:
            context.close()
            browser.close()
            print("Browser closed.")


if __name__ == "__main__":
    main()
