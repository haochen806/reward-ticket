import json
import logging
import time

from camoufox.sync_api import Camoufox

log = logging.getLogger(__name__)

DATA_URL = "https://www.alaskaair.com/search/results/__data.json"
SEARCH_URL = "https://www.alaskaair.com/search"


class BrowserSession:
    """Manages a persistent Camoufox browser session for scraping Alaska Airlines."""

    def __init__(self):
        self._camoufox = None
        self._browser = None
        self._page = None

    def start(self):
        log.info("Starting Camoufox browser session...")
        self._camoufox = Camoufox(headless=True)
        self._browser = self._camoufox.__enter__()
        self._page = self._browser.new_page()
        self._page.goto(SEARCH_URL, timeout=30000, wait_until="networkidle")
        time.sleep(2)
        log.info("Browser session established")

    def stop(self):
        if self._camoufox:
            try:
                self._camoufox.__exit__(None, None, None)
            except Exception:
                pass
            self._camoufox = None
            self._browser = None
            self._page = None
            log.info("Browser session closed")

    def search(self, origin: str, destination: str, date: str) -> str | None:
        """Fetch SvelteKit __data.json for a single date. Returns raw NDJSON text."""
        results = self.search_parallel(origin, destination, [date])
        return results.get(date)

    def search_parallel(
        self, origin: str, destination: str, dates: list[str], concurrency: int = 5
    ) -> dict[str, str]:
        """Fetch multiple dates with controlled parallelism via Promise.all.

        Splits dates into chunks of `concurrency * 5` per evaluate call to avoid
        browser event loop bottlenecks, then runs `concurrency` parallel fetches
        within each chunk.

        Args:
            origin: Airport code (e.g., "SEA")
            destination: Airport code (e.g., "NRT")
            dates: List of date strings (YYYY-MM-DD)
            concurrency: Max parallel fetches per batch (default 5). Use 0 for unlimited.

        Returns:
            Dict mapping date -> raw NDJSON response text
        """
        if not self._page:
            raise RuntimeError("Browser session not started. Call start() first.")

        all_results = {}
        chunk_size = max(concurrency * 5, 10) if concurrency > 0 else len(dates)

        for i in range(0, len(dates), chunk_size):
            chunk = dates[i:i + chunk_size]
            for attempt in range(3):
                try:
                    results = self._page.evaluate(
                        """async ([baseUrl, origin, dest, dates, concurrency]) => {
                            const out = {};
                            const makeUrl = (d) =>
                                `${baseUrl}?O=${origin}&D=${dest}&OD=${d}&A=1&RT=false&ShoppingMethod=onlineaward&locale=en-us`;

                            const fetchOne = async (d) => {
                                try {
                                    const r = await fetch(makeUrl(d), {credentials: "include"});
                                    if (r.ok) out[d] = await r.text();
                                } catch(e) {}
                            };

                            if (concurrency <= 0 || concurrency >= dates.length) {
                                await Promise.all(dates.map(fetchOne));
                            } else {
                                for (let i = 0; i < dates.length; i += concurrency) {
                                    const batch = dates.slice(i, i + concurrency);
                                    await Promise.all(batch.map(fetchOne));
                                }
                            }
                            return out;
                        }""",
                        [DATA_URL, origin, destination, chunk, concurrency],
                    )
                    all_results.update(results or {})
                    break
                except Exception as e:
                    log.error(f"Chunk fetch failed (attempt {attempt + 1}): {e}")
                    if attempt < 2:
                        time.sleep(2 ** attempt)
                        try:
                            self._page.goto(SEARCH_URL, timeout=30000, wait_until="domcontentloaded")
                            time.sleep(2)
                        except Exception:
                            self.stop()
                            self.start()

        if not all_results:
            log.error(f"All retries exhausted for {origin}->{destination}")
        return all_results
