from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import daily_quiz

SYSTEM_MESSAGE = "Return one valid JSON object only. Do not use markdown."
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "data" / "training"

NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

ALL_QUESTIONS_SHEET = "All Questions"
FAILURES_SHEET = "Failures"

ALL_QUESTIONS_HEADERS = {
    "No.",
    "Original question",
    "Corrected question",
    "Supplied answer",
    "Answer verification status",
    "Verified/correct answer",
    "Incorrect answer 1",
    "Incorrect answer 2",
    "Incorrect answer 3",
    "Why these are good incorrect answers",
    "Verification/failure note",
    "Verification source",
    "Source URL",
    "Original reasoning",
    "Original score",
    "Original score justification",
}

FAILURES_HEADERS = {
    "No.",
    "Corrected question",
    "Supplied answer",
    "Status",
    "Verified/possible answer(s)",
    "Failure reason",
    "Verification source",
    "Source URL",
}

POSITIVE_CORE_FIELDS = (
    "Corrected question",
    "Verified/correct answer",
    "Incorrect answer 1",
    "Incorrect answer 2",
    "Incorrect answer 3",
    "Verification source",
    "Source URL",
)


@dataclass(frozen=True)
class ReviewedExportResult:
    train_path: Path
    eval_path: Path
    negative_path: Path
    manifest_path: Path
    train_count: int
    eval_count: int
    negative_count: int
    medium_quality_count: int
    skipped_counts: dict[str, int]


@dataclass(frozen=True)
class PositiveCandidate:
    row: dict[str, str]
    question: dict[str, Any]
    row_no: int
    score: float
    difficulty: str


