"""X post execution path v3: explicit three-step editor diagnosis."""
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
        try:
            editor.evaluate("el => el.focus()", timeout=1000)
            page.wait_for_timeout(300)
            return True
        except Exception:
            return False


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
        return {"found": False, "data_testid": None, "disabled": None, "aria_disabled": None}
    try:
        return {
            "found": True,
            "data_testid": button.get_attribute("data-testid"),
            "disabled": button.is_disabled(timeout=800),
            "aria_disabled": button.get_attribute("aria-disabled"),
        }
    except Exception as exc:
        return {"found": True, "data_testid": None, "disabled": None, "aria_disabled": None, "error": repr(exc)}


def _dom_text(editor):
    if not editor:
        return ""
    try:
        return (editor.evaluate("el => (el.innerText || el.textContent || '').trim()", timeout=1000) or "").strip()
    except Exception:
        return ""


def _clear_editor(page, editor):
    try:
        editor.click(timeout=2000)
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        page.wait_for_timeout(300)
    except Exception:
        pass


def _direct_dom_assignment(editor, text):
    """Last-resort diagnostic: mutate the contenteditable and emit input events."""
    return editor.evaluate("""
    (el, value) => {
      el.focus();
      el.textContent = value;
      el.dispatchEvent(new InputEvent('beforeinput', {
        bubbles: true, cancelable: true, inputType: 'insertText', data: value
      }));
      el.dispatchEvent(new InputEvent('input', {
        bubbles: true, inputType: 'insertText', data: value
      }));
      el.dispatchEvent(new Event('change', {bubbles: true}));
      return (el.innerText || el.textContent || '').trim();
    }
    """, text, timeout=1500)


def type_and_verify(page, editor, text):
    """Step 2 input test. Return the method that actually changed the editor."""
    if not focus_editor(page, editor):
        return False, {"input_method": "none", "editor_text": "", "focused": False}

    _clear_editor(page, editor)

    # First requested experiment: real keyboard input.
    keyboard_error = None
    try:
        page.keyboard.type(text, delay=100)
        page.wait_for_timeout(800)
    except Exception as exc:
        keyboard_error = f"{type(exc).__name__}: {exc}"

    current = find_editor(page) or editor
    actual = _dom_text(current)
    if text.strip() in actual:
        return True, {"input_method": "keyboard.type", "editor_text": actual, "focused": True, "keyboard_error": keyboard_error}

    # If keyboard.type did not change the DOM, try insert_text.
    insert_error = None
    try:
        current.click(timeout=2000)
        page.keyboard.insert_text(text)
        page.wait_for_timeout(800)
    except Exception as exc:
        insert_error = f"{type(exc).__name__}: {exc}"

    current = find_editor(page) or editor
    actual = _dom_text(current)
    if text.strip() in actual:
        return True, {"input_method": "keyboard.insert_text", "editor_text": actual, "focused": True, "keyboard_error": keyboard_error, "insert_error": insert_error}

    # Explicit assignment is only used after both real input methods failed.
    assignment_error = None
    assigned = ""
    try:
        assigned = _direct_dom_assignment(current, text)
        page.wait_for_timeout(800)
    except Exception as exc:
        assignment_error = f"{type(exc).__name__}: {exc}"

    current = find_editor(page) or editor
    actual = _dom_text(current)
    return text.strip() in actual, {
        "input_method": "dom_assignment_input_event",
        "editor_text": actual,
        "dom_assignment_result": assigned,
        "focused": True,
        "keyboard_error": keyboard_error,
        "insert_error": insert_error,
        "assignment_error": assignment_error,
    }


