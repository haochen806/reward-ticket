import logging
import signal
import sys
import time

from .config import load_config
from .db import Database
from .scraper import BrowserSession
from .parser import parse_sveltekit
from .alerter import TelegramAlerter
from .booker import Booker

log = logging.getLogger("reward-ticket")

TICK_INTERVAL = 60  # Wake up every 60s to check for stale dates
STALE_SECONDS = 300  # Re-check a date if not checked in 5 minutes
CONCURRENCY = 10  # Parallel fetches per batch


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    setup_logging()

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    log.info(f"Loading config from {config_path}")

    try:
        config = load_config(config_path)
    except (FileNotFoundError, ValueError) as e:
        log.error(f"Config error: {e}")
        sys.exit(1)

    db = Database(config.database.path)
    # Load email config if present
    raw_cfg = {}
    try:
        import yaml
        with open(config_path) as f:
            raw_cfg = yaml.safe_load(f) or {}
    except:
        pass
    email_config = raw_cfg.get("email")

    alerter = TelegramAlerter(config.telegram.bot_token, config.telegram.chat_id, email_config=email_config)
    browser = BrowserSession()

    # Wire up booker for auto-booking via Telegram
    booker = Booker(browser, alerter, db)
    alerter.set_booker(booker)

    # Start Telegram long-polling in daemon thread
    alerter.start_polling(db)

    # Start Camoufox browser session
    try:
        browser.start()
    except Exception as e:
        log.error(f"Failed to start browser: {e}")
        sys.exit(1)

    # Seed the scan queue for all configured routes
    for route in config.routes:
        route_key = f"{route.origin}-{route.destination}"
        dates = route.date_range()
        db.seed_queue(route_key, dates)
        log.info(f"Queue seeded: {route_key} ({len(dates)} dates)")

    # Graceful shutdown
    running = True

    def handle_signal(sig, frame):
        nonlocal running
        log.info("Shutdown signal received, stopping...")
        running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    consecutive_empty = 0
    log.info(f"Monitor running: tick every {TICK_INTERVAL}s, stale threshold {STALE_SECONDS}s, concurrency {CONCURRENCY}")

    while running:
        cycle_found_any = False
        total_checked = 0

        for route in config.routes:
            if not running:
                break

            route_key = f"{route.origin}-{route.destination}"
            stale_dates = db.get_stale_dates(route_key, stale_seconds=STALE_SECONDS)

            if not stale_dates:
                continue

            log.info(f"Checking {route_key} {route.cabin}: {len(stale_dates)} stale dates")

            try:
                t0 = time.time()
                batch_results = browser.search_parallel(
                    route.origin, route.destination, stale_dates, concurrency=CONCURRENCY
                )
                elapsed = time.time() - t0

                checked_dates = list(batch_results.keys())
                db.mark_checked(route_key, checked_dates)
                total_checked += len(checked_dates)

                log.info(f"Fetched {len(checked_dates)} dates in {elapsed:.1f}s ({elapsed/max(len(checked_dates),1):.2f}s/date)")

                for flight_date, raw in batch_results.items():
                    seats = parse_sveltekit(raw, route.max_miles, route.cabin)

                    active_ids = {s.id for s in seats}
                    if seats:
                        cycle_found_any = True

                    db.mark_gone(active_ids, route.origin, route.destination, flight_date)

                    for seat in seats:
                        if db.upsert_award(seat):
                            log.info(f"NEW: {seat}")
                            alerter.send_alert(seat)
                            db.update_status(seat.id, "alerted")

            except Exception as e:
                log.error(f"Scan failed for {route_key}: {e}")

        if total_checked > 0:
            if not cycle_found_any:
                consecutive_empty += 1
                if consecutive_empty >= 10:
                    log.warning(f"0 results for {consecutive_empty} consecutive cycles")
                    alerter.send_health_warning(
                        f"Scraper returned 0 results for {consecutive_empty} consecutive cycles. "
                        "Alaska API may be broken or all routes have no availability."
                    )
                    consecutive_empty = 0
            else:
                consecutive_empty = 0

        # Sleep in 1s increments for responsive shutdown
        if running:
            for _ in range(TICK_INTERVAL):
                if not running:
                    break
                time.sleep(1)

    browser.stop()
    db.close()
    log.info("Monitor stopped.")


if __name__ == "__main__":
    main()
