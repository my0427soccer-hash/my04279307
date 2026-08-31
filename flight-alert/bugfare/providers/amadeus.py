"""Amadeus Self-Service API から価格を取る。

実在する予約可能な運賃を返すので Travelpayouts より正確だが、
1リクエストで1つの日付しか調べられない。そのため各月から代表日
（provider.sample_days）を選び、provider.stay_nights 泊の往復として問い合わせる。

テスト環境（test.api.amadeus.com）はデータが限られる。実運用では
本番キーを取り、provider.environment に "production" を入れて使う。
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any, Iterator, Optional

from ..http import HttpError, request_json
from ..models import Offer
from .base import Provider

log = logging.getLogger(__name__)

HOSTS = {
    "test": "https://test.api.amadeus.com",
    "production": "https://api.amadeus.com",
}


class AmadeusProvider(Provider):
    name = "amadeus"

    def __init__(self, config):
        super().__init__(config)
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    @property
    def host(self) -> str:
        key = "production" if self.config.provider.environment.lower() == "production" else "test"
        return HOSTS[key]

    # ------------------------------------------------------------------ 認証

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token

        cfg = self.config.provider
        if not cfg.api_key or not cfg.api_secret:
            raise RuntimeError(
                "Amadeus の api_key / api_secret が未設定です。"
                "環境変数 AMADEUS_API_KEY と AMADEUS_API_SECRET を設定してください。"
            )
        payload = request_json(
            f"{self.host}/v1/security/oauth2/token",
            method="POST",
            form_body={
                "grant_type": "client_credentials",
                "client_id": cfg.api_key,
                "client_secret": cfg.api_secret,
            },
        )
        self._token = payload["access_token"]
        self._token_expires_at = time.time() + float(payload.get("expires_in", 1799))
        return self._token

    # ------------------------------------------------------------------ 検索

    def search(self) -> Iterator[Offer]:
        cfg = self.config.provider
        requests_made = 0

        for origin in self.config.search.origins:
            for destination in self.destinations():
                for month in self.months():
                    for depart in self.sample_dates(month):
                        for trip_type in self.config.search.trip_types:
                            if requests_made >= cfg.max_requests:
                                log.warning(
                                    "リクエスト上限 %d 件に達したので打ち切ります。",
                                    cfg.max_requests,
                                )
                                return
                            requests_made += 1
                            back = (
                                depart + timedelta(days=cfg.stay_nights)
                                if trip_type == "round"
                                else None
                            )
                            rows = self._fetch(origin, destination, depart, back)
                            if requests_made > 1:
                                time.sleep(cfg.request_pause_seconds)
                            for row in rows:
                                offer = self._to_offer(row, origin, destination, depart, back)
                                if offer is not None:
                                    yield offer

    def _fetch(
        self, origin: str, destination: str, depart: date, back: Optional[date]
    ) -> list[dict]:
        params = {
            "originLocationCode": origin,
            "destinationLocationCode": destination,
            "departureDate": depart.isoformat(),
            "returnDate": back.isoformat() if back else None,
            "adults": self.config.alerting.adults,
            "currencyCode": "JPY",
            "max": self.config.search.limit_per_query,
            "nonStop": "true" if self.config.search.direct_only else "false",
        }
        try:
            payload = request_json(
                f"{self.host}/v2/shopping/flight-offers",
                params=params,
                headers={"Authorization": f"Bearer {self._access_token()}"},
            )
        except HttpError as exc:
            if exc.status == 401:
                self._token = None   # 期限切れなら次回取り直す
            log.warning("%s→%s %s の取得に失敗: %s", origin, destination, depart, exc)
            return []
        except Exception as exc:
            log.warning("%s→%s %s の取得に失敗: %s", origin, destination, depart, exc)
            return []

        data = payload.get("data") if isinstance(payload, dict) else None
        return [row for row in (data or []) if isinstance(row, dict)]

    def _to_offer(
        self,
        row: dict[str, Any],
        origin: str,
        destination: str,
        depart: date,
        back: Optional[date],
    ) -> Optional[Offer]:
        try:
            price = int(round(float(row["price"]["grandTotal"])))
        except (KeyError, TypeError, ValueError):
            return None
        if price <= 0:
            return None

        itineraries = row.get("itineraries") or []
        transfers = None
        if itineraries:
            segments = itineraries[0].get("segments") or []
            transfers = max(len(segments) - 1, 0)

        carriers = row.get("validatingAirlineCodes") or []
        return Offer(
            origin=origin,
            destination=destination,
            depart_date=depart,
            return_date=back,
            price_jpy=price,
            source=self.name,
            airline=carriers[0] if carriers else "",
            transfers=transfers,
        )
