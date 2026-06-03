from __future__ import annotations

import json
import sqlite3
import unittest
from unittest.mock import patch

import daily_quiz


def config(max_attempts: int = 3) -> daily_quiz.QuizConfig:
    return daily_quiz.QuizConfig(
        provider="gemini",
        generator_model="test-generator",
        critic_model="test-critic",
        gemini_api_key="test-key",
        compatible_api_key="",
        compatible_base_url="",
        fallback_provider="",
        fallback_generator_model="",
        fallback_critic_model="",
        fallback_gemini_api_key="",
        fallback_compatible_api_key="",
        fallback_compatible_base_url="",
        timeout_sec=5,
        request_delay_sec=0,
        transient_retries=0,
        max_attempts_per_slot=max_attempts,
        question_history_days=90,
        internal_token="test-token",
    )


def valid_question(subject: str = "general_knowledge", difficulty: str = "easy") -> dict[str, object]:
    label = f"{subject.replace('_', ' ')} {difficulty}"
    questions = {
        ("general_knowledge", "easy"): "Which historical detail best identifies this broad-audience quiz example?",
        ("general_knowledge", "medium"): "Which scientific instrument is associated with this contextual quiz example?",
        ("general_knowledge", "hard"): "Which ancient civilization is linked to this more specific quiz example?",
        ("football", "easy"): "Which football competition is associated with this broad-audience quiz example?",
        ("football", "medium"): "Which football rule is linked to this contextual quiz example?",
        ("football", "hard"): "Which football manager is connected to this more specific quiz example?",
    }
    return {
        "subject": subject,
        "difficulty": difficulty,
        "question": questions[(subject, difficulty)],
        "choices": [
            f"{label} answer",
            f"{label} distractor one",
            f"{label} distractor two",
            f"{label} distractor three",
        ],
        "correct_answer": f"{label} answer",
        "explanation": f"The {label} answer is the only choice that matches the verified historical detail.",
        "interesting_reason": f"This {label} example tests a memorable connection rather than an isolated fact.",
        "tags": [label, f"{label} topic"],
    }


def passing_critic() -> dict[str, object]:
    return {
        "passed": True,
        "scores": {
            "validity": 10,
            "correctness": 10,
            "difficulty_match": 10,
            "interestingness": 9,
            "non_repetition": 10,
        },
        "failure_reasons": [],
        "feedback_to_generator": "",
        "corrected_difficulty": "easy",
        "notes": "Suitable for publication.",
    }


class FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self.generation_calls: list[tuple[str, str, list[str]]] = []
        self.failed_validation = False
        self.failed_critic = False

    def generate_question(
        self,
        *,
        subject: str,
        difficulty: str,
        recent_questions: list[dict[str, object]],
        feedback: list[str],
    ) -> dict[str, object]:
        self.generation_calls.append((subject, difficulty, list(feedback)))
        question = valid_question(subject, difficulty)
        if subject == "general_knowledge" and difficulty == "easy" and not self.failed_validation:
            self.failed_validation = True
            question.pop("tags")
        return question

    def critique_question(
        self,
        *,
        subject: str,
        difficulty: str,
        question: dict[str, object],
        recent_questions: list[dict[str, object]],
    ) -> dict[str, object]:
        critic = passing_critic()
        critic["corrected_difficulty"] = difficulty
        if subject == "general_knowledge" and difficulty == "medium" and not self.failed_critic:
            self.failed_critic = True
            critic["passed"] = False
            critic["scores"] = {**critic["scores"], "interestingness": 4}
            critic["failure_reasons"] = ["Question is too generic."]
            critic["feedback_to_generator"] = "Use a more memorable historical connection."
        return critic


class AlwaysInvalidProvider:
    name = "always-invalid"

    def generate_question(self, **_: object) -> dict[str, object]:
        return {"subject": "football"}

    def critique_question(self, **_: object) -> dict[str, object]:
        raise AssertionError("Invalid questions must not reach the critic.")


