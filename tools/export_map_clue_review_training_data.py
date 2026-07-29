from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "data" / "training"
SYSTEM_MESSAGE = "Return one valid JSON object only. Do not use markdown."

REQUIRED_COLUMNS = (
    "example_id",
    "place_name",
    "place_type",
    "country",
    "admin1",
    "lat",
    "lng",
    "clue_level",
    "original_clue",
    "label",
    "failure_categories",
    "pass_reason",
    "fail_reason",
    "rewrite_needed",
    "rewritten_clue",
    "training_weight",
    "exclude_from_training",
    "exclude_reason",
)
VALID_LEVELS = {"hard", "medium", "easy"}
VALID_LABELS = {"pass", "fail"}
VALID_YES_NO = {"yes", "no"}
VALID_FAILURE_CATEGORIES = {
    "answer_leak",
    "too_generic",
    "static_description",
    "weak_hard_hook",
    "weak_medium_narrowing",
    "weak_easy_map_anchor",
    "deep_zoom_anchor",
    "incorrect_local_area",
    "too_broad",
    "repetitive",
    "fact_unclear",
    "factual_risk",
    "wrong_difficulty",
    "useful_but_wrong_level",
}
CATEGORY_GUIDANCE = {
    "answer_leak": "Remove the answer name, aliases, and distinctive answer tokens from playable clues.",
    "too_generic": "Replace generic claims according to role: recognition for hard, geographic narrowing for medium, and a local route for easy.",
    "static_description": "Avoid static filler and fulfil the assigned clue role with concrete information.",
    "weak_hard_hook": "Hard clues need a memorable incident, event, record, person, story, oddity, or surprising fact.",
    "weak_medium_narrowing": "Medium clues must materially reduce the geographic search area; a place-owned fact may add character when it also advances that narrowing.",
    "weak_easy_map_anchor": "Easy clues must narrow within medium's area using an anchor visible by zoom 11 or earlier on the quiz's Esri World Street Map.",
    "deep_zoom_anchor": "Replace an essential anchor that first appears after zoom 11 with a larger visible anchor and a practical directional relationship. A later district label may only supplement that route.",
    "incorrect_local_area": "Verify the target's technical local area; do not present a popular association with a nearby district as its actual location.",
    "too_broad": "Narrow the clue toward one identifiable map target.",
    "repetitive": "Avoid repeating the same clue idea in different words.",
    "fact_unclear": "Use clear, concrete wording that obviously attaches to the target place.",
    "factual_risk": "Avoid uncertain claims; prefer stable and verifiable facts.",
    "wrong_difficulty": "Move the clue to the level where it gives the right solving value.",
    "useful_but_wrong_level": "Keep the useful idea but recast it for the intended clue level.",
}
LEVEL_INTENT = {
    "hard": "One recognition hook: preferably a unique incident or story, or another genuinely distinctive record, achievement, discovery, association, tradition, natural occurrence, or cultural moment.",
    "medium": "A geographic narrowing clue that reduces the search to a useful country, region, culture, language, city, or equivalent scope.",
    "easy": "A local map route within medium's area, using an anchor visible by zoom 11 or earlier and a practical direction or relationship.",
}
GENERIC_LEAK_TOKENS = {
    "arena",
    "bridge",
    "building",
    "castle",
    "cathedral",
    "center",
    "centre",
    "city",
    "cliff",
    "cliffs",
    "estadio",
    "falls",
    "fort",
    "fortress",
    "ground",
    "hall",
    "harbour",
    "island",
    "landmark",
    "monument",
    "mosque",
    "mount",
    "mountain",
    "museum",
    "national",
    "new",
    "north",
    "old",
    "palace",
    "park",
    "road",
    "royal",
    "saint",
    "south",
    "square",
    "stadium",
    "stade",
    "statue",
    "theater",
    "theatre",
    "tower",
    "wall",
}


