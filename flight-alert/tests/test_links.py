import unittest
from datetime import date

from bugfare.links import google_flights_url, skyscanner_url


class SkyscannerUrlTest(unittest.TestCase):
    def test_round_trip_has_both_dates_in_yymmdd(self):
        url = skyscanner_url("HND", "LAX", date(2026, 4, 15), date(2026, 4, 22))
        self.assertIn("/flights/hnd/lax/260415/260422/", url)
        self.assertIn("rtn=1", url)
        self.assertIn("currency=JPY", url)

    def test_one_way_omits_return_date(self):
        url = skyscanner_url("NRT", "SIN", date(2026, 12, 1))
        self.assertIn("/flights/nrt/sin/261201/?", url)
        self.assertIn("rtn=0", url)

    def test_options_are_reflected(self):
        url = skyscanner_url(
            "HND", "LHR", date(2027, 1, 5), adults=2, cabin_class="business", direct_only=True
        )
        self.assertIn("adultsv2=2", url)
        self.assertIn("cabinclass=business", url)
        self.assertIn("preferdirects=true", url)

    def test_google_flights_includes_both_dates(self):
        url = google_flights_url("HND", "LAX", date(2026, 4, 15), date(2026, 4, 22))
        self.assertIn("2026-04-15", url)
        self.assertIn("2026-04-22", url)


if __name__ == "__main__":
    unittest.main()
