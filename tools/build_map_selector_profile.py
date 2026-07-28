from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from tools import training_data_store

DEFAULT_TRAINING_DIR = PROJECT_DIR / "data" / "training"

PRESENTATION_NOTE_TOKENS = (
    "name being in each clue",
    "name in each clue",
    "answer in each clue",
)
NOTE_CATEGORY_RULES = (
    (
        "subjective_fact",
        ("subjective", "not helpful", "true of any", "could be any", "generic", "recognisable", "recognizable"),
        "Avoid subjective or generic facts; every fact should be concrete, specific, and useful for identifying the place.",
    ),
    (
        "vague_fact",
        ("vague", "unspecific", "not specific", "nothing specific", "facts let this one down"),
        "Replace vague facts with specific events, records, visual features, or map-visible details.",
    ),
    (
        "wording_clarity",
        ("grammar", "feels a bit off", "maybe change", "better chance to guess"),
        "Keep clue wording direct and readable. If a pronoun hides the target type, use phrasing such as 'this bridge' or 'this stadium' to help the player work it out.",
    ),
    (
        "needs_specific_incident",
        ("what is the specific incident", "should be about a specific", "make it about a specific", "preferred to hear about the incident", "prefer to see it more specific"),
        "Choose the recognition hook before choosing the place. Prefer a unique, specific incident or story; allow another hook type only when it is equally recognisable.",
    ),
    (
        "insufficient_event_detail",
        ("bland", "not very informative", "more information about the event", "more detail about the event"),
        "Keep the selected recognition hook, but retain the people, action, outcome, consequence, record, or significance that makes it memorable.",
    ),
    (
        "missing_place_link",
        ("doesn't mention where", "does not mention where", "happened here", "took place"),
        "Tie the hard-clue recognition hook to the target with an answer-safe phrase such as 'here', 'on this pitch', 'inside this building', or 'at this site'.",
    ),
    (
        "medium_filler",
        ("bland", "not worded fully", "draw enormous crowds", "historic venue"),
        "Make medium reduce the geographic search area directly; remove generic crowd, popularity, prestige, fame, or historic-venue padding.",
    ),
    (
        "unnamed_cultural_reference",
        ("famous collection", "well-known writer", "vague and unhelpful", "vague amd unhelpful"),
        "Name an answer-safe creator, person, group, or work instead of using a vague famous or well-known label; if a title leaks the target, name its creator and explain the connection.",
    ),
    (
        "niche_fact",
        ("niche", "not particularly well known", "not well known"),
        "Avoid hard clues that depend on niche knowledge unless the fact is memorable, clearly interesting, and strongly identifies the place.",
    ),
    (
        "weak_colour_hook",
        ("colour", "color", "paint"),
        "Do not rely on colour or paint as the main hard clue unless it is tied to a memorable event, person, record, or story.",
    ),
    (
        "repeated_fact",
        ("essentially the same", "same info", "same information", "repeated", "repeat"),
        "Make the three facts distinct; do not restate the same stadium, event, or location clue in different wording.",
    ),
    (
        "poor_map_guessability",
        ("guessabl", "where to look", "finding", "find its location", "start finding", "location is not part"),
        "Prefer places with a clear map route; include city, water/route/district/shape anchors when the name alone does not locate it.",
    ),
    (
        "answer_leak",
        ("giving the answer", "gives the answer", "name being in each clue", "name in each clue", "answer in each clue"),
        "Do not leak the answer or a near-alias inside the playable facts.",
    ),
    (
        "needs_significant_event",
        ("finals", "significant things", "happened there", "major event"),
        "For stadiums and venues, require a particular major final, historic match, incident, result, or record-setting moment; architecture and crowd features are not substitutes.",
    ),
    (
        "poor_narrowing_ladder",
        ("narrow", "scope", "work it out", "beat the game", "succeed", "challenging", "help you find", "find it"),
        "Build each clue ladder as a narrowing path: distinctive hook, then area/context clue, then a practical map anchor.",
    ),
    (
        "bad_difficulty_progression",
        (
            "difficulty progression",
            "progression is wrong",
            "wrong difficulty",
            "dont agree with difficulty",
            "don't agree with difficulty",
            "easy fact is weak",
            "would have scored higher as hard",
            "would have scored higher as a hard",
            "higher as hard clue",
            "higher as a hard clue",
        ),
        "Order clues by solving value: hard should hook interest, medium should narrow the area, and easy should add the strongest practical map anchor.",
    ),
    (
        "off_target_fact",
        (
            "about the engineer",
            "more about the engineer",
            "about the designer",
            "more about the designer",
            "not about the place",
            "about the person",
            "famous by association",
        ),
        "Keep facts centred on the target place; associated people are useful only when they make the place itself more recognisable.",
    ),
    (
        "dry_stat_fact",
        ("just stats", "only stats", "dry stats", "capacity", "mph", "magnitude"),
        "Avoid dry numerical statistics unless they are famous, surprising, and help the player narrow or remember the place.",
    ),
    (
        "former_record_weak_hook",
        ("used to be", "isnt the tallest", "isn't the tallest", "not the tallest", "used to be tallest", "once the tallest"),
        "Avoid former-height-record hooks as hard clues. Prefer a current record, specific incident, story, achievement, tradition, or other recognition hook that remains distinctive.",
    ),
)
CLUE_LEVEL_GUIDANCE = {
    "hard": "Select one source-backed recognition hook first. Prefer a unique incident or story, while allowing a genuinely distinctive record, achievement, discovery, association, tradition, natural occurrence, or cultural moment.",
    "medium": "Materially reduce the geographic search area to a useful country, region, culture, language, city, or equivalent scope; an additional place-owned fact may add character.",
    "easy": "Narrow within medium's area to a borough, district, quarter, neighbourhood, city sector, river crossing, park, station, or named local landmark visible at city zoom.",
}
QUALIFIED_HARD_PASS_TOKENS = (
    "just passes",
    "technically passes",
    "scrapes through",
    "dont like",
    "don't like",
    "would have preferred",
    "prefer to see",
    "boring",
    "flowery",
    "grammar",
    "feels a bit off",
    "maybe change",
    "better chance to guess",
    "unclear",
    "not very interesting",
    "not something uniquely interesting",
    "too vague",
    "bit too vague",
    "should be about a specific",
    "make it about a specific",
    "what is the specific",
    "just data",
    "just reads",
    "padding",
    "could be dropped",
    "expanded on",
    "about the designer",
    "more about the designer",
    "famous by association",
    "rather than something interesting about the location itself",
    "needs context",
    "niche",
    "not particularly well known",
    "not well known",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def latest_feedback_files(training_dir: Path) -> list[Path]:
    matches = training_data_store.legacy_map_place_review_feedback_files(training_dir)
    if not matches:
        raise ValueError(f"No map_place_review_feedback_*.json files found in {training_dir}.")
    return matches


def row_score(row: dict[str, Any]) -> int | None:
    verdict = str(row.get("your_score") or "").strip().casefold()
    if verdict == "pass":
        return 10
    if verdict == "fail":
        return 0
    try:
        score = int(float(str(row.get("your_score"))))
    except (TypeError, ValueError):
        return None
    if score < 0 or score > 10:
        return None
    return score


def normalized_clue_level(value: object) -> str:
    level = str(value or "").strip().casefold()
    if level in {"hard", "medium", "easy"}:
        return level
    return ""


def row_clue_scores(row: dict[str, Any]) -> dict[str, int]:
    scores: dict[str, int] = {}
    raw_scores = row.get("clue_scores")
    if isinstance(raw_scores, dict):
        for level, value in raw_scores.items():
            normalized_level = normalized_clue_level(level)
            if not normalized_level:
                continue
            score = row_score({"your_score": value})
            if score is not None:
                scores[normalized_level] = score
    clue_uses = row.get("clue_uses")
    if isinstance(clue_uses, list):
        for clue in clue_uses:
            if not isinstance(clue, dict):
                continue
            normalized_level = normalized_clue_level(clue.get("level"))
            if not normalized_level or normalized_level in scores:
                continue
            score = row_score({"your_score": clue.get("yourScore")})
            if score is not None:
                scores[normalized_level] = score
    return scores


def normalized_pass_fail(value: object) -> str:
    verdict = str(value or "").strip().casefold()
    return verdict if verdict in {"pass", "fail"} else ""


def row_hard_review(row: dict[str, Any]) -> dict[str, str]:
    raw_review = row.get("hard_review")
    if not isinstance(raw_review, dict):
        return {}
    verdict = normalized_pass_fail(raw_review.get("pass_fail") or raw_review.get("passFail"))
    clues = row.get("clues") if isinstance(row.get("clues"), dict) else {}
    clue = str(raw_review.get("clue") or clues.get("hard") or "").strip()
    fact = str(raw_review.get("fact") or "").strip()
    reason = str(raw_review.get("reason") or "").strip()
    better_direction = str(raw_review.get("better_direction") or raw_review.get("betterDirection") or "").strip()
    if not verdict and not reason and not better_direction:
        return {}
    return {
        "pass_fail": verdict,
        "clue": clue,
        "fact": fact,
        "reason": reason,
        "better_direction": better_direction,
    }


def presentation_only_note(row: dict[str, Any]) -> bool:
    note = str(row.get("notes") or "").casefold()
    return any(token in note for token in PRESENTATION_NOTE_TOKENS)


def classify_note_categories(note: object) -> list[str]:
    normalized = str(note or "").casefold()
    return [
        category
        for category, tokens, _guidance in NOTE_CATEGORY_RULES
        if any(token in normalized for token in tokens)
    ]


def unique_texts(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = " ".join(text.casefold().split())
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def is_qualified_hard_pass(review: dict[str, str]) -> bool:
    if review.get("pass_fail") != "pass":
        return False
    text = " ".join(
        [
            review.get("reason", ""),
            review.get("better_direction", ""),
        ]
    ).casefold()
    return any(token in text for token in QUALIFIED_HARD_PASS_TOKENS)


def read_feedback_rows(paths: list[Path]) -> list[dict[str, Any]]:
    return training_data_store.read_map_place_review_feedback_rows(paths)


def canonical_row_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): canonical_row_value(child)
            for key, child in sorted(value.items())
            if str(key) != "_source_file"
        }
    if isinstance(value, list):
        return [canonical_row_value(child) for child in value]
    if isinstance(value, str):
        return " ".join(value.strip().split())
    return value


