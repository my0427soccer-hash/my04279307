"""検索サイトへの直リンクを組み立てる。

通知を受け取ってから購入までの時間がバグ価格の勝負なので、
タップした瞬間に該当の検索結果が開く URL を作る。
"""

from __future__ import annotations

from datetime import date
from typing import Optional
from urllib.parse import urlencode

SKYSCANNER_HOST = "https://www.skyscanner.jp"
GOOGLE_FLIGHTS = "https://www.google.com/travel/flights"


def skyscanner_url(
    origin: str,
    destination: str,
    depart_date: date,
    return_date: Optional[date] = None,
    adults: int = 1,
    cabin_class: str = "economy",
    direct_only: bool = False,
) -> str:
    """Skyscanner の検索結果ページ URL。

    パスの日付は yymmdd 形式。往復は日付を2つ並べる。
    """
    path = [
        SKYSCANNER_HOST,
        "transport",
        "flights",
        origin.lower(),
        destination.lower(),
        depart_date.strftime("%y%m%d"),
    ]
    if return_date is not None:
        path.append(return_date.strftime("%y%m%d"))

    params = {
        "adultsv2": adults,
        "cabinclass": cabin_class,
        "rtn": 1 if return_date is not None else 0,
        "preferdirects": "true" if direct_only else "false",
        "currency": "JPY",
        "market": "JP",
        "locale": "ja-JP",
    }
    return "/".join(path) + "/?" + urlencode(params)


def google_flights_url(
    origin: str,
    destination: str,
    depart_date: date,
    return_date: Optional[date] = None,
) -> str:
    """裏取り用の Google フライト検索 URL。

    Skyscanner 側で在庫が消えていたときに、同じ運賃が他社にも
    出ているかを確かめるのに使う。
    """
    if return_date is not None:
        query = (
            f"Flights from {origin} to {destination} on "
            f"{depart_date:%Y-%m-%d} through {return_date:%Y-%m-%d}"
        )
    else:
        query = f"One way flights from {origin} to {destination} on {depart_date:%Y-%m-%d}"
    return f"{GOOGLE_FLIGHTS}?" + urlencode({"q": query, "hl": "ja", "curr": "JPY"})
