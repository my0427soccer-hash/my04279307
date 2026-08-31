import os
import unittest

from bugfare.config import Config, ConfigError

from .helpers import BASE_CONFIG, make_config


class ConfigTest(unittest.TestCase):
    def test_env_placeholders_are_expanded(self):
        os.environ["BUGFARE_TEST_TOKEN"] = "secret-value"
        try:
            cfg = make_config(provider={"name": "travelpayouts", "token": "${BUGFARE_TEST_TOKEN}"})
            self.assertEqual(cfg.provider.token, "secret-value")
        finally:
            del os.environ["BUGFARE_TEST_TOKEN"]

    def test_missing_env_becomes_empty_not_literal(self):
        cfg = make_config(provider={"name": "travelpayouts", "token": "${BUGFARE_NOT_SET_XYZ}"})
        self.assertEqual(cfg.provider.token, "")

    def test_target_lookup_is_case_insensitive(self):
        cfg = make_config()
        self.assertEqual(cfg.target_for("lax").name, "北米")
        self.assertIsNone(cfg.target_for("CDG"))

    def test_threshold_differs_by_trip_type(self):
        target = make_config().target_for("LAX")
        self.assertEqual(target.threshold_for("round"), 60000)
        self.assertEqual(target.threshold_for("oneway"), 35000)

    def test_disabled_targets_are_ignored(self):
        cfg = make_config(
            targets=[
                {"name": "北米", "destinations": ["LAX"], "alert_price": 60000},
                {"name": "欧州", "destinations": ["CDG"], "enabled": False},
            ]
        )
        self.assertEqual([t.name for t in cfg.active_targets], ["北米"])
        self.assertIsNone(cfg.target_for("CDG"))

    def test_typo_in_key_is_rejected(self):
        broken = dict(BASE_CONFIG, detection={"drop_rate": 0.5})
        with self.assertRaises(ConfigError):
            Config.from_dict(broken)

    def test_no_targets_is_rejected(self):
        with self.assertRaises(ConfigError):
            Config.from_dict(dict(BASE_CONFIG, targets=[]))


if __name__ == "__main__":
    unittest.main()
