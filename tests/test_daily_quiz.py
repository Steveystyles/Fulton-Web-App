from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

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
        fallback2_provider="",
        fallback2_generator_model="",
        fallback2_critic_model="",
        fallback2_gemini_api_key="",
        fallback2_compatible_api_key="",
        fallback2_compatible_base_url="",
        timeout_sec=5,
        request_delay_sec=0,
        transient_retries=0,
        max_attempts_per_slot=max_attempts,
        question_history_days=90,
        learning_profile_path="",
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


def supporting_evidence(question: dict[str, object], **_: object) -> list[dict[str, str]]:
    answer = str(question.get("correct_answer") or "")
    claim = " ".join(
        str(question.get(field) or "")
        for field in ("question", "explanation", "interesting_reason")
    )
    return [
        {
            "title": f"Official record for {answer}",
            "source_name": "example.edu",
            "source_url": "https://example.edu/reference/one",
            "tier": "primary",
            "snippet": f"{answer}. {claim}",
            "excerpt": f"The documented answer is {answer}. {claim}",
            "query": answer,
        },
        {
            "title": f"Independent account of {answer}",
            "source_name": "bbc.co.uk",
            "source_url": "https://www.bbc.co.uk/archive/two",
            "tier": "reputable",
            "snippet": f"{answer}. {claim}",
            "excerpt": f"Independent evidence identifies {answer}. {claim}",
            "query": answer,
        },
    ]


