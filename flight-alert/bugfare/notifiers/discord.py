"""Discord の Webhook に送る。

スマホの Discord アプリが即座にプッシュしてくれるので、
数分が勝負のバグ価格とは相性がいい。
"""

from __future__ import annotations

from typing import Sequence

from ..http import request_json
from ..models import Alert
from .base import Notifier, alert_body_lines, alert_title, skyscanner_link

MAX_EMBEDS = 10


class DiscordNotifier(Notifier):
    type_name = "discord"

    def send(self, alerts: Sequence[Alert]) -> None:
        if not alerts:
            return
        url = self.require("webhook_url")
        embeds = []
        for alert in alerts[:MAX_EMBEDS]:
            embeds.append(
                {
                    "title": "🚨 " + alert_title(alert),
                    "url": skyscanner_link(alert, self.alerting),
                    "description": "\n".join(alert_body_lines(alert, self.alerting))[:4000],
                    "color": 0xE03131 if alert.score >= 0.6 else 0xF08C00,
                }
            )
        payload = {
            "username": self.settings.get("username", "バグ価格アラート"),
            "content": f"羽田・成田発で安値を {len(alerts)} 件見つけました",
            "embeds": embeds,
        }
        request_json(url, method="POST", json_body=payload)
