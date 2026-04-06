"""One-time headed login flow. User solves CAPTCHA once, then never again.

Usage:
    python -m src.login

This opens a visible browser window. User logs in manually (with CAPTCHA).
Once logged in, cookies from ALL domains (alaskaair.com + auth0.alaskaair.com)
are saved. The headless monitor then uses these cookies + SessionKeepAlive
to stay authenticated indefinitely.
"""

import json
import logging
import sys
import time
from pathlib import Path

from camoufox.sync_api import Camoufox

from .auth import check_auth, COOKIES_PATH

log = logging.getLogger(__name__)


def login(cookies_path: str = COOKIES_PATH):
    """Open a headed browser, let user log in, save all cookies."""
    print("Opening browser for login...")
    print("Please log in to alaskaair.com and complete the CAPTCHA.")
    print("Once you see your account dashboard, press Enter here.\n")

    with Camoufox(headless=False) as browser:
        page = browser.new_page()
        page.goto("https://www.alaskaair.com/account/login", timeout=60000)

        # Wait for user to complete login
        while True:
            try:
                input(">>> Press Enter after you've logged in (or 'q' to quit): ")
            except EOFError:
                time.sleep(5)
                break

            if check_auth(page):
                print("Login confirmed!")
                break
            else:
                # Maybe they're still on the login page
                # Try navigating to check
                page.goto("https://www.alaskaair.com/", timeout=30000, wait_until="domcontentloaded")
                time.sleep(3)
                if check_auth(page):
                    print("Login confirmed!")
                    break
                print("Not logged in yet. Please complete the login and try again.")

        # Save ALL cookies from ALL domains
        all_cookies = page.context.cookies()
        save_data = []
        for c in all_cookies:
            save_data.append({
                "name": c["name"],
                "value": c["value"],
                "domain": c["domain"],
                "path": c["path"],
                "httpOnly": c.get("httpOnly", False),
                "secure": c.get("secure", False),
            })

        Path(cookies_path).parent.mkdir(parents=True, exist_ok=True)
        with open(cookies_path, "w") as f:
            json.dump(save_data, f, indent=2)

        print(f"\nSaved {len(save_data)} cookies to {cookies_path}")
        print("Domains:", sorted(set(c["domain"] for c in save_data)))
        print("\nYou can now run the monitor — it will stay authenticated via keep-alive.")
        print("You should only need to re-login if the server session fully expires (days/weeks).")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    path = sys.argv[1] if len(sys.argv) > 1 else COOKIES_PATH
    login(path)
