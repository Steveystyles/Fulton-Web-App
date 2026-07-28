from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

MAP_PLACE_REVIEW_FEEDBACK_ALL = "map_place_review_feedback_all.jsonl"
LEGACY_MAP_PLACE_REVIEW_FEEDBACK_RE = re.compile(
    r"^map_place_review_feedback_\d{8}T\d{6}Z\.json$"
)


def legacy_map_place_review_feedback_files(training_dir: Path) -> list[Path]:
    return sorted(
        (path for path in training_dir.glob("map_place_review_feedback_*.json") if LEGACY_MAP_PLACE_REVIEW_FEEDBACK_RE.match(path.name)),
        key=lambda path: (path.stat().st_mtime, path.name),
    )


def consolidated_map_place_review_feedback_file(training_dir: Path) -> Path:
    return training_dir / MAP_PLACE_REVIEW_FEEDBACK_ALL


def default_map_place_review_feedback_files(training_dir: Path) -> list[Path]:
    consolidated = consolidated_map_place_review_feedback_file(training_dir)
    if consolidated.exists():
        return [consolidated]
    return legacy_map_place_review_feedback_files(training_dir)


def _canonical_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(child)
            for key, child in sorted(value.items())
            if not str(key).startswith("_")
        }
    if isinstance(value, list):
        return [_canonical_value(child) for child in value]
    if isinstance(value, str):
        return " ".join(value.strip().split())
    return value


def review_row_signature(row: dict[str, Any]) -> str:
    return json.dumps(_canonical_value(row), sort_keys=True, ensure_ascii=True)


def _read_legacy_feedback_file(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(payload.get("rows", [])):
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item["_source_file"] = str(path)
        item["_source_index"] = index
        rows.append(item)
    return rows


def _read_consolidated_feedback_file(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if isinstance(payload, dict) and isinstance(payload.get("row"), dict):
            item = dict(payload["row"])
            item["_source_file"] = str(payload.get("source_file") or path)
            item["_source_index"] = payload.get("source_index", line_number - 1)
            item["_consolidated_file"] = str(path)
            rows.append(item)
        elif isinstance(payload, dict):
            item = dict(payload)
            item.setdefault("_source_file", str(path))
            item.setdefault("_source_index", line_number - 1)
            rows.append(item)
    return rows


def read_map_place_review_feedback_rows(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        if path.name == MAP_PLACE_REVIEW_FEEDBACK_ALL or path.suffix.lower() == ".jsonl":
            rows.extend(_read_consolidated_feedback_file(path))
        else:
            rows.extend(_read_legacy_feedback_file(path))
    return rows


def map_place_review_is_clean_approval(row: dict[str, Any]) -> bool:
    overall = row.get("overall_review") if isinstance(row.get("overall_review"), dict) else {}
    overall_verdict = str(
        overall.get("pass_fail")
        or overall.get("passFail")
        or row.get("your_score")
        or ""
    ).strip().casefold()
    if overall_verdict != "pass":
        return False
    if str(overall.get("reason") or row.get("notes") or "").strip():
        return False

    reviews = row.get("clue_reviews") if isinstance(row.get("clue_reviews"), dict) else {}
    scores = row.get("clue_scores") if isinstance(row.get("clue_scores"), dict) else {}
    for level in ("hard", "medium", "easy"):
        review = reviews.get(level) if isinstance(reviews.get(level), dict) else {}
        verdict = str(
            review.get("pass_fail")
            or review.get("passFail")
            or scores.get(level)
            or ""
        ).strip().casefold()
        if verdict != "pass" or str(review.get("reason") or "").strip():
            return False
    return bool(str(row.get("place") or row.get("canonical_name") or "").strip())


def clean_map_place_review_names(paths: list[Path]) -> set[str]:
    return {
        str(row.get("place") or row.get("canonical_name") or "").strip().casefold()
        for row in read_map_place_review_feedback_rows(paths)
        if map_place_review_is_clean_approval(row)
    }


def failed_map_place_review_names(paths: list[Path]) -> set[str]:
    names: set[str] = set()
    for row in read_map_place_review_feedback_rows(paths):
        overall = row.get("overall_review") if isinstance(row.get("overall_review"), dict) else {}
        verdict = str(
            overall.get("pass_fail")
            or overall.get("passFail")
            or row.get("your_score")
            or ""
        ).strip().casefold()
        if verdict != "fail":
            continue
        name = str(row.get("place") or row.get("canonical_name") or "").strip().casefold()
        if name:
            names.add(name)
    return names


def consolidated_map_place_review_records(training_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in legacy_map_place_review_feedback_files(training_dir):
        for row in _read_legacy_feedback_file(path):
            signature = review_row_signature(row)
            if signature in seen:
                continue
            seen.add(signature)
            source_file = row.pop("_source_file", str(path))
            source_index = row.pop("_source_index", None)
            records.append(
                {
                    "source_file": source_file,
                    "source_index": source_index,
                    "row": row,
                }
            )
    return records


def write_consolidated_map_place_review_feedback(
    training_dir: Path,
    *,
    out_path: Path | None = None,
) -> Path:
    output = out_path or consolidated_map_place_review_feedback_file(training_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    if output.exists():
        for line in output.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if not isinstance(payload, dict):
                continue
            row = payload.get("row") if isinstance(payload.get("row"), dict) else payload
            signature = review_row_signature(row)
            if signature in seen:
                continue
            seen.add(signature)
            records.append(payload)
    for record in consolidated_map_place_review_records(training_dir):
        row = record.get("row") if isinstance(record.get("row"), dict) else record
        signature = review_row_signature(row)
        if signature in seen:
            continue
        seen.add(signature)
        records.append(record)
    if not records and output.exists():
        return output
    output.write_text(
        "".join(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    return output


def merge_map_place_review_feedback_rows(
    output: Path,
    rows: list[dict[str, Any]],
    *,
    source_file: str,
    reconstructed: bool = False,
) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    existing_records: list[dict[str, Any]] = []
    seen: set[str] = set()
    if output.exists():
        for line in output.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if not isinstance(payload, dict):
                continue
            row = payload.get("row") if isinstance(payload.get("row"), dict) else payload
            signature = review_row_signature(row)
            if signature in seen:
                continue
            seen.add(signature)
            existing_records.append(payload)
    added = 0
    for index, row in enumerate(rows):
        signature = review_row_signature(row)
        if signature in seen:
            continue
        seen.add(signature)
        existing_records.append(
            {
                "source_file": source_file,
                "source_index": index,
                "reconstructed": reconstructed,
                "row": row,
            }
        )
        added += 1
    output.write_text(
        "".join(
            json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n"
            for record in existing_records
        ),
        encoding="utf-8",
    )
    return added
