"""価格を取ってくる部品の共通インターフェース。

Skyscanner には誰でも使える公開 API がなく、サイトを直接スクレイピング
するのは利用規約違反かつ Bot 対策でまず通らない。そのため価格の取得は
正規に使える他社 API で行い、通知には Skyscanner の検索リンクを添えて、
確認と購入は Skyscanner 上でできるようにしている。
"""

from __future__ import annotations

import calendar
import logging
from abc import ABC, abstractmethod
from datetime import date, timedelta
from typing import Iterator

from ..config import Config
from ..models import Offer

log = logging.getLogger(__name__)


class Provider(ABC):
    name = "base"

    def __init__(self, config: Config):
        self.config = config

    @abstractmethod
    def search(self) -> Iterator[Offer]:
        """設定にある路線を順に調べ、見つかった価格を返す。"""

    # --------------------------------------------------------------- 共通処理

    def destinations(self) -> list[str]:
        seen: list[str] = []
        for target in self.config.active_targets:
            for dest in target.destinations:
                if dest not in seen:
                    seen.append(dest)
        return seen

    def months(self) -> list[date]:
        """調べる対象の月（各月の1日）。"""
        today = date.today()
        first = date(today.year, today.month, 1)
        out = []
        for i in range(self.config.search.months_ahead):
            year = first.year + (first.month - 1 + i) // 12
            month = (first.month - 1 + i) % 12 + 1
            out.append(date(year, month, 1))
        return out

    def earliest_departure(self) -> date:
        return date.today() + timedelta(days=self.config.search.min_days_ahead)

    def sample_dates(self, month: date) -> list[date]:
        """日付を総当たりできないプロバイダ向けに、月内の代表日を選ぶ。"""
        last_day = calendar.monthrange(month.year, month.month)[1]
        floor = self.earliest_departure()
        out = []
        for day in self.config.provider.sample_days:
            if 1 <= day <= last_day:
                candidate = date(month.year, month.month, day)
                if candidate >= floor:
                    out.append(candidate)
        return out


def build_provider(config: Config) -> Provider:
    from .amadeus import AmadeusProvider
    from .sample import SampleProvider
    from .travelpayouts import TravelpayoutsProvider

    providers = {
        TravelpayoutsProvider.name: TravelpayoutsProvider,
        AmadeusProvider.name: AmadeusProvider,
        SampleProvider.name: SampleProvider,
    }
    name = config.provider.name.lower()
    if name not in providers:
        raise ValueError(
            f"未知のプロバイダ '{name}'。使えるのは: {', '.join(sorted(providers))}"
        )
    return providers[name](config)
