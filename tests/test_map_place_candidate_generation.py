from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import daily_map_game
from tools import build_map_selector_profile
from tools import export_map_place_review_batch as review_export
from tools import generate_map_place_candidates_with_ai as generator
from tools import map_selector_model


def valid_candidate() -> dict[str, object]:
    return {
        "canonical_name": "Blackpool Tower",
        "place_type": "observation_tower",
        "difficulty": "easy",
        "country_code": "GB",
        "country_name": "United Kingdom",
        "continent": "Europe",
        "admin1": "England",
        "lat": 53.8159,
        "lng": -3.0550,
        "coordinate_precision": "landmark",
        "suggested_map_zoom": 12,
        "acceptable_aliases": [],
        "fun_facts": [
            "This tower contains the world's oldest permanent circus arena, which has presented regular seasons since 1894.",
            "Victorian engineers built a steel landmark for a northwest English seaside resort.",
            "Look for the tower on the seafront promenade where the annual light festival runs beside the Irish Sea.",
        ],
        "why_fun": "It has a strong visual target and three different hooks: seaside spectacle, engineering, and entertainment.",
        "map_guessability": "The pin can target the landmark itself on the seafront.",
        "avoid_in_clues": ["Blackpool", "Blackpool Tower"],
        "source_search_queries": [
            "Blackpool Tower history official",
            "Blackpool Illuminations history official",
        ],
        "source_urls": [
            "https://www.theblackpooltower.com/our-history/",
        ],
    }


