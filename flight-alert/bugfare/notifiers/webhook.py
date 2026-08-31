"""任意の URL に JSON を POST する。

IFTTT や自作のサーバーなど、上記以外へ流したいとき用の受け皿。
"""

from __future__ import annotations

from typing import Sequence

from ..http import request_json
from ..models import Alert
from .base import Notifier, alert_title, skyscanner_link


class WebhookNotifier(Notifier):
    type_name = "webhook"

    def send(self, alerts: Sequence[Alert]) -> None:
        if not alerts:
            return
        url = self.require("url")
        payload = {
            "count": len(alerts),
            "alerts": [
                {
                    "title": alert_title(alert),
                    "origin": alert.offer.origin,
                    "destination": alert.offer.destination,
                    "depart_date": alert.offer.depart_date.isoformat(),
                    "return_date": (
                        alert.offer.return_date.isoformat() if alert.offer.return_date else None
                    ),
                    "price_jpy": alert.offer.price_jpy,
                    "airline": alert.offer.airline,
                    "reasons": alert.reasons,
                    "messages": alert.messages,
                    "discount": alert.discount,
                    "baseline_median": alert.baseline.median if alert.baseline else None,
                    "skyscanner_url": skyscanner_link(alert, self.alerting),
                }
                for alert in alerts
            ],
        }
        headers = self.settings.get("headers") or {}
        request_json(url, method="POST", json_body=payload, headers=headers)
