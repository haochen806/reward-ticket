import json

from src.alerter import TelegramAlerter
from src.models import AwardSeat


def _seat() -> AwardSeat:
    return AwardSeat(
        airline="AS",
        flight_number="123",
        origin="SFO",
        destination="NRT",
        date="2026-12-15",
        cabin="J",
        miles=35000,
        tax=56.20,
        fare_class="X",
        seat_type="SAVER",
    )


class TestDeepLink:
    def test_contains_required_params(self):
        alerter = TelegramAlerter("fake-token", "12345")
        seat = _seat()
        link = alerter._build_deep_link(seat)
        assert "prior-origin-1=SFO" in link
        assert "prior-destination-1=NRT" in link
        assert "prior-departure-date-1=2026-12-15" in link
        assert "prior-travel-type=award" in link
        assert "prior-trip-type=oneway" in link
        assert link.startswith("https://www.alaskaair.com/booking/flights?")


class TestCallbackData:
    def test_dismiss_callback_format(self):
        seat = _seat()
        data = json.dumps({"action": "dismiss", "id": seat.id})
        parsed = json.loads(data)
        assert parsed["action"] == "dismiss"
        assert parsed["id"] == seat.id

    def test_callback_data_size(self):
        # Telegram limits callback_data to 64 bytes
        seat = _seat()
        data = json.dumps({"action": "dismiss", "id": seat.id})
        assert len(data.encode()) <= 64


class TestFirstCabinLabel:
    def test_business_label(self):
        seat = _seat()
        label = "Business" if seat.cabin == "J" else "First"
        assert label == "Business"

    def test_first_label(self):
        seat = AwardSeat("AS", "123", "SFO", "NRT", "2026-12-15", "F", 70000, 100.0, "O", "SAVER")
        label = "Business" if seat.cabin == "J" else "First"
        assert label == "First"
