from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
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
        self.discovery_feedback_calls: list[list[str]] = []
        self.composition_calls = 0
        self.critic_calls = 0

    def discover_candidates(
        self,
        *,
        subject: str,
        difficulty: str,
        topic_lane: str,
        batch_size: int,
        feedback: list[str],
        **_: object,
    ) -> dict[str, object]:
        self.discovery_calls += 1
        self.discovery_feedback_calls.append(list(feedback))
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


class DiscoveryUnavailableCandidateProvider(CandidateProvider):
    def discover_candidates(self, **_: object) -> dict[str, object]:
        self.discovery_calls += 1
        raise RuntimeError("Gemini request failed with HTTP 429.")


class VerifierUnavailableCandidateProvider(CandidateProvider):
    def __init__(self, name: str = "verifier-unavailable") -> None:
        super().__init__(name)
        self.verifier_calls = 0

    def verify_question(self, **_: object) -> dict[str, object]:
        self.verifier_calls += 1
        raise RuntimeError("Gemini request failed with HTTP 429.")


class RejectingCriticCandidateProvider(CandidateProvider):
    def critique_question(self, **kwargs: object) -> dict[str, object]:
        critic = super().critique_question(**kwargs)
        critic["passed"] = False
        critic["scores"] = {**critic["scores"], "difficulty_match": 4}
        critic["failure_reasons"] = ["The candidate is too easy for hard difficulty."]
        critic["feedback_to_generator"] = "Use a less obvious documented connection."
        return critic


class VariedCandidateProvider(CandidateProvider):
    def discover_candidates(
        self,
        *,
        subject: str,
        difficulty: str,
        topic_lane: str,
        batch_size: int,
        feedback: list[str],
        **_: object,
    ) -> dict[str, object]:
        self.discovery_calls += 1
        self.discovery_feedback_calls.append(list(feedback))
        hooks = (
            "A documented stadium ceremony linked {answer} to an unusual public milestone.",
            "Archived tactical reports credit {answer} with a formation that changed later coaching.",
            "A competition incident involving {answer} led administrators to rewrite a formal rule.",
        )
        return {
            "candidates": [
                {
                    "answer": f"Distinct Answer {index}",
                    "hook": hooks[index].format(answer=f"Distinct Answer {index}"),
                    "topic_lane": topic_lane,
                    "era": "twentieth century",
                    "region": "Europe",
                    "tags": [topic_lane, f"distinct-event-{index}"],
                    "evidence_query": f"Distinct Answer {index} documented event",
                }
                for index in range(batch_size)
            ]
        }


