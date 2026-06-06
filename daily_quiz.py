from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any, Callable, Protocol
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SUBJECTS = ("general_knowledge", "football")
DIFFICULTIES = ("easy", "medium", "hard")
REQUIRED_SLOTS = tuple(
    (subject, difficulty)
    for subject in SUBJECTS
    for difficulty in DIFFICULTIES
)
CRITIC_THRESHOLDS = {
    "validity": 8,
    "correctness": 9,
    "difficulty_match": 8,
    "interestingness": 7,
    "non_repetition": 9,
}
QUESTION_REQUIRED_FIELDS = (
    "subject",
    "difficulty",
    "question",
    "choices",
    "correct_answer",
    "explanation",
    "interesting_reason",
    "tags",
)
CRITIC_SCORE_FIELDS = tuple(CRITIC_THRESHOLDS)
QUESTION_CUES = (
    "who",
    "what",
    "when",
    "where",
    "why",
    "which",
    "how",
    "whose",
    "whom",
    "is",
    "are",
    "was",
    "were",
    "did",
    "does",
    "do",
    "can",
    "could",
)
VOLATILE_FACT_TERMS = (
    "currently",
    "latest",
    "this season",
    "right now",
    "most recent",
)
VOLATILE_FACT_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bas of (?:today|now)\b",
        r"\b(?:today|yesterday|tomorrow)\b.{0,40}\b(?:match|game|score|standings|table|fixture|transfer|manager|captain|owner|president|leader|champion|holder)\b",
        r"\b(?:match|game|score|standings|table|fixture|transfer|manager|captain|owner|president|leader|champion|holder)\b.{0,40}\b(?:today|yesterday|tomorrow)\b",
    )
)
GENERIC_TOPIC_TAGS = {
    "football",
    "general",
    "general knowledge",
    "history",
    "geography",
    "science",
    "technology",
    "nature",
    "architecture",
    "landmarks",
    "archaeology",
    "art",
    "biology",
    "books",
    "chemistry",
    "culture",
    "easy",
    "engineering",
    "film",
    "medium",
    "hard",
    "language",
    "linguistics",
    "literature",
    "math",
    "mathematics",
    "music",
    "philosophy",
    "physics",
    "politics",
    "quiz",
    "religion",
    "space",
    "sport",
    "sports",
    "television",
}

DEFAULT_COMPATIBLE_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


def default_compatible_base_url(provider: str, explicit_base_url: str) -> str:
    value = explicit_base_url.strip().rstrip("/")
    if value:
        return value
    return DEFAULT_COMPATIBLE_BASE_URLS.get(provider.strip().lower(), "")


@dataclass(frozen=True)
class QuizConfig:
    provider: str
    generator_model: str
    critic_model: str
    gemini_api_key: str
    compatible_api_key: str
    compatible_base_url: str
    fallback_provider: str
    fallback_generator_model: str
    fallback_critic_model: str
    fallback_gemini_api_key: str
    fallback_compatible_api_key: str
    fallback_compatible_base_url: str
    fallback2_provider: str
    fallback2_generator_model: str
    fallback2_critic_model: str
    fallback2_gemini_api_key: str
    fallback2_compatible_api_key: str
    fallback2_compatible_base_url: str
    timeout_sec: int
    request_delay_sec: float
    transient_retries: int
    max_attempts_per_slot: int
    question_history_days: int
    internal_token: str

    @classmethod
    def from_env(cls) -> "QuizConfig":
        provider = os.environ.get("AI_PROVIDER", "gemini").strip().lower()
        fallback_provider = os.environ.get("AI_FALLBACK_PROVIDER", "").strip().lower()
        fallback2_provider = os.environ.get("AI_FALLBACK2_PROVIDER", "").strip().lower()
        return cls(
            provider=provider,
            generator_model=os.environ.get(
                "AI_GENERATOR_MODEL",
                "gemini-3.5-flash",
            ).strip(),
            critic_model=os.environ.get(
                "AI_CRITIC_MODEL",
                "gemini-3.1-flash-lite",
            ).strip(),
            gemini_api_key=os.environ.get("GEMINI_API_KEY", "").strip(),
            compatible_api_key=os.environ.get("AI_API_KEY", "").strip(),
            compatible_base_url=default_compatible_base_url(
                provider,
                os.environ.get("AI_BASE_URL", ""),
            ),
            fallback_provider=fallback_provider,
            fallback_generator_model=os.environ.get("AI_FALLBACK_GENERATOR_MODEL", "").strip(),
            fallback_critic_model=os.environ.get("AI_FALLBACK_CRITIC_MODEL", "").strip(),
            fallback_gemini_api_key=os.environ.get("AI_FALLBACK_GEMINI_API_KEY", "").strip(),
            fallback_compatible_api_key=os.environ.get("AI_FALLBACK_API_KEY", "").strip(),
            fallback_compatible_base_url=default_compatible_base_url(
                fallback_provider,
                os.environ.get("AI_FALLBACK_BASE_URL", ""),
            ),
            fallback2_provider=fallback2_provider,
            fallback2_generator_model=os.environ.get("AI_FALLBACK2_GENERATOR_MODEL", "").strip(),
            fallback2_critic_model=os.environ.get("AI_FALLBACK2_CRITIC_MODEL", "").strip(),
            fallback2_gemini_api_key=os.environ.get("AI_FALLBACK2_GEMINI_API_KEY", "").strip(),
            fallback2_compatible_api_key=os.environ.get("AI_FALLBACK2_API_KEY", "").strip(),
            fallback2_compatible_base_url=default_compatible_base_url(
                fallback2_provider,
                os.environ.get("AI_FALLBACK2_BASE_URL", ""),
            ),
            timeout_sec=max(5, int(os.environ.get("AI_TIMEOUT_SEC", "90"))),
            request_delay_sec=max(
                0.0,
                float(os.environ.get("AI_REQUEST_DELAY_SEC", "12")),
            ),
            transient_retries=max(
                0,
                int(os.environ.get("AI_TRANSIENT_RETRIES", "3")),
            ),
            max_attempts_per_slot=max(
                1,
                int(os.environ.get("MAX_ATTEMPTS_PER_SLOT", "15")),
            ),
            question_history_days=max(
                1,
                int(os.environ.get("QUESTION_HISTORY_DAYS", "90")),
            ),
            internal_token=os.environ.get("INTERNAL_QUIZ_TOKEN", "").strip(),
        )

    def provider_is_configured(self) -> bool:
        if self.provider == "gemini":
            return bool(self.gemini_api_key)
        return bool(self.compatible_api_key and self.compatible_base_url)


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    reason: str
    question: dict[str, Any] | None = None


