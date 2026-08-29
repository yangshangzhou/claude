"""X post execution path v3.

Input strategy:
1) normal keyboard.type()
2) if DOM text did not change, keyboard.insert_text()
3) if still unchanged, set contenteditable text in DOM and dispatch real
   beforeinput/input events so X/React can update its composer state.
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
        try:
            editor.evaluate("el => el.click()", timeout=1000)
            page.wait_for_timeout(300)
            return True
        except Exception:
            return False


def _clear_editor(page, editor):
    try:
        editor.click(timeout=2000)
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        page.wait_for_timeout(300)
    except Exception:
        try:
            editor.evaluate("el => { el.focus(); el.textContent=''; el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'deleteContentBackward'})); }", timeout=1000)
            page.wait_for_timeout(300)
        except Exception:
            pass


def _dom_text(editor):
    try:
        return (editor.evaluate("el => (el.innerText || el.textContent || '').trim()", timeout=1000) or "").strip()
    except Exception:
        return ""


def _set_contenteditable_and_input(editor, text):
    # This is intentionally a fallback, not the first method. X's composer
    # is a React contenteditable; changing textContent alone is insufficient.
    # Dispatch beforeinput/input so the editor's React state can observe it.
    return editor.evaluate("""
    (el, value) => {
      el.focus();
      const before = new InputEvent('beforeinput', {
        bubbles: true,
        cancelable: true,
        inputType: 'insertText',
        data: value,
      });
      el.dispatchEvent(before);
      if (!before.defaultPrevented) {
        el.textContent = value;
      }
      el.dispatchEvent(new InputEvent('input', {
        bubbles: true,
        inputType: 'insertText',
        data: value,
      }));
      el.dispatchEvent(new Event('change', {bubbles:true}));
      return (el.innerText || el.textContent || '').trim();
    }
    """, text, timeout=1500)


def type_and_verify(page, editor, text):
    if not focus_editor(page, editor):
        return False, {"focused": False, "editor_text": "", "input_method": "none"}

    _clear_editor(page, editor)

    # Method 1: ordinary keyboard input.
    try:
        page.keyboard.type(text, delay=120)
        page.wait_for_timeout(1000)
    except Exception as exc:
        keyboard_error = f"{type(exc).__name__}: {exc}"
    else:
        keyboard_error = None

    current = find_editor(page)
    actual = _dom_text(current)
    if text.strip() in actual:
        return True, {"focused": True, "typed": True, "input_method": "keyboard.type", "editor_text": actual}

    # Method 2: insertText generates an input event without relying on key
    # mapping/composition handling.
    current = current or editor
    try:
        current.click(timeout=2000)
        page.keyboard.insert_text(text)
        page.wait_for_timeout(1000)
    except Exception as exc:
        insert_error = f"{type(exc).__name__}: {exc}"
    else:
        insert_error = None

    current = find_editor(page)
    actual = _dom_text(current)
    if text.strip() in actual:
        return True, {"focused": True, "typed": True, "input_method": "keyboard.insert_text", "editor_text": actual, "keyboard_error": keyboard_error}

    # Method 3: explicit DOM value + input events. This is the diagnostic
    # requested for the case where the DOM editor itself does not change.
    current = current or editor
    try:
        assigned = _set_contenteditable_and_input(current, text)
        page.wait_for_timeout(1200)
    except Exception as exc:
        assigned = ""
        assign_error = f"{type(exc).__name__}: {exc}"
    else:
        assign_error = None

    current = find_editor(page)
    actual = _dom_text(current)
    return text.strip() in actual, {
        "focused": True,
        "typed": True,
        "input_method": "dom_assignment_input_event",
        "editor_text": actual,
        "dom_assignment_result": assigned,
        "keyboard_error": keyboard_error,
        "insert_text_error": insert_error,
        "dom_assignment_error": assign_error,
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
        return {"data_testid": button.get_attribute("data-testid"), "disabled": button.is_disabled(timeout=800), "aria_disabled": button.get_attribute("aria-disabled")}
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
                return {"success": False, "stage": "typing_failed", "message": "Keyboard input and DOM assignment/input-event fallback did not produce verifiable text; nothing clicked.", **info, "diagnostics": bx._diagnostics(page)}

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
                return {"success": False, "stage": "post_button_disabled", "message": "Editor contains text but Post button remained disabled; nothing clicked.", "post_button": state_info, "editor_text": editor_text(find_editor(page)), "input_method": info.get("input_method"), "diagnostics": bx._diagnostics(page)}

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
                    result = {"success": True, "stage": "post_complete", "message": "Post clicked and composer cleared.", "post_button": state_info, "input_method": info.get("input_method"), "diagnostics": bx._diagnostics(page)}
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
