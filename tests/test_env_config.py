from __future__ import annotations

import unittest
from unittest.mock import patch

import env_config


class EnvironmentConfigTests(unittest.TestCase):
    def test_integer_uses_primary_then_alias_and_enforces_bounds(self) -> None:
        with patch.dict("os.environ", {"LEGACY_LIMIT": "7"}, clear=True):
            self.assertEqual(
                env_config.env_int(
                    "CURRENT_LIMIT",
                    5,
                    minimum=1,
                    maximum=10,
                    aliases=("LEGACY_LIMIT",),
                ),
                7,
            )
        with patch.dict(
            "os.environ",
            {"CURRENT_LIMIT": "8", "LEGACY_LIMIT": "7"},
            clear=True,
        ):
            self.assertEqual(
                env_config.env_int(
                    "CURRENT_LIMIT",
                    5,
                    minimum=1,
                    maximum=10,
                    aliases=("LEGACY_LIMIT",),
                ),
                8,
            )
        for invalid in ("many", "0", "11"):
            with self.subTest(invalid=invalid), patch.dict(
                "os.environ", {"CURRENT_LIMIT": invalid}, clear=True
            ):
                with self.assertRaisesRegex(RuntimeError, "CURRENT_LIMIT"):
                    env_config.env_int(
                        "CURRENT_LIMIT", 5, minimum=1, maximum=10
                    )

    def test_float_rejects_non_finite_and_out_of_range_values(self) -> None:
        for invalid in ("nan", "inf", "-inf", "-0.1", "10.1", "many"):
            with self.subTest(invalid=invalid), patch.dict(
                "os.environ", {"REQUEST_DELAY": invalid}, clear=True
            ):
                with self.assertRaisesRegex(RuntimeError, "REQUEST_DELAY"):
                    env_config.env_float(
                        "REQUEST_DELAY", 1.0, minimum=0.0, maximum=10.0
                    )

    def test_boolean_is_strict(self) -> None:
        for raw_value, expected in (
            ("1", True),
            ("true", True),
            ("YES", True),
            ("off", False),
            ("0", False),
        ):
            with self.subTest(raw_value=raw_value), patch.dict(
                "os.environ", {"FEATURE_FLAG": raw_value}, clear=True
            ):
                self.assertIs(
                    env_config.env_bool("FEATURE_FLAG", False), expected
                )
        with patch.dict("os.environ", {"FEATURE_FLAG": "sometimes"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "FEATURE_FLAG"):
                env_config.env_bool("FEATURE_FLAG", False)

    def test_ip_networks_reject_unsafe_or_invalid_ranges(self) -> None:
        with patch.dict(
            "os.environ",
            {"TRUSTED_PROXIES": "172.18.0.2/16,2001:db8::1/64"},
            clear=True,
        ):
            networks = env_config.env_ip_networks("TRUSTED_PROXIES")
            self.assertEqual([str(network) for network in networks], ["172.18.0.0/16", "2001:db8::/64"])
        for invalid in ("not-a-network", "0.0.0.0/0", "::/0", "224.0.0.0/24"):
            with self.subTest(invalid=invalid), patch.dict(
                "os.environ", {"TRUSTED_PROXIES": invalid}, clear=True
            ):
                with self.assertRaisesRegex(RuntimeError, "TRUSTED_PROXIES"):
                    env_config.env_ip_networks("TRUSTED_PROXIES")


if __name__ == "__main__":
    unittest.main()
