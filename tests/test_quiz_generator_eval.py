from __future__ import annotations

import importlib
import os
import unittest
from unittest import mock
from typing import Any

evaluator = importlib.import_module("tools.evaluate_quiz_generator")


def valid_eval_question(
    *,
    subject: str = "football",
    difficulty: str = "easy",
    answer: str = "Cricket",
) -> dict[str, Any]:
    return {
        "subject": subject,
        "difficulty": difficulty,
        "question": "Which sport gave football the term hat-trick?",
        "choices": [answer, "Tennis", "Rugby", "Golf"],
        "correct_answer": answer,
        "explanation": "The term came from cricket before becoming common in football.",
        "interesting_reason": "The question connects football language to another sport.",
        "tags": ["hat-trick", "cricket"],
    }


def eval_record(
    expected: dict[str, Any] | None = None,
    *,
    recent_questions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    expected = expected or valid_eval_question()
    return {
        "metadata": {
            "quiz_date": "2026-07-14",
            "question_id": 10,
            "subject": expected["subject"],
            "difficulty": expected["difficulty"],
        },
        "context": {
            "subject": expected["subject"],
            "difficulty": expected["difficulty"],
            "recent_questions": recent_questions or [],
            "feedback": [],
        },
        "input": {"system": "Return JSON only.", "prompt": "Generate a test question."},
        "expected_output": expected,
    }


class StaticGenerator:
    name = "static"

    def __init__(self, generated: Any) -> None:
        self.generated = generated

    def generate(self, record: dict[str, Any]) -> Any:
        return self.generated

    def critique(self, record: dict[str, Any], question: dict[str, Any]) -> dict[str, Any] | None:
        return None


class StaticProvider:
    name = "static-openai"

    def generate_question(self, **kwargs: Any) -> dict[str, Any]:
        return valid_eval_question()

    def critique_question(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "passed": True,
            "scores": {
                "validity": 10,
                "correctness": 10,
                "difficulty_match": 10,
                "interestingness": 10,
                "non_repetition": 10,
            },
            "failure_reasons": [],
            "feedback_to_generator": "",
            "corrected_difficulty": "easy",
            "notes": "OK",
        }


class QuizGeneratorEvalTests(unittest.TestCase):
    def test_fixture_expected_output_scores_as_publishable(self) -> None:
        report = evaluator.evaluate_records(
            [eval_record()],
            evaluator.FixtureExpectedGenerator(),
        )

        metrics = report["metrics"]
        self.assertEqual(metrics["total"], 1)
        self.assertEqual(metrics["valid_json"], 1)
        self.assertEqual(metrics["validation_passed"], 1)
        self.assertEqual(metrics["repetition_passed"], 1)
        self.assertEqual(metrics["publishable"], 1)
        self.assertEqual(report["failures"], [])

    def test_malformed_json_is_reported(self) -> None:
        report = evaluator.evaluate_records(
            [eval_record()],
            StaticGenerator("{not valid json"),
        )

        self.assertEqual(report["metrics"]["valid_json"], 0)
        self.assertEqual(report["metrics"]["publishable"], 0)
        self.assertEqual(report["failures"][0]["stage"], "json")

    def test_wrong_subject_or_difficulty_fails_validation(self) -> None:
        generated = valid_eval_question(subject="general_knowledge", difficulty="hard")

        report = evaluator.evaluate_records(
            [eval_record()],
            StaticGenerator(generated),
        )

        self.assertEqual(report["metrics"]["subject_match"], 0)
        self.assertEqual(report["metrics"]["difficulty_match"], 0)
        self.assertEqual(report["metrics"]["validation_passed"], 0)
        self.assertEqual(report["failures"][0]["stage"], "validation")

    def test_recent_repetition_is_reported(self) -> None:
        generated = valid_eval_question()
        recent = [
            {
                "subject": "football",
                "difficulty": "easy",
                "question": "The football term hat-trick originated from which sport?",
                "correct_answer": "Cricket",
                "tags": ["hat-trick", "cricket"],
            }
        ]

        report = evaluator.evaluate_records(
            [eval_record(recent_questions=recent)],
            StaticGenerator(generated),
        )

        self.assertEqual(report["metrics"]["validation_passed"], 1)
        self.assertEqual(report["metrics"]["repetition_passed"], 0)
        self.assertEqual(report["metrics"]["publishable"], 0)
        self.assertEqual(report["failures"][0]["stage"], "repetition")

    def test_openai_compatible_generator_uses_supplied_candidate_config(self) -> None:
        captured = {}

        def fake_provider_chain(config: Any) -> StaticProvider:
            captured["provider"] = config.provider
            captured["generator_model"] = config.generator_model
            captured["critic_model"] = config.critic_model
            captured["base_url"] = config.compatible_base_url
            captured["api_key"] = config.compatible_api_key
            return StaticProvider()

        args = type(
            "Args",
            (),
            {
                "provider": "openai-compatible",
                "api_key_env": "TEST_OPENAI_API_KEY",
                "generator_model": "ft:gpt-test:fultons",
                "critic_model": "gpt-test-critic",
                "base_url": "https://api.openai.com/v1",
            },
        )()

        with mock.patch.dict(os.environ, {"TEST_OPENAI_API_KEY": "test-key"}), mock.patch(
            "daily_quiz.provider_chain_from_config",
            side_effect=fake_provider_chain,
        ):
            generator = evaluator.generator_from_args(args)

        self.assertEqual(generator.name, "openai-compatible:ft:gpt-test:fultons")
        self.assertEqual(captured["provider"], "openai-compatible")
        self.assertEqual(captured["generator_model"], "ft:gpt-test:fultons")
        self.assertEqual(captured["critic_model"], "gpt-test-critic")
        self.assertEqual(captured["base_url"], "https://api.openai.com/v1")
        self.assertEqual(captured["api_key"], "test-key")


if __name__ == "__main__":
    unittest.main()
