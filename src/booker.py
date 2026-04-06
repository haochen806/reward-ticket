"""Auto-booking engine for Alaska Airlines award tickets.

Flow:
1. Telegram alert fires with Book Now button
2. User clicks Book Now → triggers booking
3. Camoufox navigates to search results, clicks the matching fare
4. Trip Summary loads → clicks "Add to cart"
5. Sends Telegram confirmation: "Booking X for Y miles. CONFIRM within 30s?"
6. On CONFIRM → clicks Purchase to complete
7. On timeout/cancel → aborts
"""

import json
import logging
import time
import threading

from .models import AwardSeat
from .auth import load_cookies, check_auth

log = logging.getLogger(__name__)

RESULTS_URL = "https://www.alaskaair.com/search/results"


class Booker:
    """Handles the award ticket booking flow via Camoufox."""

    def __init__(self, browser, alerter, db):
        self.browser = browser
        self.alerter = alerter
        self.db = db
        self._pending_confirm = {}
        self._confirm_result = {}

    def book(self, seat: AwardSeat) -> bool:
        if not self.browser.authenticated:
            log.error("Cannot book — not authenticated")
            self.alerter.send_health_warning(
                "Booking failed: not authenticated.\n"
                "Export cookies from alaskaair.com to data/cookies.json"
            )
            return False

        page = self.browser.page
        log.info(f"Starting booking: {seat}")

        try:
            # Step 1: Load search results
            params = f"O={seat.origin}&D={seat.destination}&OD={seat.date}&A=1&RT=false&ShoppingMethod=onlineaward&locale=en-us"
            page.goto(f"{RESULTS_URL}?{params}", timeout=60000, wait_until="domcontentloaded")
            time.sleep(8)

            if "Select Flights" not in page.title():
                log.error(f"Results page didn't load: {page.title()}")
                return False

            # Step 2: Click the matching fare button
            cabin_label = "Business" if seat.cabin == "J" else "First"
            clicked = page.evaluate('''([miles, cabinLabel]) => {
                const btns = document.querySelectorAll("button");
                // Try exact miles match in the target cabin column
                const milesK = (miles / 1000).toString().replace(".0", "");
                for (const b of btns) {
                    const text = b.textContent || "";
                    if (text.includes(milesK + "k") && text.includes("points")) {
                        b.click();
                        return "clicked: " + text.trim().substring(0, 60);
                    }
                }
                return "not found";
            }''', [seat.miles, cabin_label])

            log.info(f"Fare selection: {clicked}")
            if clicked == "not found":
                log.error("Could not find matching fare button")
                self.alerter.send_health_warning(f"Booking failed: fare not found for {seat}")
                return False

            time.sleep(5)

            # Step 3: Trip Summary page — verify and click "Add to cart"
            page.screenshot(path="/tmp/booking_summary.png")

            has_summary = page.evaluate('''() => {
                return document.body.textContent.includes("Trip summary");
            }''')

            if not has_summary:
                log.error("Trip Summary page didn't load")
                return False

            # Step 4: Send Telegram confirmation
            confirm_text = (
                f"BOOKING CONFIRMATION REQUIRED\n\n"
                f"{seat.airline} {seat.flight_number}\n"
                f"{seat.origin} -> {seat.destination}\n"
                f"{seat.date} | {'Business' if seat.cabin == 'J' else 'First'}\n"
                f"{seat.miles:,} miles + ${seat.tax:.2f}\n\n"
                f"Tap CONFIRM within 30 seconds to purchase."
            )

            event = threading.Event()
            self._pending_confirm[seat.id] = event
            self._confirm_result[seat.id] = False

            self.alerter.send_confirmation(confirm_text, seat.id)

            confirmed = event.wait(timeout=30)
            del self._pending_confirm[seat.id]
            result = self._confirm_result.pop(seat.id, False)

            if not confirmed or not result:
                log.info(f"Booking not confirmed for {seat}")
                self.alerter.send_health_warning(f"Booking timed out for {seat.flight_number} {seat.date}")
                return False

            # Step 5: Click "Add to cart"
            log.info("User confirmed — adding to cart...")
            add_clicked = page.evaluate('''() => {
                const btns = document.querySelectorAll("button, auro-button");
                for (const b of btns) {
                    const text = (b.textContent || "").trim().toLowerCase();
                    if (text.includes("add to cart")) {
                        b.click();
                        return true;
                    }
                }
                // Shadow DOM
                for (const el of document.querySelectorAll("*")) {
                    if (el.shadowRoot) {
                        for (const b of el.shadowRoot.querySelectorAll("button")) {
                            if ((b.textContent || "").toLowerCase().includes("add to cart")) {
                                b.click();
                                return true;
                            }
                        }
                    }
                }
                return false;
            }''')

            if not add_clicked:
                log.error("Could not click 'Add to cart'")
                return False

            time.sleep(8)
            page.screenshot(path="/tmp/booking_cart.png")

            # Step 6: Cart page — click Purchase/Checkout
            purchase_clicked = page.evaluate('''() => {
                const btns = document.querySelectorAll("button, auro-button, a");
                for (const b of btns) {
                    const text = (b.textContent || "").trim().toLowerCase();
                    if (text.includes("purchase") || text.includes("checkout") || text.includes("complete")) {
                        b.click();
                        return text;
                    }
                }
                for (const el of document.querySelectorAll("*")) {
                    if (el.shadowRoot) {
                        for (const b of el.shadowRoot.querySelectorAll("button")) {
                            const text = (b.textContent || "").toLowerCase();
                            if (text.includes("purchase") || text.includes("checkout")) {
                                b.click();
                                return text;
                            }
                        }
                    }
                }
                return "not found";
            }''')

            log.info(f"Purchase click: {purchase_clicked}")
            time.sleep(10)
            page.screenshot(path="/tmp/booking_final.png")

            # Step 7: Verify success
            success = page.evaluate('''() => {
                const text = document.body.textContent.toLowerCase();
                return text.includes("confirmation") || text.includes("booked") ||
                       text.includes("itinerary") || text.includes("receipt") ||
                       text.includes("thank you");
            }''')

            if success:
                self.db.update_status(seat.id, "booked")
                self.alerter.send_health_warning(
                    f"BOOKED!\n"
                    f"{seat.airline} {seat.flight_number}\n"
                    f"{seat.origin} -> {seat.destination} {seat.date}\n"
                    f"{seat.miles:,} miles + ${seat.tax:.2f}"
                )
                log.info(f"Successfully booked: {seat}")
                return True
            else:
                log.error("Purchase may not have completed")
                page.screenshot(path="/tmp/booking_unclear.png")
                self.alerter.send_health_warning(
                    f"Booking status unclear for {seat.flight_number} {seat.date}. "
                    "Check your Alaska account."
                )
                return False

        except Exception as e:
            log.error(f"Booking error: {e}")
            try:
                page.screenshot(path="/tmp/booking_error.png")
            except:
                pass
            self.alerter.send_health_warning(f"Booking error: {e}")
            return False

    def handle_confirm(self, award_id: str, confirmed: bool):
        self._confirm_result[award_id] = confirmed
        event = self._pending_confirm.get(award_id)
        if event:
            event.set()
