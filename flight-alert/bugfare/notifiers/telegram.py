"""Telegram Bot で送る。

BotFather でボットを作って chat_id を調べるだけで使えて、
プッシュ通知が速い。
"""

from __future__ import annotations

import html
from typing import Sequence

from ..http import request_json
from ..models import Alert
from .base import Notifier, alert_body_lines, alert_title, skyscanner_link

MAX_MESSAGE = 4000


class TelegramNotifier(Notifier):
    type_name = "telegram"

    def send(self, alerts: Sequence[Alert]) -> None:
        if not alerts:
            return
        token = self.require("bot_token")
        chat_id = self.require("chat_id")
        endpoint = f"https://api.telegram.org/bot{token}/sendMessage"

        for alert in alerts:
            link = skyscanner_link(alert, self.alerting)
            body = html.escape("\n".join(alert_body_lines(alert, self.alerting)))
            text = f"🚨 <b>{html.escape(alert_title(alert))}</b>\n{body}"
            request_json(
                endpoint,
                method="POST",
                json_body={
                    "chat_id": chat_id,
                    "text": text[:MAX_MESSAGE],
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                    "reply_markup": {
                        "inline_keyboard": [
                            [{"text": "Skyscannerで開く", "url": link}]
                        ]
                    },
                },
            )
