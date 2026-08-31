"""価格履歴と通知履歴を SQLite に貯める。

相場（ベースライン）は「1日1路線あたりの最安値」を積み上げて作る。
プロバイダが返す全オファーをそのまま貯めると、高い便まで混ざって
中央値が上振れし、本当のバグ価格が埋もれてしまうため。
"""

from __future__ import annotations

import sqlite3
import statistics
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

from .models import Baseline, Offer

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_low (
    route_key     TEXT NOT NULL,
    observed_date TEXT NOT NULL,
    price         INTEGER NOT NULL,
    origin        TEXT NOT NULL,
    destination   TEXT NOT NULL,
    trip_type     TEXT NOT NULL,
    depart_date   TEXT NOT NULL,
    return_date   TEXT,
    source        TEXT NOT NULL DEFAULT '',
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (route_key, observed_date)
);
CREATE INDEX IF NOT EXISTS idx_daily_low_route ON daily_low (route_key, observed_date DESC);

CREATE TABLE IF NOT EXISTS alerts (
    fingerprint TEXT PRIMARY KEY,
    route_key   TEXT NOT NULL,
    price       INTEGER NOT NULL,
    summary     TEXT NOT NULL DEFAULT '',
    sent_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alerts_route ON alerts (route_key, sent_at DESC);

CREATE TABLE IF NOT EXISTS runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    offers     INTEGER NOT NULL DEFAULT 0,
    alerts     INTEGER NOT NULL DEFAULT 0,
    note       TEXT NOT NULL DEFAULT ''
);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.parent and str(self.path.parent) not in ("", "."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ 履歴

    def record_offers(self, offers: Iterable[Offer], observed_date: Optional[date] = None) -> int:
        """その日の路線ごとの最安値を書き込む。

        同じ日に何度実行しても、より安い価格が来たときだけ更新される。
        """
        day = (observed_date or datetime.now(timezone.utc).date()).isoformat()
        now = datetime.now(timezone.utc).isoformat()
        rows = 0
        with self.conn:
            for offer in offers:
                self.conn.execute(
                    """
                    INSERT INTO daily_low (route_key, observed_date, price, origin, destination,
                                           trip_type, depart_date, return_date, source, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(route_key, observed_date) DO UPDATE SET
                        price       = excluded.price,
                        depart_date = excluded.depart_date,
                        return_date = excluded.return_date,
                        source      = excluded.source,
                        updated_at  = excluded.updated_at
                    WHERE excluded.price < daily_low.price
                    """,
                    (
                        offer.route_key,
                        day,
                        offer.price_jpy,
                        offer.origin,
                        offer.destination,
                        offer.trip_type,
                        offer.depart_date.isoformat(),
                        offer.return_date.isoformat() if offer.return_date else None,
                        offer.source,
                        now,
                    ),
                )
                rows += 1
        return rows

    def baseline(
        self,
        route_key: str,
        lookback_days: int,
        before: Optional[date] = None,
    ) -> Baseline:
        """直近 lookback_days の相場を返す。

        当日ぶんは含めない。バグ価格そのものが相場を押し下げて
        検知できなくなるのを避けるため。
        """
        end = before or datetime.now(timezone.utc).date()
        start = end - timedelta(days=lookback_days)
        cur = self.conn.execute(
            """
            SELECT price FROM daily_low
            WHERE route_key = ? AND observed_date < ? AND observed_date >= ?
            ORDER BY observed_date DESC
            """,
            (route_key, end.isoformat(), start.isoformat()),
        )
        prices = [int(r["price"]) for r in cur.fetchall()]
        if not prices:
            return Baseline(route_key, 0, None, None, None)

        median = int(statistics.median(prices))
        p25 = int(_percentile(prices, 25))
        deviations = [abs(p - median) for p in prices]
        mad = float(statistics.median(deviations))
        return Baseline(route_key, len(prices), median, p25, mad)

    def history(self, route_key: str, limit: int = 30) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            """
            SELECT observed_date, price, depart_date, return_date FROM daily_low
            WHERE route_key = ? ORDER BY observed_date DESC LIMIT ?
            """,
            (route_key, limit),
        )
        return cur.fetchall()

    def route_keys(self) -> list[str]:
        cur = self.conn.execute("SELECT DISTINCT route_key FROM daily_low ORDER BY route_key")
        return [r["route_key"] for r in cur.fetchall()]

    def prune(self, keep_days: int) -> int:
        cutoff = (datetime.now(timezone.utc).date() - timedelta(days=keep_days)).isoformat()
        with self.conn:
            cur = self.conn.execute("DELETE FROM daily_low WHERE observed_date < ?", (cutoff,))
            self.conn.execute(
                "DELETE FROM alerts WHERE sent_at < ?",
                ((datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat(),),
            )
        return cur.rowcount

    # ------------------------------------------------------------------ 通知

    def was_alerted(self, fingerprint: str, cooldown_hours: int) -> bool:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)).isoformat()
        cur = self.conn.execute(
            "SELECT 1 FROM alerts WHERE fingerprint = ? AND sent_at >= ? LIMIT 1",
            (fingerprint, cutoff),
        )
        return cur.fetchone() is not None

    def mark_alerted(self, fingerprint: str, route_key: str, price: int, summary: str) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO alerts (fingerprint, route_key, price, summary, sent_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    sent_at = excluded.sent_at, price = excluded.price
                """,
                (fingerprint, route_key, price, summary, datetime.now(timezone.utc).isoformat()),
            )

    def recent_alerts(self, limit: int = 20) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM alerts ORDER BY sent_at DESC LIMIT ?", (limit,)
        )
        return cur.fetchall()

    def log_run(self, offers: int, alerts: int, note: str = "") -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO runs (started_at, offers, alerts, note) VALUES (?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), offers, alerts, note),
            )


def _percentile(values: list[int], pct: float) -> float:
    """線形補間つきパーセンタイル。"""
    if not values:
        raise ValueError("空のリスト")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = (len(ordered) - 1) * (pct / 100.0)
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    frac = pos - low
    return ordered[low] * (1 - frac) + ordered[high] * frac


def open_store(path: str | Path) -> Store:
    return Store(path)


__all__ = ["Store", "open_store", "closing"]
