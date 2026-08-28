"""X posting flow.

Keep this module deliberately close to the proven local_post_test.py flow:
click editor -> keyboard.type -> verify text -> wait for enabled Post -> click -> verify.
"""

import base64
import mimetypes
import time
from typing import Any

import browser_x as bx
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

MAX_IMAGE_BYTES = 5 * 1024 * 1024
POST_TIMEOUT = 45


def _find_editor(page):
    return bx._find_visible_editor(page)


def _editor_text(editor) -> str:
    return bx._editor_text(editor)


def _focus_editor(page, editor) -> bool:
    try:
        editor.scroll_into_view_if_needed(timeout=3000)
        editor.click(timeout=3000)
        page.wait_for_timeout(300)
        return bool(page.evaluate("""() => {
            const e=document.activeElement;
            return !!e && (e.getAttribute('data-testid')==='tweetTextarea_0' || e.getAttribute('role')==='textbox' || e.getAttribute('contenteditable')==='true');
        }"""))
    except Exception:
        return False


def _type_into_editor(page, editor, text: str) -> bool:
    if not _focus_editor(page, editor):
        return False
    try:
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        page.wait_for_timeout(300)
        # This is intentionally the same mechanism used by the known local test.
        page.keyboard.type(text, delay=80)
        page.wait_for_timeout(1000)
    except Exception:
        return False
    return text.strip() in _editor_text(editor)


def _button_state(button) -> dict[str, Any] | None:
    if button is None:
        return None
    try:
        return {
            "data_testid": button.get_attribute("data-testid"),
            "aria_label": button.get_attribute("aria-label"),
            "disabled": button.is_disabled(timeout=1000),
            "aria_disabled": button.get_attribute("aria-disabled"),
            "text": (button.inner_text(timeout=500) or "").strip(),
        }
    except Exception as exc:
        return {"error": repr(exc)}


def _find_post_button_any_state(page):
    """Find Post even when it is disabled, so diagnostics show the real state."""
    try:
        loc = page.locator('[data-testid="tweetButtonInline"], [data-testid="tweetButton"]')
        for i in range(min(loc.count(), 10)):
            candidate = loc.nth(i)
            if bx._element_visible(candidate):
                return candidate
    except Exception:
        pass
    try:
        buttons = page.locator("button")
        for i in range(min(buttons.count(), 200)):
            candidate = buttons.nth(i)
            if not bx._element_visible(candidate):
                continue
            aria = (candidate.get_attribute("aria-label") or "").strip()
            text = (candidate.inner_text(timeout=300) or "").strip()
            if aria in {"Post", "Tweet"} or text in {"Post", "Tweet"}:
                return candidate
    except Exception:
        pass
    return None


