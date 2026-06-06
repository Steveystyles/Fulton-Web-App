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

    def test_fetch_web_page_excerpt_discards_page_chrome(self) -> None:
        import server

        html = """
        <html>
          <head>
            <title>Paisley: The story of a classic bohemian print</title>
            <meta property="og:description" content="Skip to content British Broadcasting Corporation Home" />
          </head>
          <body>
            <nav>Skip to content British Broadcasting Corporation Home</nav>
            <p>Paisley gave its name to the paisley pattern through the town's textile industry.</p>
            <p>Robert II, the first Stewart king of Scotland, was born in Paisley in 1316.</p>
          </body>
        </html>
        """

        with patch("server.fetch_text_url", return_value=html):
            excerpt = server.fetch_web_page_excerpt("https://www.bbc.com/travel/article/paisley-pattern")

        self.assertIn("Paisley gave its name to the paisley pattern", excerpt)
        self.assertIn("Robert II", excerpt)
        self.assertNotIn("Skip to content", excerpt)
        self.assertNotIn("British Broadcasting Corporation", excerpt)

    def test_web_evidence_fallback_facts_uses_specific_titles(self) -> None:
        import server

        evidence = [
            {
                "title": "Paisley travel guide",
                "sourceName": "choosewhere.com",
                "sourceUrl": "https://www.choosewhere.com/paisley",
                "snippet": "With its magnificent abbey and vibrant cultural scene, Paisley offers visitors a rewarding stop.",
                "excerpt": (
                    "With its magnificent abbey, impressive Victorian architecture, and vibrant cultural "
                    "scene, Paisley offers visitors a rewarding stop in the west of Scotland."
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
            {
                "title": "Paisley visit guide",
                "sourceName": "paisley.is",
                "sourceUrl": "https://paisley.is/visit/paisley/",
                "snippet": "Robert II, the first Stewart king of Scotland, was born here in 1316.",
                "excerpt": "Robert II, the first Stewart king of Scotland, was born in Paisley in 1316.",
            },
        ]

        facts = server.web_evidence_fallback_facts(
            "Paisley, Renfrewshire",
            evidence,
            limit=2,
            recent_texts=[],
        )

        self.assertEqual(len(facts), 2)
        self.assertTrue(all(fact["title"].casefold() not in server.FACT_GENERIC_FACT_TITLES for fact in facts))
        self.assertTrue(all(fact["sourceName"] != "choosewhere.com" for fact in facts))
        self.assertIn("Paisley Abbey", {fact["title"] for fact in facts})
        self.assertTrue(any("Robert II" in fact["title"] or "Robert II" in fact["text"] for fact in facts))

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

    def test_facts_ai_request_timeout_caps_timeout_to_remaining_budget(self) -> None:
        import server

        with (
            patch("server.FACTS_AI_TIMEOUT_SEC", 90),
            patch("server.time.monotonic", return_value=100.0),
        ):
            timeout = server.facts_ai_request_timeout(104.5)

        self.assertEqual(timeout, 4.5)

    def test_reviewed_location_facts_keep_generated_facts_if_critic_fails(self) -> None:
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
        evidence = [
            {
                "title": "Paisley Abbey history",
                "sourceName": "paisleyabbey.org.uk",
                "sourceUrl": "https://paisleyabbey.org.uk/history",
                "snippet": "Paisley Abbey traces its origins to the 12th century.",
                "excerpt": "Paisley Abbey traces its origins to the 12th century and remains central to the town's story.",
            },
            {
                "title": "Paisley visit guide",
                "sourceName": "paisley.is",
                "sourceUrl": "https://paisley.is/visit/paisley/",
                "snippet": "Paisley is the place that made the iconic world-renowned Paisley Pattern.",
                "excerpt": "The first Stewart king, Robert II, grandson of Robert the Bruce, was born here in 1316.",
            },
        ]
        selection = {
            "facts": [
                {
                    "title": "Royal Birthplace",
                    "text": "Robert II, the first Stewart king of Scotland, was born in Paisley in 1316.",
                    "theme": "people",
                    "sourceEvidenceIndex": 1,
                },
                {
                    "title": "Abbey origins",
                    "text": "Paisley Abbey traces its origins to the 12th century and remains central to the town's story.",
                    "theme": "history",
                    "sourceEvidenceIndex": 0,
                },
            ]
        }

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name) / "runtime-db"
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()
            rotation_key = server.history_fact_rotation_key("Paisley, Renfrewshire", "en")

            with (
                patch("server.FACTS_GEMINI_API_KEY", "test-key"),
                patch("server.search_web_fact_evidence", return_value=evidence),
                patch(
                    "server.facts_ai_json_response",
                    side_effect=[selection, RuntimeError("Facts AI budget exceeded.")],
                ),
            ):
                facts = server.reviewed_location_facts(
                    rotation_key,
                    "Paisley, Renfrewshire",
                    candidates,
                    limit=2,
                    recent_texts=[],
                )

            self.assertEqual([fact["title"] for fact in facts], ["Royal Birthplace", "Abbey origins"])
            self.assertEqual(facts[0]["sourceName"], "paisley.is")
            self.assertEqual(facts[1]["sourceName"], "paisleyabbey.org.uk")
            self.assertIn("critique", facts[0])
            self.assertIn("critique", facts[1])
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path

    def test_reviewed_location_facts_normalizes_single_fact_payload_and_tops_up(self) -> None:
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
        evidence = [
            {
                "title": "Paisley Abbey history",
                "sourceName": "paisleyabbey.org.uk",
                "sourceUrl": "https://paisleyabbey.org.uk/history",
                "snippet": "Paisley Abbey traces its origins to the 12th century.",
                "excerpt": "Paisley Abbey traces its origins to the 12th century and remains central to the town's story.",
            },
            {
                "title": "Paisley visit guide",
                "sourceName": "paisley.is",
                "sourceUrl": "https://paisley.is/visit/paisley/",
                "snippet": "Robert II, the first Stewart king of Scotland, was born here in 1316.",
                "excerpt": "Robert II, the first Stewart king of Scotland, was born in Paisley in 1316.",
            },
        ]
        selection = {
            "fact": "Robert II, the first Stewart king of Scotland, was born in Paisley in 1316.",
            "sourceEvidenceIndex": 1,
        }
        top_up = {
            "title": "Abbey origins",
            "text": "Paisley Abbey traces its origins to the 12th century and remains central to the town's story.",
            "theme": "history",
            "sourceEvidenceIndex": 0,
        }
        critique = {
            "overallPassed": True,
            "notes": "Both facts are specific and source-backed.",
            "facts": [
                {
                    "factIndex": 0,
                    "passed": True,
                    "relevance": 9,
                    "interestingness": 8,
                    "placeSpecificity": 9,
                    "summary": "It ties Paisley to a named royal birth.",
                },
                {
                    "factIndex": 1,
                    "passed": True,
                    "relevance": 9,
                    "interestingness": 7,
                    "placeSpecificity": 9,
                    "summary": "It anchors the town to a major medieval landmark.",
                },
            ],
        }

        original_data_dir = server.DATA_DIR
        original_db_path = server.DB_PATH
        try:
            data_dir = Path(self.temp_dir.name) / "runtime-db"
            server.DATA_DIR = data_dir
            server.DB_PATH = data_dir / "fultons.db"
            server.initialize_database()
            rotation_key = server.history_fact_rotation_key("Paisley, Renfrewshire", "en")

            with (
                patch("server.FACTS_GEMINI_API_KEY", "test-key"),
                patch("server.search_web_fact_evidence", return_value=evidence),
                patch(
                    "server.facts_ai_json_response",
                    side_effect=[selection, top_up, critique],
                ),
            ):
                facts = server.reviewed_location_facts(
                    rotation_key,
                    "Paisley, Renfrewshire",
                    candidates,
                    limit=2,
                    recent_texts=[],
                )

            self.assertEqual(len(facts), 2)
            self.assertTrue(any("Robert II" in fact["text"] for fact in facts))
            self.assertTrue(any("Paisley Abbey traces its origins" in fact["text"] for fact in facts))
            self.assertEqual({fact["sourceName"] for fact in facts}, {"paisley.is", "paisleyabbey.org.uk"})
        finally:
            server.DATA_DIR = original_data_dir
            server.DB_PATH = original_db_path


if __name__ == "__main__":
    unittest.main()
