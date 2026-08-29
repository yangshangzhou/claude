"""X post execution path v3.

Uses the proven local_post_test selector order and deliberately does not
require document.activeElement to equal the tweetTextarea_0 element.
"""
import time
from typing import Any

import browser_x as bx
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


def find_editor(page):
    return bx._find_visible_editor(page)


def editor_text(editor):
    return bx._editor_text(editor)


def focus_editor(page, editor):
    try:
        editor.scroll_into_view_if_needed(timeout=1500)
        editor.click(timeout=3000)
        page.wait_for_timeout(300)
        return True
    except Exception:
        return False


def type_and_verify(page, editor, text):
    if not focus_editor(page, editor):
        return False, {"focused": False, "editor_text": ""}
    try:
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        page.wait_for_timeout(500)
        page.keyboard.type(text, delay=120)
        page.wait_for_timeout(1000)
    except Exception as exc:
        return False, {"focused": True, "typed": False, "error": f"{type(exc).__name__}: {exc}"}
    current = find_editor(page)
    actual = editor_text(current)
    return text.strip() in actual, {
        "focused": True,
        "typed": True,
        "editor_found_after_type": current is not None,
        "editor_text": actual,
    }


def post_button(page):
    for selector in ['[data-testid="tweetButtonInline"]', '[data-testid="tweetButton"]']:
        try:
            loc = page.locator(selector)
            for i in range(min(loc.count(), 10)):
                b = loc.nth(i)
                if bx._element_visible(b):
                    return b
        except Exception:
            pass
    return None


def button_state(button):
    if not button:
        return None
    try:
        return {
            "data_testid": button.get_attribute("data-testid"),
            "disabled": button.is_disabled(timeout=800),
            "aria_disabled": button.get_attribute("aria-disabled"),
        }
    except Exception as exc:
        return {"error": repr(exc)}


def post_x(text: str, image_base64=None, image_filename="image.png") -> dict[str, Any]:
    state = bx._storage_state()
    if not state:
        return bx.browser_status()
    started, error = bx._acquire_task("starting_browser_v3")
    if error:
        error["text"] = text
        return error
    browser = context = state_file = page = None
    try:
        with sync_playwright() as p:
            bx._set_task(stage="launching_browser")
            browser, context, state_file, page = bx._launch_context(p, state)
            bx._set_task(stage="opening_compose")
            try:
                page.goto(bx.COMPOSE_URL, wait_until="commit", timeout=12000)
            except PlaywrightTimeoutError as exc:
                return {"success": False, "stage": "navigation_timeout", "message": f"X compose navigation timeout: {exc}", "diagnostics": bx._diagnostics(page)}
            bx._set_task(stage="waiting_editor")
            deadline = time.time() + 15
            editor = None
            while time.time() < deadline:
                bx._check_deadline(started)
                editor = find_editor(page)
                if editor:
                    break
                page.wait_for_timeout(300)
            if not editor:
                return {"success": False, "stage": "editor_not_found", "message": "X compose opened but tweetTextarea_0 was not found; nothing clicked.", "diagnostics": bx._diagnostics(page)}

            bx._set_task(stage="typing")
            ok, info = type_and_verify(page, editor, text)
            if not ok:
                return {"success": False, "stage": "typing_failed", "message": "keyboard.type did not produce verifiable text in the re-located tweetTextarea_0 editor; nothing clicked.", **info, "diagnostics": bx._diagnostics(page)}

            bx._set_task(stage="typing_verified")
            deadline = min(time.time() + 15, started + bx.TASK_HARD_TIMEOUT - 2)
            button = None
            state_info = None
            while time.time() < deadline:
                bx._check_deadline(started)
                button = post_button(page)
                state_info = button_state(button)
                if state_info and not state_info.get("disabled") and state_info.get("aria_disabled") != "true":
                    break
                page.wait_for_timeout(400)
            if not button or not state_info or state_info.get("disabled") or state_info.get("aria_disabled") == "true":
                return {"success": False, "stage": "post_button_disabled", "message": "Post button remained disabled; nothing clicked.", "post_button": state_info, "editor_text": editor_text(find_editor(page)), "diagnostics": bx._diagnostics(page)}

            current = find_editor(page)
            final_text = editor_text(current)
            if text.strip() not in final_text:
                return {"success": False, "stage": "final_text_verification_failed", "message": "Text disappeared before Post click; nothing clicked.", "editor_text": final_text, "post_button": state_info, "diagnostics": bx._diagnostics(page)}

            bx._set_task(stage="clicking_post")
            button = post_button(page)
            if not button:
                return {"success": False, "stage": "post_button_not_found", "message": "Post button disappeared before click; nothing clicked.", "diagnostics": bx._diagnostics(page)}
            button.click(timeout=5000)

            bx._set_task(stage="verifying_post")
            deadline = min(time.time() + 10, started + bx.TASK_HARD_TIMEOUT - 2)
            while time.time() < deadline:
                bx._check_deadline(started)
                if not editor_text(find_editor(page)):
                    result = {"success": True, "stage": "post_complete", "message": "Post clicked and composer cleared.", "post_button": state_info, "diagnostics": bx._diagnostics(page)}
                    bx._set_task(stage="post_complete", last_result=result)
                    return result
                page.wait_for_timeout(500)
            return {"success": False, "stage": "verification_failed", "message": "Post was clicked but composer still contains text.", "editor_text_after": editor_text(find_editor(page)), "post_button": state_info, "diagnostics": bx._diagnostics(page)}
    except Exception as exc:
        result = {"success": False, "stage": "timeout" if isinstance(exc, (TimeoutError, PlaywrightTimeoutError)) else "exception", "message": f"X post v3 failed: {type(exc).__name__}: {exc}", "diagnostics": bx._diagnostics(page) if page else {}}
        bx._set_task(stage="failed", last_result=result)
        return result
    finally:
        if started is not None:
            bx._cleanup_task(started, browser, context, state_file)