def row_dedupe_signature(row: dict[str, Any]) -> str:
    return json.dumps(canonical_row_value(row), sort_keys=True, ensure_ascii=True)


def dedupe_feedback_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    unique_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        signature = row_dedupe_signature(row)
        if signature in seen:
            continue
        seen.add(signature)
        unique_rows.append(row)
    return unique_rows, len(rows) - len(unique_rows)


def mean_adjustment(scores: list[int], *, multiplier: int = 6) -> int:
    if not scores:
        return 0
    return int(round((statistics.mean(scores) - 5) * multiplier))


def build_profile(rows: list[dict[str, Any]], *, source_files: list[Path]) -> dict[str, Any]:
    source_row_count = len(rows)
    rows, duplicate_row_count = dedupe_feedback_rows(rows)
    place_scores: dict[str, int] = {}
    type_scores: dict[str, list[int]] = defaultdict(list)
    category_scores: dict[str, list[int]] = defaultdict(list)
    clue_level_scores: dict[str, list[int]] = defaultdict(list)
    note_category_counts: dict[str, int] = defaultdict(int)
    note_examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    hard_review_counts: dict[str, int] = defaultdict(int)
    hard_review_examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    qualified_hard_pass_count = 0
    ignored_rows: list[dict[str, Any]] = []
    accepted_rows = 0

    for row in rows:
        score = row_score(row)
        place = str(row.get("place") or "").strip()
        clue_scores = row_clue_scores(row)
        hard_review = row_hard_review(row)
        if not place or (score is None and not clue_scores and not hard_review):
            continue
        if score is not None and presentation_only_note(row):
            ignored_rows.append({"place": place, "reason": "presentation_only_note", "score": score})
            continue
        accepted_rows += 1
        note = str(row.get("notes") or "").strip()
        note_texts = [note]
        if hard_review:
            note_texts.extend([hard_review.get("reason", ""), hard_review.get("better_direction", "")])
            note_texts = unique_texts(note_texts)
            verdict = hard_review.get("pass_fail") or "unmarked"
            hard_review_counts[verdict] += 1
            example_bucket = "qualified_pass" if is_qualified_hard_pass(hard_review) else verdict
            if example_bucket == "qualified_pass":
                qualified_hard_pass_count += 1
            if len(hard_review_examples[example_bucket]) < 8:
                hard_review_examples[example_bucket].append(
                    {
                        "place": place,
                        "clue": hard_review.get("clue", ""),
                        "reason": hard_review.get("reason", ""),
                        "better_direction": hard_review.get("better_direction", ""),
                    }
                )
        if score is not None:
            for note_text in note_texts:
                for note_category in classify_note_categories(note_text):
                    note_category_counts[note_category] += 1
                    if len(note_examples[note_category]) < 5:
                        note_examples[note_category].append(
                            {
                                "place": place,
                                "score": score,
                                "note": note_text,
                            }
                        )
            place_scores[place] = score
            place_type = str(row.get("type") or "").strip()
            if place_type:
                type_scores[place_type].append(score)
            categories = str(row.get("categories") or "").strip()
            for category in [part.strip() for part in categories.split(";") if part.strip()]:
                category_scores[category].append(score)
        for level, clue_score in clue_scores.items():
            clue_level_scores[level].append(clue_score)
        if score is None and hard_review:
            for note_text in note_texts:
                for note_category in classify_note_categories(note_text):
                    note_category_counts[note_category] += 1
                    if len(note_examples[note_category]) < 5:
                        note_examples[note_category].append(
                            {
                                "place": place,
                                "score": "",
                                "note": note_text,
                            }
                        )

    type_adjustments = {
        place_type: mean_adjustment(scores)
        for place_type, scores in sorted(type_scores.items())
        if len(scores) >= 2
    }
    category_adjustments = {
        category: mean_adjustment(scores, multiplier=3)
        for category, scores in sorted(category_scores.items())
        if len(scores) >= 3
    }
    clue_level_score_summary = {
        level: {
            "count": len(scores),
            "mean_score": round(statistics.mean(scores), 2),
            "low_score_count": len([score for score in scores if score <= 3]),
        }
        for level, scores in sorted(clue_level_scores.items())
        if scores
    }
    hard_review_count = sum(hard_review_counts.values())
    hard_pass_count = hard_review_counts.get("pass", 0)
    hard_fail_count = hard_review_counts.get("fail", 0)
    strong_hard_pass_count = max(0, hard_pass_count - qualified_hard_pass_count)
    return {
        "created_at": now_iso(),
        "source_files": [str(path) for path in source_files],
        "row_count": source_row_count,
        "unique_row_count": len(rows),
        "duplicate_row_count": duplicate_row_count,
        "accepted_row_count": accepted_rows,
        "ignored_rows": ignored_rows,
        "place_scores": place_scores,
        "type_adjustments": type_adjustments,
        "category_adjustments": category_adjustments,
        "clue_level_scores": clue_level_score_summary,
        "hard_clue_review": {
            "count": hard_review_count,
            "pass_count": hard_pass_count,
            "fail_count": hard_fail_count,
            "strong_pass_count": strong_hard_pass_count,
            "qualified_pass_count": qualified_hard_pass_count,
            "unmarked_count": hard_review_counts.get("unmarked", 0),
            "pass_rate": round(hard_pass_count / hard_review_count, 3) if hard_review_count else None,
            "pass_examples": hard_review_examples.get("pass", []),
            "qualified_pass_examples": hard_review_examples.get("qualified_pass", []),
            "fail_examples": hard_review_examples.get("fail", []),
            "guidance": (
                "Hard clue pass/fail reviews are the strongest signal for writing the first clue. "
                "Strong pass examples show acceptable place-owned hooks. Qualified passes are technically acceptable but should not be copied without improving the issue described in the reason. "
                "Failed examples and better_direction fields show what to avoid and how to rewrite."
            ),
        },
        "clue_level_guidance": [
            {
                "level": level,
                "count": summary["count"],
                "mean_score": summary["mean_score"],
                "low_score_count": summary["low_score_count"],
                "guidance": CLUE_LEVEL_GUIDANCE[level],
            }
            for level, summary in clue_level_score_summary.items()
            if level in CLUE_LEVEL_GUIDANCE
            and (summary["mean_score"] < 7 or summary["low_score_count"] > 0)
        ],
        "note_category_counts": dict(sorted(note_category_counts.items())),
        "note_guidance": [
            {
                "category": category,
                "count": note_category_counts[category],
                "guidance": guidance,
                "examples": note_examples.get(category, []),
            }
            for category, _tokens, guidance in NOTE_CATEGORY_RULES
            if note_category_counts.get(category, 0)
        ],
        "scoring": {
            "place": "(user_score - 5) * 4",
            "type": "mean(user_scores_for_type - 5) * 6",
            "category": "mean(user_scores_for_category - 5) * 3",
            "presentation_notes": list(PRESENTATION_NOTE_TOKENS),
            "note_categories": [
                {"category": category, "tokens": list(tokens), "guidance": guidance}
                for category, tokens, guidance in NOTE_CATEGORY_RULES
            ],
            "clue_level_guidance": CLUE_LEVEL_GUIDANCE,
            "hard_clue_review": {
                "pass_fail": "pass only if the hard clue is a unique, specific event or incident that would identify this place to a player who knows it; fail architects, construction, appearance, broad history, generic associations, and reusable events",
                "reason": "why the hard clue passed or failed",
                "better_direction": "which particular event or incident should have been selected before choosing the place",
                "qualified_pass_tokens": list(QUALIFIED_HARD_PASS_TOKENS),
            },
        },
    }


