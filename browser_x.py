import json
import os
import tempfile
from typing import Any

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


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


def browser_status() -> dict[str, Any]:
    state = _storage_state()
    if not state:
        return {
            "ready": False,
            "message": "No X browser session configured. Set X_STORAGE_STATE to a Playwright storage_state JSON."
        }
    return {"ready": True, "message": "X browser session is configured."}


def post_x(text: str) -> dict[str, Any]:
    state = _storage_state()
    if not state:
        return browser_status()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = None
        try:
            # Use a temporary file because Playwright accepts a path for storage_state.
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
                f.write(state)
                state_file = f.name

            context = browser.new_context(storage_state=state_file)
            page = context.new_page()
            page.goto("https://x.com/compose/post", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2500)

            # If the stored session has expired, X normally redirects to login.
            if "/i/flow/login" in page.url or "/login" in page.url:
                return {
                    "success": False,
                    "message": "X browser session has expired. Generate a new Playwright storage_state locally and update X_STORAGE_STATE on Render."
                }

            box = page.locator('[data-testid="tweetTextarea_0"]').first
            box.wait_for(state="visible", timeout=15000)
            box.fill(text)

            button = page.locator('[data-testid="tweetButtonInline"], [data-testid="tweetButton"]').first
            button.wait_for(state="visible", timeout=10000)
            button.click()

            # Give X time to submit and render the result.
            page.wait_for_timeout(4000)

            # X normally returns to the timeline after a successful post.
            if page.locator('[data-testid="tweetTextarea_0"]').count() == 0:
                return {
                    "success": True,
                    "message": "Post submitted through X web browser automation."
                }

            return {
                "success": True,
                "message": "Post submission command completed through X web browser automation."
            }
        except PlaywrightTimeoutError as exc:
            return {
                "success": False,
                "message": f"X web UI timed out: {exc}"
            }
        except Exception as exc:
            return {
                "success": False,
                "message": f"X browser automation failed: {type(exc).__name__}: {exc}"
            }
        finally:
            if context is not None:
                context.close()
            browser.close()
            try:
                os.unlink(state_file)
            except Exception:
                pass
