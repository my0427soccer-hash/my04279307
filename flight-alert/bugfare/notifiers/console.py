"""標準出力に出すだけの通知。動作確認とローカル実行用。"""

from __future__ import annotations

from typing import Sequence

from ..models import Alert
from .base import Notifier, plain_text


class ConsoleNotifier(Notifier):
    type_name = "console"

    def send(self, alerts: Sequence[Alert]) -> None:
        if not alerts:
            return
        print("=" * 60)
        print(plain_text(alerts, self.alerting))
        print("=" * 60)