@dataclass(frozen=True)
class ExportResult:
    all_rows_path: Path
    critic_train_path: Path
    critic_eval_path: Path
    rewrite_train_path: Path
    rewrite_eval_path: Path
    negative_path: Path
    report_path: Path
    included_count: int
    excluded_count: int
    critic_train_count: int
    critic_eval_count: int
    rewrite_train_count: int
    rewrite_eval_count: int
    negative_count: int


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def normalize(value: object) -> str:
    return str(value or "").strip()


def clean_row(row: dict[str, Any], row_number: int) -> dict[str, str]:
    cleaned = {column: normalize(row.get(column)) for column in REQUIRED_COLUMNS}
    cleaned["row_number"] = str(row_number)
    cleaned["clue_level"] = cleaned["clue_level"].lower()
    cleaned["label"] = cleaned["label"].lower()
    cleaned["rewrite_needed"] = cleaned["rewrite_needed"].lower()
    cleaned["exclude_from_training"] = cleaned["exclude_from_training"].lower()
    cleaned["failure_categories"] = "; ".join(split_categories(cleaned["failure_categories"]))
    cleaned["row_uid"] = f"{cleaned['example_id']}:{cleaned['clue_level']}:{row_number}"
    return cleaned


def read_ml_ready_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{path} has no header row.")
        missing = [column for column in REQUIRED_COLUMNS if column not in reader.fieldnames]
        if missing:
            raise ValueError(f"{path} is missing required columns: {', '.join(missing)}")
        return [clean_row(row, row_number) for row_number, row in enumerate(reader, start=2)]


def split_categories(value: str) -> list[str]:
    categories: list[str] = []
    for raw in re.split(r"[;,|]", value or ""):
        category = raw.strip().lower()
        if category:
            categories.append(category)
    return categories


def parse_float(value: str, *, field: str, row: dict[str, str], errors: list[str]) -> float:
    try:
        return float(value)
    except ValueError:
        errors.append(f"row {row['row_number']}: {field} is not numeric: {value!r}")
        return 0.0


def parse_weight(value: str, *, row: dict[str, str], errors: list[str] | None = None) -> float:
    try:
        weight = float(value)
    except ValueError:
        if errors is not None:
            errors.append(f"row {row['row_number']}: training_weight is not numeric: {value!r}")
        return 0.0
    if errors is not None and not 0 <= weight <= 2:
        errors.append(f"row {row['row_number']}: training_weight must be between 0 and 2.")
    return weight


def validate_rows(rows: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    seen_uids: set[str] = set()
    for row in rows:
        missing_values = [
            column
            for column in REQUIRED_COLUMNS
            if column
            not in {
                "admin1",
                "failure_categories",
                "pass_reason",
                "fail_reason",
                "rewritten_clue",
                "exclude_reason",
            }
            and not row[column]
        ]
        if missing_values:
            errors.append(f"row {row['row_number']}: blank required values: {', '.join(missing_values)}")

        if row["row_uid"] in seen_uids:
            errors.append(f"row {row['row_number']}: duplicate row uid {row['row_uid']!r}")
        seen_uids.add(row["row_uid"])

        if row["clue_level"] not in VALID_LEVELS:
            errors.append(f"row {row['row_number']}: invalid clue_level {row['clue_level']!r}")
        if row["label"] not in VALID_LABELS:
            errors.append(f"row {row['row_number']}: invalid label {row['label']!r}")
        if row["rewrite_needed"] not in VALID_YES_NO:
            errors.append(f"row {row['row_number']}: rewrite_needed must be yes or no.")
        if row["exclude_from_training"] not in VALID_YES_NO:
            errors.append(f"row {row['row_number']}: exclude_from_training must be yes or no.")

        parse_float(row["lat"], field="lat", row=row, errors=errors)
        parse_float(row["lng"], field="lng", row=row, errors=errors)
        weight = parse_weight(row["training_weight"], row=row, errors=errors)
        if row["exclude_from_training"] == "yes" and weight != 0:
            errors.append(f"row {row['row_number']}: excluded rows must have training_weight 0.")
        if row["exclude_from_training"] == "no" and weight <= 0:
            errors.append(f"row {row['row_number']}: included rows must have positive training_weight.")

        categories = split_categories(row["failure_categories"])
        invalid_categories = [category for category in categories if category not in VALID_FAILURE_CATEGORIES]
        if invalid_categories:
            errors.append(
                f"row {row['row_number']}: invalid failure_categories: {', '.join(invalid_categories)}"
            )
        if row["label"] == "fail" and row["exclude_from_training"] == "no" and not categories:
            errors.append(f"row {row['row_number']}: included fail rows need failure_categories.")
        if row["rewrite_needed"] == "yes" and not row["rewritten_clue"]:
            errors.append(f"row {row['row_number']}: rewrite_needed is yes but rewritten_clue is blank.")
        if row["rewrite_needed"] == "no" and row["rewritten_clue"]:
            errors.append(f"row {row['row_number']}: rewrite_needed is no but rewritten_clue is populated.")
        if row["exclude_from_training"] == "yes" and not row["exclude_reason"]:
            errors.append(f"row {row['row_number']}: excluded rows need exclude_reason.")
    return errors


def tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.lower())


