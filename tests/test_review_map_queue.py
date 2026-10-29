import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from deploy import backup_manager
from tools import automatic_map_pool, review_map_queue


class MapQueueReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.database = self.data / "fultons.db"
        self.backups = self.root / "backups"
        self.backups.mkdir()
        with closing(sqlite3.connect(self.database)) as conn:
            automatic_map_pool.initialize(conn)
            for candidate_id, state, name in (
                ("q940843", "ready", "Lotus Temple"),
                ("q1988240", "ready", "Cairo Citadel"),
                ("qused", "used", "Earlier place"),
            ):
                conn.execute(
                    "INSERT INTO automatic_map_entries "
                    "(id,state,candidate,result,verification,created_at,expires_at,origin) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (candidate_id, state, json.dumps({"canonical_name": name}), "{}",
                     json.dumps({"interesting_hook": True}), "2026-10-03", "2026-10-17", "discovery"),
                )
            conn.commit()

    def test_dry_run_requires_exact_ready_names_and_changes_nothing(self):
        targets = review_map_queue.parse_targets(["q940843=Lotus Temple"])
        result = review_map_queue.review(self.database, targets, reason="Hard hook is only a cement supply detail.")
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["entries"], [{"id": "q940843", "name": "Lotus Temple"}])
        with closing(sqlite3.connect(self.database)) as conn:
            self.assertEqual(conn.execute("SELECT state FROM automatic_map_entries WHERE id='q940843'").fetchone()[0], "ready")
        with self.assertRaisesRegex(ValueError, "expected place name"):
            review_map_queue.review(self.database, {"q940843": "Different place"}, reason="The hook is too thin to publish.")
        with self.assertRaisesRegex(ValueError, "not an unpublished ready"):
            review_map_queue.review(self.database, {"qused": "Earlier place"}, reason="The hook is too thin to publish.")
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_apply_backs_up_and_retires_only_named_ready_entries(self):
        targets = review_map_queue.parse_targets([
            "q940843=Lotus Temple", "q1988240=Cairo Citadel",
        ])
        reason = "The hard clues rely on cement procurement and a siege that never happened."
        result = review_map_queue.review(
            self.database, targets, reason=reason, apply=True, backup_root=self.backups
        )
        self.assertEqual(result["status"], "applied")
        backup_manager.verify_backup(Path(result["backup"]))
        with closing(sqlite3.connect(self.database)) as conn:
            rows = conn.execute("SELECT id,state,verification FROM automatic_map_entries ORDER BY id").fetchall()
        by_id = {row[0]: row for row in rows}
        self.assertEqual(by_id["q940843"][1], "rejected")
        self.assertEqual(by_id["q1988240"][1], "rejected")
        self.assertEqual(by_id["qused"][1], "used")
        self.assertEqual(json.loads(by_id["q940843"][2])["operator_rejection"]["reason"], reason)
        self.assertEqual(json.loads(by_id["q940843"][2])["operator_rejection"]["scope"], "hook")

    def test_in_container_snapshot_preserves_pre_review_state(self):
        result = review_map_queue.review(
            self.database, {"q940843": "Lotus Temple"},
            reason="The proposed hard hook is not interesting enough for the game.",
            apply=True, in_container_snapshot=True,
        )
        self.assertEqual(result["backup_kind"], "sqlite_safety_snapshot")
        snapshot = Path(result["backup"])
        self.assertEqual(snapshot.parent, self.data / "qa" / "map-review-backups")
        with closing(sqlite3.connect(snapshot)) as conn:
            self.assertEqual(conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute(
                "SELECT state FROM automatic_map_entries WHERE id='q940843'"
            ).fetchone()[0], "ready")
        with closing(sqlite3.connect(self.database)) as conn:
            self.assertEqual(conn.execute(
                "SELECT state FROM automatic_map_entries WHERE id='q940843'"
            ).fetchone()[0], "rejected")

    def test_place_scope_is_explicit(self):
        result = review_map_queue.review(
            self.database, {"q940843": "Lotus Temple"},
            reason="This place is not suitable for a light Map game.",
            scope="place", apply=True, backup_root=self.backups,
        )
        self.assertEqual(result["status"], "applied")
        with closing(sqlite3.connect(self.database)) as conn:
            verification = json.loads(conn.execute(
                "SELECT verification FROM automatic_map_entries WHERE id='q940843'"
            ).fetchone()[0])
        self.assertEqual(verification["operator_rejection"]["scope"], "place")

    def test_round_scope_records_a_reusable_clue_ladder_failure(self):
        reason = "The local anchor is inside the answer, making the route unplayable."
        review_map_queue.review(
            self.database, {"q940843": "Lotus Temple"}, reason=reason,
            scope="round", apply=True, backup_root=self.backups,
        )
        with closing(sqlite3.connect(self.database)) as conn:
            verification = json.loads(conn.execute(
                "SELECT verification FROM automatic_map_entries WHERE id='q940843'"
            ).fetchone()[0])
        self.assertEqual(verification["operator_rejection"]["scope"], "round")
        self.assertEqual(verification["round_rejection"], reason)
        self.assertTrue(verification["editorial_rejection"])

    def test_reclassify_round_requires_exact_prior_reason_and_preserves_timestamp(self):
        reason = "The local anchor is inside the answer, making the route unplayable."
        with closing(sqlite3.connect(self.database)) as conn:
            conn.execute("UPDATE automatic_map_entries SET state='rejected',verification=? WHERE id='q940843'",
                         (json.dumps({"operator_rejection": {"scope": "hook", "reason": reason,
                                                               "at": "2026-10-03T12:00:00+00:00"}}),))
            conn.commit()
        with self.assertRaisesRegex(ValueError, "exact expected reason"):
            review_map_queue.review(self.database, {"q940843": "Lotus Temple"},
                                    reason="A different historical reason is not allowed.",
                                    scope="round", reclassify_round=True)
        result = review_map_queue.review(
            self.database, {"q940843": "Lotus Temple"}, reason=reason,
            scope="round", reclassify_round=True, apply=True, backup_root=self.backups,
        )
        self.assertEqual(result["status"], "applied")
        with closing(sqlite3.connect(self.database)) as conn:
            verification = json.loads(conn.execute(
                "SELECT verification FROM automatic_map_entries WHERE id='q940843'"
            ).fetchone()[0])
        self.assertEqual(verification["operator_rejection"]["at"], "2026-10-03T12:00:00+00:00")
        self.assertEqual(verification["rejected_at"], "2026-10-03T12:00:00+00:00")
        self.assertEqual(verification["round_rejection"], reason)

    def test_apply_refuses_missing_backup_root_and_duplicate_targets(self):
        targets = review_map_queue.parse_targets(["q940843=Lotus Temple"])
        with self.assertRaisesRegex(ValueError, "backup root"):
            review_map_queue.review(self.database, targets, reason="The place hook is not compelling.", apply=True)
        with self.assertRaisesRegex(ValueError, "only once"):
            review_map_queue.parse_targets(["q940843=Lotus Temple", "q940843=Lotus Temple"])
        with self.assertRaisesRegex(ValueError, "exactly one"):
            review_map_queue.review(
                self.database, targets, reason="The place hook is not compelling.",
                apply=True, backup_root=self.backups, in_container_snapshot=True,
            )

    def test_apply_rejects_stale_batch_without_changing_other_entry(self):
        targets = review_map_queue.parse_targets([
            "q940843=Lotus Temple", "qused=Earlier place",
        ])
        with self.assertRaisesRegex(ValueError, "not an unpublished ready"):
            review_map_queue.review(
                self.database, targets,
                reason="The hard clue does not have a compelling hook.",
                apply=True, backup_root=self.backups,
            )
        with closing(sqlite3.connect(self.database)) as conn:
            state = conn.execute(
                "SELECT state FROM automatic_map_entries WHERE id='q940843'"
            ).fetchone()[0]
        self.assertEqual(state, "ready")
        self.assertEqual(list(self.backups.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
