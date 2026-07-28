from __future__ import annotations

import json
import math
import html
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import daily_map_game
from tools import training_data_store

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TRAINING_DIR = PROJECT_DIR / "data" / "training"
DEFAULT_MODEL_PATH = DEFAULT_TRAINING_DIR / "map_selector_model_latest.json"
MODEL_VERSION = 2

PRESENTATION_NOTE_TOKENS = (
    "name being in each clue",
    "name in each clue",
    "answer in each clue",
)
MEDIUM_SCOPE_ANCHOR_RE = re.compile(
    r"\b(?:city|town|district|neighbou?rhood|borough|country|region|state|province|"
    r"national|local|community|coast|coastal|river|bay|harbou?r|waterfront|island|"
    r"peninsula|strait|valley|canal|park|road|route|university|campus|centre|center|"
    r"northern|southern|eastern|western|central|european|british|english|scottish|"
    r"welsh|irish|french|spanish|italian|german|japanese|american|australian)\b",
    re.IGNORECASE,
)
FORMER_HEIGHT_RECORD_RE = re.compile(
    r"\b(?:once|formerly|previously|used to be|was|were)\b.{0,80}?"
    r"\b(?:tallest|highest|largest|world(?:'s)? tallest|world(?:'s)? highest|"
    r"tallest (?:building|structure|tower|skyscraper|free-standing))\b",
    re.IGNORECASE,
)
FORMER_RECORD_HOOK_RE = re.compile(
    r"\b(?:once|formerly|previously|historically|used to)\b.{0,80}?"
    r"\b(?:held|holds?|had)\b.{0,50}?\b(?:record|world record)\b",
    re.IGNORECASE,
)
WEAK_ANALOGY_HOOK_RE = re.compile(
    r"\b(?:often|frequently|sometimes|commonly)?\s*(?:compared to|likened to|similar to)\b",
    re.IGNORECASE,
)
GENERIC_SKYLINE_HOOK_RE = re.compile(
    r"\b(?:defining feature of (?:the|its) city(?:'s)? skyline|dominates? (?:the|its) skyline|"
    r"iconic part of (?:the|its) skyline|stands out on (?:the|its) skyline)\b",
    re.IGNORECASE,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def clean_text(value: object, *, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or "").strip()))[:limit].strip()


def slug(value: object) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")
    return text or "unknown"


def numeric_score(value: object) -> int | None:
    verdict = str(value or "").strip().casefold()
    if verdict == "pass":
        return 10
    if verdict == "fail":
        return 0
    try:
        score = int(float(str(value)))
    except (TypeError, ValueError):
        return None
    if score < 0 or score > 10:
        return None
    return score


def bounded(value: object, *, low: float, high: float, default: float = 0.0) -> float:
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        number = default
    if not math.isfinite(number):
        number = default
    return min(high, max(low, number))


def split_list_text(value: object) -> list[str]:
    if isinstance(value, list):
        raw = value
    else:
        raw = str(value or "").split(";")
    return [clean_text(item, limit=120) for item in raw if clean_text(item, limit=120)]


def feedback_files(training_dir: Path = DEFAULT_TRAINING_DIR) -> list[Path]:
    return training_data_store.default_map_place_review_feedback_files(training_dir)


def read_feedback_rows(paths: list[Path]) -> list[dict[str, Any]]:
    return training_data_store.read_map_place_review_feedback_rows(paths)


def presentation_only_note(row: dict[str, Any]) -> bool:
    note = str(row.get("notes") or "").casefold()
    return any(token in note for token in PRESENTATION_NOTE_TOKENS)


def training_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if numeric_score(row.get("your_score")) is not None and not presentation_only_note(row)
    ]


def row_name(row: dict[str, Any]) -> str:
    return clean_text(row.get("canonical_name") or row.get("place"), limit=160)


def row_type(row: dict[str, Any]) -> str:
    return slug(row.get("place_type") or row.get("type"))


def row_difficulty(row: dict[str, Any]) -> str:
    return slug(row.get("difficulty"))


def row_categories(row: dict[str, Any]) -> list[str]:
    return [slug(category) for category in split_list_text(row.get("categories"))]


def row_clue(row: dict[str, Any], level: str) -> str:
    level = level.casefold()
    clues = row.get("clues")
    if isinstance(clues, dict):
        value = clean_text(clues.get(level), limit=500)
        if value:
            return value
    value = clean_text(row.get(f"{level}_clue"), limit=500)
    if value:
        return value
    facts = row.get("facts")
    if isinstance(facts, list):
        index = {"hard": 0, "medium": 1, "easy": 2}.get(level, -1)
        if 0 <= index < len(facts):
            return clean_text(facts[index], limit=500)
    fact_key = {"hard": "fact_1", "medium": "fact_2", "easy": "fact_3"}.get(level, "")
    return clean_text(row.get(fact_key), limit=500)


