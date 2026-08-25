import os
from playwright.sync_api import sync_playwright

STATE_FILE = "x_state.json"


def post_x(text: str):
    if not os.path.exists(STATE_FILE):
        return {
            "success": False,
            "message": "Missing x_state.json. Login once and save browser session first."
        }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=STATE_FILE)
        page = context.new_page()

        page.goto("https://x.com/compose/post", wait_until="networkidle")
        page.wait_for_timeout(3000)

        box = page.locator('[data-testid="tweetTextarea_0"]')
        box.fill(text)

        page.locator('[data-testid="tweetButton"]').click()
        page.wait_for_timeout(5000)

        browser.close()

    return {
        "success": True,
        "message": "Post submitted through browser automation"
    }
