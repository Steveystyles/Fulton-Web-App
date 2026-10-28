from copy import deepcopy
from contextlib import closing
from io import BytesIO
import json
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from tools import controlled_map_round as controlled


class ControlledMapTests(unittest.TestCase):
    def setUp(self):
        seed = controlled.PROJECT_DIR / "deploy" / "map-training-seed" / "map_learning_profile_latest.json"
        profile = patch.object(controlled.daily_map_game, "map_learning_profile_hash", return_value=hashlib.sha256(seed.read_bytes()).hexdigest()[:16])
        profile.start()
        self.addCleanup(profile.stop)
        self.places = controlled.load_catalog(controlled.DEFAULT_CATALOG)
        self.place = next(p for p in self.places if p["id"] == "atomium")
        self.payload = {"place_id": "atomium", "selection_reason": "A surprising scientific idea turned into a recognisable landmark.",
                        "clues": {k: {"text": v["text"], "fact_id": k} for k, v in self.place["facts"].items()}}

    def provider(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY_DEV": "dev-fixture"}, clear=True):
            return controlled.ControlledProvider.from_preview_env(max_requests=1)

    def source(self, path):
        with sqlite3.connect(path) as conn:
            conn.executescript("CREATE TABLE daily_map_puzzles(id INTEGER, puzzle_date TEXT, status TEXT DEFAULT 'published');"
                               "CREATE TABLE daily_map_levels(puzzle_id INTEGER, place_id INTEGER);"
                               "CREATE TABLE map_place_pool(id INTEGER, canonical_name TEXT, acceptable_aliases TEXT, lat REAL, lng REAL);")
        conn.close()

    def test_sourced_ladder_passes_and_model_cannot_set_coordinates(self):
        self.payload["lat"] = 0
        result = controlled.validate_result(self.payload, self.places)
        self.assertTrue(result["automated_pass"])
        self.assertEqual(result["coordinates"]["lat"], self.place["lat"])
        self.assertEqual(len(result["map_search_anchors"]), 3)
        rendered = controlled.daily_map_game.serialize_map_search_anchors(json.dumps(result["map_search_anchors"]))
        self.assertEqual([a["minHintCount"] for a in rendered], [1, 2, 2])
        self.assertEqual(rendered[2]["minZoom"], 12)
        self.assertEqual(rendered[2]["name"], self.place["canonical_name"])

    def test_answer_leak_and_missing_anchor_are_rejected(self):
        for text in ("The Atomium was created for a world's fair in 1958.",
                     "This landmark is found in the northern part of the city."):
            with self.subTest(text=text):
                payload = deepcopy(self.payload)
                payload["clues"]["easy"]["text"] = text
                self.assertFalse(controlled.validate_result(payload, self.places)["automated_pass"])

    def test_unknown_selection_extra_clue_and_false_citation_fail(self):
        for change in ("place", "extra", "citation"):
            payload = deepcopy(self.payload)
            if change == "place":
                payload["place_id"] = "invented"
            elif change == "extra":
                payload["clues"]["fourth"] = payload["clues"]["easy"]
            else:
                payload["clues"]["hard"]["fact_id"] = "easy"
            with self.subTest(change=change), self.assertRaises(ValueError):
                controlled.validate_result(payload, self.places)

    def test_invented_number_is_rejected_without_fabricated_confidence_score(self):
        self.payload["clues"]["hard"]["text"] = self.payload["clues"]["hard"]["text"].replace("165", "999")
        result = controlled.validate_result(self.payload, self.places)
        self.assertFalse(result["automated_pass"])
        self.assertFalse(result["validation"]["passed"])
        self.assertNotIn("scores", result["validation"])

    def test_urban_legend_cannot_be_rewritten_as_a_true_purchase_mistake(self):
        place = next(p for p in self.places if p['id'] == 'q83125')
        payload = {'place_id': place['id'], 'selection_reason': 'A sourced story with a clearly identified urban legend.',
                   'clues': {k: {'text': v['text'], 'fact_id': k} for k, v in place['facts'].items()}}
        self.assertTrue(controlled.validate_result(payload, [place])['automated_pass'])
        payload['clues']['hard']['text'] = 'An American buyer confused this landmark with another upstream crossing and purchased the wrong bridge.'
        result = controlled.validate_result(payload, [place])
        self.assertFalse(result['automated_pass'])
        self.assertTrue(any('qualification' in reason for reason in result['validation']['failure_reasons']))

    def test_catalogue_rejects_missing_sources_and_bad_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            for change in ("source", "geometry", "nan", "nesting"):
                place = deepcopy(self.place)
                if change == "source":
                    place["facts"]["hard"]["source_ids"] = ["missing"]
                elif change == "geometry":
                    place["anchors"][1]["lat"] = 0
                elif change == "nan":
                    place["lat"] = float("nan")
                else:
                    place["anchors"][1]["radius_m"] = 30000
                path.write_text(json.dumps({"version": 1, "places": [place]}), encoding="utf-8")
                with self.subTest(change=change), self.assertRaises(ValueError):
                    controlled.load_catalog(path)

    def test_existing_date_and_duplicate_coordinate_history_are_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.db"
            self.source(path)
            with sqlite3.connect(path) as conn:
                conn.execute("INSERT INTO daily_map_puzzles(id,puzzle_date) VALUES(1, '2026-09-06')")
                conn.execute("INSERT INTO daily_map_levels VALUES(1, 1)")
                conn.execute("INSERT INTO map_place_pool VALUES(1, 'Different imported name', '', ?, ?)", (self.place["lat"], self.place["lng"]))
            conn.close()
            with self.assertRaisesRegex(ValueError, "already has a round"):
                controlled.eligible_places(path, "2026-09-06", self.places)
            self.assertNotIn("atomium", [p["id"] for p in controlled.eligible_places(path, "2026-09-11", self.places)])
            with self.assertRaisesRegex(ValueError, "No unused"):
                controlled.eligible_places(path, "2026-09-11", [self.place])

    def test_tools_and_large_prompts_never_reach_provider(self):
        provider = self.provider()
        client = provider.clients[0]
        with patch.object(client.provider, "_request") as request:
            for kwargs in ({"tools": [{"googleSearch": {}}], "prompt": "test"},
                           {"prompt": "x" * (controlled.MAX_PROMPT_CHARS + 1)}):
                with self.assertRaises(ValueError):
                    provider.request_json(client, model="test", schema={}, **kwargs)
            request.assert_not_called()
            provider.request_json(client, model="test", schema={}, prompt="bounded")
            self.assertEqual(request.call_args.kwargs["max_output_tokens"], 2048)

    def test_one_call_export_preserves_source_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.db"
            self.source(source)
            before = source.read_bytes()
            provider = self.provider()
            with patch.object(provider.clients[0].provider, "_request", return_value=self.payload) as request:
                report = controlled.run(source_db=source, catalog=controlled.DEFAULT_CATALOG,
                                        puzzle_date="2026-09-11", output_dir=root / "reports", provider=provider)
            self.assertEqual(report["status"], "ready_for_review")
            self.assertEqual(request.call_count, 1)
            self.assertEqual(report["request_count"], 1)
            self.assertFalse(report["requests"][0]["grounded"])
            self.assertEqual(source.read_bytes(), before)
            self.assertTrue(Path(report["review_path"]).exists())

    def test_failed_provider_is_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.db"
            self.source(source)
            provider = self.provider()
            with patch.object(provider.clients[0].provider, "_request", side_effect=RuntimeError("dev-fixture quota")) as request:
                report = controlled.run(source_db=source, catalog=controlled.DEFAULT_CATALOG,
                                        puzzle_date="2026-09-11", output_dir=root / "reports", provider=provider)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(request.call_count, 1)
            self.assertNotIn("dev-fixture", json.dumps(report))

    def test_runtime_requires_dedicated_key_and_does_not_inherit_quiz_fallback(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY_DEV": "dev", "GEMINI_API_KEY": "other"}, clear=True):
            with self.assertRaisesRegex(ValueError, "MAP_AI_API_KEY"):
                controlled.ControlledProvider.from_runtime_env()
        with patch.dict(os.environ, {"MAP_AI_API_KEY": "runtime", "MAP_AI_MODEL": "explicit-model"}, clear=True):
            provider = controlled.ControlledProvider.from_runtime_env()
            self.assertEqual(provider.max_requests, 1)
            self.assertEqual(provider.clients[0].config.generator_model, "explicit-model")
            self.assertEqual(provider.clients[0].config.fallback_provider, "")

    def test_runtime_adds_only_configured_free_openrouter_fallback(self):
        env = {"MAP_AI_API_KEY": "runtime", "AI_FALLBACK2_PROVIDER": "openrouter",
               "AI_FALLBACK2_GENERATOR_MODEL": "openrouter/free",
               "AI_FALLBACK2_CRITIC_MODEL": "openrouter/free",
               "AI_FALLBACK2_API_KEY": "router-fixture"}
        with patch.dict(os.environ, env, clear=True):
            provider = controlled.ControlledProvider.from_runtime_env()
        self.assertEqual(provider.max_requests, 2)
        self.assertEqual([client.provider.name for client in provider.clients], ["gemini", "openrouter"])
        self.assertEqual(provider.clients[1].config.generator_model, "openrouter/free")
        self.assertEqual(provider.clients[1].config.compatible_base_url, "https://openrouter.ai/api/v1")
        with patch.dict(os.environ, {**env, "AI_FALLBACK2_GENERATOR_MODEL": "paid-model"}, clear=True):
            paid = controlled.ControlledProvider.from_runtime_env()
        self.assertEqual(paid.max_requests, 1)
        self.assertEqual(len(paid.clients), 1)

    def test_runtime_falls_back_once_only_when_gemini_unavailable(self):
        with patch.dict(os.environ, {"MAP_AI_API_KEY": "runtime",
                                     "AI_FALLBACK2_PROVIDER": "openrouter",
                                     "AI_FALLBACK2_GENERATOR_MODEL": "openrouter/free",
                                     "AI_FALLBACK2_CRITIC_MODEL": "openrouter/free",
                                     "AI_FALLBACK2_API_KEY": "router-fixture"}, clear=True):
            provider = controlled.ControlledProvider.from_runtime_env()
        with patch.object(provider, "request_json", side_effect=[
            RuntimeError("Gemini request failed with HTTP 503"), self.payload,
        ]) as request:
            result = provider.call_with_fallback(
                model_attr="generator_model", prompt="public source facts", schema=controlled.response_schema(),
            )
        self.assertEqual(result, self.payload)
        self.assertEqual(request.call_count, 2)
        self.assertEqual([item["status"] for item in provider.requests], ["failed", "completed"])
        self.assertEqual(provider.last_provider_name, "openrouter")

        with patch.dict(os.environ, {"MAP_AI_API_KEY": "runtime",
                                     "AI_FALLBACK2_PROVIDER": "openrouter",
                                     "AI_FALLBACK2_GENERATOR_MODEL": "openrouter/free",
                                     "AI_FALLBACK2_CRITIC_MODEL": "openrouter/free",
                                     "AI_FALLBACK2_API_KEY": "router-fixture"}, clear=True):
            provider = controlled.ControlledProvider.from_runtime_env()
        with patch.object(provider, "request_json", side_effect=ValueError("Invalid source facts")) as request:
            with self.assertRaisesRegex(RuntimeError, "provider failed"):
                provider.call_with_fallback(
                    model_attr="generator_model", prompt="public source facts", schema=controlled.response_schema(),
                )
        request.assert_called_once()
        self.assertEqual(len(provider.requests), 1)

    def test_free_fallback_publishes_with_openrouter_provenance(self):
        with patch.dict(os.environ, {"MAP_AI_API_KEY": "runtime",
                                     "AI_FALLBACK2_PROVIDER": "openrouter",
                                     "AI_FALLBACK2_GENERATOR_MODEL": "openrouter/free",
                                     "AI_FALLBACK2_CRITIC_MODEL": "openrouter/free",
                                     "AI_FALLBACK2_API_KEY": "router-fixture"}, clear=True):
            provider = controlled.ControlledProvider.from_runtime_env()
        with closing(sqlite3.connect(":memory:")) as conn:
            conn.row_factory = sqlite3.Row
            controlled.daily_map_game.initialize_database(conn)
            conn.commit()
            with patch.object(provider, "request_json", side_effect=[
                RuntimeError("Gemini request failed with HTTP 503"), self.payload,
            ]):
                result = controlled.generate_and_publish(
                    conn, puzzle_date="2026-09-20", provider=provider,
                )
            self.assertEqual(result["publish_result"]["status"], "published")
            self.assertEqual(result["request_count"], 2)
            source = conn.execute(
                "SELECT clue_generation_source FROM map_place_pool WHERE slug LIKE 'controlled-%'"
            ).fetchone()[0]
            self.assertEqual(source, "controlled-openrouter")

    def test_controlled_free_router_does_not_hide_second_http_request(self):
        with patch.dict(os.environ, {"MAP_AI_API_KEY": "runtime",
                                     "AI_FALLBACK2_PROVIDER": "openrouter",
                                     "AI_FALLBACK2_GENERATOR_MODEL": "openrouter/free",
                                     "AI_FALLBACK2_CRITIC_MODEL": "openrouter/free",
                                     "AI_FALLBACK2_API_KEY": "router-fixture"}, clear=True):
            provider = controlled.ControlledProvider.from_runtime_env()
        router = provider.clients[1]
        mandatory = HTTPError(
            "https://openrouter.ai/api/v1/chat/completions", 400, "Bad Request",
            hdrs=None, fp=BytesIO(
                b'{"error":{"message":"Reasoning cannot be disabled."}}'
            ),
        )
        with patch("daily_quiz.urlopen", side_effect=mandatory) as request, \
             patch.object(router.provider, "_wait_for_request_slot"):
            with self.assertRaisesRegex(RuntimeError, "HTTP 400"):
                provider.request_json(
                    router, model="openrouter/free", prompt="public facts",
                    schema=controlled.response_schema(),
                )
        request.assert_called_once()

    def test_missing_learning_profile_stops_before_api_call(self):
        provider = self.provider()
        with closing(sqlite3.connect(":memory:")) as conn, patch.object(controlled.daily_map_game, "map_learning_profile_hash", return_value=""), patch.object(provider, "request_json") as request:
            with self.assertRaisesRegex(ValueError, "learning profile"):
                controlled.generate_and_publish(conn, puzzle_date="2026-09-20", provider=provider)
            request.assert_not_called()

    def test_all_catalogue_places_can_publish_with_evidence_based_clues(self):
        with closing(sqlite3.connect(":memory:")) as conn:
            conn.row_factory = sqlite3.Row
            controlled.daily_map_game.initialize_database(conn)
            conn.commit()
            for index, place in enumerate(self.places):
                payload = {"place_id": place["id"], "selection_reason": "A sourced landmark with distinctive history and practical map guidance.",
                           "clues": {k: {"text": v["text"], "fact_id": k} for k, v in place["facts"].items()}}
                provider = self.provider()
                with self.subTest(place=place["id"]), patch.object(provider, "request_json", return_value=payload):
                    result = controlled.generate_and_publish(conn, puzzle_date=f"2026-10-{index + 1:02d}", provider=provider)
                    self.assertEqual(result["publish_result"]["status"], "published")
                    conn.commit()

    def test_real_publication_and_rollback_preserve_callers_transaction(self):
        for fail in (False, True):
            with self.subTest(fail=fail), closing(sqlite3.connect(":memory:")) as conn:
                conn.row_factory = sqlite3.Row
                controlled.daily_map_game.initialize_database(conn)
                conn.commit()
                conn.execute("CREATE TABLE caller_work(value TEXT)")
                conn.execute("INSERT INTO caller_work VALUES ('preserve')")
                provider = self.provider()
                original = controlled.generator.persist_generated_round
                def publish(*args, **kwargs):
                    result = original(*args, **kwargs)
                    if fail:
                        raise RuntimeError("injected after real publication")
                    return result
                with patch.object(provider, "request_json", return_value=self.payload), patch.object(controlled.generator, "persist_generated_round", side_effect=publish):
                    if fail:
                        with self.assertRaisesRegex(RuntimeError, "injected"):
                            controlled.generate_and_publish(conn, puzzle_date="2026-09-20", provider=provider)
                    else:
                        result = controlled.generate_and_publish(conn, puzzle_date="2026-09-20", provider=provider)
                        self.assertEqual(result["publish_result"]["status"], "published")
                self.assertTrue(conn.in_transaction)
                self.assertEqual(conn.execute("SELECT value FROM caller_work").fetchone()[0], "preserve")
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM map_place_pool WHERE slug LIKE 'controlled-%'").fetchone()[0], 0 if fail else 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM daily_map_puzzles WHERE puzzle_date='2026-09-20'").fetchone()[0], 0 if fail else 1)

    def test_scheduler_uses_controlled_mode_and_preserves_published_round(self):
        import server
        with closing(sqlite3.connect(":memory:")) as conn:
            conn.row_factory = sqlite3.Row
            controlled.daily_map_game.initialize_database(conn)
            conn.commit()
            provider = self.provider()
            with patch.object(server, "DAILY_MAP_CONTROLLED_ENABLED", True), patch.object(server, "DAILY_MAP_AI_GENERATION_ENABLED", True), patch.object(server, "DAILY_MAP_CONTROLLED_CATALOG", controlled.DEFAULT_CATALOG), patch.object(controlled.ControlledProvider, "from_runtime_env", return_value=provider), patch.object(provider, "request_json", return_value=self.payload) as request:
                result = server.generate_daily_map_game_for_date(conn, puzzle_date="2026-09-20")
                self.assertEqual(result["status"], "published")
                for hint_count in (0, 1, 2):
                    level_id = conn.execute("SELECT id FROM daily_map_levels WHERE puzzle_id=(SELECT id FROM daily_map_puzzles WHERE puzzle_date='2026-09-20')").fetchone()[0]
                    conn.execute("INSERT OR REPLACE INTO daily_map_progress(user_id,level_id,revealed_hint_count,created_at,updated_at) VALUES(1,?,?, 'fixture','fixture')", (level_id, hint_count))
                    bundle = controlled.daily_map_game.daily_bundle_payload(conn, puzzle_date="2026-09-20", user_id=1)
                    level = bundle["levels"][0]
                    self.assertEqual(len(level["clues"]), hint_count + 1)
                    self.assertEqual(len(level["mapAnchors"]), hint_count)
                    self.assertNotIn('Atomium', json.dumps(level))
                repeated = server.generate_daily_map_game_for_date(conn, puzzle_date="2026-09-20", force=True)
                self.assertEqual(repeated["status"], "published")
                self.assertEqual(request.call_count, 1)

    def test_scheduler_failure_uses_existing_reviewed_fallback_without_old_ai(self):
        import server
        with closing(sqlite3.connect(":memory:")) as conn:
            conn.row_factory = sqlite3.Row
            controlled.daily_map_game.initialize_database(conn)
            conn.commit()
            with patch.object(server, "DAILY_MAP_CONTROLLED_ENABLED", True), patch.object(server, "DAILY_MAP_AI_GENERATION_ENABLED", True), patch.object(controlled.ControlledProvider, "from_runtime_env", side_effect=ValueError("missing")), patch.object(server, "publish_reviewed_daily_map_fallback", return_value={"status": "published"}) as fallback, patch.object(server.map_clue_rewriter.ConfiguredMapClueProvider, "from_env") as old:
                self.assertEqual(server.generate_daily_map_game_for_date(conn, puzzle_date="2026-09-20")["status"], "published")
                fallback.assert_called_once()
                old.assert_not_called()


if __name__ == "__main__":
    unittest.main()
