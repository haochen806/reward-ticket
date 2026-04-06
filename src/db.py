import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import AwardSeat

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS awards (
    id TEXT PRIMARY KEY,
    airline TEXT NOT NULL,
    flight_number TEXT NOT NULL,
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    date TEXT NOT NULL,
    cabin TEXT NOT NULL,
    miles INTEGER NOT NULL,
    tax REAL NOT NULL,
    fare_class TEXT NOT NULL,
    seat_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    status_changed_at TEXT
);

CREATE TABLE IF NOT EXISTS scan_queue (
    date TEXT NOT NULL,
    route TEXT NOT NULL,
    last_checked_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    PRIMARY KEY (date, route)
);

CREATE INDEX IF NOT EXISTS idx_awards_status ON awards(status);
CREATE INDEX IF NOT EXISTS idx_awards_date ON awards(date);
CREATE INDEX IF NOT EXISTS idx_scan_queue_stale ON scan_queue(route, last_checked_at);
"""


class Database:
    def __init__(self, path: str):
        db_path = Path(path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def upsert_award(self, seat: AwardSeat) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        existing = self.conn.execute(
            "SELECT id, status FROM awards WHERE id = ?", (seat.id,)
        ).fetchone()

        if existing:
            status = existing["status"]
            if status in ("booked", "dismissed"):
                # Suppressed — don't re-alert
                self.conn.execute(
                    "UPDATE awards SET last_seen_at = ? WHERE id = ?",
                    (now, seat.id),
                )
                self.conn.commit()
                return False
            if status == "gone":
                # Reappeared after disappearing — treat as new
                self.conn.execute(
                    "UPDATE awards SET status = 'new', last_seen_at = ?, status_changed_at = ? WHERE id = ?",
                    (now, now, seat.id),
                )
                self.conn.commit()
                return True
            # Already seen and active — update last_seen_at
            self.conn.execute(
                "UPDATE awards SET last_seen_at = ?, miles = ?, tax = ? WHERE id = ?",
                (now, seat.miles, seat.tax, seat.id),
            )
            self.conn.commit()
            return False

        # Genuinely new seat
        self.conn.execute(
            """INSERT INTO awards (id, airline, flight_number, origin, destination, date,
               cabin, miles, tax, fare_class, seat_type, status, first_seen_at, last_seen_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)""",
            (seat.id, seat.airline, seat.flight_number, seat.origin, seat.destination,
             seat.date, seat.cabin, seat.miles, seat.tax, seat.fare_class, seat.seat_type,
             now, now),
        )
        self.conn.commit()
        return True

    VALID_STATUSES = {"new", "alerted", "gone", "booked", "dismissed"}

    def update_status(self, award_id: str, status: str):
        if status not in self.VALID_STATUSES:
            raise ValueError(f"Invalid status '{status}'. Must be one of: {self.VALID_STATUSES}")
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE awards SET status = ?, status_changed_at = ? WHERE id = ?",
            (status, now, award_id),
        )
        self.conn.commit()

    def get_award(self, award_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM awards WHERE id = ?", (award_id,)
        ).fetchone()
        return dict(row) if row else None

    def mark_gone(self, active_ids: set[str], route_origin: str, route_dest: str, route_date: str):
        rows = self.conn.execute(
            """SELECT id FROM awards
               WHERE origin = ? AND destination = ? AND date = ?
               AND status IN ('new', 'alerted')""",
            (route_origin, route_dest, route_date),
        ).fetchall()

        now = datetime.now(timezone.utc).isoformat()
        for row in rows:
            if row["id"] not in active_ids:
                self.conn.execute(
                    "UPDATE awards SET status = 'gone', status_changed_at = ? WHERE id = ?",
                    (now, row["id"]),
                )
        self.conn.commit()

    def seed_queue(self, route_key: str, dates: list[str]):
        """Insert dates into scan_queue if not already present. Idempotent."""
        for d in dates:
            self.conn.execute(
                "INSERT OR IGNORE INTO scan_queue (date, route) VALUES (?, ?)",
                (d, route_key),
            )
        self.conn.commit()

    def get_stale_dates(self, route_key: str, stale_seconds: int = 300) -> list[str]:
        """Return dates not checked within stale_seconds."""
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(seconds=stale_seconds)).isoformat()
        rows = self.conn.execute(
            """SELECT date FROM scan_queue
               WHERE route = ? AND (last_checked_at IS NULL OR last_checked_at < ?)
               ORDER BY date""",
            (route_key, cutoff),
        ).fetchall()
        return [row["date"] for row in rows]

    def mark_checked(self, route_key: str, dates: list[str]):
        """Update last_checked_at for the given dates."""
        now = datetime.now(timezone.utc).isoformat()
        for d in dates:
            self.conn.execute(
                "UPDATE scan_queue SET last_checked_at = ?, status = 'checked' WHERE date = ? AND route = ?",
                (now, d, route_key),
            )
        self.conn.commit()

    def close(self):
        self.conn.close()
