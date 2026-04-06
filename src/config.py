import yaml
from datetime import date
from pathlib import Path

from .models import AppConfig, Route, TelegramConfig, DatabaseConfig


def load_config(path: str) -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    if not raw:
        raise ValueError("Config file is empty")

    routes = _parse_routes(raw.get("routes", []))
    telegram = _parse_telegram(raw.get("telegram", {}))
    database = _parse_database(raw.get("database", {}))
    scan_interval = raw.get("scan_interval", 300)

    if not isinstance(scan_interval, int) or scan_interval < 10:
        raise ValueError(f"scan_interval must be an integer >= 10, got: {scan_interval}")

    return AppConfig(
        routes=routes,
        telegram=telegram,
        database=database,
        scan_interval=scan_interval,
    )


def _parse_routes(raw_routes: list) -> list[Route]:
    if not raw_routes:
        raise ValueError("At least one route is required")

    routes = []
    for i, r in enumerate(raw_routes):
        for field in ("origin", "destination", "cabin", "start_date", "end_date", "max_miles"):
            if field not in r:
                raise ValueError(f"Route {i}: missing required field '{field}'")

        cabin = r["cabin"].upper()
        if cabin not in ("J", "F"):
            raise ValueError(f"Route {i}: cabin must be 'J' or 'F', got '{cabin}'")

        start = r["start_date"]
        end = r["end_date"]
        if isinstance(start, date):
            start = start.isoformat()
        if isinstance(end, date):
            end = end.isoformat()

        # Validate date formats
        try:
            start_d = date.fromisoformat(start)
            end_d = date.fromisoformat(end)
        except ValueError:
            raise ValueError(f"Route {i}: dates must be YYYY-MM-DD format")

        if end_d < start_d:
            raise ValueError(f"Route {i}: end_date must be >= start_date")

        max_miles = r["max_miles"]
        if not isinstance(max_miles, int) or max_miles <= 0:
            raise ValueError(f"Route {i}: max_miles must be a positive integer")

        routes.append(Route(
            origin=r["origin"].upper(),
            destination=r["destination"].upper(),
            cabin=cabin,
            start_date=start,
            end_date=end,
            max_miles=max_miles,
            scan_interval=r.get("scan_interval", 300),
        ))

    return routes


def _parse_telegram(raw: dict) -> TelegramConfig:
    if not raw.get("bot_token"):
        raise ValueError("telegram.bot_token is required")
    if not raw.get("chat_id"):
        raise ValueError("telegram.chat_id is required")

    return TelegramConfig(
        bot_token=raw["bot_token"],
        chat_id=str(raw["chat_id"]),
    )


def _parse_database(raw: dict) -> DatabaseConfig:
    return DatabaseConfig(
        path=raw.get("path", "./data/awards.db"),
    )
