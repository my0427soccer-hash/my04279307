"""ツール全体で使うデータ構造。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Offer:
    """1件の航空券価格。

    価格は必ず整数の日本円（税込・総額）で持つ。
    通貨換算はプロバイダ側で済ませてからここに入れる。
    """

    origin: str          # 出発空港 IATA（HND / NRT）
    destination: str     # 到着空港・都市 IATA
    depart_date: date
    return_date: Optional[date]   # 片道なら None
    price_jpy: int
    source: str                    # 取得元プロバイダ名
    airline: str = ""
    transfers: Optional[int] = None
    booking_link: str = ""         # プロバイダ側の予約リンク（あれば）
    observed_at: datetime = field(default_factory=utcnow)

    @property
    def is_round_trip(self) -> bool:
        return self.return_date is not None

    @property
    def trip_type(self) -> str:
        return "round" if self.is_round_trip else "oneway"

    @property
    def route_key(self) -> str:
        """相場を積み上げる単位。

        同じ路線でも往復と片道、出発月が違えば相場が違うので分けて持つ。
        """
        return f"{self.origin}-{self.destination}:{self.trip_type}:{self.depart_date:%Y-%m}"

    @property
    def stay_nights(self) -> Optional[int]:
        if self.return_date is None:
            return None
        return (self.return_date - self.depart_date).days

    def fingerprint(self, price_bucket: int = 1000) -> str:
        """重複通知を防ぐための識別子。

        価格を price_bucket 円単位に丸めるので、数百円の揺れで
        同じ便が何度も通知されることはない。
        """
        bucket = self.price_jpy // max(price_bucket, 1)
        raw = "|".join(
            [
                self.origin,
                self.destination,
                self.depart_date.isoformat(),
                self.return_date.isoformat() if self.return_date else "-",
                str(bucket),
            ]
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def describe(self) -> str:
        dates = f"{self.depart_date:%Y/%m/%d}"
        if self.return_date:
            dates += f" → {self.return_date:%m/%d}（{self.stay_nights}泊）"
        return f"{self.origin}→{self.destination} {dates} ¥{self.price_jpy:,}"


@dataclass(frozen=True)
class Baseline:
    """ある route_key の直近相場。"""

    route_key: str
    samples: int
    median: Optional[int]
    p25: Optional[int]
    mad: Optional[float]   # 中央絶対偏差。外れ値に強いばらつきの指標


@dataclass(frozen=True)
class Alert:
    """通知1件分。"""

    offer: Offer
    reasons: list[str]              # 発火したルール名
    messages: list[str]             # 人間が読む説明
    baseline: Optional[Baseline]
    discount: Optional[float]       # 相場からの下落率（0.6 なら 60%オフ）
    score: float                    # 並べ替え用。大きいほど「バグっぽい」

    @property
    def headline(self) -> str:
        if self.discount is not None:
            return f"相場の {round((1 - self.discount) * 100)}% — {self.offer.describe()}"
        return self.offer.describe()
