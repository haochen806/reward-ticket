from dataclasses import dataclass
from datetime import date, datetime, timedelta
from hashlib import sha256


@dataclass
class AwardSeat:
    airline: str
    flight_number: str
    origin: str
    destination: str
    date: str  # YYYY-MM-DD
    cabin: str  # J or F
    miles: int
    tax: float
    fare_class: str  # X, I, O for saver
    seat_type: str  # SAVER or MAIN

    @property
    def id(self) -> str:
        raw = f"{self.flight_number}|{self.date}|{self.cabin}|{self.fare_class}|{self.miles}"
        return sha256(raw.encode()).hexdigest()[:16]

    def __str__(self) -> str:
        return f"{self.airline} {self.flight_number} {self.origin}->{self.destination} {self.date} {self.cabin} {self.miles}mi"


@dataclass
class Route:
    origin: str
    destination: str
    cabin: str  # J or F
    start_date: str  # YYYY-MM-DD
    end_date: str  # YYYY-MM-DD
    max_miles: int
    scan_interval: int = 300  # seconds, default 5 min

    def date_range(self) -> list[str]:
        start = date.fromisoformat(self.start_date)
        end = date.fromisoformat(self.end_date)
        days = (end - start).days + 1
        return [(start + timedelta(days=i)).isoformat() for i in range(days)]


@dataclass
class TelegramConfig:
    bot_token: str
    chat_id: str


@dataclass
class DatabaseConfig:
    path: str = "./data/awards.db"


@dataclass
class AppConfig:
    routes: list[Route]
    telegram: TelegramConfig
    database: DatabaseConfig
    scan_interval: int = 300  # global scan interval in seconds