def normalize_whitespace(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def column_index(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref.upper())
    if not match:
        return 0
    index = 0
    for char in match.group(1):
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def relationship_path(source_path: str, target: str) -> str:
    target = target.replace("\\", "/").lstrip("/")
    if target.startswith("xl/"):
        return target
    return posixpath.normpath(posixpath.join(posixpath.dirname(source_path), target))


def read_shared_strings(workbook: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in workbook.namelist():
        return []
    root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for item in root.findall("a:si", NS):
        strings.append("".join(text.text or "" for text in item.findall(".//a:t", NS)))
    return strings


def workbook_sheet_paths(workbook: zipfile.ZipFile) -> dict[str, str]:
    workbook_path = "xl/workbook.xml"
    rels_path = "xl/_rels/workbook.xml.rels"
    workbook_root = ET.fromstring(workbook.read(workbook_path))
    rels_root = ET.fromstring(workbook.read(rels_path))
    rels = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels_root}

    paths: dict[str, str] = {}
    for sheet in workbook_root.findall("a:sheets/a:sheet", NS):
        relation_id = sheet.attrib[f"{{{NS['r']}}}id"]
        paths[sheet.attrib["name"]] = relationship_path(workbook_path, rels[relation_id])
    return paths


def cell_text(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(".//a:t", NS))

    value = cell.find("a:v", NS)
    if value is None or value.text is None:
        return ""
    if cell_type == "s":
        try:
            return shared_strings[int(value.text)]
        except (IndexError, ValueError):
            return ""
    return value.text


def read_sheet_rows(workbook_path: Path, sheet_name: str) -> list[list[str]]:
    with zipfile.ZipFile(workbook_path) as workbook:
        shared_strings = read_shared_strings(workbook)
        sheet_paths = workbook_sheet_paths(workbook)
        if sheet_name not in sheet_paths:
            available = ", ".join(sorted(sheet_paths))
            raise ValueError(f"Sheet {sheet_name!r} not found. Available sheets: {available}")

        root = ET.fromstring(workbook.read(sheet_paths[sheet_name]))
        rows: list[list[str]] = []
        for row in root.findall("a:sheetData/a:row", NS):
            values: list[str] = []
            for cell in row.findall("a:c", NS):
                index = column_index(cell.attrib.get("r", "A"))
                while len(values) <= index:
                    values.append("")
                values[index] = normalize_whitespace(cell_text(cell, shared_strings))
            rows.append(values)
    return rows


def table_records(
    workbook_path: Path,
    sheet_name: str,
    required_headers: set[str],
) -> list[dict[str, str]]:
    rows = read_sheet_rows(workbook_path, sheet_name)
    header_index: int | None = None
    headers: list[str] = []
    for index, row in enumerate(rows):
        cleaned = [normalize_whitespace(value) for value in row]
        if required_headers.issubset(set(cleaned)):
            header_index = index
            headers = cleaned
            break
    if header_index is None:
        raise ValueError(f"Could not find required headers in sheet {sheet_name!r}.")

    records: list[dict[str, str]] = []
    for excel_row, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if not any(normalize_whitespace(value) for value in row):
            continue
        record = {
            header: normalize_whitespace(row[position]) if position < len(row) else ""
            for position, header in enumerate(headers)
            if header
        }
        record["_sheet"] = sheet_name
        record["_excel_row"] = str(excel_row)
        records.append(record)
    return records


def parse_score(value: str) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    if not match:
        return None
    return float(match.group(0))


def parse_row_no(row: dict[str, str]) -> int:
    match = re.search(r"\d+", row.get("No.", ""))
    return int(match.group(0)) if match else 0


def is_present(value: str) -> bool:
    return normalize_whitespace(value) != ""


def is_confirmed(row: dict[str, str]) -> bool:
    return row.get("Answer verification status", "").casefold() == "confirmed correct"


def difficulty_from_score(score: float | None) -> str:
    return "medium" if score is not None and score >= 9 else "hard"


def trim_text(value: str, *, max_length: int) -> str:
    value = normalize_whitespace(value)
    if len(value) <= max_length:
        return value
    clipped = value[: max_length - 1].rstrip()
    boundary = max(clipped.rfind(". "), clipped.rfind("; "), clipped.rfind(": "))
    if boundary >= 80:
        clipped = clipped[: boundary + 1]
    return clipped.rstrip(" .;,:") + "."


def tags_for_row(row: dict[str, str]) -> list[str]:
    source = row.get("Verification source", "")
    source_url = row.get("Source URL", "")
    question = row.get("Corrected question", "")
    text = f"{source} {source_url} {question}".casefold()
    tags = ["football"]
    if "women" in text:
        tags.append("womens-football")
    if "world cup" in text:
        tags.append("world-cup")
    if "award_winners" in text or "golden " in text or "silver " in text or "bronze " in text:
        tags.append("world-cup-awards")
    if "teams took part" in text or "how many teams" in text:
        tags.append("tournament-format")
    if "international" in text:
        tags.append("international-football")
    if "premier" in text or "club" in text or "league" in text:
        tags.append("club-football")
    if "most league" in text or "goal difference" in text or "home wins" in text:
        tags.append("season-stats")
    if "minute" in text or "scored" in text or "goalscorer" in text:
        tags.append("goalscorer")
    if "penalty shootout" in text or "shootout" in text:
        tags.append("shootout")
    if "city" in text or "venue" in text or "played" in text:
        tags.append("venue")
    if len(tags) < 2:
        tags.append("football-review")
    return list(dict.fromkeys(tags))[:6]


def build_explanation(row: dict[str, str]) -> str:
    source = row.get("Verification source", "")
    note = row.get("Verification/failure note", "")
    if note and source:
        return trim_text(f"{note} Verification source: {source}.", max_length=500)
    if source:
        return trim_text(f"The reviewed answer was verified against {source}.", max_length=500)
    return "The reviewed workbook confirmed this answer against its listed source."


def build_interesting_reason(row: dict[str, str]) -> str:
    for field in (
        "Original reasoning",
        "Original score justification",
        "Why these are good incorrect answers",
    ):
        value = row.get(field, "")
        if value:
            return trim_text(value, max_length=500)
    return "This reviewed football question was selected because it has a verified answer and plausible alternatives."


def build_question(row: dict[str, str], difficulty: str) -> dict[str, Any]:
    return {
        "subject": "football",
        "difficulty": difficulty,
        "question": row["Corrected question"],
        "choices": [
            row["Verified/correct answer"],
            row["Incorrect answer 1"],
            row["Incorrect answer 2"],
            row["Incorrect answer 3"],
        ],
        "correct_answer": row["Verified/correct answer"],
        "explanation": build_explanation(row),
        "interesting_reason": build_interesting_reason(row),
        "tags": tags_for_row(row),
    }


def feedback_text(value: str) -> str:
    return trim_text(value, max_length=350)


def failure_negative_record(row: dict[str, str]) -> dict[str, Any]:
    reason = row.get("Failure reason", "") or row.get("Status", "")
    possible = row.get("Verified/possible answer(s)", "")
    feedback = reason
    if possible:
        feedback = f"{feedback} Possible valid answer(s): {possible}."
    return {
        "metadata": {
            "source_sheet": FAILURES_SHEET,
            "workbook_no": parse_row_no(row),
            "excel_row": row.get("_excel_row"),
            "status": row.get("Status"),
            "verification_source": row.get("Verification source"),
            "source_url": row.get("Source URL"),
            "reason": "review_failure",
        },
        "question": row.get("Corrected question"),
        "supplied_answer": row.get("Supplied answer"),
        "verified_or_possible_answers": possible,
        "failure_reason": reason,
        "feedback_to_generator": feedback_text(feedback),
        "recommended_action": "Do not use as a positive training example until the ambiguity or answer error is corrected.",
    }


def low_quality_negative_record(row: dict[str, str], score: float | None) -> dict[str, Any]:
    reason = row.get("Original score justification") or row.get("Original reasoning")
    if not reason:
        reason = "Confirmed answer, but the reviewed original score was too low for positive training."
    feedback = f"Low-quality confirmed football question scored {score:g}/10. {reason}" if score is not None else reason
    return {
        "metadata": {
            "source_sheet": ALL_QUESTIONS_SHEET,
            "workbook_no": parse_row_no(row),
            "excel_row": row.get("_excel_row"),
            "status": row.get("Answer verification status"),
            "original_score": score,
            "verification_source": row.get("Verification source"),
            "source_url": row.get("Source URL"),
            "reason": "low_review_score",
        },
        "question": row.get("Corrected question"),
        "supplied_answer": row.get("Supplied answer"),
        "verified_answer": row.get("Verified/correct answer"),
        "failure_reason": reason,
        "feedback_to_generator": feedback_text(feedback),
        "recommended_action": "Keep out of SFT positives; use as review or preference-training material.",
    }


def training_example(
    candidate: PositiveCandidate,
    *,
    recent_questions: list[dict[str, Any]],
    feedback: list[str],
) -> dict[str, Any]:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_MESSAGE},
            {
                "role": "user",
                "content": daily_quiz.generator_prompt(
                    "football",
                    candidate.difficulty,
                    recent_questions,
                    feedback,
                ),
            },
            {
                "role": "assistant",
                "content": json.dumps(
                    candidate.question,
                    ensure_ascii=True,
                    sort_keys=True,
                ),
            },
        ]
    }


