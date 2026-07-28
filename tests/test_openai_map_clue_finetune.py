from __future__ import annotations

import importlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

finetune = importlib.import_module("tools.openai_map_clue_finetune")


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=True))
            handle.write("\n")


def clue_ladder() -> dict[str, str]:
    return {
        "hard": "A famous boot room helped produce several generations of successful managers.",
        "medium": "Supporters sing You'll Never Walk Alone before the biggest matches.",
        "easy": "The Kop creates a towering wall of red behind one goal.",
        "reveal": "Anfield is the match, combining its boot-room history, famous anthem, and the Kop.",
    }


def sft_record() -> dict[str, Any]:
    return {
        "messages": [
            {"role": "system", "content": "Return JSON only."},
            {"role": "user", "content": "Generate a map clue ladder."},
            {"role": "assistant", "content": json.dumps(clue_ladder(), ensure_ascii=True)},
        ],
        "metadata": {
            "place": "Anfield",
            "place_type": "stadium",
            "difficulty": "easy",
        },
    }


def eval_record() -> dict[str, Any]:
    return {
        "input": {"system": "Return JSON only.", "prompt": "Generate a map clue ladder."},
        "expected": clue_ladder(),
        "metadata": {
            "place": "Anfield",
            "place_type": "stadium",
            "difficulty": "easy",
        },
    }


class OpenAIMapClueFineTuneTests(unittest.TestCase):
    def test_prepare_artifacts_combines_map_train_and_eval_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            train = root / "map_clue_sft_train_test.jsonl"
            eval_file = root / "map_clue_eval_test.jsonl"
            negative = root / "map_clue_negative_test.jsonl"
            write_jsonl(train, [sft_record()])
            write_jsonl(eval_file, [eval_record()])
            write_jsonl(negative, [{"metadata": {"reason": "map_clue_quality_gate"}}])

            result = finetune.prepare_artifacts(
                training_dir=root,
                out_dir=root / "out",
                train_files=[train],
                eval_files=[eval_file],
                negative_files=[negative],
                prefix="test_map",
            )
            train_records = finetune.read_jsonl(result.train_path)
            validation_records = finetune.read_jsonl(result.validation_path)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(result.train_count, 1)
        self.assertEqual(result.validation_count, 1)
        self.assertEqual(train_records[0]["messages"][2]["role"], "assistant")
        self.assertEqual(validation_records[0]["messages"][2]["role"], "assistant")
        self.assertEqual(json.loads(validation_records[0]["messages"][2]["content"])["easy"], clue_ladder()["easy"])
        self.assertFalse(manifest["strict_validation"])
        self.assertEqual(len(manifest["negative_files_excluded"]), 1)

    def test_load_env_file_does_not_override_existing_values_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env.local"
            env_path.write_text(
                "OPENAI_API_KEY=from-file\nOPENAI_MAP_CLUE_FT_BASE_MODEL=gpt-map-file\n",
                encoding="utf-8",
            )
            with patch.dict(
                "os.environ",
                {"OPENAI_API_KEY": "already-set"},
                clear=False,
            ):
                loaded = finetune.load_env_file(env_path)

                self.assertEqual(loaded, {"OPENAI_MAP_CLUE_FT_BASE_MODEL": "gpt-map-file"})
                self.assertEqual(finetune.os.environ["OPENAI_API_KEY"], "already-set")
                self.assertEqual(finetune.os.environ["OPENAI_MAP_CLUE_FT_BASE_MODEL"], "gpt-map-file")

    def test_prepare_artifacts_rejects_negative_file_as_training_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            train = root / "map_clue_negative_test.jsonl"
            eval_file = root / "map_clue_eval_test.jsonl"
            write_jsonl(train, [sft_record()])
            write_jsonl(eval_file, [eval_record()])

            with self.assertRaisesRegex(ValueError, "Negative file cannot be used"):
                finetune.prepare_artifacts(
                    training_dir=root,
                    out_dir=root / "out",
                    train_files=[train],
                    eval_files=[eval_file],
                    prefix="test_map",
                )

    def test_create_fine_tune_job_forms_upload_and_job_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            train = root / "map_clue_sft_train_test.jsonl"
            eval_file = root / "map_clue_eval_test.jsonl"
            write_jsonl(train, [sft_record()])
            write_jsonl(eval_file, [eval_record()])
            artifacts = finetune.prepare_artifacts(
                training_dir=root,
                out_dir=root / "out",
                train_files=[train],
                eval_files=[eval_file],
                prefix="test_map",
            )

            class FakeClient:
                def __init__(self) -> None:
                    self.uploads: list[Path] = []
                    self.payload: dict[str, Any] | None = None

                def upload_file(self, path: Path, *, purpose: str = "fine-tune") -> dict[str, Any]:
                    self.uploads.append(path)
                    return {"id": f"file-map-{len(self.uploads)}", "purpose": purpose}

                def post_json(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
                    self.payload = payload
                    return {"id": "ftjob-map-1", "status": "queued", "fine_tuned_model": None}

            client = FakeClient()
            result = finetune.openai_quiz_finetune.create_fine_tune_job(
                client=client,
                artifacts=artifacts,
                base_model="gpt-map-base",
                suffix="fultons-map-test",
            )

        self.assertEqual([path.name for path in client.uploads], [artifacts.train_path.name, artifacts.validation_path.name])
        self.assertEqual(client.payload["training_file"], "file-map-1")
        self.assertEqual(client.payload["validation_file"], "file-map-2")
        self.assertEqual(client.payload["model"], "gpt-map-base")
        self.assertEqual(client.payload["suffix"], "fultons-map-test")
        self.assertEqual(result["job"]["id"], "ftjob-map-1")


if __name__ == "__main__":
    unittest.main()
