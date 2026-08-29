"""X post v3 input test: find editor, type, re-read editor, inspect POST state."""
import time
from typing import Any

import browser_x as bx
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


def _find_editor_dom(page):
    try:
        return page.evaluate("""
        () => {
          const el = document.querySelector('[data-testid="tweetTextarea_0"]')
                || document.querySelector('[contenteditable="true"][role="textbox"]');
          if (!el) return null;
          const r = el.getBoundingClientRect();
          return {
            testid: el.getAttribute('data-testid'),
            role: el.getAttribute('role'),
            contenteditable: el.getAttribute('contenteditable'),
            text: (el.innerText || el.textContent || '').trim(),
            html: el.innerHTML,
            rect: {x:r.x, y:r.y, w:r.width, h:r.height},
            focused: document.activeElement === el
          };
        }
        """)
    except Exception:
        return None


def _read_editor(page):
    info = _find_editor_dom(page)
    if not info:
        return {"found": False, "text": "", "html": "", "focused": False}
    return {
        "found": True,
        "data_testid": info.get("testid"),
        "role": info.get("role"),
        "contenteditable": info.get("contenteditable"),
        "text": info.get("text", ""),
        "html": info.get("html", ""),
        "focused": info.get("focused", False),
        "rect": info.get("rect")
    }


def _post_state(page):
    try:
        data = page.evaluate("""
        () => {
          const b = document.querySelector('[data-testid="tweetButtonInline"]')
                 || document.querySelector('[data-testid="tweetButton"]');
          if (!b) return {found:false};
          return {
            found:true,
            data_testid:b.getAttribute('data-testid'),
            disabled:b.disabled === true || b.getAttribute('aria-disabled') === 'true',
            aria_disabled:b.getAttribute('aria-disabled')
          };
        }
        """)
        return data or {"found": False}
    except Exception as exc:
        return {"found": False, "error": f"{type(exc).__name__}: {exc}"}


def _wait_until_page_and_editor_ready(page, started, timeout_seconds=25):
    """Wait for the rendered X composer to settle, then locate the editor.

    We do not use network-idle because X continuously loads timeline resources.
    The readiness signal is a stable, fully loaded document plus the actual
    composer/editor DOM being present.
    """
    deadline = min(time.time() + timeout_seconds, started + bx.TASK_HARD_TIMEOUT - 5)
    checks = 0
    last = None
    while time.time() < deadline:
        bx._check_deadline(started)
        checks += 1
        try:
            state = page.evaluate("""
            () => ({
              ready_state: document.readyState,
              body_exists: !!document.body,
              body_children: document.body ? document.body.children.length : 0,
              composer_text: !!Array.from(document.querySelectorAll('body *')).find(
                el => (el.textContent || '').trim() === "What's happening?" ||
                      (el.textContent || '').trim() === 'What’s happening?'
              ),
              editor: !!(document.querySelector('[data-testid="tweetTextarea_0"]') ||
                          document.querySelector('[contenteditable="true"][role="textbox"]')),
              post_button: !!(document.querySelector('[data-testid="tweetButtonInline"]') ||
                               document.querySelector('[data-testid="tweetButton"]'))
            })
            """)
            last = state
            if (
                state.get("ready_state") == "complete"
                and state.get("body_exists")
                and state.get("body_children", 0) >= 5
                and state.get("composer_text")
                and state.get("editor")
                and state.get("post_button")
            ):
                return {"ready": True, "checks": checks, "state": state}
        except Exception as exc:
            last = {"error": f"{type(exc).__name__}: {exc}"}
        page.wait_for_timeout(300)
    return {"ready": False, "checks": checks, "state": last}


def _keyboard_input(page, text):
    editor = page.locator('[data-testid="tweetTextarea_0"]').first
    editor.click(timeout=3000)
    page.wait_for_timeout(200)
    page.keyboard.type(text, delay=100)
    page.wait_for_timeout(800)
    return {"success": True, "method": "page.keyboard.type"}


def post_x(text: str, image_base64=None, image_filename="image.png") -> dict[str, Any]:
    state = bx._storage_state()
    if not state:
        return {"success": False, "stage": "configuration", "message": "No X browser session configured."}

    started, lock_error = bx._acquire_task("input_test")
    if lock_error:
        lock_error["text"] = text
        return lock_error

    browser = context = state_file = page = None
    try:
        with sync_playwright() as p:
            bx._set_task(stage="launching_browser")
            browser, context, state_file, page = bx._launch_context(p, state)

            bx._set_task(stage="opening_compose")
            page.goto(bx.COMPOSE_URL, wait_until="commit", timeout=12000)

            # 0. Wait until the rendered X composer is actually ready.
            bx._set_task(stage="step0_waiting_for_x_app")
            ready = _wait_until_page_and_editor_ready(page, started)
            if not ready["ready"]:
                return {
                    "success": False,
                    "stage": "step0_x_app_not_ready",
                    "step": 0,
                    "message": "0、X 页面/UI 尚未达到可测试状态。",
                    "app": ready,
                    "post_button": _post_state(page),
                    "diagnostics": bx._diagnostics(page)
                }

            # 1. Find editor and print its initial state.
            editor_before = _read_editor(page)
            post_before = _post_state(page)
            if not editor_before.get("found"):
                return {
                    "success": False,
                    "stage": "step1_editor_not_found",
                    "step": 1,
                    "message": "1、没有找到 editor。",
                    "editor": editor_before,
                    "post_button": post_before,
                    "diagnostics": bx._diagnostics(page)
                }

            # 2. Keyboard input, then immediately re-read editor and POST.
            bx._set_task(stage="step2_keyboard_input")
            operation = _keyboard_input(page, text)
            editor_after = _read_editor(page)
            post_after = _post_state(page)
            verified = bool(text.strip()) and text.strip() in editor_after.get("text", "")

            result = {
                "success": False,
                "stage": "step2_input_test_complete",
                "message": "2、已完成键盘输入并重新读取 editor；未点击 POST。",
                "step1_editor": editor_before,
                "step1_post_button": post_before,
                "step2_keyboard_input": {
                    "input_text": text,
                    "operation": operation,
                    "editor_after": editor_after,
                    "text_verified": verified,
                    "post_button_after": post_after
                },
                "diagnostics": bx._diagnostics(page)
            }
            bx._set_task(stage=result["stage"], last_result=result)
            return result

    except Exception as exc:
        result = {
            "success": False,
            "stage": "timeout" if isinstance(exc, (TimeoutError, PlaywrightTimeoutError)) else "exception",
            "message": f"X input test failed: {type(exc).__name__}: {exc}",
            "diagnostics": bx._diagnostics(page) if page else {}
        }
        bx._set_task(stage="failed", last_result=result)
        return result
    finally:
        if started is not None:
            bx._cleanup_task(started, browser, context, state_file)