def eval_example(
    candidate: PositiveCandidate,
    *,
    workbook_path: Path,
    recent_questions: list[dict[str, Any]],
    feedback: list[str],
) -> dict[str, Any]:
    return {
        "metadata": {
            "source": str(workbook_path),
            "source_sheet": ALL_QUESTIONS_SHEET,
            "workbook_no": candidate.row_no,
            "excel_row": candidate.row.get("_excel_row"),
            "subject": "football",
            "difficulty": candidate.difficulty,
            "original_score": candidate.score,
            "verification_source": candidate.row.get("Verification source"),
            "source_url": candidate.row.get("Source URL"),
        },
        "context": {
            "subject": "football",
            "difficulty": candidate.difficulty,
            "recent_questions": daily_quiz.public_recent_questions(recent_questions),
            "feedback": feedback,
        },
        "input": {
            "system": SYSTEM_MESSAGE,
            "prompt": daily_quiz.generator_prompt(
                "football",
                candidate.difficulty,
                recent_questions,
                feedback,
            ),
        },
        "expected_output": candidate.question,
    }


def feedback_before(
    negative_records: list[dict[str, Any]],
    row_no: int,
    *,
    limit: int,
) -> list[str]:
    entries: list[str] = []
    seen: set[str] = set()
    for record in sorted(
        negative_records,
        key=lambda item: int(item.get("metadata", {}).get("workbook_no") or 0),
    ):
        metadata = record.get("metadata", {})
        if int(metadata.get("workbook_no") or 0) >= row_no:
            continue
        feedback = normalize_whitespace(record.get("feedback_to_generator", ""))
        normalized = daily_quiz.normalize_text(feedback)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        entries.append(feedback)
    return entries[-limit:]


