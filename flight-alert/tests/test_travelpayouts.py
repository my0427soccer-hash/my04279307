import unittest
from datetime import date
from unittest import mock

from bugfare.providers.travelpayouts import TravelpayoutsProvider, _parse_date

from .helpers import make_config


class ParseDateTest(unittest.TestCase):
    def test_accepts_plain_date(self):
        self.assertEqual(_parse_date("2026-04-15"), date(2026, 4, 15))

    def test_accepts_timestamp_with_offset(self):
        self.assertEqual(_parse_date("2026-04-15T10:20:00+09:00"), date(2026, 4, 15))

    def test_accepts_zulu_timestamp(self):
        self.assertEqual(_parse_date("2026-04-15T01:20:00Z"), date(2026, 4, 15))

    def test_rejects_junk(self):
        for value in ("", None, "n/a", 12345):
            self.assertIsNone(_parse_date(value))


class ToOfferTest(unittest.TestCase):
    def setUp(self):
        self.provider = TravelpayoutsProvider(make_config(provider={"name": "travelpayouts"}))

    def row(self, **overrides):
        row = {
            "origin": "HND",
            "destination": "LAX",
            "price": 39800,
            "airline": "JL",
            "transfers": 0,
            "departure_at": "2026-04-15T10:20:00+09:00",
            "return_at": "2026-04-22T12:00:00-07:00",
            "link": "/search/HND1504LAX1",
        }
        row.update(overrides)
        return row

    def test_round_trip_is_parsed(self):
        offer = self.provider._to_offer(self.row(), "HND", "LAX", "round")
        self.assertEqual(offer.price_jpy, 39800)
        self.assertEqual(offer.depart_date, date(2026, 4, 15))
        self.assertEqual(offer.return_date, date(2026, 4, 22))
        self.assertEqual(offer.stay_nights, 7)
        self.assertTrue(offer.booking_link.startswith("https://"))

    def test_one_way_has_no_return_date(self):
        offer = self.provider._to_offer(self.row(return_at=None), "HND", "LAX", "oneway")
        self.assertIsNone(offer.return_date)
        self.assertEqual(offer.trip_type, "oneway")

    def test_round_trip_without_return_date_is_dropped(self):
        self.assertIsNone(self.provider._to_offer(self.row(return_at=None), "HND", "LAX", "round"))

    def test_float_price_is_rounded(self):
        offer = self.provider._to_offer(self.row(price="39800.6"), "HND", "LAX", "round")
        self.assertEqual(offer.price_jpy, 39801)

    def test_bad_rows_are_dropped(self):
        for bad in ({"price": None}, {"price": 0}, {"price": "free"}, {"departure_at": "???"}):
            self.assertIsNone(self.provider._to_offer(self.row(**bad), "HND", "LAX", "round"))

    def test_route_key_groups_by_month_and_trip_type(self):
        offer = self.provider._to_offer(self.row(), "HND", "LAX", "round")
        self.assertEqual(offer.route_key, "HND-LAX:round:2026-04")


if __name__ == "__main__":
    unittest.main()


class RequestBudgetTest(unittest.TestCase):
    """リクエスト上限で打ち切られたときの挙動。"""

    def provider(self, max_requests: int):
        cfg = make_config(
            provider={"name": "travelpayouts", "token": "dummy", "max_requests": max_requests,
                      "request_pause_seconds": 0},
            search={"origins": ["HND", "NRT"], "months_ahead": 2, "trip_types": ["round"]},
        )
        return TravelpayoutsProvider(cfg)

    def test_required_requests_counts_every_combination(self):
        # 出発地2 × 行き先3（LAX/SFO/ICN）× 2か月 × 往復のみ
        self.assertEqual(self.provider(999).required_requests(), 12)

    def test_both_origins_are_covered_when_the_budget_runs_out(self):
        """上限で切れても、羽田だけ見て成田が丸ごと抜けることがあってはならない。"""
        provider = self.provider(6)
        asked: list[tuple[str, str]] = []

        def record(origin, destination, month, trip_type):
            asked.append((origin, destination))
            return []

        with mock.patch.object(provider, "_fetch", side_effect=record):
            list(provider.search())

        self.assertEqual(len(asked), 6)
        origins = {origin for origin, _ in asked}
        self.assertEqual(origins, {"HND", "NRT"})

    def test_nothing_is_skipped_when_the_budget_is_enough(self):
        provider = self.provider(999)
        asked = []

        def record(origin, destination, month, trip_type):
            asked.append((origin, destination))
            return []

        with mock.patch.object(provider, "_fetch", side_effect=record):
            list(provider.search())

        self.assertEqual(len(asked), provider.required_requests())
        self.assertEqual({o for o, _ in asked}, {"HND", "NRT"})
        self.assertEqual({d for _, d in asked}, {"LAX", "SFO", "ICN"})
