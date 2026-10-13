import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from deploy import backup_manager
from tools import automatic_map_pool, controlled_map_round, correct_map_queue


class MapQueueCorrectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.database = self.data / "fultons.db"
        self.backups = self.root / "backups"
        self.backups.mkdir()
        self.place = next(p for p in controlled_map_round.load_catalog(controlled_map_round.DEFAULT_CATALOG)
                          if p["id"] == "atomium")
        payload = {"place_id": self.place["id"], "selection_reason": "A memorable scientific idea with sourced local map placement.",
                   "clues": {level: {"text": fact["text"], "fact_id": level}
                             for level, fact in self.place["facts"].items()}}
        result = controlled_map_round.validate_result(payload, [self.place])
        with closing(sqlite3.connect(self.database)) as conn:
            controlled_map_round.daily_map_game.initialize_database(conn)
            automatic_map_pool.initialize(conn)
            automatic_map_pool.add(conn, self.place, result,
                                   {key: True for key in automatic_map_pool.CHECKS}, origin="discovery")
            conn.commit()
        with closing(sqlite3.connect(self.database)) as conn:
            self.old_hash = json.loads(conn.execute("SELECT verification FROM automatic_map_entries").fetchone()[0])["payload_sha256"]
        self.new = "Built for Expo 58, this landmark enlarged the structure of an iron crystal 165 billion times into a building."
        self.change = {"id": "atomium", "name": "Atomium", "expected_payload_sha256": self.old_hash,
                       "reason": "Improve the hard clue's clarity without changing the sourced scientific hook.",
                       "edits": {"hard": {"old": self.place["facts"]["hard"]["text"], "new": self.new,
                                           "source_url": "https://example.org/source",
                                           "evidence_quote": "The structure is an iron crystal magnified 165 billion times for the 1958 exhibition."}}}

    def test_dry_run_validates_without_changing_queue_or_backing_up(self):
        result = correct_map_queue.correct(self.database, [self.change])
        self.assertEqual(result["status"], "dry_run")
        with closing(sqlite3.connect(self.database)) as conn:
            candidate, verification = conn.execute("SELECT candidate,verification FROM automatic_map_entries").fetchone()
        self.assertEqual(json.loads(candidate)["facts"]["hard"]["text"], self.change["edits"]["hard"]["old"])
        self.assertEqual(json.loads(verification)["payload_sha256"], self.old_hash)
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_apply_backs_up_updates_evidence_and_keeps_publication_integrity(self):
        result = correct_map_queue.correct(self.database, [self.change], apply=True, backup_root=self.backups)
        self.assertEqual(result["status"], "applied")
        backup_manager.verify_backup(Path(result["backup"]))
        with closing(sqlite3.connect(self.database)) as conn:
            candidate, checked, verification = (json.loads(value) for value in conn.execute(
                "SELECT candidate,result,verification FROM automatic_map_entries").fetchone())
        self.assertEqual(candidate["facts"]["hard"]["text"], self.new)
        self.assertEqual(checked["clue_ladder"]["hard"], self.new)
        self.assertEqual(candidate["facts"]["hard"]["source_ids"], ["editorial_hard"])
        self.assertEqual(candidate["sources"]["editorial_hard"], "https://example.org/source")
        self.assertEqual(verification["operator_correction"]["edits"]["hard"]["old"], self.change["edits"]["hard"]["old"])
        self.assertEqual(verification["payload_sha256"], automatic_map_pool.discovery.digest({
            "candidate": candidate, "result": checked}))
        with closing(sqlite3.connect(self.database)) as conn:
            feedback = automatic_map_pool.editorial_corrections(conn)
        self.assertEqual(feedback, [{
            "place": "Atomium",
            "rejected_hook": self.change["edits"]["hard"]["old"],
            "replacement_hook": self.new,
            "reason": self.change["reason"],
        }])
        with self.assertRaisesRegex(ValueError, "reviewed payload hash"):
            correct_map_queue.correct(self.database, [self.change])

    def test_invalid_or_stale_correction_never_changes_entry(self):
        invalid = json.loads(json.dumps(self.change))
        invalid["edits"]["hard"]["source_url"] = "http://example.org/source"
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            correct_map_queue.correct(self.database, [invalid], apply=True, backup_root=self.backups)
        invalid = json.loads(json.dumps(self.change))
        invalid["edits"]["hard"]["old"] = "Different old clue"
        with self.assertRaisesRegex(ValueError, "reviewed clue"):
            correct_map_queue.correct(self.database, [invalid], apply=True, backup_root=self.backups)
        invalid = json.loads(json.dumps(self.change))
        invalid["name"] = "Different place"
        with self.assertRaisesRegex(ValueError, "expected name"):
            correct_map_queue.correct(self.database, [invalid], apply=True, backup_root=self.backups)
        with self.assertRaisesRegex(ValueError, "backup root"):
            correct_map_queue.correct(self.database, [self.change], apply=True)
        self.assertEqual(list(self.backups.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
