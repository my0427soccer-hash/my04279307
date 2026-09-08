"""Travelpayouts（Aviasales）Data API から価格を取る。

無料のアフィリエイト登録でトークンが取れて、路線と月を指定すると
その月のカレンダー最安値をまとめて返してくれる。1リクエストで1か月ぶん
見られるので、広く浅く監視する用途に向いている。

返ってくるのは各社の集計・キャッシュ済みデータなので、実売より数十分〜
数時間遅れることがある。あくまで「アラートの引き金」として使い、
最終確認は通知に入れた Skyscanner のリンクで行う前提。
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import Any, Iterator, Optional

from ..http import HttpError, request_json
from ..models import Offer
from .base import Provider

log = logging.getLogger(__name__)

ENDPOINT = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
AVIASALES = "https://www.aviasales.com"


class TravelpayoutsProvider(Provider):
    name = "travelpayouts"

    def search(self) -> Iterator[Offer]:
        cfg = self.config.provider
        if not cfg.token:
            raise RuntimeError(
                "Travelpayouts のトークンが未設定です。"
                "環境変数 TRAVELPAYOUTS_TOKEN を設定してください。"
            )

        search = self.config.search
        floor = self.earliest_departure()
        requests_made = 0

        # 出発地をいちばん内側で回す。上限で打ち切られたときに、
        # 先頭の出発地だけを調べ終えて残りが丸ごと抜ける、という偏りを避ける。
        # （羽田を全部見たところで力尽きて成田を見ない、という状態にしない）
        for destination in self.destinations():
            for month in self.months():
                for trip_type in search.trip_types:
                    for origin in search.origins:
                        if requests_made >= cfg.max_requests:
                            log.warning(
                                "リクエスト上限 %d 件に達したので打ち切ります。"
                                "全部を見るには provider.max_requests を %d 以上にするか、"
                                "search.months_ahead か行き先を減らしてください。",
                                cfg.max_requests,
                                self.required_requests(),
                            )
                            return
                        requests_made += 1
                        rows = self._fetch(origin, destination, month, trip_type)
                        if requests_made > 1:
                            time.sleep(cfg.request_pause_seconds)
                        for row in rows:
                            offer = self._to_offer(row, origin, destination, trip_type)
                            if offer is None or offer.depart_date < floor:
                                continue
                            yield offer

    # ------------------------------------------------------------------ 取得

    def _fetch(self, origin: str, destination: str, month: date, trip_type: str) -> list[dict]:
        params = {
            "origin": origin,
            "destination": destination,
            "departure_at": month.strftime("%Y-%m"),
            "one_way": "true" if trip_type == "oneway" else "false",
            "currency": "jpy",
            "sorting": "price",
            "limit": self.config.search.limit_per_query,
            "direct": "true" if self.config.search.direct_only else "false",
            "market": self.config.provider.market,
            "page": 1,
        }
        try:
            payload = request_json(
                ENDPOINT, params=params, headers={"X-Access-Token": self.config.provider.token}
            )
        except HttpError as exc:
            if exc.status in (401, 403):
                raise RuntimeError(
                    "Travelpayouts のトークンが拒否されました。値を確認してください。"
                ) from exc
            log.warning("%s→%s %s の取得に失敗: %s", origin, destination, month, exc)
            return []
        except Exception as exc:  # ネットワーク断で全体を止めない
            log.warning("%s→%s %s の取得に失敗: %s", origin, destination, month, exc)
            return []

        if not isinstance(payload, dict) or not payload.get("success", True):
            log.warning("%s→%s の応答が想定と違います: %s", origin, destination, payload)
            return []
        data = payload.get("data") or []
        return [row for row in data if isinstance(row, dict)]

    def _to_offer(
        self, row: dict[str, Any], origin: str, destination: str, trip_type: str
    ) -> Optional[Offer]:
        depart = _parse_date(row.get("departure_at"))
        if depart is None:
            return None
        back = _parse_date(row.get("return_at")) if trip_type == "round" else None
        if trip_type == "round" and back is None:
            return None

        try:
            price = int(round(float(row["price"])))
        except (KeyError, TypeError, ValueError):
            return None
        if price <= 0:
            return None

        link = row.get("link") or ""
        if link and link.startswith("/"):
            link = AVIASALES + link

        return Offer(
            origin=(row.get("origin") or origin).upper(),
            destination=(row.get("destination") or destination).upper(),
            depart_date=depart,
            return_date=back,
            price_jpy=price,
            source=self.name,
            airline=row.get("airline") or "",
            transfers=_as_int(row.get("transfers")),
            booking_link=link,
        )


def _parse_date(value: Any) -> Optional[date]:
    """"2026-04-15" と "2026-04-15T10:20:00+09:00" のどちらも受ける。"""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
