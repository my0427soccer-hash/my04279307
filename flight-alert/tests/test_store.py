import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from bugfare.store import Store, _percentile

from .helpers import make_offer


class StoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self._tmp.name) / "test.sqlite3")

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_keeps_only_the_cheapest_price_of_the_day(self):
        today = date.today()
        self.store.record_offers([make_offer(120_000)], observed_date=today)
        self.store.record_offers([make_offer(90_000)], observed_date=today)
        self.store.record_offers([make_offer(150_000)], observed_date=today)

        rows = self.store.history(make_offer(0).route_key)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["price"], 90_000)

    def test_baseline_excludes_today(self):
        """当日の値がベースラインに入ると、バグ価格が自分で相場を下げてしまう。"""
        route = make_offer(0).route_key
        today = date.today()
        for i in range(1, 11):
            self.store.record_offers([make_offer(100_000)], observed_date=today - timedelta(days=i))
        self.store.record_offers([make_offer(10_000)], observed_date=today)

        baseline = self.store.baseline(route, lookback_days=60)
        self.assertEqual(baseline.samples, 10)
        self.assertEqual(baseline.median, 100_000)

    def test_baseline_ignores_data_outside_lookback(self):
        route = make_offer(0).route_key
        today = date.today()
        for i in range(1, 6):
            self.store.record_offers([make_offer(100_000)], observed_date=today - timedelta(days=i))
        for i in range(40, 45):
            self.store.record_offers([make_offer(500_000)], observed_date=today - timedelta(days=i))

        baseline = self.store.baseline(route, lookback_days=30)
        self.assertEqual(baseline.samples, 5)
        self.assertEqual(baseline.median, 100_000)

    def test_baseline_without_history(self):
        baseline = self.store.baseline("HND-XXX:round:2030-01", lookback_days=60)
        self.assertEqual(baseline.samples, 0)
        self.assertIsNone(baseline.median)

    def test_cooldown_blocks_repeat_alerts(self):
        offer = make_offer(40_000)
        fingerprint = offer.fingerprint()
        self.assertFalse(self.store.was_alerted(fingerprint, 12))

        self.store.mark_alerted(fingerprint, offer.route_key, offer.price_jpy, offer.describe())
        self.assertTrue(self.store.was_alerted(fingerprint, 12))
        self.assertFalse(self.store.was_alerted(fingerprint, 0))

    def test_prune_drops_old_rows(self):
        today = date.today()
        self.store.record_offers([make_offer(100_000)], observed_date=today - timedelta(days=400))
        self.store.record_offers([make_offer(100_000)], observed_date=today - timedelta(days=2))
        self.assertEqual(self.store.prune(keep_days=180), 1)
        self.assertEqual(len(self.store.history(make_offer(0).route_key)), 1)


class PercentileTest(unittest.TestCase):
    def test_interpolates(self):
        self.assertEqual(_percentile([10, 20, 30, 40], 50), 25.0)
        self.assertEqual(_percentile([10], 25), 10.0)
        self.assertEqual(_percentile([10, 20], 0), 10.0)
        self.assertEqual(_percentile([10, 20], 100), 20.0)


if __name__ == "__main__":
    unittest.main()