@dataclass(frozen=True)
class RepetitionResult:
    passed: bool
    reason: str


class QuizAIProvider(Protocol):
    name: str

    def generate_question(
        self,
        *,
        subject: str,
        difficulty: str,
        recent_questions: list[dict[str, Any]],
        feedback: list[str],
    ) -> dict[str, Any]:
        ...

    def critique_question(
        self,
        *,
        subject: str,
        difficulty: str,
        question: dict[str, Any],
        recent_questions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ...


def configured_provider_config(config: QuizConfig, *, stage: int = 0) -> QuizConfig | None:
    if stage == 0:
        provider = config.provider
        generator_model = config.generator_model
        critic_model = config.critic_model
        gemini_api_key = config.gemini_api_key
        compatible_api_key = config.compatible_api_key
        compatible_base_url = config.compatible_base_url
    elif stage == 1:
        provider = config.fallback_provider
        generator_model = config.fallback_generator_model
        critic_model = config.fallback_critic_model
        gemini_api_key = config.fallback_gemini_api_key
        compatible_api_key = config.fallback_compatible_api_key
        compatible_base_url = config.fallback_compatible_base_url
    elif stage == 2:
        provider = config.fallback2_provider
        generator_model = config.fallback2_generator_model
        critic_model = config.fallback2_critic_model
        gemini_api_key = config.fallback2_gemini_api_key
        compatible_api_key = config.fallback2_compatible_api_key
        compatible_base_url = config.fallback2_compatible_base_url
    else:
        return None

    provider = provider.strip().lower()
    if not provider:
        return None

    generator_model = generator_model.strip()
    critic_model = critic_model.strip()
    if stage > 0 and provider == config.provider:
        generator_model = generator_model or config.generator_model
        critic_model = critic_model or config.critic_model
    if not generator_model or not critic_model:
        return None

    gemini_api_key = gemini_api_key.strip()
    compatible_api_key = compatible_api_key.strip()
    compatible_base_url = default_compatible_base_url(provider, compatible_base_url)

    if stage > 0:
        if provider == "gemini" and not gemini_api_key:
            gemini_api_key = config.gemini_api_key
        if provider in {"groq", "openrouter", "openai-compatible"}:
            if not compatible_api_key:
                compatible_api_key = config.compatible_api_key
            if not compatible_base_url:
                compatible_base_url = default_compatible_base_url(provider, config.compatible_base_url)

    candidate = replace(
        config,
        provider=provider,
        generator_model=generator_model,
        critic_model=critic_model,
        gemini_api_key=gemini_api_key,
        compatible_api_key=compatible_api_key,
        compatible_base_url=compatible_base_url,
    )
    return candidate if candidate.provider_is_configured() else None


def attempt_provider_label(generator_provider: str, critic_provider: str | None = None) -> str:
    critic_provider = (critic_provider or "").strip()
    if not critic_provider or critic_provider == generator_provider:
        return generator_provider
    return f"generator:{generator_provider};critic:{critic_provider}"


def current_provider_name(provider: QuizAIProvider) -> str:
    return str(getattr(provider, "last_provider_name", getattr(provider, "name", "unknown")))


class GeminiProvider:
    name = "gemini"

    def __init__(self, config: QuizConfig) -> None:
        if not config.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not configured.")
        self.config = config
        self.name = config.provider or self.name
        self._next_request_at = 0.0

    def _wait_for_request_slot(self) -> None:
        wait_sec = self._next_request_at - time.monotonic()
        if wait_sec > 0:
            time.sleep(wait_sec)
        self._next_request_at = time.monotonic() + self.config.request_delay_sec

    def _defer_retry(self, attempt: int, error: HTTPError) -> None:
        retry_after = error.headers.get("Retry-After", "").strip()
        try:
            retry_after_sec = float(retry_after)
        except ValueError:
            retry_after_sec = 0.0
        try:
            error_payload = json.loads(error.read().decode("utf-8"))
            details = error_payload.get("error", {}).get("details", [])
            retry_info = next(
                (
                    detail
                    for detail in details
                    if str(detail.get("@type", "")).endswith("RetryInfo")
                ),
                {},
            )
            retry_delay = str(retry_info.get("retryDelay", "")).rstrip("s")
            retry_after_sec = max(retry_after_sec, float(retry_delay or 0))
        except (AttributeError, json.JSONDecodeError, TypeError, ValueError):
            pass
        delay = max(
            self.config.request_delay_sec,
            retry_after_sec,
            min(60.0, 5.0 * (2**attempt)),
        )
        self._next_request_at = max(self._next_request_at, time.monotonic() + delay)

    def _request(self, model: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{quote(model, safe='')}:generateContent"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.5,
                "responseMimeType": "application/json",
                "responseJsonSchema": schema,
            },
        }
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.config.gemini_api_key,
            },
            method="POST",
        )
        for attempt in range(self.config.transient_retries + 1):
            self._wait_for_request_slot()
            try:
                with urlopen(request, timeout=self.config.timeout_sec) as response:
                    response_payload = json.loads(response.read().decode("utf-8"))
                break
            except HTTPError as error:
                if error.code in {429, 500, 502, 503, 504} and attempt < self.config.transient_retries:
                    self._defer_retry(attempt, error)
                    continue
                raise RuntimeError(f"Gemini request failed with HTTP {error.code}.") from error
        else:  # pragma: no cover - loop always exits through break or raise
            raise RuntimeError("Gemini request failed.")
        try:
            text = response_payload["candidates"][0]["content"]["parts"][0]["text"]
        except (IndexError, KeyError, TypeError) as error:
            raise ValueError("Gemini returned no structured content.") from error
        return parse_json_object(text)

    def generate_question(
        self,
        *,
        subject: str,
        difficulty: str,
        recent_questions: list[dict[str, Any]],
        feedback: list[str],
    ) -> dict[str, Any]:
        return self._request(
            self.config.generator_model,
            generator_prompt(subject, difficulty, recent_questions, feedback),
            question_schema(),
        )

    def critique_question(
        self,
        *,
        subject: str,
        difficulty: str,
        question: dict[str, Any],
        recent_questions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self._request(
            self.config.critic_model,
            critic_prompt(subject, difficulty, question, recent_questions),
            critic_schema(),
        )


class OpenAICompatibleProvider:
    name = "openai-compatible"

    def __init__(self, config: QuizConfig) -> None:
        if not config.compatible_api_key or not config.compatible_base_url:
            raise ValueError("AI_API_KEY and AI_BASE_URL must be configured.")
        self.config = config
        self.name = config.provider or self.name
        self._next_request_at = 0.0

    def _wait_for_request_slot(self) -> None:
        wait_sec = self._next_request_at - time.monotonic()
        if wait_sec > 0:
            time.sleep(wait_sec)
        self._next_request_at = time.monotonic() + self.config.request_delay_sec

    def _defer_retry(self, attempt: int, error: HTTPError | None = None) -> None:
        retry_after_sec = 0.0
        if error is not None:
            retry_after = error.headers.get("Retry-After", "").strip()
            try:
                retry_after_sec = float(retry_after)
            except ValueError:
                retry_after_sec = 0.0
        delay = max(
            self.config.request_delay_sec,
            retry_after_sec,
            min(60.0, 5.0 * (2**attempt)),
        )
        self._next_request_at = max(self._next_request_at, time.monotonic() + delay)

    def _request(self, model: str, prompt: str) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.config.compatible_api_key}",
            "Content-Type": "application/json",
        }
        if self.name == "openrouter":
            headers["HTTP-Referer"] = "https://fultons-quiz.co.uk"
            headers["X-Title"] = "Fultons Quiz"
        request = Request(
            f"{self.config.compatible_base_url}/chat/completions",
            data=json.dumps(
                {
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Return one valid JSON object only. Do not use markdown.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.5,
                    "max_tokens": 1000,
                    "stream": False,
                    "response_format": {"type": "json_object"},
                }
            ).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        for attempt in range(self.config.transient_retries + 1):
            self._wait_for_request_slot()
            try:
                with urlopen(request, timeout=self.config.timeout_sec) as response:
                    response_payload = json.loads(response.read().decode("utf-8"))
                break
            except HTTPError as error:
                if error.code in {408, 429, 500, 502, 503, 504} and attempt < self.config.transient_retries:
                    self._defer_retry(attempt, error)
                    continue
                raise RuntimeError(f"{self.name} request failed with HTTP {error.code}.") from error
            except (TimeoutError, URLError, OSError) as error:
                if attempt < self.config.transient_retries:
                    self._defer_retry(attempt)
                    continue
                raise RuntimeError(f"{self.name} request timed out or failed: {error}") from error
        else:  # pragma: no cover - loop always exits through break or raise
            raise RuntimeError(f"{self.name} request failed.")
        try:
            text = response_payload["choices"][0]["message"]["content"]
        except (IndexError, KeyError, TypeError) as error:
            raise ValueError("AI provider returned no chat completion content.") from error
        return parse_json_object(text)

    def generate_question(
        self,
        *,
        subject: str,
        difficulty: str,
        recent_questions: list[dict[str, Any]],
        feedback: list[str],
    ) -> dict[str, Any]:
        return self._request(
            self.config.generator_model,
            generator_prompt(subject, difficulty, recent_questions, feedback),
        )

    def critique_question(
        self,
        *,
        subject: str,
        difficulty: str,
        question: dict[str, Any],
        recent_questions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self._request(
            self.config.critic_model,
            critic_prompt(subject, difficulty, question, recent_questions),
        )


class FallbackQuizProvider:
    def __init__(self, providers: list[QuizAIProvider]) -> None:
        if not providers:
            raise ValueError("At least one quiz AI provider is required.")
        self.providers = providers
        self.name = " -> ".join(provider.name for provider in providers)
        self.last_provider_name = providers[0].name

    def _call(self, method_name: str, **kwargs: Any) -> dict[str, Any]:
        errors: list[str] = []
        for provider in self.providers:
            self.last_provider_name = provider.name
            try:
                return getattr(provider, method_name)(**kwargs)
            except Exception as error:
                errors.append(f"{provider.name}: {error}")
                continue
        raise RuntimeError(f"All AI providers failed for {method_name}: {' | '.join(errors)}")

    def generate_question(
        self,
        *,
        subject: str,
        difficulty: str,
        recent_questions: list[dict[str, Any]],
        feedback: list[str],
    ) -> dict[str, Any]:
        return self._call(
            "generate_question",
            subject=subject,
            difficulty=difficulty,
            recent_questions=recent_questions,
            feedback=feedback,
        )

    def critique_question(
        self,
        *,
        subject: str,
        difficulty: str,
        question: dict[str, Any],
        recent_questions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self._call(
            "critique_question",
            subject=subject,
            difficulty=difficulty,
            question=question,
            recent_questions=recent_questions,
        )


def provider_from_config(config: QuizConfig) -> QuizAIProvider:
    if config.provider == "gemini":
        return GeminiProvider(config)
    if config.provider in {"groq", "openrouter", "openai-compatible"}:
        return OpenAICompatibleProvider(config)
    raise ValueError(f"Unsupported AI_PROVIDER: {config.provider}")


def provider_chain_from_config(config: QuizConfig) -> QuizAIProvider:
    providers: list[QuizAIProvider] = []
    seen_configs: set[tuple[str, str, str, str, str, str]] = set()
    for stage in (0, 1, 2):
        candidate = configured_provider_config(config, stage=stage)
        if candidate is None:
            continue
        signature = (
            candidate.provider,
            candidate.generator_model,
            candidate.critic_model,
            candidate.gemini_api_key,
            candidate.compatible_api_key,
            candidate.compatible_base_url,
        )
        if signature in seen_configs:
            continue
        seen_configs.add(signature)
        providers.append(provider_from_config(candidate))

    if not providers:
        raise ValueError("No configured AI providers are available.")
    if len(providers) == 1:
        return providers[0]
    return FallbackQuizProvider(providers)


def question_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "subject": {"type": "string", "enum": list(SUBJECTS)},
            "difficulty": {"type": "string", "enum": list(DIFFICULTIES)},
            "question": {"type": "string"},
            "choices": {
                "type": "array",
                "items": {"type": "string"},
            },
            "correct_answer": {"type": "string"},
            "explanation": {"type": "string"},
            "interesting_reason": {"type": "string"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": list(QUESTION_REQUIRED_FIELDS),
    }


def critic_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "passed": {"type": "boolean"},
            "scores": {
                "type": "object",
                "properties": {
                    score: {"type": "integer", "minimum": 0, "maximum": 10}
                    for score in CRITIC_SCORE_FIELDS
                },
                "required": list(CRITIC_SCORE_FIELDS),
            },
            "failure_reasons": {
                "type": "array",
                "items": {"type": "string"},
            },
            "feedback_to_generator": {"type": "string"},
            "corrected_difficulty": {
                "type": "string",
                "enum": [*DIFFICULTIES, "unknown"],
            },
            "notes": {"type": "string"},
        },
        "required": [
            "passed",
            "scores",
            "failure_reasons",
            "feedback_to_generator",
            "corrected_difficulty",
            "notes",
        ],
    }


def generator_prompt(
    subject: str,
    difficulty: str,
    recent_questions: list[dict[str, Any]],
    feedback: list[str],
) -> str:
    return f"""You are generating quiz questions for a daily quiz app.

Create exactly one multiple-choice question.

Subject: {subject}
Difficulty: {difficulty}

Rules:
- The question must be interesting, not bland.
- Write a real question ending with a question mark.
- The question must have exactly one correct answer.
- Provide exactly 4 plausible answer choices.
- The correct_answer must exactly match one of the choices.
- Avoid recent or current facts unless they are very stable and well-known.
- Avoid questions that are overly obscure, ambiguous, disputed, or boring.
- Avoid repeating the recent topics and questions below.

Difficulty guide:

Easy:
- Most casual players should have a fair chance.
- The answer should be widely known.
- Avoid obscure names, tiny details, or niche facts.

Medium:
- Requires some knowledge, but should still feel fair.
- A regular quiz player may know it.
- The wrong answers should be plausible.

Hard:
- Challenging but not unfair.
- The answer should be verifiable.
- Do not use tiny, joyless trivia.
- Do not use facts that are disputed or likely to change.

Recent accepted questions:
{json.dumps(public_recent_questions(recent_questions), indent=2)}

Previous failed attempts and feedback:
{json.dumps(feedback[-5:], indent=2)}

Return JSON only using this structure:
{json.dumps(question_schema(), indent=2)}
"""


def critic_prompt(
    subject: str,
    difficulty: str,
    question: dict[str, Any],
    recent_questions: list[dict[str, Any]],
) -> str:
    return f"""You are a strict quiz question critic.

Assess the following question.

Target subject: {subject}
Target difficulty: {difficulty}

Question JSON:
{json.dumps(question, indent=2)}

Recent accepted questions:
{json.dumps(public_recent_questions(recent_questions), indent=2)}

Fail the question if:
- It is ambiguous.
- More than one answer could be correct.
- The answer appears wrong.
- The explanation is weak or does not prove the answer.
- The difficulty does not match the target.
- It is boring or too generic.
- It is too similar to a recent question.
- It depends on very recent information that may have changed.
- The choices are too obvious, silly, or implausible.

Score every dimension with an integer from 0 to 10.
- A score of 5 means borderline and must be rejected.
- Set passed to true only if validity >= 8, correctness >= 9,
  difficulty_match >= 8, interestingness >= 7, and non_repetition >= 9.
- If you describe an item as accurate, clear, interesting, and suitable for
  publication, use scores that reflect that judgement.
- If passed is false, explain the concrete problem in failure_reasons and give
  actionable feedback_to_generator.

Return JSON only using this structure:
{json.dumps(critic_schema(), indent=2)}
"""


def parse_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise ValueError("AI response is not JSON text.")
    text = value.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("AI response does not contain a JSON object.")
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("AI response JSON is not an object.")
    return payload


def normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def question_uses_volatile_fact(question: str) -> bool:
    question_lower = question.casefold()
    if any(term in question_lower for term in VOLATILE_FACT_TERMS):
        return True
    return any(pattern.search(question) for pattern in VOLATILE_FACT_PATTERNS)


def is_generic_topic_tag(value: str) -> bool:
    return normalize_text(value) in GENERIC_TOPIC_TAGS


def validate_question(
    value: Any,
    *,
    expected_subject: str | None = None,
    expected_difficulty: str | None = None,
) -> ValidationResult:
    if not isinstance(value, dict):
        return ValidationResult(False, "Question payload is not an object.")
    missing = [field for field in QUESTION_REQUIRED_FIELDS if field not in value]
    if missing:
        return ValidationResult(False, f"Missing required fields: {', '.join(missing)}.")

    subject = str(value.get("subject") or "").strip()
    difficulty = str(value.get("difficulty") or "").strip()
    if subject not in SUBJECTS:
        return ValidationResult(False, "Subject must be general_knowledge or football.")
    if expected_subject is not None and subject != expected_subject:
        return ValidationResult(False, "Subject does not match the requested slot.")
    if difficulty not in DIFFICULTIES:
        return ValidationResult(False, "Difficulty must be easy, medium, or hard.")
    if expected_difficulty is not None and difficulty != expected_difficulty:
        return ValidationResult(False, "Difficulty does not match the requested slot.")

    question = value.get("question")
    if not isinstance(question, str):
        return ValidationResult(False, "Question must be a string.")
    question = question.strip()
    if len(question) < 30:
        return ValidationResult(False, "Question is shorter than 30 characters.")
    if len(question) > 220:
        return ValidationResult(False, "Question is longer than 220 characters.")
    if not question.endswith("?"):
        return ValidationResult(False, "Question must end with a question mark.")
    question_lower = question.casefold()
    if not any(re.search(rf"\b{re.escape(cue)}\b", question_lower) for cue in QUESTION_CUES):
        return ValidationResult(False, "Question does not look interrogative.")
    if question_uses_volatile_fact(question):
        return ValidationResult(False, "Question relies on a volatile current fact.")

    choices = value.get("choices")
    if not isinstance(choices, list) or len(choices) != 4:
        return ValidationResult(False, "Choices must contain exactly four items.")
    if not all(isinstance(choice, str) and choice.strip() for choice in choices):
        return ValidationResult(False, "Every choice must be a non-empty string.")
    clean_choices = [choice.strip() for choice in choices]
    if len({normalize_text(choice) for choice in clean_choices}) != 4:
        return ValidationResult(False, "Choices must be unique.")

    correct_answer = value.get("correct_answer")
    if not isinstance(correct_answer, str) or correct_answer not in clean_choices:
        return ValidationResult(False, "correct_answer must exactly match one choice.")

    explanation = value.get("explanation")
    if not isinstance(explanation, str) or len(explanation.strip()) < 40:
        return ValidationResult(False, "Explanation must contain at least 40 characters.")
    if len(explanation.strip()) > 500:
        return ValidationResult(False, "Explanation is longer than 500 characters.")

    interesting_reason = value.get("interesting_reason")
    if not isinstance(interesting_reason, str) or len(interesting_reason.strip()) < 20:
        return ValidationResult(False, "interesting_reason must contain at least 20 characters.")
    if len(interesting_reason.strip()) > 500:
        return ValidationResult(False, "interesting_reason is longer than 500 characters.")

    tags = value.get("tags")
    if not isinstance(tags, list) or len(tags) < 2:
        return ValidationResult(False, "Tags must contain at least two items.")
    if not all(isinstance(tag, str) and tag.strip() for tag in tags):
        return ValidationResult(False, "Every tag must be a non-empty string.")
    clean_tags = list(dict.fromkeys(tag.strip().lower() for tag in tags))
    if len(clean_tags) < 2:
        return ValidationResult(False, "Tags must contain at least two unique items.")

    clean_question = {
        "subject": subject,
        "difficulty": difficulty,
        "question": question,
        "choices": clean_choices,
        "correct_answer": correct_answer,
        "explanation": explanation.strip(),
        "interesting_reason": interesting_reason.strip(),
        "tags": clean_tags,
    }
    return ValidationResult(True, "OK", clean_question)


def validate_critic(value: Any) -> ValidationResult:
    if not isinstance(value, dict):
        return ValidationResult(False, "Critic payload is not an object.")
    scores = value.get("scores")
    if not isinstance(value.get("passed"), bool) or not isinstance(scores, dict):
        return ValidationResult(False, "Critic payload is missing passed or scores.")
    for score_name in CRITIC_SCORE_FIELDS:
        score = scores.get(score_name)
        if not isinstance(score, int) or not 0 <= score <= 10:
            return ValidationResult(False, f"Critic score {score_name} must be an integer from 0 to 10.")
    if not isinstance(value.get("failure_reasons"), list):
        return ValidationResult(False, "Critic failure_reasons must be a list.")
    if not isinstance(value.get("feedback_to_generator"), str):
        return ValidationResult(False, "Critic feedback_to_generator must be a string.")
    if value.get("corrected_difficulty") not in {*DIFFICULTIES, "unknown"}:
        return ValidationResult(False, "Critic corrected_difficulty is invalid.")
    if not isinstance(value.get("notes"), str):
        return ValidationResult(False, "Critic notes must be a string.")
    return ValidationResult(True, "OK", value)


def critic_passed(value: dict[str, Any]) -> bool:
    if not value.get("passed"):
        return False
    scores = value.get("scores", {})
    return all(scores.get(name, -1) >= minimum for name, minimum in CRITIC_THRESHOLDS.items())


def initialize_database(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS daily_quiz_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_date TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL CHECK (status IN ('generating', 'published', 'failed')),
            generated_at TEXT,
            published_at TEXT,
            failure_reason TEXT
        );

        CREATE TABLE IF NOT EXISTS daily_quiz_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_set_id INTEGER NOT NULL,
            subject TEXT NOT NULL CHECK (subject IN ('general_knowledge', 'football')),
            difficulty TEXT NOT NULL CHECK (difficulty IN ('easy', 'medium', 'hard')),
            question TEXT NOT NULL,
            choices_json TEXT NOT NULL,
            correct_answer TEXT NOT NULL,
            explanation TEXT NOT NULL,
            interesting_reason TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            normalized_question TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (quiz_set_id) REFERENCES daily_quiz_sets(id) ON DELETE CASCADE,
            UNIQUE (quiz_set_id, subject, difficulty)
        );

        CREATE TABLE IF NOT EXISTS daily_quiz_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_date TEXT NOT NULL,
            subject TEXT NOT NULL,
            difficulty TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            provider TEXT NOT NULL,
            generated_json TEXT NOT NULL,
            critic_json TEXT,
            passed INTEGER NOT NULL,
            failure_reason TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_daily_quiz_questions_normalized
        ON daily_quiz_questions (normalized_question);

        CREATE INDEX IF NOT EXISTS idx_daily_quiz_attempts_date
        ON daily_quiz_attempts (quiz_date, subject, difficulty);
        """
    )


def valid_quiz_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError as error:
        raise ValueError("Quiz date must use YYYY-MM-DD format.") from error


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def commit_if_needed(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        conn.commit()


def get_or_create_quiz_set(conn: sqlite3.Connection, quiz_date: str) -> sqlite3.Row:
    conn.execute(
        """
        INSERT OR IGNORE INTO daily_quiz_sets (quiz_date, status)
        VALUES (?, 'generating')
        """,
        (quiz_date,),
    )
    commit_if_needed(conn)
    return conn.execute(
        "SELECT * FROM daily_quiz_sets WHERE quiz_date = ?",
        (quiz_date,),
    ).fetchone()


def set_quiz_status(
    conn: sqlite3.Connection,
    quiz_date: str,
    status: str,
    *,
    failure_reason: str | None = None,
) -> None:
    now = utc_now()
    conn.execute(
        """
        UPDATE daily_quiz_sets
        SET status = ?,
            generated_at = CASE WHEN ? IN ('published', 'failed') THEN ? ELSE generated_at END,
            published_at = CASE WHEN ? = 'published' THEN ? ELSE NULL END,
            failure_reason = ?
        WHERE quiz_date = ?
        """,
        (status, status, now, status, now, failure_reason, quiz_date),
    )
    commit_if_needed(conn)


def recent_questions(
    conn: sqlite3.Connection,
    *,
    subject: str,
    history_days: int,
    exclude_quiz_date: str | None = None,
) -> list[dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=history_days)).isoformat()
    params: list[Any] = [subject, cutoff]
    exclude_sql = ""
    if exclude_quiz_date is not None:
        exclude_sql = "AND daily_quiz_sets.quiz_date != ?"
        params.append(exclude_quiz_date)
    rows = conn.execute(
        f"""
        SELECT daily_quiz_questions.*, daily_quiz_sets.quiz_date
        FROM daily_quiz_questions
        INNER JOIN daily_quiz_sets ON daily_quiz_sets.id = daily_quiz_questions.quiz_set_id
        WHERE daily_quiz_sets.status = 'published'
          AND daily_quiz_questions.subject = ?
          AND daily_quiz_questions.created_at >= ?
          {exclude_sql}
        ORDER BY daily_quiz_questions.created_at DESC
        """,
        params,
    ).fetchall()
    return [question_row(row) for row in rows]


def question_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "subject": row["subject"],
        "difficulty": row["difficulty"],
        "question": row["question"],
        "choices": json.loads(row["choices_json"]),
        "correct_answer": row["correct_answer"],
        "explanation": row["explanation"],
        "interesting_reason": row["interesting_reason"],
        "tags": json.loads(row["tags_json"]),
        "created_at": row["created_at"],
    }


def public_recent_questions(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "question": question["question"],
            "correct_answer": question["correct_answer"],
            "tags": question["tags"],
        }
        for question in questions[:30]
    ]


def quiz_set_questions(conn: sqlite3.Connection, quiz_set_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM daily_quiz_questions
        WHERE quiz_set_id = ?
        ORDER BY id
        """,
        (quiz_set_id,),
    ).fetchall()
    return [question_row(row) for row in rows]


