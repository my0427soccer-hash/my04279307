import unittest
from unittest import mock

from bugfare.models import Alert, Baseline
from bugfare.notifiers.email_smtp import EmailNotifier

from .helpers import make_config, make_offer


def make_alert(price: int, destination: str = "LAX") -> Alert:
    offer = make_offer(price, destination=destination)
    return Alert(
        offer=offer,
        reasons=["absolute"],
        messages=["通知ラインを下回りました"],
        baseline=Baseline(offer.route_key, 20, price * 3, price * 2, 5000.0),
        discount=0.66,
        score=0.66,
    )


class EmailNotifierTest(unittest.TestCase):
    def notifier(self, **settings):
        base = {
            "type": "email",
            "host": "smtp.gmail.com",
            "username": "me@example.com",
            "password": "app-password",
        }
        base.update(settings)
        return EmailNotifier(base, make_config().alerting)

    # ---------------------------------------------------------------- 宛先

    def test_defaults_to_sending_to_yourself(self):
        self.assertEqual(self.notifier().recipients("me@example.com"), ["me@example.com"])

    def test_empty_env_placeholder_falls_back_to_yourself(self):
        """"${ALERT_EMAIL_TO}" 未設定は空文字になる。それを宛先にしてはいけない。"""
        notifier = self.notifier(to=[""])
        self.assertEqual(notifier.recipients("me@example.com"), ["me@example.com"])

    def test_accepts_a_bare_string(self):
        notifier = self.notifier(to="phone@example.jp")
        self.assertEqual(notifier.recipients("me@example.com"), ["phone@example.jp"])

    def test_accepts_several_addresses(self):
        notifier = self.notifier(to=["a@example.com", " b@example.com "])
        self.assertEqual(
            notifier.recipients("me@example.com"), ["a@example.com", "b@example.com"]
        )

    # ---------------------------------------------------------------- 本文

    def test_subject_names_the_cheapest_route(self):
        message = self.notifier().build_message([make_alert(39_800)], "me@example.com")
        self.assertEqual(message["Subject"], "[バグ価格] HND→LAX ¥39,800")

    def test_subject_counts_the_rest(self):
        alerts = [make_alert(39_800), make_alert(12_000, "ICN"), make_alert(50_000, "SFO")]
        message = self.notifier().build_message(alerts, "me@example.com")
        self.assertEqual(message["Subject"], "[バグ価格] HND→ICN ¥12,000 他2件")

    def test_body_carries_the_skyscanner_link(self):
        message = self.notifier().build_message([make_alert(39_800)], "me@example.com")
        body = message.get_content()
        self.assertIn("skyscanner.jp/transport/flights/hnd/lax/", body)
        self.assertIn("¥39,800", body)

    def test_from_defaults_to_the_account(self):
        message = self.notifier().build_message([make_alert(39_800)], "me@example.com")
        self.assertEqual(message["From"], "me@example.com")

    def test_from_can_be_overridden(self):
        notifier = self.notifier(**{"from": "alerts@example.com"})
        message = notifier.build_message([make_alert(39_800)], "me@example.com")
        self.assertEqual(message["From"], "alerts@example.com")

    # ---------------------------------------------------------------- 設定漏れ

    def test_missing_password_is_reported_clearly(self):
        notifier = self.notifier(password="")
        with self.assertRaises(ValueError) as ctx:
            notifier.send([make_alert(39_800)])
        self.assertIn("password", str(ctx.exception))

    def test_no_alerts_means_no_connection_attempt(self):
        # host が不正でも、送るものが無ければ SMTP に触らない
        self.notifier(host="invalid.invalid").send([])

    # ---------------------------------------------------------------- 送信経路

    def test_port_587_uses_starttls_then_logs_in(self):
        with mock.patch("smtplib.SMTP") as smtp_cls:
            smtp = smtp_cls.return_value.__enter__.return_value
            self.notifier(port=587).send([make_alert(39_800)])

        smtp_cls.assert_called_once_with("smtp.gmail.com", 587, timeout=30)
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with("me@example.com", "app-password")
        smtp.send_message.assert_called_once()

    def test_port_465_uses_ssl_without_starttls(self):
        with mock.patch("smtplib.SMTP_SSL") as smtp_cls:
            smtp = smtp_cls.return_value.__enter__.return_value
            self.notifier(host="smtp.mail.yahoo.co.jp", port=465).send([make_alert(39_800)])

        smtp_cls.assert_called_once_with("smtp.mail.yahoo.co.jp", 465, timeout=30)
        smtp.starttls.assert_not_called()
        smtp.login.assert_called_once()
        smtp.send_message.assert_called_once()

    def test_the_sent_message_is_the_one_we_built(self):
        with mock.patch("smtplib.SMTP") as smtp_cls:
            smtp = smtp_cls.return_value.__enter__.return_value
            self.notifier().send([make_alert(39_800)])

        sent = smtp.send_message.call_args.args[0]
        self.assertEqual(sent["To"], "me@example.com")
        self.assertIn("¥39,800", sent["Subject"])
        self.assertIn("skyscanner.jp", sent.get_content())


if __name__ == "__main__":
    unittest.main()
