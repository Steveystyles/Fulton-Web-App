from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools import training_data_store

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TRAINING_DIR = PROJECT_DIR / "data" / "training"
DEFAULT_MODEL_PATH = DEFAULT_TRAINING_DIR / "map_clue_quality_model_latest.json"
MODEL_VERSION = 1
LEVELS = ("hard", "medium", "easy")
LABELS = ("fail", "pass")
TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?", re.IGNORECASE)
SIGNAL_STOPWORDS = {
    "about",
    "after",
    "along",
    "also",
    "and",
    "are",
    "at",
    "before",
    "being",
    "between",
    "but",
    "by",
    "for",
    "from",
    "had",
    "has",
    "have",
    "here",
    "in",
    "inside",
    "into",
    "is",
    "it",
    "its",
    "near",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "was",
    "were",
    "where",
    "which",
    "with",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def clue_tokens(text: object, *, place_type: object = "") -> list[str]:
    words = TOKEN_RE.findall(clean_text(text).casefold())
    tokens = [f"word:{word}" for word in words]
    tokens.extend(
        f"bigram:{left}_{right}"
        for left, right in zip(words, words[1:])
    )
    normalized_type = re.sub(r"[^a-z0-9]+", "_", clean_text(place_type).casefold()).strip("_")
    if normalized_type:
        tokens.append(f"type:{normalized_type}")
    return sorted(set(tokens))


def latest_exported_rows_file(training_dir: Path = DEFAULT_TRAINING_DIR) -> Path | None:
    files = sorted(training_dir.glob("map_clue_review_rows_*.jsonl"))
    return files[-1] if files else None


def read_exported_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = line.strip()
        if not text:
            continue
        payload = json.loads(text)
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        level = clean_text(metadata.get("clue_level")).casefold()
        label = clean_text(metadata.get("label")).casefold()
        if (
            level not in LEVELS
            or label not in LABELS
            or bool(metadata.get("exclude_from_training"))
        ):
            continue
        try:
            weight = float(metadata.get("training_weight") or 0)
        except (TypeError, ValueError):
            weight = 0
        clue = clean_text(payload.get("original_clue"))
        if not clue or weight <= 0:
            continue
        rows.append(
            {
                "row_id": clean_text(metadata.get("source_row_uid")) or f"{path.name}:{line_number}",
                "level": level,
                "label": label,
                "clue": clue,
                "place_type": clean_text(metadata.get("place_type")),
                "weight": weight,
                "source": "labelled_1000",
            }
        )
    return rows


def read_human_feedback_rows(training_dir: Path = DEFAULT_TRAINING_DIR) -> list[dict[str, Any]]:
    paths = training_data_store.default_map_place_review_feedback_files(training_dir)
    try:
        feedback_rows = training_data_store.read_map_place_review_feedback_rows(paths)
    except (OSError, json.JSONDecodeError):
        return []
    rows: list[dict[str, Any]] = []
    for index, feedback in enumerate(feedback_rows):
        clue_reviews = feedback.get("clue_reviews")
        clues = feedback.get("clues")
        if not isinstance(clue_reviews, dict):
            clue_reviews = {}
        if not isinstance(clues, dict):
            clues = {}
        for level in LEVELS:
            review = clue_reviews.get(level)
            if not isinstance(review, dict):
                review = {}
            label = clean_text(review.get("pass_fail")).casefold()
            clue = clean_text(review.get("clue") or clues.get(level))
            if label not in LABELS or not clue:
                continue
            rows.append(
                {
                    "row_id": (
                        f"human:{feedback.get('candidate_id') or feedback.get('place') or index}:"
                        f"{level}:{index}"
                    ),
                    "level": level,
                    "label": label,
                    "clue": clue,
                    "place_type": clean_text(feedback.get("type") or feedback.get("place_type")),
                    "weight": 3.0,
                    "source": "human_feedback",
                }
            )
    return rows


def training_rows(training_dir: Path = DEFAULT_TRAINING_DIR) -> tuple[list[dict[str, Any]], list[str]]:
    sources: list[str] = []
    rows_file = latest_exported_rows_file(training_dir)
    rows: list[dict[str, Any]] = []
    if rows_file is not None:
        rows.extend(read_exported_rows(rows_file))
        sources.append(str(rows_file))
    human_paths = training_data_store.default_map_place_review_feedback_files(training_dir)
    human_rows = read_human_feedback_rows(training_dir)
    rows.extend(human_rows)
    sources.extend(str(path) for path in human_paths)
    return rows, sources


def split_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    train: list[dict[str, Any]] = []
    validation: list[dict[str, Any]] = []
    for row in rows:
        digest = hashlib.sha256(str(row["row_id"]).encode("utf-8")).digest()
        (validation if digest[0] < 51 else train).append(row)
    return train, validation


def fit_level(rows: list[dict[str, Any]], *, max_features: int = 5000, alpha: float = 0.75) -> dict[str, Any]:
    document_weights = {label: 0.0 for label in LABELS}
    token_counts = {label: Counter() for label in LABELS}
    global_counts: Counter[str] = Counter()
    for row in rows:
        label = str(row["label"])
        weight = float(row["weight"])
        tokens = clue_tokens(row["clue"], place_type=row.get("place_type"))
        document_weights[label] += weight
        token_counts[label].update({token: weight for token in tokens})
        global_counts.update({token: weight for token in tokens})
    vocabulary = {
        token
        for token, _count in global_counts.most_common(max_features)
    }
    token_totals = {
        label: sum(count for token, count in token_counts[label].items() if token in vocabulary)
        for label in LABELS
    }
    total_documents = sum(document_weights.values())
    vocabulary_size = max(1, len(vocabulary))
    return {
        "row_count": len(rows),
        "document_weights": document_weights,
        "token_totals": token_totals,
        "token_counts": {
            label: {
                token: round(float(count), 6)
                for token, count in token_counts[label].items()
                if token in vocabulary
            }
            for label in LABELS
        },
        "vocabulary_size": vocabulary_size,
        "alpha": alpha,
        "prior_alpha": 1.0,
        "total_document_weight": total_documents,
    }


def predict_level(
    model: dict[str, Any],
    level: str,
    clue: object,
    *,
    place_type: object = "",
) -> dict[str, Any]:
    level_model = (model.get("levels") or {}).get(level)
    if not isinstance(level_model, dict):
        return {}
    tokens = clue_tokens(clue, place_type=place_type)
    vocabulary_size = int(level_model.get("vocabulary_size") or 1)
    alpha = float(level_model.get("alpha") or 0.75)
    prior_alpha = float(level_model.get("prior_alpha") or 1.0)
    total_document_weight = float(level_model.get("total_document_weight") or 0)
    log_scores: dict[str, float] = {}
    contributions: dict[str, float] = {}
    for label in LABELS:
        document_weight = float((level_model.get("document_weights") or {}).get(label) or 0)
        prior = (document_weight + prior_alpha) / (
            total_document_weight + (prior_alpha * len(LABELS))
        )
        token_total = float((level_model.get("token_totals") or {}).get(label) or 0)
        denominator = token_total + (alpha * vocabulary_size)
        counts = (level_model.get("token_counts") or {}).get(label) or {}
        score = math.log(max(prior, 1e-12))
        for token in tokens:
            if token not in counts and not any(
                token in ((level_model.get("token_counts") or {}).get(other) or {})
                for other in LABELS
            ):
                continue
            score += math.log((float(counts.get(token) or 0) + alpha) / denominator)
        log_scores[label] = score
    log_odds = max(-30.0, min(30.0, log_scores["pass"] - log_scores["fail"]))
    pass_probability = 1.0 / (1.0 + math.exp(-log_odds))
    pass_counts = (level_model.get("token_counts") or {}).get("pass") or {}
    fail_counts = (level_model.get("token_counts") or {}).get("fail") or {}
    pass_denominator = float((level_model.get("token_totals") or {}).get("pass") or 0) + (
        alpha * vocabulary_size
    )
    fail_denominator = float((level_model.get("token_totals") or {}).get("fail") or 0) + (
        alpha * vocabulary_size
    )
    for token in tokens:
        if token not in pass_counts and token not in fail_counts:
            continue
        contributions[token] = math.log(
            (float(pass_counts.get(token) or 0) + alpha) / pass_denominator
        ) - math.log(
            (float(fail_counts.get(token) or 0) + alpha) / fail_denominator
        )
    negative_signals = [
        token.split(":", 1)[-1].replace("_", " ")
        for token, contribution in sorted(contributions.items(), key=lambda item: item[1])
        if contribution < 0
        and any(
            len(word) >= 4 and word not in SIGNAL_STOPWORDS
            for word in token.split(":", 1)[-1].split("_")
        )
    ][:5]
    return {
        "level": level,
        "pass_probability": round(pass_probability, 4),
        "pass_log_odds": round(log_odds, 4),
        "predicted_label": "pass" if pass_probability >= 0.5 else "fail",
        "confidence": round(abs(pass_probability - 0.5) * 2, 4),
        "negative_signals": negative_signals,
    }


def evaluate(model: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"row_count": 0, "accuracy": None, "balanced_accuracy": None}
    correct = 0
    per_label = {label: {"correct": 0, "total": 0} for label in LABELS}
    log_loss = 0.0
    for row in rows:
        prediction = predict_level(
            model,
            str(row["level"]),
            row["clue"],
            place_type=row.get("place_type"),
        )
        probability = min(1 - 1e-8, max(1e-8, float(prediction["pass_probability"])))
        predicted = str(prediction["predicted_label"])
        label = str(row["label"])
        per_label[label]["total"] += 1
        if predicted == label:
            correct += 1
            per_label[label]["correct"] += 1
        log_loss -= math.log(probability if label == "pass" else 1 - probability)
    recalls = [
        values["correct"] / values["total"]
        for values in per_label.values()
        if values["total"]
    ]
    return {
        "row_count": len(rows),
        "accuracy": round(correct / len(rows), 4),
        "balanced_accuracy": round(sum(recalls) / len(recalls), 4) if recalls else None,
        "log_loss": round(log_loss / len(rows), 4),
        "label_counts": {
            label: values["total"]
            for label, values in per_label.items()
        },
    }


def fit_model(rows: list[dict[str, Any]], *, sources: list[str] | None = None) -> dict[str, Any]:
    train, validation = split_rows(rows)
    evaluation_model = {
        "version": MODEL_VERSION,
        "levels": {
            level: fit_level([row for row in train if row["level"] == level])
            for level in LEVELS
        },
    }
    validation_metrics = evaluate(evaluation_model, validation)
    return {
        "version": MODEL_VERSION,
        "created_at": now_iso(),
        "row_count": len(rows),
        "source_files": sources or [],
        "source_counts": dict(Counter(str(row["source"]) for row in rows)),
        "level_counts": {
            level: dict(Counter(str(row["label"]) for row in rows if row["level"] == level))
            for level in LEVELS
        },
        "validation": validation_metrics,
        "validation_by_level": {
            level: evaluate(
                evaluation_model,
                [row for row in validation if row["level"] == level],
            )
            for level in LEVELS
        },
        "levels": {
            level: fit_level([row for row in rows if row["level"] == level])
            for level in LEVELS
        },
    }


def build_model_from_training_dir(training_dir: Path = DEFAULT_TRAINING_DIR) -> dict[str, Any]:
    rows, sources = training_rows(training_dir)
    return fit_model(rows, sources=sources)


def save_model(model: dict[str, Any], path: Path = DEFAULT_MODEL_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(model, indent=2, ensure_ascii=True), encoding="utf-8")
    temporary.replace(path)


def load_model(path: Path = DEFAULT_MODEL_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("version") != MODEL_VERSION:
        return {}
    return payload