def check_repetition(
    question: dict[str, Any],
    previous_questions: list[dict[str, Any]],
    *,
    reject_any_repeated_answer: bool = False,
) -> RepetitionResult:
    normalized = normalize_text(question["question"])
    correct_answer = normalize_text(question["correct_answer"])
    answer_count = 0
    topic_counts: dict[str, int] = {}
    for previous in previous_questions:
        previous_normalized = normalize_text(previous["question"])
        if normalized == previous_normalized:
            return RepetitionResult(False, "Question duplicates a recent accepted question.")
        if SequenceMatcher(None, normalized, previous_normalized).ratio() >= 0.84:
            return RepetitionResult(False, "Question is too similar to a recent accepted question.")
        if correct_answer == normalize_text(previous["correct_answer"]):
            answer_count += 1
        for tag in previous.get("tags", []):
            clean_tag = normalize_text(str(tag))
            if clean_tag and not is_generic_topic_tag(clean_tag):
                topic_counts[clean_tag] = topic_counts.get(clean_tag, 0) + 1

    if reject_any_repeated_answer and answer_count >= 1:
        return RepetitionResult(False, "Correct answer already appears in this quiz set.")
    if answer_count >= 2:
        return RepetitionResult(False, "Correct answer has already appeared too often recently.")
    for tag in question["tags"]:
        clean_tag = normalize_text(tag)
        if not is_generic_topic_tag(clean_tag) and topic_counts.get(clean_tag, 0) >= 5:
            return RepetitionResult(False, f"Topic tag {tag!r} has appeared too often recently.")
    return RepetitionResult(True, "OK")


