import unittest
from unittest import mock

from bugfare.notifiers.discord import DiscordNotifier, MAX_EMBEDS

from tests.helpers import make_config
from tests.test_email import make_alert


class DiscordCountTest(unittest.TestCase):
    def notifier(self):
        return DiscordNotifier(
            {"type": "discord", "webhook_url": "https://example.invalid/hook"},
            make_config().alerting,
        )

    def payload(self, alerts):
        with mock.patch("bugfare.notifiers.discord.request_json") as post:
            self.notifier().send(alerts)
        return post.call_args.kwargs["json_body"]

    def test_headline_count_matches_what_is_shown(self):
        alerts = [make_alert(30_000 + i, "LAX", score=i / 100) for i in range(MAX_EMBEDS + 5)]
        payload = self.payload(alerts)
        self.assertEqual(len(payload["embeds"]), MAX_EMBEDS)
        self.assertIn(f"{MAX_EMBEDS} 件見つけました", payload["content"])
        self.assertIn("ほかに 5 件", payload["content"])

    def test_no_extra_note_when_everything_fits(self):
        payload = self.payload([make_alert(30_000), make_alert(20_000, "ICN")])
        self.assertEqual(len(payload["embeds"]), 2)
        self.assertEqual(payload["content"], "羽田・成田発で安値を 2 件見つけました")

    def test_most_extreme_alerts_survive_the_cut(self):
        alerts = [make_alert(30_000 + i, "LAX", score=i / 100) for i in range(MAX_EMBEDS + 5)]
        titles = [e["title"] for e in self.payload(alerts)["embeds"]]
        # score が最大（i=14）の便が先頭に残る
        self.assertIn("¥30,014", titles[0])


if __name__ == "__main__":
    unittest.main()
