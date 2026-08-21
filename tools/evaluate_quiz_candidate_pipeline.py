from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import statistics
import sys
import time
from dataclasses import replace
from datetime import date, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import daily_quiz

DEFAULT_DB_PATH = PROJECT_DIR / "data" / "fultons.db"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "data" / "qa" / "quiz-candidate-shadow"
STATE_FILENAME = "state.json"


def provider_capacity_exhausted(messages: list[str]) -> bool:
    text = "\n".join(messages[-20:]).casefold()
    return "all ai providers failed" in text and any(
        marker in text
        for marker in (
            "free-models-per-day",
            "free_tier_requests",
            "resource_exhausted",
            "quota exceeded",
        )
    )


def load_elapsed_state(path: Path, *, resume: bool) -> dict[str, float]:
    if not resume or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    values = payload.get("active_elapsed_seconds") if isinstance(payload, dict) else None
    if not isinstance(values, dict):
        return {}
    return {
        str(key): max(0.0, float(value))
        for key, value in values.items()
        if isinstance(value, (int, float))
    }


def save_elapsed_state(path: Path, values: dict[str, float]) -> None:
    path.write_text(
        json.dumps({"active_elapsed_seconds": values}, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )


def copy_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    source_conn = sqlite3.connect(source)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()


def shadow_dates(start_date: str, count: int) -> list[str]:
    start = date.fromisoformat(start_date)
    return [(start + timedelta(days=offset)).isoformat() for offset in range(count)]


def generation_call_count(conn: sqlite3.Connection, quiz_date: str) -> int:
    return daily_quiz.candidate_generation_call_count(conn, quiz_date)


def answer_collisions(conn: sqlite3.Connection, quiz_date: str, embargo_days: int) -> int:
    target = date.fromisoformat(quiz_date)
    cutoff = (target - timedelta(days=embargo_days)).isoformat()
    rows = conn.execute(
        """
        SELECT q.subject, lower(trim(q.correct_answer)) AS answer,
               SUM(CASE WHEN s.quiz_date = ? THEN 1 ELSE 0 END) AS target_count,
               SUM(CASE WHEN s.quiz_date < ? THEN 1 ELSE 0 END) AS prior_count
        FROM daily_quiz_questions q
        JOIN daily_quiz_sets s ON s.id = q.quiz_set_id
        WHERE s.status = 'published' AND s.quiz_date BETWEEN ? AND ?
        GROUP BY q.subject, lower(trim(q.correct_answer))
        """,
        (quiz_date, quiz_date, cutoff, quiz_date),
    ).fetchall()
    return sum(
        1 for row in rows if int(row["target_count"] or 0) and int(row["prior_count"] or 0)
    )


def question_collisions(conn: sqlite3.Connection, quiz_date: str, history_days: int) -> int:
    target = date.fromisoformat(quiz_date)
    cutoff = (target - timedelta(days=history_days)).isoformat()
    current = conn.execute(
        """
        SELECT q.subject, q.normalized_question FROM daily_quiz_questions q
        JOIN daily_quiz_sets s ON s.id=q.quiz_set_id WHERE s.quiz_date=?
        """,
        (quiz_date,),
    ).fetchall()
    prior = conn.execute(
        """
        SELECT q.subject, q.normalized_question FROM daily_quiz_questions q
        JOIN daily_quiz_sets s ON s.id=q.quiz_set_id
        WHERE s.status='published' AND s.quiz_date>=? AND s.quiz_date<?
        """,
        (cutoff, quiz_date),
    ).fetchall()
    return sum(
        1
        for question in current
        if any(
            question["subject"] == previous["subject"]
            and SequenceMatcher(
                None, question["normalized_question"], previous["normalized_question"]
            ).ratio()
            >= 0.84
            for previous in prior
        )
    )


def write_review_sample(conn: sqlite3.Connection, output_path: Path) -> None:
    rows = conn.execute(
        """
        SELECT s.quiz_date, q.subject, q.difficulty, q.question, q.choices_json,
               q.correct_answer, q.explanation
        FROM daily_quiz_questions q
        JOIN daily_quiz_sets s ON s.id = q.quiz_set_id
        WHERE s.pipeline_version = 'candidate-v1' AND s.status = 'published'
        ORDER BY s.quiz_date,
                 CASE q.subject WHEN 'general_knowledge' THEN 0 ELSE 1 END,
                 CASE q.difficulty WHEN 'easy' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END
        """
    ).fetchall()
    by_slot: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for row in rows:
        by_slot.setdefault((row["subject"], row["difficulty"]), []).append(row)
    sample = [row for slot_rows in by_slot.values() for row in slot_rows[:2]]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "quiz_date",
                "subject",
                "difficulty",
                "question",
                "choices",
                "correct_answer",
                "explanation",
                "correctness_pass",
                "ambiguity_pass",
                "quality_pass",
                "notes",
            ],
        )
        writer.writeheader()
        for row in sample:
            writer.writerow(
                {
                    "quiz_date": row["quiz_date"],
                    "subject": row["subject"],
                    "difficulty": row["difficulty"],
                    "question": row["question"],
                    "choices": " | ".join(json.loads(row["choices_json"])),
                    "correct_answer": row["correct_answer"],
                    "explanation": row["explanation"],
                    "correctness_pass": "",
                    "ambiguity_pass": "",
                    "quality_pass": "",
                    "notes": "",
                }
            )


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    shadow_db = output_dir / "shadow.db"
    state_path = output_dir / STATE_FILENAME
    if args.resume:
        if not shadow_db.exists():
            raise FileNotFoundError(f"Cannot resume; shadow database is missing: {shadow_db}")
    else:
        copy_database(args.db.resolve(), shadow_db)
        for stale_name in (STATE_FILENAME, "report.json", "review-sample.csv"):
            (output_dir / stale_name).unlink(missing_ok=True)
    elapsed_by_date = load_elapsed_state(state_path, resume=args.resume)
    conn = sqlite3.connect(shadow_db)
    conn.row_factory = sqlite3.Row
    config = replace(
        daily_quiz.QuizConfig.from_env(),
        candidate_pipeline_enabled=True,
        answer_embargo_days=45,
        recovery_answer_embargo_days=30,
        question_similarity_days=180,
        candidate_max_calls_per_quiz=30,
    )
    daily_quiz.initialize_database(conn)
    target_dates = shadow_dates(args.start_date, args.days)
    run_status = "complete"
    pause_reason: str | None = None
    try:
        for quiz_date in target_dates:
            existing_status = daily_quiz.quiz_status(conn, quiz_date)
            if (
                existing_status["status"] == "published"
                and existing_status["pipeline_version"] == "candidate-v1"
            ):
                continue
            started = time.monotonic()
            result: dict[str, Any] = {}
            quota_exhausted = False
            call_budget_exhausted = False
            for round_number in range(1, args.max_rounds + 1):
                if generation_call_count(conn, quiz_date) >= config.candidate_max_calls_per_quiz:
                    call_budget_exhausted = True
                    break
                round_messages: list[str] = []

                def shadow_log(message: str, day: str = quiz_date) -> None:
                    round_messages.append(message)
                    print(f"[{day}] {message}", flush=True)

                result = daily_quiz.generate_daily_quiz(
                    conn,
                    quiz_date=quiz_date,
                    config=config,
                    force=round_number == 1 and not args.resume,
                    generation_mode="normal",
                    log=shadow_log,
                )
                if result.get("status") == "published":
                    break
                if provider_capacity_exhausted(round_messages):
                    quota_exhausted = True
                    break
                if generation_call_count(conn, quiz_date) >= config.candidate_max_calls_per_quiz:
                    call_budget_exhausted = True
                    break
                if round_number < args.max_rounds:
                    time.sleep(args.retry_delay_seconds)
            elapsed_by_date[quiz_date] = round(
                elapsed_by_date.get(quiz_date, 0.0) + time.monotonic() - started,
                2,
            )
            save_elapsed_state(state_path, elapsed_by_date)
            status = daily_quiz.quiz_status(conn, quiz_date)
            if status["status"] != "published":
                if quota_exhausted:
                    run_status = "paused_provider_quota"
                    pause_reason = (
                        "All configured AI providers exhausted their current free-tier capacity."
                    )
                elif call_budget_exhausted:
                    run_status = "failed_call_budget"
                    pause_reason = (
                        "The current date reached the configured discovery/composition "
                        "call ceiling."
                    )
                else:
                    run_status = "incomplete_quality_gate"
                    pause_reason = "The current date did not publish within the configured rounds."
                break
        write_review_sample(conn, output_dir / "review-sample.csv")

        results: list[dict[str, Any]] = []
        for quiz_date in target_dates:
            status = daily_quiz.quiz_status(conn, quiz_date)
            is_candidate_run = status["pipeline_version"] == "candidate-v1"
            results.append(
                {
                    "date": quiz_date,
                    "status": status["status"] if is_candidate_run else "pending",
                    "verified_questions": status["verified_questions"] if is_candidate_run else 0,
                    "generation_calls": generation_call_count(conn, quiz_date)
                    if is_candidate_run
                    else 0,
                    "answer_collisions": answer_collisions(
                        conn, quiz_date, config.answer_embargo_days
                    )
                    if is_candidate_run
                    else 0,
                    "question_collisions": question_collisions(
                        conn, quiz_date, config.question_similarity_days
                    )
                    if is_candidate_run
                    else 0,
                    "elapsed_seconds": elapsed_by_date.get(quiz_date, 0.0),
                    "candidate_batches": status["candidate_batches"]
                    if is_candidate_run
                    else 0,
                    "candidate_count": status["candidate_count"] if is_candidate_run else 0,
                    "providers": status["candidate_providers"] if is_candidate_run else [],
                }
            )
    finally:
        conn.close()

    elapsed = [
        float(item["elapsed_seconds"])
        for item in results
        if item["status"] == "published"
    ]
    automated_pass = len(results) == args.days and all(
        item["status"] == "published"
        and item["verified_questions"] == 6
        and item["answer_collisions"] == 0
        and item["question_collisions"] == 0
        and item["generation_calls"] <= config.candidate_max_calls_per_quiz
        and item["elapsed_seconds"] <= 7200
        for item in results
    ) and bool(elapsed) and statistics.median(elapsed) <= 3600
    report = {
        "automated_pass": automated_pass,
        "run_status": "passed" if automated_pass else run_status,
        "pause_reason": pause_reason,
        "resumable": run_status == "paused_provider_quota",
        "manual_review_required": True,
        "manual_acceptance": {
            "sample_size": 12,
            "required_correctness_passes": 12,
            "required_ambiguity_passes": 12,
            "required_quality_passes": 10,
        },
        "thresholds": {
            "quiz_count": args.days,
            "verified_questions_per_quiz": 6,
            "max_generation_calls_per_quiz": config.candidate_max_calls_per_quiz,
            "median_elapsed_seconds": 3600,
            "max_elapsed_seconds": 7200,
            "answer_collisions": 0,
            "question_collisions": 0,
        },
        "median_elapsed_seconds": statistics.median(elapsed) if elapsed else None,
        "results": results,
        "shadow_database": str(shadow_db),
        "review_sample": str(output_dir / "review-sample.csv"),
    }
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the two-stage quiz pipeline against an isolated copy of quiz history."
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--max-rounds", type=int, default=16)
    parser.add_argument("--retry-delay-seconds", type=float, default=60)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume the existing shadow database and active-time state in output-dir.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"Database not found: {args.db}")
    report = evaluate(args)
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0 if report["automated_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