class AlwaysFailingProvider:
    def __init__(self, name: str, reason: str = "rate limited") -> None:
        self.name = name
        self.reason = reason

    def generate_question(self, **_: object) -> dict[str, object]:
        raise RuntimeError(self.reason)

    def critique_question(self, **_: object) -> dict[str, object]:
        raise RuntimeError(self.reason)


class PassingProvider:
    def __init__(self, name: str) -> None:
        self.name = name

    def generate_question(
        self,
        *,
        subject: str,
        difficulty: str,
        recent_questions: list[dict[str, object]],
        feedback: list[str],
    ) -> dict[str, object]:
        return valid_question(subject, difficulty)

    def critique_question(
        self,
        *,
        subject: str,
        difficulty: str,
        question: dict[str, object],
        recent_questions: list[dict[str, object]],
    ) -> dict[str, object]:
        critic = passing_critic()
        critic["corrected_difficulty"] = difficulty
        return critic


class DailyQuizTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        daily_quiz.initialize_database(self.conn)
        self.addCleanup(self.conn.close)

    def test_validator_accepts_well_formed_question(self) -> None:
        result = daily_quiz.validate_question(valid_question())

        self.assertTrue(result.passed)
        self.assertIsNotNone(result.question)

    def test_validator_rejects_invalid_question_shapes(self) -> None:
        cases: list[tuple[str, dict[str, object]]] = []

        missing_tags = valid_question()
        missing_tags.pop("tags")
        cases.append(("Missing required fields", missing_tags))

        duplicate_choices = valid_question()
        duplicate_choices["choices"] = ["One", "one", "Two", "Three"]
        duplicate_choices["correct_answer"] = "One"
        cases.append(("unique", duplicate_choices))

        bad_answer = valid_question()
        bad_answer["correct_answer"] = "Not a listed choice"
        cases.append(("exactly match", bad_answer))

        statement = valid_question()
        statement["question"] = "This sentence is a factual statement rather than a quiz question."
        cases.append(("question mark", statement))

        for expected_reason, question in cases:
            with self.subTest(expected_reason=expected_reason):
                result = daily_quiz.validate_question(question)
                self.assertFalse(result.passed)
                self.assertIn(expected_reason, result.reason)

    def test_repetition_detects_normalized_duplicates(self) -> None:
        question = valid_question()
        previous = [{**question, "question": question["question"].upper().rstrip("?") + "!!!"}]

        result = daily_quiz.check_repetition(question, previous)

        self.assertFalse(result.passed)
        self.assertIn("duplicates", result.reason)

    def test_repetition_detects_overused_answer(self) -> None:
        question = valid_question()
        previous = [
            {
                **valid_question(difficulty="medium"),
                "question": "Which instrument has a keyboard, pedals, and strings struck by felt hammers?",
                "correct_answer": question["correct_answer"],
            },
            {
                **valid_question(difficulty="hard"),
                "question": "Who was the first person to walk on the Moon during the Apollo 11 mission?",
                "correct_answer": question["correct_answer"],
            },
        ]

        result = daily_quiz.check_repetition(question, previous)

        self.assertFalse(result.passed)
        self.assertIn("answer", result.reason.lower())

    def test_repetition_rejects_answer_already_used_in_same_quiz(self) -> None:
        question = valid_question(difficulty="medium")
        previous = [
            {
                **valid_question(difficulty="easy"),
                "question": "Which planet is known for the persistent storm called the Great Red Spot?",
                "correct_answer": question["correct_answer"],
            }
        ]

        result = daily_quiz.check_repetition(
            question,
            previous,
            reject_any_repeated_answer=True,
        )

        self.assertFalse(result.passed)
        self.assertIn("quiz set", result.reason)

    def test_generation_retries_and_publishes_only_after_six_approved_slots(self) -> None:
        provider = FakeProvider()

        payload = daily_quiz.generate_daily_quiz(
            self.conn,
            quiz_date="2026-06-02",
            config=config(),
            provider=provider,
            log=lambda _: None,
        )

        self.assertEqual(payload["status"], "published")
        self.assertEqual(len(payload["questions"]), 6)
        status = daily_quiz.quiz_status(self.conn, "2026-06-02")
        self.assertEqual(status["accepted_questions"], 6)
        self.assertEqual(status["failed_attempts"], 2)
        self.assertTrue(
            any(
                feedback and "Missing required fields" in feedback[-1]
                for subject, difficulty, feedback in provider.generation_calls
                if subject == "general_knowledge" and difficulty == "easy"
            )
        )
        public_question = payload["questions"][0]
        self.assertNotIn("interesting_reason", public_question)
        self.assertNotIn("tags", public_question)
        self.assertNotIn("critic", public_question)

    def test_generation_marks_set_failed_after_retry_limit(self) -> None:
        result = daily_quiz.generate_daily_quiz(
            self.conn,
            quiz_date="2026-06-03",
            config=config(max_attempts=2),
            provider=AlwaysInvalidProvider(),
            log=lambda _: None,
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["accepted_questions"], 0)
        self.assertEqual(result["failed_attempts"], 2)
        with self.assertRaises(LookupError):
            daily_quiz.quiz_payload(self.conn, "2026-06-03")

    def test_unconfigured_provider_fails_without_silent_fallback(self) -> None:
        unconfigured = daily_quiz.QuizConfig(
            **{**config().__dict__, "gemini_api_key": ""},
        )

        result = daily_quiz.generate_daily_quiz(
            self.conn,
            quiz_date="2026-06-04",
            config=unconfigured,
            log=lambda _: None,
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("not configured", result["failure_reason"])

    def test_provider_chain_uses_fallback_provider_after_primary_failure(self) -> None:
        provider = daily_quiz.FallbackQuizProvider(
            [
                AlwaysFailingProvider("gemini", "Gemini request failed with HTTP 429."),
                PassingProvider("openrouter"),
            ]
        )

        payload = daily_quiz.generate_daily_quiz(
            self.conn,
            quiz_date="2026-06-05",
            config=config(),
            provider=provider,
            log=lambda _: None,
        )

        self.assertEqual(payload["status"], "published")
        providers = {
            row["provider"]
            for row in self.conn.execute(
                "SELECT DISTINCT provider FROM daily_quiz_attempts WHERE quiz_date = ? AND passed = 1",
                ("2026-06-05",),
            )
        }
        self.assertEqual(providers, {"openrouter"})

    def test_provider_chain_from_config_includes_openrouter_fallback(self) -> None:
        chain = daily_quiz.provider_chain_from_config(
            daily_quiz.QuizConfig(
                **{
                    **config().__dict__,
                    "fallback_provider": "openrouter",
                    "fallback_generator_model": "openai/gpt-4.1-mini",
                    "fallback_critic_model": "openai/gpt-4.1-mini",
                    "fallback_compatible_api_key": "or-key",
                    "fallback_compatible_base_url": "https://openrouter.ai/api/v1",
                }
            )
        )

        self.assertIsInstance(chain, daily_quiz.FallbackQuizProvider)
        self.assertEqual([provider.name for provider in chain.providers], ["gemini", "openrouter"])

    def test_gemini_retry_uses_structured_retry_delay(self) -> None:
        class RateLimitError:
            headers: dict[str, str] = {}

            def read(self) -> bytes:
                return json.dumps(
                    {
                        "error": {
                            "details": [
                                {
                                    "@type": "type.googleapis.com/google.rpc.RetryInfo",
                                    "retryDelay": "28s",
                                }
                            ]
                        }
                    }
                ).encode("utf-8")

        provider = daily_quiz.GeminiProvider(
            daily_quiz.QuizConfig(
                **{**config().__dict__, "request_delay_sec": 12},
            )
        )
        with patch("daily_quiz.time.monotonic", return_value=100.0):
            provider._defer_retry(0, RateLimitError())  # type: ignore[arg-type]

        self.assertEqual(provider._next_request_at, 128.0)


if __name__ == "__main__":
    unittest.main()
