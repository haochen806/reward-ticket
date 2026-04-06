import json
import logging
import threading
import time
from urllib.parse import urlencode

import requests

from .models import AwardSeat

log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


class TelegramAlerter:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._offset = 0
        self._db = None
        self._polling_thread = None

    def send_alert(self, seat: AwardSeat):
        text = (
            f"SAVER SEAT FOUND\n"
            f"{seat.airline} {seat.flight_number} | {seat.origin} -> {seat.destination}\n"
            f"{seat.date} | {'Business' if seat.cabin == 'J' else 'First'} ({seat.cabin})\n"
            f"{seat.miles:,} miles + ${seat.tax:.2f} tax"
        )

        deep_link = self._build_deep_link(seat)

        keyboard = {
            "inline_keyboard": [[
                {"text": "Book", "url": deep_link},
                {"text": "Dismiss", "callback_data": json.dumps({"action": "dismiss", "id": seat.id})},
            ]]
        }

        self._send_message(text, keyboard)

    def send_health_warning(self, message: str):
        text = f"HEALTH WARNING\n{message}"
        self._send_message(text)

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
            self._answer_callback(callback["id"], "Dismissed - won't alert again")
            log.info(f"Award {award_id} dismissed via Telegram")
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

    def _build_deep_link(self, seat: AwardSeat) -> str:
        params = urlencode({
            "prior-origin-1": seat.origin,
            "prior-destination-1": seat.destination,
            "prior-departure-date-1": seat.date,
            "adults": 1,
            "prior-travel-type": "award",
            "prior-trip-type": "oneway",
        })
        return f"https://www.alaskaair.com/booking/flights?{params}"