def save_attempt(
    conn: sqlite3.Connection,
    *,
    quiz_date: str,
    subject: str,
    difficulty: str,
    attempt_number: int,
    provider: str,
    generated: Any,
    critic: dict[str, Any] | None,
    passed: bool,
    failure_reason: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO daily_quiz_attempts (
            quiz_date, subject, difficulty, attempt_number, provider,
            generated_json, critic_json, passed, failure_reason, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            quiz_date,
            subject,
            difficulty,
            attempt_number,
            provider,
            json.dumps(generated, ensure_ascii=True),
            json.dumps(critic, ensure_ascii=True) if critic is not None else None,
            int(passed),
            failure_reason,
            utc_now(),
        ),
    )
    commit_if_needed(conn)


def save_question(
    conn: sqlite3.Connection,
    *,
    quiz_set_id: int,
    question: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO daily_quiz_questions (
            quiz_set_id, subject, difficulty, question, choices_json,
            correct_answer, explanation, interesting_reason, tags_json,
            normalized_question, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            quiz_set_id,
            question["subject"],
            question["difficulty"],
            question["question"],
            json.dumps(question["choices"]),
            question["correct_answer"],
            question["explanation"],
            question["interesting_reason"],
            json.dumps(question["tags"]),
            normalize_text(question["question"]),
            utc_now(),
        ),
    )
    commit_if_needed(conn)