class DailyQuizTests(unittest.TestCase):
    def test_quiz_diagnostic_retention_prunes_age_and_row_overflow_only(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        daily_quiz.initialize_database(conn)
        conn.execute(
            "INSERT INTO daily_quiz_sets (quiz_date, status) VALUES (?, 'published')",
            ("2026-08-15",),
        )
        quiz_set_id = int(
            conn.execute(
                "SELECT id FROM daily_quiz_sets WHERE quiz_date = ?",
                ("2026-08-15",),
            ).fetchone()[0]
        )
        now = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)
        created_values = [
            now - timedelta(days=60),
            now - timedelta(days=3),
            now - timedelta(days=2),
            now - timedelta(days=1),
        ]
        for index, created_at in enumerate(created_values, start=1):
            created = created_at.isoformat()
            conn.execute(
                """
                INSERT INTO daily_quiz_attempts (
                    quiz_date, subject, difficulty, attempt_number, provider,
                    generated_json, passed, created_at
                ) VALUES (?, 'football', 'easy', ?, 'test', '{}', 0, ?)
                """,
                ("2026-08-15", index, created),
            )
            conn.execute(
                """
                INSERT INTO daily_quiz_candidates (
                    quiz_set_id, quiz_date, subject, difficulty, batch_number,
                    candidate_index, provider, answer, normalized_answer, hook,
                    normalized_hook, topic_lane, status, created_at, updated_at
                ) VALUES (
                    ?, ?, 'football', 'easy', ?, 1, 'test', ?, ?, ?, ?,
                    'history', 'rejected', ?, ?
                )
                """,
                (
                    quiz_set_id,
                    "2026-08-15",
                    index,
                    f"Answer {index}",
                    f"answer {index}",
                    f"Hook {index}",
                    f"hook {index}",
                    created,
                    created,
                ),
            )

        daily_quiz.prune_quiz_diagnostics(
            conn,
            now=now,
            retention_days=30,
            max_rows=2,
        )

        attempt_numbers = [
            int(row[0])
            for row in conn.execute(
                "SELECT attempt_number FROM daily_quiz_attempts ORDER BY attempt_number"
            )
        ]
        candidate_batches = [
            int(row[0])
            for row in conn.execute(
                "SELECT batch_number FROM daily_quiz_candidates ORDER BY batch_number"
            )
        ]
        self.assertEqual(attempt_numbers, [3, 4])
        self.assertEqual(candidate_batches, [3, 4])
        self.assertEqual(
            conn.execute(
                "SELECT status FROM daily_quiz_sets WHERE id = ?", (quiz_set_id,)
            ).fetchone()[0],
            "published",
        )
        conn.close()

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

    def test_generation_marks_current_round_separately_from_history(self) -> None:
        historical_set = daily_quiz.get_or_create_quiz_set(self.conn, "2026-08-19")
        current_set = daily_quiz.get_or_create_quiz_set(self.conn, "2026-08-20")
        daily_quiz.save_question(
            self.conn,
            quiz_set_id=historical_set["id"],
            question=valid_question("football", "hard"),
            evidence=supporting_evidence(valid_question("football", "hard")),
            verification=passing_verification([]),
        )
        self.conn.execute(
            "UPDATE daily_quiz_sets SET status = 'published' WHERE id = ?",
            (historical_set["id"],),
        )
        daily_quiz.save_question(
            self.conn,
            quiz_set_id=current_set["id"],
            question=valid_question("football", "easy"),
            evidence=supporting_evidence(valid_question("football", "easy")),
            verification=passing_verification([]),
        )
        daily_quiz.save_attempt(
            self.conn,
            quiz_date="2026-08-20",
            subject="football",
            difficulty="medium",
            attempt_number=1,
            provider="fixture",
            generated={"correct_answer": "Previously Rejected FC"},
            critic=None,
            passed=False,
            failure_reason="Correct answer already appeared recently in this quiz subject.",
        )

        class ContextCapturingProvider(PassingProvider):
            def __init__(self) -> None:
                super().__init__("context-capturing")
                self.contexts: list[list[dict[str, object]]] = []

            def generate_question(self, **kwargs: object) -> dict[str, object]:
                self.contexts.append(list(kwargs["recent_questions"]))
                return valid_question(
                    str(kwargs["subject"]), str(kwargs["difficulty"])
                )

        provider = ContextCapturingProvider()
        result = daily_quiz.generate_slot(
            self.conn,
            quiz_set_id=current_set["id"],
            quiz_date="2026-08-20",
            subject="football",
            difficulty="medium",
            provider=provider,
            config=config(),
            log=lambda _: None,
        )

        self.assertTrue(result)
        self.assertEqual(len(provider.contexts), 1)
        by_difficulty = {
            str(question["difficulty"]): question for question in provider.contexts[0]
        }
        self.assertEqual(by_difficulty["easy"]["context_scope"], "current_round")
        self.assertEqual(by_difficulty["hard"]["context_scope"], "history")
        self.assertEqual(by_difficulty["easy"]["subject"], "football")
        rejected = [
            question
            for question in provider.contexts[0]
            if question["context_scope"] == "rejected_attempt"
        ]
        self.assertEqual(
            [question["correct_answer"] for question in rejected],
            ["Previously Rejected FC"],
        )
        self.assertNotIn(
            "Previously Rejected FC",
            json.dumps(daily_quiz.public_recent_questions(provider.contexts[0])),
        )

    def test_config_uses_thirty_call_candidate_ceiling_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            loaded = daily_quiz.QuizConfig.from_env()

        self.assertEqual(loaded.candidate_max_calls_per_quiz, 30)
        self.assertEqual(loaded.max_failed_attempts_per_date, 180)

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

    def test_candidate_evidence_probe_preserves_tailored_search_query(self) -> None:
        candidate = {
            "answer": "Example Answer",
            "hook": "A documented event provides a memorable and uniquely identifying fact.",
            "topic_lane": "world history incidents",
            "era": "twentieth century",
            "region": "Europe",
            "tags": ["documented event", "public milestone"],
            "evidence_query": "Example Answer documented public milestone",
        }

        probe = daily_quiz.candidate_evidence_probe(
            candidate,
            subject="general_knowledge",
            difficulty="medium",
        )

        self.assertEqual(probe["evidence_query"], candidate["evidence_query"])

    def test_candidate_prompt_defines_general_knowledge_difficulty(self) -> None:
        prompt = daily_quiz.candidate_discovery_prompt(
            "general_knowledge",
            "hard",
            "scientific discoveries",
            8,
            [],
            recovery_mode=False,
        )

        self.assertIn("Hard questions should be specialist but fair", prompt)
        self.assertIn("foundational textbook concepts", prompt)
        self.assertIn("reputable source is likely to state explicitly", prompt)

    def test_candidate_feedback_identifies_saturated_topics(self) -> None:
        recent = [
            {"tags": ["European Cup", "football"]}
            for _ in range(5)
        ] + [{"tags": ["stadiums"]}]

        feedback = daily_quiz.saturated_topic_feedback(recent)

        self.assertEqual(len(feedback), 1)
        self.assertIn("european cup", feedback[0])
        self.assertNotIn("stadiums", feedback[0])

    def test_candidate_lane_rotation_skips_a_saturated_lane(self) -> None:
        recent = [{"tags": ["rules"]} for _ in range(5)]

        lane = daily_quiz.choose_topic_lane(
            self.conn,
            subject="football",
            difficulty="medium",
            batch_number=2,
            profile_path="",
            recent_questions_for_topics=recent,
        )

        self.assertNotEqual(lane, "competitions and rules")

    def test_candidate_allows_specific_topic_inside_a_broad_saturated_lane(self) -> None:
        recent = [{"tags": ["rules"]} for _ in range(5)]

        saturated = daily_quiz.candidate_saturated_topic_tag(
            ["rules", "back-pass rule"], recent
        )

        self.assertIsNone(saturated)

    def test_candidate_hook_must_be_a_factual_statement(self) -> None:
        candidate = {
            "answer": "Example Answer",
            "hook": "Which answer was connected to this documented public milestone?",
            "topic_lane": "world history incidents",
            "era": "twentieth century",
            "region": "Europe",
            "tags": ["documented event", "public milestone"],
            "evidence_query": "Example Answer documented public milestone",
        }

        validated, reason = daily_quiz.validate_candidate(
            candidate,
            topic_lane="world history incidents",
        )

        self.assertIsNone(validated)
        self.assertIn("factual statement", reason)

    def test_candidate_pipeline_drains_persisted_batch_before_discovery(self) -> None:
        target = daily_quiz.get_or_create_quiz_set(self.conn, "2026-08-20")
        for index in range(5):
            answer = f"Persisted Answer {index}"
            daily_quiz.insert_candidate(
                self.conn,
                quiz_set_id=target["id"],
                quiz_date="2026-08-20",
                subject="football",
                difficulty="medium",
                batch_number=1,
                candidate_index=index + 1,
                provider="seed",
                generation_mode="normal",
                candidate={
                    "answer": answer,
                    "hook": (
                        f"A distinct documented incident number {index} connects {answer} "
                        "to a memorable competition milestone."
                    ),
                    "topic_lane": "famous incidents and matches",
                    "era": "twentieth century",
                    "region": "Europe",
                    "tags": ["documented incident", f"milestone-{index}"],
                    "evidence_query": f"{answer} documented competition milestone {index}",
                },
                status="eligible",
                score=10 - index,
            )
        provider = CandidateProvider()
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
        evidence_calls = 0

        def evidence_for_probe(
            probe: dict[str, object], *, config: daily_quiz.QuizConfig
        ) -> list[dict[str, str]]:
            nonlocal evidence_calls
            evidence_calls += 1
            if evidence_calls <= 3:
                return unsupported
            return supporting_evidence(probe)

        pipeline_config = replace(
            config(),
            candidate_pipeline_enabled=True,
            candidate_batch_size=8,
            candidate_batches_per_slot=3,
        )
        with patch(
            "daily_quiz.configured_question_evidence", side_effect=evidence_for_probe
        ):
            result = daily_quiz.generate_slot(
                self.conn,
                quiz_set_id=target["id"],
                quiz_date="2026-08-20",
                subject="football",
                difficulty="medium",
                provider=provider,
                config=pipeline_config,
                log=lambda _: None,
            )

        self.assertTrue(result)
        self.assertEqual(provider.discovery_calls, 0)
        self.assertEqual(provider.composition_calls, 1)
        self.assertEqual(evidence_calls, 4)

    def test_candidate_feedback_summarizes_every_rejected_answer_in_run(self) -> None:
        target = daily_quiz.get_or_create_quiz_set(self.conn, "2026-08-20")
        for index in range(12):
            daily_quiz.insert_candidate(
                self.conn,
                quiz_set_id=target["id"],
                quiz_date="2026-08-20",
                subject="football",
                difficulty="hard",
                batch_number=index + 1,
                candidate_index=1,
                provider="test",
                generation_mode="normal",
                candidate={
                    "answer": f"Rejected Answer {index}",
                    "hook": f"Documented rejected hook number {index} for this test run.",
                    "topic_lane": "famous incidents and matches",
                    "era": "",
                    "region": "",
                    "tags": ["test", f"rejected-{index}"],
                    "evidence_query": f"Rejected Answer {index} documented event",
                },
                status="rejected",
                rejection_stage="local",
                failure_reason="Correct answer is inside the answer embargo window.",
            )

        feedback = daily_quiz.recent_candidate_rejection_feedback(
            self.conn,
            quiz_set_id=target["id"],
            subject="football",
            difficulty="hard",
            limit=3,
        )

        self.assertEqual(len(feedback), 3)
        summary = feedback[-1]
        self.assertIn("Rejected Answer 0", summary)
        self.assertIn("Rejected Answer 11", summary)

    def test_candidate_call_budget_stops_new_calls_and_survives_retry(self) -> None:
        target = daily_quiz.get_or_create_quiz_set(self.conn, "2026-08-20")
        provider = CandidateProvider()
        pipeline_config = replace(
            config(),
            candidate_pipeline_enabled=True,
            candidate_batch_size=2,
            candidate_batches_per_slot=2,
            candidate_max_calls_per_quiz=1,
        )
        logs: list[str] = []

        first = daily_quiz.generate_slot(
            self.conn,
            quiz_set_id=target["id"],
            quiz_date="2026-08-20",
            subject="football",
            difficulty="easy",
            provider=provider,
            config=pipeline_config,
            log=logs.append,
        )
        second = daily_quiz.generate_slot(
            self.conn,
            quiz_set_id=target["id"],
            quiz_date="2026-08-20",
            subject="football",
            difficulty="easy",
            provider=provider,
            config=pipeline_config,
            log=logs.append,
        )

        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(provider.discovery_calls, 0)
        self.assertEqual(provider.composition_calls, 0)
        self.assertEqual(
            daily_quiz.candidate_generation_call_count(self.conn, "2026-08-20"),
            0,
        )
        self.assertTrue(any("2 call(s) are required" in entry for entry in logs))

        self.conn.execute(
            "DELETE FROM daily_quiz_candidates WHERE quiz_set_id = ?", (target["id"],)
        )
        self.assertEqual(
            daily_quiz.candidate_generation_call_count(self.conn, "2026-08-20"),
            0,
        )

    def test_candidate_pipeline_can_resume_above_previous_thirty_call_limit(self) -> None:
        target = daily_quiz.get_or_create_quiz_set(self.conn, "2026-08-20")
        for batch_number in range(1, 31):
            daily_quiz.insert_candidate(
                self.conn,
                quiz_set_id=int(target["id"]),
                quiz_date="2026-08-20",
                subject="football",
                difficulty="hard",
                batch_number=batch_number,
                candidate_index=1,
                provider="spent-budget-fixture",
                generation_mode="normal",
                candidate={
                    "answer": f"Spent Answer {batch_number}",
                    "hook": f"Documented spent hook {batch_number} for the resume test.",
                    "topic_lane": "club stories",
                    "era": "",
                    "region": "",
                    "tags": ["spent fixture", f"spent-{batch_number}"],
                    "evidence_query": f"Spent Answer {batch_number} documented event",
                },
                status="rejected",
                rejection_stage="local",
                failure_reason="Rejected fixture.",
            )
        provider = CandidateProvider()
        pipeline_config = replace(
            config(),
            candidate_pipeline_enabled=True,
            candidate_batch_size=2,
            candidate_batches_per_slot=1,
            candidate_max_calls_per_quiz=42,
        )

        result = daily_quiz.generate_slot(
            self.conn,
            quiz_set_id=target["id"],
            quiz_date="2026-08-20",
            subject="football",
            difficulty="hard",
            provider=provider,
            config=pipeline_config,
            log=lambda _: None,
        )

        self.assertTrue(result)
        self.assertEqual(provider.discovery_calls, 1)
        self.assertEqual(provider.composition_calls, 1)
        self.assertEqual(
            daily_quiz.candidate_generation_call_count(self.conn, "2026-08-20"),
            32,
        )

    def test_candidate_pipeline_rejects_recent_hard_football_hook_locally(self) -> None:
        candidate = {
            "answer": "Recent Team",
            "hook": "The national team recorded a widely reported first competitive win in 2024.",
            "topic_lane": "documented records",
            "era": "contemporary",
            "region": "Europe",
            "tags": ["international football", "documented record"],
            "evidence_query": "Recent Team first competitive win 2024",
        }

        reason = daily_quiz.candidate_local_rejection(
            candidate,
            quiz_date="2026-08-20",
            subject="football",
            difficulty="hard",
            accepted_answer_keys=set(),
            current_answer_keys=set(),
            previous_hooks=[],
            failed_answer_keys=set(),
            failed_hooks=[],
            recent_questions_for_topics=[],
        )

        self.assertIn("latest three calendar years", str(reason))

    def test_candidate_pipeline_tries_third_candidate_after_provider_switch(self) -> None:
        target = daily_quiz.get_or_create_quiz_set(self.conn, "2026-08-20")
        composer = VariedCandidateProvider("composer")
        rejecting_critic = RejectingCriticCandidateProvider("rejecting-critic")
        recovered = CandidateProvider("recovered")
        chain = daily_quiz.FallbackQuizProvider([composer, rejecting_critic, recovered])
        pipeline_config = replace(
            config(),
            candidate_pipeline_enabled=True,
            candidate_batch_size=3,
            candidate_batches_per_slot=1,
            candidate_max_calls_per_quiz=6,
        )
        logs: list[str] = []

        result = daily_quiz.generate_slot(
            self.conn,
            quiz_set_id=target["id"],
            quiz_date="2026-08-20",
            subject="football",
            difficulty="hard",
            provider=chain,
            config=pipeline_config,
            log=logs.append,
        )

        self.assertTrue(result, logs)
        self.assertEqual(composer.composition_calls, 2)
        self.assertEqual(rejecting_critic.critic_calls, 2)
        self.assertEqual(rejecting_critic.composition_calls, 1)
        self.assertEqual(recovered.critic_calls, 1)

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
        self.assertTrue(
            any(
                "Blocked Football Answer" in entry
                and "already used recently" in entry
                for entry in provider.discovery_feedback_calls[0]
            ),
            "the first discovery call must know recent answer exclusions",
        )
        self.assertTrue(
            any(
                "Blocked Football Answer" in entry
                for entry in provider.discovery_feedback_calls[1]
            )
        )
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

    def test_candidate_pipeline_rejects_oversized_evidence_candidate(self) -> None:
        target = daily_quiz.get_or_create_quiz_set(self.conn, "2026-08-20")
        provider = DiscoveryUnavailableCandidateProvider("unavailable")
        candidate = {
            "answer": "Oversized Evidence Answer",
            "hook": (
                "A documented incident identifies this answer through a specific "
                "and memorable historical event."
            ),
            "topic_lane": "famous incidents and matches",
            "era": "twentieth century",
            "region": "Europe",
            "tags": ["documented incident", "historical event"],
            "evidence_query": "Oversized Evidence Answer documented incident",
        }
        daily_quiz.insert_candidate(
            self.conn,
            quiz_set_id=target["id"],
            quiz_date="2026-08-20",
            subject="football",
            difficulty="hard",
            batch_number=1,
            candidate_index=1,
            provider="seed",
            generation_mode="normal",
            candidate=candidate,
            status="eligible",
            score=10,
        )
        pipeline_config = replace(
            config(),
            candidate_pipeline_enabled=True,
            candidate_batches_per_slot=1,
        )
        oversized = daily_quiz.EvidenceSearchUnavailable(
            "Wikimedia evidence search failed: "
            "Upstream response exceeds the allowed size."
        )

        with patch(
            "daily_quiz.configured_question_evidence",
            side_effect=oversized,
        ) as evidence_search:
            result = daily_quiz.generate_slot(
                self.conn,
                quiz_set_id=target["id"],
                quiz_date="2026-08-20",
                subject="football",
                difficulty="hard",
                provider=provider,
                config=pipeline_config,
                log=lambda _: None,
            )

        self.assertIsNone(result)
        candidate_row = self.conn.execute(
            """
            SELECT status, rejection_stage, failure_reason
            FROM daily_quiz_candidates WHERE id = (
                SELECT MIN(id) FROM daily_quiz_candidates
            )
            """
        ).fetchone()
        self.assertEqual(candidate_row["status"], "rejected")
        self.assertEqual(candidate_row["rejection_stage"], "evidence")
        self.assertIn("response exceeds the allowed size", candidate_row["failure_reason"])
        self.assertEqual(evidence_search.call_count, 1)

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
        self.assertEqual(provider.composition_calls, 1)
        self.assertEqual(
            daily_quiz.candidate_generation_call_count(self.conn, "2026-08-20"),
            2,
        )
        recorded = self.conn.execute(
            "SELECT COUNT(*) FROM daily_quiz_attempts WHERE candidate_id IS NOT NULL"
        ).fetchone()[0]
        self.assertEqual(recorded, 1)

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

    def test_candidate_pipeline_falls_back_when_discovery_provider_is_unavailable(self) -> None:
        target = daily_quiz.get_or_create_quiz_set(self.conn, "2026-08-20")
        unavailable = DiscoveryUnavailableCandidateProvider("unavailable")
        fallback = CandidateProvider("fallback")
        chain = daily_quiz.FallbackQuizProvider([unavailable, fallback])
        pipeline_config = replace(
            config(),
            candidate_pipeline_enabled=True,
            candidate_batch_size=2,
            candidate_batches_per_slot=1,
        )

        result = daily_quiz.generate_slot(
            self.conn,
            quiz_set_id=target["id"],
            quiz_date="2026-08-20",
            subject="football",
            difficulty="easy",
            provider=chain,
            config=pipeline_config,
            log=lambda _: None,
        )

        self.assertTrue(result)
        self.assertEqual(unavailable.discovery_calls, 1)
        self.assertEqual(fallback.discovery_calls, 1)
        provider = self.conn.execute(
            "SELECT provider FROM daily_quiz_candidates ORDER BY id LIMIT 1"
        ).fetchone()["provider"]
        self.assertEqual(provider, "fallback")

    def test_candidate_pipeline_falls_back_when_verifier_is_unavailable(self) -> None:
        target = daily_quiz.get_or_create_quiz_set(self.conn, "2026-08-20")
        composer = CandidateProvider("composer")
        critic = CandidateProvider("critic")
        unavailable = VerifierUnavailableCandidateProvider()
        chain = daily_quiz.FallbackQuizProvider([composer, critic, unavailable])
        pipeline_config = replace(
            config(),
            candidate_pipeline_enabled=True,
            candidate_batch_size=2,
            candidate_batches_per_slot=1,
        )

        result = daily_quiz.generate_slot(
            self.conn,
            quiz_set_id=target["id"],
            quiz_date="2026-08-20",
            subject="football",
            difficulty="easy",
            provider=chain,
            config=pipeline_config,
            log=lambda _: None,
        )

        self.assertTrue(result)
        self.assertEqual(unavailable.verifier_calls, 1)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM daily_quiz_candidates WHERE status='accepted'"
            ).fetchone()[0],
            1,
        )

    def test_candidate_pipeline_resumes_after_all_verifiers_are_unavailable(self) -> None:
        target = daily_quiz.get_or_create_quiz_set(self.conn, "2026-08-20")
        unavailable = VerifierUnavailableCandidateProvider()
        pipeline_config = replace(
            config(),
            candidate_pipeline_enabled=True,
            candidate_batch_size=2,
            candidate_batches_per_slot=1,
        )

        first = daily_quiz.generate_slot(
            self.conn,
            quiz_set_id=target["id"],
            quiz_date="2026-08-20",
            subject="football",
            difficulty="easy",
            provider=unavailable,
            config=pipeline_config,
            log=lambda _: None,
        )
        resumable = self.conn.execute(
            """
            SELECT status, rejection_stage FROM daily_quiz_candidates
            WHERE status='verified' ORDER BY id LIMIT 1
            """
        ).fetchone()

        fallback = CandidateProvider("recovered")
        second = daily_quiz.generate_slot(
            self.conn,
            quiz_set_id=target["id"],
            quiz_date="2026-08-20",
            subject="football",
            difficulty="easy",
            provider=fallback,
            config=pipeline_config,
            log=lambda _: None,
        )

        self.assertIsNone(first)
        self.assertIsNotNone(resumable)
        self.assertEqual(resumable["rejection_stage"], "transient")
        self.assertTrue(second)
        self.assertEqual(fallback.discovery_calls, 0)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM daily_quiz_candidates WHERE status='accepted'"
            ).fetchone()[0],
            1,
        )

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

    def test_validator_rejects_malformed_text_encoding(self) -> None:
        question = valid_question()
        question["choices"][0] = "Luis Barrag%n"
        question["correct_answer"] = "Luis Barrag%n"

        result = daily_quiz.validate_question(question)

        self.assertFalse(result.passed)
        self.assertIn("malformed text encoding", result.reason)

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
        self.assertNotIn("correct_answer", public_question)
        self.assertNotIn("explanation", public_question)
        self.assertIsInstance(public_question["id"], str)
        self.assertEqual(
            set(public_question["choices"][0]),
            {"id", "text"},
        )
        serialized_payload = json.dumps(payload, sort_keys=True)
        self.assertNotIn('"correct_answer"', serialized_payload)
        self.assertNotIn('"explanation"', serialized_payload)
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

    def test_daily_failure_budget_persists_across_retries_and_force_bypasses_it(self) -> None:
        quiz_date = "2026-06-04"
        budget_config = replace(
            config(max_attempts=3),
            max_failed_attempts_per_date=3,
        )
        for attempt_number in (1, 2):
            daily_quiz.save_attempt(
                self.conn,
                quiz_date=quiz_date,
                subject="general_knowledge",
                difficulty="easy",
                attempt_number=attempt_number,
                provider="seed",
                generated={"invalid": True},
                critic=None,
                passed=False,
                failure_reason="Seeded quality rejection.",
            )

        class CountingInvalidProvider(AlwaysInvalidProvider):
            def __init__(self) -> None:
                self.calls = 0

            def generate_question(self, **kwargs: object) -> dict[str, object]:
                self.calls += 1
                return super().generate_question(**kwargs)

        invalid_provider = CountingInvalidProvider()
        first = daily_quiz.generate_daily_quiz(
            self.conn,
            quiz_date=quiz_date,
            config=budget_config,
            provider=invalid_provider,
            log=lambda _: None,
        )
        second = daily_quiz.generate_daily_quiz(
            self.conn,
            quiz_date=quiz_date,
            config=budget_config,
            provider=invalid_provider,
            log=lambda _: None,
        )

        self.assertEqual(first["status"], "failed")
        self.assertEqual(second["status"], "failed")
        self.assertEqual(first["failed_attempts"], 3)
        self.assertEqual(second["failed_attempts"], 3)
        self.assertIn("persistent daily failure budget", second["failure_reason"])
        self.assertEqual(invalid_provider.calls, 1)

        class CountingPassingProvider(PassingProvider):
            def __init__(self) -> None:
                super().__init__("forced-recovery")
                self.calls = 0

            def generate_question(self, **kwargs: object) -> dict[str, object]:
                self.calls += 1
                return super().generate_question(**kwargs)

        recovery_provider = CountingPassingProvider()
        recovered = daily_quiz.generate_daily_quiz(
            self.conn,
            quiz_date=quiz_date,
            config=budget_config,
            force=True,
            provider=recovery_provider,
            log=lambda _: None,
        )

        self.assertEqual(recovered["status"], "published")
        self.assertEqual(recovery_provider.calls, 6)

    def test_force_regeneration_failure_preserves_published_quiz(self) -> None:
        quiz_date = "2026-06-13"
        quiz_set = daily_quiz.get_or_create_quiz_set(self.conn, quiz_date)
        for subject, difficulty in daily_quiz.REQUIRED_SLOTS:
            daily_quiz.save_question(
                self.conn,
                quiz_set_id=int(quiz_set["id"]),
                question=valid_question(subject, difficulty),
            )
        daily_quiz.set_quiz_status(self.conn, quiz_date, "published")
        before = self.conn.execute(
            """
            SELECT id, subject, difficulty, question, correct_answer
            FROM daily_quiz_questions WHERE quiz_set_id = ? ORDER BY id
            """,
            (quiz_set["id"],),
        ).fetchall()

        result = daily_quiz.generate_daily_quiz(
            self.conn,
            quiz_date=quiz_date,
            config=config(max_attempts=1),
            force=True,
            provider=AlwaysInvalidProvider(),
            log=lambda _: None,
        )
        after = self.conn.execute(
            """
            SELECT id, subject, difficulty, question, correct_answer
            FROM daily_quiz_questions WHERE quiz_set_id = ? ORDER BY id
            """,
            (quiz_set["id"],),
        ).fetchall()

        self.assertEqual(result["status"], "published")
        self.assertTrue(result["regeneration_failed"])
        self.assertEqual([tuple(row) for row in after], [tuple(row) for row in before])

    def test_force_regeneration_atomically_swaps_complete_quiz(self) -> None:
        quiz_date = "2026-06-14"
        quiz_set = daily_quiz.get_or_create_quiz_set(self.conn, quiz_date)
        for subject, difficulty in daily_quiz.REQUIRED_SLOTS:
            question = valid_question(subject, difficulty)
            question["question"] = f"Old published prompt for {subject} {difficulty}?"
            daily_quiz.save_question(
                self.conn,
                quiz_set_id=int(quiz_set["id"]),
                question=question,
            )
        daily_quiz.set_quiz_status(self.conn, quiz_date, "published")
        before_ids = {
            int(row[0])
            for row in self.conn.execute(
                "SELECT id FROM daily_quiz_questions WHERE quiz_set_id = ?",
                (quiz_set["id"],),
            )
        }

        result = daily_quiz.generate_daily_quiz(
            self.conn,
            quiz_date=quiz_date,
            config=config(),
            force=True,
            provider=PassingProvider("replacement"),
            log=lambda _: None,
        )
        after_rows = self.conn.execute(
            "SELECT id, question FROM daily_quiz_questions WHERE quiz_set_id = ?",
            (quiz_set["id"],),
        ).fetchall()

        self.assertEqual(result["status"], "published")
        self.assertEqual(len(after_rows), 6)
        self.assertTrue(before_ids.isdisjoint({int(row["id"]) for row in after_rows}))
        self.assertFalse(any(str(row["question"]).startswith("Old published") for row in after_rows))

    def test_served_quiz_blocks_force_regeneration_and_loaded_answers_stay_valid(self) -> None:
        import server

        quiz_date = "2026-08-15"
        quiz_set = daily_quiz.get_or_create_quiz_set(self.conn, quiz_date)
        for subject, difficulty in daily_quiz.REQUIRED_SLOTS:
            daily_quiz.save_question(
                self.conn,
                quiz_set_id=int(quiz_set["id"]),
                question=valid_question(subject, difficulty),
            )
        daily_quiz.set_quiz_status(self.conn, quiz_date, "published")
        daily_quiz.lock_published_quiz_for_play(self.conn, quiz_date)
        loaded = daily_quiz.quiz_payload(self.conn, quiz_date)
        loaded_general = [
            question
            for question in loaded["questions"]
            if question["subject"] == "general_knowledge"
        ]
        submitted = [
            {
                "questionId": question["id"],
                "choiceId": question["choices"][0]["id"],
            }
            for question in loaded_general
        ]

        result = daily_quiz.generate_daily_quiz(
            self.conn,
            quiz_date=quiz_date,
            config=config(),
            force=True,
            provider=PassingProvider("replacement"),
            log=lambda _: None,
        )

        self.assertTrue(result["regeneration_failed"])
        self.assertTrue(result["regeneration_blocked"])
        self.assertEqual(daily_quiz.quiz_payload(self.conn, quiz_date), loaded)
        normalized, adjudications, _ = server.adjudicate_quiz_answers(
            server.quiz_category_questions(self.conn, quiz_date, "general"),
            submitted,
        )
        self.assertEqual(normalized, submitted)
        self.assertTrue(all(item["correct"] for item in adjudications))

    def test_play_lock_committed_during_staging_blocks_final_atomic_swap(self) -> None:
        generation_started = threading.Event()
        continue_generation = threading.Event()

        class BlockingProvider(PassingProvider):
            def generate_question(self, **kwargs: object) -> dict[str, object]:
                if not generation_started.is_set():
                    generation_started.set()
                    if not continue_generation.wait(timeout=10):
                        raise TimeoutError("test did not release staged generation")
                return super().generate_question(**kwargs)  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "quiz-race.db"
            writer = sqlite3.connect(db_path, timeout=5, check_same_thread=False)
            writer.row_factory = sqlite3.Row
            writer.execute("PRAGMA foreign_keys = ON")
            player = sqlite3.connect(db_path, timeout=5)
            player.row_factory = sqlite3.Row
            daily_quiz.initialize_database(writer)
            quiz_date = "2026-08-15"
            quiz_set = daily_quiz.get_or_create_quiz_set(writer, quiz_date)
            for subject, difficulty in daily_quiz.REQUIRED_SLOTS:
                daily_quiz.save_question(
                    writer,
                    quiz_set_id=int(quiz_set["id"]),
                    question=valid_question(subject, difficulty),
                )
            daily_quiz.set_quiz_status(writer, quiz_date, "published")
            before_ids = [
                int(row[0])
                for row in writer.execute(
                    "SELECT id FROM daily_quiz_questions ORDER BY id"
                )
            ]
            outcome: dict[str, object] = {}

            def regenerate() -> None:
                outcome.update(
                    daily_quiz.generate_daily_quiz(
                        writer,
                        quiz_date=quiz_date,
                        config=config(),
                        force=True,
                        provider=BlockingProvider("replacement"),
                        log=lambda _: None,
                    )
                )

            worker = threading.Thread(target=regenerate)
            worker.start()
            self.assertTrue(generation_started.wait(timeout=10))
            with player:
                daily_quiz.lock_published_quiz_for_play(player, quiz_date)
            continue_generation.set()
            worker.join(timeout=20)
            self.assertFalse(worker.is_alive())

            after_ids = [
                int(row[0])
                for row in writer.execute(
                    "SELECT id FROM daily_quiz_questions ORDER BY id"
                )
            ]
            self.assertTrue(outcome["regeneration_blocked"])
            self.assertEqual(after_ids, before_ids)
            self.assertIsNotNone(
                writer.execute(
                    "SELECT locked_at FROM daily_quiz_sets WHERE quiz_date = ?",
                    (quiz_date,),
                ).fetchone()[0]
            )
            writer.close()
            player.close()

    def test_locked_swap_rolls_back_original_content_when_commit_fails(self) -> None:
        class CommitFailingConnection:
            def __init__(self, connection: sqlite3.Connection) -> None:
                self.connection = connection
                self.rollback_called = False

            @property
            def in_transaction(self) -> bool:
                return self.connection.in_transaction

            def execute(self, *args: object, **kwargs: object):
                return self.connection.execute(*args, **kwargs)

            def commit(self) -> None:
                raise sqlite3.OperationalError("commit failed")

            def rollback(self) -> None:
                self.rollback_called = True
                self.connection.rollback()

        quiz_date = "2026-08-15"
        self.conn.execute(
            "INSERT INTO daily_quiz_sets (quiz_date, status) VALUES (?, 'published')",
            (quiz_date,),
        )
        self.conn.commit()
        wrapped = CommitFailingConnection(self.conn)

        with self.assertRaisesRegex(sqlite3.OperationalError, "commit failed"):
            with daily_quiz.locked_quiz_swap(  # type: ignore[arg-type]
                wrapped,
                quiz_date,
                savepoint_name="test_commit_failure",
            ):
                wrapped.execute(
                    "UPDATE daily_quiz_sets SET status = 'failed' WHERE quiz_date = ?",
                    (quiz_date,),
                )

        self.assertTrue(wrapped.rollback_called)
        self.assertFalse(self.conn.in_transaction)
        self.assertEqual(
            self.conn.execute(
                "SELECT status FROM daily_quiz_sets WHERE quiz_date = ?",
                (quiz_date,),
            ).fetchone()[0],
            "published",
        )

    def test_recorded_result_blocks_single_question_regeneration(self) -> None:
        quiz_date = "2026-08-16"
        quiz_set = daily_quiz.get_or_create_quiz_set(self.conn, quiz_date)
        for subject, difficulty in daily_quiz.REQUIRED_SLOTS:
            daily_quiz.save_question(
                self.conn,
                quiz_set_id=int(quiz_set["id"]),
                question=valid_question(subject, difficulty),
            )
        daily_quiz.set_quiz_status(self.conn, quiz_date, "published")
        self.conn.execute(
            """
            CREATE TABLE daily_quiz_results (
                id INTEGER PRIMARY KEY,
                game_date TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            "INSERT INTO daily_quiz_results (game_date) VALUES (?)",
            (quiz_date,),
        )
        before = daily_quiz.quiz_payload(self.conn, quiz_date)

        result = daily_quiz.regenerate_question(
            self.conn,
            quiz_date=quiz_date,
            subject="football",
            difficulty="easy",
            config=config(),
            provider=PassingProvider("replacement"),
            log=lambda _: None,
        )

        self.assertTrue(result["regeneration_failed"])
        self.assertTrue(result["regeneration_blocked"])
        self.assertEqual(daily_quiz.quiz_payload(self.conn, quiz_date), before)

    def test_question_regeneration_failure_preserves_published_slot(self) -> None:
        quiz_date = "2026-06-15"
        quiz_set = daily_quiz.get_or_create_quiz_set(self.conn, quiz_date)
        for subject, difficulty in daily_quiz.REQUIRED_SLOTS:
            daily_quiz.save_question(
                self.conn,
                quiz_set_id=int(quiz_set["id"]),
                question=valid_question(subject, difficulty),
            )
        daily_quiz.set_quiz_status(self.conn, quiz_date, "published")
        before = self.conn.execute(
            """
            SELECT id, question, correct_answer FROM daily_quiz_questions
            WHERE quiz_set_id = ? AND subject = 'football' AND difficulty = 'easy'
            """,
            (quiz_set["id"],),
        ).fetchone()

        result = daily_quiz.regenerate_question(
            self.conn,
            quiz_date=quiz_date,
            subject="football",
            difficulty="easy",
            config=config(max_attempts=1),
            provider=AlwaysInvalidProvider(),
            log=lambda _: None,
        )
        after = self.conn.execute(
            """
            SELECT id, question, correct_answer FROM daily_quiz_questions
            WHERE quiz_set_id = ? AND subject = 'football' AND difficulty = 'easy'
            """,
            (quiz_set["id"],),
        ).fetchone()

        self.assertEqual(result["status"], "published")
        self.assertTrue(result["regeneration_failed"])
        self.assertEqual(tuple(after), tuple(before))

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

    def test_critic_compares_relative_difficulty_inside_subject_round(self) -> None:
        prompt = daily_quiz.critic_prompt(
            "general_knowledge",
            "hard",
            valid_question("general_knowledge", "hard"),
            [
                {
                    **valid_question("general_knowledge", "medium"),
                    "context_scope": "current_round",
                }
            ],
        )

        self.assertIn("Relative difficulty is inverted", prompt)
        self.assertIn("hard question that is easier", prompt)

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

    def test_daily_quota_circuit_skips_exhausted_provider_until_its_reset(self) -> None:
        class CountingQuotaProvider(AlwaysFailingProvider):
            def __init__(self) -> None:
                super().__init__(
                    "gemini",
                    "RESOURCE_EXHAUSTED free_tier_requests requests per day",
                )
                self.calls = 0

            def generate_question(self, **kwargs: object) -> dict[str, object]:
                self.calls += 1
                return super().generate_question(**kwargs)

        exhausted = CountingQuotaProvider()
        provider = daily_quiz.FallbackQuizProvider(
            [exhausted, PassingProvider("openrouter")]
        )

        payload = daily_quiz.generate_daily_quiz(
            self.conn,
            quiz_date="2026-06-05",
            config=config(),
            provider=provider,
            log=lambda _: None,
        )

        self.assertEqual(payload["status"], "published")
        self.assertEqual(exhausted.calls, 1)
        circuit = daily_quiz.active_provider_circuit(self.conn, "gemini")
        self.assertIsNotNone(circuit)
        circuit_status = daily_quiz.quiz_status(self.conn, "2026-06-05")[
            "provider_circuits"
        ]
        self.assertEqual([item["provider"] for item in circuit_status], ["gemini"])
        available, blocked = daily_quiz.provider_with_available_circuits(
            self.conn,
            daily_quiz.FallbackQuizProvider(
                [exhausted, PassingProvider("openrouter")]
            ),
        )
        self.assertIsNotNone(available)
        self.assertEqual(len(blocked), 1)
        available.generate_question(
            subject="general_knowledge",
            difficulty="easy",
            recent_questions=[],
            feedback=[],
        )
        self.assertEqual(daily_quiz.current_provider_name(available), "openrouter")
        self.assertEqual(exhausted.calls, 1)

    def test_all_open_provider_circuits_defer_without_an_attempt(self) -> None:
        reason = "free-models-per-day daily quota exceeded"
        gemini = AlwaysFailingProvider("gemini", reason)
        openrouter = AlwaysFailingProvider("openrouter", reason)
        self.assertTrue(
            daily_quiz.open_provider_quota_circuit(self.conn, gemini, reason)
        )
        self.assertTrue(
            daily_quiz.open_provider_quota_circuit(self.conn, openrouter, reason)
        )

        result = daily_quiz.generate_daily_quiz(
            self.conn,
            quiz_date="2026-06-06",
            config=config(),
            provider=daily_quiz.FallbackQuizProvider([gemini, openrouter]),
            log=lambda _: None,
        )

        self.assertEqual(result["status"], "generating")
        self.assertEqual(result["failed_attempts"], 0)
        self.assertIn("paused until", result["failure_reason"])

    def test_provider_daily_quota_resets_follow_documented_timezones(self) -> None:
        now = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)

        self.assertEqual(
            daily_quiz.provider_quota_reset_at("gemini:model", now=now),
            datetime(2026, 7, 2, 7, 5, tzinfo=timezone.utc),
        )
        self.assertEqual(
            daily_quiz.provider_quota_reset_at("openrouter", now=now),
            datetime(2026, 7, 2, 0, 5, tzinfo=timezone.utc),
        )
        self.assertFalse(
            daily_quiz.is_daily_quota_failure(
                "Provider request failed with HTTP 429 after a minute limit."
            )
        )

    def test_provider_chain_uses_next_critic_after_invalid_payload(self) -> None:
        invalid = InvalidCriticProvider("invalid-critic")
        fallback = PassingProvider("valid-critic")
        provider = daily_quiz.FallbackQuizProvider([invalid, fallback])

        payload = provider.critique_question(
            subject="general_knowledge",
            difficulty="easy",
            question=valid_question(),
            recent_questions=[],
        )

        self.assertTrue(payload["passed"])
        self.assertEqual(provider.last_provider_name, "valid-critic")

    def test_provider_chain_uses_next_verifier_after_invalid_payload(self) -> None:
        invalid = InvalidVerifierProvider("invalid-verifier")
        fallback = PassingProvider("valid-verifier")
        provider = daily_quiz.FallbackQuizProvider([invalid, fallback])
        evidence = supporting_evidence(valid_question())

        payload = provider.verify_question(
            subject="general_knowledge",
            difficulty="easy",
            question=valid_question(),
            evidence=evidence,
            risk_profile={},
        )

        self.assertTrue(payload["passed"])
        self.assertEqual(provider.last_provider_name, "valid-verifier")

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

    def test_generation_continues_after_oversized_evidence_response(self) -> None:
        evidence_calls = 0

        def evidence_with_first_response_oversized(
            question: dict[str, object], **_: object
        ) -> list[dict[str, str]]:
            nonlocal evidence_calls
            evidence_calls += 1
            if evidence_calls == 1:
                raise daily_quiz.EvidenceSearchUnavailable(
                    "Wikimedia evidence search failed: "
                    "Upstream response exceeds the allowed size."
                )
            return supporting_evidence(question)

        with patch(
            "daily_quiz.collect_question_evidence",
            side_effect=evidence_with_first_response_oversized,
        ):
            payload = daily_quiz.generate_daily_quiz(
                self.conn,
                quiz_date="2026-06-09",
                config=config(max_attempts=2),
                provider=PassingProvider("gemini"),
                log=lambda _: None,
            )

        self.assertEqual(payload["status"], "published")
        self.assertEqual(
            daily_quiz.quiz_status(self.conn, "2026-06-09")["accepted_questions"],
            6,
        )
        first_failure = self.conn.execute(
            """
            SELECT failure_reason FROM daily_quiz_attempts
            WHERE quiz_date = ? AND passed = 0 ORDER BY id LIMIT 1
            """,
            ("2026-06-09",),
        ).fetchone()
        self.assertIn("response exceeds the allowed size", first_failure["failure_reason"])

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

    def test_candidate_evidence_requires_trusted_source_before_short_circuit(self) -> None:
        evidence_config = daily_quiz.QuizConfig(
            **{
                **config().__dict__,
                "evidence_openrouter_api_key": "openrouter-key",
                "evidence_openrouter_base_url": "https://openrouter.ai/api/v1",
                "evidence_openrouter_model": "openrouter/free",
            }
        )
        question = valid_question()
        question["_requires_reputable_evidence"] = True
        wikipedia_evidence = [
            {
                **supporting_evidence(question)[0],
                "source_name": "Wikipedia",
                "source_url": "https://en.wikipedia.org/wiki/Example",
                "tier": "reference",
            }
        ]
        bing_evidence = [
            {
                **supporting_evidence(question)[1],
                "source_name": "Official archive",
                "source_url": "https://example.edu/official-record",
                "tier": "primary",
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
            patch("daily_quiz.precheck_question_evidence", return_value={"passed": True}),
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

    def test_verified_archive_fallback_publishes_six_embargo_safe_slots(self) -> None:
        for index, source_date in enumerate(
            ("2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06")
        ):
            quiz_set = daily_quiz.get_or_create_quiz_set(self.conn, source_date)
            for subject in daily_quiz.SUBJECTS:
                for difficulty in daily_quiz.DIFFICULTIES:
                    question = valid_question(subject, difficulty)
                    question["question"] = f"Archive {index} {subject} {difficulty}: which answer is correct?"
                    question["correct_answer"] = f"Archive answer {index} {subject} {difficulty}"
                    question["choices"] = [question["correct_answer"], "B", "C", "D"]
                    daily_quiz.save_question(
                        self.conn,
                        quiz_set_id=int(quiz_set["id"]),
                        question=question,
                        evidence=supporting_evidence(question),
                        verification=passing_verification(supporting_evidence(question)),
                    )
            daily_quiz.publish_quiz(self.conn, source_date)

        result = daily_quiz.publish_verified_archive_fallback(
            self.conn, "2026-03-01", answer_embargo_days=45
        )

        self.assertEqual(result["status"], "published")
        self.assertEqual(result["accepted_questions"], 6)
        self.assertEqual(result["verified_questions"], 6)
        stored = self.conn.execute(
            "SELECT pipeline_version, generation_mode FROM daily_quiz_sets WHERE quiz_date='2026-03-01'"
        ).fetchone()
        self.assertEqual(tuple(stored), ("archived-reserve-v1", "reserve"))

    def test_verified_archive_fallback_will_not_reuse_recent_answer(self) -> None:
        source = daily_quiz.get_or_create_quiz_set(self.conn, "2026-01-01")
        recent = daily_quiz.get_or_create_quiz_set(self.conn, "2026-02-20")
        for subject in daily_quiz.SUBJECTS:
            for difficulty in daily_quiz.DIFFICULTIES:
                question = valid_question(subject, difficulty)
                evidence = supporting_evidence(question)
                daily_quiz.save_question(
                    self.conn,
                    quiz_set_id=int(source["id"]),
                    question=question,
                    evidence=evidence,
                    verification=passing_verification(evidence),
                )
                daily_quiz.save_question(
                    self.conn,
                    quiz_set_id=int(recent["id"]),
                    question={**question, "question": "Recent " + str(question["question"])},
                    evidence=evidence,
                    verification=passing_verification(evidence),
                )
        daily_quiz.publish_quiz(self.conn, "2026-01-01")
        daily_quiz.publish_quiz(self.conn, "2026-02-20")

        with self.assertRaisesRegex(LookupError, "embargo-safe"):
            daily_quiz.publish_verified_archive_fallback(
                self.conn, "2026-03-01", answer_embargo_days=45
            )

    def test_quiz_pool_replenishes_complete_verified_batch_and_publishes_atomically(self) -> None:
        replenished = daily_quiz.replenish_quiz_pool(
            self.conn,
            config=config(),
            target_ready=1,
            max_batch_attempts=1,
            provider=PassingProvider("pool-provider"),
            log=lambda _: None,
        )

        self.assertEqual(replenished["status"], "stocked")
        self.assertEqual(replenished["ready"], 1)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM daily_quiz_pool_questions"
            ).fetchone()[0],
            6,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM daily_quiz_sets WHERE quiz_date >= '9000-01-01'"
            ).fetchone()[0],
            0,
        )

        published = daily_quiz.publish_quiz_from_pool(
            self.conn,
            "2026-08-21",
            answer_embargo_days=45,
        )

        self.assertEqual(published["status"], "published")
        self.assertEqual(published["accepted_questions"], 6)
        self.assertEqual(published["verified_questions"], 6)
        stored = self.conn.execute(
            """
            SELECT pipeline_version, generation_mode
            FROM daily_quiz_sets WHERE quiz_date = '2026-08-21'
            """
        ).fetchone()
        self.assertEqual(tuple(stored), ("pool-v1", "pool"))
        batch = self.conn.execute(
            "SELECT state, used_quiz_date FROM daily_quiz_pool_batches"
        ).fetchone()
        self.assertEqual(tuple(batch), ("used", "2026-08-21"))

    def test_quiz_pool_pauses_at_provider_cap_and_resumes_same_batch_after_reset(self) -> None:
        capped = daily_quiz.replenish_quiz_pool(
            self.conn,
            config=config(max_attempts=1),
            target_ready=1,
            max_batch_attempts=1,
            provider=AlwaysFailingProvider(
                "pool-quota-provider",
                "requests per day quota exhausted",
            ),
            log=lambda _: None,
        )

        self.assertEqual(capped["status"], "capped")
        self.assertEqual(capped["ready"], 0)
        self.assertIsNotNone(capped["retry_at"])
        job_before = self.conn.execute(
            """
            SELECT id, state, work_quiz_date
            FROM daily_quiz_pool_batches
            WHERE state = 'generating'
            """
        ).fetchone()
        self.assertIsNotNone(job_before)

        self.conn.execute("DELETE FROM daily_quiz_provider_circuits")
        self.conn.commit()
        resumed = daily_quiz.replenish_quiz_pool(
            self.conn,
            config=config(),
            target_ready=1,
            max_batch_attempts=1,
            provider=PassingProvider("pool-quota-provider"),
            log=lambda _: None,
        )

        self.assertEqual(resumed["status"], "stocked")
        job_after = self.conn.execute(
            "SELECT id, state, work_quiz_date FROM daily_quiz_pool_batches"
        ).fetchone()
        self.assertEqual(job_after["id"], job_before["id"])
        self.assertEqual(job_after["work_quiz_date"], job_before["work_quiz_date"])
        self.assertEqual(job_after["state"], "ready")

    def test_quiz_pool_retries_when_fallback_remains_available(self) -> None:
        self.conn.execute(
            """INSERT INTO daily_quiz_provider_circuits
               (provider_key, blocked_until, failure_reason, opened_at, updated_at)
               VALUES ('primary', ?, 'Primary quota exhausted', ?, ?)""",
            ((datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
             daily_quiz.utc_now(), daily_quiz.utc_now()),
        )
        self.conn.commit()
        providers = daily_quiz.FallbackQuizProvider([
            AlwaysFailingProvider("primary"), PassingProvider("fallback")
        ])
        with patch.object(
            daily_quiz,
            "generate_daily_quiz",
            return_value={"status": "generating", "failure_reason": "Candidate batch deferred"},
        ):
            result = daily_quiz.replenish_quiz_pool(
                self.conn,
                config=config(),
                target_ready=1,
                max_batch_attempts=1,
                provider=providers,
                log=lambda _: None,
            )

        self.assertEqual(result["status"], "deferred")
        self.assertIsNone(result["retry_at"])
        self.assertEqual(result["generating"], 1)
        self.assertEqual(len(result["provider_circuits"]), 1)

    def test_quiz_pool_retires_exhausted_work_date_even_with_provider_circuit(self) -> None:
        job = daily_quiz._create_quiz_pool_job(self.conn)
        work_date = job["work_quiz_date"]
        self.conn.execute(
            """INSERT INTO daily_quiz_attempts
               (quiz_date, subject, difficulty, attempt_number, provider,
                generated_json, passed, failure_reason, created_at)
               VALUES (?, 'football', 'medium', 1, 'test-provider', '{}', 0,
                       'Repeated answer', ?)""",
            (work_date, daily_quiz.utc_now()),
        )
        self.conn.execute(
            """INSERT INTO daily_quiz_provider_circuits
               (provider_key, blocked_until, failure_reason, opened_at, updated_at)
               VALUES ('test-provider', ?, 'Quota exhausted', ?, ?)""",
            ((datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
             daily_quiz.utc_now(), daily_quiz.utc_now()),
        )
        self.conn.commit()

        result = daily_quiz.replenish_quiz_pool(
            self.conn,
            config=replace(config(), max_failed_attempts_per_date=1),
            target_ready=1,
            max_batch_attempts=2,
            provider=PassingProvider("test-provider"),
            log=lambda _: None,
        )

        self.assertEqual(result["status"], "capped")
        self.assertEqual(result["generating"], 0)
        self.assertEqual(self.conn.execute(
            "SELECT state FROM daily_quiz_pool_batches WHERE id=?", (job["id"],)
        ).fetchone()[0], "failed")
        self.assertEqual(daily_quiz.failed_attempt_count(self.conn, work_date), 0)

    def test_quiz_pool_moves_to_fresh_work_date_after_exhausted_budget(self) -> None:
        job = daily_quiz._create_quiz_pool_job(self.conn)
        self.conn.execute(
            """INSERT INTO daily_quiz_attempts
               (quiz_date, subject, difficulty, attempt_number, provider,
                generated_json, passed, failure_reason, created_at)
               VALUES (?, 'football', 'medium', 1, 'test-provider', '{}', 0,
                       'Repeated answer', ?)""",
            (job["work_quiz_date"], daily_quiz.utc_now()),
        )
        self.conn.commit()

        result = daily_quiz.replenish_quiz_pool(
            self.conn,
            config=replace(config(), max_failed_attempts_per_date=1),
            target_ready=1,
            max_batch_attempts=2,
            provider=PassingProvider("test-provider"),
            log=lambda _: None,
        )

        self.assertEqual(result["status"], "stocked")
        self.assertEqual(result["ready"], 1)
        self.assertEqual(self.conn.execute(
            "SELECT state FROM daily_quiz_pool_batches WHERE id=?", (job["id"],)
        ).fetchone()[0], "failed")
        self.assertNotEqual(self.conn.execute(
            "SELECT work_quiz_date FROM daily_quiz_pool_batches WHERE state='ready'"
        ).fetchone()[0], job["work_quiz_date"])

    def test_quiz_pool_carries_verified_partial_batch_after_attempt_budget(self) -> None:
        job = daily_quiz._create_quiz_pool_job(self.conn)
        quiz_set = daily_quiz.get_or_create_quiz_set(self.conn, job["work_quiz_date"])
        carried = []
        for subject, difficulty in daily_quiz.REQUIRED_SLOTS[:-1]:
            question = valid_question(subject, difficulty)
            evidence = supporting_evidence(question)
            daily_quiz.save_question(
                self.conn,
                quiz_set_id=int(quiz_set["id"]),
                question=question,
                evidence=evidence,
                verification=passing_verification(evidence),
            )
            carried.append((subject, difficulty, question["question"]))
        self.conn.execute(
            """INSERT INTO daily_quiz_attempts
               (quiz_date, subject, difficulty, attempt_number, provider,
                generated_json, passed, failure_reason, created_at)
               VALUES (?, 'football', 'medium', 1, 'test-provider', '{}', 0,
                       'Repeated answer', ?)""",
            (job["work_quiz_date"], daily_quiz.utc_now()),
        )
        self.conn.commit()

        result = daily_quiz.replenish_quiz_pool(
            self.conn,
            config=replace(config(), max_failed_attempts_per_date=1),
            target_ready=1,
            max_batch_attempts=2,
            provider=PassingProvider("test-provider"),
            log=lambda _: None,
        )

        self.assertEqual(result["status"], "stocked")
        self.assertEqual(self.conn.execute(
            "SELECT state FROM daily_quiz_pool_batches WHERE id=?", (job["id"],)
        ).fetchone()[0], "failed")
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM daily_quiz_pool_questions WHERE batch_id != ?",
            (job["id"],),
        ).fetchone()[0], 6)
        self.assertEqual(
            [tuple(row) for row in self.conn.execute(
                """SELECT subject, difficulty, question FROM daily_quiz_pool_questions
                   WHERE batch_id != ? ORDER BY subject, difficulty""",
                (job["id"],),
            ) if (row[0], row[1], row[2]) in carried],
            sorted(carried),
        )
        self.assertEqual(daily_quiz.failed_attempt_count(self.conn, job["work_quiz_date"]), 0)

    def test_quiz_pool_claim_rolls_back_if_publication_fails(self) -> None:
        daily_quiz.replenish_quiz_pool(
            self.conn,
            config=config(),
            target_ready=1,
            max_batch_attempts=1,
            provider=PassingProvider("pool-rollback-provider"),
            log=lambda _: None,
        )
        self.conn.execute(
            """
            CREATE TRIGGER fail_pool_question_insert
            BEFORE INSERT ON daily_quiz_questions
            WHEN NEW.quiz_set_id IN (
                SELECT id FROM daily_quiz_sets WHERE quiz_date = '2026-08-22'
            )
            BEGIN
                SELECT RAISE(ABORT, 'simulated publication failure');
            END
            """
        )
        self.conn.commit()

        with self.assertRaisesRegex(sqlite3.IntegrityError, "simulated publication failure"):
            daily_quiz.publish_quiz_from_pool(
                self.conn,
                "2026-08-22",
                answer_embargo_days=45,
            )

        self.assertEqual(
            self.conn.execute(
                "SELECT state FROM daily_quiz_pool_batches"
            ).fetchone()[0],
            "ready",
        )
        self.assertIsNone(
            self.conn.execute(
                "SELECT 1 FROM daily_quiz_sets WHERE quiz_date = '2026-08-22'"
            ).fetchone()
        )

    def test_ready_quiz_pool_questions_are_part_of_duplicate_history(self) -> None:
        daily_quiz.replenish_quiz_pool(
            self.conn,
            config=config(),
            target_ready=1,
            max_batch_attempts=1,
            provider=PassingProvider("pool-history-provider"),
            log=lambda _: None,
        )

        history = daily_quiz.recent_questions(
            self.conn,
            subject="football",
            history_days=90,
        )

        self.assertEqual(len(history), 3)
        self.assertEqual(
            {question["difficulty"] for question in history},
            {"easy", "medium", "hard"},
        )

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

    def test_free_routes_only_rejects_named_paid_openrouter_model(self) -> None:
        restricted = daily_quiz.QuizConfig(
            **{
                **config().__dict__,
                "provider": "openrouter",
                "generator_model": "openai/gpt-4.1-mini",
                "critic_model": "openai/gpt-4.1-mini",
                "gemini_api_key": "",
                "compatible_api_key": "or-key",
                "compatible_base_url": "https://openrouter.ai/api/v1",
                "free_routes_only": True,
            }
        )

        with self.assertRaisesRegex(ValueError, "only openrouter/free"):
            daily_quiz.provider_chain_from_config(restricted)

    def test_free_routes_only_accepts_openrouter_free_variants(self) -> None:
        restricted = daily_quiz.QuizConfig(
            **{
                **config().__dict__,
                "provider": "openrouter",
                "generator_model": "openrouter/free",
                "critic_model": "meta-llama/llama-3.3-70b-instruct:free",
                "gemini_api_key": "",
                "compatible_api_key": "or-key",
                "compatible_base_url": "https://openrouter.ai/api/v1",
                "free_routes_only": True,
            }
        )

        provider = daily_quiz.provider_chain_from_config(restricted)

        self.assertIsInstance(provider, daily_quiz.OpenAICompatibleProvider)

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

            def read(self, _limit: int) -> bytes:
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

            def read(self, _limit: int) -> bytes:
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

            def read(self, _limit: int) -> bytes:
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
