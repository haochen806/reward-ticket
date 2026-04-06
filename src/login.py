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


SITES = {
    "alaska": {
        "login_url": "https://www.alaskaair.com/account/login",
        "check_domain": "alaskaair.com",
        "cookies_file": "cookies.json",
    },
    "united": {
        "login_url": "https://www.united.com/",
        "check_domain": "united.com",
        "cookies_file": "cookies_united.json",
    },
}


def login(cookies_path: str = COOKIES_PATH, site: str = "alaska"):
    """Open a headed browser, let user log in, save all cookies."""
    site_info = SITES.get(site, SITES["alaska"])
    cookies_file = cookies_path if site == "alaska" else str(Path(cookies_path).parent / site_info["cookies_file"])

    print(f"Opening browser for {site} login...")
    print(f"Please log in at {site_info['login_url']}")
    print("Once you're logged in, press Enter here.\n")

    with Camoufox(headless=False) as browser:
        page = browser.new_page()
        page.goto(site_info["login_url"], timeout=60000)

        # Wait for user to complete login
        while True:
            try:
                input(">>> Press Enter after you've logged in (or 'q' to quit): ")
            except EOFError:
                time.sleep(5)
                break

            # Check auth based on site
            if site == "alaska":
                page.goto("https://www.alaskaair.com/", timeout=30000, wait_until="domcontentloaded")
                time.sleep(3)
                if check_auth(page):
                    print("Login confirmed!")
                    break
            elif site == "united":
                logged_in = page.evaluate('''() => {
                    const text = document.body.textContent;
                    return text.includes("MileagePlus") || text.includes("My trips") || !text.includes("Sign in");
                }''')
                if logged_in:
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

        Path(cookies_file).parent.mkdir(parents=True, exist_ok=True)
        with open(cookies_file, "w") as f:
            json.dump(save_data, f, indent=2)

        print(f"\nSaved {len(save_data)} cookies to {cookies_file}")
        print("Domains:", sorted(set(c["domain"] for c in save_data)))
        print("\nThe monitor will use these cookies to stay authenticated.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Usage: python -m src.login [alaska|united]
    site = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in SITES else "alaska"
    login(COOKIES_PATH, site=site)
