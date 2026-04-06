import os
import tempfile

import pytest
import yaml

from src.config import load_config


def _write_config(data: dict) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    yaml.dump(data, f)
    f.close()
    return f.name


def _valid_config(**overrides) -> dict:
    base = {
        "scan_interval": 300,
        "routes": [
            {
                "origin": "SFO",
                "destination": "NRT",
                "cabin": "J",
                "start_date": "2026-12-15",
                "end_date": "2026-12-30",
                "max_miles": 55000,
            }
        ],
        "telegram": {"bot_token": "test-token", "chat_id": "12345"},
        "database": {"path": "./data/test.db"},
    }
    base.update(overrides)
    return base


class TestLoadConfig:
    def test_valid_config(self):
        path = _write_config(_valid_config())
        try:
            config = load_config(path)
            assert len(config.routes) == 1
            assert config.routes[0].origin == "SFO"
            assert config.routes[0].destination == "NRT"
            assert config.routes[0].cabin == "J"
            assert config.routes[0].max_miles == 55000
            assert config.scan_interval == 300
            assert config.telegram.bot_token == "test-token"
        finally:
            os.unlink(path)

    def test_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/config.yaml")

    def test_empty_file(self):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        f.close()
        try:
            with pytest.raises(ValueError, match="empty"):
                load_config(f.name)
        finally:
            os.unlink(f.name)

    def test_no_routes(self):
        path = _write_config(_valid_config(routes=[]))
        try:
            with pytest.raises(ValueError, match="At least one route"):
                load_config(path)
        finally:
            os.unlink(path)

    def test_invalid_cabin(self):
        cfg = _valid_config()
        cfg["routes"][0]["cabin"] = "Y"
        path = _write_config(cfg)
        try:
            with pytest.raises(ValueError, match="cabin must be"):
                load_config(path)
        finally:
            os.unlink(path)

    def test_negative_miles(self):
        cfg = _valid_config()
        cfg["routes"][0]["max_miles"] = -100
        path = _write_config(cfg)
        try:
            with pytest.raises(ValueError, match="positive integer"):
                load_config(path)
        finally:
            os.unlink(path)

    def test_end_before_start(self):
        cfg = _valid_config()
        cfg["routes"][0]["start_date"] = "2026-12-30"
        cfg["routes"][0]["end_date"] = "2026-12-15"
        path = _write_config(cfg)
        try:
            with pytest.raises(ValueError, match="end_date"):
                load_config(path)
        finally:
            os.unlink(path)

    def test_missing_telegram_token(self):
        cfg = _valid_config()
        cfg["telegram"] = {"chat_id": "123"}
        path = _write_config(cfg)
        try:
            with pytest.raises(ValueError, match="bot_token"):
                load_config(path)
        finally:
            os.unlink(path)

    def test_scan_interval_too_low(self):
        path = _write_config(_valid_config(scan_interval=5))
        try:
            with pytest.raises(ValueError, match="scan_interval"):
                load_config(path)
        finally:
            os.unlink(path)

    def test_missing_route_field(self):
        cfg = _valid_config()
        del cfg["routes"][0]["max_miles"]
        path = _write_config(cfg)
        try:
            with pytest.raises(ValueError, match="missing required field"):
                load_config(path)
        finally:
            os.unlink(path)

    def test_lowercase_cabin_normalized(self):
        cfg = _valid_config()
        cfg["routes"][0]["cabin"] = "j"
        path = _write_config(cfg)
        try:
            config = load_config(path)
            assert config.routes[0].cabin == "J"
        finally:
            os.unlink(path)