def recent_questions_before(
    accepted: list[PositiveCandidate],
    candidate: PositiveCandidate,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    recent: list[dict[str, Any]] = []
    candidate_question = candidate.question
    candidate_normalized = daily_quiz.normalize_text(candidate_question["question"])
    candidate_answer = daily_quiz.normalize_text(candidate_question["correct_answer"])
    candidate_tags = [
        daily_quiz.normalize_text(tag)
        for tag in candidate_question["tags"]
        if not daily_quiz.is_generic_topic_tag(tag)
    ]
    candidate_tag_set = set(candidate_tags)
    answer_count = 0
    candidate_tag_counts = {tag: 0 for tag in candidate_tags}
    previous = [prior for prior in accepted if prior.row_no < candidate.row_no]
    for prior in reversed(previous):
        prior_question = prior.question
        prior_normalized = daily_quiz.normalize_text(prior_question["question"])
        if candidate_normalized == prior_normalized:
            continue
        if SequenceMatcher(None, candidate_normalized, prior_normalized).ratio() >= 0.84:
            continue

        prior_answer = daily_quiz.normalize_text(prior_question["correct_answer"])
        prior_answer_matches = candidate_answer == prior_answer
        if prior_answer_matches and (
            daily_quiz.normalize_text(candidate_question.get("subject", ""))
            == daily_quiz.normalize_text(prior_question.get("subject", ""))
            and daily_quiz.normalize_text(candidate_question.get("difficulty", ""))
            == daily_quiz.normalize_text(prior_question.get("difficulty", ""))
        ):
            continue
        if prior_answer_matches and answer_count >= 1:
            continue

        prior_candidate_tags = [
            daily_quiz.normalize_text(str(tag))
            for tag in prior_question.get("tags", [])
            if daily_quiz.normalize_text(str(tag)) in candidate_tag_set
        ]
        if any(candidate_tag_counts[tag] + prior_candidate_tags.count(tag) >= 5 for tag in candidate_tag_set):
            continue

        recent.append(prior_question)
        if prior_answer_matches:
            answer_count += 1
        for tag in prior_candidate_tags:
            candidate_tag_counts[tag] += 1
        if len(recent) >= limit:
            break
    return recent


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True))
            handle.write("\n")