def critic_failure_reason(critic: dict[str, Any]) -> str:
    reasons = critic.get("failure_reasons")
    if isinstance(reasons, list):
        clean_reasons = [str(reason).strip() for reason in reasons if str(reason).strip()]
        if clean_reasons:
            return "; ".join(clean_reasons)
    return "Critic scores did not meet publication thresholds."


def generate_slot(
    conn: sqlite3.Connection,
    *,
    quiz_set_id: int,
    quiz_date: str,
    subject: str,
    difficulty: str,
    provider: QuizAIProvider,
    config: QuizConfig,
    log: Callable[[str], None],
) -> bool:
    feedback: list[str] = []
    recent = recent_questions(
        conn,
        subject=subject,
        history_days=config.question_history_days,
        exclude_quiz_date=quiz_date,
    )
    for attempt_number in range(1, config.max_attempts_per_slot + 1):
        same_set_questions = quiz_set_questions(conn, quiz_set_id)
        context_questions = [*same_set_questions, *recent]
        log(f"Generating {subject} / {difficulty} attempt {attempt_number}")
        try:
            generated = provider.generate_question(
                subject=subject,
                difficulty=difficulty,
                recent_questions=context_questions,
                feedback=feedback,
            )
            generator_provider_name = current_provider_name(provider)
        except Exception as error:
            reason = f"Generator request failed: {error}"
            save_attempt(
                conn,
                quiz_date=quiz_date,
                subject=subject,
                difficulty=difficulty,
                attempt_number=attempt_number,
                provider=provider.name,
                generated={"error": str(error)},
                critic=None,
                passed=False,
                failure_reason=reason,
            )
            feedback.append(reason)
            log(f"Rejected {subject} / {difficulty} attempt {attempt_number}: {reason}")
            continue

        validation = validate_question(
            generated,
            expected_subject=subject,
            expected_difficulty=difficulty,
        )
        if not validation.passed or validation.question is None:
            save_attempt(
                conn,
                quiz_date=quiz_date,
                subject=subject,
                difficulty=difficulty,
                attempt_number=attempt_number,
                provider=generator_provider_name,
                generated=generated,
                critic=None,
                passed=False,
                failure_reason=validation.reason,
            )
            feedback.append(validation.reason)
            log(f"Rejected {subject} / {difficulty} attempt {attempt_number}: {validation.reason}")
            continue

        same_set_repetition = check_repetition(
            validation.question,
            same_set_questions,
            reject_any_repeated_answer=True,
        )
        repetition = (
            same_set_repetition
            if not same_set_repetition.passed
            else check_repetition(validation.question, recent)
        )
        if not repetition.passed:
            save_attempt(
                conn,
                quiz_date=quiz_date,
                subject=subject,
                difficulty=difficulty,
                attempt_number=attempt_number,
                provider=generator_provider_name,
                generated=validation.question,
                critic=None,
                passed=False,
                failure_reason=repetition.reason,
            )
            feedback.append(repetition.reason)
            log(f"Rejected {subject} / {difficulty} attempt {attempt_number}: {repetition.reason}")
            continue

        try:
            critic = provider.critique_question(
                subject=subject,
                difficulty=difficulty,
                question=validation.question,
                recent_questions=context_questions,
            )
            critic_provider_name = current_provider_name(provider)
        except Exception as error:
            reason = f"Critic request failed: {error}"
            critic_provider_name = current_provider_name(provider)
            save_attempt(
                conn,
                quiz_date=quiz_date,
                subject=subject,
                difficulty=difficulty,
                attempt_number=attempt_number,
                provider=attempt_provider_label(generator_provider_name, critic_provider_name),
                generated=validation.question,
                critic=None,
                passed=False,
                failure_reason=reason,
            )
            feedback.append(reason)
            log(f"Rejected {subject} / {difficulty} attempt {attempt_number}: {reason}")
            continue

        critic_validation = validate_critic(critic)
        if not critic_validation.passed:
            reason = critic_validation.reason
            save_attempt(
                conn,
                quiz_date=quiz_date,
                subject=subject,
                difficulty=difficulty,
                attempt_number=attempt_number,
                provider=attempt_provider_label(generator_provider_name, critic_provider_name),
                generated=validation.question,
                critic=critic,
                passed=False,
                failure_reason=reason,
            )
            feedback.append(reason)
            log(f"Rejected {subject} / {difficulty} attempt {attempt_number}: {reason}")
            continue

        if not critic_passed(critic):
            reason = critic_failure_reason(critic)
            feedback_text = str(critic.get("feedback_to_generator") or reason).strip()
            save_attempt(
                conn,
                quiz_date=quiz_date,
                subject=subject,
                difficulty=difficulty,
                attempt_number=attempt_number,
                provider=attempt_provider_label(generator_provider_name, critic_provider_name),
                generated=validation.question,
                critic=critic,
                passed=False,
                failure_reason=reason,
            )
            feedback.append(feedback_text)
            log(f"Rejected {subject} / {difficulty} attempt {attempt_number}: {reason}")
            continue

        save_question(conn, quiz_set_id=quiz_set_id, question=validation.question)
        save_attempt(
            conn,
            quiz_date=quiz_date,
            subject=subject,
            difficulty=difficulty,
            attempt_number=attempt_number,
            provider=attempt_provider_label(generator_provider_name, critic_provider_name),
            generated=validation.question,
            critic=critic,
            passed=True,
            failure_reason=None,
        )
        log(f"Accepted {subject} / {difficulty} attempt {attempt_number}")
        return True
    return False


