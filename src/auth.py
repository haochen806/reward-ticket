"""Cookie-based authentication for Alaska Airlines.

The Auth0 JWT expires every 30 minutes, but server-side session cookies
(ASSession, ASSessionSSL) persist longer. The browser's Auth0 SDK silently
refreshes the JWT. We replicate this by:

1. User exports cookies (including httpOnly) from Chrome DevTools
2. Cookies injected into Camoufox on startup
3. A background thread periodically visits alaskaair.com to trigger
   Auth0's silent token refresh, keeping the session alive
4. Refreshed cookies are saved back to the file for persistence
"""

import json
import logging
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

COOKIES_PATH = "./data/cookies.json"

EXPORT_SCRIPT = """
// Run in Chrome Console at alaskaair.com after logging in.
// Then go to DevTools > Application > Cookies > alaskaair.com
// Right-click > Copy all rows, and save as JSON to data/cookies.json
""".strip()


def load_cookies(path: str = COOKIES_PATH) -> list[dict] | None:
    p = Path(path)
    if not p.exists():
        log.warning(f"No cookies file at {path}")
        return None
    with open(p) as f:
        cookies = json.load(f)
    log.info(f"Loaded {len(cookies)} cookies from {path}")
    return cookies


def save_cookies(cookies: list[dict], path: str = COOKIES_PATH):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(cookies, f, indent=2)
    log.debug(f"Saved {len(cookies)} cookies to {path}")


def inject_cookies(page, cookies: list[dict]):
    context = page.context
    formatted = []
    for c in cookies:
        cookie = {
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", ".alaskaair.com"),
            "path": c.get("path", "/"),
        }
        if c.get("httpOnly"):
            cookie["httpOnly"] = True
        if c.get("secure"):
            cookie["secure"] = True
        formatted.append(cookie)
    context.add_cookies(formatted)
    log.info(f"Injected {len(formatted)} cookies into browser")


def check_auth(page) -> bool:
    try:
        result = page.evaluate("""async () => {
            try {
                const r = await fetch('/services/v1/myaccount/getloginstatus', {credentials: 'include'});
                const data = await r.json();
                return data.IsLoggedIn === true;
            } catch(e) {
                return false;
            }
        }""")
        return result
    except Exception:
        return False


class SessionKeepAlive:
    """Background thread that periodically refreshes the browser session
    to keep Auth0 tokens alive, mimicking what Chrome does automatically."""

    def __init__(self, page, cookies_path: str = COOKIES_PATH, interval: int = 1200):
        self._page = page
        self._cookies_path = cookies_path
        self._interval = interval  # default 20 min
        self._thread = None
        self._running = False

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info(f"Session keep-alive started (every {self._interval}s)")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            time.sleep(self._interval)
            if not self._running:
                break
            try:
                self._refresh()
            except Exception as e:
                log.error(f"Session refresh failed: {e}")

    def _refresh(self):
        """Visit homepage to trigger Auth0 silent refresh, then save updated cookies."""
        log.info("Refreshing session...")

        # Navigate to homepage — triggers Auth0 iframe refresh
        self._page.evaluate("""async () => {
            await fetch('/', {credentials: 'include'});
            await fetch('/services/v1/myaccount/getloginstatus', {credentials: 'include'});
        }""")

        # Save refreshed cookies
        cookies = self._page.context.cookies()
        alaska_cookies = [
            {
                "name": c["name"],
                "value": c["value"],
                "domain": c["domain"],
                "path": c["path"],
                "httpOnly": c.get("httpOnly", False),
                "secure": c.get("secure", False),
            }
            for c in cookies
            if "alaskaair.com" in c.get("domain", "")
        ]
        if alaska_cookies:
            save_cookies(alaska_cookies, self._cookies_path)
            log.info(f"Session refreshed, saved {len(alaska_cookies)} cookies")

        # Verify still authenticated
        if check_auth(self._page):
            log.info("Session still authenticated")
        else:
            log.warning("Session may have expired — re-export cookies needed")
