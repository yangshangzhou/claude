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
        '[role="textbox"][contenteditable="true"]',
    ]

    # Prefer the composer inside the X modal/dialog when it exists.
    for scope in (page.locator('[role="dialog"]'), page.locator('body')):
        try:
            if not scope.is_visible():
                continue
        except Exception:
            pass

        for selector in selectors:
            try:
                loc = scope.locator(selector)
                for i in range(min(loc.count(), 10)):
                    candidate = loc.nth(i)
                    if candidate.is_visible():
                        return candidate
            except Exception:
                pass

    return None


def _find_post_button(page):
    selectors = [
        '[data-testid="tweetButton"]',
        '[data-testid="tweetButtonInline"]',
        'button[aria-label="Post"]',
        'button[aria-label="Tweet"]',
    ]

    for scope in (page.locator('[role="dialog"]'), page.locator('body')):
        for selector in selectors:
            try:
                loc = scope.locator(selector)
                for i in range(min(loc.count(), 10)):
                    candidate = loc.nth(i)
                    if candidate.is_visible() and candidate.is_enabled():
                        return candidate
            except Exception:
                pass

        try:
            loc = scope.get_by_role("button", name="Post", exact=True)
            for i in range(min(loc.count(), 10)):
                candidate = loc.nth(i)
                if candidate.is_visible() and candidate.is_enabled():
                    return candidate
        except Exception:
            pass

    return None


def _diagnostics(page) -> dict[str, Any]:
    body_text = ""
    test_ids: list[str] = []
    try:
        body_text = page.locator("body").inner_text(timeout=1500)[:2000]
    except Exception:
        pass
    try:
        test_ids = page.locator("[data-testid]").evaluate_all(
            "els => Array.from(new Set(els.map(e => e.getAttribute('data-testid')).filter(Boolean))).slice(0, 80)"
        )
    except Exception:
        pass
    return {
        "url": page.url,
        "title": page.title(),
        "body": body_text,
        "test_ids": test_ids,
    }


def post_x(text: str) -> dict[str, Any]:
    state = _storage_state()
    if not state:
        return browser_status()

    with sync_playwright() as p:
        browser = None
        context = None
        state_file = None
        page = None
        try:
            # Keep Chromium lightweight enough for Render Free (512 MB RAM).
            browser = p.chromium.launch(
                headless=True,
                channel="chromium",
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--disable-background-networking",
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-breakpad",
                    "--disable-component-update",
                    "--disable-default-apps",
                    "--disable-extensions",
                    "--disable-features=Translate,BackForwardCache",
                    "--disable-sync",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            )

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
            page.set_default_timeout(6000)

            # IMPORTANT: use /compose/tweet rather than /compose/post.
            # Current X automation reports show /compose/post/home can fail
            # to hydrate while /compose/tweet can still open the composer.
            page.goto(
                "https://x.com/compose/tweet",
                wait_until="commit",
                timeout=10000,
            )
            page.wait_for_timeout(3000)

            if "/i/flow/login" in page.url or "/login" in page.url:
                return {
                    "success": False,
                    "message": "X browser session has expired. Generate a new Playwright storage_state locally and update X_STORAGE_STATE on Render.",
                    "diagnostics": _diagnostics(page),
                }

            editor = _find_visible_editor(page)
            if editor is None:
                return {
                    "success": False,
                    "message": "X compose/tweet loaded, but the tweet editor was not rendered.",
                    "diagnostics": _diagnostics(page),
                }

            editor.click()

            # X's current composer can ignore programmatic fill(). Use real
            # keyboard input instead so the React editor receives input events.
            editor.press_sequentially(text, delay=8)
            page.wait_for_timeout(500)

            button = _find_post_button(page)
            if button is None:
                return {
                    "success": False,
                    "message": "X editor was found and text was typed, but the Post button was not enabled/rendered.",
                    "diagnostics": _diagnostics(page),
                }

            button.click()
            page.wait_for_timeout(3000)

            # Successful submission normally closes the compose modal.
            if _find_visible_editor(page) is None:
                return {
                    "success": True,
                    "message": "Post submitted through X web browser automation.",
                    "url": page.url,
                }

            # Do not claim success if the composer is still open.
            return {
                "success": False,
                "message": "X Post button was clicked, but the composer is still open; submission could not be verified.",
                "diagnostics": _diagnostics(page),
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
                try:
                    context.close()
                except Exception:
                    pass
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass
            if state_file:
                try:
                    os.unlink(state_file)
                except Exception:
                    pass
