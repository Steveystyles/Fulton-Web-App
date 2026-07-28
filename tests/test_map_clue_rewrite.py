from __future__ import annotations

import importlib
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import daily_map_game

rewriter = importlib.import_module("tools.rewrite_map_clues_with_ai")


class FixtureMapClueProvider:
    name = "fixture-map-ai"

    def __init__(self) -> None:
        self.generate_calls = 0
        self.critic_calls = 0

    def generate_clue_ladder(
        self,
        *,
        place: dict[str, object],
        recent_places: list[dict[str, object]],
        feedback: list[str],
    ) -> dict[str, object]:
        self.generate_calls += 1
        return {
            "hard": "Nelson Mandela made his first public speech after 27 years of imprisonment from City Hall here.",
            "medium": "This South African legislative capital sits beneath Table Mountain.",
            "easy": "Work within the City Bowl between Table Mountain and the Atlantic waterfront.",
            "reveal": "Cape Town links Mandela's City Hall speech with Table Mountain and the City Bowl.",
        }

    def critique_clue_ladder(
        self,
        *,
        place: dict[str, object],
        clue_ladder: dict[str, object],
        recent_places: list[dict[str, object]],
    ) -> dict[str, object]:
        self.critic_calls += 1
        return {
            "passed": True,
            "scores": {
                "correctness": 9,
                "distinctiveness": 9,
                "difficulty_ladder": 9,
                "non_spoiler": 9,
                "interestingness": 8,
            },
            "failure_reasons": [],
            "feedback_to_generator": [],
        }


class RateLimitedMapClueProvider:
    name = "rate-limited-map-ai"

    def generate_clue_ladder(self, **_: object) -> dict[str, object]:
        raise RuntimeError("openai-compatible request failed with HTTP 429.")

    def critique_clue_ladder(self, **_: object) -> dict[str, object]:
        raise AssertionError("Critic should not run after a provider generation failure.")


class FlakyThenFixtureMapClueProvider(FixtureMapClueProvider):
    name = "flaky-then-fixture-map-ai"

    def __init__(self) -> None:
        super().__init__()
        self.failures_left = 1

    def generate_clue_ladder(self, **kwargs: object) -> dict[str, object]:
        if self.failures_left:
            self.failures_left -= 1
            raise RuntimeError("openai-compatible request failed with HTTP 429.")
        return super().generate_clue_ladder(**kwargs)


class AcceptFirstThenRateLimitSecondOnceProvider(FixtureMapClueProvider):
    name = "accept-first-then-rate-limit-second-once"

    def __init__(self) -> None:
        super().__init__()
        self.rate_limited = False

    def generate_clue_ladder(self, **kwargs: object) -> dict[str, object]:
        self.generate_calls += 1
        if self.generate_calls == 2 and not self.rate_limited:
            self.rate_limited = True
            raise RuntimeError("gemini request failed with HTTP 429.")
        place = kwargs.get("place")
        place_name = str(place.get("canonical_name") if isinstance(place, dict) else "Cape Town")
        if place_name == "Bath":
            return {
                "hard": "Jane Austen set two novels partly here after living in the spa city with her family.",
                "medium": "This English spa city lies in Somerset west of London.",
                "easy": "Search the city centre between the abbey and Georgian Pulteney Bridge.",
                "reveal": "Bath links Jane Austen, Somerset spa culture, its abbey, and Pulteney Bridge.",
            }
        return {
            "hard": "Nelson Mandela made his first public speech after 27 years of imprisonment from City Hall here.",
            "medium": "This South African legislative capital sits beneath Table Mountain.",
            "easy": "Work within the City Bowl between Table Mountain and the Atlantic waterfront.",
            "reveal": f"{place_name} links Mandela's City Hall speech with Table Mountain and the City Bowl.",
        }


class LocationOnlyMapClueProvider:
    name = "location-only-map-ai"

    def __init__(self) -> None:
        self.generate_calls = 0

    def generate_clue_ladder(self, **_: object) -> dict[str, object]:
        self.generate_calls += 1
        return {
            "hard": "A large settlement near a broad river and low hills.",
            "medium": "Look in the southern part of its country beside a bay.",
            "easy": "Find the coastal city between two larger urban areas.",
            "reveal": "This city is the answer.",
        }

    def critique_clue_ladder(self, **_: object) -> dict[str, object]:
        raise AssertionError("AI critic should not run when local validation rejects the ladder.")


class MapClueRewriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL)")
        daily_map_game.initialize_database(self.conn)
        self.conn.execute("UPDATE map_place_pool SET active = 0")
        self.conn.execute(
            """
            UPDATE map_place_pool
            SET active = 1,
                review_status = 'approved',
                verified_facts_json = ?,
                nearby_context = 'City Bowl, Table Mountain, Atlantic waterfront',
                clue_text = 'In Gulf of Guinea, its wider national-map setting is north of another mapped urban centre.',
                medium_clue_text = 'Look within the wider national-map setting for one of the country''s mapped urban centres.',
                easy_clue_text = 'Find the city at 5.354, -4.002 using its time zone metadata.',
                reveal_text = 'Cape Town is located at 5.354, -4.002 in the Africa/Abidjan time zone.'
            WHERE canonical_name = 'Cape Town'
            """,
            (
                json.dumps(
                    [
                        "Nelson Mandela made his first public speech after 27 years of imprisonment from City Hall.",
                        "This South African legislative capital sits beneath Table Mountain.",
                        "The City Bowl lies between Table Mountain and the Atlantic waterfront.",
                    ]
                ),
            ),
        )
        self.conn.commit()
        self.addCleanup(self.conn.close)

    def test_rewrite_map_clues_saves_accepted_ai_ladder(self) -> None:
        provider = FixtureMapClueProvider()

        report = rewriter.rewrite_map_clues(
            self.conn,
            provider=provider,
            limit=1,
            dry_run=False,
        )
        row = self.conn.execute(
            "SELECT * FROM map_place_pool WHERE canonical_name = 'Cape Town'"
        ).fetchone()

        self.assertEqual(report["accepted_count"], 1)
        self.assertEqual(report["results"][0]["status"], "accepted")
        self.assertTrue(report["results"][0]["saved"])
        self.assertEqual(provider.generate_calls, 1)
        self.assertEqual(provider.critic_calls, 1)
        self.assertIn("South African", row["medium_clue_text"])
        self.assertTrue(daily_map_game.row_passes_map_clue_quality(row))

    def test_rewrite_map_clues_dry_run_does_not_save(self) -> None:
        provider = FixtureMapClueProvider()

        report = rewriter.rewrite_map_clues(
            self.conn,
            provider=provider,
            limit=1,
            dry_run=True,
        )
        row = self.conn.execute(
            "SELECT medium_clue_text FROM map_place_pool WHERE canonical_name = 'Cape Town'"
        ).fetchone()

        self.assertEqual(report["accepted_count"], 1)
        self.assertFalse(report["results"][0]["saved"])
        self.assertIn("mapped urban centres", row["medium_clue_text"])

    def test_rewrite_map_clues_local_critic_mode_skips_ai_critic(self) -> None:
        provider = FixtureMapClueProvider()

        report = rewriter.rewrite_map_clues(
            self.conn,
            provider=provider,
            limit=1,
            dry_run=True,
            critic_mode="local",
        )

        self.assertEqual(report["accepted_count"], 1)
        self.assertEqual(report["critic_mode"], "local")
        self.assertEqual(report["results"][0]["critic_mode"], "local")
        self.assertEqual(report["results"][0]["attempts"][0]["critic_source"], "local")
        self.assertEqual(provider.generate_calls, 1)
        self.assertEqual(provider.critic_calls, 0)

    def test_candidate_rows_default_to_quality_failed_rows(self) -> None:
        rows = rewriter.candidate_rows(self.conn, limit=10)

        self.assertEqual([row["canonical_name"] for row in rows], ["Cape Town"])

    def test_candidate_rows_can_exclude_completed_places(self) -> None:
        cape_town = self.conn.execute(
            "SELECT id FROM map_place_pool WHERE canonical_name = 'Cape Town'"
        ).fetchone()

        rows = rewriter.candidate_rows(
            self.conn,
            limit=10,
            exclude_place_ids={int(cape_town["id"])},
        )

        self.assertEqual(rows, [])

    def test_rewrite_map_clues_defers_rate_limit_without_rejecting_clue(self) -> None:
        report = rewriter.rewrite_map_clues(
            self.conn,
            provider=RateLimitedMapClueProvider(),
            limit=1,
            dry_run=True,
            retry_after_minutes=45,
        )

        self.assertEqual(report["accepted_count"], 0)
        self.assertEqual(report["rejected_count"], 0)
        self.assertEqual(report["deferred_count"], 1)
        self.assertTrue(report["stopped_on_provider_error"])
        self.assertEqual(report["retry_after_minutes"], 45)
        self.assertEqual(report["results"][0]["status"], "deferred")
        self.assertTrue(report["results"][0]["retryable"])

    def test_run_rewrite_attempt_appends_failure_log_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "fultons.db"
            file_conn = sqlite3.connect(db_path)
            try:
                self.conn.backup(file_conn)
            finally:
                file_conn.close()
            failure_log_path = Path(tmpdir) / "map_clue_failure_log.jsonl"

            report = rewriter.run_rewrite_attempt(
                db_path=db_path,
                provider=LocationOnlyMapClueProvider(),
                output_dir=Path(tmpdir),
                limit=1,
                dry_run=True,
                difficulty=None,
                place_type=None,
                include_clean=False,
                learning_profile_path="test-profile.json",
                stop_on_provider_error=True,
                retry_after_minutes=1,
                critic_mode="local",
                max_attempts_per_place=1,
                failure_log_path=failure_log_path,
            )
            records = [
                json.loads(line)
                for line in failure_log_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(report["accepted_count"], 0)
        self.assertEqual(report["rejected_count"], 1)
        self.assertEqual(report["failure_log_count"], 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["place"], "Cape Town")
        self.assertEqual(records[0]["learning_profile_path"], "test-profile.json")
        self.assertIn("location_based", records[0]["failure_categories"])
        self.assertIn("weak_known_for_hook", records[0]["failure_categories"])

    def test_load_env_file_does_not_override_existing_values_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env.local"
            env_path.write_text(
                "OPENAI_API_KEY=from-file\nAI_PROVIDER=openai-compatible\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"OPENAI_API_KEY": "already-set"}, clear=False):
                loaded = rewriter.load_env_file(env_path)

                self.assertEqual(os.environ["OPENAI_API_KEY"], "already-set")
                self.assertEqual(os.environ["AI_PROVIDER"], "openai-compatible")
                self.assertNotIn("OPENAI_API_KEY", loaded)

    def test_provider_from_env_uses_existing_openai_api_key_fallback(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-key",
                "FULTONS_OPENAI_MODEL": "gpt-4.1-mini",
            },
            clear=True,
        ):
            provider = rewriter.ConfiguredMapClueProvider.from_env()

        self.assertEqual(provider.name, "openai-compatible")
        self.assertEqual(provider.clients[0].config.generator_model, "gpt-4.1-mini")
        self.assertEqual(provider.clients[0].config.compatible_base_url, "https://api.openai.com/v1")

    def test_provider_from_env_uses_map_specific_gemini_lite_defaults(self) -> None:
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True):
            provider = rewriter.ConfiguredMapClueProvider.from_env()

        self.assertEqual(provider.name, "gemini")
        self.assertEqual(provider.clients[0].config.generator_model, "gemini-3.1-flash-lite")
        self.assertEqual(provider.clients[0].config.critic_model, "gemini-3.1-flash-lite")
        self.assertEqual(
            [client.config.generator_model for client in provider.clients],
            ["gemini-3.1-flash-lite", "gemini-2.5-flash-lite"],
        )

    def test_provider_from_env_prefers_separate_map_gemini_key(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "quiz-key",
                "MAP_CLUE_GEMINI_API_KEY": "map-key",
            },
            clear=True,
        ):
            provider = rewriter.ConfiguredMapClueProvider.from_env()

        self.assertEqual(provider.clients[0].config.gemini_api_key, "map-key")
        self.assertNotEqual(provider.clients[0].config.gemini_api_key, "quiz-key")

    def test_provider_from_env_allows_map_model_overrides(self) -> None:
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True):
            provider = rewriter.ConfiguredMapClueProvider.from_env(
                generator_model="gemini-test-generator",
                critic_model="gemini-test-critic",
            )

        self.assertEqual(provider.clients[0].config.generator_model, "gemini-test-generator")
        self.assertEqual(provider.clients[0].config.critic_model, "gemini-test-critic")
        self.assertEqual(provider.clients[1].config.generator_model, "gemini-2.5-flash-lite")

    def test_apply_runtime_env_overrides_sets_timeout_and_retry_values(self) -> None:
        args = type(
            "Args",
            (),
            {
                "timeout_sec": 3,
                "request_delay_sec": 0.5,
                "transient_retries": -1,
            },
        )()
        with patch.dict(os.environ, {}, clear=True):
            rewriter.apply_runtime_env_overrides(args)

            self.assertEqual(os.environ["AI_TIMEOUT_SEC"], "5")
            self.assertEqual(os.environ["AI_REQUEST_DELAY_SEC"], "0.5")
            self.assertEqual(os.environ["AI_TRANSIENT_RETRIES"], "0")

    def test_run_until_processed_retries_after_deferred_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "fultons.db"
            file_conn = sqlite3.connect(db_path)
            try:
                self.conn.backup(file_conn)
            finally:
                file_conn.close()
            provider = FlakyThenFixtureMapClueProvider()
            with patch("tools.rewrite_map_clues_with_ai.time.sleep", return_value=None) as sleep:
                summary = rewriter.run_until_processed(
                    db_path=db_path,
                    provider=provider,
                    output_dir=Path(tmpdir),
                    limit=1,
                    dry_run=True,
                    difficulty=None,
                    place_type=None,
                    include_clean=False,
                    learning_profile_path="",
                    stop_on_provider_error=True,
                    retry_after_minutes=1,
                    retry_sleep_minutes=1,
                    max_retry_attempts=2,
                    critic_mode="ai",
                    max_attempts_per_place=None,
                )

            self.assertEqual(summary["attempt_count"], 2)
            self.assertTrue(summary["completed"])
            self.assertEqual(summary["attempts"][0]["deferred_count"], 1)
            self.assertEqual(summary["attempts"][1]["processed_count"], 1)
            self.assertTrue(Path(summary["summary_path"]).exists())
            sleep.assert_called_once()

    def test_run_until_processed_resumes_remaining_candidates_after_partial_attempt(self) -> None:
        self.conn.execute(
            """
            UPDATE map_place_pool
            SET active = 1,
                review_status = 'approved',
                verified_facts_json = ?,
                nearby_context = 'Bath Abbey, Pulteney Bridge, city centre, Somerset, England',
                clue_text = 'The clue uses coordinate-style metadata instead of a proper map hook.',
                medium_clue_text = 'The medium clue repeats coordinate-style metadata instead of teaching.',
                easy_clue_text = 'The easy clue points to the time zone metadata rather than a visible place.',
                reveal_text = 'Bath is located at 51.381, -2.360 in the Europe/London time zone.'
            WHERE canonical_name = 'Bath'
            """,
            (
                json.dumps(
                    [
                        "Jane Austen set two novels partly here after living in the spa city with her family.",
                        "This English spa city lies in Somerset west of London.",
                        "The abbey and Georgian Pulteney Bridge stand in the compact city centre.",
                    ]
                ),
            ),
        )
        self.conn.commit()
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "fultons.db"
            file_conn = sqlite3.connect(db_path)
            try:
                self.conn.backup(file_conn)
            finally:
                file_conn.close()
            provider = AcceptFirstThenRateLimitSecondOnceProvider()
            with patch("tools.rewrite_map_clues_with_ai.time.sleep", return_value=None) as sleep:
                summary = rewriter.run_until_processed(
                    db_path=db_path,
                    provider=provider,
                    output_dir=Path(tmpdir),
                    limit=2,
                    dry_run=True,
                    difficulty=None,
                    place_type=None,
                    include_clean=False,
                    learning_profile_path="",
                    stop_on_provider_error=True,
                    retry_after_minutes=1,
                    retry_sleep_minutes=1,
                    max_retry_attempts=2,
                    critic_mode="ai",
                    max_attempts_per_place=None,
                )

            self.assertEqual(summary["attempt_count"], 2)
            self.assertTrue(summary["completed"])
            self.assertEqual(summary["collected_count"], 2)
            self.assertEqual(summary["accepted_count"], 2)
            self.assertEqual(summary["attempts"][0]["processed_count"], 1)
            self.assertEqual(summary["attempts"][0]["deferred_count"], 1)
            self.assertEqual(summary["attempts"][1]["processed_count"], 1)
            self.assertEqual(summary["attempts"][1]["remaining_before_attempt"], 1)
            self.assertEqual(len(summary["results"]), 2)
            sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
