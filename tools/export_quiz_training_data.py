from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import daily_quiz

SYSTEM_MESSAGE = "Return one valid JSON object only. Do not use markdown."
DEFAULT_DB_PATH = PROJECT_DIR / "data" / "fultons.db"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "data" / "training"


@dataclass(frozen=True)
class ExportResult:
    train_path: Path
    eval_path: Path
    manifest_path: Path
    train_count: int
    eval_count: int
    dates: list[str]
    eval_dates: list[str]


def connect_database(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def parse_json_list(value: str) -> list[Any]:
    parsed = json.loads(value)
    return parsed if isinstance(parsed, list) else []


def question_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "subject": row["subject"],
        "difficulty": row["difficulty"],
        "question": row["question"],
        "choices": parse_json_list(row["choices_json"]),
        "correct_answer": row["correct_answer"],
        "explanation": row["explanation"],
        "interesting_reason": row["interesting_reason"],
        "tags": parse_json_list(row["tags_json"]),
    }


def accepted_question_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            daily_quiz_questions.*,
            daily_quiz_sets.quiz_date,
            daily_quiz_sets.status
        FROM daily_quiz_questions
        INNER JOIN daily_quiz_sets
            ON daily_quiz_sets.id = daily_quiz_questions.quiz_set_id
        WHERE daily_quiz_sets.status = 'published'
        ORDER BY daily_quiz_sets.quiz_date ASC,
                 daily_quiz_questions.created_at ASC,
                 daily_quiz_questions.id ASC
        """
    ).fetchall()


def prior_accepted_questions(
    rows: list[sqlite3.Row],
    current: sqlite3.Row,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    current_created = str(current["created_at"])
    current_id = int(current["id"])
    candidates = [
        row
        for row in rows
        if row["subject"] == current["subject"]
        and row["quiz_date"] != current["quiz_date"]
        and (
            str(row["created_at"]) < current_created
            or (str(row["created_at"]) == current_created and int(row["id"]) < current_id)
        )
    ]
    candidates.sort(key=lambda row: (str(row["created_at"]), int(row["id"])), reverse=True)
    return [question_from_row(row) for row in candidates[:limit]]


def feedback_from_attempt_rows(rows: list[sqlite3.Row], *, limit: int) -> list[str]:
    feedback: list[str] = []
    seen: set[str] = set()
    for row in rows:
        entries: list[str] = []
        critic_json = row["critic_json"]
        if critic_json:
            try:
                critic = json.loads(critic_json)
            except json.JSONDecodeError:
                critic = None
            if isinstance(critic, dict):
                feedback_text = str(critic.get("feedback_to_generator") or "").strip()
                if feedback_text:
                    entries.append(feedback_text)
        reason = str(row["failure_reason"] or "").strip()
        if reason and not daily_quiz.is_transient_provider_failure(reason):
            entries.append(reason)
        for entry in entries:
            normalized = daily_quiz.normalize_text(entry)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            feedback.append(entry)
            if len(feedback) >= limit:
                return feedback
    return feedback


def prior_failed_feedback(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    limit: int,
) -> list[str]:
    rows = conn.execute(
        """
        SELECT failure_reason, critic_json, created_at
        FROM daily_quiz_attempts
        WHERE quiz_date = ?
          AND subject = ?
          AND difficulty = ?
          AND passed = 0
          AND created_at <= ?
        ORDER BY created_at ASC, id ASC
        """,
        (
            row["quiz_date"],
            row["subject"],
            row["difficulty"],
            row["created_at"],
        ),
    ).fetchall()
    return feedback_from_attempt_rows(rows, limit=limit)


def training_example(
    row: sqlite3.Row,
    *,
    recent_questions: list[dict[str, Any]],
    feedback: list[str],
) -> dict[str, Any]:
    question = question_from_row(row)
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_MESSAGE},
            {
                "role": "user",
                "content": daily_quiz.generator_prompt(
                    row["subject"],
                    row["difficulty"],
                    recent_questions,
                    feedback,
                ),
            },
            {
                "role": "assistant",
                "content": json.dumps(question, ensure_ascii=True, sort_keys=True),
            },
        ]
    }


def eval_example(
    row: sqlite3.Row,
    *,
    recent_questions: list[dict[str, Any]],
    feedback: list[str],
) -> dict[str, Any]:
    context_recent = daily_quiz.public_recent_questions(recent_questions)
    return {
        "metadata": {
            "quiz_date": row["quiz_date"],
            "question_id": row["id"],
            "subject": row["subject"],
            "difficulty": row["difficulty"],
        },
        "context": {
            "subject": row["subject"],
            "difficulty": row["difficulty"],
            "recent_questions": context_recent,
            "feedback": feedback,
        },
        "input": {
            "system": SYSTEM_MESSAGE,
            "prompt": daily_quiz.generator_prompt(
                row["subject"],
                row["difficulty"],
                recent_questions,
                feedback,
            ),
        },
        "expected_output": question_from_row(row),
    }


def choose_eval_dates(rows: list[sqlite3.Row], eval_days: int) -> list[str]:
    dates = sorted({str(row["quiz_date"]) for row in rows})
    if eval_days <= 0 or len(dates) <= 1:
        return []
    count = min(eval_days, len(dates) - 1)
    return dates[-count:]


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True))
            handle.write("\n")


def export_training_data(
    conn: sqlite3.Connection,
    output_dir: Path,
    *,
    eval_days: int = 7,
    recent_limit: int = 30,
    feedback_limit: int = 5,
    prefix: str = "quiz",
) -> ExportResult:
    rows = accepted_question_rows(conn)
    if not rows:
        raise ValueError("No published daily quiz questions found to export.")

    output_dir.mkdir(parents=True, exist_ok=True)
    eval_dates = choose_eval_dates(rows, eval_days)
    eval_date_set = set(eval_dates)

    train_records: list[dict[str, Any]] = []
    eval_records: list[dict[str, Any]] = []
    for row in rows:
        recent = prior_accepted_questions(rows, row, limit=recent_limit)
        feedback = prior_failed_feedback(conn, row, limit=feedback_limit)
        if row["quiz_date"] in eval_date_set:
            eval_records.append(
                eval_example(row, recent_questions=recent, feedback=feedback)
            )
        else:
            train_records.append(
                training_example(row, recent_questions=recent, feedback=feedback)
            )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    train_path = output_dir / f"{prefix}_sft_train_{timestamp}.jsonl"
    eval_path = output_dir / f"{prefix}_eval_{timestamp}.jsonl"
    manifest_path = output_dir / f"{prefix}_export_manifest_{timestamp}.json"

    write_jsonl(train_path, train_records)
    write_jsonl(eval_path, eval_records)

    dates = sorted({str(row["quiz_date"]) for row in rows})
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "daily_quiz_sets + daily_quiz_questions + daily_quiz_attempts",
        "train_path": str(train_path),
        "eval_path": str(eval_path),
        "train_count": len(train_records),
        "eval_count": len(eval_records),
        "published_question_count": len(rows),
        "quiz_dates": dates,
        "eval_dates": eval_dates,
        "recent_limit": recent_limit,
        "feedback_limit": feedback_limit,
        "format": {
            "train": "OpenAI chat fine-tuning JSONL with messages",
            "eval": "Held-out quiz prompt, expected output, and metadata JSONL",
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")

    return ExportResult(
        train_path=train_path,
        eval_path=eval_path,
        manifest_path=manifest_path,
        train_count=len(train_records),
        eval_count=len(eval_records),
        dates=dates,
        eval_dates=eval_dates,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export accepted daily quiz history into training and eval JSONL.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Path to fultons.db. Defaults to data/fultons.db.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for generated JSONL and manifest files.",
    )
    parser.add_argument(
        "--eval-days",
        type=int,
        default=7,
        help="Number of most recent quiz dates to hold out for evals.",
    )
    parser.add_argument(
        "--recent-limit",
        type=int,
        default=30,
        help="Maximum prior accepted questions included in each prompt.",
    )
    parser.add_argument(
        "--feedback-limit",
        type=int,
        default=5,
        help="Maximum prior failed-attempt feedback entries included in each prompt.",
    )
    parser.add_argument(
        "--prefix",
        default="quiz",
        help="Filename prefix for generated artifacts.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"Database not found: {args.db}")
    conn = connect_database(args.db)
    try:
        result = export_training_data(
            conn,
            args.out_dir,
            eval_days=args.eval_days,
            recent_limit=args.recent_limit,
            feedback_limit=args.feedback_limit,
            prefix=args.prefix,
        )
    finally:
        conn.close()
    print(
        json.dumps(
            {
                "train_path": str(result.train_path),
                "eval_path": str(result.eval_path),
                "manifest_path": str(result.manifest_path),
                "train_count": result.train_count,
                "eval_count": result.eval_count,
                "eval_dates": result.eval_dates,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
