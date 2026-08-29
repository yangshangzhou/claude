import json
import os
import tempfile
import threading
import time
from typing import Any

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

COMPOSE_URL = "https://x.com/compose/tweet"
_HOME_URL = "https://x.com/home"
_BROWSER_LOCK = threading.Lock()
_TASK_STATE_LOCK = threading.Lock()
_TASK_STATE: dict[str, Any] = {"busy": False, "stage": "idle", "started_at": None, "elapsed_seconds": 0, "text": "", "last_result": None}
TASK_HARD_TIMEOUT = 60


def _storage_state() -> str | None:
    value = os.getenv("X_STORAGE_STATE", "").strip()
    if value:
        try:
            json.loads(value)
        except json.JSONDecodeError:
            return None
        return value
    path = os.getenv("X_STORAGE_STATE_FILE", "x_state.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return None


def _task_snapshot() -> dict[str, Any]:
    with _TASK_STATE_LOCK:
        state = dict(_TASK_STATE)
        if state.get("busy") and state.get("started_at"):
            state["elapsed_seconds"] = round(time.time() - state["started_at"], 1)
        return state


def _set_task(**updates: Any) -> None:
    with _TASK_STATE_LOCK:
        _TASK_STATE.update(updates)
        if _TASK_STATE.get("busy") and _TASK_STATE.get("started_at"):
            _TASK_STATE["elapsed_seconds"] = round(time.time() - _TASK_STATE["started_at"], 1)


def _check_deadline(started_at: float) -> None:
    if time.time() - started_at > TASK_HARD_TIMEOUT:
        raise TimeoutError(f"X browser task exceeded the {TASK_HARD_TIMEOUT}s hard timeout.")


def browser_status():
    configured = bool(_storage_state())
    return {"ready": configured, "message": "X browser session is configured." if configured else "No X browser session configured. Set X_STORAGE_STATE to a Playwright storage_state JSON.", "task": _task_snapshot()}


def _element_visible(candidate) -> bool:
    try:
        return bool(candidate.is_visible(timeout=1000))
    except Exception:
        try:
            return bool(candidate.evaluate("""el => { const r=el.getBoundingClientRect(); const s=getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=='none' && s.visibility!=='hidden'; }""", timeout=1000))
        except Exception:
            return False


def _find_visible_editor(page):
    # tweetTextarea_0 is the stable anchor in the current X compose DOM.
    # Do not require a Playwright visibility probe here: the diagnostics have
    # shown this node can be document.activeElement while React is rendering.
    primary = page.locator('[data-testid="tweetTextarea_0"]').first
    try:
        primary.wait_for(state="attached", timeout=1200)
        return primary
    except Exception:
        pass

    # Fallbacks for markup changes.
    for selector in [
        '[contenteditable="true"][role="textbox"]',
        '[contenteditable="true"]',
    ]:
        try:
            loc = page.locator(selector)
            count = min(loc.count(), 10)
            for i in range(count):
                candidate = loc.nth(i)
                if _element_visible(candidate):
                    return candidate
        except Exception:
            continue
    return None


def _editor_text(editor) -> str:
    if editor is None:
        return ""
    try:
        return (editor.evaluate("el => (el.innerText || el.textContent || '').trim()", timeout=1000) or "").strip()
    except Exception:
        try:
            return (editor.input_value(timeout=1000) or "").strip()
        except Exception:
            return ""


def _focus_editor(page, editor) -> bool:
    try:
        editor.scroll_into_view_if_needed(timeout=1500)
        editor.click(timeout=3000)
        page.wait_for_timeout(300)
        return True
    except Exception:
        try:
            editor.evaluate("el => el.click()", timeout=1000)
            page.wait_for_timeout(300)
            return True
        except Exception:
            return False


def _type_into_editor(page, editor, text: str) -> bool:
    if not _focus_editor(page, editor):
        return False
    try:
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        page.wait_for_timeout(500)
        page.keyboard.type(text, delay=120)
        page.wait_for_timeout(1000)
    except Exception:
        return False
    current = _find_visible_editor(page)
    actual = _editor_text(current)
    return bool(current and text.strip() in actual)


def _find_post_button(page):
    for selector in ['[data-testid="tweetButtonInline"]', '[data-testid="tweetButton"]']:
        try:
            loc = page.locator(selector)
            for i in range(min(loc.count(), 10)):
                c = loc.nth(i)
                if _element_visible(c):
                    try:
                        if not c.is_disabled(timeout=800) and c.get_attribute("aria-disabled") != "true":
                            return c
                    except Exception:
                        continue
        except Exception:
            pass
    return None


def _find_new_post_button(page):
    for selector in ['[data-testid="SideNav_NewTweet_Button"]', 'a[href="/compose/post"]', 'a[href="/compose/tweet"]']:
        try:
            loc = page.locator(selector).first
            if _element_visible(loc):
                return loc
        except Exception:
            pass
    return None


def _diagnostics(page):
    out = {"url": page.url if page else "", "title": "", "ready_state": "", "html_length": 0, "body_exists": False, "body_children": 0, "body": "", "test_ids": []}
    if not page:
        return out
    try:
        out.update(page.evaluate("() => ({ready_state:document.readyState,html_length:document.documentElement?.outerHTML?.length||0,body_exists:!!document.body,body_children:document.body?.children?.length||0})"))
    except Exception:
        pass
    try: out["title"] = page.title()
    except Exception: pass
    try: out["body"] = page.locator("body").inner_text(timeout=1200)[:2000]
    except Exception: pass
    try: out["test_ids"] = page.locator("[data-testid]").evaluate_all("els=>Array.from(new Set(els.map(e=>e.getAttribute('data-testid')).filter(Boolean))).slice(0,100)", timeout=1500)
    except Exception: pass
    try:
        out["active_element"] = page.evaluate("""() => { const e=document.activeElement; return e ? {tag:e.tagName,testid:e.getAttribute('data-testid'),role:e.getAttribute('role'),editable:e.getAttribute('contenteditable')} : null; }""")
    except Exception: pass
    try:
        out["tweet_textarea_dom"] = page.evaluate("""() => { const e=document.querySelector('[data-testid=\"tweetTextarea_0\"]'); return e ? {tag:e.tagName,text:(e.innerText||e.textContent||'').trim(),role:e.getAttribute('role'),editable:e.getAttribute('contenteditable'),rect:(()=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})()} : null; }""")
    except Exception: pass
    return out


def _install_lightweight_network_policy(page):
    def route_handler(route):
        if route.request.resource_type in {"media", "font"}:
            route.abort()
        else:
            route.continue_()
    page.route("**/*", route_handler)


def _launch_context(p, state):
    browser = p.chromium.launch(headless=True, timeout=20000, args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--disable-software-rasterizer", "--no-first-run", "--no-default-browser-check"])
    sf = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    sf.write(state); sf.close()
    ctx = browser.new_context(storage_state=sf.name, viewport={"width": 1280, "height": 900}, locale="en-US")
    page = ctx.new_page()
    page.set_default_timeout(3000)
    _install_lightweight_network_policy(page)
    return browser, ctx, sf.name, page


def _wait_for_app(page, started_at, timeout_ms=10000):
    deadline = min(time.time() + timeout_ms / 1000, started_at + TASK_HARD_TIMEOUT - 2)
    while time.time() < deadline:
        _check_deadline(started_at)
        try:
            if page.evaluate("() => !!document.body && document.body.children.length > 0", timeout=1000):
                return True
        except Exception:
            pass
        page.wait_for_timeout(250)
    return False


def _open_compose(page, started_at):
    _set_task(stage="opening_home")
    page.goto(_HOME_URL, wait_until="commit", timeout=12000)
    _wait_for_app(page, started_at, 10000)
    if _login_state(page) or _onboarding_state(page):
        return page.url
    _set_task(stage="opening_compose")
    entry = _find_new_post_button(page)
    if entry:
        try:
            entry.click(timeout=2500)
            return page.url
        except Exception:
            pass
    page.goto(COMPOSE_URL, wait_until="commit", timeout=12000)
    _wait_for_app(page, started_at, 10000)
    return page.url


def _wait_for_editor(page, started_at, timeout_ms=10000):
    deadline = min(time.time() + timeout_ms / 1000, started_at + TASK_HARD_TIMEOUT - 2)
    while time.time() < deadline:
        _check_deadline(started_at)
        editor = _find_visible_editor(page)
        if editor:
            return editor
        page.wait_for_timeout(300)
    return None


def _acquire_task(stage):
    if not _BROWSER_LOCK.acquire(blocking=False):
        return None, {"success": False, "busy": True, "stage": "lock", "message": "Another X browser task is currently running.", "task": _task_snapshot()}
    started = time.time()
    _set_task(busy=True, stage=stage, started_at=started, elapsed_seconds=0, text="", last_result=None)
    return started, None


def _cleanup_task(started_at, browser, context, state_file):
    if context:
        try: context.close()
        except Exception: pass
    if browser:
        try: browser.close()
        except Exception: pass
    if state_file:
        try: os.unlink(state_file)
        except Exception: pass
    try: _BROWSER_LOCK.release()
    except RuntimeError: pass
    with _TASK_STATE_LOCK:
        _TASK_STATE.update(busy=False, stage="idle", elapsed_seconds=round(time.time() - started_at, 1))


def _login_state(page): return "/i/flow/login" in page.url or "/login" in page.url

def _onboarding_state(page): return "/i/jf/" in page.url or "/onboarding" in page.url


def test_x_browser():
    state = _storage_state()
    if not state: return {"success": False, "stage": "configuration", "message": "No X browser session configured."}
    started, error = _acquire_task("test_starting")
    if error: return error
    b = c = sf = page = None
    try:
        with sync_playwright() as p:
            _set_task(stage="test_launching_browser"); b,c,sf,page = _launch_context(p,state)
            _set_task(stage="test_opening_x"); page.goto(_HOME_URL,wait_until="commit",timeout=12000)
            mounted = _wait_for_app(page,started,10000); page.wait_for_timeout(500)
            lr=_login_state(page); ob=_onboarding_state(page)
            r={"success":not lr and mounted,"stage":"test_complete" if not lr and mounted else ("login_required" if lr else "x_dom_not_mounted"),"message":"Playwright launched and X mounted with the saved browser session." if not lr and mounted else "X did not finish mounting its web application in the browser.","login_redirect":lr,"onboarding":ob,"diagnostics":_diagnostics(page)}
            _set_task(stage=r["stage"],last_result=r); return r
    except Exception as e:
        r={"success":False,"stage":"timeout" if isinstance(e,(TimeoutError,PlaywrightTimeoutError)) else "exception","message":f"Playwright/X diagnostic failed: {type(e).__name__}: {e}","diagnostics":_diagnostics(page) if page else {}}; _set_task(stage="failed",last_result=r); return r
    finally: _cleanup_task(started,b,c,sf)


def test_x_compose():
    state=_storage_state()
    if not state: return {"success":False,"stage":"configuration","message":"No X browser session configured."}
    started,error=_acquire_task("compose_starting")
    if error: return error
    b=c=sf=page=None
    try:
        with sync_playwright() as p:
            b,c,sf,page=_launch_context(p,state); _open_compose(page,started); lr=_login_state(page); ob=_onboarding_state(page)
            if lr or ob: return {"success":False,"stage":"login_required","message":"X did not open the compose page in the saved session.","login_redirect":lr,"onboarding":ob,"diagnostics":_diagnostics(page)}
            _set_task(stage="compose_waiting_editor"); editor=_wait_for_editor(page,started,10000); ef=editor is not None
            _set_task(stage="compose_checking_post_button"); button=_find_post_button(page) if ef else None
            r={"success":ef,"stage":"compose_ready" if ef else "editor_not_found","message":"X compose UI loaded and the tweet editor was found." if ef else "X opened, but the tweet editor was not rendered.","login_redirect":lr,"onboarding":ob,"editor_found":ef,"editor":None if not ef else {"data_testid":editor.get_attribute("data-testid"),"role":editor.get_attribute("role"),"contenteditable":editor.get_attribute("contenteditable")},"post_button_found":button is not None,"post_button":None if button is None else {"data_testid":button.get_attribute("data-testid"),"aria_label":button.get_attribute("aria-label"),"enabled":not button.is_disabled(timeout=800)},"diagnostics":_diagnostics(page)}
            _set_task(stage=r["stage"],last_result=r); return r
    except Exception as e:
        r={"success":False,"stage":"timeout" if isinstance(e,(TimeoutError,PlaywrightTimeoutError)) else "exception","message":f"X compose diagnostic failed: {type(e).__name__}: {e}","diagnostics":_diagnostics(page) if page else {}}; _set_task(stage="failed",last_result=r); return r
    finally: _cleanup_task(started,b,c,sf)
