from __future__ import annotations
import json
import sqlite3
import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch

import daily_map_game


class DailyMapGameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL
            )
            """
        )
        self.conn.execute("INSERT INTO users (id, username) VALUES (1, 'tester')")
        daily_map_game.initialize_database(self.conn)
        self.addCleanup(self.conn.close)

    def first_level(self, puzzle_date: str = "2026-07-13") -> sqlite3.Row:
        level = self.conn.execute(
            """
            SELECT
                daily_map_levels.id,
                daily_map_levels.level_slug,
                map_place_pool.canonical_name,
                map_place_pool.lat,
                map_place_pool.lng
            FROM daily_map_levels
            INNER JOIN daily_map_puzzles
                ON daily_map_puzzles.id = daily_map_levels.puzzle_id
            INNER JOIN map_place_pool
                ON map_place_pool.id = daily_map_levels.place_id
            WHERE daily_map_puzzles.puzzle_date = ?
            ORDER BY daily_map_levels.id
            LIMIT 1
            """,
            (puzzle_date,),
        ).fetchone()
        self.assertIsNotNone(level)
        return level

    def publish_named_level(
        self,
        name: str,
        *,
        puzzle_date: str = "2026-07-13",
    ) -> sqlite3.Row:
        puzzle = daily_map_game.get_or_create_puzzle(self.conn, puzzle_date)
        place = self.conn.execute(
            "SELECT * FROM map_place_pool WHERE canonical_name = ?",
            (name,),
        ).fetchone()
        self.assertIsNotNone(place)
        now = daily_map_game.utc_now()
        config = daily_map_game.SCORE_CONFIG[place["difficulty"]]
        self.conn.execute(
            """
            INSERT OR REPLACE INTO daily_map_levels (
                puzzle_id, level_slug, place_id, max_points, lambda_km, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                puzzle["id"],
                place["difficulty"],
                place["id"],
                config["max_points"],
                config["lambda_km"],
                now,
            ),
        )
        daily_map_game.set_puzzle_status(self.conn, puzzle_date, "published")
        return self.first_level(puzzle_date)

    def make_london_quality_ready(self, *, current_profile: bool = False) -> int:
        facts = [
            "Guy Fawkes was arrested beneath Parliament in 1605 while guarding gunpowder intended to kill King James I.",
            "This English capital is home to the monarchy and the world's oldest underground railway.",
            "Westminster lies beside the Thames around Parliament and its famous clock tower.",
        ]
        self.conn.execute(
            """
            UPDATE map_place_pool
            SET review_status = 'approved',
                validation_grade = 10,
                verified_facts_json = ?,
                nearby_context = ?,
                clue_text = ?,
                medium_clue_text = ?,
                easy_clue_text = ?,
                reveal_text = ?,
                clue_profile_hash = ?
            WHERE canonical_name = 'London'
            """,
            (
                json.dumps(facts),
                "Westminster, River Thames, central London",
                "Guy Fawkes was arrested beneath Parliament here in 1605 while guarding gunpowder intended to kill King James I.",
                "This English capital is home to the monarchy and the world's oldest underground railway.",
                "Look within Westminster, beside the Thames, around Parliament and its famous clock tower.",
                "London is the English capital linked by the Gunpowder Plot, the Underground, and Westminster.",
                daily_map_game.map_learning_profile_hash() if current_profile else "",
            ),
        )
        return int(
            self.conn.execute(
                "SELECT id FROM map_place_pool WHERE canonical_name = 'London'"
            ).fetchone()["id"]
        )

    def insert_excluded_thebes_place(self) -> sqlite3.Row:
        now = daily_map_game.utc_now()
        self.conn.execute(
            """
            INSERT OR REPLACE INTO map_place_pool (
                slug,
                canonical_name,
                country_code,
                country_name,
                admin1,
                place_type,
                difficulty,
                lat,
                lng,
                clue_text,
                medium_clue_text,
                easy_clue_text,
                reveal_text,
                acceptable_aliases,
                review_status,
                scoring_radius_m,
                active,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "medium-ancient-thebes-with-its-necropolis",
                "Ancient Thebes with its Necropolis",
                "EG",
                "Egypt",
                "Luxor Governorate",
                "archaeological_site",
                "medium",
                25.73333,
                32.6,
                "Temples, palaces and immense necropolises extend across both sides of the Nile.",
                "Look in Egypt for the capital of the Middle and New Kingdoms, sacred to the god Amun.",
                "Find the monumental landscape containing Karnak and Luxor temples together with the Valleys of the Kings and Queens.",
                "This was Ancient Thebes with its Necropolis, a UNESCO-listed archaeological site in Egypt.",
                "Thebes antique et sa necropole",
                "approved",
                10_000,
                1,
                now,
            ),
        )
        row = self.conn.execute(
            """
            SELECT *
            FROM map_place_pool
            WHERE canonical_name = 'Ancient Thebes with its Necropolis'
            """
        ).fetchone()
        self.assertIsNotNone(row)
        return row

    def test_generation_publishes_one_level_with_clue_ladder(self) -> None:
        self.conn.execute("UPDATE map_place_pool SET active = 0")
        london_id = self.make_london_quality_ready()
        self.conn.execute("UPDATE map_place_pool SET active = 1 WHERE id = ?", (london_id,))
        with patch.object(daily_map_game, "initialize_database", return_value=None):
            status = daily_map_game.generate_daily_map_game(
                self.conn,
                puzzle_date="2026-07-13",
                log=lambda _: None,
            )
        payload = daily_map_game.daily_bundle_payload(
            self.conn,
            puzzle_date="2026-07-13",
            user_id=1,
        )

        self.assertEqual(status["status"], "published")
        self.assertEqual(status["acceptedLevels"], 1)
        self.assertEqual(payload["maxScore"], 10)
        self.assertEqual(payload["completedLevels"], 0)
        self.assertEqual(len(payload["levels"]), 1)
        self.assertEqual(
            [clue["id"] for clue in payload["levels"][0]["clues"]],
            ["hard", "medium", "easy", "name"],
        )
        self.assertEqual(
            [clue["maxPoints"] for clue in payload["levels"][0]["clues"]],
            [10, 7, 5, 2],
        )
        self.assertTrue(all("result" not in level for level in payload["levels"]))

    def test_generation_can_publish_a_specific_quality_place_for_qa(self) -> None:
        with patch.object(
            daily_map_game,
            "map_learning_profile_hash",
            return_value="test-profile",
        ):
            london_id = self.make_london_quality_ready(current_profile=True)
            with patch.object(daily_map_game, "initialize_database", return_value=None):
                status = daily_map_game.generate_daily_map_game(
                    self.conn,
                    puzzle_date="2026-07-13",
                    preferred_place_id=london_id,
                )

        self.assertEqual(status["status"], "published")
        self.assertEqual(self.first_level()["canonical_name"], "London")

    def test_qa_generation_rejects_legacy_place_not_reviewed_under_current_profile(self) -> None:
        with patch.object(
            daily_map_game,
            "map_learning_profile_hash",
            return_value="test-profile",
        ):
            london_id = self.make_london_quality_ready(current_profile=False)
            with patch.object(daily_map_game, "initialize_database", return_value=None):
                status = daily_map_game.generate_daily_map_game(
                    self.conn,
                    puzzle_date="2026-07-13",
                    preferred_place_id=london_id,
                )

        self.assertEqual(status["status"], "failed")
        self.assertIn("unavailable", status["failureReason"])

    def test_reviewed_clue_ladder_overrides_derived_medium_and_easy_clues(self) -> None:
        level = self.publish_named_level("Cape Town")
        place_id = self.conn.execute(
            "SELECT place_id FROM daily_map_levels WHERE id = ?",
            (level["id"],),
        ).fetchone()["place_id"]
        self.conn.execute(
            """
            UPDATE map_place_pool
            SET verified_facts_json = ?,
                nearby_context = ?
            WHERE id = ?
            """,
            (
                json.dumps(
                    [
                        "Nelson Mandela made his first public speech after 27 years of imprisonment from City Hall.",
                        "This South African legislative capital sits beneath Table Mountain.",
                        "The City Bowl lies between Table Mountain and the Atlantic waterfront.",
                    ]
                ),
                "City Bowl, Table Mountain, Atlantic waterfront",
                place_id,
            ),
        )
        daily_map_game.save_reviewed_clue_ladder(
            self.conn,
            place_id=place_id,
            clue_ladder={
                "hard": "Nelson Mandela made his first public speech after 27 years of imprisonment from City Hall here.",
                "medium": "This South African legislative capital sits beneath Table Mountain.",
                "easy": "Work within the City Bowl between Table Mountain and the Atlantic waterfront.",
                "reveal": "Cape Town links Mandela's City Hall speech with Table Mountain and the City Bowl.",
            },
        )

        payload = daily_map_game.daily_bundle_payload(
            self.conn,
            puzzle_date="2026-07-13",
            user_id=1,
        )
        clues = payload["levels"][0]["clues"]

        self.assertIn("South African", clues[1]["text"])
        self.assertIn("City Bowl", clues[2]["text"])
        self.assertNotIn("Cape Town", clues[0]["text"])
        self.assertNotIn("Cape Town", clues[1]["text"])
        self.assertNotIn("Cape Town", clues[2]["text"])

    def test_daily_bundle_exposes_valid_map_search_anchors(self) -> None:
        level = self.publish_named_level("London")
        place_id = self.conn.execute(
            "SELECT place_id FROM daily_map_levels WHERE id = ?",
            (level["id"],),
        ).fetchone()["place_id"]
        self.conn.execute(
            "UPDATE map_place_pool SET map_search_anchors_json = ? WHERE id = ?",
            (
                json.dumps(
                    [
                        {
                            "name": "Westminster",
                            "lat": 51.4995,
                            "lng": -0.1248,
                            "min_hint_count": 2,
                        },
                        {"name": "Broken", "lat": "north", "lng": 0},
                    ]
                ),
                place_id,
            ),
        )

        payload = daily_map_game.daily_bundle_payload(
            self.conn,
            puzzle_date="2026-07-13",
            user_id=1,
        )

        self.assertEqual(
            payload["levels"][0]["mapAnchors"],
            [
                {
                    "name": "Westminster",
                    "point": {"lat": 51.4995, "lng": -0.1248},
                    "minHintCount": 2,
                    "minZoom": 4,
                    "maxZoom": 4,
                }
            ],
        )

    def test_local_map_clue_critic_rejects_repetition_and_answer_leak(self) -> None:
        place = {
            "canonical_name": "Cape Town",
            "acceptable_aliases": [],
        }
        critic = daily_map_game.local_map_clue_critique(
            place,
            {
                "hard": "Cape Town is near Table Mountain.",
                "medium": "This city is near Table Mountain.",
                "easy": "The city below Table Mountain is the answer.",
                "reveal": "Cape Town sits below Table Mountain.",
            },
        )

        self.assertFalse(critic["passed"])
        self.assertTrue(any("reveals" in reason for reason in critic["failure_reasons"]))

    def test_local_map_clue_critic_rejects_template_metadata_and_long_text(self) -> None:
        place = {
            "canonical_name": "Abidjan",
            "acceptable_aliases": [],
        }
        critic = daily_map_game.local_map_clue_critique(
            place,
            {
                "hard": "In Gulf of Guinea, its wider national-map setting is north of another mapped urban centre.",
                "medium": "Look within the wider national-map setting for one of the country's mapped urban centres.",
                "easy": "Find the city at 5.354, -4.002 using its time zone metadata.",
                "reveal": "Abidjan is located at 5.354, -4.002 in the Africa/Abidjan time zone.",
            },
        )

        self.assertFalse(critic["passed"])
        self.assertTrue(any("formulaic" in reason for reason in critic["failure_reasons"]))
        self.assertTrue(any("coordinates" in reason for reason in critic["failure_reasons"]))
        self.assertTrue(any("natural explanation" in item for item in critic["feedback_to_generator"]))

    def test_local_map_clue_critic_rejects_mobile_unfriendly_clues(self) -> None:
        place = {
            "canonical_name": "Caserta",
            "acceptable_aliases": [],
        }
        critic = daily_map_game.local_map_clue_critique(
            place,
            {
                "hard": (
                    "A Bourbon royal site joins palace, park, planned industry, woodland, hunting lodges, "
                    "a long aqueduct, formal gardens, ceremonial apartments, workshops, fountains, avenues, "
                    "and an Enlightenment landscape composition into one vast complex whose many separate "
                    "elements cannot be understood comfortably in a single mobile clue."
                ),
                "medium": "Look in southern Italy for a palace and park built for a Bourbon king as a monumental rival to other European royal seats.",
                "easy": "Find the vast royal palace complex north of Naples with a long formal park and Vanvitelli's aqueduct.",
                "reveal": "Caserta is the royal palace and park complex north of Naples.",
            },
        )

        self.assertFalse(critic["passed"])
        self.assertTrue(any("too long" in reason for reason in critic["failure_reasons"]))

    def test_local_map_clue_critic_does_not_impose_word_counts(self) -> None:
        place = {
            "canonical_name": "Alexandria",
            "acceptable_aliases": [],
            "nearby_context": "Eastern Harbour, Qaitbay Citadel, Mediterranean coast, Egypt",
        }
        critic = daily_map_game.local_map_clue_critique(
            place,
            {
                "hard": "An ancient lighthouse here guided Mediterranean sailors and became one of the Seven Wonders before earthquakes finally destroyed it.",
                "medium": "This Egyptian Mediterranean port became a centre of learning, translation, mapmaking, medicine, astronomy, and ancient scholarship.",
                "easy": "Search the waterfront district around Qaitbay Citadel at the city's Eastern Harbour.",
                "reveal": "Alexandria is known for its ancient library, lighthouse, and Mediterranean history.",
            },
        )

        self.assertTrue(critic["passed"], critic["failure_reasons"])
        self.assertFalse(any("too many words" in reason for reason in critic["failure_reasons"]))

    def test_local_map_clue_critic_rejects_location_only_ladders(self) -> None:
        place = {
            "canonical_name": "Test City",
            "acceptable_aliases": [],
        }
        critic = daily_map_game.local_map_clue_critique(
            place,
            {
                "hard": "A large settlement near a broad river and low hills.",
                "medium": "Look in the southern part of its country beside a bay.",
                "easy": "Find the coastal city between two larger urban areas.",
                "reveal": "Test City is the answer.",
            },
        )

        self.assertFalse(critic["passed"])
        self.assertTrue(any("recognition hook" in reason for reason in critic["failure_reasons"]))
        self.assertTrue(any("broad geography" in reason for reason in critic["failure_reasons"]))

    def test_local_map_clue_critic_rejects_single_weak_location_clue(self) -> None:
        place = {
            "canonical_name": "London",
            "acceptable_aliases": [],
        }
        critic = daily_map_game.local_map_clue_critique(
            place,
            {
                "hard": "This historic settlement grew around a river that flows into the North Sea.",
                "medium": "Visitors often ride a giant observation wheel to see the skyline from above.",
                "easy": "Red double-decker buses pass a famous clock tower known as Big Ben.",
                "reveal": "London is known for royal landmarks, Westminster, and the Underground.",
            },
        )

        self.assertFalse(critic["passed"])
        self.assertTrue(any("weak fields: hard" in reason for reason in critic["failure_reasons"]))
        self.assertTrue(any("broad geography" in reason for reason in critic["failure_reasons"]))

    def test_local_map_clue_critic_rejects_generic_capital_easy_clue(self) -> None:
        place = {
            "canonical_name": "Paris",
            "acceptable_aliases": [],
        }
        critic = daily_map_game.local_map_clue_critique(
            place,
            {
                "hard": "This historic fashion capital is home to the world's most visited art museum.",
                "medium": "A famous iron lattice tower stands tall above the banks of the Seine river.",
                "easy": "This major European destination is the iconic capital city of France.",
                "reveal": "Paris is known for the Louvre, Eiffel Tower, and cafe culture.",
            },
        )

        self.assertFalse(critic["passed"])
        self.assertTrue(
            any("weak fields:" in reason and "easy" in reason for reason in critic["failure_reasons"])
        )
        self.assertTrue(any("medium geographic narrowing" in reason for reason in critic["failure_reasons"]))

    def test_local_map_clue_critic_rejects_awkward_placeholders(self) -> None:
        place = {
            "canonical_name": "London",
            "acceptable_aliases": [],
        }
        critic = daily_map_game.local_map_clue_critique(
            place,
            {
                "hard": "This historic capital is home to the oldest underground railway network.",
                "medium": "Famous for red double-decker buses and black taxicabs.",
                "easy": "Find the fortress known as the Tower of the place.",
                "reveal": "London is known for Westminster, the Underground, and royal landmarks.",
            },
        )

        self.assertFalse(critic["passed"])
        self.assertTrue(any("placeholder" in reason for reason in critic["failure_reasons"]))

    def test_local_map_clue_critic_accepts_distinct_known_for_hooks(self) -> None:
        place = {
            "canonical_name": "Rio de Janeiro",
            "acceptable_aliases": [],
            "nearby_context": "Maracana district, central Rio waterfront, Brazil",
            "verified_facts": [
                "Germany defeated Argentina 1-0 here in the 2014 World Cup final after extra time.",
                "This Brazilian former capital hosted South America's first Olympic Games.",
                "The Maracana district lies north of the central waterfront.",
            ],
        }
        critic = daily_map_game.local_map_clue_critique(
            place,
            {
                "hard": "Germany defeated Argentina 1-0 here in the 2014 World Cup final after extra time.",
                "medium": "This Brazilian former capital hosted South America's first Olympic Games.",
                "easy": "Search around the Maracana district north of the central waterfront.",
                "reveal": "Rio de Janeiro links the 2014 final, Brazilian Olympic history, and the Maracana district.",
            },
        )

        self.assertTrue(critic["passed"], critic["failure_reasons"])

    def test_local_map_clue_critic_accepts_cultural_and_architectural_hooks(self) -> None:
        place = {
            "canonical_name": "Alhambra",
            "acceptable_aliases": [],
            "verified_facts": [
                "UNESCO describes the complex as the only preserved palatine city of the Islamic period.",
                "The palaces are a major surviving expression of Nasrid art and architecture.",
                "A long walled palace-fortress occupies a wooded ridge above a compact historic city.",
            ],
            "nearby_context": "Sabika hill, Granada, Albaicin district, southern Spain",
        }
        critic = daily_map_game.local_map_clue_critique(
            place,
            {
                "hard": "The only preserved palatine city from the Islamic period survives here with its Nasrid courts.",
                "medium": "Its Nasrid rulers made this a final Muslim stronghold in southern Spain.",
                "easy": "Find the walled complex on Sabika hill above Granada's Albaicin district.",
                "reveal": "The Alhambra is Granada's Nasrid palace-fortress.",
            },
        )

        self.assertTrue(critic["passed"], critic["failure_reasons"])

    def test_local_map_clue_critic_rejects_non_progressive_landmark_fact_lists(self) -> None:
        cases = [
            (
                {
                    "canonical_name": "Anfield",
                    "acceptable_aliases": [],
                    "verified_facts": [
                        "A famous boot room helped produce several generations of successful managers.",
                        "Supporters sing You'll Never Walk Alone before the biggest matches.",
                        "The Kop creates a towering wall of red behind one goal.",
                    ],
                },
                {
                    "hard": "A famous boot room helped produce several generations of successful managers.",
                    "medium": "Supporters sing You'll Never Walk Alone before the biggest matches.",
                    "easy": "The Kop creates a towering wall of red behind one goal.",
                    "reveal": "Anfield is the match, combining its boot-room history, famous anthem, and the Kop.",
                },
            ),
            (
                {
                    "canonical_name": "Atomium",
                    "acceptable_aliases": [],
                    "verified_facts": [
                        "The structure was built as a centrepiece for the 1958 world exposition.",
                        "Its design enlarges the unit cell of an iron crystal billions of times.",
                        "Nine giant steel spheres connect through broad silver tubes.",
                    ],
                },
                {
                    "hard": "The structure was built as a centrepiece for the 1958 world exposition.",
                    "medium": "Its design enlarges the unit cell of an iron crystal billions of times.",
                    "easy": "Nine giant steel spheres connect through broad silver tubes.",
                    "reveal": "Atomium fits because of Expo 58, an enlarged iron crystal, and nine connected spheres.",
                },
            ),
            (
                {
                    "canonical_name": "Auschwitz II-Birkenau Gate",
                    "acceptable_aliases": ["Birkenau Gate"],
                    "verified_facts": [
                        "Nazi Germany murdered more than a million people across the surrounding camp complex.",
                        "Surviving barracks and personal belongings document industrialised persecution and killing.",
                        "Railway tracks pass beneath a brick gate toward rows of wooden barracks.",
                    ],
                },
                {
                    "hard": "Nazi Germany murdered more than a million people across the surrounding camp complex.",
                    "medium": "Surviving barracks and personal belongings document industrialised persecution and killing.",
                    "easy": "Railway tracks pass beneath a brick gate toward rows of wooden barracks.",
                    "reveal": "Auschwitz II-Birkenau Gate ties together Holocaust history, preserved evidence, and the rail entrance.",
                },
            ),
        ]

        for place, ladder in cases:
            with self.subTest(place=place["canonical_name"]):
                critic = daily_map_game.local_map_clue_critique(place, ladder)
                self.assertFalse(critic["passed"])
                self.assertTrue(
                    any("medium geographic narrowing" in reason for reason in critic["failure_reasons"])
                )

    def test_local_map_clue_critic_allows_answer_phrase_in_reveal(self) -> None:
        place = {
            "canonical_name": "London",
            "acceptable_aliases": [],
            "verified_facts": [
                "Guy Fawkes was arrested beneath Parliament in 1605 while guarding gunpowder.",
                "This English capital is home to the world's oldest underground railway.",
                "Westminster lies beside the Thames around Parliament and Big Ben.",
            ],
            "nearby_context": "Westminster, River Thames, central London",
        }
        critic = daily_map_game.local_map_clue_critique(
            place,
            {
                "hard": "Guy Fawkes was arrested beneath Parliament here in 1605 while guarding gunpowder.",
                "medium": "This English capital is home to the world's oldest underground railway.",
                "easy": "Look within Westminster, beside the Thames river, around Parliament and its clock tower.",
                "reveal": "The answer is London: the Gunpowder Plot, the Underground, and Westminster.",
            },
        )

        self.assertTrue(critic["passed"], critic["failure_reasons"])

    def test_local_map_clue_critic_rejects_validation_style_reveal(self) -> None:
        place = {
            "canonical_name": "London",
            "acceptable_aliases": [],
            "verified_facts": [
                "Guy Fawkes was arrested beneath Parliament in 1605 while guarding gunpowder.",
                "This English capital is home to the world's oldest underground railway.",
                "Westminster lies beside the Thames around Parliament and Big Ben.",
            ],
            "nearby_context": "Westminster, River Thames, central London",
        }
        critic = daily_map_game.local_map_clue_critique(
            place,
            {
                "hard": "Guy Fawkes was arrested beneath Parliament here in 1605 while guarding gunpowder.",
                "medium": "This English capital is home to the world's oldest underground railway.",
                "easy": "Look within Westminster, beside the Thames river, around Parliament and its clock tower.",
                "reveal": "London fits because of the Gunpowder Plot, the Underground, and Westminster.",
            },
        )

        self.assertFalse(critic["passed"])
        self.assertTrue(any("placeholder" in reason for reason in critic["failure_reasons"]))

    def test_local_map_clue_critic_rejects_unsupported_known_for_claims(self) -> None:
        place = {
            "canonical_name": "Abidjan",
            "acceptable_aliases": [],
            "verified_facts": [
                "Abidjan is recorded by GeoNames as a populated place in Ivory Coast.",
                "The GeoNames record lists a population and the time zone Africa/Abidjan.",
                "A mapped urban settlement; inspect the road pattern and surrounding terrain at city scale.",
            ],
            "nearby_context": "Use the GeoNames populated-place point as the target centre.",
        }
        critic = daily_map_game.local_map_clue_critique(
            place,
            {
                "hard": "This hub is home to the largest Roman Catholic church on the African continent.",
                "medium": "The local economy thrives on the export of cocoa beans and other tropical crops.",
                "easy": "It is the economic powerhouse of a West African nation famous for its coffee.",
                "reveal": "Abidjan is a major economic center of Ivory Coast.",
            },
        )

        self.assertFalse(critic["passed"])
        self.assertTrue(any("verified facts/context" in reason for reason in critic["failure_reasons"]))

    def test_explicitly_excluded_place_fails_quality_gate(self) -> None:
        row = self.insert_excluded_thebes_place()

        self.assertFalse(daily_map_game.row_passes_map_clue_quality(row))

    def test_broad_multi_site_targets_are_explicitly_excluded(self) -> None:
        names = [
            "Aflaj Irrigation Systems of Oman",
            "Ancient Thebes with its Necropolis",
            "Ancient Villages of Northern Syria",
            "Baekje Historic Areas",
            "Bagrati Cathedral and Gelati Monastery",
        ]

        for name in names:
            with self.subTest(name=name):
                self.assertTrue(daily_map_game.place_is_explicitly_excluded({"canonical_name": name}))

    def test_daily_selector_skips_quality_failed_active_rows(self) -> None:
        self.conn.execute("UPDATE map_place_pool SET active = 0")
        self.conn.execute(
            """
            UPDATE map_place_pool
            SET active = 1,
                review_status = 'approved',
                clue_text = 'In Gulf of Guinea, its wider national-map setting is north of another mapped urban centre.',
                medium_clue_text = 'Look within the wider national-map setting for one of the country''s mapped urban centres.',
                easy_clue_text = 'Find the city at 5.354, -4.002 using its time zone metadata.',
                reveal_text = 'Abidjan is located at 5.354, -4.002 in the Africa/Abidjan time zone.'
            WHERE canonical_name = 'Cape Town'
            """
        )
        london_id = self.make_london_quality_ready()
        self.conn.execute("UPDATE map_place_pool SET active = 1 WHERE id = ?", (london_id,))

        place = daily_map_game.select_daily_place(self.conn, "2026-07-13")

        self.assertIsNotNone(place)
        self.assertEqual(place["canonical_name"], "London")

    def test_place_interest_profile_rewards_three_distinct_persuading_facts(self) -> None:
        strong = daily_map_game.map_place_interest_profile(
            {
                "canonical_name": "London",
                "place_type": "city",
                "country_code": "GB",
                "difficulty": "easy",
                "lat": 51.5,
                "lng": -0.1,
                "validation_grade": 10,
                "verified_facts_json": json.dumps(
                    [
                        "Roman walls and royal ceremonies reveal layers of a long history.",
                        "West End theatre and major museums anchor its cultural life.",
                        "Big Ben stands beside Parliament in a world-famous view.",
                    ]
                ),
            }
        )
        weak = daily_map_game.map_place_interest_profile(
            {
                "canonical_name": "Test Castle",
                "place_type": "castle",
                "country_code": "GB",
                "difficulty": "medium",
                "lat": 50.0,
                "lng": -1.0,
                "validation_grade": 10,
                "verified_facts_json": json.dumps(
                    [
                        "GeoNames records this as a populated place.",
                        "The record includes a latitude and longitude.",
                        "It is in an administrative region.",
                    ]
                ),
            }
        )

        self.assertEqual(strong["persuadingFactCount"], 3)
        self.assertEqual(weak["persuadingFactCount"], 0)
        self.assertGreater(strong["score"], weak["score"])

    def test_place_interest_profile_accepts_public_attraction_and_skyscraper_hooks(self) -> None:
        cases = [
            (
                "The High Line",
                [
                    "This public park is built on a historic elevated freight rail line.",
                    "A community campaign turned a derelict structure into a green corridor.",
                    "Native plants and art installations change along the route through the seasons.",
                ],
                {"visual_landmark", "engineering_industry", "culture_event", "natural_setting"},
            ),
            (
                "Willis Tower",
                [
                    "It was the tallest building in the world for 25 years after completion.",
                    "The structure is made of nine bundled tubes for wind resistance.",
                    "Visitors can step onto a glass-bottomed balcony from the 103rd floor.",
                ],
                {"visual_landmark", "engineering_industry"},
            ),
            (
                "Palm Jumeirah",
                [
                    "This artificial archipelago was created using land reclamation and is shaped like a date palm tree.",
                    "It is visible from space and required millions of cubic meters of sand and rock to construct.",
                    "The project added miles of beachfront to the city's coastline.",
                ],
                {"visual_landmark", "engineering_industry", "natural_setting"},
            ),
            (
                "Burj Al Arab",
                [
                    "The sail-shaped building sits on its own man-made island just offshore.",
                    "A private bridge connects the offshore island back to the mainland.",
                    "The interior is decorated with large areas of gold leaf.",
                ],
                {"visual_landmark", "engineering_industry", "natural_setting"},
            ),
        ]

        for name, facts, expected_categories in cases:
            with self.subTest(name=name):
                profile = daily_map_game.map_place_interest_profile(
                    {
                        "canonical_name": name,
                        "place_type": "landmark",
                        "country_code": "US",
                        "difficulty": "medium",
                        "lat": 40.0,
                        "lng": -73.0,
                        "validation_grade": 10,
                        "verified_facts_json": json.dumps(facts),
                    }
                )

                self.assertEqual(profile["persuadingFactCount"], 3)
                self.assertTrue(expected_categories & set(profile["categories"]))

    def test_map_workoutability_score_requires_actual_map_route(self) -> None:
        self.assertEqual(
            daily_map_game.map_workoutability_score(
                {
                    "canonical_name": "Willis Tower",
                    "nearby_context": "high",
                    "verified_facts_json": "[]",
                    "lat": 0,
                    "lng": 0,
                }
            ),
            0,
        )
        self.assertGreaterEqual(
            daily_map_game.map_workoutability_score(
                {
                    "canonical_name": "The High Line",
                    "nearby_context": (
                        "A player can work from Manhattan, then look for the long elevated park "
                        "running through Chelsea on the west side."
                    ),
                    "verified_facts_json": "[]",
                    "lat": 0,
                    "lng": 0,
                }
            ),
            daily_map_game.MAP_PLACE_REQUIRED_WORKOUTABILITY_SCORE,
        )

    def test_daily_selector_prefers_more_interesting_place_data(self) -> None:
        self.conn.execute("UPDATE map_place_pool SET active = 0")
        london_id = self.make_london_quality_ready()
        self.conn.execute("UPDATE map_place_pool SET active = 1 WHERE id = ?", (london_id,))
        self.conn.execute(
            """
            UPDATE map_place_pool
            SET active = 1,
                review_status = 'approved',
                validation_grade = 1,
                verified_facts_json = ?,
                nearby_context = 'City Bowl, Table Mountain, Atlantic waterfront',
                clue_text = 'Nelson Mandela made his first public speech after 27 years of imprisonment from City Hall here.',
                medium_clue_text = 'This South African legislative capital sits beneath Table Mountain.',
                easy_clue_text = 'Work within the City Bowl between Table Mountain and the Atlantic waterfront.',
                reveal_text = 'Cape Town links Mandela''s City Hall speech with Table Mountain and the City Bowl.'
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

        place = daily_map_game.select_daily_place(self.conn, "2026-07-13")

        self.assertIsNotNone(place)
        self.assertEqual(place["canonical_name"], "London")

    def test_map_clue_learning_profile_feedback_uses_slot_specific_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "map_profile.json"
            profile_path.write_text(
                """
                {
                  "feedback_by_slot": {
                    "global": ["Use map-visible hooks."],
                    "city/*": ["Avoid generic city clues."],
                    "*/easy": ["Easy should help without naming."],
                    "city/easy": ["City easy clues need a distinct landmark."]
                  }
                }
                """,
                encoding="utf-8",
            )

            feedback = daily_map_game.map_clue_learning_profile_feedback(
                str(profile_path),
                place_type="city",
                difficulty="easy",
            )

        self.assertEqual(
            feedback,
            [
                "Use map-visible hooks.",
                "Avoid generic city clues.",
                "Easy should help without naming.",
                "City easy clues need a distinct landmark.",
            ],
        )

    def test_map_clue_learning_profile_feedback_labels_each_clue_level(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "map_profile.json"
            profile_path.write_text(
                """
                {
                  "feedback_by_slot": {
                    "global": ["Write for an adult player.", "Make the ladder solvable."],
                    "*/hard": ["Use a hard fallback hook."],
                    "*/medium": ["Use a medium fallback narrowing fact."],
                    "*/easy": ["Use an easy fallback map anchor."],
                    "city/hard": ["Use a memorable incident or record."],
                    "city/medium": ["Narrow the likely setting with a different fact."],
                    "city/easy": ["Give a practical map-visible anchor."]
                  },
                  "approved_examples_by_level": {
                    "hard": [
                      {
                        "example_id": "h1",
                        "place_type": "city",
                        "clue": "A hard city example.",
                        "why_it_passed": "It uses a memorable incident.",
                        "training_weight": 2
                      }
                    ],
                    "medium": [
                      {
                        "example_id": "m1",
                        "place_type": "bridge",
                        "clue": "A medium bridge example.",
                        "why_it_passed": "It narrows the region.",
                        "training_weight": 2
                      }
                    ],
                    "easy": [
                      {
                        "example_id": "e1",
                        "place_type": "landmark",
                        "clue": "An easy landmark example.",
                        "why_it_passed": "It gives a map anchor.",
                        "training_weight": 2
                      }
                    ]
                  }
                }
                """,
                encoding="utf-8",
            )

            feedback = daily_map_game.map_clue_learning_profile_ladder_feedback(
                str(profile_path),
                place_type="city",
            )
            fallback = daily_map_game.map_clue_learning_profile_ladder_feedback(
                str(profile_path),
                place_type="national_park",
            )

        self.assertEqual(
            feedback,
            [
                "Write for an adult player.",
                "Make the ladder solvable.",
                "HARD: Use a memorable incident or record.",
                "HARD: Use a hard fallback hook.",
                "HARD APPROVED EXAMPLE (city): A hard city example. Review: It uses a memorable incident.",
                "MEDIUM: Narrow the likely setting with a different fact.",
                "MEDIUM: Use a medium fallback narrowing fact.",
                "MEDIUM APPROVED EXAMPLE (bridge): A medium bridge example. Review: It narrows the region.",
                "EASY: Give a practical map-visible anchor.",
                "EASY: Use an easy fallback map anchor.",
                "EASY APPROVED EXAMPLE (landmark): An easy landmark example. Review: It gives a map anchor.",
            ],
        )

        self.assertEqual(
            fallback,
            [
                "Write for an adult player.",
                "Make the ladder solvable.",
                "HARD: Use a hard fallback hook.",
                "HARD APPROVED EXAMPLE (city): A hard city example. Review: It uses a memorable incident.",
                "MEDIUM: Use a medium fallback narrowing fact.",
                "MEDIUM APPROVED EXAMPLE (bridge): A medium bridge example. Review: It narrows the region.",
                "EASY: Use an easy fallback map anchor.",
                "EASY APPROVED EXAMPLE (landmark): An easy landmark example. Review: It gives a map anchor.",
            ],
        )

    def test_map_clue_prompt_targets_adult_and_distinct_clue_roles(self) -> None:
        prompt = daily_map_game.map_clue_generator_prompt(
            {
                "canonical_name": "Budapest",
                "acceptable_aliases": [],
                "verified_facts": ["The Danube separates Buda and Pest."],
            },
            [],
            [],
        )

        self.assertIn("adult player", prompt)
        self.assertIn("Hard is a recognition hook", prompt)
        self.assertIn("answer-safe functional identity", prompt)
        self.assertIn("Do not manufacture a hook", prompt)
        self.assertIn("commissioner, ruler, architect", prompt)
        self.assertIn("Medium must materially reduce the geographic search area", prompt)
        self.assertIn("Generic narrowing", prompt)
        self.assertIn("geographic progress is mandatory", prompt)
        self.assertIn("Do not force every medium clue into the same template", prompt)
        self.assertIn("Easy must narrow to a local area", prompt)
        self.assertIn("must explicitly name that locality", prompt)
        self.assertIn('Never introduce an unnamed place with "the city"', prompt)
        self.assertIn("zoom 11 or earlier", prompt)
        self.assertIn("popular association", prompt)
        self.assertNotIn("Write for a child", prompt)

    def test_map_clue_critic_rejects_deep_zoom_or_incorrect_local_anchors(self) -> None:
        prompt = daily_map_game.map_clue_critic_prompt(
            {
                "canonical_name": "Example Stadium",
                "acceptable_aliases": [],
                "verified_facts": ["The stadium is in the city's northern area."],
            },
            {
                "hard": "A memorable event happened on this pitch.",
                "medium": "Its resident club represents this capital city.",
                "easy": "Search a nearby district.",
                "reveal": "This is Example Stadium.",
            },
            [],
        )

        self.assertIn("after zoom 11", prompt)
        self.assertIn("supported answer-safe target identity", prompt)
        self.assertIn("neither medium nor easy explicitly names it", prompt)
        self.assertIn("popular association", prompt)
        self.assertIn("verified technical location", prompt)

    def test_local_critic_rejects_an_unresolved_city_reference(self) -> None:
        place = {
            "canonical_name": "Camp Nou",
            "acceptable_aliases": ["Nou Camp"],
            "country_name": "Spain",
            "admin1": "Catalonia",
            "locality_name": "Barcelona",
            "verified_facts": [
                "Manchester United beat Bayern Munich 2-1 here in the 1999 Champions League final.",
                "The venue is home to a Catalan football club.",
                "The stadium lies north of Avinguda Diagonal in Les Corts.",
            ],
            "nearby_context": "A large oval in the western urban area north of Avinguda Diagonal.",
            "required_hard_hook": (
                "Manchester United beat Bayern Munich 2-1 on this pitch in the "
                "1999 Champions League final with two stoppage-time goals."
            ),
        }
        critic = daily_map_game.local_map_clue_critique(
            place,
            {
                "hard": place["required_hard_hook"],
                "medium": "Its resident football club represents Catalonia.",
                "easy": (
                    "Look for a large oval in the western urban area of the city, "
                    "north of Avinguda Diagonal in Les Corts."
                ),
                "reveal": "Camp Nou is Barcelona's famous football stadium.",
            },
        )

        self.assertFalse(critic["passed"])
        self.assertTrue(
            any(
                "required low-zoom locality Barcelona" in reason
                for reason in critic["failure_reasons"]
            )
        )

    def test_locality_progression_accepts_the_city_named_by_medium_or_easy(self) -> None:
        place = {
            "canonical_name": "Camp Nou",
            "acceptable_aliases": ["Nou Camp"],
            "locality_name": "Barcelona",
        }

        self.assertTrue(
            daily_map_game.clue_ladder_reaches_required_locality(
                {
                    "medium": "This is the home of a football club from Barcelona.",
                    "easy": "Search west of the city centre.",
                },
                place,
            )
        )
        self.assertTrue(
            daily_map_game.clue_ladder_reaches_required_locality(
                {
                    "medium": "Its resident football club represents Catalonia.",
                    "easy": "In Barcelona, search west of the city centre.",
                },
                place,
            )
        )

    def test_generation_avoid_list_keeps_geography_available(self) -> None:
        place = {
            "canonical_name": "Camp Nou",
            "acceptable_aliases": ["Nou Camp"],
            "country_name": "Spain",
            "admin1": "Catalonia",
            "continent": "Europe",
            "locality_name": "Barcelona",
            "avoid_in_clues": "Camp Nou; Nou Camp; Barcelona; Spain; Catalonia; Europe",
        }

        self.assertEqual(
            daily_map_game.generation_avoid_in_clues(place),
            "Camp Nou; Nou Camp",
        )

    def test_local_critic_rejects_a_city_name_followed_only_by_deep_map_details(self) -> None:
        place = {
            "canonical_name": "Camp Nou",
            "acceptable_aliases": ["Nou Camp"],
            "country_name": "Spain",
            "admin1": "Catalonia",
            "locality_name": "Barcelona",
            "verified_facts": [
                "Manchester United beat Bayern Munich 2-1 here in the 1999 Champions League final.",
                "The venue is home to FC Barcelona.",
                "The stadium is in Les Corts near Avinguda Diagonal and Palau Reial station.",
            ],
            "nearby_context": "Les Corts, Barcelona, near Avinguda Diagonal.",
            "required_hard_hook": (
                "Manchester United beat Bayern Munich 2-1 on this pitch in the "
                "1999 Champions League final with two stoppage-time goals."
            ),
        }
        critic = daily_map_game.local_map_clue_critique(
            place,
            {
                "hard": place["required_hard_hook"],
                "medium": "This is the permanent home ground for FC Barcelona in Spain.",
                "easy": (
                    "Locate this venue in the Les Corts district of Barcelona, "
                    "near Avinguda Diagonal and Palau Reial metro station."
                ),
                "reveal": "Camp Nou is FC Barcelona's home stadium.",
            },
        )

        self.assertFalse(critic["passed"])
        self.assertTrue(
            any(
                "broad city-sector route within Barcelona" in reason
                for reason in critic["failure_reasons"]
            )
        )

    def test_locality_route_accepts_a_broad_city_sector_before_smaller_details(self) -> None:
        place = {
            "canonical_name": "Camp Nou",
            "acceptable_aliases": ["Nou Camp"],
            "locality_name": "Barcelona",
        }
        ladder = {
            "medium": "This is the home of a football club from Catalonia.",
            "easy": (
                "In western Barcelona, search north of Avinguda Diagonal; "
                "Les Corts provides a closer guide."
            ),
        }

        self.assertTrue(daily_map_game.easy_has_broad_locality_route(ladder, place))

    def test_low_confidence_learned_failure_is_advisory_not_a_veto(self) -> None:
        place = {"place_type": "island"}
        ladder = {
            "hard": "A specific escape happened at this site.",
            "medium": "This prison operated in the United States.",
            "easy": "Look on an island inside a major bay.",
            "reveal": "This is Example Island.",
        }
        critic = {
            "passed": True,
            "scores": {field: 10 for field in daily_map_game.MAP_CLUE_CRITIC_THRESHOLDS},
            "failure_reasons": [],
            "feedback_to_generator": [],
        }

        def prediction(_model, level, _clue, **_kwargs):
            probability = 0.40 if level == "hard" else 0.90
            return {
                "pass_probability": probability,
                "confidence": abs(probability - 0.5) * 2,
                "negative_signals": ["this site"] if level == "hard" else [],
            }

        with (
            patch("tools.map_clue_quality_model.load_model", return_value={"version": 1}),
            patch("tools.map_clue_quality_model.predict_level", side_effect=prediction),
        ):
            result = daily_map_game.apply_learned_map_clue_quality_gate(
                place,
                ladder,
                critic,
                model_path="model.json",
            )

        self.assertTrue(result["passed"])
        self.assertEqual(result["learned_advisories"][0]["level"], "hard")
        self.assertEqual(result["failure_reasons"], [])

    def test_high_confidence_learned_failure_is_also_advisory(self) -> None:
        place = {"place_type": "island"}
        ladder = {
            "hard": "A generic thing happened at this site.",
            "medium": "This is in a country.",
            "easy": "Look nearby.",
            "reveal": "This is Example Island.",
        }
        critic = {
            "passed": True,
            "scores": {field: 10 for field in daily_map_game.MAP_CLUE_CRITIC_THRESHOLDS},
            "failure_reasons": [],
            "feedback_to_generator": [],
        }

        def prediction(_model, level, _clue, **_kwargs):
            probability = 0.10 if level == "hard" else 0.90
            return {
                "pass_probability": probability,
                "confidence": abs(probability - 0.5) * 2,
                "negative_signals": ["generic"] if level == "hard" else [],
            }

        with (
            patch("tools.map_clue_quality_model.load_model", return_value={"version": 1}),
            patch("tools.map_clue_quality_model.predict_level", side_effect=prediction),
        ):
            result = daily_map_game.apply_learned_map_clue_quality_gate(
                place,
                ladder,
                critic,
                model_path="model.json",
            )

        self.assertTrue(result["passed"])
        self.assertEqual(result["learned_advisories"][0]["level"], "hard")
        self.assertEqual(result["failure_reasons"], [])

    def test_hard_hook_gate_requires_a_recognition_hook_not_architecture(self) -> None:
        qualifying = (
            "Uruguay beat host nation Brazil 2-1 in the decisive 1950 World Cup "
            "match here, an upset known as the Maracanazo."
        )
        architect_fact = (
            "Architect Bernardo Morando designed this location to embody Italian "
            "theories of the ideal city."
        )
        generic_conflict = (
            "Designed by architect Sinan, this structure was destroyed during "
            "the 1990s conflict."
        )
        competition_opening = "The venue first opened for the 2002 Commonwealth Games."
        broad_wartime_claim = (
            "Defensive walls helped the settlement resist attacks during the "
            "Hundred Years' War."
        )
        dated_destruction = (
            "The coastal town flourished as a pearling centre before it was "
            "destroyed in 1811."
        )
        current_record = (
            "This cave holds the current world record for the largest mapped chamber "
            "by surface area."
        )
        former_record = (
            "This bridge had the world's longest spans when it opened in 1890."
        )
        weak_superlative = (
            "This stand is one of English football's largest end terraces."
        )
        weak_dedication = (
            "This memorial honours the first president of the United States."
        )

        self.assertTrue(daily_map_game.hard_hook_is_qualifying_event(qualifying))
        self.assertFalse(daily_map_game.hard_hook_is_qualifying_event(architect_fact))
        self.assertFalse(daily_map_game.hard_hook_is_qualifying_event(generic_conflict))
        self.assertFalse(daily_map_game.hard_hook_is_qualifying_event(competition_opening))
        self.assertFalse(daily_map_game.hard_hook_is_qualifying_event(broad_wartime_claim))
        self.assertFalse(daily_map_game.hard_hook_is_qualifying_event(dated_destruction))
        self.assertTrue(
            daily_map_game.hard_hook_is_qualifying_recognition_hook(current_record)
        )
        self.assertFalse(
            daily_map_game.hard_hook_is_qualifying_recognition_hook(former_record)
        )
        self.assertFalse(
            daily_map_game.hard_hook_is_qualifying_recognition_hook(weak_superlative)
        )
        self.assertFalse(
            daily_map_game.hard_hook_is_qualifying_recognition_hook(weak_dedication)
        )

    def test_generator_prompt_locks_selected_event_hook(self) -> None:
        hook = (
            "Uruguay beat host nation Brazil 2-1 in the decisive 1950 World Cup "
            "match here, an upset known as the Maracanazo."
        )
        prompt = daily_map_game.map_clue_generator_prompt(
            {
                "canonical_name": "Maracana Stadium",
                "acceptable_aliases": [],
                "verified_facts": [hook],
                "required_hard_hook": hook,
            },
            [],
            [],
        )

        self.assertIn("Locked verified recognition hook:", prompt)
        self.assertIn(hook, prompt)
        self.assertIn("Do not replace it with another fact", prompt)

    def test_locked_event_hook_cannot_be_replaced_by_an_architect_fact(self) -> None:
        hook = (
            "Uruguay beat host nation Brazil 2-1 in the decisive 1950 World Cup "
            "match here, an upset known as the Maracanazo."
        )

        self.assertTrue(
            daily_map_game.clue_preserves_required_hard_hook(
                "Uruguay stunned Brazil 2-1 in the 1950 World Cup match called the Maracanazo.",
                hook,
            )
        )
        self.assertFalse(
            daily_map_game.clue_preserves_required_hard_hook(
                "Two architects designed this enormous circular stadium.",
                hook,
            )
        )

    def test_hard_event_capsule_requires_more_than_a_headline(self) -> None:
        headline = "Archbishop Thomas Becket was murdered inside the church in 1170."
        event_capsule = (
            "After a bitter dispute with Henry II, four knights murdered "
            "Archbishop Thomas Becket inside this church in 1170."
        )

        self.assertFalse(daily_map_game.hard_event_has_enough_information(headline))
        self.assertTrue(daily_map_game.hard_event_has_enough_information(event_capsule))

    def test_copyedit_removes_only_approved_padding_to_meet_word_limit(self) -> None:
        medium = (
            "Medieval pilgrims travelled to this grand site, inspiring Geoffrey "
            "Chaucer to frame travellers as storytellers in literature."
        )
        easy = (
            "A tall central Gothic tower rises above stone cloisters and precincts "
            "in the historic heart of Canterbury, England."
        )

        edited_medium = daily_map_game.compress_clue_text_to_word_limit(medium, 16)
        edited_easy = daily_map_game.compress_clue_text_to_word_limit(easy, 16)

        self.assertNotIn("grand", edited_medium.casefold())
        self.assertIn("Geoffrey Chaucer", edited_medium)
        self.assertNotIn("historic", edited_easy.casefold())
        self.assertIn("Canterbury, England", edited_easy)
        self.assertLessEqual(daily_map_game.clue_word_count(edited_medium), 16)
        self.assertLessEqual(daily_map_game.clue_word_count(edited_easy), 16)

    def test_copyedit_leaves_clue_within_limit_unchanged(self) -> None:
        clue = "Geoffrey Chaucer linked medieval pilgrims with this English church."

        self.assertEqual(
            daily_map_game.compress_clue_text_to_word_limit(clue, 16),
            clue,
        )

    def test_copyedit_removes_redundant_fictional_when_fiction_is_explicit(self) -> None:
        clue = (
            "In Geoffrey Chaucer's fiction, fictional pilgrims tell stories while "
            "journeying to Thomas Becket's shrine at this church."
        )

        edited = daily_map_game.compress_clue_text_to_word_limit(clue, 16)

        self.assertIn("Chaucer's fiction", edited)
        self.assertNotIn("fictional pilgrims", edited)
        self.assertLessEqual(daily_map_game.clue_word_count(edited), 16)

    def test_copyedit_removes_meticulously_when_it_is_the_only_excess_word(self) -> None:
        clue = (
            "Citizens carefully and meticulously restored this European district's "
            "churches, palaces, market place after years of wartime destruction."
        )

        edited = daily_map_game.compress_clue_text_to_word_limit(clue, 16)

        self.assertNotIn("meticulously", edited)
        self.assertIn("churches, palaces, market place", edited)
        self.assertLessEqual(daily_map_game.clue_word_count(edited), 16)

    def test_word_count_treats_hyphenated_compounds_as_single_words(self) -> None:
        self.assertEqual(
            daily_map_game.clue_word_count("A five-year campaign rebuilt the market-place."),
            6,
        )

    def test_locked_event_accepts_a_semantically_preserved_sports_result(self) -> None:
        self.assertTrue(
            daily_map_game.clue_preserves_required_hard_hook(
                (
                    "Argentina beat the Netherlands 3-1 after extra time, "
                    "winning their first World Cup title in 1978."
                ),
                "The host nation won the 1978 World Cup final on this pitch.",
            )
        )

    def test_team_final_requires_both_sides_not_only_a_scorer(self) -> None:
        scorer_only = (
            "During the 1978 World Cup final, Mario Kempes scored twice "
            "to secure a 3-1 victory after extra time."
        )
        complete_event = (
            "Argentina beat the Netherlands 3-1 after extra time here in the "
            "1978 World Cup final, securing their first title."
        )

        self.assertFalse(
            daily_map_game.hard_event_has_enough_information(scorer_only)
        )
        self.assertTrue(
            daily_map_game.hard_event_has_enough_information(complete_event)
        )

    def test_hard_event_capsule_rejects_a_bare_outcome_statistic(self) -> None:
        clue = "During a 1944 uprising, Nazi troops destroyed over 85% of this district."

        self.assertFalse(daily_map_game.hard_event_has_enough_information(clue))
        self.assertIn(
            "a trigger, consequence, result, record, defining method, or reason the event mattered",
            daily_map_game.hard_event_missing_requirements(clue),
        )

    def test_hard_event_accepts_destruction_motive_with_synonymous_verbs(self) -> None:
        clue = (
            "During the August 1944 rebellion, Nazi forces systematically flattened "
            "over eighty-five percent of this district to suppress local resistance."
        )
        source = (
            "During the Warsaw Uprising in August 1944, more than 85% of Warsaw's "
            "historic centre was destroyed by Nazi troops."
        )

        self.assertTrue(daily_map_game.hard_event_has_enough_information(clue))
        self.assertTrue(daily_map_game.clue_preserves_required_hard_hook(clue, source))

    def test_hard_event_capsule_requires_an_answer_safe_place_link(self) -> None:
        self.assertFalse(
            daily_map_game.hard_event_has_enough_information(
                "Argentina beat the Netherlands 3-1 after extra time in the "
                "1978 World Cup final, securing their first title."
            )
        )
        self.assertTrue(
            daily_map_game.hard_event_has_enough_information(
                "Argentina beat the Netherlands 3-1 after extra time here in "
                "the 1978 World Cup final, securing their first title."
            )
        )
        self.assertTrue(
            daily_map_game.hard_event_has_enough_information(
                "After a 1944 uprising, Nazi troops deliberately destroyed over "
                "85% of this district, triggering a meticulous postwar reconstruction."
            )
        )

    def test_team_event_accepts_indirect_wording_that_still_names_both_sides(self) -> None:
        clue = (
            "On this pitch, the national team of England secured their only major "
            "international trophy by defeating West Germany 4-2 after extra time "
            "in the 1966 World Cup final."
        )

        self.assertNotIn(
            "both competing sides",
            daily_map_game.hard_hook_missing_requirements(clue),
        )

    def test_team_event_accepts_title_wording_with_both_countries(self) -> None:
        clue = (
            "On this pitch, Australia secured their first Cricket World Cup title "
            "in 1987 by defeating England by seven runs in the final."
        )

        self.assertNotIn(
            "both competing sides",
            daily_map_game.hard_hook_missing_requirements(clue),
        )

    def test_team_event_accepts_unicode_team_names(self) -> None:
        clue = (
            "On this pitch, Real Madrid defeated Atlético Madrid 5-3 on penalties "
            "after a 1-1 draw in the 2016 Champions League final."
        )

        self.assertNotIn(
            "both competing sides",
            daily_map_game.hard_hook_missing_requirements(clue),
        )

    def test_hard_target_identity_rejects_generic_site_for_an_island_prison(self) -> None:
        place = {
            "canonical_name": "Alcatraz Island",
            "place_type": "island",
            "verified_facts": [
                "In 1962, three inmates escaped using a makeshift raft."
            ],
            "validation_reasoning": (
                "The history of the prison and the escape make this compelling."
            ),
        }

        self.assertEqual(
            daily_map_game.hard_missing_target_identities(
                (
                    "In 1962, Frank Morris and the Anglin brothers escaped from "
                    "this site using a makeshift raft."
                ),
                place,
            ),
            ["island", "prison"],
        )
        self.assertEqual(
            daily_map_game.hard_missing_target_identities(
                (
                    "In 1962, Frank Morris and the Anglin brothers escaped from "
                    "the federal prison on this island using a makeshift raft."
                ),
                place,
            ),
            [],
        )

    def test_hard_geography_gate_rejects_a_named_point(self) -> None:
        clue = (
            "During construction of this performing arts venue on Bennelong Point, "
            "a worker became a local legend after falling into the foundation."
        )

        self.assertIsNotNone(
            daily_map_game.MAP_HARD_NAMED_GEOGRAPHIC_FEATURE_RE.search(clue)
        )

    def test_hard_geography_gate_rejects_country_scope_but_allows_a_team(self) -> None:
        place = {
            "country_name": "England",
            "admin1": "Kent",
            "locality_name": "Canterbury",
            "continent": "Europe",
        }

        self.assertEqual(
            daily_map_game.hard_nonparticipant_geographic_names(
                (
                    "Inside this cathedral, Thomas Becket was murdered by four "
                    "knights, transforming religious devotion in England."
                ),
                place,
            ),
            ["England"],
        )
        self.assertEqual(
            daily_map_game.hard_nonparticipant_geographic_names(
                (
                    "On this pitch, England defeated West Germany 4-2 after "
                    "extra time in the 1966 World Cup final."
                ),
                place,
            ),
            [],
        )

    def test_team_hook_accepts_country_name_before_national_football_team(self) -> None:
        missing = daily_map_game.hard_hook_missing_requirements(
            (
                "On this pitch, the England national football team won the 1966 "
                "World Cup final, defeating West Germany 4-2 after extra time."
            )
        )

        self.assertNotIn("both named sides or participants", missing)

    def test_local_critic_rejects_geographic_scope_in_locked_hard_clue(self) -> None:
        place = {
            "canonical_name": "Example Old Town",
            "acceptable_aliases": [],
            "required_hard_hook": (
                "During a 1944 uprising, Nazi troops destroyed over 85% of this district."
            ),
            "verified_facts": [
                "During a 1944 uprising, Nazi troops destroyed over 85% of this district.",
                "Residents rebuilt its churches and palaces from historic paintings.",
                "The district stands beside a major river.",
            ],
        }
        result = daily_map_game.local_map_clue_critique(
            place,
            {
                "hard": (
                    "After a 1944 uprising, Nazi troops destroyed 85% of this "
                    "Polish capital's district, forcing a five-year reconstruction."
                ),
                "medium": "Residents rebuilt its churches and palaces from historic paintings.",
                "easy": "Look beside the Vistula River in the centre of Poland's capital.",
                "reveal": f"The answer is {place['canonical_name']}.",
            },
        )

        self.assertFalse(result["passed"])
        self.assertTrue(
            any("geographic scope" in reason for reason in result["failure_reasons"])
        )

    def test_escape_hook_accepts_unsolved_outcome_but_rejects_national_padding(self) -> None:
        answer_safe = (
            "In 1962, Frank Morris and the Anglin brothers escaped from this site "
            "using dummy heads and makeshift rafts, leaving a mystery that remains unsolved."
        )
        vanished = (
            "In 1962, Frank Morris and brothers John and Clarence Anglin vanished "
            "from this site on a raft made from raincoats, leaving an enduring "
            "mystery that remains one of the most famous unsolved prison breaks in history."
        )
        padded = (
            "In 1962, Frank Morris and the Anglin brothers escaped from this site "
            "using dummy heads and makeshift rafts, an event that remains one of the "
            "most famous unsolved disappearances in American penal history."
        )

        self.assertTrue(daily_map_game.hard_event_has_enough_information(answer_safe))
        self.assertTrue(daily_map_game.hard_event_has_enough_information(vanished))
        self.assertTrue(daily_map_game.MAP_HARD_GEO_SCOPE_RE.search(padded))

    def test_escape_hook_accepts_a_prison_link_and_defining_method(self) -> None:
        clue = (
            "In 1962, Frank Morris and brothers John and Clarence Anglin escaped "
            "from this federal penitentiary by using papier-mache dummy heads to "
            "deceive guards before leaving on a raft made from raincoats."
        )

        self.assertTrue(daily_map_game.MAP_HARD_PLACE_LINK_RE.search(clue))
        self.assertTrue(daily_map_game.hard_event_has_enough_information(clue))

    def test_named_national_teams_are_event_participants_not_directional_scope(self) -> None:
        clue = (
            "On this pitch, England defeated West Germany 4-2 in extra time "
            "to win the 1966 World Cup final."
        )

        self.assertTrue(daily_map_game.hard_event_has_enough_information(clue))
        self.assertFalse(daily_map_game.MAP_HARD_GEO_SCOPE_RE.search(clue))

    def test_hard_hook_gate_accepts_a_scored_stoppage_time_comeback(self) -> None:
        clue = (
            "On this pitch, Manchester United defeated Bayern Munich 2-1 in the "
            "Champions League final, scoring twice in stoppage time to complete "
            "a comeback that secured the continental treble."
        )

        self.assertTrue(daily_map_game.hard_event_has_enough_information(clue))

    def test_local_critic_rejects_vague_unnamed_cultural_reference_in_medium(self) -> None:
        place = {
            "canonical_name": "Example Cathedral",
            "acceptable_aliases": [],
            "verified_facts": [
                "Four knights murdered an archbishop inside this church in 1170.",
                "Medieval pilgrims inspired a famous collection of English tales.",
                "A Gothic tower rises above the city centre.",
            ],
        }
        result = daily_map_game.local_map_clue_critique(
            place,
            {
                "hard": (
                    "After a royal dispute, four knights murdered an archbishop "
                    "inside this church in 1170, triggering widespread pilgrimage."
                ),
                "medium": (
                    "Medieval travellers journeyed to this English church, "
                    "inspiring a famous collection of tales."
                ),
                "easy": "Find its Gothic tower in the centre of this English city.",
                "reveal": "This was Example Cathedral, the medieval pilgrimage destination.",
            },
        )

        self.assertFalse(result["passed"])
        self.assertTrue(
            any("cultural reference" in reason for reason in result["failure_reasons"])
        )
        self.assertTrue(
            daily_map_game.medium_uses_unnamed_cultural_reference(
                "Geoffrey Chaucer linked this English pilgrimage church to a famous collection of medieval tales."
            )
        )
        self.assertFalse(
            daily_map_game.medium_uses_unnamed_cultural_reference(
                "Geoffrey Chaucer framed pilgrims travelling here as storytellers in a foundational English work."
            )
        )

    def test_medium_clue_must_distinguish_fictional_characters_from_history(self) -> None:
        ambiguous = (
            "Geoffrey Chaucer's pilgrims tell stories while journeying "
            "to Thomas Becket's shrine at this church."
        )
        clear = (
            "In Geoffrey Chaucer's fiction, pilgrims tell stories while journeying "
            "to Thomas Becket's shrine at this church."
        )

        self.assertTrue(daily_map_game.medium_blurs_fiction_and_history(ambiguous))
        self.assertFalse(daily_map_game.medium_blurs_fiction_and_history(clear))

    def test_hard_clue_rejects_distinctive_target_name_component(self) -> None:
        place = {
            "canonical_name": "Historic Centre of Warsaw",
            "acceptable_aliases": [],
        }

        self.assertTrue(
            daily_map_game.hard_clue_reveals_target_token(
                "During the Warsaw Uprising, Nazi troops destroyed most of this district.",
                place,
            )
        )
        self.assertFalse(
            daily_map_game.hard_clue_reveals_target_token(
                "After the 1944 uprising, Nazi troops razed most of this district in retaliation.",
                place,
            )
        )

    def test_learning_profile_can_supply_a_complete_gold_ladder_without_making_it_a_template(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "map_profile.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "feedback_by_slot": {
                            "global": ["Write for an adult player."],
                        },
                        "approved_ladders": [
                            {
                                "example_id": "gold-1",
                                "place_type": "stadium",
                                "clue_ladder": {
                                    "hard": "A memorable hard hook.",
                                    "medium": "A place-specific clue that advances the solve.",
                                    "easy": "A practical map anchor.",
                                },
                                "why_the_ladder_passed": "Each clue has a different role.",
                                "generalisation_note": "This is one pattern, not a mandatory template.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            feedback = daily_map_game.map_clue_learning_profile_ladder_feedback(
                str(profile_path),
                place_type="stadium",
            )

        self.assertTrue(any("GOLD COMPLETE LADDER" in item for item in feedback))
        self.assertTrue(any("not a mandatory template" in item for item in feedback))

    def test_local_critic_rejects_generic_construction_date_and_ruler_as_hard_hook(self) -> None:
        place = {
            "canonical_name": "Example Crossing",
            "acceptable_aliases": [],
            "verified_facts": [
                "Construction of this stone bridge began in 1357 under Charles IV.",
                "Religious statues line its pedestrian crossing over a named river.",
                "The bridge links an old town with the castle side.",
            ],
        }
        ladder = {
            "hard": "Construction of this stone bridge began in 1357 under Charles IV.",
            "medium": "Religious statues line this pedestrian crossing over the Vltava River.",
            "easy": "This medieval stone bridge links Prague's old town with the castle side.",
            "reveal": "Example Crossing is the statue-lined stone bridge across the Vltava.",
        }

        critique = daily_map_game.local_map_clue_critique(place, ladder)

        self.assertFalse(critique["passed"])
        self.assertTrue(
            any("construction" in reason.casefold() for reason in critique["failure_reasons"])
        )

    def test_local_critic_allows_construction_fact_with_unusual_one_place_detail(self) -> None:
        place = {
            "canonical_name": "Example Arena",
            "acceptable_aliases": [],
            "verified_facts": [
                "After the empire, parts of this arena were reused as homes, workshops and a fortress.",
                "Gladiatorial contests drew enormous crowds.",
                "The ruined oval stands in central Rome.",
            ],
        }
        ladder = {
            "hard": "After the empire, parts of this arena were reused as homes, workshops and a fortress.",
            "medium": "Gladiatorial contests drew enormous crowds in the heart of the Roman world.",
            "easy": "Find the vast ruined oval beside the Roman Forum in central Rome.",
            "reveal": "Example Arena is Rome's vast ancient amphitheatre.",
        }

        self.assertFalse(daily_map_game.clue_is_generic_origin_fact(ladder["hard"]))

    def test_local_critic_rejects_unnamed_generic_person_as_medium_detail(self) -> None:
        place = {
            "canonical_name": "Example Stadium",
            "acceptable_aliases": [],
            "verified_facts": [
                "A famous final was played here.",
                "Its official name honours journalist Mario Example.",
                "The oval stadium stands beside metro and suburban rail stations.",
            ],
        }
        ladder = {
            "hard": "A famous final here ended with a major upset for the host nation.",
            "medium": "The official name of this oval venue honours a prominent national sports journalist.",
            "easy": "Find this stadium beside metro and suburban rail stations in the northern district.",
            "reveal": "Example Stadium is the city's major oval football venue.",
        }

        critique = daily_map_game.local_map_clue_critique(place, ladder)

        self.assertFalse(critique["passed"])
        self.assertTrue(
            any("unnamed generic role" in reason for reason in critique["failure_reasons"])
        )

    def test_local_critic_requires_exact_canonical_name_in_reveal(self) -> None:
        place = {
            "canonical_name": "Maracanã Stadium",
            "acceptable_aliases": ["Maracana Stadium"],
            "verified_facts": [
                "A major 1950 final was played here.",
                "Its official name honours Mario Filho.",
                "The stadium stands beside metro and suburban rail stations.",
            ],
        }
        ladder = {
            "hard": "A major 1950 final here ended with a famous upset for the hosts.",
            "medium": "Named for Mario Filho, this Brazilian venue stands in northern Rio.",
            "easy": "Find this stadium beside metro and suburban rail stations, north of Tijuca.",
            "reveal": "Maracană Stadium opened in 1950 and became a famous football venue.",
        }

        critique = daily_map_game.local_map_clue_critique(place, ladder)

        self.assertFalse(critique["passed"])
        self.assertTrue(
            any("canonical place name" in reason for reason in critique["failure_reasons"])
        )

    def test_submit_guess_scores_correct_place_by_clues_used_and_is_idempotent(self) -> None:
        level = self.publish_named_level("Cairo")

        first, first_status = daily_map_game.submit_guess(
            self.conn,
            user_id=1,
            level_id=level["id"],
            lat=level["lat"],
            lng=level["lng"],
            selected_name="Cairo",
            revealed_hint_count=0,
            today="2026-07-13",
        )
        second, second_status = daily_map_game.submit_guess(
            self.conn,
            user_id=1,
            level_id=level["id"],
            lat=0,
            lng=0,
            selected_name="Luxor",
            revealed_hint_count=3,
            today="2026-07-13",
        )

        self.assertEqual(first_status, HTTPStatus.CREATED)
        self.assertEqual(second_status, HTTPStatus.OK)
        self.assertEqual(first["result"]["score"], 10)
        self.assertEqual(first["result"]["maxPoints"], 10)
        self.assertEqual(first["result"]["band"], "Solved from hard clue")
        self.assertTrue(first["result"]["correct"])
        self.assertEqual(first["result"], second["result"])

    def test_correct_place_after_easy_clue_scores_five_points(self) -> None:
        level = self.publish_named_level("Cape Town")

        result, status = daily_map_game.submit_guess(
            self.conn,
            user_id=1,
            level_id=level["id"],
            lat=float(level["lat"]) + 0.05,
            lng=level["lng"],
            selected_name="Cape Town",
            revealed_hint_count=2,
            today="2026-07-13",
        )

        self.assertEqual(status, HTTPStatus.CREATED)
        self.assertEqual(result["result"]["score"], 5)
        self.assertEqual(result["result"]["maxPoints"], 5)
        self.assertEqual(result["result"]["band"], "Solved with easy clue")
        self.assertTrue(result["result"]["correct"])

    def test_wrong_place_scores_zero(self) -> None:
        level = self.publish_named_level("Cairo")

        result, status = daily_map_game.submit_guess(
            self.conn,
            user_id=1,
            level_id=level["id"],
            lat=25.6872,
            lng=32.6396,
            selected_name="Luxor",
            revealed_hint_count=1,
            today="2026-07-13",
        )

        self.assertEqual(status, HTTPStatus.CREATED)
        self.assertEqual(result["result"]["score"], 0)
        self.assertEqual(result["result"]["maxPoints"], 7)
        self.assertEqual(result["result"]["band"], "Wrong place")
        self.assertFalse(result["result"]["correct"])
        self.assertEqual(result["result"]["selectedPlace"]["name"], "Luxor")

    def test_snap_guess_returns_nearby_named_place(self) -> None:
        level = self.publish_named_level("Cairo")

        selection, status = daily_map_game.snap_guess(
            self.conn,
            level_id=level["id"],
            lat=float(level["lat"]) + 0.05,
            lng=level["lng"],
            today="2026-07-13",
        )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(selection["snapped"])
        self.assertEqual(selection["name"], "Cairo")
        self.assertEqual(selection["kind"], "place")

    def test_snap_guess_rejects_when_no_place_is_close(self) -> None:
        level = self.publish_named_level("Cairo")

        payload, status = daily_map_game.snap_guess(
            self.conn,
            level_id=level["id"],
            lat=0,
            lng=0,
            today="2026-07-13",
            allow_reverse_geocode=False,
        )

        self.assertEqual(status, HTTPStatus.UNPROCESSABLE_ENTITY)
        self.assertIn("No nearby place", payload["error"])

    def test_snap_guess_falls_back_to_reverse_geocoded_place(self) -> None:
        level = self.publish_named_level("Cairo")
        reverse_selection = daily_map_game.selection_payload(
            point_lat=25.6872,
            point_lng=32.6396,
            clicked_lat=25.6872,
            clicked_lng=32.6396,
            snapped=True,
            name="Luxor",
            kind="place",
            country_code="EG",
            admin1="Luxor Governorate",
            alternatives=[],
            selected_index=0,
        )

        with patch.object(
            daily_map_game,
            "reverse_geocode_candidate",
            return_value=reverse_selection,
        ) as reverse_geocode:
            selection, status = daily_map_game.snap_guess(
                self.conn,
                level_id=level["id"],
                lat=25.6872,
                lng=32.6396,
                today="2026-07-13",
                zoom=10,
            )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(selection["name"], "Luxor")
        reverse_geocode.assert_called_once()

    def test_snap_guess_uses_zoom_tolerance_for_touch_taps(self) -> None:
        level = self.publish_named_level("Cairo")

        selection, status = daily_map_game.snap_guess(
            self.conn,
            level_id=level["id"],
            lat=level["lat"],
            lng=float(level["lng"]) + 0.5,
            today="2026-07-13",
            zoom=1,
        )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(selection["snapped"])
        self.assertEqual(selection["name"], "Cairo")
        self.assertGreater(selection["snapRadiusMeters"], 90_000)
        self.assertGreater(selection["snapRadiusMeters"], selection["distanceMeters"])
        self.assertLessEqual(selection["snapRadiusMeters"], 200_000)

    def test_snap_guess_keeps_one_answer_option_within_tighter_low_zoom_radius(self) -> None:
        level = self.publish_named_level("Cairo")
        cairo = self.conn.execute(
            "SELECT * FROM map_place_pool WHERE canonical_name = 'Cairo'"
        ).fetchone()
        self.assertIsNotNone(cairo)
        self.conn.execute(
            """
            INSERT INTO map_place_pool (
                slug, canonical_name, country_code, admin1, difficulty,
                lat, lng, clue_text, reveal_text, scoring_radius_m,
                active, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "duplicate-cairo-for-snap-test",
                "Cairo",
                cairo["country_code"],
                cairo["admin1"],
                cairo["difficulty"],
                cairo["lat"],
                float(cairo["lng"]) + 0.001,
                cairo["clue_text"],
                cairo["reveal_text"],
                cairo["scoring_radius_m"],
                1,
                daily_map_game.utc_now(),
            ),
        )

        selection, status = daily_map_game.snap_guess(
            self.conn,
            level_id=level["id"],
            lat=float(level["lat"]),
            lng=float(level["lng"]) + 0.5,
            today="2026-07-13",
            zoom=1,
            allow_reverse_geocode=False,
        )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(selection["name"], "Cairo")
        self.assertEqual(selection["alternatives"][0]["name"], "Cairo")
        self.assertEqual(
            [alternative["name"] for alternative in selection["alternatives"]].count("Cairo"),
            1,
        )
        self.assertLessEqual(selection["snapRadiusMeters"], 200_000)

    def test_snap_guess_does_not_select_answer_from_across_a_country(self) -> None:
        level = self.publish_named_level("Cairo")
        self.conn.execute(
            "UPDATE map_place_pool SET active = 0 WHERE canonical_name <> 'Cairo'"
        )

        payload, status = daily_map_game.snap_guess(
            self.conn,
            level_id=level["id"],
            lat=float(level["lat"]),
            lng=float(level["lng"]) + 4.0,
            today="2026-07-13",
            zoom=1,
            allow_reverse_geocode=False,
        )

        self.assertEqual(status, HTTPStatus.UNPROCESSABLE_ENTITY)
        self.assertIn("No nearby place", payload["error"])

    def test_snap_guess_selects_the_nearest_place_instead_of_preferring_answer(self) -> None:
        level = self.publish_named_level("Cairo")
        cairo = self.conn.execute(
            "SELECT * FROM map_place_pool WHERE canonical_name = 'Cairo'"
        ).fetchone()
        clicked_lng = float(cairo["lng"]) + 0.5
        self.conn.execute(
            """
            INSERT INTO map_place_pool (
                slug, canonical_name, country_code, admin1, difficulty,
                lat, lng, clue_text, reveal_text, scoring_radius_m,
                active, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "closer-place-for-snap-test",
                "Closer Place",
                cairo["country_code"],
                cairo["admin1"],
                cairo["difficulty"],
                cairo["lat"],
                clicked_lng,
                "A closer test place.",
                "Closer Place.",
                cairo["scoring_radius_m"],
                1,
                daily_map_game.utc_now(),
            ),
        )

        selection, status = daily_map_game.snap_guess(
            self.conn,
            level_id=level["id"],
            lat=float(cairo["lat"]),
            lng=clicked_lng,
            today="2026-07-13",
            zoom=1,
            allow_reverse_geocode=False,
        )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(selection["name"], "Closer Place")
        self.assertIn(
            "Cairo",
            [alternative["name"] for alternative in selection["alternatives"]],
        )

    def test_snap_guess_supports_landmark_places(self) -> None:
        level = self.publish_named_level("Falkirk Wheel")

        selection, status = daily_map_game.snap_guess(
            self.conn,
            level_id=level["id"],
            lat=level["lat"],
            lng=level["lng"],
            today="2026-07-13",
        )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(selection["snapped"])
        self.assertEqual(selection["kind"], "landmark")

    def test_snap_guess_returns_nearby_alternatives(self) -> None:
        level = self.publish_named_level("Bath")

        selection, status = daily_map_game.snap_guess(
            self.conn,
            level_id=level["id"],
            lat=51.42,
            lng=-2.48,
            today="2026-07-13",
            zoom=8,
        )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("alternatives", selection)
        names = [alternative["name"] for alternative in selection["alternatives"]]
        self.assertGreaterEqual(len(names), 2)
        self.assertIn("Bath", names)
        self.assertIn("Clifton Suspension Bridge", names)
        self.assertEqual(selection["selectedIndex"], 0)

    def test_snap_guess_skips_explicitly_excluded_places(self) -> None:
        self.publish_named_level("Cairo")
        row = self.insert_excluded_thebes_place()

        payload, status = daily_map_game.snap_guess(
            self.conn,
            level_id=self.first_level()["id"],
            lat=row["lat"],
            lng=row["lng"],
            today="2026-07-13",
            zoom=12,
            allow_reverse_geocode=False,
        )

        self.assertEqual(status, HTTPStatus.UNPROCESSABLE_ENTITY)
        self.assertIn("No nearby place", payload["error"])

    def test_invalid_coordinates_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Latitude"):
            daily_map_game.valid_coordinate(91, 0)

        with self.assertRaisesRegex(ValueError, "Longitude"):
            daily_map_game.valid_coordinate(0, 181)


if __name__ == "__main__":
    unittest.main()
