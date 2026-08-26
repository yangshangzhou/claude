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
    page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded")

    print("\n========================================")
    print("X login window is open.")
    print("Please log in manually.")
    print("Google login is supported; complete the Google window if needed.")
    print("========================================\n")

    input("After you are fully logged in and can see your X home page, press Enter here... ")

    # Verify that the session is actually logged in before saving it.
    page.goto("https://x.com/home", wait_until="domcontentloaded")
    time.sleep(3)
    print(f"Current URL: {page.url}")

    if "/home" not in page.url:
        raise RuntimeError(
            "X login was not completed. Please make sure you can see the X home page, then run the script again."
        )

    context.storage_state(path=str(OUTPUT))
    print(f"\nSUCCESS: Saved browser session to: {OUTPUT.resolve()}")
    print("IMPORTANT: x_state.json contains authentication cookies. Do not commit or share it.")

    browser.close()
