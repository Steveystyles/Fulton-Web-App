from __future__ import annotations

import unittest
from unittest.mock import patch


class HistoryEventCategorisationTests(unittest.TestCase):
    def test_history_events_do_not_classify_military_league_as_sport(self) -> None:
        import server

        source_payload = {
            "data": {
                "Events": [
                    {
                        "year": "1513",
                        "text": "War of the League of Cambrai: In the Battle of Novara, Swiss troops defeat the French under Louis II de la Trémoille.",
                        "links": [
                            {"title": "War of the League of Cambrai", "link": "https://example.com/war"},
                            {"title": "Battle of Novara (1513)", "link": "https://example.com/novara"},
                        ],
                    },
                    {
                        "year": "2021",
                        "text": "A landmark science mission launched.",
                        "links": [],
                    },
                ],
                "Births": [],
            }
        }

        with patch("server.fetch_json_url", return_value=source_payload):
            events = server.fetch_history_events(6, 6, 5)

        novara_event = next(
            event for event in events if "Battle of Novara" in event["text"]
        )
        self.assertEqual(novara_event["category"], "history")
        self.assertNotIn("sport", {event["category"] for event in events})

    def test_history_events_still_keep_real_sport_highlight(self) -> None:
        import server

        source_payload = {
            "data": {
                "Events": [
                    {
                        "year": "1513",
                        "text": "War of the League of Cambrai: In the Battle of Novara, Swiss troops defeat the French under Louis II de la Trémoille.",
                        "links": [
                            {"title": "War of the League of Cambrai", "link": "https://example.com/war"},
                            {"title": "Battle of Novara (1513)", "link": "https://example.com/novara"},
                        ],
                    },
                    {
                        "year": "1967",
                        "text": "A football club won a European cup.",
                        "links": [],
                    },
                    {
                        "year": "2021",
                        "text": "A landmark science mission launched.",
                        "links": [],
                    },
                ],
                "Births": [],
            }
        }

        with patch("server.fetch_json_url", return_value=source_payload):
            events = server.fetch_history_events(6, 6, 5)

        sport_events = [event for event in events if event["category"] == "sport"]
        self.assertEqual(len(sport_events), 1)
        self.assertIn("football club won a European cup", sport_events[0]["text"])
        novara_event = next(
            event for event in events if "Battle of Novara" in event["text"]
        )
        self.assertEqual(novara_event["category"], "history")


if __name__ == "__main__":
    unittest.main()
