from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import daily_quiz


class EvalGenerator(Protocol):
    name: str

    def generate(self, record: dict[str, Any]) -> Any:
        ...

    def critique(self, record: dict[str, Any], question: dict[str, Any]) -> dict[str, Any] | None:
        ...


@dataclass(frozen=True)
class EvalOptions:
    run_critic: bool = False


class FixtureExpectedGenerator:
    name = "fixture"

    def generate(self, record: dict[str, Any]) -> Any:
        return record["expected_output"]

    def critique(self, record: dict[str, Any], question: dict[str, Any]) -> dict[str, Any] | None:
        return None


class CurrentProviderGenerator:
    name = "current"

    def __init__(self, config: daily_quiz.QuizConfig) -> None:
        self.provider = daily_quiz.provider_chain_from_config(config)

    def generate(self, record: dict[str, Any]) -> Any:
        context = eval_context(record)
        return self.provider.generate_question(
            subject=context["subject"],
            difficulty=context["difficulty"],
            recent_questions=context["recent_questions"],
            feedback=context["feedback"],
        )

    def critique(self, record: dict[str, Any], question: dict[str, Any]) -> dict[str, Any] | None:
        context = eval_context(record)
        return self.provider.critique_question(
            subject=context["subject"],
            difficulty=context["difficulty"],
            question=question,
            recent_questions=context["recent_questions"],
        )


class ConfiguredProviderGenerator:
    def __init__(self, config: daily_quiz.QuizConfig, *, name: str) -> None:
        self.name = name
        self.provider = daily_quiz.provider_chain_from_config(config)

    def generate(self, record: dict[str, Any]) -> Any:
        context = eval_context(record)
        return self.provider.generate_question(
            subject=context["subject"],
            difficulty=context["difficulty"],
            recent_questions=context["recent_questions"],
            feedback=context["feedback"],
        )

    def critique(self, record: dict[str, Any], question: dict[str, Any]) -> dict[str, Any] | None:
        context = eval_context(record)
        return self.provider.critique_question(
            subject=context["subject"],
            difficulty=context["difficulty"],
            question=question,
            recent_questions=context["recent_questions"],
        )


def eval_context(record: dict[str, Any]) -> dict[str, Any]:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    context = record.get("context") if isinstance(record.get("context"), dict) else {}
    subject = str(context.get("subject") or metadata.get("subject") or "")
    difficulty = str(context.get("difficulty") or metadata.get("difficulty") or "")
    recent_questions = context.get("recent_questions")
    feedback = context.get("feedback")
    return {
        "subject": subject,
        "difficulty": difficulty,
        "recent_questions": recent_questions if isinstance(recent_questions, list) else [],
        "feedback": feedback if isinstance(feedback, list) else [],
    }


