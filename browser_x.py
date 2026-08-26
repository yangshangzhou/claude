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
_TASK_STATE: dict[str, Any] = {
    "busy": False,
    "stage": "idle",
    "started_at": None,
    "elapsed_seconds": 0,
    "text": "",
    "last_result": None,
}


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
    return {
        "ready": configured,
        "message": "X browser session is configured." if configured else "No X browser session configured. Set X_STORAGE_STATE to a Playwright storage_state JSON.",
        "task": _task_snapshot(),
    }


def _find_visible_editor(page):
    selectors = [
        '[data-testid="tweetTextarea_0"]',
        'div[contenteditable="true"][role="textbox"]',
        '[role="textbox"][contenteditable="true"]',
    ]
    for scope in (page.locator('[role="dialog"]'), page.locator('body')):
        try:
            if not scope.is_visible():
                continue
        except Exception:
            pass
        for selector in selectors:
            try:
                loc = scope.locator(selector)
                for i in range(min(loc.count(), 10)):
                    candidate = loc.nth(i)
                    if candidate.is_visible():
                        return candidate
            except Exception:
                pass
    return None


def _find_post_button(page):
    selectors = [
        '[data-testid="tweetButton"]',
        '[data-testid="tweetButtonInline"]',
        'button[aria-label="Post"]',
        'button[aria-label="Tweet"]',
    ]
    for scope in (page.locator('[role="dialog"]'), page.locator('body')):
        for selector in selectors:
            try:
                loc = scope.locator(selector)
                for i in range(min(loc.count(), 10)):
                    candidate = loc.nth(i)
                    if candidate.is_visible() and candidate.is_enabled():
                        return candidate
            except Exception:
                pass
        try:
            loc = scope.get_by_role("button", name="Post", exact=True)
            for i in range(min(loc.count(), 10)):
                candidate = loc.nth(i)
                if candidate.is_visible() and candidate.is_enabled():
                    return candidate
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
        test_ids = page.locator("[data-testid]").evaluate_all(
            "els => Array.from(new Set(els.map(e => e.getAttribute('data-testid')).filter(Boolean))).slice(0, 80)"
        )
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


def test_x_browser() -> dict[str, Any]:
    """Diagnostic only: launch Playwright with the saved X session and open X.

    This never opens the composer and never posts anything. It is intended to
    separate Playwright/browser/session problems from the create_post workflow.
    """
    state = _storage_state()
    if not state:
        return {
            "success": False,
            "stage": "configuration",
            "message": "No X browser session configured.",
        }

    if not _BROWSER_LOCK.acquire(blocking=False):
        return {
            "success": False,
            "busy": True,
            "stage": "lock",
            "message": "Another X browser task is currently running.",
            "task": _task_snapshot(),
        }

    started_at = time.time()
    _set_task(busy=True, stage="test_starting", started_at=started_at, elapsed_seconds=0, text="", last_result=None)
    browser = None
    context = None
    state_file = None
    page = None
    try:
        with sync_playwright() as p:
            _set_task(stage="test_launching_browser")
            browser = p.chromium.launch(
                headless=True,
                timeout=20000,
                args=[
                    "--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage",
                    "--disable-gpu", "--disable-software-rasterizer", "--disable-background-networking",
                    "--disable-background-timer-throttling", "--disable-backgrounding-occluded-windows",
                    "--disable-breakpad", "--disable-component-update", "--disable-default-apps",
                    "--disable-extensions", "--disable-plugins", "--disable-sync", "--disable-translate",
                    "--disable-features=Translate,BackForwardCache", "--mute-audio", "--no-first-run",
                    "--no-default-browser-check", "--no-zygote", "--renderer-process-limit=1",
                    "--js-flags=--max-old-space-size=96",
                ],
            )

            _set_task(stage="test_creating_context")
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
                f.write(state)
                state_file = f.name
            context = browser.new_context(
                storage_state=state_file,
                viewport={"width": 900, "height": 650},
                locale="en-US",
            )
            page = context.new_page()
            page.set_default_timeout(8000)
            _install_lightweight_network_policy(page)

            _set_task(stage="test_opening_x")
            page.goto(_HOME_URL, wait_until="commit", timeout=20000)
            page.wait_for_timeout(3000)

            diagnostics = _diagnostics(page)
            current_url = page.url
            login_redirect = "/i/flow/login" in current_url or "/login" in current_url
            onboarding = "/i/jf/" in current_url or "/onboarding" in current_url

            result = {
                "success": not login_redirect,
                "stage": "test_complete" if not login_redirect else "login_required",
                "message": (
                    "Playwright can launch and X opened with the saved browser session."
                    if not login_redirect
                    else "Playwright launched, but X redirected to a login flow; the saved session is not authenticated."
                ),
                "login_redirect": login_redirect,
                "onboarding": onboarding,
                "diagnostics": diagnostics,
            }
            _set_task(stage=result["stage"], last_result=result)
            return result

    except PlaywrightTimeoutError as exc:
        result = {
            "success": False,
            "stage": "timeout",
            "message": f"Playwright/X diagnostic timed out: {exc}",
            "diagnostics": _diagnostics(page) if page else {},
        }
        _set_task(stage="failed", last_result=result)
        return result
    except Exception as exc:
        result = {
            "success": False,
            "stage": "exception",
            "message": f"Playwright/X diagnostic failed: {type(exc).__name__}: {exc}",
            "diagnostics": _diagnostics(page) if page else {},
        }
        _set_task(stage="failed", last_result=result)
        return result
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if state_file:
            try:
                os.unlink(state_file)
            except Exception:
                pass
        _BROWSER_LOCK.release()
        with _TASK_STATE_LOCK:
            _TASK_STATE["busy"] = False
            _TASK_STATE["elapsed_seconds"] = round(time.time() - started_at, 1)


