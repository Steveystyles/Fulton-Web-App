from __future__ import annotations

import unittest

from tools.generate_daily_quiz import generation_succeeded


class DailyQuizCliTests(unittest.TestCase):
    def test_preserved_published_quiz_is_not_reported_as_regeneration_success(self) -> None:
        self.assertTrue(generation_succeeded({"status": "published"}))
        self.assertFalse(
            generation_succeeded(
                {"status": "published", "regeneration_failed": True}
            )
        )
        self.assertFalse(
            generation_succeeded(
                {"status": "published", "regeneration_blocked": True}
            )
        )


if __name__ == "__main__":
    unittest.main()
