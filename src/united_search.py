"""United Airlines ANA award search via Chrome DevTools Protocol.

Instead of launching a new browser (which United detects), this connects
to your REAL Chrome browser via CDP — zero automation signals.

Usage:
  Step 1: Start Chrome with debugging enabled:
    /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222

  Step 2: In that Chrome, go to united.com and log in normally

  Step 3: Run this script:
    python -m src.united_search [HND] [SEA]
"""

import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    origin = sys.argv[1] if len(sys.argv) > 1 else "HND"
    dest = sys.argv[2] if len(sys.argv) > 2 else "SEA"
    port = int(sys.argv[3]) if len(sys.argv) > 3 else 9222

    print(f"United Award Search: {origin} -> {dest}")
    print("=" * 50)
    print(f"Connecting to Chrome on port {port}...")
    print("Make sure Chrome is running with: --remote-debugging-port=9222\n")

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(f"http://localhost:{port}")
        except Exception as e:
            print(f"Cannot connect to Chrome. Start it with:")
            print(f'  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port={port}')
            print(f"\nThen log into united.com and run this script again.")
            print(f"\nError: {e}")
            return

        # Use existing browser context (user's real session)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()

        api_calls = []
        def on_resp(response):
            url = response.url
            ct = response.headers.get("content-type", "")
            if "united.com" in url and "json" in ct:
                try:
                    body = response.text()
                    if len(body) > 2000:
                        api_calls.append({"url": url, "size": len(body), "body": body})
                except:
                    pass
        page.on("response", on_resp)

        # Navigate to award search — should work since user is logged in
        start_date = (date.today() + timedelta(days=30)).isoformat()
        print(f"Loading award search: {origin}->{dest} {start_date}...", flush=True)
        page.goto(
            f"https://www.united.com/en/us/fsr/choose-flights?f={origin}&t={dest}&d={start_date}&tt=1&at=1&sc=7&px=1&taxng=1",
            timeout=60000, wait_until="domcontentloaded",
        )
        time.sleep(15)

        print(f"Title: {page.title()}", flush=True)
        page.screenshot(path="/tmp/united_cdp.png")

        state = page.evaluate("""() => {
            const t = document.body.textContent;
            return {
                ANA: t.includes("ANA") || t.includes("All Nippon"),
                NH: /NH\\s?\\d/.test(t),
                nonstop: t.includes("Nonstop"),
                miles: t.includes("k miles") || t.includes(",000 miles"),
                signIn: t.includes("Email or MileagePlus"),
                depart: t.includes("Depart"),
            };
        }""")
        print(f"Results: {json.dumps(state)}", flush=True)

        if state.get("signIn"):
            print("\nSign-in modal appeared. Please log in to united.com in Chrome first.")
            return

        if not state.get("depart") and not state.get("miles"):
            print("\nNo results loaded. Check Chrome window.", flush=True)
            return

        # Scan multiple dates
        print(f"\n{'='*60}", flush=True)
        start = date.today() + timedelta(days=30)
        dates = [(start + timedelta(days=i)).isoformat() for i in range(30)]
        print(f"Scanning {len(dates)} dates: {dates[0]} to {dates[-1]}\n", flush=True)

        for dt in dates:
            api_calls.clear()
            try:
                page.goto(
                    f"https://www.united.com/en/us/fsr/choose-flights?f={origin}&t={dest}&d={dt}&tt=1&at=1&sc=7&px=1&taxng=1",
                    timeout=30000, wait_until="domcontentloaded",
                )
                time.sleep(8)
            except:
                print(f"  {dt}: timeout", flush=True)
                continue

            s = page.evaluate("""() => {
                const t = document.body.textContent;
                return {
                    ANA: t.includes("ANA") || t.includes("All Nippon"),
                    miles: t.includes("k miles"),
                    signIn: t.includes("Email or MileagePlus"),
                };
            }""")

            if s.get("signIn"):
                print(f"  {dt}: session expired!", flush=True)
                break

            # Check API for ANA flight details
            ana_in_api = any("NH" in a["body"] or "ANA" in a["body"] for a in api_calls)

            if s.get("ANA") or ana_in_api:
                print(f"  {dt}: ANA AVAILABLE (miles: {s.get('miles')})", flush=True)
            else:
                print(f"  {dt}: no ANA", flush=True)

        page.close()


if __name__ == "__main__":
    main()
