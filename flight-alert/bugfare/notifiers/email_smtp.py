"""メールで送る。

スマホのメールアプリがそのまま通知してくれるので、追加のアプリを
入れなくても着信に気づける。

Gmail を使う場合は、2段階認証を有効にしたうえで「アプリパスワード」を
発行し、それを password に入れる（普段のログインパスワードでは送れない）。
宛先を省略すると、自分のアドレス宛に送る。
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Sequence

from ..models import Alert
from .base import Notifier, plain_text

DEFAULT_PORT = 587
SSL_PORT = 465


class EmailNotifier(Notifier):
    type_name = "email"

    def recipients(self, username: str) -> list[str]:
        """宛先を決める。未指定・空なら自分宛に送る。

        設定の "${ALERT_EMAIL_TO}" は環境変数が無いと空文字になるため、
        中身が空のものを取り除いてから判断する。
        """
        raw = self.settings.get("to") or []
        if isinstance(raw, str):
            raw = [raw]
        addresses = [str(a).strip() for a in raw if str(a).strip()]
        return addresses or [username]

    @staticmethod
    def ordered(alerts: Sequence[Alert]) -> list[Alert]:
        """本文に並べる順。バグらしさ（相場からの外れ具合）が大きいものを先頭にする。"""
        return sorted(alerts, key=lambda a: a.score, reverse=True)

    def build_message(self, alerts: Sequence[Alert], username: str) -> EmailMessage:
        # 件名は必ず本文の1件目と同じ便を指す。
        # 以前は件名だけ「いちばん安い便」を選んでいたため、本文の先頭
        # （いちばんバグらしい便）と食い違うことがあった。安さの順と
        # 外れ具合の順は一致しない（例: 相場6万円に対する3.2万円は、
        # 相場3万円に対する1.7万円より高いが、より大きく外れている）。
        ordered = self.ordered(alerts)
        lead = ordered[0].offer

        subject = f"[バグ価格] {lead.origin}→{lead.destination} ¥{lead.price_jpy:,}"
        if len(ordered) > 1:
            subject += f" 他{len(ordered) - 1}件"

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.settings.get("from") or username
        message["To"] = ", ".join(self.recipients(username))
        message.set_content(plain_text(ordered, self.alerting))
        return message

    def send(self, alerts: Sequence[Alert]) -> None:
        if not alerts:
            return

        host = self.require("host")
        username = self.require("username")
        password = self.require("password")
        port = int(self.settings.get("port", DEFAULT_PORT))
        message = self.build_message(alerts, username)

        if port == SSL_PORT:
            with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
                smtp.login(username, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.starttls()
                smtp.login(username, password)
                smtp.send_message(message)
