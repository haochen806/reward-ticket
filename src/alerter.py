import json
import logging
import smtplib
import threading
import time
from email.mime.text import MIMEText
from urllib.parse import urlencode

import requests

from .models import AwardSeat

log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


class EmailAlerter:
    """Send email alerts via SMTP (Gmail)."""

    def __init__(self, smtp_server: str, smtp_port: int, username: str, password: str, to: str):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.to = to

    def send(self, subject: str, body: str):
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = self.username
        msg["To"] = self.to
        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as s:
                s.starttls()
                s.login(self.username, self.password)
                s.send_message(msg)
            log.info(f"Email sent: {subject}")
        except Exception as e:
            log.error(f"Email failed: {e}")


class TelegramAlerter:
    def __init__(self, bot_token: str, chat_id: str, email_config: dict | None = None):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._offset = 0
        self._db = None
        self._booker = None
        self._polling_thread = None
        self._email = None
        if email_config and email_config.get("username"):
            self._email = EmailAlerter(
                email_config.get("smtp_server", "smtp.gmail.com"),
                email_config.get("smtp_port", 587),
                email_config["username"],
                email_config["password"],
                email_config.get("to", email_config["username"]),
            )

    def set_booker(self, booker):
        """Attach the booker for handling book/confirm callbacks."""
        self._booker = booker

    def send_alert(self, seat: AwardSeat):
        deep_link = (
            f"https://www.alaskaair.com/search/results?"
            f"O={seat.origin}&D={seat.destination}&OD={seat.date}"
            f"&A=1&RT=false&ShoppingMethod=onlineaward&locale=en-us"
        )

        text = (
            f"SAVER SEAT FOUND\n"
            f"{seat.airline} {seat.flight_number} | {seat.origin} -> {seat.destination}\n"
            f"{seat.date} | {'Business' if seat.cabin == 'J' else 'First'} ({seat.cabin})\n"
            f"{seat.miles:,} miles + ${seat.tax:.2f} tax"
        )

        keyboard = {
            "inline_keyboard": [[
                {"text": "Book Now", "url": deep_link},
                {"text": "Dismiss", "callback_data": json.dumps({"action": "dismiss", "id": seat.id})},
            ]]
        }

        self._send_message(text, keyboard)

        # Also send email
        if self._email:
            subject = f"Award: {seat.airline} {seat.flight_number} {seat.origin}->{seat.destination} {seat.date} {seat.miles:,}mi"
            body = f"{text}\n\nBook now: {deep_link}"
            self._email.send(subject, body)

    def send_confirmation(self, text: str, award_id: str):
        """Send a booking confirmation prompt with Confirm/Cancel buttons."""
        keyboard = {
            "inline_keyboard": [[
                {"text": "CONFIRM Purchase", "callback_data": json.dumps({"action": "confirm", "id": award_id})},
                {"text": "Cancel", "callback_data": json.dumps({"action": "cancel", "id": award_id})},
            ]]
        }
        self._send_message(text, keyboard)

    def send_health_warning(self, message: str):
        self._send_message(message)

    def start_polling(self, db):
        self._db = db
        self._polling_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._polling_thread.start()
        log.info("Telegram callback polling started")

    def _poll_loop(self):
        while True:
            try:
                updates = self._get_updates()
                for update in updates:
                    self._handle_update(update)
                    self._offset = update["update_id"] + 1
            except Exception as e:
                log.error(f"Telegram polling error: {e}")
            time.sleep(1)

    def _get_updates(self) -> list:
        url = TELEGRAM_API.format(token=self.bot_token, method="getUpdates")
        try:
            resp = requests.get(url, params={"offset": self._offset, "timeout": 30}, timeout=35)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    return data.get("result", [])
        except requests.RequestException as e:
            log.error(f"Failed to get updates: {e}")
        return []

    def _handle_update(self, update: dict):
        callback = update.get("callback_query")
        if not callback:
            return

        try:
            data = json.loads(callback.get("data", "{}"))
        except json.JSONDecodeError:
            return

        # Verify sender is the authorized user
        sender_id = str(callback.get("from", {}).get("id", ""))
        if sender_id != self.chat_id:
            self._answer_callback(callback["id"], "Unauthorized")
            return

        action = data.get("action")
        award_id = data.get("id")

        if action == "dismiss" and award_id and self._db:
            self._db.update_status(award_id, "dismissed")
            self._answer_callback(callback["id"], "Dismissed")
            log.info(f"Award {award_id} dismissed via Telegram")

        elif action == "book" and award_id and self._booker:
            self._answer_callback(callback["id"], "Starting booking...")
            # Run booking in a thread to not block polling
            award = self._db.get_award(award_id)
            if award:
                seat = AwardSeat(
                    airline=award["airline"],
                    flight_number=award["flight_number"],
                    origin=award["origin"],
                    destination=award["destination"],
                    date=award["date"],
                    cabin=award["cabin"],
                    miles=award["miles"],
                    tax=award["tax"],
                    fare_class=award["fare_class"],
                    seat_type=award["seat_type"],
                )
                threading.Thread(target=self._booker.book, args=(seat,), daemon=True).start()
            else:
                self._answer_callback(callback["id"], "Award not found")

        elif action == "confirm" and award_id and self._booker:
            self._answer_callback(callback["id"], "Confirmed! Completing purchase...")
            self._booker.handle_confirm(award_id, True)

        elif action == "cancel" and award_id and self._booker:
            self._answer_callback(callback["id"], "Cancelled")
            self._booker.handle_confirm(award_id, False)

        else:
            self._answer_callback(callback["id"], "Unknown action")

    def _answer_callback(self, callback_id: str, text: str):
        url = TELEGRAM_API.format(token=self.bot_token, method="answerCallbackQuery")
        try:
            requests.post(url, json={"callback_query_id": callback_id, "text": text}, timeout=10)
        except requests.RequestException:
            pass

    def _send_message(self, text: str, reply_markup: dict | None = None):
        url = TELEGRAM_API.format(token=self.bot_token, method="sendMessage")
        payload = {"chat_id": self.chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code != 200:
                log.error(f"Telegram send failed ({resp.status_code}): {resp.text}")
        except requests.RequestException as e:
            log.error(f"Telegram send error: {e}")