def answer_leak_tokens(row: dict[str, str], clue_field: str) -> list[str]:
    clue_tokens = set(tokens(row[clue_field]))
    place_tokens = tokens(row["place_name"])
    leaks = [
        token
        for token in place_tokens
        if len(token) >= 4 and token not in GENERIC_LEAK_TOKENS and token in clue_tokens
    ]
    place_phrase = row["place_name"].strip().lower()
    clue = row[clue_field].lower()
    if len(place_phrase) >= 4 and place_phrase in clue:
        leaks.append(place_phrase)
    return sorted(set(leaks))


def effective_failure_categories(row: dict[str, str]) -> list[str]:
    if row["label"] == "pass":
        return []
    return split_categories(row["failure_categories"])


def base_metadata(row: dict[str, str]) -> dict[str, Any]:
    return {
        "source": "map_clue_review_ml_ready_csv",
        "example_id": row["example_id"],
        "source_row_uid": row["row_uid"],
        "place": row["place_name"],
        "place_type": row["place_type"],
        "country": row["country"],
        "admin1": row["admin1"],
        "lat": float(row["lat"]),
        "lng": float(row["lng"]),
        "difficulty": row["clue_level"],
        "clue_level": row["clue_level"],
        "label": row["label"],
        "training_weight": parse_weight(row["training_weight"], row=row),
        "failure_categories": effective_failure_categories(row),
        "review_categories": split_categories(row["failure_categories"]),
    }


def all_row_record(row: dict[str, str]) -> dict[str, Any]:
    return {
        "metadata": base_metadata(row)
        | {
            "row_number": int(row["row_number"]),
            "exclude_from_training": row["exclude_from_training"] == "yes",
            "exclude_reason": row["exclude_reason"],
            "rewrite_needed": row["rewrite_needed"] == "yes",
            "detected_answer_leak_original": answer_leak_tokens(row, "original_clue"),
            "detected_answer_leak_rewritten": answer_leak_tokens(row, "rewritten_clue")
            if row["rewritten_clue"]
            else [],
        },
        "original_clue": row["original_clue"],
        "rewritten_clue": row["rewritten_clue"],
        "pass_reason": row["pass_reason"],
        "fail_reason": row["fail_reason"],
    }