def post_x(text: str, image_base64=None, image_filename="image.png") -> dict[str, Any]:
    state = bx._storage_state()
    if not state:
        return bx.browser_status()

    started, lock_error = bx._acquire_task("starting_browser_v3")
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

            # ============================================================
            # STEP 1: Find editor ID and print Post button state.
            # ============================================================
            bx._set_task(stage="step1_find_editor")
            deadline = min(time.time() + 15, started + bx.TASK_HARD_TIMEOUT - 2)
            editor = None
            while time.time() < deadline:
                bx._check_deadline(started)
                editor = find_editor(page)
                if editor:
                    break
                page.wait_for_timeout(300)

            step1_button = button_state(post_button(page))
            if not editor:
                result = {
                    "success": False,
                    "stage": "step1_editor_not_found",
                    "step": 1,
                    "message": "1、没有找到 editor。",
                    "editor": {"found": False, "data_testid": None},
                    "post_button": step1_button,
                    "diagnostics": bx._diagnostics(page),
                }
                bx._set_task(stage=result["stage"], last_result=result)
                return result

            editor_id = editor.get_attribute("data-testid")
            step1 = {
                "found": True,
                "data_testid": editor_id,
                "role": editor.get_attribute("role"),
                "contenteditable": editor.get_attribute("contenteditable"),
            }
            # Do not call Post here. This is only the editor discovery check.

            # ============================================================
            # STEP 2: Type text, then re-read editor content and Post state.
            # ============================================================
            bx._set_task(stage="step2_type_and_verify")
            ok, input_info = type_and_verify(page, editor, text)
            current = find_editor(page) or editor
            reread_text = editor_text(current)
            step2_button = button_state(post_button(page))

            if not ok or text.strip() not in reread_text:
                result = {
                    "success": False,
                    "stage": "step2_editor_input_failed",
                    "step": 2,
                    "message": "2、EDITOR 输入后重新读取失败，EDITOR 内容没有正常改变。",
                    "editor": step1,
                    "input_method": input_info.get("input_method"),
                    "input_result": input_info,
                    "editor_text_after_input": reread_text,
                    "post_button": step2_button,
                    "diagnostics": bx._diagnostics(page),
                }
                bx._set_task(stage=result["stage"], last_result=result)
                return result

            # ============================================================
            # STEP 3: Content is verified. Print Post state again.
            # If disabled here, editor is proven to contain the text and the
            # remaining problem is NOT editor text insertion.
            # ============================================================
            bx._set_task(stage="step3_editor_verified")
            step3_button = button_state(post_button(page))
            if not step3_button.get("found"):
                result = {
                    "success": False,
                    "stage": "step3_post_button_not_found",
                    "step": 3,
                    "message": "3、EDITOR 内容已正常获取；但没有找到 POST 按钮，因此不是 EDITOR 内容读取问题。",
                    "editor": step1,
                    "editor_text_verified": reread_text,
                    "post_button": step3_button,
                    "diagnostics": bx._diagnostics(page),
                }
                bx._set_task(stage=result["stage"], last_result=result)
                return result

            if step3_button.get("disabled") or step3_button.get("aria_disabled") == "true":
                result = {
                    "success": False,
                    "stage": "step3_post_button_disabled",
                    "step": 3,
                    "message": "3、EDITOR 内容已正常获取，POST 按钮仍不可点击。问题不在 EDITOR。",
                    "editor": step1,
                    "editor_text_verified": reread_text,
                    "post_button": step3_button,
                    "diagnostics": bx._diagnostics(page),
                }
                bx._set_task(stage=result["stage"], last_result=result)
                return result

            # Only now is clicking Post allowed.
            bx._set_task(stage="clicking_post")
            button = post_button(page)
            button.click(timeout=5000)

            bx._set_task(stage="verifying_post")
            deadline = min(time.time() + 10, started + bx.TASK_HARD_TIMEOUT - 2)
            while time.time() < deadline:
                bx._check_deadline(started)
                if not editor_text(find_editor(page)):
                    result = {
                        "success": True,
                        "stage": "post_complete",
                        "step": 3,
                        "message": "3、EDITOR 内容正常，POST 按钮可点击，已完成点击并确认编辑器清空。",
                        "editor": step1,
                        "editor_text_verified": reread_text,
                        "post_button": step3_button,
                        "input_method": input_info.get("input_method"),
                        "diagnostics": bx._diagnostics(page),
                    }
                    bx._set_task(stage="post_complete", last_result=result)
                    return result
                page.wait_for_timeout(500)

            result = {
                "success": False,
                "stage": "post_verification_failed",
                "step": 3,
                "message": "3、EDITOR 内容正常且 POST 已点击，但无法确认编辑器清空。",
                "editor": step1,
                "editor_text_verified": reread_text,
                "post_button": step3_button,
                "diagnostics": bx._diagnostics(page),
            }
            bx._set_task(stage=result["stage"], last_result=result)
            return result

    except Exception as exc:
        result = {
            "success": False,
            "stage": "timeout" if isinstance(exc, (TimeoutError, PlaywrightTimeoutError)) else "exception",
            "message": f"X post v3 failed: {type(exc).__name__}: {exc}",
            "diagnostics": bx._diagnostics(page) if page else {},
        }
        bx._set_task(stage="failed", last_result=result)
        return result
    finally:
        if started is not None:
            bx._cleanup_task(started, browser, context, state_file)
