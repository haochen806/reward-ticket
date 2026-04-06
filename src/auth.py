"""Cookie-based authentication for Alaska Airlines.

Flow:
1. User logs into alaskaair.com in their real browser
2. User runs the bookmarklet or browser console script to export cookies
3. Cookies saved to data/cookies.json
4. BrowserSession.load_cookies() injects them into Camoufox
"""

import json
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

COOKIES_PATH = "./data/cookies.json"

# Bookmarklet JS — user runs this in browser console after logging in
EXPORT_SCRIPT = """
// Run this in your browser console at alaskaair.com after logging in:
// It copies your session cookies to clipboard as JSON.

(function() {
    const cookies = document.cookie.split(';').map(c => {
        const [name, ...rest] = c.trim().split('=');
        return {
            name: name,
            value: rest.join('='),
            domain: '.alaskaair.com',
            path: '/',
        };
    });
    const json = JSON.stringify(cookies, null, 2);
    navigator.clipboard.writeText(json).then(() => {
        alert('Cookies copied to clipboard! Paste into data/cookies.json');
    }).catch(() => {
        // Fallback: show in prompt
        prompt('Copy this JSON and save to data/cookies.json:', json);
    });
})();
""".strip()


def save_cookies_from_json(raw_json: str, path: str = COOKIES_PATH):
    """Save cookie JSON string to file."""
    cookies = json.loads(raw_json)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(cookies, f, indent=2)
    log.info(f"Saved {len(cookies)} cookies to {path}")


def load_cookies(path: str = COOKIES_PATH) -> list[dict] | None:
    """Load cookies from JSON file."""
    p = Path(path)
    if not p.exists():
        log.warning(f"No cookies file at {path}")
        return None
    with open(p) as f:
        cookies = json.load(f)
    log.info(f"Loaded {len(cookies)} cookies from {path}")
    return cookies


def inject_cookies(page, cookies: list[dict]):
    """Inject cookies into a Playwright/Camoufox page context."""
    context = page.context
    formatted = []
    for c in cookies:
        cookie = {
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", ".alaskaair.com"),
            "path": c.get("path", "/"),
        }
        formatted.append(cookie)

    context.add_cookies(formatted)
    log.info(f"Injected {len(formatted)} cookies into browser")


def check_auth(page) -> bool:
    """Check if the browser session is authenticated."""
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
