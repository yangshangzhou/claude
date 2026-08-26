from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT = Path("x_state.json")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context(viewport={"width": 1400, "height": 900})
    page = context.new_page()
    page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded")

    print("\nA browser window is open.")
    print("Log in to your X account manually, including any verification steps.")
    input("After you are fully logged in and can see your X home page, press Enter here... ")

    context.storage_state(path=str(OUTPUT))
    print(f"Saved browser session to: {OUTPUT.resolve()}")
    print("IMPORTANT: x_state.json contains authentication cookies. Do not commit or share it.")
    browser.close()