def row_machine_score(row: dict[str, Any]) -> float:
    return bounded(
        row.get("interest_score", row.get("machine_score", row.get("score", 0))),
        low=0,
        high=200,
    )


def clue_map_workoutability_score(text: object) -> int:
    context = clean_text(text, limit=320)
    if not context or daily_map_game.MAP_WORKOUTABILITY_VAGUE_RE.fullmatch(context):
        return 0
    anchors = {
        match.group(0).casefold()
        for match in daily_map_game.MAP_WORKOUTABILITY_ANCHOR_RE.finditer(context)
    }
    score = min(6, len(anchors) * 2)
    if daily_map_game.MAP_WORKOUTABILITY_ACTION_RE.search(context):
        score += 3
    if len(context.split()) >= 10:
        score += 1
    if any(character.isupper() for character in context[1:]):
        score += 1
    return min(12, score)


def medium_scope_score(text: object, row: dict[str, Any]) -> int:
    context = clean_text(text, limit=320)
    if not context or daily_map_game.MAP_WORKOUTABILITY_VAGUE_RE.fullmatch(context):
        return 0
    anchors = {match.group(0).casefold() for match in MEDIUM_SCOPE_ANCHOR_RE.finditer(context)}
    score = min(6, len(anchors) * 2)
    named_context = [
        row.get("country_name") or row.get("country"),
        row.get("admin1"),
    ]
    if any(str(value or "").strip() and str(value).casefold() in context.casefold() for value in named_context):
        score += 2
    if re.search(r"\b(?:in|from|of|across|through|spans|connects|located|based|serves|used by|home of|home to)\b", context, re.IGNORECASE):
        score += 1
    if len(context.split()) >= 10:
        score += 1
    if any(character.isupper() for character in context[1:]):
        score += 1
    return min(12, score)


def hard_hook_score(text: object) -> int:
    context = clean_text(text, limit=320)
    if not context or daily_map_game.MAP_WORKOUTABILITY_VAGUE_RE.fullmatch(context):
        return 0
    specificity = daily_map_game.hard_hook_specificity_score(context)
    score = daily_map_game.fact_interest_score(context)
    if specificity >= 7:
        score += min(6, specificity - 3)
    else:
        score -= 5
    if daily_map_game.MAP_HARD_HOOK_STATIC_DESCRIPTION_RE.search(context):
        score -= 3
    if daily_map_game.clue_is_location_framed_without_hook(context):
        score -= 3
    if FORMER_HEIGHT_RECORD_RE.search(context):
        score -= 4
    if FORMER_RECORD_HOOK_RE.search(context):
        score -= 3
    if WEAK_ANALOGY_HOOK_RE.search(context):
        score -= 3
    if GENERIC_SKYLINE_HOOK_RE.search(context):
        score -= 3
    return max(0, min(12, score))


def feature_dict(row: dict[str, Any]) -> dict[str, float]:
    hard = row_clue(row, "hard")
    medium = row_clue(row, "medium")
    easy = row_clue(row, "easy")
    features: dict[str, float] = {
        "num:machine_score": row_machine_score(row) / 200.0,
        "num:base_score": bounded(row.get("base_score"), low=0, high=160) / 160.0,
        "num:feedback_adjustment": bounded(row.get("feedback_adjustment"), low=-80, high=80) / 80.0,
        "num:persuading_fact_count": bounded(row.get("persuading_fact_count"), low=0, high=5) / 5.0,
        "num:workoutability_score": bounded(row.get("workoutability_score"), low=0, high=12) / 12.0,
        "num:hard_hook_score": hard_hook_score(hard) / 12.0,
        "num:medium_scope_score": medium_scope_score(medium, row) / 12.0,
        "num:easy_map_score": clue_map_workoutability_score(easy) / 12.0,
        "flag:former_height_record": 1.0 if FORMER_HEIGHT_RECORD_RE.search(hard) else 0.0,
        "flag:former_record_hook": 1.0 if FORMER_RECORD_HOOK_RE.search(hard) else 0.0,
        "flag:weak_analogy_hook": 1.0 if WEAK_ANALOGY_HOOK_RE.search(hard) else 0.0,
        "flag:generic_skyline_hook": 1.0 if GENERIC_SKYLINE_HOOK_RE.search(hard) else 0.0,
        "flag:retry_candidate": 1.0
        if str(row.get("source") or "").casefold().endswith("retry") or str(row.get("existing_retry") or "").casefold() == "true"
        else 0.0,
    }
    place_type = row_type(row)
    difficulty = row_difficulty(row)
    features[f"type:{place_type}"] = 1.0
    features[f"difficulty:{difficulty}"] = 1.0
    for category in row_categories(row):
        features[f"category:{category}"] = 1.0
    return features


def solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float]:
    n = len(vector)
    augmented = [matrix[i][:] + [vector[i]] for i in range(n)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-10:
            augmented[column][column] += 1e-8
            pivot = column
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        if abs(divisor) < 1e-12:
            divisor = 1e-12
        for index in range(column, n + 1):
            augmented[column][index] /= divisor
        for row in range(n):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor == 0:
                continue
            for index in range(column, n + 1):
                augmented[row][index] -= factor * augmented[column][index]
    return [augmented[row][n] for row in range(n)]


def fit_model(rows: list[dict[str, Any]], *, ridge: float = 1.25) -> dict[str, Any]:
    usable_rows = training_rows(rows)
    if not usable_rows:
        return {
            "version": MODEL_VERSION,
            "created_at": now_iso(),
            "row_count": 0,
            "feature_count": 0,
            "intercept": 5.0,
            "coefficients": {},
            "mean_score": 5.0,
            "training_mae": None,
            "baseline_mae": None,
        }
    feature_rows = [feature_dict(row) for row in usable_rows]
    feature_names = sorted({name for features in feature_rows for name in features})
    y = [float(numeric_score(row.get("your_score")) or 0) for row in usable_rows]
    width = len(feature_names) + 1
    xtx = [[0.0 for _ in range(width)] for _ in range(width)]
    xty = [0.0 for _ in range(width)]
    for features, target in zip(feature_rows, y):
        vector = [1.0, *[features.get(name, 0.0) for name in feature_names]]
        for i, left in enumerate(vector):
            xty[i] += left * target
            for j, right in enumerate(vector):
                xtx[i][j] += left * right
    for index in range(1, width):
        xtx[index][index] += ridge
    coefficients_vector = solve_linear_system(xtx, xty)
    intercept = coefficients_vector[0]
    coefficients = {
        name: coefficients_vector[index + 1]
        for index, name in enumerate(feature_names)
        if abs(coefficients_vector[index + 1]) >= 1e-8
    }
    predictions = [
        clamp_score(intercept + sum(coefficients.get(name, 0.0) * value for name, value in features.items()))
        for features in feature_rows
    ]
    mean_score = sum(y) / len(y)
    training_mae = sum(abs(prediction - target) for prediction, target in zip(predictions, y)) / len(y)
    baseline_mae = sum(abs(mean_score - target) for target in y) / len(y)
    sorted_coefficients = sorted(coefficients.items(), key=lambda item: item[1])
    return {
        "version": MODEL_VERSION,
        "created_at": now_iso(),
        "row_count": len(usable_rows),
        "feature_count": len(feature_names),
        "ridge": ridge,
        "intercept": intercept,
        "coefficients": coefficients,
        "mean_score": mean_score,
        "training_mae": training_mae,
        "baseline_mae": baseline_mae,
        "top_positive_features": [
            {"feature": name, "weight": round(weight, 4)}
            for name, weight in sorted_coefficients[-12:][::-1]
        ],
        "top_negative_features": [
            {"feature": name, "weight": round(weight, 4)}
            for name, weight in sorted_coefficients[:12]
        ],
    }


def clamp_score(value: float) -> float:
    if not math.isfinite(value):
        return 5.0
    return min(10.0, max(0.0, value))


def load_model(path: Path = DEFAULT_MODEL_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) and payload.get("version") == MODEL_VERSION else {}


def save_model(model: dict[str, Any], path: Path = DEFAULT_MODEL_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model, indent=2, ensure_ascii=True), encoding="utf-8")


def build_model_from_training_dir(training_dir: Path = DEFAULT_TRAINING_DIR) -> dict[str, Any]:
    return fit_model(read_feedback_rows(feedback_files(training_dir)))


def predict_score(model: dict[str, Any], row: dict[str, Any]) -> dict[str, float]:
    if not model:
        return {}
    coefficients = model.get("coefficients")
    if not isinstance(coefficients, dict):
        return {}
    features = feature_dict(row)
    raw = float(model.get("intercept", model.get("mean_score", 5.0)) or 5.0)
    known_weight = 0.0
    total_weight = 0.0
    for name, value in features.items():
        magnitude = abs(value)
        total_weight += magnitude
        if name in coefficients:
            known_weight += magnitude
            raw += float(coefficients.get(name) or 0.0) * value
    coverage = 1.0 if total_weight <= 0 else known_weight / total_weight
    row_count = int(model.get("row_count") or 0)
    row_factor = min(1.0, row_count / 200.0)
    confidence = min(0.95, max(0.2, 0.25 + 0.5 * row_factor + 0.25 * coverage))
    predicted = clamp_score(raw)
    heuristic_score = min(10.0, row_machine_score(row) / 16.0)
    rank_score = ((predicted * confidence) + (heuristic_score * (1.0 - confidence))) * 10.0
    return {
        "ml_score": round(predicted, 3),
        "ml_confidence": round(confidence, 3),
        "ml_rank_score": round(rank_score, 3),
        "ml_feature_coverage": round(coverage, 3),
    }