def generate_daily_quiz(
    conn: sqlite3.Connection,
    *,
    quiz_date: str,
    config: QuizConfig,
    force: bool = False,
    provider: QuizAIProvider | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    quiz_date = valid_quiz_date(quiz_date)
    initialize_database(conn)
    quiz_set = get_or_create_quiz_set(conn, quiz_date)
    if quiz_set["status"] == "published" and not force:
        return quiz_payload(conn, quiz_date)

    if force:
        conn.execute("DELETE FROM daily_quiz_questions WHERE quiz_set_id = ?", (quiz_set["id"],))
        commit_if_needed(conn)
    set_quiz_status(conn, quiz_date, "generating")

    if provider is None:
        try:
            provider = provider_chain_from_config(config)
        except ValueError:
            reason = (
                f"AI provider {config.provider!r} is not configured, "
                "and no configured fallback provider is available."
            )
            set_quiz_status(conn, quiz_date, "failed", failure_reason=reason)
            return quiz_status(conn, quiz_date)

    log(f"Starting daily quiz generation for {quiz_date} using {provider.name}")
    existing_slots = {
        (row["subject"], row["difficulty"])
        for row in conn.execute(
            "SELECT subject, difficulty FROM daily_quiz_questions WHERE quiz_set_id = ?",
            (quiz_set["id"],),
        )
    }
    for subject, difficulty in REQUIRED_SLOTS:
        if (subject, difficulty) in existing_slots:
            continue
        if not generate_slot(
            conn,
            quiz_set_id=quiz_set["id"],
            quiz_date=quiz_date,
            subject=subject,
            difficulty=difficulty,
            provider=provider,
            config=config,
            log=log,
        ):
            reason = f"Could not generate {subject} / {difficulty} after {config.max_attempts_per_slot} attempts."
            set_quiz_status(conn, quiz_date, "failed", failure_reason=reason)
            log(reason)
            return quiz_status(conn, quiz_date)

    set_quiz_status(conn, quiz_date, "published")
    log(f"Published daily quiz for {quiz_date}")
    return quiz_payload(conn, quiz_date)


def quiz_payload(conn: sqlite3.Connection, quiz_date: str) -> dict[str, Any]:
    quiz_set = conn.execute(
        "SELECT * FROM daily_quiz_sets WHERE quiz_date = ?",
        (valid_quiz_date(quiz_date),),
    ).fetchone()
    if quiz_set is None or quiz_set["status"] != "published":
        raise LookupError("No published quiz exists for that date.")
    rows = conn.execute(
        """
        SELECT *
        FROM daily_quiz_questions
        WHERE quiz_set_id = ?
        ORDER BY CASE subject WHEN 'general_knowledge' THEN 0 ELSE 1 END,
                 CASE difficulty WHEN 'easy' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END
        """,
        (quiz_set["id"],),
    ).fetchall()
    return {
        "date": quiz_set["quiz_date"],
        "status": quiz_set["status"],
        "questions": [
            {
                "id": row["id"],
                "subject": row["subject"],
                "difficulty": row["difficulty"],
                "question": row["question"],
                "choices": json.loads(row["choices_json"]),
                "correct_answer": row["correct_answer"],
                "explanation": row["explanation"],
            }
            for row in rows
        ],
    }


def quiz_status(conn: sqlite3.Connection, quiz_date: str) -> dict[str, Any]:
    quiz_date = valid_quiz_date(quiz_date)
    quiz_set = conn.execute(
        "SELECT * FROM daily_quiz_sets WHERE quiz_date = ?",
        (quiz_date,),
    ).fetchone()
    if quiz_set is None:
        return {
            "date": quiz_date,
            "status": "missing",
            "accepted_questions": 0,
            "failed_attempts": 0,
            "failure_reason": None,
        }
    accepted = conn.execute(
        "SELECT COUNT(*) FROM daily_quiz_questions WHERE quiz_set_id = ?",
        (quiz_set["id"],),
    ).fetchone()[0]
    failed = conn.execute(
        "SELECT COUNT(*) FROM daily_quiz_attempts WHERE quiz_date = ? AND passed = 0",
        (quiz_date,),
    ).fetchone()[0]
    return {
        "date": quiz_date,
        "status": quiz_set["status"],
        "accepted_questions": accepted,
        "failed_attempts": failed,
        "failure_reason": quiz_set["failure_reason"],
    }


def question_attempts(conn: sqlite3.Connection, quiz_date: str) -> dict[str, Any]:
    quiz_date = valid_quiz_date(quiz_date)
    rows = conn.execute(
        """
        SELECT *
        FROM daily_quiz_attempts
        WHERE quiz_date = ?
        ORDER BY id DESC
        """,
        (quiz_date,),
    ).fetchall()
    return {
        "date": quiz_date,
        "attempts": [
            {
                "id": row["id"],
                "subject": row["subject"],
                "difficulty": row["difficulty"],
                "attempt_number": row["attempt_number"],
                "provider": row["provider"],
                "generated": json.loads(row["generated_json"]),
                "critic": json.loads(row["critic_json"]) if row["critic_json"] else None,
                "passed": bool(row["passed"]),
                "failure_reason": row["failure_reason"],
                "created_at": row["created_at"],
            }
            for row in rows
        ],
    }


def publish_quiz(conn: sqlite3.Connection, quiz_date: str) -> dict[str, Any]:
    quiz_date = valid_quiz_date(quiz_date)
    status = quiz_status(conn, quiz_date)
    if status["accepted_questions"] != len(REQUIRED_SLOTS):
        raise ValueError("A quiz can only be published after all six slots are approved.")
    set_quiz_status(conn, quiz_date, "published")
    return quiz_payload(conn, quiz_date)


def regenerate_question(
    conn: sqlite3.Connection,
    *,
    quiz_date: str,
    subject: str,
    difficulty: str,
    config: QuizConfig,
    provider: QuizAIProvider | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    quiz_date = valid_quiz_date(quiz_date)
    if subject not in SUBJECTS or difficulty not in DIFFICULTIES:
        raise ValueError("subject or difficulty is invalid.")
    initialize_database(conn)
    quiz_set = get_or_create_quiz_set(conn, quiz_date)
    if provider is None:
        provider = provider_from_config(config)
    conn.execute(
        """
        DELETE FROM daily_quiz_questions
        WHERE quiz_set_id = ? AND subject = ? AND difficulty = ?
        """,
        (quiz_set["id"], subject, difficulty),
    )
    commit_if_needed(conn)
    set_quiz_status(conn, quiz_date, "generating")
    generated = generate_slot(
        conn,
        quiz_set_id=quiz_set["id"],
        quiz_date=quiz_date,
        subject=subject,
        difficulty=difficulty,
        provider=provider,
        config=config,
        log=log,
    )
    if not generated:
        reason = f"Could not regenerate {subject} / {difficulty}."
        set_quiz_status(conn, quiz_date, "failed", failure_reason=reason)
        return quiz_status(conn, quiz_date)
    status = quiz_status(conn, quiz_date)
    if status["accepted_questions"] == len(REQUIRED_SLOTS):
        set_quiz_status(conn, quiz_date, "published")
    return quiz_status(conn, quiz_date)