def _decode_image(image_base64: str, filename: str) -> tuple[bytes, str, str]:
    raw = image_base64.strip()
    mime = None
    if raw.startswith("data:") and "," in raw:
        header, raw = raw.split(",", 1)
        mime = header[5:].split(";", 1)[0].strip() or None
    data = base64.b64decode(raw, validate=True)
    if not data:
        raise ValueError("image_base64 is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("image exceeds 5 MB")
    mime = mime or mimetypes.guess_type(filename)[0] or "image/png"
    if not mime.startswith("image/"):
        raise ValueError(f"unsupported media type: {mime}")
    return data, mime, filename or "image.png"


def _upload_image(page, image_base64: str, filename: str) -> dict[str, Any]:
    data, mime, filename = _decode_image(image_base64, filename)
    bx._set_task(stage="uploading_image")
    file_input = page.locator('input[type="file"]').first
    if not file_input.count():
        raise RuntimeError("X composer file input was not found")
    file_input.set_input_files({"name": filename, "mimeType": mime, "buffer": data})
    deadline = time.time() + 12
    while time.time() < deadline:
        try:
            state = page.evaluate("""() => {
                const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'};
                const root=[...document.querySelectorAll('[role="dialog"]')].find(visible)||document.body;
                return {images:[...root.querySelectorAll('img')].filter(visible).length};
            }""")
            if state.get("images", 0) > 0:
                return {"success": True, "bytes": len(data), "mime": mime, "filename": filename}
        except Exception:
            pass
        page.wait_for_timeout(400)
    return {"success": False, "bytes": len(data), "mime": mime, "filename": filename}


def _post_verified(page, editor, text: str, started: float, upload: dict[str, Any] | None) -> dict[str, Any]:
    before = _editor_text(editor)
    if text.strip() not in before:
        return {"success": False, "stage": "final_text_verification_failed", "message": "Text is not present immediately before Post; nothing clicked.", "editor_text": before, "upload": upload}

    bx._set_task(stage="waiting_post_button")
    button = None
    state = None
    deadline = time.time() + 15
    while time.time() < deadline:
        bx._check_deadline(started)
        button = _find_post_button_any_state(page)
        state = _button_state(button)
        if state and not state.get("disabled") and state.get("aria_disabled") != "true":
            break
        page.wait_for_timeout(500)

    if not button or not state or state.get("disabled") or state.get("aria_disabled") == "true":
        return {"success": False, "stage": "post_button_disabled", "message": "Post button was found but remained disabled; nothing clicked.", "post_button": state, "editor_text": _editor_text(editor), "upload": upload, "diagnostics": bx._diagnostics(page)}

    final_text = _editor_text(editor)
    if text.strip() not in final_text:
        return {"success": False, "stage": "final_text_verification_failed", "message": "Editor text changed before click; nothing clicked.", "editor_text": final_text, "post_button": state, "upload": upload}

    bx._set_task(stage="clicking_post")
    button.scroll_into_view_if_needed(timeout=3000)
    button.click(timeout=5000)
    bx._set_task(stage="verifying_post")

    deadline = time.time() + 10
    last_text = ""
    while time.time() < deadline:
        bx._check_deadline(started)
        try:
            last_text = _editor_text(editor)
        except Exception:
            last_text = ""
        if not last_text:
            return {"success": True, "stage": "post_complete", "message": "X Post click completed and composer was cleared.", "post_button": state, "upload": upload, "diagnostics": bx._diagnostics(page)}
        page.wait_for_timeout(500)

    return {"success": False, "stage": "verification_failed", "message": "Post was clicked but the composer still contains text.", "editor_text_after": last_text, "post_button": state, "upload": upload, "diagnostics": bx._diagnostics(page)}


def test_x_typing(text: str = "LOCAL_X_TYPING_TEST") -> dict[str, Any]:
    state = bx._storage_state()
    if not state:
        return {"success": False, "stage": "configuration", "message": "No X browser session configured."}
    started, error = bx._acquire_task("typing_test_starting")
    if error:
        error["text"] = text
        return error
    bx._set_task(text=text)
    browser = context = state_file = page = None
    try:
        with sync_playwright() as p:
            browser, context, state_file, page = bx._launch_context(p, state)
            bx._open_compose(page, started)
            if bx._login_state(page):
                return {"success": False, "stage": "login_required", "message": "X browser session has expired.", "diagnostics": bx._diagnostics(page)}
            editor = bx._wait_for_editor(page, started, 12000)
            if not editor:
                return {"success": False, "stage": "editor_not_found", "message": "Visible X editor was not found.", "diagnostics": bx._diagnostics(page)}
            focused = _focus_editor(page, editor)
            typed = _type_into_editor(page, editor, text) if focused else False
            result = {"success": typed, "stage": "typing_test_complete" if typed else "typing_failed", "message": "Editor -> keyboard.type -> verification complete. Post was NOT clicked.", "focused": focused, "editor_text": _editor_text(editor), "post_button": _button_state(_find_post_button_any_state(page)), "diagnostics": bx._diagnostics(page)}
            bx._set_task(stage=result["stage"], last_result=result)
            return result
    except Exception as exc:
        result = {"success": False, "stage": "timeout" if isinstance(exc, (TimeoutError, PlaywrightTimeoutError)) else "exception", "message": f"X typing test failed: {type(exc).__name__}: {exc}", "diagnostics": bx._diagnostics(page) if page else {}}
        bx._set_task(stage="failed", last_result=result)
        return result
    finally:
        bx._cleanup_task(started, browser, context, state_file)


def post_x(text: str, image_base64: str | None = None, image_filename: str = "image.png") -> dict[str, Any]:
    state = bx._storage_state()
    if not state:
        return bx.browser_status()
    started, error = bx._acquire_task("starting_browser")
    if error:
        error["text"] = text
        return error
    bx._set_task(text=text)
    browser = context = state_file = page = None
    try:
        with sync_playwright() as p:
            bx._set_task(stage="launching_browser")
            browser, context, state_file, page = bx._launch_context(p, state)
            bx._set_task(stage="opening_compose")
            bx._open_compose(page, started)
            bx._check_deadline(started)
            if bx._login_state(page):
                return {"success": False, "stage": "login_required", "message": "X browser session has expired.", "diagnostics": bx._diagnostics(page)}
            if bx._onboarding_state(page):
                return {"success": False, "stage": "onboarding", "message": "X opened onboarding instead of compose.", "diagnostics": bx._diagnostics(page)}

            bx._set_task(stage="waiting_editor")
            editor = _find_editor(page)
            if not editor:
                editor = bx._wait_for_editor(page, started, 12000)
            if not editor:
                return {"success": False, "stage": "editor_not_found", "message": "X composer did not render a visible editor; nothing clicked.", "diagnostics": bx._diagnostics(page)}

            upload = None
            if image_base64:
                upload = _upload_image(page, image_base64, image_filename)
                if not upload.get("success"):
                    return {"success": False, "stage": "image_upload_failed", "message": "Image was not verified in the composer; nothing clicked.", "upload": upload, "diagnostics": bx._diagnostics(page)}

            bx._set_task(stage="typing")
            if not _type_into_editor(page, editor, text):
                return {"success": False, "stage": "typing_failed", "message": "Text was not verified inside the editor; nothing clicked.", "editor_text": _editor_text(editor), "upload": upload, "diagnostics": bx._diagnostics(page)}

            bx._set_task(stage="typing_verified")
            result = _post_verified(page, editor, text, started, upload)
            bx._set_task(stage=result["stage"], last_result=result)
            return result
    except Exception as exc:
        result = {"success": False, "stage": "timeout" if isinstance(exc, (TimeoutError, PlaywrightTimeoutError)) else "exception", "message": f"X post failed: {type(exc).__name__}: {exc}", "diagnostics": bx._diagnostics(page) if page else {}}
        bx._set_task(stage="failed", last_result=result)
        return result
    finally:
        bx._cleanup_task(started, browser, context, state_file)
