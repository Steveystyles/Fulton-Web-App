import json
import sqlite3
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from tools import generate_ai_daily_map_round, generate_ai_map_review_batch, training_data_store


class FakeProvider:
    def __init__(self, hook_id: str) -> None:
        self.hook_id = hook_id
        self.prompt = ""

    def call_with_fallback(self, **kwargs):
        self.prompt = str(kwargs["prompt"])
        return {
            "hook_id": self.hook_id,
            "selection_reason": "This incident is specific, memorable, and map-playable.",
        }


class EventResearchProvider:
    def __init__(self) -> None:
        self.tools = []
        self.calls = 0

    def call_with_fallback(self, **kwargs):
        self.calls += 1
        self.tools = list(kwargs.get("tools") or [])
        return {
            "enriched_hard_hook": (
                "After a bitter dispute with Henry II, four knights murdered "
                "Archbishop Thomas Becket inside this church in 1170."
            ),
            "supporting_details": [
                "Four knights carried out the murder.",
                "The killing followed Becket's dispute with Henry II.",
            ],
            "used_source_urls": [
                "https://www.britannica.com/biography/Saint-Thomas-Becket",
            ],
            "confidence": 95,
        }


class CorrectingEventResearchProvider(EventResearchProvider):
    def call_with_fallback(self, **kwargs):
        self.calls += 1
        self.tools = list(kwargs.get("tools") or [])
        if self.calls == 1:
            return {
                "enriched_hard_hook": (
                    "Archbishop Thomas Becket was murdered inside this building "
                    "in 1170 by four knights acting on a rash phrase uttered by "
                    "King Henry II, triggering a wave of medieval pilgrimage."
                ),
                "supporting_details": ["The first attempt is too long."],
                "used_source_urls": ["https://www.canterbury-cathedral.org/history/"],
                "confidence": 95,
            }
        return super().call_with_fallback(**kwargs)


