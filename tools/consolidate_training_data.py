from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from tools import training_data_store

DEFAULT_TRAINING_DIR = PROJECT_DIR / "data" / "training"
DEFAULT_DATA_DIR = PROJECT_DIR / "data"


def row_signature(row: dict[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=True, sort_keys=True)


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def jsonl_record_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def consolidate_map_candidate_csvs(training_dir: Path) -> tuple[Path, dict[str, int]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    source_files = sorted(training_dir.glob("map_ai_place_candidates*.csv"))
    output = training_dir / "map_ai_place_candidates_all.jsonl"
    if not source_files and output.exists():
        return output, {
            "source_file_count": 0,
            "consolidated_row_count": jsonl_record_count(output),
            "preserved_existing": 1,
        }
    for path in source_files:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for index, row in enumerate(reader):
                cleaned = {str(key): str(value or "") for key, value in row.items() if key is not None}
                signature = row_signature(cleaned)
                if signature in seen:
                    continue
                seen.add(signature)
                records.append(
                    {
                        "source_file": str(path),
                        "source_index": index,
                        "row": cleaned,
                    }
                )
    write_jsonl(output, records)
    return output, {
        "source_file_count": len(source_files),
        "consolidated_row_count": len(records),
    }


def consolidate_map_candidate_json_runs(training_dir: Path) -> tuple[Path, dict[str, int]]:
    records: list[dict[str, Any]] = []
    source_files = sorted(training_dir.glob("map_ai_place_candidates*.json"))
    output = training_dir / "map_ai_place_candidate_runs_all.jsonl"
    if not source_files and output.exists():
        return output, {
            "source_file_count": 0,
            "consolidated_run_count": jsonl_record_count(output),
            "preserved_existing": 1,
        }
    for path in source_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            payload = {"error": f"invalid_json: {error}"}
        records.append({"source_file": str(path), "payload": payload})
    write_jsonl(output, records)
    return output, {
        "source_file_count": len(source_files),
        "consolidated_run_count": len(records),
    }


def consolidate_legacy_quizzes(data_dir: Path) -> tuple[Path, dict[str, int]]:
    quiz_dir = data_dir / "quizzes"
    records: list[dict[str, Any]] = []
    source_files = sorted(path for path in quiz_dir.glob("*") if path.is_file()) if quiz_dir.exists() else []
    output = data_dir / "legacy_quizzes_all.jsonl"
    if not source_files and output.exists():
        return output, {
            "source_file_count": 0,
            "consolidated_record_count": jsonl_record_count(output),
            "preserved_existing": 1,
        }
    for path in source_files:
        if path.suffix.lower() == ".jsonl":
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError as error:
                    payload = {"error": f"invalid_jsonl_line: {error}", "raw": text}
                records.append(
                    {
                        "source_file": str(path),
                        "source_line": line_number,
                        "payload": payload,
                    }
                )
        else:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                payload = {"error": f"invalid_json: {error}"}
            records.append({"source_file": str(path), "payload": payload})
    write_jsonl(output, records)
    return output, {
        "source_file_count": len(source_files),
        "consolidated_record_count": len(records),
    }


def consolidate_map_place_selection_batches(training_dir: Path) -> tuple[Path, dict[str, int]]:
    records: list[dict[str, Any]] = []
    source_files = sorted(training_dir.glob("map_place_selection_batch_*.*"))
    output = training_dir / "map_place_selection_batches_all.jsonl"
    if not source_files and output.exists():
        return output, {
            "source_file_count": 0,
            "consolidated_record_count": jsonl_record_count(output),
            "preserved_existing": 1,
        }
    for path in source_files:
        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                for index, row in enumerate(reader):
                    records.append(
                        {
                            "source_file": str(path),
                            "source_index": index,
                            "kind": "csv_row",
                            "row": {str(key): str(value or "") for key, value in row.items() if key is not None},
                        }
                    )
        else:
            records.append(
                {
                    "source_file": str(path),
                    "kind": "text",
                    "text": path.read_text(encoding="utf-8", errors="replace"),
                }
            )
    write_jsonl(output, records)
    return output, {
        "source_file_count": len(source_files),
        "consolidated_record_count": len(records),
    }


def consolidate_map_clue_rewrite_reports(training_dir: Path) -> tuple[Path, dict[str, int]]:
    records: list[dict[str, Any]] = []
    source_files = sorted(training_dir.glob("map_clue_ai_rewrite_report_*.json"))
    output = training_dir / "map_clue_ai_rewrite_reports_all.jsonl"
    if not source_files and output.exists():
        return output, {
            "source_file_count": 0,
            "consolidated_report_count": jsonl_record_count(output),
            "preserved_existing": 1,
        }
    for path in source_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            payload = {"error": f"invalid_json: {error}"}
        records.append({"source_file": str(path), "payload": payload})
    write_jsonl(output, records)
    return output, {
        "source_file_count": len(source_files),
        "consolidated_report_count": len(records),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Consolidate generated training/review artifacts.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--training-dir", type=Path, default=DEFAULT_TRAINING_DIR)
    parser.add_argument(
        "--map-feedback-out",
        type=Path,
        default=None,
        help="Output path for consolidated map review feedback JSONL.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    legacy_files = training_data_store.legacy_map_place_review_feedback_files(args.training_dir)
    legacy_rows = training_data_store.read_map_place_review_feedback_rows(legacy_files)
    out_path = training_data_store.write_consolidated_map_place_review_feedback(
        args.training_dir,
        out_path=args.map_feedback_out,
    )
    records = training_data_store.consolidated_map_place_review_records(args.training_dir)
    candidate_csv_path, candidate_csv_summary = consolidate_map_candidate_csvs(args.training_dir)
    candidate_json_path, candidate_json_summary = consolidate_map_candidate_json_runs(args.training_dir)
    legacy_quiz_path, legacy_quiz_summary = consolidate_legacy_quizzes(args.data_dir)
    selection_batch_path, selection_batch_summary = consolidate_map_place_selection_batches(args.training_dir)
    rewrite_report_path, rewrite_report_summary = consolidate_map_clue_rewrite_reports(args.training_dir)
    existing_feedback_rows = training_data_store.read_map_place_review_feedback_rows([out_path])
    map_feedback_count = len(records) or len(existing_feedback_rows)
    print(
        json.dumps(
            {
                "map_feedback_path": str(out_path),
                "legacy_file_count": len(legacy_files),
                "legacy_row_count": len(legacy_rows),
                "consolidated_row_count": map_feedback_count,
                "duplicate_row_count": len(legacy_rows) - len(records),
                "map_candidate_csv_path": str(candidate_csv_path),
                **{
                    f"map_candidate_csv_{key}": value
                    for key, value in candidate_csv_summary.items()
                },
                "map_candidate_json_path": str(candidate_json_path),
                **{
                    f"map_candidate_json_{key}": value
                    for key, value in candidate_json_summary.items()
                },
                "legacy_quiz_path": str(legacy_quiz_path),
                **{
                    f"legacy_quiz_{key}": value
                    for key, value in legacy_quiz_summary.items()
                },
                "selection_batch_path": str(selection_batch_path),
                **{
                    f"selection_batch_{key}": value
                    for key, value in selection_batch_summary.items()
                },
                "rewrite_report_path": str(rewrite_report_path),
                **{
                    f"rewrite_report_{key}": value
                    for key, value in rewrite_report_summary.items()
                },
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
