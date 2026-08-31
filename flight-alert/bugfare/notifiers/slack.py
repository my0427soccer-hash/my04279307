"""Slack の Incoming Webhook に送る。"""

from __future__ import annotations

from typing import Sequence

from ..http import request_json
from ..models import Alert
from .base import Notifier, alert_body_lines, alert_title, skyscanner_link


class SlackNotifier(Notifier):
    type_name = "slack"

    def send(self, alerts: Sequence[Alert]) -> None:
        if not alerts:
            return
        url = self.require("webhook_url")
        blocks: list[dict] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🚨 バグ価格の可能性 {len(alerts)}件",
                    "emoji": True,
                },
            }
        ]
        for alert in alerts:
            body = "\n".join(alert_body_lines(alert, self.alerting))
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*<{skyscanner_link(alert, self.alerting)}|{alert_title(alert)}>*\n{body}"[:2900],
                    },
                }
            )
            blocks.append({"type": "divider"})
        request_json(
            url,
            method="POST",
            json_body={"text": f"バグ価格の可能性 {len(alerts)}件", "blocks": blocks},
        )
