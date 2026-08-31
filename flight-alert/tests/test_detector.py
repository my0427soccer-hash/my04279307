import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from bugfare.detector import Detector
from bugfare.store import Store

from .helpers import make_config, make_offer


class DetectorTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self._tmp.name) / "test.sqlite3")
        self.config = make_config()

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def seed(self, price: int, days: int = 20, **offer_kwargs):
        today = date.today()
        for i in range(1, days + 1):
            self.store.record_offers(
                [make_offer(price, **offer_kwargs)], observed_date=today - timedelta(days=i)
            )

    def detector(self, **config_overrides):
        config = make_config(**config_overrides) if config_overrides else self.config
        return Detector(config, self.store)

    # ------------------------------------------------------------ 各ルール

    def test_absolute_rule_fires_without_any_history(self):
        """履歴ゼロの初日から効くのが絶対額ルールの役割。"""
        alert = self.detector().evaluate(make_offer(40_000))
        self.assertIsNotNone(alert)
        self.assertIn("absolute", alert.reasons)

    def test_price_above_threshold_without_history_is_silent(self):
        self.assertIsNone(self.detector().evaluate(make_offer(150_000)))

    def test_baseline_rule_fires_at_half_the_going_rate(self):
        self.seed(200_000)
        alert = self.detector().evaluate(make_offer(95_000))
        self.assertIsNotNone(alert)
        self.assertIn("baseline", alert.reasons)
        self.assertAlmostEqual(alert.discount, 1 - 95_000 / 200_000, places=4)

    def test_baseline_rule_ignores_ordinary_sale(self):
        """2割引程度のセールで起こされたくない。"""
        self.seed(200_000)
        self.assertIsNone(self.detector().evaluate(make_offer(160_000)))

    def test_baseline_needs_enough_samples(self):
        self.seed(200_000, days=3)   # min_samples は 5
        self.assertIsNone(self.detector().evaluate(make_offer(95_000)))

    def test_outlier_rule_fires_on_a_stable_route(self):
        """値動きがほぼ無い路線での急落は、割引率が浅くても異常。"""
        today = date.today()
        for i in range(1, 21):
            price = 200_000 + (i % 3) * 500   # ほとんど動かない
            self.store.record_offers([make_offer(price)], observed_date=today - timedelta(days=i))
        alert = self.detector(detection={"min_samples": 5, "drop_ratio": 0.3}).evaluate(
            make_offer(130_000)
        )
        self.assertIsNotNone(alert)
        self.assertEqual(alert.reasons, ["outlier"])

    def test_outlier_rule_does_not_fire_on_a_shallow_drop(self):
        today = date.today()
        for i in range(1, 21):
            price = 200_000 + (i % 3) * 500
            self.store.record_offers([make_offer(price)], observed_date=today - timedelta(days=i))
        # 中央値の 70% より上の下落は外れ値と呼ばない
        self.assertIsNone(
            self.detector(detection={"min_samples": 5, "drop_ratio": 0.3}).evaluate(
                make_offer(150_000)
            )
        )

    def test_target_can_override_drop_ratio(self):
        self.seed(200_000)
        config_targets = [
            {"name": "北米", "destinations": ["LAX"], "drop_ratio": 0.8},
        ]
        alert = Detector(make_config(targets=config_targets), self.store).evaluate(
            make_offer(150_000)
        )
        self.assertIsNotNone(alert)
        self.assertIn("baseline", alert.reasons)

    # ------------------------------------------------------------ 足切り

    def test_unwatched_destination_is_ignored(self):
        self.assertIsNone(self.detector().evaluate(make_offer(1_000, destination="CDG")))

    def test_absurdly_low_price_is_treated_as_bad_data(self):
        self.assertIsNone(self.detector().evaluate(make_offer(100)))

    def test_one_way_uses_its_own_threshold(self):
        detector = self.detector()
        self.assertIsNotNone(detector.evaluate(make_offer(30_000, nights=None)))
        self.assertIsNone(detector.evaluate(make_offer(40_000, nights=None)))

    # ------------------------------------------------------------ まとめ処理

    def test_select_keeps_only_the_cheapest_per_route(self):
        alerts = self.detector().select(
            [make_offer(50_000), make_offer(30_000), make_offer(45_000)]
        )
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].offer.price_jpy, 30_000)

    def test_select_sorts_by_how_extreme_the_price_is(self):
        alerts = self.detector().select(
            [make_offer(55_000, destination="LAX"), make_offer(12_000, destination="ICN")]
        )
        self.assertEqual([a.offer.destination for a in alerts], ["ICN", "LAX"])

    def test_select_respects_the_cooldown(self):
        detector = self.detector()
        offer = make_offer(30_000)
        self.assertEqual(len(detector.select([offer])), 1)

        self.store.mark_alerted(offer.fingerprint(), offer.route_key, offer.price_jpy, "")
        self.assertEqual(len(detector.select([offer])), 0)

    def test_cooldown_lets_a_further_drop_through(self):
        """同じ路線でも、さらに安くなったら知りたい。"""
        detector = self.detector()
        first = make_offer(30_000)
        self.store.mark_alerted(first.fingerprint(), first.route_key, first.price_jpy, "")
        self.assertEqual(len(detector.select([make_offer(21_000)])), 1)

    def test_select_caps_the_number_of_alerts(self):
        detector = self.detector(alerting={"max_alerts_per_run": 1})
        alerts = detector.select(
            [make_offer(30_000, destination="LAX"), make_offer(9_000, destination="ICN")]
        )
        self.assertEqual(len(alerts), 1)


if __name__ == "__main__":
    unittest.main()
