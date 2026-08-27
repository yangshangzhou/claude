"""Browser-based X read capabilities.

This module intentionally uses the existing Playwright X session instead of the
X API. It is for local capability testing and does not require X API credits.
"""

import re
import time
from typing import Any

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

import browser_x as bx

HARD_TIMEOUT = 45


def _visible_text(page) -> str:
    try:
        return (page.locator("body").inner_text(timeout=1500) or "").strip()
    except Exception:
        return ""


def _require_session():
    state = bx._storage_state()
    if not state:
        return None, {"success": False, "stage": "configuration", "message": "No X browser session configured. Run login_x.py first."}
    return state, None


def _login_required(page) -> bool:
    url = page.url.lower()
    text = _visible_text(page).lower()
    return "/login" in url or "/i/flow/login" in url or "sign in to x" in text or "log in to x" in text


def _launch(p, state):
    browser, context, state_file, page = bx._launch_context(p, state)
    page.set_default_timeout(5000)
    return browser, context, state_file, page


def _extract_posts(page, max_results: int) -> list[dict[str, Any]]:
    """Extract visible post cards from the search timeline.

    X changes DOM details frequently, so this intentionally relies on the
    stable article/role structure and returns evidence fields rather than
    pretending to expose API-complete post objects.
    """
    items = []
    articles = page.locator('article')
    count = min(articles.count(), max_results * 3)
    seen = set()
    for i in range(count):
        try:
            article = articles.nth(i)
            if not article.is_visible(timeout=500):
                continue
            text = (article.inner_text(timeout=1000) or "").strip()
            if not text:
                continue
            links = article.locator('a[href*="/status/"]')
            href = ""
            if links.count():
                href = links.first.get_attribute("href") or ""
            if not href:
                continue
            url = "https://x.com" + href if href.startswith("/") else href
            if url in seen:
                continue
            seen.add(url)
            items.append({"url": url, "text": text[:3000]})
            if len(items) >= max_results:
                break
        except Exception:
            continue
    return items


def search_x_posts(query: str, max_results: int = 10, live: bool = True) -> dict[str, Any]:
    """Search public X posts through the logged-in browser session."""
    query = query.strip()
    if not query:
        return {"success": False, "stage": "validation", "message": "query cannot be empty"}
    max_results = max(1, min(int(max_results), 50))
    state, error = _require_session()
    if error:
        return error

    started = time.time()
    browser = context = state_file = page = None
    try:
        with sync_playwright() as p:
            browser, context, state_file, page = _launch(p, state)
            bx._set_task(busy=True, stage="opening_search", started_at=started, text=query, last_result=None)
            from urllib.parse import quote
            mode = "live" if live else "top"
            url = f"https://x.com/search?q={quote(query)}&src=typed_query&f={mode}"
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            bx._wait_for_app(page, started, 12000)
            if _login_required(page):
                return {"success": False, "stage": "login_required", "message": "X browser session has expired.", "url": page.url}
            page.wait_for_timeout(2500)
            posts = _extract_posts(page, max_results)
            result = {
                "success": True,
                "stage": "search_complete",
                "query": query,
                "mode": mode,
                "count": len(posts),
                "posts": posts,
                "source": "X web UI via Playwright",
                "url": page.url,
            }
            bx._set_task(stage="search_complete", last_result=result)
            return result
    except Exception as exc:
        result = {"success": False, "stage": "timeout" if isinstance(exc, (TimeoutError, PlaywrightTimeoutError)) else "exception", "message": f"X browser search failed: {type(exc).__name__}: {exc}", "url": page.url if page else ""}
        bx._set_task(stage="failed", last_result=result)
        return result
    finally:
        bx._cleanup_task(started, browser, context, state_file)


def get_x_trends(max_results: int = 20) -> dict[str, Any]:
    """Read visible X Explore trends through the logged-in browser session.

    This is browser/UI evidence only. It does not claim that the returned list
    is the complete platform-wide trend ranking.
    """
    max_results = max(1, min(int(max_results), 50))
    state, error = _require_session()
    if error:
        return error

    started = time.time()
    browser = context = state_file = page = None
    try:
        with sync_playwright() as p:
            browser, context, state_file, page = _launch(p, state)
            bx._set_task(busy=True, stage="opening_explore", started_at=started, text="", last_result=None)
            page.goto("https://x.com/explore", wait_until="domcontentloaded", timeout=20000)
            bx._wait_for_app(page, started, 12000)
            if _login_required(page):
                return {"success": False, "stage": "login_required", "message": "X browser session has expired.", "url": page.url}
            page.wait_for_timeout(2500)
            text = _visible_text(page)
            lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines()]
            lines = [x for x in lines if x]
            # Keep candidate trend labels conservatively. We return raw visible
            # lines as evidence rather than assigning an invented popularity score.
            candidates = []
            for line in lines:
                if 2 <= len(line) <= 120 and line not in candidates:
                    candidates.append(line)
                if len(candidates) >= max_results:
                    break
            result = {
                "success": True,
                "stage": "trends_page_read",
                "count": len(candidates),
                "visible_lines": candidates,
                "source": "X web UI via Playwright",
                "url": page.url,
                "warning": "Browser-visible Explore content is evidence from the current session, not a guaranteed complete platform-wide trends API response.",
            }
            bx._set_task(stage="trends_page_read", last_result=result)
            return result
    except Exception as exc:
        result = {"success": False, "stage": "timeout" if isinstance(exc, (TimeoutError, PlaywrightTimeoutError)) else "exception", "message": f"X browser trends read failed: {type(exc).__name__}: {exc}", "url": page.url if page else ""}
        bx._set_task(stage="failed", last_result=result)
        return result
    finally:
        bx._cleanup_task(started, browser, context, state_file)
