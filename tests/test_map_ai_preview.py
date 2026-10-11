import json
from contextlib import closing
from io import BytesIO
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import daily_map_game
from tools import generate_ai_daily_map_round as generator
from tools import preview_ai_map_round as preview


class MapPreviewTests(unittest.TestCase):
    def provider(self, **kwargs):
        with patch.dict(os.environ, {"GEMINI_API_KEY_DEV": "isolated-test-value"}, clear=True):
            return preview.PreviewGeminiProvider.from_preview_env(**kwargs)

    def test_missing_or_reused_credentials_fail_closed(self):
        for env in ({"GEMINI_API_KEY": "production-test-value"},
                    {"GEMINI_API_KEY": "same-test-value", "GEMINI_API_KEY_DEV": "same-test-value"}):
            with self.subTest(env_names=list(env)), patch.dict(os.environ, env, clear=True):
                with self.assertRaises(ValueError):
                    preview.PreviewGeminiProvider.from_preview_env()

    def test_existing_openai_and_fallback_keys_are_not_used(self):
        with patch.dict(os.environ, {
            "GEMINI_API_KEY_DEV": "isolated-test-value",
            "OPENAI_API_KEY": "other-test-value", "AI_FALLBACK_API_KEY": "fallback-test-value",
            "AI_PROVIDER": "openai-compatible", "AI_TRANSIENT_RETRIES": "10",
        }, clear=True):
            provider = preview.PreviewGeminiProvider.from_preview_env()
        self.assertEqual(len(provider.clients), 1)
        config = provider.clients[0].config
        self.assertEqual(config.provider, "gemini")
        self.assertEqual(config.transient_retries, 0)
        self.assertEqual(config.compatible_api_key, "")
        self.assertEqual(config.fallback_compatible_api_key, "")

    def test_budget_counts_grounded_critic_and_generation_calls(self):
        provider = self.provider(max_requests=2)
        with patch.object(provider, "request_json", return_value={}) as request:
            provider.call_with_fallback(model_attr="generator_model", prompt="fixture", schema={})
            provider.call_with_fallback(model_attr="critic_model", prompt="fixture", schema={}, tools=[{"googleSearch": {}}])
            with self.assertRaisesRegex(RuntimeError, "budget exhausted"):
                provider.call_with_fallback(model_attr="generator_model", prompt="fixture", schema={})
        self.assertEqual(request.call_count, 2)
        self.assertEqual(len(provider.requests), 2)
        self.assertTrue(provider.requests[1]["grounded"])

    def test_provider_failure_halts_without_exporting_error_body(self):
        provider = self.provider()
        with patch.object(provider, "request_json", side_effect=RuntimeError("isolated-test-value HTTP 429")) as request:
            for _ in range(2):
                with self.assertRaisesRegex(RuntimeError, "stopped to preserve quota"):
                    provider.call_with_fallback(model_attr="generator_model", prompt="fixture", schema={})
        self.assertEqual(request.call_count, 1)
        self.assertNotIn("isolated-test-value", json.dumps(provider.requests))

    def test_gemini_quota_error_preserves_provider_retry_delay(self):
        provider = self.provider()
        client = provider.clients[0].provider
        error = HTTPError(
            'https://generativelanguage.googleapis.com/v1beta/models/test:generateContent',
            429, 'Too Many Requests', hdrs={'Retry-After': '42'},
            fp=BytesIO(json.dumps({'error': {'code': 429, 'status': 'RESOURCE_EXHAUSTED',
                'message': 'free-models-per-day', 'details': [
                    {'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '125.5s'}
                ]}}).encode('utf-8')),
        )
        self.assertIn('RESOURCE_EXHAUSTED', client._http_error_detail(error))
        self.assertEqual(client.last_retry_after_seconds, 125.5)

    def test_preview_uses_copy_and_exports_three_clues(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.db"
            with closing(sqlite3.connect(source)) as conn, conn:
                daily_map_game.initialize_database(conn)
            original = source.read_bytes()
            provider = self.provider()

            def discover(**kwargs):
                self.assertNotEqual(kwargs["db_path"], source)
                with closing(sqlite3.connect(kwargs["db_path"])) as conn, conn:
                    conn.execute("UPDATE map_place_pool SET canonical_name = 'Preview only' WHERE id = 1")
                return {"candidate_place_ids": [1], "candidate_names": ["preview only"]}

            def generate(conn, **kwargs):
                self.assertEqual(kwargs["eligible_place_ids"], {1})
                self.assertNotEqual(kwargs["event_brief_cache_path"], generator.DEFAULT_EVENT_BRIEF_CACHE_PATH)
                self.assertEqual(conn.execute("SELECT canonical_name FROM map_place_pool WHERE id=1").fetchone()[0], "Preview only")
                return {"place": "Preview only", "selection_reason": "Fixture story",
                        "clue_ladder": {"hard": "Fixture hook", "medium": "Fixture region", "easy": "Fixture map route"}}

            with patch.object(generator, "discover_uncurated_candidates", side_effect=discover), patch.object(generator, "generate_round", side_effect=generate):
                result = preview.preview_round(source_db=source, output_dir=root / "reports",
                                               puzzle_date="2030-01-01", provider=provider)
            self.assertEqual(result["status"], "ready_for_review")
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(len(list((root / "reports").iterdir())), 2)
            review = Path(result["review_path"]).read_text(encoding="utf-8")
            for level in ("Hard", "Medium", "Easy"):
                self.assertIn(level + " clue", review)

    def test_published_source_date_cannot_be_reported_as_new_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.db"
            with closing(sqlite3.connect(source)) as conn, conn:
                daily_map_game.initialize_database(conn)
                conn.execute("INSERT INTO daily_map_puzzles (puzzle_date, status) VALUES ('2030-01-01', 'published')")
            with patch.object(generator, "discover_uncurated_candidates") as discover:
                result = preview.preview_round(source_db=source, output_dir=root / "reports",
                                               puzzle_date="2030-01-01", provider=self.provider())
            self.assertEqual(result["status"], "failed")
            self.assertIn("unpublished date", result["error"])
            discover.assert_not_called()


class MapAtomicPublicationTests(unittest.TestCase):
    def test_failed_publication_restores_clues_and_guidance_but_not_caller_work(self):
        with closing(sqlite3.connect(":memory:")) as conn, conn:
            conn.row_factory = sqlite3.Row
            daily_map_game.initialize_database(conn)
            conn.commit()
            place_id = conn.execute("SELECT id FROM map_place_pool LIMIT 1").fetchone()[0]
            conn.execute("UPDATE map_place_pool SET review_notes='caller work' WHERE id=?", (place_id,))
            before = dict(conn.execute("SELECT * FROM map_place_pool WHERE id=?", (place_id,)).fetchone())

            def save_clues(conn, **kwargs):
                conn.execute("UPDATE map_place_pool SET clue_text='new clue', review_status='machine_validated' WHERE id=?", (place_id,))

            with patch.object(daily_map_game, "save_reviewed_clue_ladder", side_effect=save_clues), patch.object(daily_map_game, "selected_qa_place", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "fails the clue quality gate"):
                    generator.persist_generated_round(conn, provider_name="fixture", puzzle_date="2030-01-01",
                        place_id=place_id, clue_result={"clue_ladder": {}, "critic_mode": "ai"},
                        map_anchors=[{"name": "new guidance"}])
            after = dict(conn.execute("SELECT * FROM map_place_pool WHERE id=?", (place_id,)).fetchone())
            self.assertEqual(before, after)
            self.assertTrue(conn.in_transaction)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM daily_map_puzzles WHERE puzzle_date='2030-01-01'").fetchone()[0], 0)

    def test_success_is_not_committed_until_caller_accepts(self):
        with closing(sqlite3.connect(":memory:")) as conn:
            conn.row_factory = sqlite3.Row
            daily_map_game.initialize_database(conn)
            conn.commit()
            place = conn.execute("SELECT * FROM map_place_pool LIMIT 1").fetchone()
            with patch.object(daily_map_game, "save_reviewed_clue_ladder"), patch.object(daily_map_game, "selected_qa_place", return_value=place):
                result = generator.persist_generated_round(conn, provider_name="fixture", puzzle_date="2030-01-01",
                    place_id=place["id"], clue_result={"clue_ladder": {}, "critic_mode": "ai"}, map_anchors=[])
            self.assertEqual(result["status"], "published")
            self.assertTrue(conn.in_transaction)
            conn.rollback()
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM daily_map_puzzles WHERE puzzle_date='2030-01-01'").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
