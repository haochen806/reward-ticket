import os
import pytest

from src.models import AwardSeat
from src.db import Database


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = Database(db_path)
    yield database
    database.close()


def _seat(miles=35000, flight="123", fare_class="X") -> AwardSeat:
    return AwardSeat(
        airline="AS",
        flight_number=flight,
        origin="SFO",
        destination="NRT",
        date="2026-12-15",
        cabin="J",
        miles=miles,
        tax=56.20,
        fare_class=fare_class,
        seat_type="SAVER",
    )


class TestUpsertAward:
    def test_new_seat_returns_true(self, db):
        assert db.upsert_award(_seat()) is True

    def test_duplicate_returns_false(self, db):
        seat = _seat()
        db.upsert_award(seat)
        assert db.upsert_award(seat) is False

    def test_different_miles_is_new(self, db):
        s1 = _seat(miles=35000)
        s2 = _seat(miles=25000)
        assert s1.id != s2.id
        assert db.upsert_award(s1) is True
        assert db.upsert_award(s2) is True

    def test_dismissed_suppressed(self, db):
        seat = _seat()
        db.upsert_award(seat)
        db.update_status(seat.id, "dismissed")
        assert db.upsert_award(seat) is False

    def test_booked_suppressed(self, db):
        seat = _seat()
        db.upsert_award(seat)
        db.update_status(seat.id, "booked")
        assert db.upsert_award(seat) is False

    def test_gone_reappear_is_new(self, db):
        seat = _seat()
        db.upsert_award(seat)
        db.update_status(seat.id, "alerted")
        db.mark_gone(set(), "SFO", "NRT", "2026-12-15")
        assert db.get_award(seat.id)["status"] == "gone"
        # Reappear
        assert db.upsert_award(seat) is True
        assert db.get_award(seat.id)["status"] == "new"


class TestMarkGone:
    def test_active_seats_not_marked_gone(self, db):
        seat = _seat()
        db.upsert_award(seat)
        db.update_status(seat.id, "alerted")
        db.mark_gone({seat.id}, "SFO", "NRT", "2026-12-15")
        assert db.get_award(seat.id)["status"] == "alerted"

    def test_missing_seats_marked_gone(self, db):
        seat = _seat()
        db.upsert_award(seat)
        db.update_status(seat.id, "alerted")
        db.mark_gone(set(), "SFO", "NRT", "2026-12-15")
        assert db.get_award(seat.id)["status"] == "gone"

    def test_different_route_not_affected(self, db):
        seat = _seat()
        db.upsert_award(seat)
        db.update_status(seat.id, "alerted")
        db.mark_gone(set(), "LAX", "HND", "2026-12-15")
        assert db.get_award(seat.id)["status"] == "alerted"


class TestGetAward:
    def test_exists(self, db):
        seat = _seat()
        db.upsert_award(seat)
        award = db.get_award(seat.id)
        assert award is not None
        assert award["miles"] == 35000

    def test_not_exists(self, db):
        assert db.get_award("nonexistent") is None
