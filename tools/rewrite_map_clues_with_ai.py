from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import daily_map_game
import daily_quiz
from tools import map_clue_failure_log

DEFAULT_DB_PATH = PROJECT_DIR / "data" / "fultons.db"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "data" / "training"
DEFAULT_ENV_FILE = PROJECT_DIR / ".env.local"
DEFAULT_FAILURE_LOG_PATH = map_clue_failure_log.DEFAULT_FAILURE_LOG_PATH
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
DEFAULT_MAP_GEMINI_GENERATOR_MODEL = "gemini-3.1-flash-lite"
DEFAULT_MAP_GEMINI_CRITIC_MODEL = "gemini-3.1-flash-lite"
DEFAULT_MAP_GEMINI_FALLBACK_MODELS = ("gemini-2.5-flash-lite",)
DEFAULT_PROVIDER_RETRY_AFTER_MINUTES = 30
CRITIC_MODES = ("local", "ai")


def provider_failure_is_deferred(reason: str) -> bool:
    normalized = reason.casefold()
    return any(
        token in normalized
        for token in (
            "http 429",
            "rate limit",
            "rate_limit",
            "quota",
            "timed out",
            "timeout",
            "temporarily unavailable",
            "connection",
            "socket",
            "winerror 10013",
        )
    )


def load_env_file(path: Path, *, override: bool = False) -> dict[str, str]:
    loaded: dict[str, str] = {}
    if not path.exists():
        return loaded
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if not name:
            continue
        if override or not os.environ.get(name):
            os.environ[name] = value
            loaded[name] = value
    return loaded


def map_clue_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "hard": {"type": "string"},
            "medium": {"type": "string"},
            "easy": {"type": "string"},
            "reveal": {"type": "string"},
        },
        "required": list(daily_map_game.MAP_CLUE_REQUIRED_FIELDS),
    }


def map_clue_critic_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "passed": {"type": "boolean"},
            "scores": {
                "type": "object",
                "properties": {
                    score: {"type": "integer", "minimum": 0, "maximum": 10}
                    for score in daily_map_game.MAP_CLUE_CRITIC_THRESHOLDS
                },
                "required": list(daily_map_game.MAP_CLUE_CRITIC_THRESHOLDS),
            },
            "failure_reasons": {"type": "array", "items": {"type": "string"}},
            "feedback_to_generator": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["passed", "scores", "failure_reasons", "feedback_to_generator"],
    }


@dataclass(frozen=True)
class ProviderClient:
    provider: Any
    config: daily_quiz.QuizConfig


