import json
import sqlite3
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from tools import (
    generate_ai_daily_map_round,
    generate_ai_map_review_batch,
    generate_map_place_candidates_with_ai,
    training_data_store,
)


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


class EventPlaceVerificationProvider:
    def __init__(self, *, passed: bool = True) -> None:
        self.passed = passed
        self.tools = []
        self.prompt = ""

    def call_with_fallback(self, **kwargs):
        self.tools = list(kwargs.get("tools") or [])
        self.prompt = str(kwargs.get("prompt") or "")
        return {
            "passed": self.passed,
            "confidence": 96,
            "failure_reasons": [] if self.passed else ["The match occurred at another stadium."],
            "used_source_urls": ["https://example.com/match-record"],
        }


class FallbackEventPlaceVerificationProvider(EventPlaceVerificationProvider):
    def call_with_fallback(self, **kwargs):
        if kwargs.get("tools"):
            raise RuntimeError("Grounded provider quota exhausted.")
        self.tools = []
        self.prompt = str(kwargs.get("prompt") or "")
        return {
            "passed": True,
            "confidence": 96,
            "failure_reasons": [],
            "used_source_urls": ["https://en.wikipedia.org/?curid=42"],
        }


class AiDailyMapRoundTests(unittest.TestCase):
    def test_discovery_resolves_retry_name_variant_to_existing_place_id(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        generate_ai_daily_map_round.daily_map_game.initialize_database(conn)
        row = conn.execute(
            "SELECT id FROM map_place_pool WHERE canonical_name = 'London'"
        ).fetchone()
        self.assertIsNotNone(row)
        place_id = int(row["id"])
        conn.execute(
            "UPDATE map_place_pool SET canonical_name = ?, acceptable_aliases = ? WHERE id = ?",
            ("Estádio do Maracanã", "Maracana Stadium", place_id),
        )
        accepted = [
            {
                "canonical_name": "Maracana Stadium",
                "_pool_row": {
                    "slug": "generated-retry-name",
                    "canonical_name": "Maracana Stadium",
                    "acceptable_aliases": "Maracanã",
                },
            }
        ]

        resolved = generate_ai_daily_map_round.resolve_candidate_place_ids(
            conn,
            accepted,
            normalized_name_variants=(
                generate_map_place_candidates_with_ai.normalized_name_variants
            ),
        )

        self.assertEqual(resolved, [place_id])

    def test_discovery_blocks_explicitly_excluded_places(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            db_path = Path(temporary_directory) / "map.db"
            conn = sqlite3.connect(db_path)
            generate_ai_daily_map_round.daily_map_game.initialize_database(conn)
            conn.close()
            discovery = {
                "accepted": [{"canonical_name": "Fresh Place"}],
                "attempts": [],
                "rejected": [],
            }
            with patch(
                "tools.generate_map_place_candidates_with_ai.generate_review_batch",
                return_value=discovery,
            ) as generate_batch, patch(
                "tools.generate_map_place_candidates_with_ai.insert_draft_rows",
                return_value=1,
            ):
                result = generate_ai_daily_map_round.discover_uncurated_candidates(
                    db_path=db_path,
                    provider=FakeProvider("fresh"),
                    puzzle_date="2026-08-01",
                    count=4,
                    max_attempts=2,
                    excluded_names={"Rejected Stadium"},
                )

        call = generate_batch.call_args.kwargs
        self.assertIn("Rejected Stadium", call["blocked_name_examples"])
        self.assertIn("rejectedstadium", call["blocked_names"])
        self.assertEqual(result["candidate_names"], ["fresh place"])

    def test_discovery_keeps_only_the_required_place_type(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            db_path = Path(temporary_directory) / "map.db"
            conn = sqlite3.connect(db_path)
            generate_ai_daily_map_round.daily_map_game.initialize_database(conn)
            conn.close()
            discovery = {
                "accepted": [
                    {"canonical_name": "Final Stadium", "place_type": "stadium"},
                    {"canonical_name": "Famous Palace", "place_type": "palace"},
                ],
                "attempts": [],
                "rejected": [],
            }
            with patch(
                "tools.generate_map_place_candidates_with_ai.generate_review_batch",
                return_value=discovery,
            ) as generate_batch, patch(
                "tools.generate_map_place_candidates_with_ai.insert_draft_rows",
                return_value=1,
            ) as insert_rows:
                result = generate_ai_daily_map_round.discover_uncurated_candidates(
                    db_path=db_path,
                    provider=FakeProvider("stadium"),
                    puzzle_date="2026-08-01",
                    count=4,
                    max_attempts=2,
                    required_place_type="stadium",
                )

        self.assertIn("Return only stadium places", generate_batch.call_args.kwargs["focus"])
        self.assertEqual(
            insert_rows.call_args.args[1],
            [{"canonical_name": "Final Stadium", "place_type": "stadium"}],
        )
        self.assertEqual(result["candidate_names"], ["final stadium"])
        self.assertEqual(result["wrong_type_count"], 1)

    def test_event_brief_rejects_a_generic_site_that_drops_target_identity(self) -> None:
        selected_hook = {
            "verified_hard_hook": (
                "In 1962, three inmates executed a daring escape using makeshift "
                "rafts, a mystery that remains unsolved."
            )
        }
        place = {
            "canonical_name": "Alcatraz Island",
            "place_type": "island",
            "acceptable_aliases": ["Alcatraz"],
            "verified_facts": [selected_hook["verified_hard_hook"]],
            "validation_reasoning": (
                "The history of the prison and the escape make this compelling."
            ),
        }
        payload = {
            "enriched_hard_hook": (
                "In 1962, Frank Morris and the Anglin brothers escaped from this "
                "site using a raft made from raincoats, leaving a mystery that "
                "remains unsolved."
            ),
            "supporting_details": ["The raft was made from raincoats."],
            "used_source_urls": ["https://www.nps.gov/alca/"],
            "confidence": 95,
        }

        with self.assertRaisesRegex(ValueError, "missing island, prison"):
            generate_ai_daily_map_round.validate_event_brief(
                payload,
                selected_hook,
                place=place,
            )

    def test_wikipedia_verification_searches_event_before_venue(self) -> None:
        requests = []

        class FakeResponse:
            def __init__(self, payload) -> None:
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def read(self) -> bytes:
                import json

                return json.dumps(self.payload).encode("utf-8")

        def fake_urlopen(request, timeout):
            from urllib.parse import parse_qs, urlparse

            del timeout
            query = parse_qs(urlparse(request.full_url).query)
            requests.append(query)
            if query.get("list") == ["search"]:
                search_text = query["srsearch"][0]
                if search_text == "Eden Gardens":
                    page_id = 30
                    title = "Eden Gardens"
                elif search_text.startswith('"Eden Gardens"'):
                    page_id = 20
                    title = "Eden Gardens events"
                else:
                    page_id = 10
                    title = "1987 Cricket World Cup final"
                return FakeResponse(
                    {"query": {"search": [{"pageid": page_id, "title": title, "snippet": title}]}}
                )
            return FakeResponse(
                {
                    "query": {
                        "pages": [
                            {
                                "pageid": 10,
                                "title": "1987 Cricket World Cup final",
                                "extract": "Australia defeated England at Eden Gardens.",
                            },
                            {
                                "pageid": 20,
                                "title": "Eden Gardens events",
                                "extract": "The venue hosted major cricket finals.",
                            },
                            {
                                "pageid": 30,
                                "title": "Eden Gardens",
                                "extract": "Eden Gardens is a cricket ground.",
                            },
                        ]
                    }
                }
            )

        with patch.object(generate_ai_daily_map_round, "urlopen", side_effect=fake_urlopen):
            evidence = generate_ai_daily_map_round.wikipedia_verification_evidence(
                {
                    "verified_hard_hook": (
                        "Australia secured the 1987 Cricket World Cup by defeating "
                        "England at this ground."
                    )
                },
                {
                    "enriched_hard_hook": (
                        "Australia defeated England by seven runs here in the 1987 final."
                    )
                },
                place={"canonical_name": "Eden Gardens"},
            )

        search_requests = [item["srsearch"][0] for item in requests if "srsearch" in item]
        self.assertIn("Australia", search_requests[0])
        self.assertEqual(search_requests[-1], "Eden Gardens")
        self.assertEqual(evidence[0]["title"], "1987 Cricket World Cup final")

    def test_reverse_geocoded_locality_uses_a_low_zoom_city_anchor(self) -> None:
        with patch.object(
            generate_ai_daily_map_round.daily_map_game,
            "fetch_reverse_geocode",
            return_value={
                "name": "Barcelona",
                "address": {
                    "city": "Barcelona",
                    "county": "Barcelones",
                    "state": "Catalonia",
                },
            },
        ) as reverse:
            locality = generate_ai_daily_map_round.reverse_geocoded_locality(
                {"lat": 41.3809, "lng": 2.1228}
            )

        self.assertEqual(locality, "Barcelona")
        reverse.assert_called_once_with(41.3809, 2.1228, 10)

    def test_reverse_geocoded_locality_normalizes_an_administrative_city_name(self) -> None:
        with patch.object(
            generate_ai_daily_map_round.daily_map_game,
            "fetch_reverse_geocode",
            return_value={
                "name": "London Borough of Brent",
                "address": {
                    "city_district": "London Borough of Brent",
                    "city": "Greater London",
                    "state": "England",
                },
            },
        ):
            locality = generate_ai_daily_map_round.reverse_geocoded_locality(
                {"lat": 51.556, "lng": -0.2795}
            )

        self.assertEqual(locality, "London")

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

    def test_event_brief_prompt_requires_separate_events_to_stay_separate(self) -> None:
        prompt = generate_ai_daily_map_round.event_brief_prompt(
            {
                "verified_hard_hook": "This stadium hosted two famous finals.",
                "source_urls": ["https://example.com/stadium"],
            },
            place={"canonical_name": "Example Stadium"},
        )

        self.assertIn("Never merge separate matches or incidents", prompt)
        self.assertIn("exact competition stage", prompt)

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

    def test_learned_selector_skips_a_low_recognisability_candidate(self) -> None:
        hooks = [
            {
                "hook_id": "42:low",
                "place_id": 42,
                "place": "Niche Palace",
                "learned_score": 2.83,
                "learned_confidence": 0.934,
                "selector_score": 32,
            },
            {
                "hook_id": "43:good",
                "place_id": 43,
                "place": "Recognisable Landmark",
                "learned_score": 5.2,
                "learned_confidence": 0.94,
                "selector_score": 96,
            },
        ]

        selected, _reason = generate_ai_daily_map_round.choose_learned_hard_hook(hooks)

        self.assertEqual(selected["place_id"], 43)

    def test_learned_selector_does_not_let_legacy_heuristic_veto_a_strong_model_score(self) -> None:
        hooks = [
            {
                "hook_id": "42:strong",
                "place_id": 42,
                "place": "Strong Learned Candidate",
                "learned_score": 7.924,
                "learned_confidence": 0.947,
                "selector_score": 75,
            }
        ]

        selected, _reason = generate_ai_daily_map_round.choose_learned_hard_hook(hooks)

        self.assertEqual(selected["place_id"], 42)

    def test_learned_selector_fails_closed_when_only_niche_hooks_remain(self) -> None:
        with self.assertRaisesRegex(LookupError, "minimum human-learned recognisability"):
            generate_ai_daily_map_round.choose_learned_hard_hook(
                [
                    {
                        "hook_id": "42:low",
                        "place_id": 42,
                        "place": "Niche Palace",
                        "learned_score": 2.83,
                        "learned_confidence": 0.934,
                        "selector_score": 32,
                    }
                ]
            )

    def test_recent_place_ids_excludes_the_existing_round_when_regenerating(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        generate_ai_daily_map_round.daily_map_game.initialize_database(conn)
        place_id = conn.execute(
            "SELECT id FROM map_place_pool WHERE canonical_name = 'London'"
        ).fetchone()["id"]
        puzzle_id = conn.execute(
            """
            INSERT INTO daily_map_puzzles (
                puzzle_date, status, generated_at, published_at
            )
            VALUES ('2026-07-30', 'published', '2026-07-30', '2026-07-30')
            """
        ).lastrowid
        conn.execute(
            """
            INSERT INTO daily_map_levels (
                puzzle_id, level_slug, place_id, max_points, lambda_km, created_at
            )
            VALUES (?, 'easy', ?, 10, 1800, '2026-07-30')
            """,
            (puzzle_id, place_id),
        )

        recent = generate_ai_daily_map_round.recent_place_ids(conn, "2026-07-30")

        self.assertIn(place_id, recent)

    def test_candidate_shortlist_excludes_explicitly_seen_place_names(self) -> None:
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

        candidates = generate_ai_daily_map_round.candidate_shortlist(
            conn,
            puzzle_date="2026-07-31",
            eligible_names={"london"},
            excluded_names={"london"},
        )

        self.assertEqual(candidates, [])

    def test_candidate_shortlist_uses_resolved_ids_over_generated_name_variants(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        generate_ai_daily_map_round.daily_map_game.initialize_database(conn)
        hook = (
            "Uruguay beat host nation Brazil 2-1 in the decisive 1950 World Cup "
            "match here, an upset known as the Maracanazo."
        )
        row = conn.execute(
            "SELECT id FROM map_place_pool WHERE canonical_name = 'London'"
        ).fetchone()
        self.assertIsNotNone(row)
        place_id = int(row["id"])
        conn.execute(
            """
            UPDATE map_place_pool
            SET canonical_name = 'Estádio do Maracanã',
                verified_facts_json = ?,
                nearby_context = 'Maracana district, Rio de Janeiro, Brazil'
            WHERE id = ?
            """,
            (json.dumps([hook]), place_id),
        )

        candidates = generate_ai_daily_map_round.candidate_shortlist(
            conn,
            puzzle_date="2026-08-20",
            eligible_place_ids={place_id},
            eligible_names={"maracana stadium"},
        )

        self.assertEqual([candidate["place_id"] for candidate in candidates], [place_id])

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
                generate_ai_daily_map_round,
                "verify_event_place_connection",
                return_value={
                    "passed": True,
                    "confidence": 96,
                    "failure_reasons": [],
                    "used_source_urls": ["https://example.com/verified"],
                },
            ),
            patch.object(
                generate_ai_daily_map_round,
                "reverse_geocoded_locality",
                side_effect=["London", "Paris"],
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
                generate_ai_daily_map_round,
                "build_verified_map_search_anchors",
                return_value=[
                    {
                        "name": "Paris",
                        "lat": 48.8566,
                        "lng": 2.3522,
                        "min_hint_count": 2,
                    }
                ],
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

    def test_map_search_anchor_uses_named_locality_near_answer(self) -> None:
        place = {
            "canonical_name": "Camp Nou",
            "acceptable_aliases": ["Nou Camp"],
            "country_code": "ES",
            "country_name": "Spain",
            "admin1": "Catalonia",
            "lat": 41.3809,
            "lng": 2.1228,
        }
        result = {
            "lat": "41.3829",
            "lon": "2.1774",
            "display_name": "Barcelona, Catalonia, Spain",
            "importance": 0.8,
            "address": {
                "city": "Barcelona",
                "state": "Catalonia",
                "country_code": "es",
            },
            "geojson": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [2.05, 41.32],
                        [2.23, 41.32],
                        [2.23, 41.47],
                        [2.05, 41.47],
                        [2.05, 41.32],
                    ]
                ],
            },
        }
        broader_result = {
            "lat": "41.3809",
            "lon": "2.1228",
            "display_name": "Barcelona, Catalonia, Spain",
            "address": {
                "county": "Barcelona",
                "state": "Catalonia",
                "country_code": "es",
            },
            "geojson": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [1.5, 40.9],
                        [2.8, 40.9],
                        [2.8, 42.0],
                        [1.5, 42.0],
                        [1.5, 40.9],
                    ]
                ],
            },
        }
        point_result = {
            "lat": "41.3809",
            "lon": "2.1228",
            "display_name": "Barcelona, Catalonia, Spain",
            "importance": 0.95,
            "address": {
                "city": "Barcelona",
                "state": "Catalonia",
                "country_code": "es",
            },
            "geojson": {
                "type": "Point",
                "coordinates": [2.1228, 41.3809],
            },
        }
        with patch.object(
            generate_ai_daily_map_round.daily_map_game,
            "fetch_forward_geocode",
            return_value=[point_result, broader_result, result],
        ) as geocode:
            anchors = generate_ai_daily_map_round.build_verified_map_search_anchors(
                place,
                {
                    "hard": "A famous comeback happened on this pitch.",
                    "medium": "Its resident club represents Catalonia.",
                    "easy": "In western Barcelona, search north of a major avenue.",
                    "reveal": "This is Camp Nou.",
                },
                locality_name="Barcelona",
            )

        self.assertEqual(anchors[0]["name"], "Catalonia")
        self.assertEqual(anchors[0]["min_hint_count"], 1)
        self.assertEqual(anchors[0]["max_zoom"], 9)
        self.assertEqual(anchors[0]["boundary"]["type"], "Polygon")
        self.assertEqual(anchors[0]["boundary_kind"], "guidance")
        self.assertTrue(
            generate_ai_daily_map_round.map_boundary_contains_point(
                anchors[0]["boundary"],
                lat=place["lat"],
                lng=place["lng"],
            )
        )
        self.assertEqual(
            anchors[2],
            {
                "name": "Camp Nou",
                "lat": 41.3809,
                "lng": 2.1228,
                "min_hint_count": 2,
                "min_zoom": 12,
                "max_zoom": 19,
            },
        )
        self.assertEqual(anchors[1]["name"], "Barcelona")
        self.assertEqual(anchors[1]["min_hint_count"], 2)
        self.assertAlmostEqual(anchors[1]["lat"], 41.3829)
        self.assertEqual(anchors[1]["boundary_kind"], "administrative")
        self.assertEqual(anchors[1]["boundary_min_zoom"], 5)
        self.assertEqual(geocode.call_count, 2)

    def test_medium_map_anchor_can_precede_easy_locality_anchor(self) -> None:
        place = {
            "canonical_name": "Example Stadium",
            "acceptable_aliases": [],
            "country_code": "FR",
            "country_name": "France",
            "admin1": "Ile-de-France",
            "lat": 48.9245,
            "lng": 2.3601,
        }
        ladder = {
            "medium": (
                "This major sports venue is located in the northern suburbs of "
                "the French capital, just beyond its ring road."
            ),
            "medium_map_anchor": "Paris",
            "easy": "Look in Saint-Denis, just north of Paris, near the A1 motorway.",
        }
        paris = {
            "lat": "48.8566",
            "lon": "2.3522",
            "display_name": "Paris, Ile-de-France, France",
            "importance": 0.9,
            "address": {"city": "Paris", "country_code": "fr"},
        }
        saint_denis = {
            "lat": "48.9358",
            "lon": "2.3580",
            "display_name": "Saint-Denis, Ile-de-France, France",
            "importance": 0.6,
            "address": {"city": "Saint-Denis", "country_code": "fr"},
        }

        with patch.object(
            generate_ai_daily_map_round.daily_map_game,
            "fetch_forward_geocode",
            side_effect=[[paris], [saint_denis]],
        ):
            anchors = generate_ai_daily_map_round.build_verified_map_search_anchors(
                place,
                ladder,
                locality_name="Saint-Denis",
            )

        self.assertEqual(
            [
                (anchor["name"], anchor["min_hint_count"])
                for anchor in anchors
            ],
            [("Paris", 1), ("Saint-Denis", 2), ("Example Stadium", 2)],
        )
        self.assertEqual(anchors[0]["boundary_kind"], "guidance")
        self.assertEqual(anchors[0]["boundary_min_zoom"], 4)
        self.assertTrue(
            generate_ai_daily_map_round.map_boundary_contains_point(
                anchors[0]["boundary"],
                lat=place["lat"],
                lng=place["lng"],
            )
        )

    def test_medium_map_anchor_cannot_replace_region_named_in_medium_clue(self) -> None:
        place = {
            "canonical_name": "Example Stadium",
            "acceptable_aliases": [],
            "country_code": "ES",
            "country_name": "Spain",
            "admin1": "Catalonia",
            "lat": 41.3809,
            "lng": 2.1228,
        }

        with self.assertRaisesRegex(
            ValueError,
            "medium map anchor must not replace the region explicitly named",
        ):
            generate_ai_daily_map_round.build_verified_map_search_anchors(
                place,
                {
                    "medium": "This historic club represents Catalonia, Spain.",
                    "medium_map_anchor": "Barcelona",
                    "easy": "Look west of Barcelona city centre.",
                },
                locality_name="Barcelona",
            )

    def test_map_boundary_must_contain_the_answer_point(self) -> None:
        paris_city_boundary = {
            "type": "Polygon",
            "coordinates": [
                [[2.20, 48.80], [2.45, 48.80], [2.45, 48.90], [2.20, 48.90], [2.20, 48.80]]
            ],
        }
        saint_denis_boundary = {
            "type": "Polygon",
            "coordinates": [
                [[2.33, 48.90], [2.40, 48.90], [2.40, 48.96], [2.33, 48.96], [2.33, 48.90]]
            ],
        }

        self.assertFalse(
            generate_ai_daily_map_round.map_boundary_contains_point(
                paris_city_boundary,
                lat=48.9245,
                lng=2.3601,
            )
        )
        self.assertTrue(
            generate_ai_daily_map_round.map_boundary_contains_point(
                saint_denis_boundary,
                lat=48.9245,
                lng=2.3601,
            )
        )

    def test_map_search_anchor_rejects_unmapped_clue_route(self) -> None:
        with self.assertRaisesRegex(ValueError, "No answer-safe locality or region"):
            generate_ai_daily_map_round.build_verified_map_search_anchors(
                {
                    "canonical_name": "Example Stadium",
                    "acceptable_aliases": [],
                    "country_code": "GB",
                    "country_name": "United Kingdom",
                    "admin1": "Greater Manchester",
                    "lat": 53.4631,
                    "lng": -2.2913,
                },
                {
                    "hard": "A memorable match happened on this pitch.",
                    "medium": "This ground is in northern England.",
                    "easy": "Search west of the city centre.",
                    "reveal": "This is Example Stadium.",
                },
                locality_name="Manchester",
            )

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
            [{"googleSearch": {}}],
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

    def test_event_place_verifier_requires_exact_venue_connection(self) -> None:
        provider = EventPlaceVerificationProvider()
        result = generate_ai_daily_map_round.verify_event_place_connection(
            provider,
            {
                "verified_hard_hook": (
                    "A named team won a tournament match on this pitch."
                )
            },
            {
                "enriched_hard_hook": (
                    "On this pitch, Team A defeated Team B 2-0 in the group stage."
                )
            },
            place={"canonical_name": "Example Stadium"},
        )

        self.assertTrue(result["passed"])
        self.assertEqual(provider.tools, [{"googleSearch": {}}])
        self.assertIn("exact stadium or venue", provider.prompt)

    def test_event_place_verifier_fails_when_event_was_at_another_venue(self) -> None:
        provider = EventPlaceVerificationProvider(passed=False)

        with patch.object(
            generate_ai_daily_map_round,
            "wikipedia_verification_evidence",
            return_value=[],
        ):
            with self.assertRaisesRegex(ValueError, "another stadium"):
                generate_ai_daily_map_round.verify_event_place_connection(
                    provider,
                    {"verified_hard_hook": "A match happened on this pitch."},
                    {"enriched_hard_hook": "Team A defeated Team B here."},
                    place={"canonical_name": "Wrong Stadium"},
                )

    def test_event_place_verifier_can_use_independent_wikipedia_evidence(self) -> None:
        provider = FallbackEventPlaceVerificationProvider()
        evidence = [
            {
                "title": "Example match",
                "url": "https://en.wikipedia.org/?curid=42",
                "extract": "Team A defeated Team B 2-0 at Example Stadium.",
            }
        ]

        with patch.object(
            generate_ai_daily_map_round,
            "wikipedia_verification_evidence",
            return_value=evidence,
        ):
            result = generate_ai_daily_map_round.verify_event_place_connection(
                provider,
                {"verified_hard_hook": "Team A defeated Team B here."},
                {"enriched_hard_hook": "Team A defeated Team B 2-0 here."},
                place={"canonical_name": "Example Stadium"},
            )

        self.assertTrue(result["passed"])
        self.assertEqual(result["evidence_source"], "wikipedia")
        self.assertIn("Judge only", provider.prompt)

    def test_event_place_verifier_rechecks_a_low_confidence_grounded_result(self) -> None:
        provider = EventPlaceVerificationProvider(passed=False)
        evidence = [
            {
                "title": "Example match",
                "url": "https://en.wikipedia.org/?curid=42",
                "extract": "Team A defeated Team B 2-0 at Example Stadium.",
            }
        ]

        def low_confidence_then_evidence(**kwargs):
            if kwargs.get("tools"):
                return {
                    "passed": False,
                    "confidence": 5,
                    "failure_reasons": ["The search result was inconclusive."],
                    "used_source_urls": ["https://example.com/search"],
                }
            return {
                "passed": True,
                "confidence": 96,
                "failure_reasons": [],
                "used_source_urls": ["https://en.wikipedia.org/?curid=42"],
            }

        provider.call_with_fallback = low_confidence_then_evidence
        with patch.object(
            generate_ai_daily_map_round,
            "wikipedia_verification_evidence",
            return_value=evidence,
        ):
            result = generate_ai_daily_map_round.verify_event_place_connection(
                provider,
                {"verified_hard_hook": "Team A defeated Team B here."},
                {"enriched_hard_hook": "Team A defeated Team B 2-0 here."},
                place={"canonical_name": "Example Stadium"},
            )

        self.assertTrue(result["passed"])
        self.assertEqual(result["evidence_source"], "wikipedia")

    def test_exact_target_page_support_accepts_a_directly_corroborated_hook(self) -> None:
        result = generate_ai_daily_map_round.exact_target_page_support(
            [
                {
                    "title": "Terracotta Army",
                    "url": "https://en.wikipedia.org/?curid=148653",
                    "extract": (
                        "The figures were buried with the emperor. Local farmers "
                        "discovered the figures while digging a well in 1974."
                    ),
                }
            ],
            {
                "verified_hard_hook": (
                    "Farmers discovered the buried figures while digging a well in 1974."
                )
            },
            place={"canonical_name": "Terracotta Army"},
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["coverage"], 1.0)

    def test_direct_support_accepts_an_event_page_that_names_the_target(self) -> None:
        result = generate_ai_daily_map_round.exact_target_page_support(
            [
                {
                    "title": "1987 Cricket World Cup",
                    "url": "https://en.wikipedia.org/?curid=184346",
                    "extract": (
                        "The 1987 Cricket World Cup was won for the first time by "
                        "Australia, who defeated England by seven runs in the final "
                        "at Eden Gardens stadium."
                    ),
                }
            ],
            {
                "verified_hard_hook": (
                    "Australia secured their first Cricket World Cup title in 1987 "
                    "by defeating England by seven runs in the final."
                )
            },
            place={"canonical_name": "Eden Gardens"},
        )

        self.assertIsNotNone(result)
        self.assertGreaterEqual(result["coverage"], 0.75)

    def test_direct_support_accepts_a_famous_final_with_synonymous_outcome(self) -> None:
        result = generate_ai_daily_map_round.exact_target_page_support(
            [
                {
                    "title": "1966 FIFA World Cup final",
                    "url": "https://en.wikipedia.org/?curid=34657",
                    "extract": (
                        "The 1966 FIFA World Cup final was played at Wembley "
                        "Stadium. England defeated West Germany 4-2 after extra "
                        "time to claim the Jules Rimet Trophy. It remains the "
                        "only time England won the World Cup."
                    ),
                }
            ],
            {
                "verified_hard_hook": (
                    "This stadium hosted the 1966 World Cup final where England "
                    "secured their only major international trophy."
                )
            },
            place={"canonical_name": "Wembley Stadium"},
        )

        self.assertIsNotNone(result)
        self.assertGreaterEqual(result["coverage"], 0.65)

    def test_exact_target_page_support_rejects_an_event_from_another_venue(self) -> None:
        result = generate_ai_daily_map_round.exact_target_page_support(
            [
                {
                    "title": "Old Trafford",
                    "url": "https://en.wikipedia.org/?curid=1234",
                    "extract": (
                        "This stadium hosted three group matches during the 1966 "
                        "World Cup."
                    ),
                }
            ],
            {
                "verified_hard_hook": (
                    "Brazil beat Bulgaria here in 1966 while Pele was injured by "
                    "a brutal tackle."
                )
            },
            place={"canonical_name": "Old Trafford"},
        )

        self.assertIsNone(result)

    def test_event_place_verifier_rejects_fallback_urls_outside_evidence(self) -> None:
        provider = FallbackEventPlaceVerificationProvider()

        def unsupported_source_response(**kwargs):
            if kwargs.get("tools"):
                raise RuntimeError("Grounded provider quota exhausted.")
            return {
                "passed": True,
                "confidence": 96,
                "failure_reasons": [],
                "used_source_urls": ["https://unsupported.example/source"],
            }

        provider.call_with_fallback = unsupported_source_response

        with patch.object(
            generate_ai_daily_map_round,
            "wikipedia_verification_evidence",
            return_value=[
                {
                    "title": "Evidence",
                    "url": "https://en.wikipedia.org/?curid=42",
                    "extract": "Evidence text.",
                }
            ],
        ):
            with self.assertRaisesRegex(ValueError, "outside the supplied evidence"):
                generate_ai_daily_map_round.verify_event_place_connection(
                    provider,
                    {"verified_hard_hook": "A match happened here."},
                    {"enriched_hard_hook": "A match happened here."},
                    place={"canonical_name": "Example Stadium"},
                )

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
