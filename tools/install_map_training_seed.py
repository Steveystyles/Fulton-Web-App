from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools import training_data_store


MODEL_FILES = (
    "map_learning_profile_latest.json",
    "map_selector_profile_latest.json",
    "map_selector_model_latest.json",
    "map_clue_quality_model_latest.json",
)
IMMUTABLE_SOURCE_FILES = (
    "map_clue_review_rows_20260727_152734.jsonl",
    "map_clue_negative_map_clue_review_20260727_152734.jsonl",
    "map_clue_failure_log_seed_20260718.jsonl",
)
OPTIONAL_FILES = ("map_clue_gold_examples.json",)


def _created_at(path: Path) -> datetime | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        value = str(payload.get("created_at") or "").strip()
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
        if parsed is not None and parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
    shutil.copyfile(source, temporary)
    temporary.replace(destination)


def _copy_model_when_newer(source: Path, destination: Path) -> bool:
    if not destination.exists():
        _atomic_copy(source, destination)
        return True
    source_created_at = _created_at(source)
    destination_created_at = _created_at(destination)
    if (
        source_created_at is not None
        and (
            destination_created_at is None
            or source_created_at > destination_created_at
        )
    ):
        _atomic_copy(source, destination)
        return True
    return False


def install_seed(seed_dir: Path, training_dir: Path) -> dict[str, Any]:
    if not seed_dir.is_dir():
        return {
            "installed": False,
            "reason": "seed directory is absent",
            "copied": [],
            "feedback_rows_added": 0,
        }

    training_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []

    for name in (*IMMUTABLE_SOURCE_FILES, *OPTIONAL_FILES):
        source = seed_dir / name
        destination = training_dir / name
        if source.is_file() and not destination.exists():
            _atomic_copy(source, destination)
            copied.append(name)

    feedback_rows_added = 0
    feedback_seed = seed_dir / training_data_store.MAP_PLACE_REVIEW_FEEDBACK_ALL
    if feedback_seed.is_file():
        rows = training_data_store.read_map_place_review_feedback_rows([feedback_seed])
        feedback_rows_added = training_data_store.merge_map_place_review_feedback_rows(
            training_data_store.consolidated_map_place_review_feedback_file(training_dir),
            rows,
            source_file=f"deployment-seed:{feedback_seed.name}",
        )

    for name in MODEL_FILES:
        source = seed_dir / name
        if source.is_file() and _copy_model_when_newer(source, training_dir / name):
            copied.append(name)

    return {
        "installed": bool(copied or feedback_rows_added),
        "reason": "",
        "copied": copied,
        "feedback_rows_added": feedback_rows_added,
    }