def passing_verification(evidence: list[dict[str, object]]) -> dict[str, object]:
    return {
        "passed": True,
        "premise_supported": True,
        "answer_supported": True,
        "unique_answer": True,
        "claims": [
            {
                "claim": "The question premise and proposed answer are supported.",
                "status": "supported",
                "evidence_indices": list(range(min(2, len(evidence)))),
            }
        ],
        "failure_reasons": [],
        "feedback_to_generator": "",
        "notes": "The supplied evidence supports publication.",
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

    def verify_question(self, *, evidence: list[dict[str, object]], **_: object) -> dict[str, object]:
        return passing_verification(evidence)


class AlwaysInvalidProvider:
    name = "always-invalid"

    def generate_question(self, **_: object) -> dict[str, object]:
        return {"subject": "football"}

    def critique_question(self, **_: object) -> dict[str, object]:
        raise AssertionError("Invalid questions must not reach the critic.")

    def verify_question(self, **_: object) -> dict[str, object]:
        raise AssertionError("Invalid questions must not reach the verifier.")


class AlwaysFailingProvider:
    def __init__(self, name: str, reason: str = "rate limited") -> None:
        self.name = name
        self.reason = reason

    def generate_question(self, **_: object) -> dict[str, object]:
        raise RuntimeError(self.reason)

    def critique_question(self, **_: object) -> dict[str, object]:
        raise RuntimeError(self.reason)

    def verify_question(self, **_: object) -> dict[str, object]:
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

    def verify_question(self, *, evidence: list[dict[str, object]], **_: object) -> dict[str, object]:
        return passing_verification(evidence)

class CriticUnavailableProvider(PassingProvider):
    def critique_question(
        self,
        *,
        subject: str,
        difficulty: str,
        question: dict[str, object],
        recent_questions: list[dict[str, object]],
    ) -> dict[str, object]:
        raise RuntimeError("Gemini request failed with HTTP 429.")


class InvalidCriticProvider(PassingProvider):
    def critique_question(
        self,
        *args: object,
        **kwargs: object,
    ) -> dict[str, object]:
        return {"passed": True}


class VerifierUnavailableProvider(PassingProvider):
    def verify_question(self, **_: object) -> dict[str, object]:
        raise RuntimeError("Gemini request failed with HTTP 429.")


class InvalidVerifierProvider(PassingProvider):
    def verify_question(self, **_: object) -> dict[str, object]:
        return {"passed": True}


class FeedbackReuseProvider(PassingProvider):
    def __init__(self) -> None:
        super().__init__("feedback-reuse")
        self.feedback_calls: list[list[str]] = []

    def generate_question(
        self,
        *,
        subject: str,
        difficulty: str,
        recent_questions: list[dict[str, object]],
        feedback: list[str],
    ) -> dict[str, object]:
        if subject == "football" and difficulty == "easy":
            self.feedback_calls.append(list(feedback))
            if not feedback:
                return {"subject": "football"}
        return valid_question(subject, difficulty)


class CandidateProvider(PassingProvider):
    def __init__(
        self,
        name: str = "candidate-provider",
        *,
        blocked_answer: str | None = None,
        invalid_first_batch: bool = False,
    ) -> None:
        super().__init__(name)
        self.blocked_answer = blocked_answer
        self.invalid_first_batch = invalid_first_batch
        self.discovery_calls = 0
        self.composition_calls = 0
        self.critic_calls = 0

    def discover_candidates(
        self,
        *,
        subject: str,
        difficulty: str,
        topic_lane: str,
        batch_size: int,
        **_: object,
    ) -> dict[str, object]:
        self.discovery_calls += 1
        if self.invalid_first_batch and self.discovery_calls == 1:
            return {"candidates": [{"answer": "invalid"} for _ in range(batch_size)]}
        candidates: list[dict[str, object]] = []
        for index in range(batch_size):
            answer = (
                self.blocked_answer
                if self.blocked_answer and self.discovery_calls == 1
                else f"{subject} {difficulty} candidate {self.discovery_calls}-{index}"
            )
            hook_templates = (
                "A documented ceremony connected {answer} with a landmark public milestone recorded by contemporary sources.",
                "Archival evidence shows that {answer} played the decisive role in an unusual competition incident.",
                "Researchers identify {answer} through a distinctive discovery that changed later practice in the field.",
            )
            hook = hook_templates[(self.discovery_calls - 1) % len(hook_templates)].format(
                answer=answer
            )
            candidates.append(
                {
                    "answer": answer,
                    "hook": hook,
                    "topic_lane": topic_lane,
                    "era": "twentieth century",
                    "region": "Europe",
                    "tags": [topic_lane, f"test-event-{self.discovery_calls}-{index}"],
                    "evidence_query": f"{answer} documented historical milestone",
                }
            )
        return {"candidates": candidates}

    def compose_question(
        self,
        *,
        subject: str,
        difficulty: str,
        candidate: dict[str, object],
        **_: object,
    ) -> dict[str, object]:
        self.composition_calls += 1
        answer = str(candidate["answer"])
        hook = str(candidate["hook"])
        slot_question = str(valid_question(subject, difficulty)["question"])
        return {
            "subject": subject,
            "difficulty": difficulty,
            "question": slot_question,
            "choices": [answer, "Alternative Alpha", "Alternative Beta", "Alternative Gamma"],
            "correct_answer": answer,
            "explanation": f"{answer} is correct because the supplied evidence documents the milestone clearly.",
            "interesting_reason": hook,
            "tags": list(candidate["tags"]),
        }

    def critique_question(self, **kwargs: object) -> dict[str, object]:
        self.critic_calls += 1
        return super().critique_question(**kwargs)


class DailyQuizTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        daily_quiz.initialize_database(self.conn)
        self.addCleanup(self.conn.close)
        evidence_patcher = patch(
            "daily_quiz.collect_question_evidence",
            side_effect=supporting_evidence,
        )
        evidence_patcher.start()
        self.addCleanup(evidence_patcher.stop)

    def test_validator_accepts_well_formed_question(self) -> None:
        result = daily_quiz.validate_question(valid_question())

        self.assertTrue(result.passed)
        self.assertIsNotNone(result.question)

    def test_config_reuses_openrouter_fallback_for_evidence_search(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AI_PROVIDER": "gemini",
                "GEMINI_API_KEY": "gemini-key",
                "AI_FALLBACK_PROVIDER": "openrouter",
                "AI_FALLBACK_GENERATOR_MODEL": "openrouter/free",
                "AI_FALLBACK_CRITIC_MODEL": "openrouter/free",
                "AI_FALLBACK_API_KEY": "openrouter-key",
                "AI_FALLBACK_BASE_URL": "https://openrouter.ai/api/v1",
            },
            clear=True,
        ):
            loaded = daily_quiz.QuizConfig.from_env()

        self.assertEqual(loaded.evidence_openrouter_api_key, "openrouter-key")
        self.assertEqual(loaded.evidence_openrouter_model, "openrouter/free")
        self.assertEqual(
            loaded.evidence_openrouter_base_url,
            "https://openrouter.ai/api/v1",
        )

    def test_candidate_pipeline_publishes_verified_questions(self) -> None:
        provider = CandidateProvider()
        pipeline_config = replace(
            config(),
            candidate_pipeline_enabled=True,
            candidate_batch_size=8,
            candidate_batches_per_slot=3,
        )

        result = daily_quiz.generate_daily_quiz(
            self.conn,
            quiz_date="2026-08-20",
            config=pipeline_config,
            provider=provider,
        )

        self.assertEqual(result["status"], "published")
        status = daily_quiz.quiz_status(self.conn, "2026-08-20")
        self.assertEqual(status["pipeline_version"], "candidate-v1")
        self.assertEqual(status["verified_questions"], 6)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM daily_quiz_candidates WHERE status='accepted'"
            ).fetchone()[0],
            6,
        )
        self.assertEqual(provider.composition_calls, 6)

    def test_candidate_pipeline_filters_embargoed_answer_before_composition(self) -> None:
        old_set = daily_quiz.get_or_create_quiz_set(self.conn, "2026-08-18")
        old_question = valid_question("football", "easy")
        old_question["question"] = (
            "Which football side is represented by this deliberately older embargo example?"
        )
        old_question["correct_answer"] = "Blocked Football Answer"
        old_question["choices"][0] = "Blocked Football Answer"
        daily_quiz.save_question(
            self.conn,
            quiz_set_id=old_set["id"],
            question=old_question,
            evidence=supporting_evidence(old_question),
            verification=passing_verification(supporting_evidence(old_question)),
        )
        daily_quiz.set_quiz_status(self.conn, "2026-08-18", "published")
        target = daily_quiz.get_or_create_quiz_set(self.conn, "2026-08-20")
        provider = CandidateProvider(blocked_answer="Blocked Football Answer")
        pipeline_config = replace(
            config(),
            candidate_pipeline_enabled=True,
            candidate_batch_size=8,
            candidate_batches_per_slot=2,
        )

        result = daily_quiz.generate_slot(
            self.conn,
            quiz_set_id=target["id"],
            quiz_date="2026-08-20",
            subject="football",
            difficulty="easy",
            provider=provider,
            config=pipeline_config,
            log=lambda _: None,
        )

        self.assertTrue(result)
        self.assertEqual(provider.discovery_calls, 2)
        self.assertEqual(provider.composition_calls, 1)
        local_rejections = self.conn.execute(
            """
            SELECT COUNT(*) FROM daily_quiz_candidates
            WHERE rejection_stage='local' AND failure_reason LIKE '%embargo%'
            """
        ).fetchone()[0]
        self.assertEqual(local_rejections, 8)

    def test_candidate_pipeline_does_not_compose_unsupported_hook(self) -> None:
        target = daily_quiz.get_or_create_quiz_set(self.conn, "2026-08-20")
        provider = CandidateProvider()
        pipeline_config = replace(
            config(),
            candidate_pipeline_enabled=True,
            candidate_batch_size=2,
            candidate_batches_per_slot=1,
        )
        unsupported = [
            {
                "title": "Unrelated source",
                "source_name": "example.edu",
                "source_url": "https://example.edu/unrelated",
                "tier": "primary",
                "snippet": "This source concerns an unrelated subject.",
                "excerpt": "No proposed answer or hook is discussed.",
                "query": "unrelated",
            }
        ]

        with patch("daily_quiz.configured_question_evidence", return_value=unsupported):
            result = daily_quiz.generate_slot(
                self.conn,
                quiz_set_id=target["id"],
                quiz_date="2026-08-20",
                subject="football",
                difficulty="easy",
                provider=provider,
                config=pipeline_config,
                log=lambda _: None,
            )

        self.assertIsNone(result)
        self.assertEqual(provider.composition_calls, 0)
        self.assertEqual(provider.critic_calls, 0)

    def test_candidate_pipeline_rejects_final_question_from_180_day_history(self) -> None:
        old_set = daily_quiz.get_or_create_quiz_set(self.conn, "2026-04-20")
        old_question = valid_question("football", "easy")
        daily_quiz.save_question(
            self.conn,
            quiz_set_id=old_set["id"],
            question=old_question,
            evidence=supporting_evidence(old_question),
            verification=passing_verification(supporting_evidence(old_question)),
        )
        daily_quiz.set_quiz_status(self.conn, "2026-04-20", "published")
        target = daily_quiz.get_or_create_quiz_set(self.conn, "2026-08-20")
        provider = CandidateProvider()
        pipeline_config = replace(
            config(),
            candidate_pipeline_enabled=True,
            candidate_batch_size=2,
            candidate_batches_per_slot=1,
            question_similarity_days=180,
        )

        result = daily_quiz.generate_slot(
            self.conn,
            quiz_set_id=target["id"],
            quiz_date="2026-08-20",
            subject="football",
            difficulty="easy",
            provider=provider,
            config=pipeline_config,
            log=lambda _: None,
        )

        self.assertIsNone(result)
        rejected = self.conn.execute(
            """
            SELECT COUNT(*) FROM daily_quiz_candidates
            WHERE rejection_stage='composition'
              AND failure_reason LIKE '%180-day history%'
            """
        ).fetchone()[0]
        self.assertEqual(rejected, 1)

    def test_candidate_pipeline_rotates_provider_after_bad_batch(self) -> None:
        target = daily_quiz.get_or_create_quiz_set(self.conn, "2026-08-20")
        first = CandidateProvider("first", invalid_first_batch=True)
        second = CandidateProvider("second")
        chain = daily_quiz.FallbackQuizProvider([first, second])
        pipeline_config = replace(
            config(),
            candidate_pipeline_enabled=True,
            candidate_batch_size=2,
            candidate_batches_per_slot=2,
        )

        result = daily_quiz.generate_slot(
            self.conn,
            quiz_set_id=target["id"],
            quiz_date="2026-08-20",
            subject="general_knowledge",
            difficulty="easy",
            provider=chain,
            config=pipeline_config,
            log=lambda _: None,
        )

        self.assertTrue(result)
        self.assertEqual(first.discovery_calls, 1)
        self.assertEqual(second.discovery_calls, 1)
        self.assertEqual(second.composition_calls, 1)

    def test_candidate_pipeline_remembers_rejected_candidates_across_retries(self) -> None:
        target = daily_quiz.get_or_create_quiz_set(self.conn, "2026-08-20")
        provider = CandidateProvider()
        pipeline_config = replace(
            config(),
            candidate_pipeline_enabled=True,
            candidate_batch_size=2,
            candidate_batches_per_slot=1,
        )
        unsupported = [
            {
                "title": "Unrelated source",
                "source_name": "example.edu",
                "source_url": "https://example.edu/unrelated",
                "tier": "primary",
                "snippet": "No candidate is discussed here.",
                "excerpt": "This is intentionally unrelated.",
                "query": "unrelated",
            }
        ]
        with patch(
            "daily_quiz.configured_question_evidence", return_value=unsupported
        ) as evidence_search:
            first = daily_quiz.generate_slot(
                self.conn,
                quiz_set_id=target["id"],
                quiz_date="2026-08-20",
                subject="football",
                difficulty="easy",
                provider=provider,
                config=pipeline_config,
                log=lambda _: None,
            )
            provider.discovery_calls = 0
            second = daily_quiz.generate_slot(
                self.conn,
                quiz_set_id=target["id"],
                quiz_date="2026-08-20",
                subject="football",
                difficulty="easy",
                provider=provider,
                config=pipeline_config,
                log=lambda _: None,
            )

        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(evidence_search.call_count, 1)
        remembered = self.conn.execute(
            """
            SELECT COUNT(*) FROM daily_quiz_candidates
            WHERE rejection_stage='local'
              AND failure_reason LIKE '%already failed during this generation run%'
            """
        ).fetchone()[0]
        self.assertEqual(remembered, 2)

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

    def test_validator_allows_stable_today_wording(self) -> None:
        question = valid_question(difficulty="hard")
        question["question"] = (
            "Which ancient wonder of the world is the only one still largely intact and standing today?"
        )

        result = daily_quiz.validate_question(
            question,
            expected_subject="general_knowledge",
            expected_difficulty="hard",
        )

        self.assertTrue(result.passed)

    def test_validator_rejects_explicit_current_fact_language(self) -> None:
        question = valid_question()
        question["question"] = "Which football manager is currently top of the league this season?"

        result = daily_quiz.validate_question(question)

        self.assertFalse(result.passed)
        self.assertIn("volatile current fact", result.reason)

    def test_validator_rejects_live_ranking_language(self) -> None:
        question = valid_question(subject="football")
        question["question"] = (
            "Which national team consistently ranks among Europe's top-performing teams?"
        )

        result = daily_quiz.validate_question(question)

        self.assertFalse(result.passed)
        self.assertIn("volatile current fact", result.reason)

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

    def test_repetition_rejects_recent_answer_in_same_slot(self) -> None:
        question = {
            **valid_question(subject="football", difficulty="easy"),
            "question": (
                "The term \"hat-trick\" is famously used in football when a player scores "
                "three goals in a single match. From which other sport did this popular "
                "phrase originally derive?"
            ),
            "correct_answer": "Cricket",
            "tags": ["hat-trick", "cricket"],
        }
        previous = [
            {
                **valid_question(subject="football", difficulty="easy"),
                "question": (
                    "The football term \"hat-trick\" originated from a tradition in which "
                    "sport, where a player who achieved three of a kind was awarded a hat?"
                ),
                "correct_answer": "Cricket",
                "tags": ["hat-trick", "cricket"],
            }
        ]

        result = daily_quiz.check_repetition(question, previous)

        self.assertFalse(result.passed)
        self.assertIn("quiz subject", result.reason)

    def test_repetition_rejects_recent_answer_at_different_difficulty(self) -> None:
        question = {
            **valid_question(subject="football", difficulty="easy"),
            "correct_answer": "Australia",
        }
        previous = [
            {
                **valid_question(subject="football", difficulty="medium"),
                "correct_answer": "Australia",
            }
        ]

        result = daily_quiz.check_repetition(question, previous)

        self.assertFalse(result.passed)
        self.assertIn("quiz subject", result.reason)

    def test_repetition_rejects_answer_with_generic_qualifier_removed(self) -> None:
        question = {
            **valid_question(subject="football", difficulty="easy"),
            "question": "Which national venue is marked by a sweeping roof arch?",
            "correct_answer": "Wembley",
        }
        previous = [
            {
                **valid_question(subject="football", difficulty="easy"),
                "question": "At which stadium did England win the 1966 World Cup final?",
                "correct_answer": "Wembley Stadium",
            }
        ]

        result = daily_quiz.check_repetition(question, previous)

        self.assertFalse(result.passed)
        self.assertIn("quiz subject", result.reason)

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

    def test_repetition_ignores_broad_topic_tags(self) -> None:
        question = valid_question(difficulty="hard")
        question["tags"] = ["history", "landmarks"]
        previous = [
            {
                "question": f"Which documented event is associated with archive entry {index}?",
                "correct_answer": f"Archive answer {index}",
                "tags": ["history"],
            }
            for index in range(6)
        ]

        result = daily_quiz.check_repetition(question, previous)

        self.assertTrue(result.passed)

    def test_repetition_ignores_broad_football_topic_tags(self) -> None:
        question = valid_question(subject="football", difficulty="easy")
        question["tags"] = ["world cup", "premier league", "legends"]
        previous = [
            {
                "question": f"Which football clue is associated with archive entry {index}?",
                "correct_answer": f"Football answer {index}",
                "tags": ["world cup", "premier league", "legends"],
            }
            for index in range(8)
        ]

        result = daily_quiz.check_repetition(question, previous)

        self.assertTrue(result.passed)

    def test_repetition_rejects_specific_overused_topic_tags(self) -> None:
        question = valid_question(difficulty="hard")
        question["tags"] = ["mesopotamia", "history"]
        previous = [
            {
                "question": f"Which ruler is associated with Mesopotamian record {index}?",
                "correct_answer": f"Different answer {index}",
                "tags": ["mesopotamia"],
            }
            for index in range(5)
        ]

        result = daily_quiz.check_repetition(question, previous)

        self.assertFalse(result.passed)
        self.assertIn("mesopotamia", result.reason.lower())

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
        self.assertEqual(status["verified_questions"], 6)
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
        stored = self.conn.execute(
            "SELECT evidence_json, verification_json FROM daily_quiz_questions LIMIT 1"
        ).fetchone()
        self.assertEqual(len(json.loads(stored["evidence_json"])), 2)
        self.assertTrue(json.loads(stored["verification_json"])["passed"])

    def test_generation_keeps_quiz_generating_after_retry_limit(self) -> None:
        result = daily_quiz.generate_daily_quiz(
            self.conn,
            quiz_date="2026-06-03",
            config=config(max_attempts=2),
            provider=AlwaysInvalidProvider(),
            log=lambda _: None,
        )

        self.assertEqual(result["status"], "generating")
        self.assertEqual(result["accepted_questions"], 0)
        self.assertEqual(result["failed_attempts"], 2)
        with self.assertRaises(LookupError):
            daily_quiz.quiz_payload(self.conn, "2026-06-03")

    def test_generation_reuses_prior_feedback_on_later_retry_cycles(self) -> None:
        provider = FeedbackReuseProvider()

        first = daily_quiz.generate_daily_quiz(
            self.conn,
            quiz_date="2026-06-07",
            config=config(max_attempts=1),
            provider=provider,
            log=lambda _: None,
        )
        second = daily_quiz.generate_daily_quiz(
            self.conn,
            quiz_date="2026-06-07",
            config=config(max_attempts=1),
            provider=provider,
            log=lambda _: None,
        )

        self.assertEqual(first["status"], "generating")
        self.assertEqual(first["accepted_questions"], 3)
        self.assertEqual(second["status"], "published")
        self.assertEqual(len(provider.feedback_calls), 2)
        self.assertEqual(provider.feedback_calls[0], [])
        self.assertTrue(
            any("Missing required fields" in entry for entry in provider.feedback_calls[1])
        )

    def test_generation_includes_learning_profile_feedback(self) -> None:
        provider = FeedbackReuseProvider()
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "profile.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "feedback_by_slot": {
                            "football/*": [
                                "Avoid arbitrary dated fixture recall.",
                                "Prefer season-level football hooks.",
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            result = daily_quiz.generate_daily_quiz(
                self.conn,
                quiz_date="2026-06-08",
                config=daily_quiz.QuizConfig(
                    **{**config().__dict__, "learning_profile_path": str(profile_path)}
                ),
                provider=provider,
                log=lambda _: None,
            )

        self.assertEqual(result["status"], "published")
        self.assertTrue(provider.feedback_calls)
        self.assertIn("Avoid arbitrary dated fixture recall.", provider.feedback_calls[0])

    def test_generation_keeps_quiz_generating_after_transient_provider_failures(self) -> None:
        result = daily_quiz.generate_daily_quiz(
            self.conn,
            quiz_date="2026-06-03",
            config=config(max_attempts=2),
            provider=AlwaysFailingProvider("gemini", "Gemini request failed with HTTP 429."),
            log=lambda _: None,
        )

        self.assertEqual(result["status"], "generating")
        self.assertEqual(result["accepted_questions"], 0)
        self.assertEqual(result["failed_attempts"], 1)
        self.assertIsNone(result["failure_reason"])
        self.assertTrue(result["last_failure_transient"])

    def test_prior_attempt_feedback_skips_transient_provider_failures(self) -> None:
        daily_quiz.save_attempt(
            self.conn,
            quiz_date="2026-06-03",
            subject="general_knowledge",
            difficulty="easy",
            attempt_number=1,
            provider="gemini",
            generated={"error": "rate limited"},
            critic=None,
            passed=False,
            failure_reason="Generator request failed: Gemini request failed with HTTP 429.",
        )
        daily_quiz.save_attempt(
            self.conn,
            quiz_date="2026-06-03",
            subject="general_knowledge",
            difficulty="easy",
            attempt_number=2,
            provider="gemini",
            generated={"subject": "general_knowledge"},
            critic=None,
            passed=False,
            failure_reason="Missing required fields: question.",
        )

        feedback = daily_quiz.prior_attempt_feedback(
            self.conn,
            quiz_date="2026-06-03",
            subject="general_knowledge",
            difficulty="easy",
        )

        self.assertEqual(feedback, ["Missing required fields: question."])

    def test_transient_evidence_failure_does_not_blacklist_generated_answer(self) -> None:
        question = valid_question(subject="general_knowledge", difficulty="easy")
        daily_quiz.save_attempt(
            self.conn,
            quiz_date="2026-06-03",
            subject="general_knowledge",
            difficulty="easy",
            attempt_number=1,
            provider="openrouter",
            generated=question,
            critic=passing_critic(),
            passed=False,
            failure_reason="OpenRouter evidence search failed with HTTP 500.",
        )

        feedback = daily_quiz.prior_attempt_feedback(
            self.conn,
            quiz_date="2026-06-03",
            subject="general_knowledge",
            difficulty="easy",
        )

        self.assertEqual(feedback, [])

    def test_verifier_format_failure_does_not_blacklist_generated_answer(self) -> None:
        question = valid_question(subject="general_knowledge", difficulty="easy")
        daily_quiz.save_attempt(
            self.conn,
            quiz_date="2026-06-03",
            subject="general_knowledge",
            difficulty="easy",
            attempt_number=1,
            provider="openrouter",
            generated=question,
            critic=passing_critic(),
            passed=False,
            failure_reason=(
                "Evidence verifier request failed: AI response does not contain a JSON object."
            ),
        )

        feedback = daily_quiz.prior_attempt_feedback(
            self.conn,
            quiz_date="2026-06-03",
            subject="general_knowledge",
            difficulty="easy",
        )

        self.assertEqual(feedback, [])

    def test_prior_attempt_feedback_names_rejected_answer(self) -> None:
        daily_quiz.save_attempt(
            self.conn,
            quiz_date="2026-06-03",
            subject="football",
            difficulty="easy",
            attempt_number=1,
            provider="gemini",
            generated={"correct_answer": "Wembley Stadium"},
            critic=None,
            passed=False,
            failure_reason="Correct answer already appeared recently in this quiz slot.",
        )

        feedback = daily_quiz.prior_attempt_feedback(
            self.conn,
            quiz_date="2026-06-03",
            subject="football",
            difficulty="easy",
        )

        self.assertIn(
            "Do not reuse the previously rejected correct answer: Wembley Stadium.",
            feedback,
        )

    def test_generator_prompt_blocks_answers_beyond_question_excerpt(self) -> None:
        recent = [
            {
                "question": f"Question {index}?",
                "correct_answer": f"Answer {index}",
                "tags": ["history"],
            }
            for index in range(40)
        ]

        prompt = daily_quiz.generator_prompt("football", "easy", recent, [])

        self.assertIn('"Answer 39"', prompt)
        self.assertNotIn('"question": "Question 39?"', prompt)

    def test_generator_prompt_blocks_capped_tags_and_keeps_retry_history(self) -> None:
        recent = [
            {
                "question": f"Question {index}?",
                "correct_answer": f"Answer {index}",
                "tags": ["football", "tactics"],
            }
            for index in range(5)
        ]
        feedback = [f"Failure {index}" for index in range(10)]

        prompt = daily_quiz.generator_prompt("football", "medium", recent, feedback)

        self.assertIn('"tactics"', prompt)
        self.assertIn('"Failure 0"', prompt)

    def test_football_critic_receives_medium_difficulty_guidance(self) -> None:
        prompt = daily_quiz.critic_prompt(
            "football",
            "medium",
            valid_question("football", "medium"),
            [],
        )

        self.assertIn("direct recall question", prompt)
        self.assertIn("easy, not medium", prompt)

    def test_prior_attempt_feedback_prefers_newest_failures(self) -> None:
        for index in range(7):
            daily_quiz.save_attempt(
                self.conn,
                quiz_date="2026-06-03",
                subject="football",
                difficulty="medium",
                attempt_number=index + 1,
                provider="gemini",
                generated={"correct_answer": f"Answer {index}"},
                critic=None,
                passed=False,
                failure_reason=f"Failure {index}",
            )

        feedback = daily_quiz.prior_attempt_feedback(
            self.conn,
            quiz_date="2026-06-03",
            subject="football",
            difficulty="medium",
            limit=2,
        )

        self.assertEqual(
            feedback,
            [
                "Do not reuse the previously rejected correct answer: Answer 6.",
                "Failure 6",
            ],
        )

    def test_regenerate_question_uses_fallback_provider_chain(self) -> None:
        quiz_set = daily_quiz.get_or_create_quiz_set(self.conn, "2026-06-04")
        daily_quiz.save_question(
            self.conn,
            quiz_set_id=quiz_set["id"],
            question=valid_question(subject="football", difficulty="easy"),
        )

        with (
            patch("daily_quiz.provider_chain_from_config", return_value=PassingProvider("fallback")) as provider_chain,
            patch(
                "daily_quiz.provider_from_config",
                side_effect=AssertionError("primary-only provider should not be used"),
            ),
        ):
            result = daily_quiz.regenerate_question(
                self.conn,
                quiz_date="2026-06-04",
                subject="football",
                difficulty="easy",
                config=config(),
                log=lambda _: None,
            )

        provider_chain.assert_called_once()
        self.assertEqual(result["accepted_questions"], 1)

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

    def test_generation_defers_when_critic_is_unavailable(self) -> None:
        payload = daily_quiz.generate_daily_quiz(
            self.conn,
            quiz_date="2026-06-06",
            config=config(),
            provider=CriticUnavailableProvider("gemini"),
            log=lambda _: None,
        )

        self.assertEqual(payload["status"], "generating")
        self.assertEqual(payload["accepted_questions"], 0)
        self.assertTrue(payload["last_failure_transient"])
        failed_rows = self.conn.execute(
            "SELECT failure_reason FROM daily_quiz_attempts WHERE quiz_date = ? AND passed = 0",
            ("2026-06-06",),
        ).fetchall()
        self.assertEqual(len(failed_rows), 1)
        self.assertIn("Critic request failed", failed_rows[0]["failure_reason"])

    def test_generation_rejects_invalid_critic_payload(self) -> None:
        payload = daily_quiz.generate_daily_quiz(
            self.conn,
            quiz_date="2026-06-07",
            config=config(max_attempts=1),
            provider=InvalidCriticProvider("invalid-critic"),
            log=lambda _: None,
        )

        self.assertEqual(payload["status"], "generating")
        self.assertEqual(payload["accepted_questions"], 0)
        self.assertFalse(payload["last_failure_transient"])
        self.assertIn("Critic payload invalid", payload["last_failure_reason"])

    def test_generation_defers_when_evidence_search_is_unavailable(self) -> None:
        with patch(
            "daily_quiz.collect_question_evidence",
            side_effect=daily_quiz.EvidenceSearchUnavailable(
                "Evidence search unavailable: DNS lookup failed"
            ),
        ):
            payload = daily_quiz.generate_daily_quiz(
                self.conn,
                quiz_date="2026-06-09",
                config=config(),
                provider=PassingProvider("gemini"),
                log=lambda _: None,
            )

        self.assertEqual(payload["status"], "generating")
        self.assertEqual(payload["accepted_questions"], 0)
        self.assertTrue(payload["last_failure_transient"])
        self.assertIn("Evidence search unavailable", payload["last_failure_reason"])

    def test_generation_uses_wikipedia_when_openrouter_search_is_capped(self) -> None:
        evidence_config = daily_quiz.QuizConfig(
            **{
                **config().__dict__,
                "evidence_openrouter_api_key": "openrouter-key",
                "evidence_openrouter_base_url": "https://openrouter.ai/api/v1",
                "evidence_openrouter_model": "openrouter/free",
            }
        )
        with (
            patch(
                "daily_quiz.collect_openrouter_question_evidence",
                side_effect=daily_quiz.EvidenceSearchUnavailable(
                    "OpenRouter evidence search failed with HTTP 429"
                ),
            ) as openrouter_search,
            patch(
                "daily_quiz.collect_wikipedia_question_evidence",
                side_effect=supporting_evidence,
            ) as wikipedia_search,
        ):
            payload = daily_quiz.generate_daily_quiz(
                self.conn,
                quiz_date="2026-06-09",
                config=evidence_config,
                provider=PassingProvider("gemini"),
                log=lambda _: None,
            )

        self.assertEqual(payload["status"], "published")
        self.assertEqual(len(payload["questions"]), 6)
        self.assertEqual(
            daily_quiz.quiz_status(self.conn, "2026-06-09")["verified_questions"],
            6,
        )
        self.assertEqual(openrouter_search.call_count, 6)
        self.assertEqual(wikipedia_search.call_count, 6)

    def test_generation_supplements_incomplete_openrouter_evidence(self) -> None:
        evidence_config = daily_quiz.QuizConfig(
            **{
                **config().__dict__,
                "evidence_openrouter_api_key": "openrouter-key",
                "evidence_openrouter_base_url": "https://openrouter.ai/api/v1",
                "evidence_openrouter_model": "openrouter/free",
            }
        )
        with (
            patch("daily_quiz.collect_openrouter_question_evidence", return_value=[]),
            patch(
                "daily_quiz.collect_wikipedia_question_evidence",
                side_effect=supporting_evidence,
            ) as wikipedia_search,
        ):
            payload = daily_quiz.generate_daily_quiz(
                self.conn,
                quiz_date="2026-06-09",
                config=evidence_config,
                provider=PassingProvider("gemini"),
                log=lambda _: None,
            )

        self.assertEqual(payload["status"], "published")
        self.assertEqual(len(payload["questions"]), 6)
        self.assertEqual(wikipedia_search.call_count, 6)

    def test_capped_openrouter_supplements_incomplete_wikipedia_with_bing(self) -> None:
        evidence_config = daily_quiz.QuizConfig(
            **{
                **config().__dict__,
                "evidence_openrouter_api_key": "openrouter-key",
                "evidence_openrouter_base_url": "https://openrouter.ai/api/v1",
                "evidence_openrouter_model": "openrouter/free",
            }
        )
        question = valid_question()
        wikipedia_evidence = supporting_evidence(question)[:1]
        bing_evidence = [
            {
                **wikipedia_evidence[0],
                "source_name": "Independent source",
                "source_url": "https://example.org/independent-source",
                "tier": "reputable",
            }
        ]
        with (
            patch(
                "daily_quiz.collect_openrouter_question_evidence",
                side_effect=daily_quiz.EvidenceSearchUnavailable(
                    "OpenRouter evidence search failed with HTTP 429"
                ),
            ),
            patch(
                "daily_quiz.collect_wikipedia_question_evidence",
                return_value=wikipedia_evidence,
            ),
            patch("daily_quiz.precheck_question_evidence", return_value={"passed": False}),
            patch(
                "daily_quiz.collect_question_evidence",
                return_value=bing_evidence,
            ) as bing_search,
        ):
            evidence = daily_quiz.configured_question_evidence(
                question,
                config=evidence_config,
            )

        self.assertEqual(len(evidence), 2)
        self.assertEqual(bing_search.call_count, 1)

    def test_evidence_supplement_merges_longer_excerpt_for_duplicate_url(self) -> None:
        evidence_config = daily_quiz.QuizConfig(
            **{
                **config().__dict__,
                "evidence_openrouter_api_key": "openrouter-key",
                "evidence_openrouter_base_url": "https://openrouter.ai/api/v1",
                "evidence_openrouter_model": "openrouter/free",
            }
        )
        question = {
            "question": "Which national team changed confederations in 2006?",
            "correct_answer": "Australia",
            "explanation": "Australia joined the AFC in 2006.",
            "interesting_reason": (
                "Australia won in 2015, becoming the only team to win two "
                "confederation cups."
            ),
        }
        shared_url = "https://en.wikipedia.org/wiki/Australia_national_team"
        openrouter_evidence = [
            {
                "title": "Australia national team",
                "source_name": "Wikipedia",
                "source_url": shared_url,
                "tier": "reference",
                "snippet": "Australia joined the AFC in 2006.",
                "excerpt": "Australia joined the AFC in 2006.",
                "query": "Australia 2006",
            }
        ]
        wikipedia_evidence = [
            {
                **openrouter_evidence[0],
                "excerpt": (
                    "Australia joined the AFC in 2006 and won in 2015, becoming the "
                    "only team to win two confederation cups."
                ),
            },
            {
                **openrouter_evidence[0],
                "source_name": "The Guardian",
                "source_url": "https://www.theguardian.com/football/australia-2015",
                "tier": "reputable",
                "snippet": "Australia won the Asian Cup in 2015.",
                "excerpt": "Australia won the Asian Cup in 2015.",
            },
        ]
        with (
            patch(
                "daily_quiz.collect_openrouter_question_evidence",
                return_value=openrouter_evidence,
            ),
            patch(
                "daily_quiz.collect_wikipedia_question_evidence",
                return_value=wikipedia_evidence,
            ),
        ):
            evidence = daily_quiz.configured_question_evidence(
                question,
                config=evidence_config,
            )

        self.assertEqual(len(evidence), 2)
        self.assertIn("won in 2015", evidence[0]["excerpt"])

    def test_generation_rejects_question_with_no_supporting_evidence(self) -> None:
        with patch("daily_quiz.collect_question_evidence", return_value=[]):
            payload = daily_quiz.generate_daily_quiz(
                self.conn,
                quiz_date="2026-06-10",
                config=config(max_attempts=1),
                provider=PassingProvider("gemini"),
                log=lambda _: None,
            )

        self.assertEqual(payload["status"], "generating")
        self.assertEqual(payload["accepted_questions"], 0)
        self.assertFalse(payload["last_failure_transient"])
        self.assertIn("no usable sources", payload["last_failure_reason"])
        attempt = daily_quiz.question_attempts(self.conn, "2026-06-10")["attempts"][0]
        self.assertEqual(attempt["evidence"], [])
        self.assertFalse(attempt["verification"]["passed"])

    def test_generation_defers_when_evidence_verifier_is_unavailable(self) -> None:
        payload = daily_quiz.generate_daily_quiz(
            self.conn,
            quiz_date="2026-06-11",
            config=config(),
            provider=VerifierUnavailableProvider("gemini"),
            log=lambda _: None,
        )

        self.assertEqual(payload["status"], "generating")
        self.assertEqual(payload["accepted_questions"], 0)
        self.assertTrue(payload["last_failure_transient"])
        self.assertIn("Evidence verifier request failed", payload["last_failure_reason"])

    def test_generation_rejects_invalid_evidence_verifier_payload(self) -> None:
        payload = daily_quiz.generate_daily_quiz(
            self.conn,
            quiz_date="2026-06-12",
            config=config(max_attempts=1),
            provider=InvalidVerifierProvider("invalid-verifier"),
            log=lambda _: None,
        )

        self.assertEqual(payload["status"], "generating")
        self.assertEqual(payload["accepted_questions"], 0)
        self.assertFalse(payload["last_failure_transient"])
        self.assertIn("Evidence verifier payload invalid", payload["last_failure_reason"])

    def test_manual_publish_rejects_unverified_questions(self) -> None:
        quiz_set = daily_quiz.get_or_create_quiz_set(self.conn, "2026-06-13")
        for subject in daily_quiz.SUBJECTS:
            for difficulty in daily_quiz.DIFFICULTIES:
                daily_quiz.save_question(
                    self.conn,
                    quiz_set_id=quiz_set["id"],
                    question=valid_question(subject, difficulty),
                )

        with self.assertRaisesRegex(ValueError, "evidence verification"):
            daily_quiz.publish_quiz(self.conn, "2026-06-13")

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

    def test_hard_football_prompts_reject_inferred_statistical_superlatives(self) -> None:
        generator = daily_quiz.generator_prompt("football", "hard", [], [])
        critic = daily_quiz.critic_prompt("football", "hard", valid_question("football", "hard"), [])

        for prompt in (generator, critic):
            self.assertIn("do not manufacture a statistical superlative", prompt)
            self.assertIn("cross-era format changes", prompt)

    def test_openai_compatible_provider_keeps_http_error_details(self) -> None:
        provider = daily_quiz.OpenAICompatibleProvider(
            daily_quiz.QuizConfig(
                **{
                    **config().__dict__,
                    "provider": "openai-compatible",
                    "generator_model": "gpt-test",
                    "critic_model": "gpt-test",
                    "compatible_api_key": "test-key",
                    "compatible_base_url": "https://api.openai.com/v1",
                }
            )
        )
        error = HTTPError(
            "https://api.openai.com/v1/chat/completions",
            429,
            "Too Many Requests",
            hdrs=None,
            fp=BytesIO(
                json.dumps(
                    {
                        "error": {
                            "code": "insufficient_quota",
                            "message": "You exceeded your current quota.",
                        }
                    }
                ).encode("utf-8")
            ),
        )

        detail = provider._http_error_detail(error)

        self.assertIn("insufficient_quota", detail)
        self.assertIn("current quota", detail)

    def test_openrouter_retries_invalid_json_with_response_healing_enabled(self) -> None:
        class FakeResponse:
            def __init__(self, content: str) -> None:
                self.content = content

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    {"choices": [{"message": {"content": self.content}}]}
                ).encode("utf-8")

        provider = daily_quiz.OpenAICompatibleProvider(
            daily_quiz.QuizConfig(
                **{
                    **config().__dict__,
                    "provider": "openrouter",
                    "generator_model": "openrouter/free",
                    "critic_model": "openrouter/free",
                    "compatible_api_key": "test-key",
                    "compatible_base_url": "https://openrouter.ai/api/v1",
                    "transient_retries": 1,
                    "request_delay_sec": 0,
                }
            )
        )
        with (
            patch(
                "daily_quiz.urlopen",
                side_effect=[FakeResponse('{"passed": true'), FakeResponse('{"passed": true}')],
            ) as request,
            patch.object(provider, "_defer_retry") as retry,
        ):
            payload = provider._request("openrouter/free", "Return a decision.")

        self.assertEqual(payload, {"passed": True})
        self.assertEqual(request.call_count, 2)
        retry.assert_called_once_with(0)
        request_payload = json.loads(request.call_args_list[0].args[0].data.decode("utf-8"))
        self.assertEqual(request_payload["plugins"], [{"id": "response-healing"}])
        self.assertTrue(daily_quiz.is_transient_provider_failure("Provider returned invalid JSON."))

    def test_gemini_provider_keeps_http_error_details(self) -> None:
        provider = daily_quiz.GeminiProvider(config())
        error = HTTPError(
            "https://generativelanguage.googleapis.com/v1beta/models/test:generateContent",
            429,
            "Too Many Requests",
            hdrs=None,
            fp=BytesIO(
                json.dumps(
                    {
                        "error": {
                            "code": 429,
                            "status": "RESOURCE_EXHAUSTED",
                            "message": "Quota exceeded for quota metric.",
                        }
                    }
                ).encode("utf-8")
            ),
        )

        detail = provider._http_error_detail(error)

        self.assertIn("RESOURCE_EXHAUSTED", detail)
        self.assertIn("Quota exceeded", detail)

    def test_gemini_provider_retries_network_timeout(self) -> None:
        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    {
                        "candidates": [
                            {"content": {"parts": [{"text": '{"passed": true}'}]}}
                        ]
                    }
                ).encode("utf-8")

        provider = daily_quiz.GeminiProvider(
            daily_quiz.QuizConfig(
                **{
                    **config().__dict__,
                    "transient_retries": 1,
                    "request_delay_sec": 0,
                }
            )
        )
        with (
            patch("daily_quiz.urlopen", side_effect=[TimeoutError("read timed out"), FakeResponse()]) as request,
            patch.object(provider, "_defer_transient_retry") as retry,
        ):
            payload = provider._request("test-model", "Return a decision.", {})

        self.assertEqual(payload, {"passed": True})
        self.assertEqual(request.call_count, 2)
        retry.assert_called_once_with(0)

    def test_provider_chain_reuses_primary_gemini_key_for_gemini_fallback(self) -> None:
        chain = daily_quiz.provider_chain_from_config(
            daily_quiz.QuizConfig(
                **{
                    **config().__dict__,
                    "fallback_provider": "gemini",
                    "fallback_generator_model": "gemini-2.5-flash",
                    "fallback_critic_model": "gemini-2.5-flash-lite",
                    "fallback2_provider": "gemini",
                    "fallback2_generator_model": "gemini-2.0-flash",
                    "fallback2_critic_model": "gemini-2.0-flash-lite",
                }
            )
        )

        self.assertIsInstance(chain, daily_quiz.FallbackQuizProvider)
        self.assertEqual([provider.name for provider in chain.providers], ["gemini", "gemini", "gemini"])
        self.assertEqual(
            [provider.config.generator_model for provider in chain.providers],
            ["test-generator", "gemini-2.5-flash", "gemini-2.0-flash"],
        )
        self.assertTrue(all(provider.config.gemini_api_key == "test-key" for provider in chain.providers))

    def test_provider_chain_from_config_includes_second_fallback(self) -> None:
        chain = daily_quiz.provider_chain_from_config(
            daily_quiz.QuizConfig(
                **{
                    **config().__dict__,
                    "fallback_provider": "openrouter",
                    "fallback_generator_model": "google/gemini-2.5-flash",
                    "fallback_critic_model": "google/gemini-2.5-flash",
                    "fallback_compatible_api_key": "or-key",
                    "fallback_compatible_base_url": "https://openrouter.ai/api/v1",
                    "fallback2_provider": "openrouter",
                    "fallback2_generator_model": "openrouter/free",
                    "fallback2_critic_model": "openrouter/free",
                    "fallback2_compatible_api_key": "or-key",
                    "fallback2_compatible_base_url": "https://openrouter.ai/api/v1",
                }
            )
        )

        self.assertIsInstance(chain, daily_quiz.FallbackQuizProvider)
        self.assertEqual(
            [provider.name for provider in chain.providers],
            ["gemini", "openrouter", "openrouter"],
        )

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
