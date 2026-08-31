"""テスト用の小道具。"""

from __future__ import annotations

from datetime import date, timedelta

from bugfare.config import Config
from bugfare.models import Offer

BASE_CONFIG = {
    "database_path": ":memory:",
    "provider": {"name": "sample"},
    "search": {"origins": ["HND", "NRT"], "months_ahead": 3},
    "targets": [
        {
            "name": "北米",
            "destinations": ["LAX", "SFO"],
            "alert_price": 60000,
            "oneway_alert_price": 35000,
        },
        {"name": "東アジア", "destinations": ["ICN"], "alert_price": 15000},
    ],
    "detection": {"min_samples": 5, "drop_ratio": 0.5, "lookback_days": 60},
    "alerting": {"cooldown_hours": 12, "max_alerts_per_run": 10},
    "notifiers": [{"type": "console"}],
}


def make_config(**overrides) -> Config:
    data = {k: (v.copy() if isinstance(v, dict) else list(v)) for k, v in BASE_CONFIG.items()}
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key].update(value)
        else:
            data[key] = value
    return Config.from_dict(data)


def make_offer(
    price: int,
    destination: str = "LAX",
    origin: str = "HND",
    days_ahead: int = 60,
    nights: int | None = 7,
) -> Offer:
    depart = date.today() + timedelta(days=days_ahead)
    return Offer(
        origin=origin,
        destination=destination,
        depart_date=depart,
        return_date=depart + timedelta(days=nights) if nights is not None else None,
        price_jpy=price,
        source="test",
    )