class MapPlaceCandidateGenerationTests(unittest.TestCase):
    def test_ai_generation_does_not_hold_database_write_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "map.db"

            def generate_while_checking_lock(**_kwargs: object) -> list[dict[str, object]]:
                second = sqlite3.connect(db_path, timeout=0.1)
                try:
                    second.execute("BEGIN IMMEDIATE")
                    second.rollback()
                finally:
                    second.close()
                return [valid_candidate()]

            with (
                patch.object(generator, "generate_raw_candidates", side_effect=generate_while_checking_lock),
                patch.object(
                    generator,
                    "validated_review_rows",
                    return_value=([valid_candidate()], []),
                ),
            ):
                result = generator.generate_review_batch(
                    db_path=db_path,
                    provider=object(),
                    limit=1,
                    batch_size=1,
                    max_attempts=1,
                    retry_after_minutes=0,
                    feedback_dir=Path(temp_dir),
                )

            self.assertEqual(len(result["accepted"]), 1)

    def test_selector_profile_classifies_review_notes_into_guidance(self) -> None:
        profile = build_map_selector_profile.build_profile(
            [
                {
                    "place": "Wembley Stadium",
                    "type": "stadium",
                    "categories": "sport; visual_landmark",
                    "your_score": 8,
                    "notes": "This is good but the clues need more significant things that happened there like finals.",
                },
                {
                    "place": "Signal Iduna Park",
                    "type": "stadium",
                    "categories": "sport",
                    "your_score": 8,
                    "notes": "No 3 is subjective and not helpful.",
                },
                {
                    "place": "Stade de France",
                    "type": "stadium",
                    "categories": "sport",
                    "your_score": 8,
                    "notes": "2 and 3 are essentially the same.",
                },
            ],
            source_files=[],
        )

        self.assertEqual(profile["note_category_counts"]["needs_significant_event"], 1)
        self.assertEqual(profile["note_category_counts"]["subjective_fact"], 1)
        self.assertEqual(profile["note_category_counts"]["repeated_fact"], 1)
        guidance = " ".join(item["guidance"] for item in profile["note_guidance"])
        self.assertIn("major final", guidance)
        self.assertIn("subjective", guidance)
        self.assertIn("distinct", guidance)

    def test_selector_profile_summary_includes_note_guidance(self) -> None:
        summary = generator.selector_profile_summary(
            {
                "accepted_row_count": 3,
                "note_guidance": [
                    {
                        "category": "subjective_fact",
                        "count": 2,
                        "guidance": "Avoid subjective facts.",
                    }
                ],
                "clue_level_guidance": [
                    {
                        "level": "easy",
                        "count": 2,
                        "mean_score": 3.0,
                        "guidance": "Improve easy clues.",
                    }
                ],
            }
        )

        self.assertEqual(summary["note_guidance"][0]["category"], "subjective_fact")
        self.assertEqual(summary["note_guidance"][0]["guidance"], "Avoid subjective facts.")
        self.assertEqual(summary["clue_level_guidance"][0]["level"], "easy")
        self.assertEqual(summary["clue_level_guidance"][0]["guidance"], "Improve easy clues.")

    def test_selector_profile_classifies_former_record_feedback(self) -> None:
        profile = build_map_selector_profile.build_profile(
            [
                {
                    "place": "CN Tower",
                    "type": "landmark",
                    "categories": "visual_landmark",
                    "your_score": 8,
                    "notes": "This isnt the tallest, it just used to be.",
                }
            ],
            source_files=[],
        )

        self.assertEqual(profile["note_category_counts"]["former_record_weak_hook"], 1)
        guidance = " ".join(item["guidance"] for item in profile["note_guidance"])
        self.assertIn("former-height-record", guidance)

    def test_selector_profile_classifies_weak_colour_hook_feedback(self) -> None:
        profile = build_map_selector_profile.build_profile(
            [
                {
                    "place": "Golden Gate Bridge",
                    "type": "bridge",
                    "categories": "visual_landmark",
                    "your_score": 8,
                    "notes": "The hard is too vague, there must be an interesting fact other than its colour.",
                }
            ],
            source_files=[],
        )

        self.assertEqual(profile["note_category_counts"]["weak_colour_hook"], 1)
        guidance = " ".join(item["guidance"] for item in profile["note_guidance"])
        self.assertIn("colour or paint", guidance)

    def test_selector_profile_collects_individual_clue_scores(self) -> None:
        profile = build_map_selector_profile.build_profile(
            [
                {
                    "place": "Wembley Stadium",
                    "type": "stadium",
                    "categories": "sport",
                    "your_score": 8,
                    "clue_scores": {"Hard": 8, "Medium": 3},
                    "clue_uses": [
                        {"level": "Easy", "yourScore": 5},
                        {"level": "Name", "yourScore": 10},
                    ],
                },
                {
                    "place": "Golden Gate Bridge",
                    "type": "bridge",
                    "categories": "visual_landmark",
                    "your_score": "",
                    "clue_uses": [
                        {"level": "Hard", "yourScore": 5},
                        {"level": "Medium", "yourScore": 5},
                        {"level": "Easy", "yourScore": 3},
                    ],
                },
            ],
            source_files=[],
        )

        self.assertEqual(profile["clue_level_scores"]["hard"]["count"], 2)
        self.assertEqual(profile["clue_level_scores"]["medium"]["low_score_count"], 1)
        self.assertEqual(profile["clue_level_scores"]["easy"]["low_score_count"], 1)
        self.assertNotIn("Golden Gate Bridge", profile["place_scores"])
        levels = {item["level"] for item in profile["clue_level_guidance"]}
        self.assertIn("medium", levels)
        self.assertIn("easy", levels)

    def test_selector_profile_collects_hard_pass_fail_reviews(self) -> None:
        profile = build_map_selector_profile.build_profile(
            [
                {
                    "place": "Tower Bridge",
                    "type": "bridge",
                    "categories": "visual_landmark",
                    "your_score": "",
                    "hard_review": {
                        "pass_fail": "fail",
                        "clue": "One of the most recognisable bridges in the world.",
                        "reason": "Too subjective and not specific to that bridge.",
                        "better_direction": "Use the bascule mechanism or glass walkway as the concrete hook.",
                    },
                },
                {
                    "place": "Maracanã Stadium",
                    "type": "stadium",
                    "categories": "sport",
                    "your_score": "",
                    "hard_review": {
                        "pass_fail": "pass",
                        "clue": "It was the site of the infamous Maracanazo in 1950.",
                        "reason": "Specific named event and memorable football hook.",
                    },
                },
            ],
            source_files=[],
        )

        hard_review = profile["hard_clue_review"]
        self.assertEqual(hard_review["count"], 2)
        self.assertEqual(hard_review["pass_count"], 1)
        self.assertEqual(hard_review["fail_count"], 1)
        self.assertEqual(profile["note_category_counts"]["subjective_fact"], 1)
        self.assertIn("bascule mechanism", hard_review["fail_examples"][0]["better_direction"])

    def test_selector_profile_treats_pass_fail_scores_as_numeric_feedback(self) -> None:
        profile = build_map_selector_profile.build_profile(
            [
                {
                    "place": "Failed Place",
                    "type": "stadium",
                    "categories": "sport",
                    "your_score": "fail",
                    "clue_scores": {
                        "hard": "fail",
                        "medium": "pass",
                        "easy": "pass",
                    },
                },
                {
                    "place": "Passed Place",
                    "type": "stadium",
                    "categories": "sport",
                    "your_score": "pass",
                },
            ],
            source_files=[],
        )

        self.assertEqual(profile["place_scores"]["Failed Place"], 0)
        self.assertEqual(profile["place_scores"]["Passed Place"], 10)
        self.assertEqual(profile["clue_level_scores"]["hard"]["mean_score"], 0)
        self.assertEqual(profile["clue_level_scores"]["medium"]["mean_score"], 10)

    def test_selector_profile_dedupes_identical_feedback_rows(self) -> None:
        row = {
            "place": "Alcatraz Island",
            "type": "island",
            "categories": "history",
            "your_score": "",
            "hard_review": {
                "pass_fail": "pass",
                "clue": "A famous prison escape happened here.",
                "reason": "Specific memorable incident.",
            },
        }
        profile = build_map_selector_profile.build_profile([row, dict(row)], source_files=[])

        self.assertEqual(profile["row_count"], 2)
        self.assertEqual(profile["unique_row_count"], 1)
        self.assertEqual(profile["duplicate_row_count"], 1)
        self.assertEqual(profile["hard_clue_review"]["count"], 1)
        self.assertEqual(profile["hard_clue_review"]["pass_count"], 1)

    def test_selector_profile_qualifies_designer_association_passes(self) -> None:
        profile = build_map_selector_profile.build_profile(
            [
                {
                    "place": "Clifton Suspension Bridge",
                    "type": "bridge",
                    "categories": "engineering_industry",
                    "your_score": "",
                    "hard_review": {
                        "pass_fail": "pass",
                        "clue": "Designed by Isambard Kingdom Brunel, it was completed after his death.",
                        "reason": "This feels more about the designer than the bridge. It is famous by association rather than something interesting about the location itself.",
                    },
                }
            ],
            source_files=[],
        )

        hard_review = profile["hard_clue_review"]
        self.assertEqual(hard_review["pass_count"], 1)
        self.assertEqual(hard_review["strong_pass_count"], 0)
        self.assertEqual(hard_review["qualified_pass_count"], 1)
        self.assertEqual(hard_review["qualified_pass_examples"][0]["place"], "Clifton Suspension Bridge")
        self.assertEqual(profile["note_category_counts"]["off_target_fact"], 1)

    def test_selector_profile_qualifies_wording_warning_passes(self) -> None:
        profile = build_map_selector_profile.build_profile(
            [
                {
                    "place": "Brooklyn Bridge",
                    "type": "bridge",
                    "categories": "engineering_industry",
                    "your_score": "",
                    "hard_review": {
                        "pass_fail": "pass",
                        "clue": "During its opening week, a fatal stampede happened here.",
                        "reason": "Pass but I would maybe change its to this bridge's to give the user a better chance to guess it.",
                    },
                }
            ],
            source_files=[],
        )

        hard_review = profile["hard_clue_review"]
        self.assertEqual(hard_review["pass_count"], 1)
        self.assertEqual(hard_review["strong_pass_count"], 0)
        self.assertEqual(hard_review["qualified_pass_count"], 1)
        self.assertEqual(profile["note_category_counts"]["wording_clarity"], 1)

    def test_selector_profile_keeps_qualified_hard_passes_separate(self) -> None:
        profile = build_map_selector_profile.build_profile(
            [
                {
                    "place": "Millau Viaduct",
                    "type": "bridge",
                    "categories": "engineering_industry",
                    "your_score": "",
                    "hard_review": {
                        "pass_fail": "pass",
                        "clue": "This bridge is the tallest in the world.",
                        "reason": "This just passes but it is just data and quite boring.",
                    },
                },
                {
                    "place": "Statue of Liberty",
                    "type": "landmark",
                    "categories": "visual_landmark",
                    "your_score": "",
                    "hard_review": {
                        "pass_fail": "pass",
                        "clue": "This copper statue was a gift from France.",
                        "reason": "This is a bit too vague. Should be about a specific event or incident.",
                    },
                },
                {
                    "place": "Old Trafford",
                    "type": "stadium",
                    "categories": "sport",
                    "your_score": "",
                    "hard_review": {
                        "pass_fail": "pass",
                        "clue": "In 1966, this stadium hosted several matches, including the game where Pelé was injured.",
                        "reason": "The three cup matches line could be dropped and the Pelé injury expanded on.",
                    },
                },
                {
                    "place": "Wembley Stadium",
                    "type": "stadium",
                    "categories": "sport",
                    "your_score": "",
                    "hard_review": {
                        "pass_fail": "pass",
                        "clue": "A famous World Cup hat-trick was completed here in extra time.",
                        "reason": "Strong specific incident and a football fan could work towards the place.",
                    },
                },
            ],
            source_files=[],
        )

        hard_review = profile["hard_clue_review"]
        self.assertEqual(hard_review["pass_count"], 4)
        self.assertEqual(hard_review["strong_pass_count"], 1)
        self.assertEqual(hard_review["qualified_pass_count"], 3)
        self.assertEqual(hard_review["pass_examples"][0]["place"], "Wembley Stadium")
        self.assertEqual(hard_review["qualified_pass_examples"][0]["place"], "Millau Viaduct")
        self.assertEqual(hard_review["qualified_pass_examples"][1]["place"], "Statue of Liberty")
        self.assertEqual(hard_review["qualified_pass_examples"][2]["place"], "Old Trafford")
        self.assertEqual(profile["note_category_counts"]["needs_specific_incident"], 1)

    def test_selector_profile_classifies_ladder_intention_notes(self) -> None:
        profile = build_map_selector_profile.build_profile(
            [
                {
                    "place": "Clifton Suspension Bridge",
                    "type": "bridge",
                    "categories": "engineering_industry",
                    "your_score": 5,
                    "notes": "These seem more about the engineer than the bridge.",
                },
                {
                    "place": "Space Needle",
                    "type": "monument",
                    "categories": "visual_landmark",
                    "your_score": 5,
                    "notes": "No 3 is just stats.",
                },
                {
                    "place": "Test Place",
                    "type": "landmark",
                    "categories": "history",
                    "your_score": 5,
                    "notes": "The clues should narrow the scope so he can work it out and beat the game.",
                },
                {
                    "place": "Another Test Place",
                    "type": "landmark",
                    "categories": "history",
                    "your_score": 3,
                    "notes": "The difficulty progression is wrong and the easy fact is weak.",
                },
                {
                    "place": "Ponte Vecchio",
                    "type": "bridge",
                    "categories": "history",
                    "your_score": 3,
                    "notes": "Medium would have scored higher as a hard clue.",
                },
            ],
            source_files=[],
        )

        self.assertEqual(profile["note_category_counts"]["off_target_fact"], 1)
        self.assertEqual(profile["note_category_counts"]["dry_stat_fact"], 1)
        self.assertEqual(profile["note_category_counts"]["poor_narrowing_ladder"], 1)
        self.assertEqual(profile["note_category_counts"]["bad_difficulty_progression"], 2)
        guidance = " ".join(item["guidance"] for item in profile["note_guidance"])
        self.assertIn("target place", guidance)
        self.assertIn("dry numerical", guidance)
        self.assertIn("narrowing path", guidance)
        self.assertIn("solving value", guidance)

    def test_candidate_generation_prompt_includes_narrowing_ladder_intention(self) -> None:
        prompt = generator.candidate_generation_prompt(
            limit=5,
            existing_places=[],
            existing_name_examples=[],
            blocked_name_examples=[],
            selector_profile={},
            feedback=[],
        )

        self.assertIn("recognition hook -> broad area -> local map route", prompt)
        self.assertIn("Never bundle separate matches or incidents", prompt)
        self.assertIn("Prefer persistent map geography", prompt)
        self.assertIn("event occurred at the exact target place", prompt)
        self.assertIn("One strong incident beats a bundled list of lesser facts", prompt)
        self.assertIn("this bridge", prompt)
        self.assertIn("fun but beatable", prompt)
        self.assertIn("ordered as hard, medium, then easy", prompt)
        self.assertIn("clue-level scores affect how the ladder should be written", prompt)
        self.assertIn("explicitly name the city, town, or municipality", prompt)
        self.assertIn("avoid_in_clues must contain only", prompt)

    def test_candidate_generation_prompt_includes_blocked_names_as_hard_stop(self) -> None:
        prompt = generator.candidate_generation_prompt(
            limit=5,
            existing_places=[],
            existing_name_examples=[],
            blocked_name_examples=["CN Tower", "Petronas Twin Towers"],
            selector_profile={},
            feedback=[],
        )

        self.assertIn("Never return these", prompt)
        self.assertIn("CN Tower", prompt)
        self.assertIn("Petronas Twin Towers", prompt)

    def test_validated_review_rows_accepts_distinct_fun_candidate(self) -> None:
        rows, rejected = generator.validated_review_rows(
            [valid_candidate()],
            existing_names=set(),
            selector_profile={"type_adjustments": {"observation_tower": 6}},
        )

        self.assertEqual(rejected, [])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["canonical_name"], "Blackpool Tower")
        self.assertEqual(row["source"], "ai_candidate")
        self.assertGreaterEqual(row["persuading_fact_count"], 3)
        self.assertIn("visual_landmark", row["categories"])
        self.assertGreaterEqual(row["feedback_adjustment"], 6)
        self.assertNotIn("Blackpool Tower", row["fact_1"])
        self.assertNotIn("Blackpool Tower", row["hard_clue"])
        self.assertEqual(row["hard_clue"], row["fact_1"])
        self.assertEqual(row["medium_clue"], row["fact_2"])
        self.assertEqual(row["easy_clue"], row["fact_3"])
        self.assertEqual(row["reveal_text"], "Blackpool Tower")

    def test_validated_review_rows_attaches_ml_scores_when_model_is_available(self) -> None:
        selector_model = map_selector_model.fit_model(
            [
                {
                    "place": "Blackpool Tower",
                    "your_score": 10,
                    "machine_score": 100,
                    "type": "observation_tower",
                    "difficulty": "easy",
                    "categories": "visual_landmark; engineering_industry",
                    "clues": {
                        "hard": "A steel seaside tower rises above a ballroom and illuminations.",
                        "medium": "Victorian engineers built a landmark for a northwest English seaside resort.",
                        "easy": "Look for the tower on the seafront promenade beside the Irish Sea.",
                    },
                }
            ]
        )

        rows, rejected = generator.validated_review_rows(
            [valid_candidate()],
            existing_names=set(),
            selector_profile={},
            selector_model=selector_model,
        )

        self.assertEqual(rejected, [])
        self.assertIn("ml_score", rows[0])
        self.assertIn("ml_rank_score", rows[0])

    def test_validated_review_rows_rejects_existing_but_allows_named_source_facts(self) -> None:
        duplicate = valid_candidate()
        named_source_fact = valid_candidate()
        named_source_fact["canonical_name"] = "Skellig Michael"
        named_source_fact["acceptable_aliases"] = []
        named_source_fact["fun_facts"] = [
            "Star Wars scenes showing Luke Skywalker's island refuge were filmed on Skellig Michael, bringing its steep monastic steps to a global audience.",
            "Modern film appearances introduced this Atlantic island off Ireland to a global audience.",
            "Look for the jagged island rock rising from the Atlantic off County Kerry.",
        ]

        rows, rejected = generator.validated_review_rows(
            [duplicate, named_source_fact],
            existing_names={generator.normalized_name("Blackpool Tower")},
            selector_profile={},
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["canonical_name"], "Skellig Michael")
        self.assertNotIn("Skellig Michael", rows[0]["fact_1"])
        reasons = " ".join(
            reason
            for item in rejected
            for reason in item.get("reasons", [])
        )
        self.assertIn("already exists", reasons)

    def test_validated_review_rows_can_allow_known_retries_for_beta_review(self) -> None:
        rows, rejected = generator.validated_review_rows(
            [valid_candidate()],
            existing_names={generator.normalized_name("Blackpool Tower")},
            selector_profile={},
            allow_known_retries=True,
        )

        self.assertEqual(rejected, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["canonical_name"], "Blackpool Tower")
        self.assertEqual(rows[0]["source"], "ai_candidate_retry")
        self.assertTrue(rows[0]["existing_retry"])

    def test_validated_review_rows_can_block_known_retry_for_current_batch(self) -> None:
        rows, rejected = generator.validated_review_rows(
            [valid_candidate()],
            existing_names={generator.normalized_name("Blackpool Tower")},
            selector_profile={},
            allow_known_retries=True,
            blocked_names=generator.normalized_name_variants("Blackpool Tower"),
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("blocked" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_leading_article_duplicate(self) -> None:
        candidate = valid_candidate()
        candidate["canonical_name"] = "The Blackpool Tower"

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=generator.normalized_name_variants("Blackpool Tower"),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("already exists" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_generated_name_subset_duplicate(self) -> None:
        first = valid_candidate()
        first["canonical_name"] = "The O2 Arena"
        first["acceptable_aliases"] = []
        first["avoid_in_clues"] = ["O2 Arena"]
        second = valid_candidate()
        second["canonical_name"] = "The O2"
        second["acceptable_aliases"] = []
        second["avoid_in_clues"] = ["O2"]

        rows, rejected = generator.validated_review_rows(
            [first, second],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(len(rows), 1)
        self.assertTrue(
            any("duplicate within this generated batch" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_unique_review_rows_removes_accent_variant_duplicates(self) -> None:
        rows = [
            {"canonical_name": "Maracană Stadium", "interest_score": 10},
            {"canonical_name": "Maracanã Stadium", "interest_score": 9},
            {"canonical_name": "Camp Nou", "interest_score": 8},
        ]

        unique = generator.unique_review_rows(rows)

        self.assertEqual([row["canonical_name"] for row in unique], ["Maracană Stadium", "Camp Nou"])

    def test_candidate_to_pool_row_corrects_known_canonical_spelling(self) -> None:
        candidate = valid_candidate()
        candidate["canonical_name"] = "Maracană Stadium"
        candidate["place_type"] = "stadium"
        candidate["map_guessability"] = "Locate Rio de Janeiro and look for the large circular stadium north of the centre."

        row = generator.candidate_to_pool_row(candidate)

        self.assertEqual(row["canonical_name"], "Maracanã Stadium")

    def test_candidate_to_pool_row_decodes_html_entities_in_clues(self) -> None:
        candidate = valid_candidate()
        candidate["fun_facts"] = [
            "A steel seaside tower rises above a ballroom, circus arena, and glowing illuminations.",
            "Victorian engineers built a steel landmark for a northwest English seaside resort.",
            "It overlooks the Albaic&iacute;n district beside a river and old city.",
        ]

        row = generator.candidate_to_pool_row(candidate)

        self.assertIn("Albaicín", row["easy_clue_text"])
        self.assertNotIn("&iacute;", row["easy_clue_text"])

    def test_validated_review_rows_rejects_text_encoding_artifacts(self) -> None:
        candidate = valid_candidate()
        candidate["canonical_name"] = "Estadio Santiago Bernab\u0090u"
        candidate["place_type"] = "stadium"
        candidate["acceptable_aliases"] = []
        candidate["avoid_in_clues"] = ["Estadio Santiago Bernabeu"]
        candidate["map_guessability"] = "Locate Madrid and look for the rectangular stadium beside Paseo de la Castellana."

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("encoding artifacts" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_can_exclude_focused_place_types(self) -> None:
        rows, rejected = generator.validated_review_rows(
            [valid_candidate()],
            existing_names=set(),
            selector_profile={},
            excluded_place_types={"observation_tower"},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("excluded" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_one_word_map_guessability(self) -> None:
        candidate = valid_candidate()
        candidate["map_guessability"] = "high"

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("work out where to look" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_easy_clue_without_map_anchor(self) -> None:
        candidate = valid_candidate()
        candidate["fun_facts"] = [
            "A steel seaside tower rises above a ballroom, circus arena, and glowing illuminations.",
            "Victorian engineers opened the structure in 1894 after being inspired by Paris ironwork.",
            "The annual light festival turns the promenade into miles of illuminated displays.",
        ]

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("easy clue" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_medium_clue_without_scope_narrowing(self) -> None:
        candidate = valid_candidate()
        candidate["fun_facts"] = [
            "A steel seaside tower rises above a ballroom, circus arena, and glowing illuminations.",
            "It has hosted numerous famous ceremonies and memorable public spectacles.",
            "Look for the tower on the seafront promenade where the annual light festival runs beside the Irish Sea.",
        ]

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("medium clue" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_medium_clue_that_is_map_instruction(self) -> None:
        candidate = valid_candidate()
        candidate["fun_facts"] = [
            "A steel seaside tower rises above a ballroom, circus arena, and glowing illuminations.",
            "Look for it on the northwest English seafront promenade beside the Irish Sea.",
            "Look for the tower on the seafront promenade where the annual light festival runs beside the Irish Sea.",
        ]

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("map instruction" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_hard_clue_that_is_map_instruction(self) -> None:
        candidate = valid_candidate()
        candidate["fun_facts"] = [
            "Look for the tower on the seafront promenade where the annual light festival runs beside the Irish Sea.",
            "Victorian engineers built a steel landmark for a northwest English seaside resort.",
            "Find the Irish Sea coast, then target the tower on the resort's central seafront promenade.",
        ]

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("hard clue" in reason and "map instruction" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_hard_clue_without_distinctive_hook(self) -> None:
        candidate = valid_candidate()
        candidate["fun_facts"] = [
            "It is located in a large city near a river and a busy central district.",
            "Victorian engineers built a steel landmark for a northwest English seaside resort.",
            "Look for the tower on the seafront promenade where the annual light festival runs beside the Irish Sea.",
        ]

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("hard clue needs" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_hard_clue_based_on_former_height_record(self) -> None:
        candidate = valid_candidate()
        candidate["fun_facts"] = [
            "Once the tallest free-standing structure in the world, it remains a defining feature of the city's skyline.",
            "Victorian engineers built a steel landmark for a northwest English seaside resort.",
            "Look for the tower on the seafront promenade where the annual light festival runs beside the Irish Sea.",
        ]

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("former height record" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_stale_record_hard_clue(self) -> None:
        candidate = valid_candidate()
        candidate["fun_facts"] = [
            "Historically held the world record for the highest attendance at a football match.",
            "Victorian engineers built a steel landmark for a northwest English seaside resort.",
            "Look for the tower on the seafront promenade where the annual light festival runs beside the Irish Sea.",
        ]

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("stale record" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_comparison_hard_clue(self) -> None:
        candidate = valid_candidate()
        candidate["fun_facts"] = [
            "Often compared to the Golden Gate Bridge due to its red colour and suspension design.",
            "Victorian engineers built a steel landmark for a northwest English seaside resort.",
            "Look for the tower on the seafront promenade where the annual light festival runs beside the Irish Sea.",
        ]

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("comparison" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_generic_skyline_hard_clue(self) -> None:
        candidate = valid_candidate()
        candidate["fun_facts"] = [
            "This famous tower remains a defining feature of the city's skyline.",
            "Victorian engineers built a steel landmark for a northwest English seaside resort.",
            "Look for the tower on the seafront promenade where the annual light festival runs beside the Irish Sea.",
        ]

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("skyline" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_generic_recognisability_hard_clue(self) -> None:
        candidate = valid_candidate()
        candidate["canonical_name"] = "Tower Bridge"
        candidate["place_type"] = "bridge"
        candidate["acceptable_aliases"] = []
        candidate["avoid_in_clues"] = ["Tower Bridge"]
        candidate["map_guessability"] = "Find central London and look for the two-towered bridge beside the Tower of London."
        candidate["fun_facts"] = [
            "This Victorian bascule bridge is one of the most recognizable structures in the world.",
            "It spans the River Thames in central London beside a historic fortress.",
            "Look just downstream from the City of London near the HMS Belfast museum ship.",
        ]

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("recognisability" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_colour_only_hard_clue(self) -> None:
        candidate = valid_candidate()
        candidate["canonical_name"] = "Golden Gate Bridge"
        candidate["place_type"] = "bridge"
        candidate["acceptable_aliases"] = []
        candidate["avoid_in_clues"] = ["Golden Gate Bridge"]
        candidate["map_guessability"] = "Find San Francisco Bay and look for the bridge across the narrow ocean entrance."
        candidate["fun_facts"] = [
            "Its signature International Orange colour was chosen to improve visibility in thick fog.",
            "The suspension bridge connects the northern tip of the San Francisco Peninsula to Marin County.",
            "It spans the narrow ocean entrance into San Francisco Bay.",
        ]

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("colour or paint" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_generic_prison_island_hard_clue(self) -> None:
        candidate = valid_candidate()
        candidate["canonical_name"] = "Alcatraz Island"
        candidate["place_type"] = "island"
        candidate["acceptable_aliases"] = []
        candidate["avoid_in_clues"] = ["Alcatraz Island"]
        candidate["map_guessability"] = "Find San Francisco Bay and look for the small island between the waterfront piers and the Golden Gate."
        candidate["fun_facts"] = [
            "This small island once housed a maximum-security federal penitentiary known for holding notorious criminals.",
            "It sits in the middle of a cold-water bay with strong currents.",
            "Look offshore from the famous waterfront piers of a major West Coast city.",
        ]

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("specific prison story" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_repeated_bridge_span_ladder(self) -> None:
        candidate = valid_candidate()
        candidate["canonical_name"] = "Golden Gate Bridge"
        candidate["place_type"] = "bridge"
        candidate["acceptable_aliases"] = []
        candidate["avoid_in_clues"] = ["Golden Gate Bridge"]
        candidate["map_guessability"] = "Find San Francisco Bay and look for the bridge across the narrow ocean entrance."
        candidate["fun_facts"] = [
            "Engineers built a major suspension bridge through heavy fog, ocean winds, and dangerous tidal currents.",
            "The bridge connects the northern tip of the San Francisco Peninsula to Marin County.",
            "It spans the narrow strait that serves as the entrance from the Pacific Ocean into the bay.",
        ]

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("both describe the span" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_easy_clue_less_map_useful_than_hard(self) -> None:
        candidate = valid_candidate()
        candidate["fun_facts"] = [
            "A visible steel seaside tower rises above the seafront promenade beside the Irish Sea illuminations.",
            "Victorian engineers built a steel landmark for a northwest English seaside resort.",
            "The annual light festival turns the promenade into miles of illuminated displays.",
        ]

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("easy clue should be more map-useful" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_unstable_venue_names(self) -> None:
        candidate = valid_candidate()
        candidate["canonical_name"] = "Wanda Metropolitano"
        candidate["place_type"] = "stadium"
        candidate["acceptable_aliases"] = []
        candidate["avoid_in_clues"] = ["Wanda Metropolitano"]
        candidate["map_guessability"] = "Look for the distinct oval stadium in eastern Madrid beside the M-40 motorway."

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("sponsor-style" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_awkward_masked_fact_wording(self) -> None:
        candidate = valid_candidate()
        candidate["canonical_name"] = "San Mames Stadium"
        candidate["acceptable_aliases"] = ["The Cathedral"]
        candidate["avoid_in_clues"] = ["San Mames Stadium"]
        candidate["map_guessability"] = "Look for the glowing stadium beside the Nervion River in Bilbao."
        candidate["fun_facts"] = [
            "Known as The Cathedral of football, it has a fierce local atmosphere.",
            "The stadium facade uses thousands of glowing panels.",
            "It replaced an older ground on the same city site.",
        ]

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("awkward masked" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_the_this_place_masked_wording(self) -> None:
        candidate = valid_candidate()
        candidate["canonical_name"] = "Old Trafford"
        candidate["place_type"] = "stadium"
        candidate["acceptable_aliases"] = ["Theatre of Dreams"]
        candidate["avoid_in_clues"] = ["Old Trafford"]
        candidate["map_guessability"] = "Locate Manchester, then look southwest of the city centre near the Manchester Ship Canal."
        candidate["fun_facts"] = [
            "Known globally as the Theatre of Dreams, a nickname coined by Bobby Charlton.",
            "During World War II, the venue was heavily damaged by German bombing raids.",
            "It is the largest club football stadium in the United Kingdom.",
        ]

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("awkward masked" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_known_as_this_place_masked_wording(self) -> None:
        candidate = valid_candidate()
        candidate["canonical_name"] = "Old Trafford"
        candidate["place_type"] = "stadium"
        candidate["acceptable_aliases"] = ["Theatre of Dreams"]
        candidate["avoid_in_clues"] = ["Old Trafford", "Theatre of Dreams"]
        candidate["map_guessability"] = "Locate Manchester, then look southwest of the city centre near the Manchester Ship Canal."
        candidate["fun_facts"] = [
            "Known as the Theatre of Dreams, this stadium has hosted many legendary matches and international events.",
            "It is located in the Trafford borough, near the Manchester Ship Canal.",
            "Look for the massive rectangular stadium structure west of central Manchester.",
        ]

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("awkward masked" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_this_is_this_place_masked_wording(self) -> None:
        candidate = valid_candidate()
        candidate["canonical_name"] = "Anfield"
        candidate["place_type"] = "stadium"
        candidate["acceptable_aliases"] = []
        candidate["avoid_in_clues"] = ["Anfield", "This Is Anfield"]
        candidate["map_guessability"] = "Find Liverpool, then look for the stadium just east of Stanley Park."
        candidate["fun_facts"] = [
            "The stadium is famous for the This Is Anfield sign players pass before walking onto the pitch.",
            "It was originally used by Everton before Liverpool moved in.",
            "It sits in north Liverpool near Stanley Park.",
        ]

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("awkward masked" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_called_this_place_masked_wording(self) -> None:
        candidate = valid_candidate()
        candidate["canonical_name"] = "Sydney Harbour Bridge"
        candidate["place_type"] = "bridge"
        candidate["acceptable_aliases"] = ["Coathanger"]
        candidate["avoid_in_clues"] = ["Sydney Harbour Bridge", "Coathanger"]
        candidate["map_guessability"] = "Find Sydney Harbour and look for the large arch bridge beside the Opera House."
        candidate["fun_facts"] = [
            "Locals call this steel arch bridge the Coathanger because of its distinct shape.",
            "It spans Sydney Harbour between the central business district and the North Shore.",
            "Look for the bridge beside the Opera House on the harbour skyline.",
        ]

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("awkward masked" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_translates_to_this_place_masked_wording(self) -> None:
        candidate = valid_candidate()
        candidate["canonical_name"] = "Estadio do Dragao"
        candidate["place_type"] = "stadium"
        candidate["acceptable_aliases"] = ["Dragao"]
        candidate["avoid_in_clues"] = ["Estadio do Dragao", "Dragao"]
        candidate["map_guessability"] = "Locate Porto and look for the stadium near the main highway interchange east of the city centre."
        candidate["fun_facts"] = [
            "The stadium's name translates to Dragao, matching the creature on the club crest.",
            "Built for the 2004 European Championship, it is located in the eastern part of Porto.",
            "Look for the stadium near the main highway interchange that connects the city to the north.",
        ]

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("awkward masked" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_hyphenated_partial_name_mask(self) -> None:
        candidate = valid_candidate()
        candidate["canonical_name"] = "Fenway Park"
        candidate["place_type"] = "stadium"
        candidate["acceptable_aliases"] = ["Fenway"]
        candidate["avoid_in_clues"] = ["Fenway Park", "Fenway"]
        candidate["map_guessability"] = "Locate Boston, then look for the ballpark in the dense street grid near the Charles River."
        candidate["fun_facts"] = [
            "The oldest active ballpark in Major League Baseball is famous for a towering left-field wall.",
            "The venue sits in Boston and is tightly fitted into a dense neighbourhood street grid.",
            "It is located a few blocks from the Charles River in the Fenway-Kenmore district.",
        ]

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("awkward masked" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_validated_review_rows_rejects_non_current_map_targets(self) -> None:
        candidate = valid_candidate()
        candidate["canonical_name"] = "The Dome of Discovery"
        candidate["place_type"] = "monument"
        candidate["acceptable_aliases"] = []
        candidate["avoid_in_clues"] = ["The Dome of Discovery"]
        candidate["fun_facts"] = [
            "The centerpiece of a major post-war exhibition was the largest dome in the world at the time.",
            "The structure showcased science and industry after the war.",
            "Though dismantled, its legacy remains a symbol of post-war optimism and modern design.",
        ]

        rows, rejected = generator.validated_review_rows(
            [candidate],
            existing_names=set(),
            selector_profile={},
        )

        self.assertEqual(rows, [])
        self.assertTrue(
            any("non-current" in reason for item in rejected for reason in item.get("reasons", []))
        )

    def test_inserted_machine_candidates_enter_learned_rotation(self) -> None:
        rows, rejected = generator.validated_review_rows(
            [valid_candidate()],
            existing_names=set(),
            selector_profile={},
        )
        self.assertFalse(rejected)
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL)")
            daily_map_game.initialize_database(conn)
            inserted = generator.insert_draft_rows(conn, rows)
            conn.commit()
            stored = conn.execute(
                "SELECT review_status, active, verified_facts_json FROM map_place_pool WHERE canonical_name = ?",
                ("Blackpool Tower",),
            ).fetchone()
        finally:
            conn.close()

        self.assertEqual(inserted, 1)
        self.assertIsNotNone(stored)
        self.assertEqual(stored["review_status"], "machine_candidate")
        self.assertEqual(stored["active"], 1)
        self.assertEqual(len(json.loads(stored["verified_facts_json"])), 3)

    def test_insert_draft_rows_refreshes_known_retry_without_moving_target(self) -> None:
        initial_rows, rejected = generator.validated_review_rows(
            [valid_candidate()],
            existing_names=set(),
            selector_profile={},
        )
        self.assertFalse(rejected)
        retry_rows, rejected = generator.validated_review_rows(
            [valid_candidate()],
            existing_names={generator.normalized_name("Blackpool Tower")},
            selector_profile={},
            allow_known_retries=True,
        )
        self.assertFalse(rejected)
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL)")
            daily_map_game.initialize_database(conn)
            generator.insert_draft_rows(conn, initial_rows)
            conn.execute(
                """
                UPDATE map_place_pool
                SET lat = 1.25,
                    lng = 2.5,
                    clue_text = 'Old clue'
                WHERE canonical_name = 'Blackpool Tower'
                """
            )
            inserted = generator.insert_draft_rows(conn, retry_rows)
            conn.commit()
            stored = conn.execute(
                """
                SELECT COUNT(*) AS count, lat, lng, clue_text, review_status
                FROM map_place_pool
                WHERE canonical_name = ?
                """,
                ("Blackpool Tower",),
            ).fetchone()
        finally:
            conn.close()

        self.assertEqual(inserted, 1)
        self.assertEqual(stored["count"], 1)
        self.assertEqual(stored["lat"], 1.25)
        self.assertEqual(stored["lng"], 2.5)
        self.assertNotEqual(stored["clue_text"], "Old clue")
        self.assertEqual(stored["review_status"], "machine_candidate")

    def test_selector_profile_default_reads_all_saved_feedback_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = root / "map_place_review_feedback_20260719T100000Z.json"
            second = root / "map_place_review_feedback_20260719T110000Z.json"
            first.write_text(
                json.dumps({"rows": [{"place": "A", "your_score": 10}]}),
                encoding="utf-8",
            )
            second.write_text(
                json.dumps({"rows": [{"place": "B", "your_score": 0}]}),
                encoding="utf-8",
            )

            files = build_map_selector_profile.latest_feedback_files(root)

        self.assertEqual([path.name for path in files], [first.name, second.name])

    def test_reviewed_feedback_place_names_reads_all_saved_review_places(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "map_place_review_feedback_20260719T100000Z.json").write_text(
                json.dumps(
                    {
                        "rows": [
                            {"place": "The O2 Arena", "your_score": 5},
                            {"place": "The O2 Arena", "your_score": 8},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (root / "map_place_review_feedback_20260719T110000Z.json").write_text(
                json.dumps({"rows": [{"place": "Royal Observatory, Greenwich", "your_score": 10}]}),
                encoding="utf-8",
            )

            names = generator.reviewed_feedback_place_names(root)

        self.assertEqual(names, ["The O2 Arena", "Royal Observatory, Greenwich"])

    def test_review_page_shows_fact_and_playable_clue_use(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            page_path = Path(tmpdir) / "review.html"
            review_export.write_review_page(
                page_path,
                [
                    {
                        "canonical_name": "Test Bridge",
                        "place_type": "bridge",
                        "difficulty": "medium",
                        "country_name": "Testland",
                        "admin1": "Testshire",
                        "interest_score": 100,
                        "base_score": 90,
                        "feedback_adjustment": 10,
                        "categories": "engineering_industry; visual_landmark",
                        "fact_1": "A source fact about the bridge.",
                        "fact_2": "A second source fact about the bridge.",
                        "fact_3": "A third source fact about the bridge.",
                        "hard_clue": "A hard playable clue about the bridge.",
                        "medium_clue": "A medium playable clue about the bridge.",
                        "easy_clue": "An easy playable clue about the bridge.",
                        "reveal_text": "Test Bridge",
                    }
                ],
            )

            html = page_path.read_text(encoding="utf-8")

        self.assertIn('"clueUses"', html)
        self.assertIn("Fact", html)
        self.assertIn("Used as", html)
        self.assertIn("Clue", html)
        self.assertIn("Pass", html)
        self.assertIn("Fail", html)
        self.assertIn("hard_review", html)
        self.assertIn("review_phase", html)
        self.assertNotIn("Clue score", html)
        self.assertNotIn("Overall", html)
        self.assertIn("A source fact about the bridge.", html)
        self.assertIn("A hard playable clue about the bridge.", html)


if __name__ == "__main__":
    unittest.main()
