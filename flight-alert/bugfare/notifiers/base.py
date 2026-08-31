"""通知の共通部分。文面の組み立てと送信先の振り分け。"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Sequence

from ..config import AlertingConfig
from ..links import google_flights_url, skyscanner_url
from ..models import Alert

log = logging.getLogger(__name__)

RULE_LABELS = {
    "absolute": "通知ライン超え",
    "baseline": "相場割れ",
    "outlier": "統計的な外れ値",
}


def skyscanner_link(alert: Alert, alerting: AlertingConfig, direct_only: bool = False) -> str:
    offer = alert.offer
    return skyscanner_url(
        offer.origin,
        offer.destination,
        offer.depart_date,
        offer.return_date,
        adults=alerting.adults,
        cabin_class=alerting.cabin_class,
        direct_only=direct_only,
    )


def alert_title(alert: Alert) -> str:
    offer = alert.offer
    trip = "往復" if offer.is_round_trip else "片道"
    return f"{offer.origin}→{offer.destination} {trip} ¥{offer.price_jpy:,}"


def alert_body_lines(alert: Alert, alerting: AlertingConfig) -> list[str]:
    """プレーンテキストの本文。各通知先はこれを整形して使う。"""
    offer = alert.offer
    lines = []

    if offer.return_date:
        lines.append(
            f"日程: {offer.depart_date:%Y/%m/%d}（{_weekday(offer.depart_date)}）発 → "
            f"{offer.return_date:%m/%d}（{_weekday(offer.return_date)}）帰り・{offer.stay_nights}泊"
        )
    else:
        lines.append(f"日程: {offer.depart_date:%Y/%m/%d}（{_weekday(offer.depart_date)}）発 片道")

    detail = []
    if offer.airline:
        detail.append(f"航空会社 {offer.airline}")
    if offer.transfers is not None:
        detail.append("直行便" if offer.transfers == 0 else f"乗り継ぎ{offer.transfers}回")
    if detail:
        lines.append("便: " + " / ".join(detail))

    if alert.baseline and alert.baseline.median:
        lines.append(
            f"相場: 直近{alert.baseline.samples}日の中央値 ¥{alert.baseline.median:,}"
        )

    lines.append("判定: " + "、".join(RULE_LABELS.get(r, r) for r in alert.reasons))
    lines.extend(f"　・{m}" for m in alert.messages)

    lines.append("")
    lines.append(f"Skyscannerで確認: {skyscanner_link(alert, alerting)}")
    lines.append(f"念のため他社でも確認: {google_flights_url(offer.origin, offer.destination, offer.depart_date, offer.return_date)}")
    if offer.booking_link:
        lines.append(f"価格の取得元: {offer.booking_link}")
    lines.append("")
    lines.append("※ 価格データには遅れがあります。表示が違う場合は既に売り切れです。")
    return lines


def plain_text(alerts: Sequence[Alert], alerting: AlertingConfig) -> str:
    chunks = []
    for alert in alerts:
        chunks.append("🚨 " + alert_title(alert))
        chunks.extend(alert_body_lines(alert, alerting))
        chunks.append("-" * 32)
    return "\n".join(chunks).rstrip("-\n")


WEEKDAYS = "月火水木金土日"


def _weekday(d) -> str:
    return WEEKDAYS[d.weekday()]


class Notifier(ABC):
    type_name = "base"

    def __init__(self, settings: dict, alerting: AlertingConfig):
        self.settings = settings
        self.alerting = alerting

    @abstractmethod
    def send(self, alerts: Sequence[Alert]) -> None:
        """通知を送る。失敗したら例外を投げる。"""

    def require(self, key: str) -> str:
        value = str(self.settings.get(key) or "").strip()
        if not value:
            raise ValueError(
                f"通知設定 {self.type_name} の '{key}' が空です。"
                "環境変数が設定されているか確認してください。"
            )
        return value


def build_notifiers(entries: list[dict], alerting: AlertingConfig) -> list[Notifier]:
    from .console import ConsoleNotifier
    from .discord import DiscordNotifier
    from .email_smtp import EmailNotifier
    from .slack import SlackNotifier
    from .telegram import TelegramNotifier
    from .webhook import WebhookNotifier

    registry = {
        cls.type_name: cls
        for cls in (
            ConsoleNotifier,
            DiscordNotifier,
            SlackNotifier,
            TelegramNotifier,
            EmailNotifier,
            WebhookNotifier,
        )
    }

    built: list[Notifier] = []
    for entry in entries:
        if not entry.get("enabled", True):
            continue
        kind = str(entry.get("type", "")).lower()
        if kind not in registry:
            raise ValueError(
                f"未知の通知タイプ '{kind}'。使えるのは: {', '.join(sorted(registry))}"
            )
        built.append(registry[kind](entry, alerting))
    return built
