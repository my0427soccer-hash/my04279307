"""ファイルから価格を読むプロバイダ。

API キーがなくても通知の見た目や判定ロジックを試せるようにするためのもの。
テストと `python -m bugfare demo` から使う。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator

from ..models import Offer
from .base import Provider


class SampleProvider(Provider):
    name = "sample"

    def search(self) -> Iterator[Offer]:
        path = self.config.provider.fixtures_path
        if path:
            yield from self._from_file(Path(path))
        else:
            yield from self._generated()

    def _from_file(self, path: Path) -> Iterator[Offer]:
        rows = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            yield Offer(
                origin=row["origin"].upper(),
                destination=row["destination"].upper(),
                depart_date=date.fromisoformat(row["depart_date"]),
                return_date=(
                    date.fromisoformat(row["return_date"]) if row.get("return_date") else None
                ),
                price_jpy=int(row["price_jpy"]),
                source=self.name,
                airline=row.get("airline", ""),
                transfers=row.get("transfers"),
            )

    def _generated(self) -> Iterator[Offer]:
        """設定にある行き先ぶんの、それらしい価格を作って返す。

        1つだけ極端に安い便を混ぜてあるので、検知と通知の流れを確認できる。
        """
        depart = datetime.now().date() + timedelta(days=45)
        back = depart + timedelta(days=7)
        cheap_marked = False
        for origin in self.config.search.origins:
            for target in self.config.active_targets:
                for i, destination in enumerate(target.destinations):
                    normal = (target.alert_price or 80_000) * 2 + i * 3_000
                    price = normal
                    if not cheap_marked and origin == self.config.search.origins[0]:
                        price = int(normal * 0.28)   # これがバグ価格役
                        cheap_marked = True
                    yield Offer(
                        origin=origin,
                        destination=destination,
                        depart_date=depart,
                        return_date=back,
                        price_jpy=price,
                        source=self.name,
                        airline="SAMPLE",
                        transfers=0,
                    )
