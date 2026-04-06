import pytest

from src.models import AwardSeat
from src.parser import parse_awards, _normalize_cabin


def _mock_response(fares: list, flight="AS123", origin="SFO", dest="NRT", depart="2026-12-15T10:00:00") -> dict:
    return {
        "slices": [{
            "segments": [{
                "flightNumber": flight,
                "origin": origin,
                "destination": dest,
                "departureTime": depart,
                "operatingAirline": "AS",
                "fares": fares,
            }]
        }]
    }


class TestParseAwards:
    def test_saver_j_under_threshold(self):
        data = _mock_response([
            {"bookingClass": "X", "cabin": "business", "miles": 35000, "tax": 56.20, "fareType": "SAVER"},
        ])
        seats = parse_awards(data, 55000, "J")
        assert len(seats) == 1
        assert seats[0].miles == 35000
        assert seats[0].fare_class == "X"
        assert seats[0].seat_type == "SAVER"

    def test_saver_over_threshold_filtered(self):
        data = _mock_response([
            {"bookingClass": "X", "cabin": "business", "miles": 80000, "tax": 56.20, "fareType": "SAVER"},
        ])
        seats = parse_awards(data, 55000, "J")
        assert len(seats) == 0

    def test_main_fare_filtered(self):
        data = _mock_response([
            {"bookingClass": "Y", "cabin": "business", "miles": 35000, "tax": 56.20, "fareType": "MAIN"},
        ])
        seats = parse_awards(data, 55000, "J")
        assert len(seats) == 0

    def test_wrong_cabin_filtered(self):
        data = _mock_response([
            {"bookingClass": "X", "cabin": "first", "miles": 35000, "tax": 56.20, "fareType": "SAVER"},
        ])
        seats = parse_awards(data, 55000, "J")
        assert len(seats) == 0

    def test_f_cabin(self):
        data = _mock_response([
            {"bookingClass": "O", "cabin": "first", "miles": 70000, "tax": 100.0, "fareType": "SAVER"},
        ])
        seats = parse_awards(data, 80000, "F")
        assert len(seats) == 1
        assert seats[0].cabin == "F"

    def test_multiple_saver_fares(self):
        data = _mock_response([
            {"bookingClass": "X", "cabin": "business", "miles": 35000, "tax": 56.20, "fareType": "SAVER"},
            {"bookingClass": "I", "cabin": "business", "miles": 45000, "tax": 56.20, "fareType": "SAVER"},
            {"bookingClass": "Y", "cabin": "business", "miles": 70000, "tax": 56.20, "fareType": "MAIN"},
        ])
        seats = parse_awards(data, 55000, "J")
        assert len(seats) == 2

    def test_empty_data(self):
        assert parse_awards({}, 55000, "J") == []
        assert parse_awards(None, 55000, "J") == []

    def test_no_slices(self):
        assert parse_awards({"slices": []}, 55000, "J") == []

    def test_tax_as_string(self):
        data = _mock_response([
            {"bookingClass": "X", "cabin": "business", "miles": 35000, "tax": "$56.20", "fareType": "SAVER"},
        ])
        seats = parse_awards(data, 55000, "J")
        assert seats[0].tax == 56.20

    def test_zero_miles_filtered(self):
        data = _mock_response([
            {"bookingClass": "X", "cabin": "business", "miles": 0, "tax": 56.20, "fareType": "SAVER"},
        ])
        seats = parse_awards(data, 55000, "J")
        assert len(seats) == 0


class TestNormalizeCabin:
    def test_business(self):
        assert _normalize_cabin("business") == "J"

    def test_first(self):
        assert _normalize_cabin("first") == "F"

    def test_already_letter(self):
        assert _normalize_cabin("J") == "J"
        assert _normalize_cabin("f") == "F"

    def test_empty(self):
        assert _normalize_cabin("") == ""
