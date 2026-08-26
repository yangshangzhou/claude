"""Deterministic X composer typing + media upload layer."""

import base64
import mimetypes
import time
from typing import Any

import browser_x as bx
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _focus_editor(page, editor) -> bool:
    try:
        editor.scroll_into_view_if_needed(timeout=1500)
        editor.click(timeout=1500)
        editor.focus(timeout=1500)
        return bool(page.evaluate("""() => {
            const el = document.activeElement;
            return !!el && (
                el.getAttribute('data-testid') === 'tweetTextarea_0' ||
                (el.getAttribute('role') === 'textbox' && el.getAttribute('contenteditable') === 'true') ||
                el.getAttribute('contenteditable') === 'true'
            );
        }"""))
    except Exception:
        return False


def _type_into_editor(page, editor, text: str) -> bool:
    if not _focus_editor(page, editor):
        return False
    try:
        editor.press_sequentially(text, delay=20, timeout=8000)
    except Exception:
        try:
            page.keyboard.type(text, delay=20)
        except Exception:
            return False
    page.wait_for_timeout(700)
    actual = bx._editor_text(editor)
    return bool(actual) and text.strip() in actual


def _decode_image(image_base64: str, filename: str) -> tuple[bytes, str, str]:
    raw = image_base64.strip()
    mime = None
    if raw.startswith("data:") and "," in raw:
        header, raw = raw.split(",", 1)
        mime = header[5:].split(";", 1)[0].strip() or None
    try:
        data = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise ValueError(f"image_base64 is not valid base64: {exc}") from exc
    if not data:
        raise ValueError("image_base64 is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"image is too large; maximum is {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    mime = mime or mimetypes.guess_type(filename)[0] or "image/png"
    if not mime.startswith("image/"):
        raise ValueError(f"unsupported media type: {mime}")
    return data, mime, filename or "image.png"


def _find_file_input(page):
    try:
        inputs = page.locator('input[type="file"]')
        for i in range(inputs.count()):
            candidate = inputs.nth(i)
            try:
                accept = candidate.get_attribute("accept") or ""
                if not accept or "image" in accept.lower() or "video" in accept.lower():
                    return candidate
            except Exception:
                continue
    except Exception:
        pass
    return None


def _composer_media_state(page) -> dict[str, Any]:
    """Return lightweight evidence that an attachment is present in the composer."""
    try:
        return page.evaluate("""() => {
            const visible = el => { const r=el.getBoundingClientRect(), s=getComputedStyle(el); return s.display!=='none' && s.visibility!=='hidden' && r.width>0 && r.height>0; };
            const dialog = [...document.querySelectorAll('[role="dialog"]')].find(visible) || document.body;
            const imgs = [...dialog.querySelectorAll('img')].filter(visible);
            const removeLabels = [...dialog.querySelectorAll('[aria-label]')]
              .map(e => e.getAttribute('aria-label') || '')
              .filter(x => /remove|delete/i.test(x));
            return {
                visible_images: imgs.length,
                image_srcs: imgs.slice(-5).map(e => e.getAttribute('src') || '').filter(Boolean),
                remove_labels: removeLabels.slice(-10)
            };
        }""")
    except Exception:
        return {"visible_images": 0, "image_srcs": [], "remove_labels": []}


def _upload_image(page, image_base64: str, filename: str) -> dict[str, Any]:
    data, mime, filename = _decode_image(image_base64, filename)
    bx._set_task(stage="uploading_image")

    file_input = _find_file_input(page)
    if file_input is None:
        # X normally keeps the file input hidden in the DOM. If the first render
        # has not created it yet, click the media control once and look again.
        media = None
        for selector in [
            '[data-testid="fileInput"]',
            '[aria-label="Add photos or video"]',
            '[aria-label="Add photo or video"]',
        ]:
            try:
                loc = page.locator(selector).first
                if loc.count() and loc.is_visible(timeout=500):
                    media = loc
                    break
            except Exception:
                pass
        if media:
            try:
                media.click(timeout=1500)
                page.wait_for_timeout(500)
            except Exception:
                pass
        file_input = _find_file_input(page)

    if file_input is None:
        raise RuntimeError("X composer file input was not found")

    file_input.set_input_files({"name": filename, "mimeType": mime, "buffer": data})

    # Do not type/click until X has had time to process the attachment.
    deadline = time.time() + 12
    last_state = {}
    while time.time() < deadline:
        last_state = _composer_media_state(page)
        if last_state.get("visible_images", 0) > 0 or last_state.get("remove_labels"):
            return {"success": True, "bytes": len(data), "mime": mime, "filename": filename, "state": last_state}
        try:
            file_count = page.locator('input[type="file"]').first.evaluate("el => el.files ? el.files.length : 0")
            if file_count:
                # X can clear the input after ingestion, so this is only a
                # secondary signal. Keep waiting for a visible composer state.
                pass
        except Exception:
            pass
        page.wait_for_timeout(400)

    return {"success": False, "bytes": len(data), "mime": mime, "filename": filename, "state": last_state}


def _post_after_verified_editor(page, editor, text: str, started: float, upload_result: dict[str, Any] | None = None) -> dict[str, Any]:
    editor_text_before = bx._editor_text(editor)
    if text.strip() not in editor_text_before:
        return {"success": False, "stage": "final_text_verification_failed", "message": "Editor text is not verified immediately before Post. Post was NOT clicked.", "editor_text": editor_text_before, "upload": upload_result}

    bx._set_task(stage="waiting_post_button")
    button = None
    deadline = time.time() + 12
    while time.time() < deadline:
        bx._check_deadline(started)
        button = bx._find_post_button(page)
        if button:
            break
        page.wait_for_timeout(300)

    if button is None:
        return {"success": False, "stage": "post_button_not_found", "message": "Text/media is ready, but X kept Post disabled or unavailable. Post was NOT clicked.", "editor_text": editor_text_before, "upload": upload_result, "diagnostics": bx._diagnostics(page)}

    button_info = {
        "data_testid": button.get_attribute("data-testid"),
        "aria_label": button.get_attribute("aria-label"),
        "enabled": not button.is_disabled(timeout=800),
    }
    final_editor_text = bx._editor_text(editor)
    if text.strip() not in final_editor_text:
        return {"success": False, "stage": "final_text_verification_failed", "message": "Editor text changed before click. Post was NOT clicked.", "editor_text": final_editor_text, "post_button": button_info, "upload": upload_result}

    bx._set_task(stage="clicking_post")
    button.scroll_into_view_if_needed(timeout=1500)
    button.click(timeout=2500)
    bx._set_task(stage="verifying_post")
    page.wait_for_timeout(1500)

    text_after = bx._editor_text(editor)
    alert = ""
    try:
        alert = (page.locator('[role="alert"]').first.text_content(timeout=800) or "").strip()
    except Exception:
        pass

    success = not text_after
    return {
        "success": success,
        "stage": "post_complete" if success else "verification_failed",
        "message": "X post with media submitted successfully." if success else "Post was clicked but the composer still contains text.",
        "verification": {"editor_text_before": editor_text_before[:500], "editor_text_after": text_after[:500], "alert": alert[:500]},
        "post_button": button_info,
        "upload": upload_result,
        "diagnostics": bx._diagnostics(page),
    }


def test_x_typing(text: str = "LOCAL_X_TYPING_TEST") -> dict[str, Any]:
    """Open composer, enter text, verify it, and do not click Post."""
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
            if editor is None:
                return {"success": False, "stage": "editor_not_found", "message": "Visible X editor was not found.", "diagnostics": bx._diagnostics(page)}
            focused = _focus_editor(page, editor)
            typed = _type_into_editor(page, editor, text) if focused else False
            actual = bx._editor_text(editor)
            button = bx._find_post_button(page) if typed else None
            result = {"success": bool(typed), "stage": "typing_test_complete" if typed else "typing_failed", "message": "Editor found -> text entered -> text verified -> Post button inspected. Post was NOT clicked.", "editor_text": actual, "focused": focused, "post_button": None if not button else {"data_testid":button.get_attribute("data-testid"),"enabled":not button.is_disabled(timeout=800)}, "diagnostics": bx._diagnostics(page)}
            bx._set_task(stage=result["stage"], last_result=result)
            return result
    except Exception as e:
        result = {"success": False, "stage": "timeout" if isinstance(e, (TimeoutError, PlaywrightTimeoutError)) else "exception", "message": f"X typing test failed: {type(e).__name__}: {e}", "diagnostics": bx._diagnostics(page) if page else {}}
        bx._set_task(stage="failed", last_result=result)
        return result
    finally:
        bx._cleanup_task(started, browser, context, state_file)


def post_x(text: str, image_base64: str | None = None, image_filename: str = "image.png") -> dict[str, Any]:
    """Post text, optionally with one image, only after all inputs are verified."""
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
            browser, context, state_file, page = bx._launch_context(p, state)
            bx._open_compose(page, started)
            bx._check_deadline(started)
            if bx._login_state(page):
                return {"success": False, "stage": "login_required", "message": "X browser session has expired.", "diagnostics": bx._diagnostics(page)}
            if bx._onboarding_state(page):
                return {"success": False, "stage": "onboarding", "message": "X opened onboarding instead of the compose page.", "diagnostics": bx._diagnostics(page)}

            bx._set_task(stage="waiting_editor")
            editor = bx._wait_for_editor(page, started, 12000)
            if editor is None:
                return {"success": False, "stage": "editor_not_found", "message": "X composer did not render a visible editor. Post was NOT clicked.", "diagnostics": bx._diagnostics(page)}

            upload_result = None
            if image_base64:
                try:
                    upload_result = _upload_image(page, image_base64, image_filename)
                except Exception as exc:
                    result = {"success": False, "stage": "image_upload_failed", "message": f"Image upload failed: {type(exc).__name__}: {exc}. Post was NOT clicked.", "diagnostics": bx._diagnostics(page)}
                    bx._set_task(stage="failed", last_result=result)
                    return result
                if not upload_result.get("success"):
                    result = {"success": False, "stage": "image_upload_not_verified", "message": "Image was selected, but its presence in the X composer could not be verified. Post was NOT clicked.", "upload": upload_result, "diagnostics": bx._diagnostics(page)}
                    bx._set_task(stage="failed", last_result=result)
                    return result

            bx._set_task(stage="focusing_editor")
            if not _focus_editor(page, editor):
                result = {"success": False, "stage": "editor_focus_failed", "message": "Editor found but focus failed. Post was NOT clicked.", "upload": upload_result, "diagnostics": bx._diagnostics(page)}
                bx._set_task(stage="failed", last_result=result)
                return result

            bx._set_task(stage="typing")
            if not _type_into_editor(page, editor, text):
                result = {"success": False, "stage": "typing_failed", "message": "Editor found, but text was not verified inside it. Post was NOT clicked.", "editor_text": bx._editor_text(editor), "upload": upload_result, "diagnostics": bx._diagnostics(page)}
                bx._set_task(stage="failed", last_result=result)
                return result

            bx._set_task(stage="typing_verified")
            result = _post_after_verified_editor(page, editor, text, started, upload_result)
            bx._set_task(stage=result["stage"], last_result=result)
            return result

    except Exception as e:
        result = {"success": False, "stage": "timeout" if isinstance(e, (TimeoutError, PlaywrightTimeoutError)) else "exception", "message": f"X post failed: {type(e).__name__}: {e}", "diagnostics": bx._diagnostics(page) if page else {}}
        bx._set_task(stage="failed", last_result=result)
        return result
    finally:
        bx._cleanup_task(started, browser, context, state_file)