def export_reviewed_football_training_data(
    workbook_path: Path,
    output_dir: Path,
    *,
    high_score_min: float = 7,
    low_score_max: float = 3,
    eval_modulo: int = 5,
    recent_limit: int = 30,
    feedback_limit: int = 5,
    prefix: str = "football_review",
) -> ReviewedExportResult:
    all_rows = table_records(workbook_path, ALL_QUESTIONS_SHEET, ALL_QUESTIONS_HEADERS)
    failure_rows = table_records(workbook_path, FAILURES_SHEET, FAILURES_HEADERS)
    if not all_rows:
        raise ValueError("No reviewed questions found in the All Questions sheet.")

    output_dir.mkdir(parents=True, exist_ok=True)

    skipped_counts = {
        "missing_core_fields": 0,
        "duplicate_questions": 0,
        "validation_failed": 0,
        "missing_score": 0,
    }
    validation_failures: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    score_distribution: dict[str, int] = {}
    medium_quality_count = 0
    positive_candidates: list[PositiveCandidate] = []
    negative_records: list[dict[str, Any]] = [
        failure_negative_record(row) for row in failure_rows
    ]
    seen_questions: set[str] = set()

    for row in sorted(all_rows, key=parse_row_no):
        status = row.get("Answer verification status", "")
        status_counts[status] = status_counts.get(status, 0) + 1
        score = parse_score(row.get("Original score", ""))
        if score is None:
            skipped_counts["missing_score"] += 1
        else:
            score_key = f"{score:g}/10"
            score_distribution[score_key] = score_distribution.get(score_key, 0) + 1

        if not is_confirmed(row):
            continue

        if score is not None and score <= low_score_max:
            negative_records.append(low_quality_negative_record(row, score))

        if score is None or score < high_score_min:
            if score is not None and low_score_max < score < high_score_min:
                medium_quality_count += 1
            continue

        missing = [field for field in POSITIVE_CORE_FIELDS if not is_present(row.get(field, ""))]
        if missing:
            skipped_counts["missing_core_fields"] += 1
            continue

        question_key = daily_quiz.normalize_text(row["Corrected question"])
        if question_key in seen_questions:
            skipped_counts["duplicate_questions"] += 1
            continue
        seen_questions.add(question_key)

        difficulty = difficulty_from_score(score)
        validation = daily_quiz.validate_question(
            build_question(row, difficulty),
            expected_subject="football",
            expected_difficulty=difficulty,
        )
        if not validation.passed or validation.question is None:
            skipped_counts["validation_failed"] += 1
            validation_failures[validation.reason] = validation_failures.get(validation.reason, 0) + 1
            continue

        positive_candidates.append(
            PositiveCandidate(
                row=row,
                question=validation.question,
                row_no=parse_row_no(row),
                score=score,
                difficulty=difficulty,
            )
        )

    train_records: list[dict[str, Any]] = []
    eval_records: list[dict[str, Any]] = []
    for candidate in positive_candidates:
        recent = recent_questions_before(
            positive_candidates,
            candidate,
            limit=recent_limit,
        )
        feedback = feedback_before(negative_records, candidate.row_no, limit=feedback_limit)
        if eval_modulo > 0 and candidate.row_no % eval_modulo == 0:
            eval_records.append(
                eval_example(
                    candidate,
                    workbook_path=workbook_path,
                    recent_questions=recent,
                    feedback=feedback,
                )
            )
        else:
            train_records.append(
                training_example(
                    candidate,
                    recent_questions=recent,
                    feedback=feedback,
                )
            )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    train_path = output_dir / f"{prefix}_sft_train_{timestamp}.jsonl"
    eval_path = output_dir / f"{prefix}_eval_{timestamp}.jsonl"
    negative_path = output_dir / f"{prefix}_negative_{timestamp}.jsonl"
    manifest_path = output_dir / f"{prefix}_manifest_{timestamp}.json"

    write_jsonl(train_path, train_records)
    write_jsonl(eval_path, eval_records)
    write_jsonl(negative_path, negative_records)

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(workbook_path),
        "source_sheets": [ALL_QUESTIONS_SHEET, FAILURES_SHEET],
        "train_path": str(train_path),
        "eval_path": str(eval_path),
        "negative_path": str(negative_path),
        "train_count": len(train_records),
        "eval_count": len(eval_records),
        "negative_count": len(negative_records),
        "positive_candidate_count": len(positive_candidates),
        "medium_quality_count": medium_quality_count,
        "all_questions_count": len(all_rows),
        "failure_sheet_count": len(failure_rows),
        "status_counts": status_counts,
        "score_distribution": score_distribution,
        "skipped_counts": skipped_counts,
        "validation_failures": validation_failures,
        "filters": {
            "positive_status": "Confirmed correct",
            "high_score_min": high_score_min,
            "low_score_max": low_score_max,
            "eval_split": f"workbook No. divisible by {eval_modulo}",
            "difficulty_mapping": "score >= 9 -> medium; otherwise hard; never easy",
            "recent_limit": recent_limit,
            "feedback_limit": feedback_limit,
        },
        "format": {
            "train": "OpenAI chat fine-tuning JSONL with messages",
            "eval": "Held-out quiz prompt, expected output, and metadata JSONL",
            "negative": "Failed, ambiguous, incorrect, and low-score reviewed rows for review/preference training",
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )

    return ReviewedExportResult(
        train_path=train_path,
        eval_path=eval_path,
        negative_path=negative_path,
        manifest_path=manifest_path,
        train_count=len(train_records),
        eval_count=len(eval_records),
        negative_count=len(negative_records),
        medium_quality_count=medium_quality_count,
        skipped_counts=skipped_counts,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export reviewed football workbook rows into SFT, eval, and negative JSONL datasets.",
    )
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for generated JSONL and manifest files.",
    )
    parser.add_argument(
        "--high-score-min",
        type=float,
        default=7,
        help="Minimum original score for positive SFT/eval candidates.",
    )
    parser.add_argument(
        "--low-score-max",
        type=float,
        default=3,
        help="Maximum confirmed original score to send to the negative dataset.",
    )
    parser.add_argument(
        "--eval-modulo",
        type=int,
        default=5,
        help="Hold out rows whose workbook No. is divisible by this value. Use 0 to disable.",
    )
    parser.add_argument(
        "--recent-limit",
        type=int,
        default=30,
        help="Maximum prior accepted reviewed questions included in each prompt.",
    )
    parser.add_argument(
        "--feedback-limit",
        type=int,
        default=5,
        help="Maximum prior reviewed failure feedback entries included in each prompt.",
    )
    parser.add_argument(
        "--prefix",
        default="football_review",
        help="Filename prefix for generated artifacts.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.workbook.exists():
        raise SystemExit(f"Workbook not found: {args.workbook}")
    result = export_reviewed_football_training_data(
        args.workbook,
        args.out_dir,
        high_score_min=args.high_score_min,
        low_score_max=args.low_score_max,
        eval_modulo=args.eval_modulo,
        recent_limit=args.recent_limit,
        feedback_limit=args.feedback_limit,
        prefix=args.prefix,
    )
    print(
        json.dumps(
            {
                "train_path": str(result.train_path),
                "eval_path": str(result.eval_path),
                "negative_path": str(result.negative_path),
                "manifest_path": str(result.manifest_path),
                "train_count": result.train_count,
                "eval_count": result.eval_count,
                "negative_count": result.negative_count,
                "medium_quality_count": result.medium_quality_count,
                "skipped_counts": result.skipped_counts,
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