def load_jsonl(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            record = json.loads(stripped)
            if not isinstance(record, dict):
                raise ValueError(f"Line {line_number} is not a JSON object.")
            records.append(record)
            if limit is not None and len(records) >= limit:
                break
    return records


def coerce_generated(value: Any) -> tuple[dict[str, Any] | None, bool, str | None]:
    if isinstance(value, dict):
        return value, True, None
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            return None, False, f"Generated output is not valid JSON: {error}"
        if isinstance(parsed, dict):
            return parsed, True, None
        return None, True, "Generated JSON is not an object."
    return None, False, f"Generated output has unsupported type: {type(value).__name__}."


def empty_metrics() -> dict[str, Any]:
    return {
        "total": 0,
        "generated": 0,
        "valid_json": 0,
        "validation_passed": 0,
        "subject_match": 0,
        "difficulty_match": 0,
        "repetition_passed": 0,
        "critic_evaluated": 0,
        "critic_passed": 0,
        "publishable": 0,
        "failures": 0,
        "by_slot": {},
    }


def increment_slot(metrics: dict[str, Any], subject: str, difficulty: str, key: str) -> None:
    slot = f"{subject}/{difficulty}"
    by_slot = metrics["by_slot"]
    if slot not in by_slot:
        by_slot[slot] = {
            "total": 0,
            "validation_passed": 0,
            "repetition_passed": 0,
            "critic_passed": 0,
            "publishable": 0,
        }
    by_slot[slot][key] += 1


def evaluate_record(
    record: dict[str, Any],
    generator: EvalGenerator,
    options: EvalOptions,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    context = eval_context(record)
    subject = context["subject"]
    difficulty = context["difficulty"]
    metrics_delta = empty_metrics()
    metrics_delta["total"] = 1
    increment_slot(metrics_delta, subject, difficulty, "total")
    metadata = record.get("metadata", {})

    failure: dict[str, Any] | None = None
    try:
        raw_generated = generator.generate(record)
        metrics_delta["generated"] = 1
    except Exception as error:
        failure = {
            "stage": "generation",
            "metadata": metadata,
            "reason": str(error),
        }
        metrics_delta["failures"] = 1
        return metrics_delta, failure

    generated, valid_json, json_error = coerce_generated(raw_generated)
    if valid_json:
        metrics_delta["valid_json"] = 1
    if generated is None:
        failure = {
            "stage": "json",
            "metadata": metadata,
            "reason": json_error or "Generated output could not be parsed.",
            "generated": raw_generated,
        }
        metrics_delta["failures"] = 1
        return metrics_delta, failure

    if str(generated.get("subject") or "") == subject:
        metrics_delta["subject_match"] = 1
    if str(generated.get("difficulty") or "") == difficulty:
        metrics_delta["difficulty_match"] = 1

    validation = daily_quiz.validate_question(
        generated,
        expected_subject=subject,
        expected_difficulty=difficulty,
    )
    if not validation.passed or validation.question is None:
        failure = {
            "stage": "validation",
            "metadata": metadata,
            "reason": validation.reason,
            "generated": generated,
        }
        metrics_delta["failures"] = 1
        return metrics_delta, failure

    metrics_delta["validation_passed"] = 1
    increment_slot(metrics_delta, subject, difficulty, "validation_passed")
    repetition = daily_quiz.check_repetition(
        validation.question,
        context["recent_questions"],
    )
    if not repetition.passed:
        failure = {
            "stage": "repetition",
            "metadata": metadata,
            "reason": repetition.reason,
            "generated": generated,
        }
        metrics_delta["failures"] = 1
        return metrics_delta, failure

    metrics_delta["repetition_passed"] = 1
    increment_slot(metrics_delta, subject, difficulty, "repetition_passed")
    if options.run_critic:
        metrics_delta["critic_evaluated"] = 1
        try:
            critic = generator.critique(record, validation.question)
        except Exception as error:
            failure = {
                "stage": "critic",
                "metadata": metadata,
                "reason": str(error),
                "generated": generated,
            }
            metrics_delta["failures"] = 1
            return metrics_delta, failure
        critic_validation = daily_quiz.validate_critic(critic)
        if not critic_validation.passed or not critic or not daily_quiz.critic_passed(critic):
            failure = {
                "stage": "critic",
                "metadata": metadata,
                "reason": (
                    critic_validation.reason
                    if not critic_validation.passed
                    else daily_quiz.critic_failure_reason(critic)
                ),
                "generated": generated,
                "critic": critic,
            }
            metrics_delta["failures"] = 1
            return metrics_delta, failure
        metrics_delta["critic_passed"] = 1
        increment_slot(metrics_delta, subject, difficulty, "critic_passed")

    metrics_delta["publishable"] = 1
    increment_slot(metrics_delta, subject, difficulty, "publishable")
    return metrics_delta, None


def merge_metrics(target: dict[str, Any], delta: dict[str, Any]) -> None:
    for key, value in delta.items():
        if key == "by_slot":
            for slot, slot_delta in value.items():
                if slot not in target["by_slot"]:
                    target["by_slot"][slot] = dict(slot_delta)
                else:
                    for slot_key, slot_value in slot_delta.items():
                        target["by_slot"][slot][slot_key] += slot_value
        elif isinstance(value, int):
            target[key] += value


def add_rates(metrics: dict[str, Any]) -> dict[str, Any]:
    total = max(int(metrics["total"]), 1)
    with_rates = dict(metrics)
    with_rates["rates"] = {
        "valid_json": metrics["valid_json"] / total,
        "validation_passed": metrics["validation_passed"] / total,
        "repetition_passed": metrics["repetition_passed"] / total,
        "publishable": metrics["publishable"] / total,
    }
    for slot_metrics in with_rates["by_slot"].values():
        slot_total = max(int(slot_metrics["total"]), 1)
        slot_metrics["rates"] = {
            "validation_passed": slot_metrics["validation_passed"] / slot_total,
            "repetition_passed": slot_metrics["repetition_passed"] / slot_total,
            "publishable": slot_metrics["publishable"] / slot_total,
        }
    return with_rates


def evaluate_records(
    records: list[dict[str, Any]],
    generator: EvalGenerator,
    options: EvalOptions | None = None,
) -> dict[str, Any]:
    options = options or EvalOptions()
    metrics = empty_metrics()
    failures: list[dict[str, Any]] = []
    for record in records:
        delta, failure = evaluate_record(record, generator, options)
        merge_metrics(metrics, delta)
        if failure is not None:
            failures.append(failure)
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": generator.name,
        "critic_enabled": options.run_critic,
        "metrics": add_rates(metrics),
        "failures": failures,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate quiz generator output against held-out quiz eval JSONL.",
    )
    parser.add_argument("--eval-file", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--provider",
        choices=("fixture", "current", "openai-compatible"),
        default="fixture",
        help="fixture replays expected outputs; current calls env config; openai-compatible calls a supplied candidate model.",
    )
    parser.add_argument("--base-url", default="https://api.openai.com/v1")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--generator-model")
    parser.add_argument("--critic-model")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--with-critic",
        action="store_true",
        help="Also run the configured critic. This may double API calls in current mode.",
    )
    return parser.parse_args()


def generator_from_args(args: argparse.Namespace) -> EvalGenerator:
    if args.provider == "fixture":
        return FixtureExpectedGenerator()
    if args.provider == "current":
        return CurrentProviderGenerator(daily_quiz.QuizConfig.from_env())
    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        raise ValueError(f"{args.api_key_env} is not configured.")
    if not args.generator_model:
        raise ValueError("--generator-model is required for openai-compatible evals.")
    critic_model = args.critic_model or args.generator_model
    return ConfiguredProviderGenerator(
        replace(
            daily_quiz.QuizConfig.from_env(),
            provider="openai-compatible",
            generator_model=args.generator_model,
            critic_model=critic_model,
            compatible_api_key=api_key,
            compatible_base_url=args.base_url,
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
        ),
        name=f"openai-compatible:{args.generator_model}",
    )


def main() -> int:
    args = parse_args()
    records = load_jsonl(args.eval_file, limit=args.limit)
    report = evaluate_records(
        records,
        generator_from_args(args),
        EvalOptions(run_critic=bool(args.with_critic)),
    )
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0 if report["metrics"]["failures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
