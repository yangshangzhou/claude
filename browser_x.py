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


def _find_visible_editor(page):
    """Find X's compose editor using several selectors because X changes its DOM frequently."""
    selectors = [
        '[data-testid="tweetTextarea_0"]',
        'div[contenteditable="true"][role="textbox"]',
        'div[contenteditable="true"]',
        '[role="textbox"][contenteditable="true"]',
    ]

    for selector in selectors:
        loc = page.locator(selector)
        count = loc.count()
        for i in range(min(count, 10)):
            candidate = loc.nth(i)
            try:
                if candidate.is_visible():
                    return candidate
            except Exception:
                pass
    return None


def _find_post_button(page):
    """Find the active Post button using X's current and fallback selectors."""
    selectors = [
        '[data-testid="tweetButtonInline"]',
        '[data-testid="tweetButton"]',
        'button[aria-label="Post"]',
    ]

    for selector in selectors:
        loc = page.locator(selector)
        count = loc.count()
        for i in range(min(count, 10)):
            candidate = loc.nth(i)
            try:
                if candidate.is_visible() and candidate.is_enabled():
                    return candidate
            except Exception:
                pass

    # Last fallback: an enabled button whose accessible name is exactly Post.
    try:
        loc = page.get_by_role("button", name="Post", exact=True)
        count = loc.count()
        for i in range(min(count, 10)):
            candidate = loc.nth(i)
            if candidate.is_visible() and candidate.is_enabled():
                return candidate
    except Exception:
        pass

    return None


def post_x(text: str) -> dict[str, Any]:
    state = _storage_state()
    if not state:
        return browser_status()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = None
        state_file = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", suffix=".json", delete=False, encoding="utf-8"
            ) as f:
                f.write(state)
                state_file = f.name

            context = browser.new_context(
                storage_state=state_file,
                viewport={"width": 1280, "height": 900},
                locale="en-US",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/151.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            page.set_default_timeout(15000)

            # X's React UI can occasionally fail to hydrate on /compose/post in an
            # automated browser. Start from Home, then open the composer explicitly.
            page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(5000)

            if "/i/flow/login" in page.url or "/login" in page.url:
                return {
                    "success": False,
                    "message": "X browser session has expired. Generate a new Playwright storage_state locally and update X_STORAGE_STATE on Render."
                }

            editor = _find_visible_editor(page)

            # If the home-page composer is not present, open the dedicated composer.
            if editor is None:
                try:
                    compose_link = page.locator('a[href="/compose/post"]').first
                    if compose_link.count() and compose_link.is_visible():
                        compose_link.click()
                    else:
                        compose_button = page.locator('[data-testid="SideNav_NewTweet_Button"]').first
                        if compose_button.count() and compose_button.is_visible():
                            compose_button.click()
                        else:
                            page.goto(
                                "https://x.com/compose/post",
                                wait_until="domcontentloaded",
                                timeout=30000,
                            )
                    page.wait_for_timeout(4000)
                except Exception:
                    page.wait_for_timeout(2000)

                editor = _find_visible_editor(page)

            if editor is None:
                # Return useful diagnostics instead of the generic selector timeout.
                body_text = ""
                try:
                    body_text = page.locator("body").inner_text(timeout=3000)[:1000]
                except Exception:
                    pass
                return {
                    "success": False,
                    "message": (
                        "X compose editor was not found after loading the authenticated web UI. "
                        f"url={page.url!r}; title={page.title()!r}; body={body_text!r}"
                    ),
                }

            editor.click()
            editor.fill(text)

            button = _find_post_button(page)
            if button is None:
                return {
                    "success": False,
                    "message": (
                        "X compose editor was found and text was entered, but the Post button "
                        f"was not found. url={page.url!r}"
                    ),
                }

            button.click()
            page.wait_for_timeout(5000)

            # X normally closes the compose dialog after a successful submission.
            if _find_visible_editor(page) is None:
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
                "message": f"X web UI timed out: {exc}; url={page.url if 'page' in locals() else 'unknown'}"
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
            if state_file:
                try:
                    os.unlink(state_file)
                except Exception:
                    pass