def critic_prompt(row: dict[str, str]) -> str:
    categories = ", ".join(sorted(VALID_FAILURE_CATEGORIES))
    return "\n".join(
        [
            "Judge whether this map quiz clue should be accepted.",
            f"Place: {row['place_name']} ({row['place_type']}, {row['country']}, {row['admin1']})",
            f"Clue level: {row['clue_level']}",
            f"Level intent: {LEVEL_INTENT[row['clue_level']]}",
            f"Clue: {row['original_clue']}",
            "Pass only if it is fun, clear, answer-safe, at the right level, and useful for finding the place on a map.",
            f"If it fails, choose zero or more categories from: {categories}.",
            "Return JSON with keys: label, failure_categories, rationale.",
        ]
    )


def critic_record(row: dict[str, str]) -> dict[str, Any]:
    rationale = row["pass_reason"] if row["label"] == "pass" else row["fail_reason"]
    assistant = {
        "label": row["label"],
        "failure_categories": effective_failure_categories(row),
        "rationale": rationale,
    }
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_MESSAGE},
            {"role": "user", "content": critic_prompt(row)},
            {"role": "assistant", "content": json.dumps(assistant, ensure_ascii=True, sort_keys=True)},
        ],
        "metadata": base_metadata(row),
    }


def rewrite_prompt(row: dict[str, str]) -> str:
    categories = split_categories(row["failure_categories"])
    guidance = [CATEGORY_GUIDANCE[category] for category in categories if category in CATEGORY_GUIDANCE]
    return "\n".join(
        [
            "Rewrite this failed map quiz clue for the same place and clue level.",
            f"Place: {row['place_name']} ({row['place_type']}, {row['country']}, {row['admin1']})",
            f"Clue level: {row['clue_level']}",
            f"Level intent: {LEVEL_INTENT[row['clue_level']]}",
            f"Original clue: {row['original_clue']}",
            f"Failure categories: {', '.join(categories)}",
            f"Failure note: {row['fail_reason']}",
            "Guidance:",
            *[f"- {item}" for item in guidance],
            "Return JSON with key: rewritten_clue.",
        ]
    )


def rewrite_record(row: dict[str, str]) -> dict[str, Any]:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_MESSAGE},
            {"role": "user", "content": rewrite_prompt(row)},
            {
                "role": "assistant",
                "content": json.dumps(
                    {"rewritten_clue": row["rewritten_clue"]},
                    ensure_ascii=True,
                    sort_keys=True,
                ),
            },
        ],
        "metadata": base_metadata(row),
    }


def negative_record(row: dict[str, str]) -> dict[str, Any]:
    categories = effective_failure_categories(row)
    guidance = [CATEGORY_GUIDANCE[category] for category in categories if category in CATEGORY_GUIDANCE]
    return {
        "failure_reason": row["fail_reason"] or "; ".join(categories) or "Rejected during map clue review.",
        "feedback_to_generator": guidance or ["Improve this clue according to the map quiz clue-level intent."],
        "failure_categories": categories,
        "metadata": base_metadata(row),
    }


def row_sort_key(row: dict[str, str]) -> tuple[str, float, str]:
    return (row["example_id"], -parse_weight(row["training_weight"], row=row), row["clue_level"])


def balanced_critic_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    for level in ("hard", "medium", "easy"):
        level_rows = [row for row in rows if row["clue_level"] == level]
        passes = sorted(
            [row for row in level_rows if row["label"] == "pass"],
            key=lambda row: (-parse_weight(row["training_weight"], row=row), row["example_id"], row["row_uid"]),
        )
        fails = sorted(
            [row for row in level_rows if row["label"] == "fail"],
            key=lambda row: (-parse_weight(row["training_weight"], row=row), row["example_id"], row["row_uid"]),
        )
        if not passes or not fails:
            continue
        keep = min(len(passes), len(fails))
        selected.extend(passes[:keep])
        selected.extend(fails[:keep])
    return sorted(selected, key=row_sort_key)


