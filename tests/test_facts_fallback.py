from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class FactsFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def test_reviewed_location_facts_use_web_evidence_when_ai_fails(self) -> None:
        import server

        candidates = [
            {
                "title": "History",
                "text": "Paisley Abbey was founded in the 12th century and remains one of the town's best-known landmarks.",
                "theme": "history",
                "sourceName": "Wikipedia",
                "sourceUrl": "https://example.com/abbey",
                "confidence": "medium",
            },
            {
                "title": "Industry",
                "text": "Paisley gave its name to the Paisley pattern through the town's textile industry.",
                "theme": "industry",
                "sourceName": "Wikipedia",
                "sourceUrl": "https://example.com/pattern",
                "confidence": "medium",
            },
        ]

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name) / "runtime-db"
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()
            rotation_key = server.history_fact_rotation_key("Paisley, Renfrewshire", "en")
            evidence = [
                {
                    "title": "Paisley visit guide",
                    "sourceName": "paisley.is",
                    "sourceUrl": "https://paisley.is/visit/paisley/",
                    "snippet": "Paisley is the place that made the iconic world-renowned Paisley Pattern.",
                    "excerpt": (
                        "Paisley is the place that made the iconic world-renowned Paisley Pattern. "
                        "The first Stewart king, Robert II, grandson of Robert the Bruce, was born here in 1316."
                    ),
                },
                {
                    "title": "Paisley Abbey history",
                    "sourceName": "paisleyabbey.org.uk",
                    "sourceUrl": "https://paisleyabbey.org.uk/history",
                    "snippet": "Paisley Abbey traces its origins to the 12th century.",
                    "excerpt": (
                        "Paisley Abbey traces its origins to the 12th century and remains central to the town's story."
                    ),
                },
            ]

            with (
                patch("server.FACTS_GEMINI_API_KEY", "test-key"),
                patch("server.search_web_fact_evidence", return_value=evidence),
                patch("server.facts_ai_json_response", side_effect=RuntimeError("Gemini request failed with HTTP 429.")),
            ):
                facts = server.reviewed_location_facts(
                    rotation_key,
                    "Paisley, Renfrewshire",
                    candidates,
                    limit=2,
                    recent_texts=["Paisley Abbey was founded in the 12th century and remains one of the town's best-known landmarks."],
                )

            self.assertEqual(len(facts), 2)
            self.assertTrue(all(fact["sourceName"] != "Wikipedia" for fact in facts))
            self.assertTrue(all("wikipedia.org" not in str(fact["sourceUrl"]) for fact in facts))
            self.assertTrue(any("Paisley Abbey traces its origins" in fact["text"] for fact in facts))
            self.assertTrue(any("Robert II" in fact["text"] for fact in facts))
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_facts_compatible_json_response_handles_content_parts(self) -> None:
        import server

        class FakeResponse:
            def __init__(self, payload: dict[str, object]) -> None:
                self._payload = payload

            def read(self) -> bytes:
                return json.dumps(self._payload).encode("utf-8")

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, exc_type, exc, tb) -> bool:
                return False

        payload = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {
                                "type": "text",
                                "text": "{\"facts\":[{\"title\":\"Paisley Abbey\",\"text\":\"Paisley Abbey is a medieval landmark.\"}]}\nExtra note",
                            }
                        ]
                    }
                }
            ]
        }

        with patch("server.urlopen", return_value=FakeResponse(payload)):
            parsed = server.facts_compatible_json_response(
                provider_name="openrouter",
                base_url="https://openrouter.ai/api/v1",
                api_key="test-key",
                model="openrouter/free",
                prompt="Prompt",
            )

        self.assertEqual(parsed["facts"][0]["title"], "Paisley Abbey")
        self.assertEqual(parsed["facts"][0]["text"], "Paisley Abbey is a medieval landmark.")


if __name__ == "__main__":
    unittest.main()