def write_profile(profile: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"map_selector_profile_{timestamp()}.json"
    output_path.write_text(json.dumps(profile, indent=2, ensure_ascii=True), encoding="utf-8")
    latest_path = output_dir / "map_selector_profile_latest.json"
    latest_path.write_text(json.dumps(profile, indent=2, ensure_ascii=True), encoding="utf-8")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build map place selector preference profile from review feedback.")
    parser.add_argument("--training-dir", type=Path, default=DEFAULT_TRAINING_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_TRAINING_DIR)
    parser.add_argument("--feedback-file", type=Path, action="append", default=[])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    feedback_files = args.feedback_file or training_data_store.default_map_place_review_feedback_files(args.training_dir)
    if not feedback_files:
        raise ValueError(
            f"No map review feedback found in {args.training_dir}. "
            "Expected map_place_review_feedback_all.jsonl or map_place_review_feedback_*.json."
        )
    rows = read_feedback_rows(feedback_files)
    profile = build_profile(rows, source_files=feedback_files)
    output_path = write_profile(profile, args.out_dir)
    print(
        json.dumps(
            {
                "profile_path": str(output_path),
                "latest_profile_path": str(args.out_dir / "map_selector_profile_latest.json"),
                "row_count": profile["row_count"],
                "accepted_row_count": profile["accepted_row_count"],
                "ignored_count": len(profile["ignored_rows"]),
                "type_adjustments": profile["type_adjustments"],
                "category_adjustments": profile["category_adjustments"],
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
