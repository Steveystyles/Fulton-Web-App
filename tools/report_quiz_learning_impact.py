from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import daily_quiz

DEFAULT_DB_PATH = PROJECT_DIR / "data" / "fultons.db"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "data" / "training"
DEFAULT_ACTIVATION_DATE = "2026-07-14"


@dataclass(frozen=True)
class LearningImpactResult:
    json_path: Path
    markdown_path: Path
    report: dict[str, Any]


def connect_database(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def classify_failure(reason: str, critic_json: str | None) -> str:
    normalized = daily_quiz.normalize_text(reason)
    if daily_quiz.is_transient_provider_failure(reason):
        return "provider_transient"
    if any(
        token in normalized
        for token in (
            "duplicate",
            "too similar",
            "appeared recently",
            "already appears",
            "already appeared",
            "too often recently",
        )
    ):
        return "repetition"
    critic: dict[str, Any] | None = None
    if critic_json:
        try:
            parsed = json.loads(critic_json)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            critic = parsed
    if critic is not None and not daily_quiz.critic_passed(critic):
        return "critic"
    if normalized:
        return "local_validation"
    return "unknown"


def phase_for_date(quiz_date: str, activation_date: str) -> str:
    return "after" if quiz_date >= activation_date else "before"


def empty_metrics() -> dict[str, Any]:
    return {
        "attempts": 0,
        "passed_attempts": 0,
        "failed_attempts": 0,
        "accepted_questions": 0,
        "attempts_per_passed_attempt": 0.0,
        "attempts_per_accepted_question": 0.0,
        "failure_categories": {},
        "top_failure_reasons": [],
        "providers": {},
    }


def summarize_bucket(attempt_rows: list[sqlite3.Row], accepted_count: int) -> dict[str, Any]:
    failure_categories: Counter[str] = Counter()
    failure_reasons: Counter[str] = Counter()
    providers: Counter[str] = Counter()
    passed = 0
    failed = 0

    for row in attempt_rows:
        providers[str(row["provider"] or "unknown")] += 1
        if int(row["passed"] or 0):
            passed += 1
            continue
        failed += 1
        reason = str(row["failure_reason"] or "")
        failure_categories[classify_failure(reason, row["critic_json"])] += 1
        if reason:
            failure_reasons[reason] += 1

    attempts = len(attempt_rows)
    result = empty_metrics()
    result.update(
        {
            "attempts": attempts,
            "passed_attempts": passed,
            "failed_attempts": failed,
            "accepted_questions": accepted_count,
            "attempts_per_passed_attempt": round(attempts / passed, 2) if passed else 0.0,
            "attempts_per_accepted_question": round(attempts / accepted_count, 2)
            if accepted_count
            else 0.0,
            "failure_categories": dict(failure_categories),
            "top_failure_reasons": [
                {"reason": reason, "count": count}
                for reason, count in failure_reasons.most_common(10)
            ],
            "providers": dict(providers),
        }
    )
    return result


def attempt_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT quiz_date, subject, difficulty, provider, passed, failure_reason, critic_json
        FROM daily_quiz_attempts
        ORDER BY quiz_date ASC, id ASC
        """
    ).fetchall()


def accepted_question_counts(
    conn: sqlite3.Connection,
    *,
    activation_date: str,
) -> tuple[Counter[str], Counter[tuple[str, str, str]]]:
    phase_counts: Counter[str] = Counter()
    slot_counts: Counter[tuple[str, str, str]] = Counter()
    rows = conn.execute(
        """
        SELECT daily_quiz_sets.quiz_date, daily_quiz_questions.subject, daily_quiz_questions.difficulty
        FROM daily_quiz_questions
        INNER JOIN daily_quiz_sets ON daily_quiz_sets.id = daily_quiz_questions.quiz_set_id
        WHERE daily_quiz_sets.status = 'published'
        """
    ).fetchall()
    for row in rows:
        phase = phase_for_date(str(row["quiz_date"]), activation_date)
        phase_counts[phase] += 1
        slot_counts[(phase, str(row["subject"]), str(row["difficulty"]))] += 1
    return phase_counts, slot_counts


def build_learning_impact_report(
    conn: sqlite3.Connection,
    *,
    activation_date: str = DEFAULT_ACTIVATION_DATE,
) -> dict[str, Any]:
    attempts = attempt_rows(conn)
    phase_question_counts, slot_question_counts = accepted_question_counts(
        conn,
        activation_date=activation_date,
    )

    by_phase_rows: dict[str, list[sqlite3.Row]] = {"before": [], "after": []}
    by_slot_rows: dict[tuple[str, str, str], list[sqlite3.Row]] = defaultdict(list)
    for row in attempts:
        phase = phase_for_date(str(row["quiz_date"]), activation_date)
        by_phase_rows[phase].append(row)
        by_slot_rows[(phase, str(row["subject"]), str(row["difficulty"]))].append(row)

    by_phase = {
        phase: summarize_bucket(rows, phase_question_counts[phase])
        for phase, rows in by_phase_rows.items()
    }
    by_slot = {
        f"{phase}/{subject}/{difficulty}": summarize_bucket(
            rows,
            slot_question_counts[(phase, subject, difficulty)],
        )
        for (phase, subject, difficulty), rows in sorted(by_slot_rows.items())
    }

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "activation_date": activation_date,
        "source": "daily_quiz_attempts + published daily_quiz_questions",
        "by_phase": by_phase,
        "by_slot": by_slot,
    }


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Quiz Learning Impact Report",
        "",
        f"- Created: {report['created_at']}",
        f"- Activation date: {report['activation_date']}",
        "",
        "## Phase Summary",
        "",
        "| Phase | Attempts | Passed | Failed | Accepted questions | Attempts / accepted | Top failure category |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for phase in ("before", "after"):
        metrics = report["by_phase"][phase]
        categories = metrics["failure_categories"]
        top_category = "-"
        if categories:
            top_category = max(categories.items(), key=lambda item: item[1])[0]
        lines.append(
            "| {phase} | {attempts} | {passed} | {failed} | {accepted} | {apa:.2f} | {category} |".format(
                phase=phase,
                attempts=metrics["attempts"],
                passed=metrics["passed_attempts"],
                failed=metrics["failed_attempts"],
                accepted=metrics["accepted_questions"],
                apa=metrics["attempts_per_accepted_question"],
                category=top_category,
            )
        )
    lines.append("")
    lines.append("## Top Current Failure Reasons")
    lines.append("")
    after_reasons = report["by_phase"]["after"]["top_failure_reasons"]
    if not after_reasons:
        lines.append("- No post-activation failures recorded.")
    else:
        for item in after_reasons[:5]:
            lines.append(f"- {item['count']}x {item['reason']}")
    lines.append("")
    return "\n".join(lines)


def write_report(
    report: dict[str, Any],
    output_dir: Path,
    *,
    prefix: str = "quiz_learning_impact",
) -> LearningImpactResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"{prefix}_{timestamp}.json"
    markdown_path = output_dir / f"{prefix}_{timestamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    markdown_path.write_text(markdown_report(report), encoding="utf-8")
    return LearningImpactResult(json_path=json_path, markdown_path=markdown_path, report=report)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report daily quiz generation quality before and after learning-profile activation.",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--activation-date", default=DEFAULT_ACTIVATION_DATE)
    parser.add_argument("--prefix", default="quiz_learning_impact")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"Database not found: {args.db}")
    conn = connect_database(args.db)
    try:
        report = build_learning_impact_report(conn, activation_date=args.activation_date)
    finally:
        conn.close()
    result = write_report(report, args.out_dir, prefix=args.prefix)
    print(
        json.dumps(
            {
                "json_path": str(result.json_path),
                "markdown_path": str(result.markdown_path),
                "activation_date": report["activation_date"],
                "by_phase": report["by_phase"],
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
