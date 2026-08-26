"""Deterministic X composer typing layer.

The existing browser_x.py had a subtle Playwright bug: it passed a Locator to
page.evaluate("el => el.focus()", editor). A Locator is not a DOM element, so
focus could fail before any keyboard input happened. This module keeps the
existing browser/session code and replaces only the focus/type/post sequence.
"""

import time
from typing import Any

import browser_x as bx
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


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
        # Use real keyboard events on the contenteditable editor.
        editor.press_sequentially(text, delay=25, timeout=8000)
    except Exception:
        try:
            page.keyboard.type(text, delay=25)
        except Exception:
            return False
    page.wait_for_timeout(800)
    actual = bx._editor_text(editor)
    return bool(actual) and text.strip() in actual


def test_x_typing(text: str = "LOCAL_X_TYPING_TEST") -> dict[str, Any]:
    """Open composer, enter text, verify it, and deliberately do NOT click Post."""
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
            if bx._onboarding_state(page):
                return {"success": False, "stage": "onboarding", "message": "X opened onboarding instead of compose.", "diagnostics": bx._diagnostics(page)}

            bx._set_task(stage="typing_test_finding_editor")
            editor = bx._wait_for_editor(page, started, 12000)
            if editor is None:
                return {"success": False, "stage": "editor_not_found", "message": "Visible X editor was not found.", "diagnostics": bx._diagnostics(page)}

            editor_info = {
                "data_testid": editor.get_attribute("data-testid"),
                "role": editor.get_attribute("role"),
                "contenteditable": editor.get_attribute("contenteditable"),
            }

            bx._set_task(stage="typing_test_focusing_editor")
            focused = _focus_editor(page, editor)
            if not focused:
                return {
                    "success": False,
                    "stage": "editor_focus_failed",
                    "message": "Editor was located but could not be focused. Post was NOT clicked.",
                    "editor": editor_info,
                    "diagnostics": bx._diagnostics(page),
                }

            bx._set_task(stage="typing_test_typing")
            typed = _type_into_editor(page, editor, text)
            actual = bx._editor_text(editor)

            # Only inspect the Post button after text has been verified.
            bx._set_task(stage="typing_test_checking_post_button")
            button = bx._find_post_button(page) if typed else None
            button_info = None
            if button:
                button_info = {
                    "data_testid": button.get_attribute("data-testid"),
                    "aria_label": button.get_attribute("aria-label"),
                    "enabled": not button.is_disabled(timeout=800),
                }

            result = {
                "success": bool(typed),
                "stage": "typing_test_complete" if typed else "typing_failed",
                "message": "Editor found -> text entered -> text verified -> Post button inspected. Post was NOT clicked.",
                "editor_text": actual,
                "focused": focused,
                "editor": editor_info,
                "post_button": button_info,
                "post_button_ready": bool(button),
                "diagnostics": bx._diagnostics(page),
            }
            bx._set_task(stage=result["stage"], last_result=result)
            return result

    except Exception as e:
        result = {
            "success": False,
            "stage": "timeout" if isinstance(e, (TimeoutError, PlaywrightTimeoutError)) else "exception",
            "message": f"X typing test failed: {type(e).__name__}: {e}",
            "diagnostics": bx._diagnostics(page) if page else {},
        }
        bx._set_task(stage="failed", last_result=result)
        return result
    finally:
        bx._cleanup_task(started, browser, context, state_file)


def post_x(text: str) -> dict[str, Any]:
    """Post only after editor text is positively verified."""
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
                return {"success": False, "stage": "onboarding", "message": "X opened an onboarding flow instead of the compose page.", "diagnostics": bx._diagnostics(page)}

            bx._set_task(stage="waiting_editor")
            editor = bx._wait_for_editor(page, started, 12000)
            if editor is None:
                return {"success": False, "stage": "editor_not_found", "message": "X composer did not render a visible editor. Post was NOT clicked.", "diagnostics": bx._diagnostics(page)}

            bx._set_task(stage="focusing_editor")
            if not _focus_editor(page, editor):
                result = {"success": False, "stage": "editor_focus_failed", "message": "Editor found but focus failed. No text was typed and Post was NOT clicked.", "diagnostics": bx._diagnostics(page)}
                bx._set_task(stage="failed", last_result=result)
                return result

            bx._set_task(stage="typing")
            if not _type_into_editor(page, editor, text):
                result = {
                    "success": False,
                    "stage": "typing_failed",
                    "message": "Editor found, but text was not verified inside it. Post was NOT clicked.",
                    "editor_text": bx._editor_text(editor),
                    "diagnostics": bx._diagnostics(page),
                }
                bx._set_task(stage="failed", last_result=result)
                return result

            # This is the hard gate: text MUST be present before button lookup/click.
            editor_text_before = bx._editor_text(editor)
            bx._set_task(stage="typing_verified")

            button = None
            deadline = time.time() + 8
            while time.time() < deadline:
                bx._check_deadline(started)
                button = bx._find_post_button(page)
                if button:
                    break
                page.wait_for_timeout(300)

            if button is None:
                result = {
                    "success": False,
                    "stage": "post_button_not_found",
                    "message": "Text is verified, but the Post button is not found/enabled. Post was NOT clicked.",
                    "editor_text": editor_text_before,
                    "diagnostics": bx._diagnostics(page),
                }
                bx._set_task(stage="failed", last_result=result)
                return result

            button_info = {
                "data_testid": button.get_attribute("data-testid"),
                "aria_label": button.get_attribute("aria-label"),
                "enabled": not button.is_disabled(timeout=800),
            }
            bx._set_task(stage="post_button_ready")

            # Final safety gate: re-read editor immediately before clicking.
            final_editor_text = bx._editor_text(editor)
            if text.strip() not in final_editor_text:
                result = {
                    "success": False,
                    "stage": "final_text_verification_failed",
                    "message": "Editor text disappeared/changed before click. Post was NOT clicked.",
                    "editor_text": final_editor_text,
                    "post_button": button_info,
                    "diagnostics": bx._diagnostics(page),
                }
                bx._set_task(stage="failed", last_result=result)
                return result

            bx._set_task(stage="clicking_post")
            button.scroll_into_view_if_needed(timeout=1500)
            button.click(timeout=2500)

            bx._set_task(stage="verifying_post")
            page.wait_for_timeout(1200)
            text_after = bx._editor_text(editor)
            alert = ""
            try:
                alert = (page.locator('[role="alert"]').first.text_content(timeout=800) or "").strip()
            except Exception:
                pass

            success = not text_after
            result = {
                "success": success,
                "stage": "post_complete" if success else "verification_failed",
                "message": "X post submitted successfully." if success else "Post was clicked but the editor still contains text.",
                "verification": {
                    "editor_text_before": editor_text_before[:500],
                    "editor_text_after": text_after[:500],
                    "alert": alert[:500],
                },
                "post_button": button_info,
                "diagnostics": bx._diagnostics(page),
            }
            bx._set_task(stage=result["stage"], last_result=result)
            return result

    except Exception as e:
        result = {
            "success": False,
            "stage": "timeout" if isinstance(e, (TimeoutError, PlaywrightTimeoutError)) else "exception",
            "message": f"X post failed: {type(e).__name__}: {e}",
            "diagnostics": bx._diagnostics(page) if page else {},
        }
        bx._set_task(stage="failed", last_result=result)
        return result
    finally:
        bx._cleanup_task(started, browser, context, state_file)