def stratified_eval_uids(rows: list[dict[str, str]], *, eval_fraction: float) -> set[str]:
    if eval_fraction <= 0:
        return set()
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(row["clue_level"], row["label"])].append(row)

    eval_uids: set[str] = set()
    for group in grouped.values():
        ordered = sorted(group, key=lambda row: row["row_uid"])
        if len(ordered) <= 1:
            continue
        eval_count = max(1, min(len(ordered) - 1, round(len(ordered) * eval_fraction)))
        interval = len(ordered) / eval_count
        for index in range(eval_count):
            pick = min(len(ordered) - 1, int(round((index + 0.5) * interval - 0.5)))
            eval_uids.add(ordered[pick]["row_uid"])
    return eval_uids


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")


def count_by(rows: list[dict[str, str]], *fields: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        key = "/".join(row[field] for field in fields)
        counter[key] += 1
    return dict(sorted(counter.items()))


def category_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    return dict(
        sorted(
            Counter(
                category for row in rows for category in split_categories(row["failure_categories"])
            ).items()
        )
    )


def export_map_clue_review_training_data(
    csv_path: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    eval_fraction: float = 0.15,
    prefix: str = "map_clue_review",
) -> ExportResult:
    rows = read_ml_ready_csv(csv_path)
    validation_errors = validate_rows(rows)
    if validation_errors:
        raise ValueError(json.dumps({"validation_errors": validation_errors[:25]}, ensure_ascii=True))

    included = [row for row in rows if row["exclude_from_training"] == "no"]
    excluded = [row for row in rows if row["exclude_from_training"] == "yes"]
    balanced_critic = balanced_critic_rows(included)
    critic_eval_uids = stratified_eval_uids(balanced_critic, eval_fraction=eval_fraction)
    rewrite_rows = [
        row
        for row in included
        if row["label"] == "fail" and row["rewrite_needed"] == "yes" and row["rewritten_clue"]
    ]
    rewrite_eval_uids = stratified_eval_uids(rewrite_rows, eval_fraction=eval_fraction)
    negative_rows = [row for row in included if row["label"] == "fail"]

    stamp = timestamp()
    output_dir.mkdir(parents=True, exist_ok=True)
    all_rows_path = output_dir / f"{prefix}_rows_{stamp}.jsonl"
    critic_train_path = output_dir / f"{prefix}_critic_train_{stamp}.jsonl"
    critic_eval_path = output_dir / f"{prefix}_critic_eval_{stamp}.jsonl"
    rewrite_train_path = output_dir / f"{prefix}_rewrite_train_{stamp}.jsonl"
    rewrite_eval_path = output_dir / f"{prefix}_rewrite_eval_{stamp}.jsonl"
    negative_path = output_dir / f"map_clue_negative_{prefix}_{stamp}.jsonl"
    report_path = output_dir / f"{prefix}_manifest_{stamp}.json"

    critic_train_rows = [row for row in balanced_critic if row["row_uid"] not in critic_eval_uids]
    critic_eval_rows = [row for row in balanced_critic if row["row_uid"] in critic_eval_uids]
    rewrite_train_rows = [row for row in rewrite_rows if row["row_uid"] not in rewrite_eval_uids]
    rewrite_eval_rows = [row for row in rewrite_rows if row["row_uid"] in rewrite_eval_uids]

    write_jsonl(all_rows_path, [all_row_record(row) for row in rows])
    write_jsonl(critic_train_path, [critic_record(row) for row in critic_train_rows])
    write_jsonl(critic_eval_path, [critic_record(row) for row in critic_eval_rows])
    write_jsonl(rewrite_train_path, [rewrite_record(row) for row in rewrite_train_rows])
    write_jsonl(rewrite_eval_path, [rewrite_record(row) for row in rewrite_eval_rows])
    write_jsonl(negative_path, [negative_record(row) for row in negative_rows])

    report = {
        "created_at": now_iso(),
        "source_csv": str(csv_path),
        "source_row_count": len(rows),
        "included_count": len(included),
        "excluded_count": len(excluded),
        "balanced_critic_count": len(balanced_critic),
        "critic_train_count": len(critic_train_rows),
        "critic_eval_count": len(critic_eval_rows),
        "rewrite_train_count": len(rewrite_train_rows),
        "rewrite_eval_count": len(rewrite_eval_rows),
        "pass_rewrites_ignored_count": sum(
            1
            for row in included
            if row["label"] == "pass" and row["rewrite_needed"] == "yes" and row["rewritten_clue"]
        ),
        "negative_count": len(negative_rows),
        "counts_by_level_label_included": count_by(included, "clue_level", "label"),
        "counts_by_level_label_balanced_critic": count_by(balanced_critic, "clue_level", "label"),
        "excluded_reasons": dict(Counter(row["exclude_reason"] or "blank" for row in excluded)),
        "review_categories_included": category_counts(included),
        "failure_categories_included_fail": category_counts(
            [row for row in included if row["label"] == "fail"]
        ),
        "pass_rows_with_review_categories": sum(
            1 for row in included if row["label"] == "pass" and split_categories(row["failure_categories"])
        ),
        "answer_leaks": {
            "included_original_clue_count": sum(
                1 for row in included if answer_leak_tokens(row, "original_clue")
            ),
            "included_rewritten_clue_count": sum(
                1 for row in included if row["rewritten_clue"] and answer_leak_tokens(row, "rewritten_clue")
            ),
        },
        "outputs": {
            "all_rows_path": str(all_rows_path),
            "critic_train_path": str(critic_train_path),
            "critic_eval_path": str(critic_eval_path),
            "rewrite_train_path": str(rewrite_train_path),
            "rewrite_eval_path": str(rewrite_eval_path),
            "negative_path": str(negative_path),
            "report_path": str(report_path),
        },
        "format": {
            "all_rows": "All source rows as JSONL for audit and weighted local experiments.",
            "critic_train": "Balanced pass/fail chat JSONL for clue-level quality judging.",
            "critic_eval": "Held-out balanced pass/fail chat JSONL.",
            "rewrite_train": "Chat JSONL for rewriting failed clues with approved rewrites.",
            "rewrite_eval": "Held-out rewrite examples.",
            "negative": "Included failed rows in existing map learning-profile negative format.",
        },
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")

    return ExportResult(
        all_rows_path=all_rows_path,
        critic_train_path=critic_train_path,
        critic_eval_path=critic_eval_path,
        rewrite_train_path=rewrite_train_path,
        rewrite_eval_path=rewrite_eval_path,
        negative_path=negative_path,
        report_path=report_path,
        included_count=len(included),
        excluded_count=len(excluded),
        critic_train_count=len(critic_train_rows),
        critic_eval_count=len(critic_eval_rows),
        rewrite_train_count=len(rewrite_train_rows),
        rewrite_eval_count=len(rewrite_eval_rows),
        negative_count=len(negative_rows),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export ML-ready map clue review CSV to JSONL training artifacts.")
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--eval-fraction", type=float, default=0.15)
    parser.add_argument("--prefix", default="map_clue_review")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = export_map_clue_review_training_data(
        args.csv,
        args.out_dir,
        eval_fraction=args.eval_fraction,
        prefix=args.prefix,
    )
    print(
        json.dumps(
            {
                "all_rows_path": str(result.all_rows_path),
                "critic_train_path": str(result.critic_train_path),
                "critic_eval_path": str(result.critic_eval_path),
                "rewrite_train_path": str(result.rewrite_train_path),
                "rewrite_eval_path": str(result.rewrite_eval_path),
                "negative_path": str(result.negative_path),
                "report_path": str(result.report_path),
                "included_count": result.included_count,
                "excluded_count": result.excluded_count,
                "critic_train_count": result.critic_train_count,
                "critic_eval_count": result.critic_eval_count,
                "rewrite_train_count": result.rewrite_train_count,
                "rewrite_eval_count": result.rewrite_eval_count,
                "negative_count": result.negative_count,
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
