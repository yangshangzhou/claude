from pathlib import Path
import shutil
import subprocess
import time
from playwright.sync_api import sync_playwright

OUTPUT = Path("x_state.json")
DEBUG_PORT = 9222
PROFILE_DIR = Path.home() / "x_playwright_chrome_profile"


def find_chrome():
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe",
    ]
    for path in candidates:
        if path.exists():
            return path
    found = shutil.which("chrome.exe")
    if found:
        return Path(found)
    raise FileNotFoundError("Cannot find Google Chrome. Please install Google Chrome first.")


def is_logged_in(page):
    """Detect an authenticated X session without relying on the current URL.

    X can keep the user on /i/jf/onboarding/web?mode=login even after a
    successful Google login. The reliable signal is the authenticated X UI
    and/or auth cookies, not simply whether the URL contains /home.
    """
    try:
        if page.locator('[data-testid="SideNav_AccountSwitcher_Button"]').count() > 0:
            return True
        if page.locator('[data-testid="AppTabBar_Home_Link"]').count() > 0:
            return True
        if page.locator('a[href="/home"]').count() > 0:
            return True
    except Exception:
        pass

    try:
        cookies = page.context.cookies(["https://x.com"])
        cookie_names = {c["name"] for c in cookies}
        # auth_token is the main X web authentication cookie.
        if "auth_token" in cookie_names:
            return True
    except Exception:
        pass

    return False


chrome = find_chrome()
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

print(f"Using normal Google Chrome: {chrome}")
print(f"Chrome profile: {PROFILE_DIR}")
print("Starting Chrome with remote debugging...")

subprocess.Popen([
    str(chrome),
    f"--remote-debugging-port={DEBUG_PORT}",
    f"--user-data-dir={PROFILE_DIR}",
    "--no-first-run",
    "--no-default-browser-check",
    "https://x.com/i/flow/login",
])

time.sleep(3)

with sync_playwright() as p:
    print("Connecting to the normal Chrome window...")
    browser = None
    for _ in range(20):
        try:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{DEBUG_PORT}")
            break
        except Exception:
            time.sleep(1)

    if browser is None:
        raise RuntimeError("Could not connect to Chrome on port 9222.")

    context = browser.contexts[0]
    page = context.pages[0] if context.pages else context.new_page()

    print("\n========================================")
    print("X login window is open.")
    print("Please log in manually.")
    print("Google login is supported; complete the Google window if needed.")
    print("========================================\n")

    input("After you are fully logged in and can see your X home page, press Enter here... ")

    # Do NOT force navigation to /home here. X may legitimately remain on
    # /i/jf/onboarding/web?mode=login after Google authentication.
    time.sleep(2)
    print(f"Current URL: {page.url}")

    # Give X a few seconds to finish its SPA transitions / cookie writes.
    logged_in = False
    for _ in range(10):
        if is_logged_in(page):
            logged_in = True
            break
        time.sleep(1)

    if not logged_in:
        print("Could not positively detect the authenticated X UI/cookie.")
        print("If you can see the X home timeline in the browser, press Enter again after it settles.")
        input("Press Enter to retry detection... ")
        logged_in = is_logged_in(page)

    if not logged_in:
        raise RuntimeError(
            f"X login could not be verified. Current URL: {page.url}. "
            "Make sure the browser is showing the authenticated X home page."
        )

    context.storage_state(path=str(OUTPUT))
    print(f"\nSUCCESS: Saved browser session to: {OUTPUT.resolve()}")
    print("IMPORTANT: x_state.json contains authentication cookies. Do not commit or share it.")

    browser.close()