class AiDailyMapRoundTests(unittest.TestCase):
    def test_candidate_needs_one_strong_hook_not_three_persuading_facts(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        generate_ai_daily_map_round.daily_map_game.initialize_database(conn)
        hook = (
            "Uruguay beat host nation Brazil 2-1 in the decisive 1950 World Cup "
            "match here, an upset known as the Maracanazo."
        )
        conn.execute(
            """
            UPDATE map_place_pool
            SET verified_facts_json = ?,
                nearby_context = 'Maracana district, Rio de Janeiro, Brazil'
            WHERE canonical_name = 'London'
            """,
            (json.dumps([hook]),),
        )
        row = conn.execute(
            "SELECT * FROM map_place_pool WHERE canonical_name = 'London'"
        ).fetchone()

        candidate = generate_ai_daily_map_round.candidate_summary(
            row,
            selector_profile={},
            selector_model={},
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(len(candidate["hard_hook_candidates"]), 1)
        self.assertEqual(candidate["verified_facts"], [hook])

    def test_review_results_are_training_labels_not_selection_exclusions(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        generate_ai_daily_map_round.daily_map_game.initialize_database(conn)
        with tempfile.TemporaryDirectory() as directory:
            training_dir = Path(directory)
            feedback_path = (
                training_dir / training_data_store.MAP_PLACE_REVIEW_FEEDBACK_ALL
            )
            rows = [
                {
                    "place": "Retriable Stadium",
                    "your_score": "fail",
                    "overall_review": {"pass_fail": "fail", "reason": "Weak medium clue."},
                    "clue_reviews": {},
                },
                {
                    "place": "Clean Stadium",
                    "your_score": "pass",
                    "overall_review": {"pass_fail": "pass", "reason": ""},
                    "clue_reviews": {
                        level: {"pass_fail": "pass", "reason": ""}
                        for level in ("hard", "medium", "easy")
                    },
                },
            ]
            feedback_path.write_text(
                "".join(json.dumps({"row": row}) + "\n" for row in rows),
                encoding="utf-8",
            )
            with patch.object(
                generate_ai_map_review_batch,
                "DEFAULT_OUTPUT_DIR",
                training_dir,
            ):
                _used_ids, excluded_names = (
                    generate_ai_map_review_batch.review_batch_exclusions(
                        conn,
                        puzzle_date="2026-07-28",
                    )
                )

        self.assertNotIn("clean stadium", excluded_names)
        self.assertNotIn("retriable stadium", excluded_names)

    def test_selector_chooses_a_verified_hook_before_its_place(self) -> None:
        hooks = [
            {
                "hook_id": "42:abc",
                "place_id": 42,
                "place": "Example Stadium",
                "verified_hard_hook": (
                    "A named team beat another named team 2-1 in the 1950 World Cup final."
                ),
            }
        ]
        provider = FakeProvider("42:abc")

        selected, reason = generate_ai_daily_map_round.choose_hard_hook(
            provider,
            hooks,
            puzzle_date="2026-07-27",
        )

        self.assertEqual(selected["place_id"], 42)
        self.assertIn("specific", reason)
        self.assertIn("The hook determines the place", provider.prompt)
        self.assertIn("Reject architecture, architects, construction", provider.prompt)

    def test_selector_rejects_hook_id_outside_verified_shortlist(self) -> None:
        provider = FakeProvider("outside")

        with self.assertRaisesRegex(ValueError, "outside the verified shortlist"):
            generate_ai_daily_map_round.choose_hard_hook(
                provider,
                [
                    {
                        "hook_id": "42:abc",
                        "place_id": 42,
                        "place": "Example Stadium",
                        "verified_hard_hook": "A specific event happened here.",
                    }
                ],
                puzzle_date="2026-07-27",
            )

    def test_learned_selector_uses_the_ranked_hook_without_an_api_call(self) -> None:
        hooks = [
            {
                "hook_id": "42:abc",
                "place_id": 42,
                "place": "Preferred Stadium",
                "learned_score": 8.5,
                "learned_confidence": 0.9,
                "selector_score": 120,
            },
            {
                "hook_id": "43:def",
                "place_id": 43,
                "place": "Other Stadium",
                "learned_score": 7.0,
                "learned_confidence": 0.9,
                "selector_score": 130,
            },
        ]

        selected, reason = generate_ai_daily_map_round.choose_learned_hard_hook(hooks)

        self.assertEqual(selected["place_id"], 42)
        self.assertIn("trained place-ranking profile", reason)

    def test_round_moves_to_next_place_when_first_ladder_is_rejected(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        generate_ai_daily_map_round.daily_map_game.initialize_database(conn)
        first_id = conn.execute(
            "SELECT id FROM map_place_pool WHERE canonical_name = 'London'"
        ).fetchone()["id"]
        second_id = conn.execute(
            "SELECT id FROM map_place_pool WHERE canonical_name = 'Paris'"
        ).fetchone()["id"]
        hooks = [
            {
                "hook_id": "first",
                "place_id": first_id,
                "place": "London",
                "verified_hard_hook": "A first recognisable event happened here.",
                "learned_score": 9.0,
                "learned_confidence": 0.9,
                "selector_score": 90,
            },
            {
                "hook_id": "second",
                "place_id": second_id,
                "place": "Paris",
                "verified_hard_hook": "A second recognisable event happened here.",
                "learned_score": 8.0,
                "learned_confidence": 0.9,
                "selector_score": 80,
            },
        ]
        rejected = {
            "status": "rejected",
            "saved": False,
            "attempts": [
                {
                    "critic_source": "local",
                    "critic": {"failure_reasons": ["easy leaks the answer"]},
                    "local_critic": {"failure_reasons": []},
                }
            ],
        }
        accepted = {
            "status": "accepted",
            "saved": True,
            "attempts": [{}],
            "critic_mode": "ai",
            "clue_ladder": {
                "hard": "Hard",
                "medium": "Medium",
                "easy": "Easy",
                "reveal": "Reveal",
            },
        }
        event_briefs = [
            {
                "enriched_hard_hook": "A first recognisable event happened here.",
                "supporting_details": [],
                "used_source_urls": ["https://example.com/first"],
                "confidence": 90,
            },
            {
                "enriched_hard_hook": "A second recognisable event happened here.",
                "supporting_details": [],
                "used_source_urls": ["https://example.com/second"],
                "confidence": 90,
            },
        ]

        with (
            patch.object(
                generate_ai_daily_map_round,
                "hard_hook_shortlist",
                return_value=hooks,
            ),
            patch.object(
                generate_ai_daily_map_round,
                "research_event_brief",
                side_effect=event_briefs,
            ),
            patch.object(
                generate_ai_daily_map_round.daily_map_game,
                "generate_reviewed_clue_ladder",
                side_effect=[rejected, accepted],
            ) as generate_clues,
            patch.object(
                generate_ai_daily_map_round.daily_map_game,
                "generate_daily_map_game",
                return_value={"status": "published"},
            ),
            patch.object(
                generate_ai_daily_map_round.daily_map_game,
                "map_learning_profile_hash",
                return_value="profile-hash",
            ),
        ):
            result = generate_ai_daily_map_round.generate_round(
                conn,
                provider=object(),
                puzzle_date="2026-07-30",
                shortlist_limit=8,
                max_clue_attempts=2,
                max_place_attempts=2,
            )

        self.assertEqual(result["place"], "Paris")
        self.assertEqual(result["place_attempts"], 2)
        self.assertEqual(result["rejected_places"][0]["place"], "London")
        self.assertEqual(generate_clues.call_count, 2)

    def test_event_research_uses_grounding_and_returns_a_richer_capsule(self) -> None:
        provider = EventResearchProvider()
        result = generate_ai_daily_map_round.research_event_brief(
            provider,
            {
                "verified_hard_hook": (
                    "Archbishop Thomas Becket was murdered inside the church in 1170."
                ),
                "source_urls": [
                    "https://en.wikipedia.org/wiki/Canterbury_Cathedral",
                ],
            },
            place={
                "canonical_name": "Canterbury Cathedral",
                "acceptable_aliases": [],
            },
            cache_path=None,
        )

        self.assertIn("four knights", result["enriched_hard_hook"])
        self.assertEqual(
            provider.tools,
            [{"urlContext": {}}],
        )

    def test_event_research_uses_search_when_no_source_url_exists(self) -> None:
        provider = EventResearchProvider()
        generate_ai_daily_map_round.research_event_brief(
            provider,
            {
                "verified_hard_hook": (
                    "Archbishop Thomas Becket was murdered inside the church in 1170."
                ),
                "source_urls": [],
            },
            place={
                "canonical_name": "Canterbury Cathedral",
                "acceptable_aliases": [],
            },
            cache_path=None,
        )

        self.assertEqual(provider.tools, [{"googleSearch": {}}])

    def test_event_research_reuses_a_validated_cache_entry(self) -> None:
        provider = EventResearchProvider()
        selected_hook = {
            "place_id": 42,
            "verified_hard_hook": (
                "Archbishop Thomas Becket was murdered inside the church in 1170."
            ),
            "source_urls": [
                "https://www.canterbury-cathedral.org/history/"
            ],
        }
        place = {
            "canonical_name": "Canterbury Cathedral",
            "acceptable_aliases": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "event-cache.json"
            first = generate_ai_daily_map_round.research_event_brief(
                provider,
                selected_hook,
                place=place,
                cache_path=cache_path,
            )
            second = generate_ai_daily_map_round.research_event_brief(
                provider,
                selected_hook,
                place=place,
                cache_path=cache_path,
            )

        self.assertEqual(provider.calls, 1)
        self.assertEqual(second, first)

    def test_event_research_retries_a_rejected_capsule_with_feedback(self) -> None:
        provider = CorrectingEventResearchProvider()
        result = generate_ai_daily_map_round.research_event_brief(
            provider,
            {
                "verified_hard_hook": (
                    "Archbishop Thomas Becket was murdered inside the church in 1170."
                ),
                "source_urls": ["https://www.canterbury-cathedral.org/history/"],
            },
            place={
                "canonical_name": "Canterbury Cathedral",
                "acceptable_aliases": [],
            },
            cache_path=None,
        )

        self.assertEqual(provider.calls, 1)
        self.assertIn("four knights", result["enriched_hard_hook"])

    def test_grounded_hook_is_not_truncated_to_a_word_limit(self) -> None:
        capsule = (
            "At this site, Nazi troops systematically demolished over 85 percent "
            "of the medieval district during the August 1944 uprising to suppress local resistance."
        )

        edited = generate_ai_daily_map_round.compress_event_capsule_to_limit(capsule)

        self.assertIn("systematically", edited)
        self.assertEqual(edited, capsule)

        reconstruction = (
            "During the August 1944 uprising here, occupation forces deliberately "
            "demolished over eighty-five percent of the medieval architecture, "
            "prompting a total postwar citizens' reconstruction."
        )
        edited_reconstruction = (
            generate_ai_daily_map_round.compress_event_capsule_to_limit(reconstruction)
        )
        self.assertEqual(edited_reconstruction, reconstruction)
        self.assertIn("prompting", edited_reconstruction)

        rubble = (
            "During the August 1944 uprising here, Nazi troops carried out a "
            "systematic demolition campaign that reduced over 85 percent of "
            "the medieval district to rubble."
        )
        edited_rubble = generate_ai_daily_map_round.compress_event_capsule_to_limit(
            rubble
        )
        self.assertEqual(edited_rubble, rubble)
        self.assertTrue(
            generate_ai_daily_map_round.daily_map_game.hard_event_has_enough_information(
                edited_rubble
            )
        )


if __name__ == "__main__":
    unittest.main()
