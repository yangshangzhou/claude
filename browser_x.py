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


def browser_status() -> dict[str, Any]:
    configured = bool(_storage_state())
    return {"ready": configured, "message": "X browser session is configured." if configured else "No X browser session configured. Set X_STORAGE_STATE to a Playwright storage_state JSON.", "task": _task_snapshot()}


def _find_visible_editor(page):
    selectors = ['[data-testid="tweetTextarea_0"]', 'div[contenteditable="true"][role="textbox"]', '[role="textbox"][contenteditable="true"]']
    for selector in selectors:
        try:
            loc = page.locator(selector)
            count = min(loc.count(), 10)
            for i in range(count):
                candidate = loc.nth(i)
                if candidate.is_visible():
                    return candidate
        except Exception:
            continue
    return None


def _find_post_button(page):
    """Fast X Post button lookup. Avoid broad body scans and role queries."""
    selectors = [
        '[data-testid="tweetButton"]',
        '[data-testid="tweetButtonInline"]',
        '[data-testid="tweetButton"]:visible',
        '[data-testid="tweetButtonInline"]:visible',
    ]
    for selector in selectors:
        try:
            loc = page.locator(selector)
            count = min(loc.count(), 5)
            for i in range(count):
                candidate = loc.nth(i)
                if candidate.is_visible() and candidate.is_enabled():
                    return candidate
        except Exception:
            continue
    # Only if testids are unavailable, use a narrowly scoped visible button query.
    try:
        loc = page.locator('button:visible')
        count = min(loc.count(), 80)
        for i in range(count):
            candidate = loc.nth(i)
            try:
                aria = candidate.get_attribute("aria-label")
                text = (candidate.inner_text(timeout=300) or "").strip()
                if (aria in {"Post", "Tweet"} or text in {"Post", "Tweet"}) and candidate.is_enabled():
                    return candidate
            except Exception:
                continue
    except Exception:
        pass
    return None


def _diagnostics(page) -> dict[str, Any]:
    body_text = ""
    test_ids: list[str] = []
    try:
        body_text = page.locator("body").inner_text(timeout=1500)[:2000]
    except Exception:
        pass
    try:
        test_ids = page.locator("[data-testid]").evaluate_all("els => Array.from(new Set(els.map(e => e.getAttribute('data-testid')).filter(Boolean))).slice(0, 80)")
    except Exception:
        pass
    return {"url": page.url, "title": page.title(), "body": body_text, "test_ids": test_ids}


def _install_lightweight_network_policy(page) -> None:
    def handle_route(route):
        if route.request.resource_type in {"image", "media", "font"}:
            route.abort()
        else:
            route.continue_()
    page.route("**/*", handle_route)