class ConfiguredMapClueProvider:
    def __init__(self, clients: list[ProviderClient]) -> None:
        if not clients:
            raise ValueError("No configured AI providers are available for map clue rewriting.")
        self.clients = clients
        self.name = " -> ".join(dict.fromkeys(client.provider.name for client in clients))
        self.last_provider_name = clients[0].provider.name

    @classmethod
    def from_env(
        cls,
        *,
        generator_model: str = "",
        critic_model: str = "",
    ) -> "ConfiguredMapClueProvider":
        config = daily_quiz.QuizConfig.from_env()
        if config.provider == "gemini":
            map_gemini_api_key = os.environ.get("MAP_CLUE_GEMINI_API_KEY", "").strip()
            map_generator_model = (
                generator_model.strip()
                or os.environ.get("MAP_CLUE_GENERATOR_MODEL", "").strip()
                or DEFAULT_MAP_GEMINI_GENERATOR_MODEL
            )
            map_critic_model = (
                critic_model.strip()
                or os.environ.get("MAP_CLUE_CRITIC_MODEL", "").strip()
                or DEFAULT_MAP_GEMINI_CRITIC_MODEL
            )
            config = replace(
                config,
                gemini_api_key=map_gemini_api_key or config.gemini_api_key,
                generator_model=map_generator_model,
                critic_model=map_critic_model,
            )
        clients: list[ProviderClient] = []
        seen: set[tuple[str, str, str, str, str, str]] = set()
        for stage in (0, 1, 2):
            candidate = daily_quiz.configured_provider_config(config, stage=stage)
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
            if signature in seen:
                continue
            seen.add(signature)
            clients.append(ProviderClient(daily_quiz.provider_from_config(candidate), candidate))
        if config.provider == "gemini" and config.gemini_api_key:
            for model in DEFAULT_MAP_GEMINI_FALLBACK_MODELS:
                candidate = replace(
                    config,
                    provider="gemini",
                    generator_model=model,
                    critic_model=model,
                )
                signature = (
                    candidate.provider,
                    candidate.generator_model,
                    candidate.critic_model,
                    candidate.gemini_api_key,
                    candidate.compatible_api_key,
                    candidate.compatible_base_url,
                )
                if signature in seen:
                    continue
                seen.add(signature)
                clients.append(
                    ProviderClient(daily_quiz.provider_from_config(candidate), candidate)
                )
        openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if openai_key:
            model = (
                os.environ.get("AI_GENERATOR_MODEL", "").strip()
                or os.environ.get("FULTONS_OPENAI_MODEL", "").strip()
                or DEFAULT_OPENAI_MODEL
            )
            critic_model = (
                os.environ.get("AI_CRITIC_MODEL", "").strip()
                or os.environ.get("FULTONS_OPENAI_MODEL", "").strip()
                or model
            )
            candidate = replace(
                config,
                provider="openai-compatible",
                generator_model=model,
                critic_model=critic_model,
                compatible_api_key=openai_key,
                compatible_base_url=daily_quiz.default_compatible_base_url(
                    "openai-compatible",
                    os.environ.get("AI_BASE_URL", ""),
                ),
            )
            signature = (
                candidate.provider,
                candidate.generator_model,
                candidate.critic_model,
                candidate.gemini_api_key,
                candidate.compatible_api_key,
                candidate.compatible_base_url,
            )
            if signature not in seen:
                clients.append(ProviderClient(daily_quiz.provider_from_config(candidate), candidate))
        return cls(clients)

    def model_summary(self) -> list[dict[str, str]]:
        return [
            {
                "provider": client.provider.name,
                "generator_model": client.config.generator_model,
                "critic_model": client.config.critic_model,
            }
            for client in self.clients
        ]

    def request_json(
        self,
        client: ProviderClient,
        *,
        model: str,
        prompt: str,
        schema: dict[str, Any],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        provider = client.provider
        self.last_provider_name = provider.name
        if isinstance(provider, daily_quiz.GeminiProvider):
            return provider._request(model, prompt, schema, tools=tools)
        if tools:
            raise RuntimeError(
                f"{provider.name} does not support the grounded tools required by this request."
            )
        return provider._request(model, prompt)

    def call_with_fallback(
        self,
        *,
        model_attr: str,
        prompt: str,
        schema: dict[str, Any],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        errors: list[str] = []
        for client in self.clients:
            model = getattr(client.config, model_attr)
            try:
                return self.request_json(
                    client,
                    model=model,
                    prompt=prompt,
                    schema=schema,
                    tools=tools,
                )
            except Exception as error:
                errors.append(f"{client.provider.name}: {error}")
                continue
        raise RuntimeError(f"All AI providers failed for map clue rewrite: {' | '.join(errors)}")

    def generate_clue_ladder(
        self,
        *,
        place: dict[str, Any],
        recent_places: list[dict[str, Any]],
        feedback: list[str],
    ) -> dict[str, Any]:
        return self.call_with_fallback(
            model_attr="generator_model",
            prompt=daily_map_game.map_clue_generator_prompt(place, recent_places, feedback),
            schema=map_clue_json_schema(),
        )

    def critique_clue_ladder(
        self,
        *,
        place: dict[str, Any],
        clue_ladder: dict[str, Any],
        recent_places: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self.call_with_fallback(
            model_attr="critic_model",
            prompt=daily_map_game.map_clue_critic_prompt(place, clue_ladder, recent_places),
            schema=map_clue_critic_json_schema(),
        )


def connect_database(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def candidate_rows(
    conn: sqlite3.Connection,
    *,
    difficulty: str | None = None,
    place_type: str | None = None,
    include_clean: bool = False,
    limit: int = 10,
    scan_limit: int = 3000,
    exclude_place_ids: set[int] | None = None,
) -> list[sqlite3.Row]:
    clauses = [
        "active = 1",
        "clue_text <> ''",
        "reveal_text <> ''",
    ]
    params: list[Any] = []
    excluded = sorted({int(place_id) for place_id in (exclude_place_ids or set())})
    if excluded:
        placeholders = ", ".join("?" for _ in excluded)
        clauses.append(f"id NOT IN ({placeholders})")
        params.extend(excluded)
    if difficulty:
        clauses.append("difficulty = ?")
        params.append(difficulty)
    if place_type:
        clauses.append("place_type = ?")
        params.append(place_type)
    params.append(max(1, scan_limit))
    rows = conn.execute(
        f"""
        SELECT *
        FROM map_place_pool
        WHERE {' AND '.join(clauses)}
        ORDER BY validation_grade DESC NULLS LAST, canonical_name COLLATE NOCASE
        LIMIT ?
        """,
        params,
    ).fetchall()
    selected: list[sqlite3.Row] = []
    for row in rows:
        if include_clean or not daily_map_game.row_passes_map_clue_quality(row):
            selected.append(row)
            if len(selected) >= limit:
                break
    return selected


def summarize_attempts(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for attempt in attempts:
        critic = attempt.get("critic") if isinstance(attempt.get("critic"), dict) else {}
        local_critic = attempt.get("local_critic") if isinstance(attempt.get("local_critic"), dict) else None
        summary.append(
            {
                "generated": attempt.get("generated"),
                "critic_source": attempt.get("critic_source") or "ai",
                "passed": bool(critic.get("passed")),
                "failure_reasons": critic.get("failure_reasons") or [],
                "feedback_to_generator": critic.get("feedback_to_generator") or [],
                "local_passed": bool(local_critic.get("passed")) if local_critic else None,
            }
        )
    return summary


def rewrite_map_clues(
    conn: sqlite3.Connection,
    *,
    provider: daily_map_game.MapClueProvider,
    limit: int = 10,
    dry_run: bool = True,
    difficulty: str | None = None,
    place_type: str | None = None,
    include_clean: bool = False,
    learning_profile_path: str = "",
    stop_on_provider_error: bool = True,
    retry_after_minutes: int = DEFAULT_PROVIDER_RETRY_AFTER_MINUTES,
    exclude_place_ids: set[int] | None = None,
    critic_mode: str = "ai",
    max_attempts_per_place: int | None = None,
) -> dict[str, Any]:
    daily_map_game.initialize_database(conn)
    rows = candidate_rows(
        conn,
        difficulty=difficulty,
        place_type=place_type,
        include_clean=include_clean,
        limit=limit,
        exclude_place_ids=exclude_place_ids,
    )
    config = daily_map_game.MapClueConfig(
        learning_profile_path=learning_profile_path or daily_map_game.DEFAULT_MAP_LEARNING_PROFILE_PATH,
        max_attempts_per_place=max(1, max_attempts_per_place or daily_map_game.MapClueConfig().max_attempts_per_place),
        require_ai_critic=critic_mode == "ai",
    )
    results: list[dict[str, Any]] = []
    accepted = 0
    rejected = 0
    deferred = 0
    processed = 0
    for row in rows:
        before = daily_map_game.clue_ladder_dict_for_row(row)
        try:
            result = daily_map_game.generate_reviewed_clue_ladder(
                conn,
                place_id=row["id"],
                provider=provider,
                config=config,
                save=not dry_run,
            )
        except Exception as error:
            reason = str(error)
            if provider_failure_is_deferred(reason):
                deferred += 1
                results.append(
                    {
                        "place_id": row["id"],
                        "place": row["canonical_name"],
                        "status": "deferred",
                        "retryable": True,
                        "retry_after_minutes": retry_after_minutes,
                        "error": reason,
                        "before": before,
                    }
                )
                if stop_on_provider_error:
                    break
                continue
            rejected += 1
            results.append(
                {
                    "place_id": row["id"],
                    "place": row["canonical_name"],
                    "status": "error",
                    "error": str(error),
                    "before": before,
                }
            )
            continue
        processed += 1
        if result["status"] == "accepted":
            accepted += 1
        else:
            rejected += 1
        results.append(
            {
                "place_id": row["id"],
                "place": row["canonical_name"],
                "place_type": row["place_type"],
                "difficulty": row["difficulty"],
                "status": result["status"],
                "saved": bool(result.get("saved")),
                "critic_mode": result.get("critic_mode") or critic_mode,
                "before": before,
                "after": result.get("clue_ladder"),
                "attempts": summarize_attempts(result.get("attempts") or []),
            }
        )
        if not dry_run:
            conn.commit()
    if dry_run:
        conn.rollback()
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider.name,
        "provider_models": provider.model_summary() if hasattr(provider, "model_summary") else None,
        "dry_run": dry_run,
        "critic_mode": critic_mode,
        "learning_profile_path": learning_profile_path,
        "candidate_count": len(rows),
        "processed_count": processed,
        "accepted_count": accepted,
        "rejected_count": rejected,
        "deferred_count": deferred,
        "retry_after_minutes": retry_after_minutes if deferred else None,
        "stopped_on_provider_error": bool(deferred and stop_on_provider_error),
        "results": results,
    }


def write_report(report: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = output_dir / f"map_clue_ai_rewrite_report_{stamp}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    return path


def run_rewrite_attempt(
    *,
    db_path: Path,
    provider: daily_map_game.MapClueProvider,
    output_dir: Path,
    limit: int,
    dry_run: bool,
    difficulty: str | None,
    place_type: str | None,
    include_clean: bool,
    learning_profile_path: str,
    stop_on_provider_error: bool,
    retry_after_minutes: int,
    exclude_place_ids: set[int] | None = None,
    critic_mode: str = "ai",
    max_attempts_per_place: int | None = None,
    failure_log_path: Path | None = None,
) -> dict[str, Any]:
    conn = connect_database(db_path)
    try:
        report = rewrite_map_clues(
            conn,
            provider=provider,
            limit=limit,
            dry_run=dry_run,
            difficulty=difficulty,
            place_type=place_type,
            include_clean=include_clean,
            learning_profile_path=learning_profile_path,
            stop_on_provider_error=stop_on_provider_error,
            retry_after_minutes=retry_after_minutes,
            exclude_place_ids=exclude_place_ids,
            critic_mode=critic_mode,
            max_attempts_per_place=max_attempts_per_place,
        )
    finally:
        conn.close()
    report_path = write_report(report, output_dir)
    failure_log_count = 0
    if failure_log_path is not None:
        failure_records = map_clue_failure_log.failure_records_from_rewrite_report(
            report,
            report_path=str(report_path),
        )
        failure_log_count = map_clue_failure_log.append_failure_records(failure_log_path, failure_records)
    return {
        "report_path": str(report_path),
        "failure_log_path": str(failure_log_path) if failure_log_path is not None else None,
        "failure_log_count": failure_log_count,
        **report,
    }


def run_until_processed(
    *,
    db_path: Path,
    provider: daily_map_game.MapClueProvider,
    output_dir: Path,
    limit: int,
    dry_run: bool,
    difficulty: str | None,
    place_type: str | None,
    include_clean: bool,
    learning_profile_path: str,
    stop_on_provider_error: bool,
    retry_after_minutes: int,
    retry_sleep_minutes: int,
    max_retry_attempts: int,
    critic_mode: str,
    max_attempts_per_place: int | None,
    failure_log_path: Path | None = None,
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    collected_results: list[dict[str, Any]] = []
    completed_place_ids: set[int] = set()
    target_limit = max(1, limit)
    attempt_number = 0
    while True:
        attempt_number += 1
        remaining_limit = max(1, target_limit - len(completed_place_ids))
        attempt = run_rewrite_attempt(
            db_path=db_path,
            provider=provider,
            output_dir=output_dir,
            limit=remaining_limit,
            dry_run=dry_run,
            difficulty=difficulty,
            place_type=place_type,
            include_clean=include_clean,
            learning_profile_path=learning_profile_path,
            stop_on_provider_error=stop_on_provider_error,
            retry_after_minutes=retry_after_minutes,
            exclude_place_ids=completed_place_ids,
            critic_mode=critic_mode,
            max_attempts_per_place=max_attempts_per_place,
            failure_log_path=failure_log_path,
        )
        for result in attempt.get("results", []):
            if result.get("status") == "deferred":
                continue
            place_id = int(result["place_id"])
            if place_id in completed_place_ids:
                continue
            completed_place_ids.add(place_id)
            collected_results.append(result)
        attempts.append(
            {
                "attempt": attempt_number,
                "created_at": attempt["created_at"],
                "report_path": attempt["report_path"],
                "candidate_count": attempt["candidate_count"],
                "remaining_before_attempt": remaining_limit,
                "processed_count": attempt["processed_count"],
                "accepted_count": attempt["accepted_count"],
                "rejected_count": attempt["rejected_count"],
                "deferred_count": attempt["deferred_count"],
                "stopped_on_provider_error": attempt["stopped_on_provider_error"],
                "failure_log_count": attempt["failure_log_count"],
            }
        )
        print(json.dumps(attempts[-1], ensure_ascii=True), flush=True)
        if len(completed_place_ids) >= target_limit or int(attempt["deferred_count"]) == 0:
            break
        if max_retry_attempts > 0 and attempt_number >= max_retry_attempts:
            break
        time.sleep(max(1, retry_sleep_minutes) * 60)

    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider.name,
        "provider_models": provider.model_summary() if hasattr(provider, "model_summary") else None,
        "dry_run": dry_run,
        "critic_mode": critic_mode,
        "target_limit": limit,
        "retry_until_processed": True,
        "retry_sleep_minutes": retry_sleep_minutes,
        "max_retry_attempts": max_retry_attempts,
        "attempt_count": len(attempts),
        "completed": bool(len(completed_place_ids) >= target_limit or (attempts and attempts[-1]["deferred_count"] == 0)),
        "collected_count": len(collected_results),
        "accepted_count": sum(1 for result in collected_results if result.get("status") == "accepted"),
        "rejected_count": sum(1 for result in collected_results if result.get("status") != "accepted"),
        "failure_log_path": str(failure_log_path) if failure_log_path is not None else None,
        "failure_log_count": sum(int(attempt.get("failure_log_count") or 0) for attempt in attempts),
        "attempts": attempts,
        "results": collected_results,
        "latest_report_path": attempts[-1]["report_path"] if attempts else None,
    }
    summary_path = write_report(
        {"kind": "map_clue_ai_rewrite_retry_summary", **summary},
        output_dir,
    )
    return {"summary_path": str(summary_path), **summary}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Use the configured AI provider to rewrite weak map clue ladders, saving only critic-approved results.",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--save", action="store_true", help="Persist accepted rewrites. Default is dry-run.")
    parser.add_argument("--difficulty", choices=daily_map_game.DIFFICULTIES)
    parser.add_argument("--place-type")
    parser.add_argument("--include-clean", action="store_true")
    parser.add_argument("--learning-profile-path", default="")
    parser.add_argument(
        "--critic-mode",
        choices=CRITIC_MODES,
        default="local",
        help="Use local validation only for bulk rewrites, or also require the configured AI critic.",
    )
    parser.add_argument(
        "--generator-model",
        default="",
        help=f"Override the map clue generator model. Gemini defaults to {DEFAULT_MAP_GEMINI_GENERATOR_MODEL}.",
    )
    parser.add_argument(
        "--critic-model",
        default="",
        help=f"Override the map clue critic model. Gemini defaults to {DEFAULT_MAP_GEMINI_CRITIC_MODEL}.",
    )
    parser.add_argument(
        "--max-attempts-per-place",
        type=int,
        default=2,
        help="Maximum generation attempts per place for this rewrite run.",
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument(
        "--failure-log-path",
        type=Path,
        default=DEFAULT_FAILURE_LOG_PATH,
        help="Append rejected/deferred attempt records to this JSONL learning log.",
    )
    parser.add_argument(
        "--no-failure-log",
        action="store_true",
        help="Do not append rewrite failures to the learning log.",
    )
    parser.add_argument("--override-env", action="store_true")
    parser.add_argument("--timeout-sec", type=int, help="Override AI_TIMEOUT_SEC for this run.")
    parser.add_argument("--request-delay-sec", type=float, help="Override AI_REQUEST_DELAY_SEC for this run.")
    parser.add_argument("--transient-retries", type=int, help="Override AI_TRANSIENT_RETRIES for this run.")
    parser.add_argument(
        "--continue-on-provider-error",
        action="store_true",
        help="Continue through candidates after timeout/rate-limit provider errors. Default stops the batch.",
    )
    parser.add_argument(
        "--retry-after-minutes",
        type=int,
        default=DEFAULT_PROVIDER_RETRY_AFTER_MINUTES,
        help="Advisory retry window written to deferred reports.",
    )
    parser.add_argument(
        "--retry-until-processed",
        action="store_true",
        help="Keep retrying after provider deferrals until a batch processes or max retry attempts is reached.",
    )
    parser.add_argument(
        "--retry-sleep-minutes",
        type=int,
        default=60,
        help="Sleep interval between retry-until-processed attempts.",
    )
    parser.add_argument(
        "--max-retry-attempts",
        type=int,
        default=0,
        help="Maximum retry-until-processed attempts. 0 means no limit.",
    )
    return parser.parse_args()


def apply_runtime_env_overrides(args: argparse.Namespace) -> None:
    if args.timeout_sec is not None:
        os.environ["AI_TIMEOUT_SEC"] = str(max(5, args.timeout_sec))
    if args.request_delay_sec is not None:
        os.environ["AI_REQUEST_DELAY_SEC"] = str(max(0.0, args.request_delay_sec))
    if args.transient_retries is not None:
        os.environ["AI_TRANSIENT_RETRIES"] = str(max(0, args.transient_retries))


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"Database not found: {args.db}")
    load_env_file(args.env_file, override=args.override_env)
    apply_runtime_env_overrides(args)
    try:
        provider = ConfiguredMapClueProvider.from_env(
            generator_model=args.generator_model,
            critic_model=args.critic_model,
        )
    except ValueError as error:
        raise SystemExit(
            f"{error} Configure GEMINI_API_KEY, or set AI_PROVIDER=openai-compatible with AI_API_KEY and AI_BASE_URL."
        ) from error
    if args.retry_until_processed:
        failure_log_path = None if args.no_failure_log else args.failure_log_path
        summary = run_until_processed(
            db_path=args.db,
            provider=provider,
            output_dir=args.out_dir,
            limit=args.limit,
            dry_run=not args.save,
            difficulty=args.difficulty,
            place_type=args.place_type,
            include_clean=args.include_clean,
            learning_profile_path=args.learning_profile_path,
            stop_on_provider_error=not args.continue_on_provider_error,
            retry_after_minutes=args.retry_after_minutes,
            retry_sleep_minutes=args.retry_sleep_minutes,
            max_retry_attempts=args.max_retry_attempts,
            critic_mode=args.critic_mode,
            max_attempts_per_place=args.max_attempts_per_place,
            failure_log_path=failure_log_path,
        )
        print(
            json.dumps(
                {
                    "summary_path": summary["summary_path"],
                    "latest_report_path": summary["latest_report_path"],
                    "provider": summary["provider"],
                    "provider_models": summary["provider_models"],
                    "dry_run": summary["dry_run"],
                    "critic_mode": summary["critic_mode"],
                    "attempt_count": summary["attempt_count"],
                    "completed": summary["completed"],
                    "collected_count": summary["collected_count"],
                    "accepted_count": summary["accepted_count"],
                    "failure_log_path": summary["failure_log_path"],
                    "failure_log_count": summary["failure_log_count"],
                },
                indent=2,
                ensure_ascii=True,
            )
        )
        return 0

    report = run_rewrite_attempt(
        db_path=args.db,
        provider=provider,
        output_dir=args.out_dir,
        limit=args.limit,
        dry_run=not args.save,
        difficulty=args.difficulty,
        place_type=args.place_type,
        include_clean=args.include_clean,
        learning_profile_path=args.learning_profile_path,
        stop_on_provider_error=not args.continue_on_provider_error,
        retry_after_minutes=args.retry_after_minutes,
        critic_mode=args.critic_mode,
        max_attempts_per_place=args.max_attempts_per_place,
        failure_log_path=None if args.no_failure_log else args.failure_log_path,
    )
    print(
        json.dumps(
            {
                "report_path": report["report_path"],
                "provider": report["provider"],
                "provider_models": report["provider_models"],
                "dry_run": report["dry_run"],
                "critic_mode": report["critic_mode"],
                "candidate_count": report["candidate_count"],
                "processed_count": report["processed_count"],
                "accepted_count": report["accepted_count"],
                "rejected_count": report["rejected_count"],
                "deferred_count": report["deferred_count"],
                "retry_after_minutes": report["retry_after_minutes"],
                "stopped_on_provider_error": report["stopped_on_provider_error"],
                "failure_log_path": report["failure_log_path"],
                "failure_log_count": report["failure_log_count"],
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
