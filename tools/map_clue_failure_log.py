from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TRAINING_DIR = PROJECT_DIR / "data" / "training"
DEFAULT_FAILURE_LOG_PATH = DEFAULT_TRAINING_DIR / "map_clue_failure_log.jsonl"

CATEGORY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "engineered_hard_hook",
        re.compile(
            r"\b(?:engineer(?:ed|ing)? (?:a )?hook|architect|architecture|"
            r"construction|designed by|appearance|static fact)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "non_specific_incident",
        re.compile(
            r"\b(?:not specific|specific incident|generic incident|broad conflict|"
            r"what .* conflict|could (?:fit|be|describe) many)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "broad_multi_site_target",
        re.compile(
            r"\b(?:broad (?:multi-site|multi site|serial|heritage|target|property)|serial|multi-site|multi site|multi-village|split into|poor pin target)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "unsupported_fact",
        re.compile(r"\b(?:unsupported|verified facts/context|unverified|hallucinat|source-backed|source backed|not supported)\b", re.IGNORECASE),
    ),
    (
        "location_based",
        re.compile(r"\b(?:location|proximity|broad geography|where the place is|what it is near|nearby|located|situated)\b", re.IGNORECASE),
    ),
    (
        "map_invisible_detail",
        re.compile(r"\b(?:not visible on (?:the )?map|map cannot show|colour indicator|color indicator|seat colou?r|roof colou?r|interior detail|aerial imagery)\b", re.IGNORECASE),
    ),
    (
        "weak_known_for_hook",
        re.compile(r"\b(?:known-for hook|known for|weak fields|concrete hook|distinct known-for)\b", re.IGNORECASE),
    ),
    (
        "answer_leak",
        re.compile(r"\b(?:answer name|accepted alias|alias|reveals? the answer|spoiler)\b", re.IGNORECASE),
    ),
    (
        "too_long_for_mobile",
        re.compile(r"\b(?:too long|too many words|mobile|wordy|concise)\b", re.IGNORECASE),
    ),
    (
        "coordinate_or_metadata",
        re.compile(r"\b(?:coordinate|latitude|longitude|iso code|time zone|database|metadata)\b", re.IGNORECASE),
    ),
    (
        "template_phrasing",
        re.compile(r"\b(?:formulaic|template|dataset wording|mapped urban|national-map|urban settlement)\b", re.IGNORECASE),
    ),
    (
        "placeholder_wording",
        re.compile(r"\b(?:placeholder|the place|target place|the answer)\b", re.IGNORECASE),
    ),
    (
        "repetitive_ladder",
        re.compile(r"\b(?:repeat|repetitive|same information|same fact)\b", re.IGNORECASE),
    ),
    (
        "provider_deferred",
        re.compile(r"\b(?:http 429|rate limit|quota|timeout|timed out|temporarily unavailable|socket|connection)\b", re.IGNORECASE),
    ),
)


def compact_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def compact_list(values: object) -> list[str]:
    if isinstance(values, list):
        return [compact_text(value) for value in values if compact_text(value)]
    text = compact_text(values)
    return [text] if text else []


def classify_failure_reasons(reasons: object) -> list[str]:
    text = " ".join(compact_list(reasons))
    categories = [
        category
        for category, pattern in CATEGORY_PATTERNS
        if pattern.search(text)
    ]
    return categories or ["other"]


def feedback_text(attempt: dict[str, Any], fallback: str = "") -> list[str]:
    feedback = compact_list(attempt.get("feedback_to_generator"))
    if feedback:
        return feedback
    reasons = compact_list(attempt.get("failure_reasons"))
    if reasons:
        return reasons
    if fallback:
        return [fallback]
    return ["Review and improve this failed map clue attempt."]


def should_log_attempt(result: dict[str, Any], attempt: dict[str, Any]) -> bool:
    if result.get("status") in {"deferred", "error"}:
        return True
    return not bool(attempt.get("passed"))


def failure_records_from_rewrite_report(
    report: dict[str, Any],
    *,
    report_path: str = "",
    prompt_version: str = "map_clue_generator_prompt:v1",
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    run_id = compact_text(report.get("created_at")) or datetime.now(timezone.utc).isoformat()
    provider_models = report.get("provider_models")
    for result in report.get("results") or []:
        status = compact_text(result.get("status"))
        attempts = result.get("attempts") if isinstance(result.get("attempts"), list) else []
        if status in {"deferred", "error"} and not attempts:
            reason = compact_text(result.get("error")) or f"Map clue rewrite ended with status {status}."
            attempts = [
                {
                    "generated": result.get("after"),
                    "failure_reasons": [reason],
                    "feedback_to_generator": [reason],
                    "critic_source": "provider",
                    "passed": False,
                }
            ]
        for index, attempt in enumerate(attempts, start=1):
            if not should_log_attempt(result, attempt):
                continue
            reasons = compact_list(attempt.get("failure_reasons"))
            fallback_reason = compact_text(result.get("error"))
            if not reasons and fallback_reason:
                reasons = [fallback_reason]
            categories = classify_failure_reasons(reasons)
            records.append(
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "run_id": run_id,
                    "report_path": report_path,
                    "provider": report.get("provider"),
                    "provider_models": provider_models,
                    "critic_mode": report.get("critic_mode"),
                    "dry_run": bool(report.get("dry_run")),
                    "prompt_version": prompt_version,
                    "learning_profile_path": report.get("learning_profile_path") or "",
                    "place_id": result.get("place_id"),
                    "place": result.get("place"),
                    "place_type": result.get("place_type"),
                    "difficulty": result.get("difficulty"),
                    "status": status or "unknown",
                    "attempt_index": index,
                    "generated": attempt.get("generated"),
                    "failure_reason": "; ".join(reasons) or f"Map clue rewrite ended with status {status or 'unknown'}.",
                    "failure_reasons": reasons,
                    "failure_categories": categories,
                    "feedback_to_generator": feedback_text(attempt, fallback="Use source-supported, adult-readable clues with the correct role at each level."),
                    "critic_source": attempt.get("critic_source") or "unknown",
                    "human_review": {
                        "status": "unreviewed",
                        "notes": "",
                        "reviewed_at": "",
                    },
                    "metadata": {
                        "reason": "map_clue_rewrite_failure",
                        "failure_categories": categories,
                        "place": result.get("place"),
                        "place_type": result.get("place_type") or "*",
                        "difficulty": result.get("difficulty") or "*",
                        "status": status or "unknown",
                        "critic_source": attempt.get("critic_source") or "unknown",
                    },
                }
            )
    return records


def append_failure_records(path: Path, records: list[dict[str, Any]]) -> int:
    if not records:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")
    return len(records)


def read_failure_log(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            record = json.loads(stripped)
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_number} is not a JSON object.")
            records.append(record)
    return records
