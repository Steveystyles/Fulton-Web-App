from __future__ import annotations

import importlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

finetune = importlib.import_module("tools.openai_quiz_finetune")


def valid_question(
    *,
    subject: str = "football",
    difficulty: str = "medium",
    answer: str = "Brazil",
) -> dict[str, Any]:
    return {
        "subject": subject,
        "difficulty": difficulty,
        "question": "Which nation won the 1970 FIFA World Cup final in Mexico City?",
        "choices": [answer, "Italy", "England", "West Germany"],
        "correct_answer": answer,
        "explanation": "Brazil beat Italy in the 1970 FIFA World Cup final in Mexico City.",
        "interesting_reason": "The match is one of football's most famous World Cup finals.",
        "tags": ["football", "world-cup"],
    }


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=True))
            handle.write("\n")


def sft_record(question: dict[str, Any] | None = None) -> dict[str, Any]:
    question = question or valid_question()
    return {
        "messages": [
            {"role": "system", "content": "Return JSON only."},
            {"role": "user", "content": "Generate a football question."},
            {"role": "assistant", "content": json.dumps(question, ensure_ascii=True)},
        ]
    }


def eval_record(question: dict[str, Any] | None = None) -> dict[str, Any]:
    question = question or valid_question()
    return {
        "metadata": {"subject": question["subject"], "difficulty": question["difficulty"]},
        "context": {
            "subject": question["subject"],
            "difficulty": question["difficulty"],
            "recent_questions": [],
            "feedback": [],
        },
        "input": {"system": "Return JSON only.", "prompt": "Generate a football question."},
        "expected_output": question,
    }


class OpenAIQuizFineTuneTests(unittest.TestCase):
    def test_prepare_artifacts_combines_training_and_eval_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            train = root / "quiz_sft_train_test.jsonl"
            eval_file = root / "quiz_eval_test.jsonl"
            negative = root / "football_review_negative_test.jsonl"
            write_jsonl(train, [sft_record()])
            write_jsonl(eval_file, [eval_record()])
            write_jsonl(negative, [{"metadata": {"reason": "low_review_score"}}])

            result = finetune.prepare_artifacts(
                training_dir=root,
                out_dir=root / "out",
                train_files=[train],
                eval_files=[eval_file],
                negative_files=[negative],
                prefix="test_openai",
            )
            train_records = finetune.read_jsonl(result.train_path)
            validation_records = finetune.read_jsonl(result.validation_path)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(result.train_count, 1)
        self.assertEqual(result.validation_count, 1)
        self.assertEqual(train_records[0]["messages"][2]["role"], "assistant")
        self.assertEqual(validation_records[0]["messages"][2]["role"], "assistant")
        self.assertIn("negative_files_excluded", manifest)
        self.assertEqual(len(manifest["negative_files_excluded"]), 1)

    def test_prepare_artifacts_rejects_negative_file_as_training_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            train = root / "football_review_negative_test.jsonl"
            eval_file = root / "quiz_eval_test.jsonl"
            write_jsonl(train, [sft_record()])
            write_jsonl(eval_file, [eval_record()])

            with self.assertRaisesRegex(ValueError, "Negative file cannot be used"):
                finetune.prepare_artifacts(
                    training_dir=root,
                    out_dir=root / "out",
                    train_files=[train],
                    eval_files=[eval_file],
                    prefix="test_openai",
                )

    def test_create_fine_tune_job_forms_upload_and_job_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            train = root / "quiz_sft_train_test.jsonl"
            eval_file = root / "quiz_eval_test.jsonl"
            write_jsonl(train, [sft_record()])
            write_jsonl(eval_file, [eval_record()])
            artifacts = finetune.prepare_artifacts(
                training_dir=root,
                out_dir=root / "out",
                train_files=[train],
                eval_files=[eval_file],
                prefix="test_openai",
            )

            class FakeClient:
                def __init__(self) -> None:
                    self.uploads: list[Path] = []
                    self.payload: dict[str, Any] | None = None

                def upload_file(self, path: Path, *, purpose: str = "fine-tune") -> dict[str, Any]:
                    self.uploads.append(path)
                    return {"id": f"file-{len(self.uploads)}", "purpose": purpose}

                def post_json(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
                    self.payload = payload
                    return {"id": "ftjob-1", "status": "queued", "fine_tuned_model": None}

            client = FakeClient()
            result = finetune.create_fine_tune_job(
                client=client,
                artifacts=artifacts,
                base_model="gpt-test-base",
                suffix="fultons-test",
            )

        self.assertEqual([path.name for path in client.uploads], [artifacts.train_path.name, artifacts.validation_path.name])
        self.assertEqual(client.payload["training_file"], "file-1")
        self.assertEqual(client.payload["validation_file"], "file-2")
        self.assertEqual(client.payload["model"], "gpt-test-base")
        self.assertEqual(client.payload["suffix"], "fultons-test")
        self.assertEqual(result["job"]["id"], "ftjob-1")


if __name__ == "__main__":
    unittest.main()
