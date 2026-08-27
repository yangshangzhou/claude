"""Browser-based X read capabilities.

This module intentionally uses the existing Playwright X session instead of the
X API. It is for local capability testing and does not require X API credits.
"""

import re
import time
from typing import Any
from urllib.parse import quote

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


def _search_diagnostics(page) -> dict[str, Any]:
    out: dict[str, Any] = {
        "url": page.url if page else "",
        "title": "",
        "article_count": 0,
        "tweet_testid_count": 0,
        "status_link_count": 0,
        "body_text": "",
        "test_ids": [],
    }
    if not page:
        return out
    try:
        out["title"] = page.title()
    except Exception:
        pass
    try:
        out["article_count"] = page.locator("article").count()
    except Exception:
        pass
    try:
        out["tweet_testid_count"] = page.locator('[data-testid="tweet"]').count()
    except Exception:
        pass
    try:
        out["status_link_count"] = page.locator('a[href*="/status/"]').count()
    except Exception:
        pass
    try:
        out["body_text"] = _visible_text(page)[:5000]
    except Exception:
        pass
    try:
        out["test_ids"] = page.locator('[data-testid]').evaluate_all(
            "els => Array.from(new Set(els.map(e => e.getAttribute('data-testid')).filter(Boolean))).slice(0, 100)"
        )
    except Exception:
        pass
    return out


def _extract_posts(page, max_results: int) -> list[dict[str, Any]]:
    """Extract visible posts using several DOM strategies used by X."""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    selectors = ['article', '[data-testid="tweet"]']
    for selector in selectors:
        cards = page.locator(selector)
        try:
            count = cards.count()
        except Exception:
            continue
        for i in range(min(count, max_results * 5)):
            try:
                card = cards.nth(i)
                if not card.is_visible(timeout=500):
                    continue
                text = (card.inner_text(timeout=1500) or "").strip()
                if not text:
                    continue
                links = card.locator('a[href*="/status/"]')
                href = ""
                if links.count():
                    href = links.first.get_attribute("href") or ""
                if not href:
                    try:
                        matches = re.findall(r'href=["\']([^"\']*/status/[^"\']+)["\']', card.inner_html())
                        if matches:
                            href = matches[0]
                    except Exception:
                        pass
                if not href:
                    continue
                url = "https://x.com" + href if href.startswith("/") else href
                if url in seen:
                    continue
                seen.add(url)
                items.append({"url": url, "text": text[:3000]})
                if len(items) >= max_results:
                    return items
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
            mode = "live" if live else "top"
            url = f"https://x.com/search?q={quote(query)}&src=typed_query&f={mode}"
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            bx._wait_for_app(page, started, 12000)
            if _login_required(page):
                return {"success": False, "stage": "login_required", "message": "X browser session has expired.", "url": page.url}
            bx._set_task(stage="waiting_search_results")
            deadline = time.time() + 8
            posts: list[dict[str, Any]] = []
            while time.time() < deadline:
                bx._check_deadline(started)
                posts = _extract_posts(page, max_results)
                if posts:
                    break
                page.wait_for_timeout(800)
            if not posts:
                try:
                    page.mouse.wheel(0, 900)
                    page.wait_for_timeout(1500)
                    posts = _extract_posts(page, max_results)
                except Exception:
                    pass
            diagnostics = _search_diagnostics(page)
            result = {
                "success": bool(posts),
                "stage": "search_complete" if posts else "search_no_posts_extracted",
                "query": query,
                "mode": mode,
                "count": len(posts),
                "posts": posts,
                "source": "X web UI via Playwright",
                "url": page.url,
                "diagnostics": diagnostics,
            }
            if not posts:
                result["message"] = "X search page loaded, but no post cards could be extracted. See diagnostics for the current DOM/page text."
            bx._set_task(stage=result["stage"], last_result=result)
            return result
    except Exception as exc:
        result = {"success": False, "stage": "timeout" if isinstance(exc, (TimeoutError, PlaywrightTimeoutError)) else "exception", "message": f"X browser search failed: {type(exc).__name__}: {exc}", "url": page.url if page else ""}
        bx._set_task(stage="failed", last_result=result)
        return result
    finally:
        bx._cleanup_task(started, browser, context, state_file)


def _read_explore_content(page, max_results: int) -> list[str]:
    text = _visible_text(page)
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines()]
    lines = [x for x in lines if x]
    candidates = []
    for line in lines:
        if 2 <= len(line) <= 120 and line not in candidates:
            candidates.append(line)
        if len(candidates) >= max_results:
            break
    return candidates


def get_x_trends(max_results: int = 20) -> dict[str, Any]:
    """Read browser-visible X Explore content, with a browser-navigation fallback."""
    max_results = max(1, min(int(max_results), 50))
    state, error = _require_session()
    if error:
        return error

    started = time.time()
    browser = context = state_file = page = None
    navigation_error = None
    try:
        with sync_playwright() as p:
            browser, context, state_file, page = _launch(p, state)
            bx._set_task(busy=True, stage="opening_explore", started_at=started, text="", last_result=None)

            try:
                page.goto("https://x.com/explore", wait_until="domcontentloaded", timeout=20000)
                bx._wait_for_app(page, started, 12000)
            except Exception as exc:
                navigation_error = f"{type(exc).__name__}: {exc}"
                # Direct /explore can intermittently fail at the transport layer.
                # Retry through /home, which is already proven to work, then
                # click X's own Explore navigation item.
                page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=20000)
                bx._wait_for_app(page, started, 12000)
                if _login_required(page):
                    return {"success": False, "stage": "login_required", "message": "X browser session has expired.", "url": page.url}
                explore = page.locator('a[data-testid="AppTabBar_Explore_Link"]')
                if explore.count() and explore.first.is_visible(timeout=2000):
                    explore.first.click(timeout=5000)
                    page.wait_for_timeout(3000)
                else:
                    raise RuntimeError("X Explore navigation link was not available after /home fallback")

            if _login_required(page):
                return {"success": False, "stage": "login_required", "message": "X browser session has expired.", "url": page.url}

            page.wait_for_timeout(2000)
            candidates = _read_explore_content(page, max_results)
            result = {
                "success": bool(candidates),
                "stage": "trends_page_read" if candidates else "trends_no_content",
                "count": len(candidates),
                "visible_lines": candidates,
                "source": "X web UI via Playwright",
                "url": page.url,
                "navigation_fallback": bool(navigation_error),
                "navigation_error": navigation_error,
                "warning": "Browser-visible Explore content is evidence from the current session, not a guaranteed complete platform-wide trends API response.",
            }
            if not candidates:
                result["message"] = "X Explore opened, but no visible trend/content lines were extracted."
            bx._set_task(stage=result["stage"], last_result=result)
            return result
    except Exception as exc:
        result = {"success": False, "stage": "timeout" if isinstance(exc, (TimeoutError, PlaywrightTimeoutError)) else "exception", "message": f"X browser trends read failed: {type(exc).__name__}: {exc}", "url": page.url if page else "", "navigation_error": navigation_error}
        bx._set_task(stage="failed", last_result=result)
        return result
    finally:
        bx._cleanup_task(started, browser, context, state_file)