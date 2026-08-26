import json
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "x_state.json"
COMPOSE_URL = "https://x.com/compose/tweet"
TEST_TEXT = "LOCAL_X_KEYBOARD_TEST_123"


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
        loc=page.locator(selector)
        for i in range(min(loc.count(),10)):
            el=loc.nth(i)
            if visible(el): return el
    return None


def find_post_button(page):
    for selector in ['[data-testid="tweetButtonInline"]','[data-testid="tweetButton"]']:
        loc=page.locator(selector)
        for i in range(min(loc.count(),10)):
            el=loc.nth(i)
            if visible(el): return el
    return None


def button_state(button):
    if button is None: return None
    try:
        return {'testid':button.get_attribute('data-testid'),'disabled':button.is_disabled(timeout=1000),'aria_disabled':button.get_attribute('aria-disabled'),'text':(button.inner_text(timeout=500) or '').strip()}
    except Exception as e: return {'error':repr(e)}


def enabled(state):
    return bool(state and state.get('disabled') is False and state.get('aria_disabled') != 'true')


def dump(page, label):
    editor=find_editor(page); button=find_post_button(page)
    print(f"\n--- {label} ---")
    print("URL:",page.url)
    print("EDITOR FOUND:",bool(editor))
    print("EDITOR TEXT:",repr(editor_text(editor) if editor else ''))
    print("POST BUTTON:",button_state(button))
    return editor,button


def main():
    print("X local keyboard-input diagnostic - AUTO CLICK ENABLED")
    print("This version deliberately avoids fill(). It uses real keyboard events and verifies X's button state.")
    print("Browser stays open after the test. Ctrl+C closes it.")
    if not STATE_FILE.exists():
        print("ERROR: x_state.json not found."); sys.exit(1)
    json.loads(STATE_FILE.read_text(encoding='utf-8'))

    with sync_playwright() as p:
        browser=p.chromium.launch(headless=False,timeout=20000,args=["--disable-gpu","--disable-dev-shm-usage"])
        context=browser.new_context(storage_state=str(STATE_FILE),viewport={"width":1440,"height":1000},locale='en-US')
        page=context.new_page(); page.set_default_timeout(5000)
        try:
            print("[1] Open compose")
            page.goto(COMPOSE_URL,wait_until='domcontentloaded',timeout=20000)
            page.wait_for_timeout(5000)
            editor=find_editor(page)
            if editor is None:
                print("ERROR: editor not found")
                page.screenshot(path=str(BASE_DIR/'debug_keyboard_no_editor.png'),full_page=True)
                while True: time.sleep(60)

            print("EDITOR FOUND:",editor.get_attribute('data-testid'))
            editor.scroll_into_view_if_needed(timeout=2000)
            editor.click(timeout=3000)
            page.wait_for_timeout(300)
            print("ACTIVE ELEMENT:",page.evaluate("document.activeElement && ({tag:document.activeElement.tagName,testid:document.activeElement.getAttribute('data-testid'),role:document.activeElement.getAttribute('role'),editable:document.activeElement.getAttribute('contenteditable')})"))

            # Clear with real keyboard events, then type character-by-character.
            print("[2] Real keyboard typing:",TEST_TEXT)
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.wait_for_timeout(300)
            for index,ch in enumerate(TEST_TEXT,1):
                page.keyboard.insert_text(ch)
                page.wait_for_timeout(80)
                if index in {1,2,3,5,10,len(TEST_TEXT)}:
                    ed=find_editor(page); bt=find_post_button(page); st=button_state(bt)
                    print(f"  chars={index}/{len(TEST_TEXT)} text={repr(editor_text(ed))} post={st}")

            page.wait_for_timeout(1500)
            editor,button=dump(page,"AFTER REAL KEYBOARD INPUT")
            actual=editor_text(editor) if editor else ''
            if TEST_TEXT not in actual:
                print("STOP: keyboard text verification failed. Nothing will be clicked.")
                page.screenshot(path=str(BASE_DIR/'debug_keyboard_typing_failed.png'),full_page=True)
                while True: time.sleep(60)

            print("TEXT VERIFIED: True")
            print("[3] Waiting for X to enable Post...")
            post_enabled=False
            for attempt in range(30):
                page.wait_for_timeout(500)
                button=find_post_button(page); state=button_state(button)
                print(f"  check {attempt+1}/30:",state)
                if enabled(state): post_enabled=True; break

            if not post_enabled:
                print("STOP: X kept Post disabled after REAL keyboard events. Nothing will be clicked.")
                page.screenshot(path=str(BASE_DIR/'debug_keyboard_post_disabled.png'),full_page=True)
                while True: time.sleep(60)

            print("POST BUTTON ENABLED: True")
            print("[4] AUTO CLICKING POST NOW")
            button.scroll_into_view_if_needed(timeout=2000)
            button.click(timeout=5000)
            print("POST CLICK SENT")

            previous=None
            while True:
                page.wait_for_timeout(1000)
                editor=find_editor(page); button=find_post_button(page)
                text=editor_text(editor) if editor else ''
                state=button_state(button)
                alerts=[]
                try: alerts=page.locator('[role="alert"]').all_inner_texts()
                except Exception: pass
                current=(page.url,text,repr(state),tuple(alerts[:5]))
                if current!=previous:
                    print("\n[PAGE CHANGE]")
                    print("URL:",page.url)
                    print("EDITOR TEXT:",repr(text))
                    print("POST BUTTON:",state)
                    print("ALERTS:",alerts[:5])
                    previous=current
        except KeyboardInterrupt:
            print("\nCtrl+C received. Closing browser now.")
        except PlaywrightTimeoutError as e:
            print("PLAYWRIGHT TIMEOUT:",repr(e))
            try: page.screenshot(path=str(BASE_DIR/'debug_keyboard_timeout.png'),full_page=True)
            except Exception: pass
            while True: time.sleep(60)
        except Exception as e:
            print("UNEXPECTED ERROR:",type(e).__name__,repr(e))
            try: page.screenshot(path=str(BASE_DIR/'debug_keyboard_exception.png'),full_page=True)
            except Exception: pass
            while True: time.sleep(60)
        finally:
            context.close(); browser.close(); print("Browser closed.")

if __name__=='__main__': main()
