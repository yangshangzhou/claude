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
    selectors = [
        '[data-testid="tweetTextarea_0"]',
        'div[contenteditable="true"][role="textbox"]',
        'textarea[aria-label*="Post"]',
        'div[contenteditable="true"]',
        '[role="textbox"][contenteditable="true"]',
    ]
    for selector in selectors:
        try:
            loc = page.locator(selector)
            for i in range(min(loc.count(), 10)):
                candidate = loc.nth(i)
                if candidate.is_visible():
                    return candidate
        except Exception:
            pass
    return None


def _find_post_button(page):
    selectors = [
        '[data-testid="tweetButtonInline"]',
        '[data-testid="tweetButton"]',
        'button[aria-label="Post"]',
    ]
    for selector in selectors:
        try:
            loc = page.locator(selector)
            for i in range(min(loc.count(), 10)):
                candidate = loc.nth(i)
                if candidate.is_visible() and candidate.is_enabled():
                    return candidate
        except Exception:
            pass
    try:
        loc = page.get_by_role("button", name="Post", exact=True)
        for i in range(min(loc.count(), 10)):
            candidate = loc.nth(i)
            if candidate.is_visible() and candidate.is_enabled():
                return candidate
    except Exception:
        pass
    return None


def _diagnostics(page) -> dict[str, Any]:
    body_text = ""
    try:
        body_text = page.locator("body").inner_text(timeout=1500)[:1500]
    except Exception:
        pass
    return {"url": page.url, "title": page.title(), "body": body_text}


def post_x(text: str) -> dict[str, Any]:
    state = _storage_state()
    if not state:
        return browser_status()

    with sync_playwright() as p:
        # Render/Linux: use the newer Chromium headless mode and the flags
        # commonly required for Chromium inside containers.
        browser = p.chromium.launch(
            headless=True,
            channel="chromium",
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = None
        state_file = None
        page = None
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
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/151.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            page.set_default_timeout(7000)

            # Try the compose route first. If X does not hydrate it, fall back
            # to Home and its compose control.
            try:
                page.goto(
                    "https://x.com/compose/post",
                    wait_until="commit",
                    timeout=12000,
                )
                page.wait_for_timeout(2500)
            except PlaywrightTimeoutError:
                return {
                    "success": False,
                    "message": "X compose navigation timed out.",
                    "diagnostics": _diagnostics(page),
                }

            if "/i/flow/login" in page.url or "/login" in page.url:
                return {
                    "success": False,
                    "message": "X browser session has expired. Generate a new Playwright storage_state locally and update X_STORAGE_STATE on Render.",
                    "diagnostics": _diagnostics(page),
                }

            editor = _find_visible_editor(page)

            if editor is None:
                try:
                    page.goto(
                        "https://x.com/home",
                        wait_until="commit",
                        timeout=12000,
                    )
                    page.wait_for_timeout(2500)
                except PlaywrightTimeoutError:
                    return {
                        "success": False,
                        "message": "X Home navigation timed out.",
                        "diagnostics": _diagnostics(page),
                    }
                editor = _find_visible_editor(page)

            if editor is None:
                for selector in (
                    'a[href="/compose/post"]',
                    '[data-testid="SideNav_NewTweet_Button"]',
                ):
                    try:
                        loc = page.locator(selector).first
                        if loc.count() and loc.is_visible():
                            loc.click()
                            page.wait_for_timeout(2000)
                            editor = _find_visible_editor(page)
                            if editor is not None:
                                break
                    except Exception:
                        pass

            if editor is None:
                return {
                    "success": False,
                    "message": "X compose editor was not rendered. The session is configured, but X web UI did not hydrate in this Render browser.",
                    "diagnostics": _diagnostics(page),
                }

            editor.click()
            editor.fill(text)

            button = _find_post_button(page)
            if button is None:
                return {
                    "success": False,
                    "message": "X editor was found, but the Post button was not rendered.",
                    "diagnostics": _diagnostics(page),
                }

            button.click()
            page.wait_for_timeout(3500)

            if _find_visible_editor(page) is None:
                return {
                    "success": True,
                    "message": "Post submitted through X web browser automation.",
                    "url": page.url,
                }

            return {
                "success": True,
                "message": "Post submission command completed through X web browser automation.",
                "url": page.url,
            }

        except PlaywrightTimeoutError as exc:
            return {
                "success": False,
                "message": f"X web UI timed out: {exc}",
                "diagnostics": _diagnostics(page) if page else {},
            }
        except Exception as exc:
            return {
                "success": False,
                "message": f"X browser automation failed: {type(exc).__name__}: {exc}",
                "diagnostics": _diagnostics(page) if page else {},
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
