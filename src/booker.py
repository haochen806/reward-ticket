"""Auto-booking engine for Alaska Airlines award tickets.

Proven e2e flow (classic checkout):
1. Search results → click fare button
2. Trip summary → submit "Add to cart" form
3. Cart → click "Continue to checkout" (fs-auro-button)
4. Eject to classic checkout (form submit)
5. Fill passenger info → submit form
6. Seats page → submit seats form (skip)
7. Payment page → fill CVV → click PURCHASE (no_wait_after)
8. Confirmation page
"""

import logging
import threading
import time

from .models import AwardSeat

log = logging.getLogger(__name__)

RESULTS_URL = "https://www.alaskaair.com/search/results"


class Booker:
    def __init__(self, browser, alerter, db, config=None):
        self.browser = browser
        self.alerter = alerter
        self.db = db
        self.config = config or {}
        self._pending_confirm = {}
        self._confirm_result = {}

    def book(self, seat: AwardSeat) -> bool:
        if not self.browser.authenticated:
            log.error("Cannot book — not authenticated")
            self.alerter.send_health_warning("Booking failed: not authenticated. Run: python -m src.login")
            return False

        page = self.browser.page
        log.info(f"Starting booking: {seat}")

        try:
            # Step 1: Search results
            dt = seat.date
            params = f"O={seat.origin}&D={seat.destination}&OD={dt}&A=1&RT=false&ShoppingMethod=onlineaward&locale=en-us"
            page.goto(f"{RESULTS_URL}?{params}", timeout=60000, wait_until="domcontentloaded")
            time.sleep(8)

            # Step 2: Select fare — match by miles (handle decimals like 47.5k)
            miles_k = seat.miles / 1000
            if miles_k == int(miles_k):
                miles_str = str(int(miles_k))
            else:
                miles_str = f"{miles_k:g}"

            clicked = page.evaluate(f'''() => {{
                for (const b of document.querySelectorAll("button")) {{
                    const t = b.textContent || "";
                    if (t.includes("{miles_str}k") && t.includes("points")) {{ b.click(); return t.trim().substring(0,50); }}
                }}
                return "not found";
            }}''')
            log.info(f"Fare selection: {clicked}")
            if clicked == "not found":
                log.error("Fare not found on results page")
                return False
            time.sleep(5)

            # Step 3: Add to cart (submit form)
            page.evaluate('''() => {
                for (const f of document.querySelectorAll("form")) {
                    if ((f.textContent||"").toLowerCase().includes("add to cart")) { f.submit(); return; }
                }
            }''')
            time.sleep(8)

            # Step 4: Continue to checkout
            page.evaluate('''() => {
                for (const el of document.querySelectorAll("fs-auro-button")) {
                    if ((el.textContent||"").toLowerCase().includes("continue to checkout")) { el.click(); return; }
                }
            }''')
            time.sleep(8)

            # Step 5: Eject to classic checkout
            page.evaluate('''() => {
                for (const f of document.querySelectorAll("form")) {
                    if (f.action && f.action.includes("eject")) { f.submit(); return; }
                }
            }''')
            time.sleep(10)

            # Step 6: Fill passenger info + submit
            passenger = self._get_passenger()
            page.evaluate(f'''() => {{
                const set = (id, v) => {{ const el=document.getElementById(id); if(el){{el.value=v; el.dispatchEvent(new Event("change",{{bubbles:true}}));}} }};
                set("Traveler_0__FirstName", "{passenger['first_name']}");
                set("Traveler_0__LastName", "{passenger['last_name']}");
                set("Traveler_0__Gender", "Male");
                set("Traveler_0__BirthMonth", "1");
                set("Traveler_0__BirthDay", "15");
                set("Traveler_0__BirthYear", "1990");
                const btn = document.getElementById("ContinueButton");
                if (btn) {{ const form = btn.closest("form"); if (form) form.submit(); }}
            }}''')

            # Wait for seats page
            for _ in range(15):
                time.sleep(1)
                if "Seat" in page.title():
                    break
            log.info(f"After passenger: {page.title()}")

            # Step 7: Skip seats (submit seats form)
            time.sleep(2)
            page.evaluate('() => { const f = document.getElementById("ascom-seats-form"); if(f) f.submit(); }')
            for _ in range(15):
                time.sleep(1)
                if "Payment" in page.title():
                    break
            log.info(f"After seats: {page.title()}")

            if "Payment" not in page.title():
                log.error(f"Not on payment page: {page.title()}")
                page.screenshot(path="/tmp/booking_error.png")
                return False

            # Step 8: Telegram confirmation (30s window)
            confirm_text = (
                f"BOOKING CONFIRMATION REQUIRED\n\n"
                f"{seat.airline} {seat.flight_number}\n"
                f"{seat.origin} -> {seat.destination}\n"
                f"{seat.date} | {'Business' if seat.cabin == 'J' else 'Economy'}\n"
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
                self.alerter.send_health_warning(f"Booking timed out: {seat.flight_number} {seat.date}")
                return False

            # Step 9: Fill CVV + click PURCHASE
            log.info("User confirmed — purchasing...")
            cvv_code = self.config.get("alaska", {}).get("card_security_code", "")
            if not cvv_code:
                log.error("No card_security_code in config")
                return False

            cvv = page.locator("#CreditCardInformation_BillingCreditCards_0__SecurityCode")
            cvv.click(force=True)
            time.sleep(0.3)
            cvv.fill(cvv_code)
            log.info(f"CVV set ({len(cvv.input_value())} chars)")

            # CRITICAL: no_wait_after=True — purchase navigation takes >30s
            page.locator("#PurchaseButton").click(force=True, no_wait_after=True)
            log.info("PURCHASE clicked, waiting for confirmation...")
            time.sleep(45)

            # Step 10: Check confirmation
            title = page.title()
            page.screenshot(path="/tmp/booking_confirmation.png")

            if "confirmed" in title.lower() or "thank you" in title.lower():
                self.db.update_status(seat.id, "booked")
                self.alerter.send_health_warning(
                    f"BOOKED! Confirmation: check Alaska account\n"
                    f"{seat.airline} {seat.flight_number}\n"
                    f"{seat.origin} -> {seat.destination} {seat.date}\n"
                    f"{seat.miles:,} miles + ${seat.tax:.2f}"
                )
                log.info(f"BOOKED: {seat}")
                return True
            else:
                log.warning(f"Purchase status unclear: {title}")
                self.alerter.send_health_warning(
                    f"Booking status unclear for {seat.flight_number} {seat.date}. Check your Alaska account."
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

    def _get_passenger(self) -> dict:
        """Get passenger info from config, default to first passenger."""
        passengers = self.config.get("passengers", [])
        if passengers:
            return passengers[0]
        return {"first_name": "HAO", "last_name": "CHEN"}