def _launch_context(p, state: str):
    browser = p.chromium.launch(headless=True, timeout=20000, args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--disable-software-rasterizer", "--disable-background-networking", "--disable-background-timer-throttling", "--disable-backgrounding-occluded-windows", "--disable-breakpad", "--disable-component-update", "--disable-default-apps", "--disable-extensions", "--disable-plugins", "--disable-sync", "--disable-translate", "--disable-features=Translate,BackForwardCache", "--mute-audio", "--no-first-run", "--no-default-browser-check", "--no-zygote", "--renderer-process-limit=1", "--js-flags=--max-old-space-size=96"])
    state_file = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    state_file.write(state)
    state_file.close()
    context = browser.new_context(storage_state=state_file.name, viewport={"width": 900, "height": 650}, locale="en-US")
    page = context.new_page()
    page.set_default_timeout(5000)
    _install_lightweight_network_policy(page)
    return browser, context, state_file.name, page


def _acquire_task(stage: str):
    if not _BROWSER_LOCK.acquire(blocking=False):
        return None, {"success": False, "busy": True, "stage": "lock", "message": "Another X browser task is currently running.", "task": _task_snapshot()}
    started_at = time.time()
    _set_task(busy=True, stage=stage, started_at=started_at, elapsed_seconds=0, text="", last_result=None)
    return started_at, None


def _cleanup_task(started_at, browser, context, state_file):
    if context is not None:
        try: context.close()
        except Exception: pass
    if browser is not None:
        try: browser.close()
        except Exception: pass
    if state_file:
        try: os.unlink(state_file)
        except Exception: pass
    try:
        _BROWSER_LOCK.release()
    except RuntimeError:
        pass
    with _TASK_STATE_LOCK:
        _TASK_STATE["busy"] = False
        _TASK_STATE["stage"] = "idle"
        _TASK_STATE["elapsed_seconds"] = round(time.time() - started_at, 1)


def test_x_browser() -> dict[str, Any]:
    state = _storage_state()
    if not state:
        return {"success": False, "stage": "configuration", "message": "No X browser session configured."}
    started_at, error = _acquire_task("test_starting")
    if error:
        return error
    browser = context = None
    state_file = None
    page = None
    try:
        with sync_playwright() as p:
            _set_task(stage="test_launching_browser")
            browser, context, state_file, page = _launch_context(p, state)
            _set_task(stage="test_opening_x")
            page.goto(_HOME_URL, wait_until="commit", timeout=20000)
            page.wait_for_timeout(3000)
            diagnostics = _diagnostics(page)
            current_url = page.url
            login_redirect = "/i/flow/login" in current_url or "/login" in current_url
            onboarding = "/i/jf/" in current_url or "/onboarding" in current_url
            result = {"success": not login_redirect, "stage": "test_complete" if not login_redirect else "login_required", "message": "Playwright can launch and X opened with the saved browser session." if not login_redirect else "Playwright launched, but X redirected to a login flow; the saved session is not authenticated.", "login_redirect": login_redirect, "onboarding": onboarding, "diagnostics": diagnostics}
            _set_task(stage=result["stage"], last_result=result)
            return result
    except PlaywrightTimeoutError as exc:
        result = {"success": False, "stage": "timeout", "message": f"Playwright/X diagnostic timed out: {exc}", "diagnostics": _diagnostics(page) if page else {}}
        _set_task(stage="failed", last_result=result)
        return result
    except Exception as exc:
        result = {"success": False, "stage": "exception", "message": f"Playwright/X diagnostic failed: {type(exc).__name__}: {exc}", "diagnostics": _diagnostics(page) if page else {}}
        _set_task(stage="failed", last_result=result)
        return result
    finally:
        _cleanup_task(started_at, browser, context, state_file)


def test_x_compose() -> dict[str, Any]:
    """Diagnostic only: open X compose and inspect editor/button; never types or posts."""
    state = _storage_state()
    if not state:
        return {"success": False, "stage": "configuration", "message": "No X browser session configured."}
    started_at, error = _acquire_task("compose_starting")
    if error:
        return error
    browser = context = None
    state_file = None
    page = None
    try:
        with sync_playwright() as p:
            _set_task(stage="compose_launching_browser")
            browser, context, state_file, page = _launch_context(p, state)
            _set_task(stage="compose_opening_x")
            page.goto(COMPOSE_URL, wait_until="commit", timeout=20000)
            page.wait_for_timeout(2500)
            current_url = page.url
            login_redirect = "/i/flow/login" in current_url or "/login" in current_url
            onboarding = "/i/jf/" in current_url or "/onboarding" in current_url
            if login_redirect or onboarding:
                result = {"success": False, "stage": "login_required", "message": "X did not open the compose page in the saved session.", "login_redirect": login_redirect, "onboarding": onboarding, "diagnostics": _diagnostics(page)}
                _set_task(stage="failed", last_result=result)
                return result
            _set_task(stage="compose_checking_editor")
            editor = _find_visible_editor(page)
            editor_found = editor is not None
            editor_details = None
            if editor_found:
                try:
                    editor_details = {"tag": editor.evaluate("el => el.tagName"), "role": editor.get_attribute("role"), "contenteditable": editor.get_attribute("contenteditable"), "data_testid": editor.get_attribute("data-testid")}
                except Exception: pass
            _set_task(stage="compose_checking_post_button")
            post_button = _find_post_button(page)
            post_button_found = post_button is not None
            post_button_details = None
            if post_button_found:
                try:
                    post_button_details = {"tag": post_button.evaluate("el => el.tagName"), "aria_label": post_button.get_attribute("aria-label"), "data_testid": post_button.get_attribute("data-testid"), "enabled": post_button.is_enabled()}
                except Exception: pass
            diagnostics = _diagnostics(page)
            result = {"success": editor_found, "stage": "compose_ready" if editor_found else "editor_not_found", "message": "X compose page loaded and the tweet editor was found." if editor_found else "X compose page loaded, but no visible tweet editor was found.", "login_redirect": login_redirect, "onboarding": onboarding, "editor_found": editor_found, "editor": editor_details, "post_button_found": post_button_found, "post_button": post_button_details, "diagnostics": diagnostics}
            _set_task(stage=result["stage"], last_result=result)
            return result
    except PlaywrightTimeoutError as exc:
        result = {"success": False, "stage": "timeout", "message": f"X compose diagnostic timed out: {exc}", "diagnostics": _diagnostics(page) if page else {}}
        _set_task(stage="failed", last_result=result)
        return result
    except Exception as exc:
        result = {"success": False, "stage": "exception", "message": f"X compose diagnostic failed: {type(exc).__name__}: {exc}", "diagnostics": _diagnostics(page) if page else {}}
        _set_task(stage="failed", last_result=result)
        return result
    finally:
        _cleanup_task(started_at, browser, context, state_file)


def post_x(text: str) -> dict[str, Any]:
    state = _storage_state()
    if not state:
        return browser_status()
    started_at, error = _acquire_task("starting_browser")
    if error:
        error["text"] = text
        return error
    _set_task(text=text)
    browser = context = None
    state_file = None
    page = None
    try:
        with sync_playwright() as p:
            _set_task(stage="launching_browser")
            browser, context, state_file, page = _launch_context(p, state)
            _set_task(stage="opening_x")
            page.goto(COMPOSE_URL, wait_until="commit", timeout=20000)
            if "/i/flow/login" in page.url or "/login" in page.url:
                result = {"success": False, "message": "X browser session has expired. Generate a new Playwright storage_state locally and update X_STORAGE_STATE on Render.", "diagnostics": _diagnostics(page)}
                _set_task(stage="failed", last_result=result)
                return result
            _set_task(stage="waiting_editor")
            editor = _find_visible_editor(page)
            if editor is None:
                result = {"success": False, "message": "X compose/tweet loaded, but the tweet editor was not rendered.", "diagnostics": _diagnostics(page)}
                _set_task(stage="failed", last_result=result)
                return result
            _set_task(stage="typing")
            editor.click()
            editor.press_sequentially(text, delay=3)
            _set_task(stage="waiting_post_button")
            button = _find_post_button(page)
            if button is None:
                result = {"success": False, "message": "X editor was found and text was typed, but the Post button was not enabled/rendered.", "diagnostics": _diagnostics(page)}
                _set_task(stage="failed", last_result=result)
                return result
            _set_task(stage="clicking_post")
            button.click()
            _set_task(stage="verifying_post")
            try:
                editor.wait_for(state="hidden", timeout=10000)
                result = {"success": True, "message": "Post submitted through X web browser automation.", "url": page.url}
            except PlaywrightTimeoutError:
                result = {"success": False, "message": "X Post button was clicked, but the composer is still open; submission could not be verified.", "diagnostics": _diagnostics(page)}
            _set_task(stage="finished" if result.get("success") else "failed", last_result=result)
            return result
    except PlaywrightTimeoutError as exc:
        result = {"success": False, "message": f"X web UI timed out: {exc}", "diagnostics": _diagnostics(page) if page else {}}
        _set_task(stage="failed", last_result=result)
        return result
    except Exception as exc:
        result = {"success": False, "message": f"X browser automation failed: {type(exc).__name__}: {exc}", "diagnostics": _diagnostics(page) if page else {}}
        _set_task(stage="failed", last_result=result)
        return result
    finally:
        _cleanup_task(started_at, browser, context, state_file)
