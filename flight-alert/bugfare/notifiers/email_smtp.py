"""メールで送る。

キャリアメール宛にすれば、アプリを入れなくても着信音で気づける。
Gmail を使う場合は2段階認証を有効にしたうえでアプリパスワードを発行し、
それを password に入れる。
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Sequence

from ..models import Alert
from .base import Notifier, plain_text


class EmailNotifier(Notifier):
    type_name = "email"

    def send(self, alerts: Sequence[Alert]) -> None:
        if not alerts:
            return

        host = self.require("host")
        port = int(self.settings.get("port", 587))
        username = self.require("username")
        password = self.require("password")
        to_addrs = self.settings.get("to") or [username]
        if isinstance(to_addrs, str):
            to_addrs = [to_addrs]

        cheapest = min(alerts, key=lambda a: a.offer.price_jpy).offer
        message = EmailMessage()
        message["Subject"] = (
            f"[バグ価格] {cheapest.origin}→{cheapest.destination} ¥{cheapest.price_jpy:,} 他{len(alerts) - 1}件"
            if len(alerts) > 1
            else f"[バグ価格] {cheapest.origin}→{cheapest.destination} ¥{cheapest.price_jpy:,}"
        )
        message["From"] = self.settings.get("from") or username
        message["To"] = ", ".join(to_addrs)
        message.set_content(plain_text(alerts, self.alerting))

        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
                smtp.login(username, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.starttls()
                smtp.login(username, password)
                smtp.send_message(message)