def post_x(text: str) -> dict[str, Any]:
    state = _storage_state()
    if not state:
        return browser_status()

    if not _BROWSER_LOCK.acquire(blocking=False):
        return {
            "success": False,
            "busy": True,
            "message": "Another X post is currently being processed. Check /mcp/post_status and retry after it finishes.",
            "task": _task_snapshot(),
        }

    started_at = time.time()
    _set_task(busy=True, stage="starting_browser", started_at=started_at, elapsed_seconds=0, text=text, last_result=None)

    try:
        with sync_playwright() as p:
            browser = None
            context = None
            state_file = None
            page = None
            try:
                _set_task(stage="launching_browser")
                browser = p.chromium.launch(
                    headless=True,
                    timeout=20000,
                    args=[
                        "--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage",
                        "--disable-gpu", "--disable-software-rasterizer", "--disable-background-networking",
                        "--disable-background-timer-throttling", "--disable-backgrounding-occluded-windows",
                        "--disable-breakpad", "--disable-component-update", "--disable-default-apps",
                        "--disable-extensions", "--disable-plugins", "--disable-sync", "--disable-translate",
                        "--disable-features=Translate,BackForwardCache", "--mute-audio", "--no-first-run",
                        "--no-default-browser-check", "--no-zygote", "--renderer-process-limit=1",
                        "--js-flags=--max-old-space-size=96",
                    ],
                )

                _set_task(stage="creating_browser_context")
                with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
                    f.write(state)
                    state_file = f.name
                context = browser.new_context(storage_state=state_file, viewport={"width": 900, "height": 650}, locale="en-US")
                page = context.new_page()
                page.set_default_timeout(8000)
                _install_lightweight_network_policy(page)

                _set_task(stage="opening_x")
                page.goto(COMPOSE_URL, wait_until="commit", timeout=20000)
                if "/i/flow/login" in page.url or "/login" in page.url:
                    result = {"success": False, "message": "X browser session has expired. Generate a new Playwright storage_state locally and update X_STORAGE_STATE on Render.", "diagnostics": _diagnostics(page)}
                    _set_task(stage="failed", last_result=result)
                    return result

                _set_task(stage="waiting_editor")
                editor_locator = page.locator('[data-testid="tweetTextarea_0"]').first
                try:
                    editor_locator.wait_for(state="visible", timeout=15000)
                    editor = editor_locator
                except PlaywrightTimeoutError:
                    editor = _find_visible_editor(page)
                    if editor is None:
                        result = {"success": False, "message": "X compose/tweet loaded, but the tweet editor was not rendered within 15 seconds.", "diagnostics": _diagnostics(page)}
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
                if context is not None:
                    try: context.close()
                    except Exception: pass
                if browser is not None:
                    try: browser.close()
                    except Exception: pass
                if state_file:
                    try: os.unlink(state_file)
                    except Exception: pass
    finally:
        _BROWSER_LOCK.release()
        with _TASK_STATE_LOCK:
            _TASK_STATE["busy"] = False
            _TASK_STATE["elapsed_seconds"] = round(time.time() - started_at, 1)
