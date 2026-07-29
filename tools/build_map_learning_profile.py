from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TRAINING_DIR = PROJECT_DIR / "data" / "training"

PATTERNS = (
    (
        "broad_multi_site_target",
        re.compile(
            r"\b(?:broad (?:multi-site|multi site|serial|heritage|target|property)|serial|multi-site|multi site|multi-village|poor pin target|split into)\b",
            re.IGNORECASE,
        ),
        "Avoid broad serial or multi-site heritage properties; choose one clickable landmark, ruin, bridge, temple, fort, monastery, or mound.",
    ),
    (
        "repetitive_ladder",
        re.compile(r"repeat|same information|same fact|repetitive", re.IGNORECASE),
        "Make hard, medium, and easy clues introduce different facts rather than restating the same hook.",
    ),
    (
        "answer_leak",
        re.compile(r"answer name|alias|spoiler|reveals? the answer", re.IGNORECASE),
        "Do not include the answer name, aliases, or obvious name fragments before the final name reveal.",
    ),
    (
        "generic_clue",
        re.compile(r"generic|bland|could fit many|not distinctive|specific source-backed|known-for hook|weak fields", re.IGNORECASE),
        "Make the assigned role concrete: hard needs a recognition hook, medium needs geographic progress, and easy needs a local map route.",
    ),
    (
        "location_based",
        re.compile(r"location|proximity|broad geography|where the place is|what it is near|nearby|located", re.IGNORECASE),
        "Keep geography out of hard; medium must reduce the broad search area and easy must then provide a useful local-area route.",
    ),
    (
        "coordinate_or_code_targeting",
        re.compile(r"coordinate|latitude|longitude|degrees|iso code|database-like identifier", re.IGNORECASE),
        "Do not use coordinates, compass degrees, ISO codes, or database-like identifiers as clues.",
    ),
    (
        "template_phrasing",
        re.compile(r"formulaic|template|dataset wording|mapped urban|national-map|urban settlement", re.IGNORECASE),
        "Avoid formulaic dataset wording; write natural clues around specific visible or historic hooks.",
    ),
    (
        "too_long",
        re.compile(r"too long|mobile|concise", re.IGNORECASE),
        "Keep every clue short enough to read comfortably on a phone.",
    ),
    (
        "metadata_reveal",
        re.compile(r"time zone|database metadata|located at|coordinate metadata", re.IGNORECASE),
        "Make the reveal a natural explanation, not a coordinate or database summary.",
    ),
    (
        "weak_progression",
        re.compile(r"difficulty progression|too easy|too hard|ladder", re.IGNORECASE),
        "Keep hard subtle, medium regionally helpful, and easy highly suggestive without naming the answer.",
    ),
    (
        "unverified_claim",
        re.compile(r"unverified|source|incorrect|appears wrong|unsupported|verified facts/context", re.IGNORECASE),
        "Use only details supported by verified_facts, nearby_context, or validation_reasoning; do not invent landmarks, industries, products, events, or institutions.",
    ),
)

CATEGORY_GUIDANCE = {
    "answer_leak": "Do not include the answer name, aliases, or obvious name fragments before the final name reveal.",
    "broad_multi_site_target": "Avoid broad serial or multi-site heritage properties; choose one clickable landmark, ruin, bridge, temple, fort, monastery, or mound.",
    "coordinate_or_metadata": "Do not use coordinates, compass degrees, ISO codes, time zones, or database-like identifiers as clues.",
    "engineered_hard_hook": "Do not choose a place and manufacture a hook from its architect, construction, appearance, or static attributes. Select a verified recognition hook first; its location becomes the target.",
    "fact_unclear": "Use clear, concrete clue wording; avoid facts that are hard to understand or do not clearly attach to the target place.",
    "factual_risk": "Avoid clues with uncertain or risky factual claims; prefer stable, verifiable facts from the curated place data.",
    "repetitive": "Make hard, medium, and easy clues introduce different facts rather than restating the same hook.",
    "location_based": "Keep geography out of hard; medium must reduce the broad search area and easy must then provide a useful local-area route.",
    "map_invisible_detail": "Easy clues must use features visible on the quiz street map; do not rely on colours, interiors, roof details, or aerial imagery.",
    "deep_zoom_anchor": "Easy's essential route must use an anchor labelled by zoom 11 or earlier on the quiz's Esri World Street Map. A later neighbourhood or district label may only supplement a usable lower-zoom route.",
    "incorrect_local_area": "Verify the target's technical borough, district, quarter, or neighbourhood. Do not present a popular association with a nearby area as the target's actual location.",
    "non_specific_incident": "A hard clue must name or clearly describe one particular incident, with defining participants, outcome, event, or date context. Broad conflict or generic event wording fails.",
    "insufficient_event_detail": "Do not reduce a good hook to a headline. Retain the useful people, action, outcome, consequence, record, or significance that makes it recognisable.",
    "missing_place_link": "Tie hard's recognition hook to the target with an answer-safe phrase such as 'here', 'on this pitch', 'inside this building', or 'at this site'. Do not replace this link with geographic hints.",
    "medium_filler": "State medium's useful place-owned relationship directly. Remove generic padding about crowds, popularity, prestige, fame, or being a historic venue.",
    "unnamed_cultural_reference": "Do not say only 'a famous collection', 'a well-known writer', or similar. Name an answer-safe creator, person, group, or work; when a title leaks the target, name its creator and explain the connection.",
    "fictional_context_ambiguity": "Clearly label fictional or imaginary people and events as fiction. Do not present an author's characters as though they were historical people.",
    "place_selected_before_hook": "Select the verified recognition hook first. Its location becomes the target; prefer a specific incident or story, while allowing a genuinely distinctive record, achievement, discovery, association, tradition, or phenomenon.",
    "placeholder_wording": "Do not use placeholders such as 'the place', 'the target place', or 'the answer' inside clues.",
    "repetitive_ladder": "Make hard, medium, and easy clues introduce different facts rather than restating the same hook.",
    "static_description": "Avoid static filler: hard needs a recognition hook, medium needs geographic progress, and easy needs a visible local route.",
    "template_phrasing": "Avoid formulaic dataset wording; write natural clues around specific visible or historic hooks.",
    "too_broad": "Avoid clues that could fit many places; narrow toward one identifiable map target.",
    "too_generic": "Avoid generic claims and fulfil the assigned role: recognition for hard, geographic narrowing for medium, and a local route for easy.",
    "too_long_for_mobile": "Keep every clue short enough to read comfortably on a phone.",
    "unsupported_fact": "Use only details supported by verified_facts, nearby_context, or validation_reasoning; do not invent landmarks, industries, products, events, or institutions.",
    "useful_but_wrong_level": "Move useful clues to the correct difficulty level instead of using them where they make the ladder too easy or too vague.",
    "weak_known_for_hook": "Hard needs one concrete recognition hook. Medium and easy should instead concentrate on progressively reducing the map area.",
    "weak_easy_map_anchor": "Easy must narrow within medium's area using an anchor visible by zoom 11 or earlier on the quiz's Esri World Street Map.",
      "weak_hard_hook": "Hard must use a verified place-owned recognition hook. Prefer a unique incident or story; a distinctive record, achievement, discovery, association, tradition, natural occurrence, or cultural moment may also qualify.",
      "generic_origin_fact": "A construction date, founder, commissioner, ruler, architect, or opening date is not a hard clue by itself. Add an unusual event, consequence, record, ritual, story, or oddity tied to one place.",
      "generic_unnamed_identity": "Do not replace a distinctive person or story with an unnamed role such as 'a famous journalist' or 'a prominent architect'. Name the answer-safe person or use another precise place-owned fact.",
      "weak_medium_narrowing": "Medium must materially reduce the geographic search area to a useful country, region, culture, language, city, or equivalent scope. An extra place-owned fact can add character but is not mandatory.",
    "wrong_difficulty": "Order clues by solving value: hard is a hook, medium narrows the context, and easy gives the strongest practical map anchor.",
}

POSITIVE_GUIDANCE = (
    "Write clear, natural clues for an adult player; keep them comfortable to read on a phone without imposing a word count.",
    "Build a solvable ladder: hard is a memorable recognition hook, medium reduces the broad geography, and easy gives a local map route inside that area.",
    "Treat approved examples as demonstrations of successful outcomes, not mandatory wording or fact templates.",
)
CLUE_LEVELS = ("hard", "medium", "easy")


def latest_negative_file(training_dir: Path) -> Path:
    matches = sorted(
        training_dir.glob("map_clue_negative_*.jsonl"),
        key=lambda path: (path.stat().st_mtime, path.name),
    )
    if not matches:
        raise ValueError(f"No map_clue_negative_*.jsonl files found in {training_dir}.")
    return matches[-1]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
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


def approved_examples_by_level(
    records: list[dict[str, Any]],
    *,
    per_level: int = 8,
) -> dict[str, list[dict[str, Any]]]:
    candidates: dict[str, list[dict[str, Any]]] = {level: [] for level in CLUE_LEVELS}
    for record in records:
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        level = str(metadata.get("clue_level") or metadata.get("difficulty") or "").strip().lower()
        if level not in candidates or str(metadata.get("label") or "").strip().lower() != "pass":
            continue
        if bool(metadata.get("exclude_from_training")):
            continue
        try:
            weight = float(metadata.get("training_weight") or 0)
        except (TypeError, ValueError):
            continue
        review_categories = metadata.get("review_categories")
        detected_leaks = metadata.get("detected_answer_leak_original")
        if weight < 1 or (isinstance(review_categories, list) and review_categories):
            continue
        if isinstance(detected_leaks, list) and detected_leaks:
            continue
        clue = str(record.get("original_clue") or "").strip()
        if not clue:
            continue
        candidates[level].append(
            {
                "example_id": str(metadata.get("example_id") or "").strip(),
                "place": str(metadata.get("place") or "").strip(),
                "place_type": str(metadata.get("place_type") or "place").strip() or "place",
                "clue": clue,
                "why_it_passed": str(record.get("pass_reason") or "").strip(),
                "training_weight": weight,
            }
        )

    selected: dict[str, list[dict[str, Any]]] = {}
    for level, level_candidates in candidates.items():
        ordered = sorted(
            level_candidates,
            key=lambda item: (
                -float(item["training_weight"]),
                str(item["place_type"]).casefold(),
                str(item["place"]).casefold(),
                str(item["example_id"]),
            ),
        )
        diverse: list[dict[str, Any]] = []
        seen_types: set[str] = set()
        seen_clues: set[str] = set()
        for item in ordered:
            place_type = str(item["place_type"]).casefold()
            clue_key = re.sub(r"\s+", " ", str(item["clue"])).casefold()
            if place_type in seen_types or clue_key in seen_clues:
                continue
            seen_types.add(place_type)
            seen_clues.add(clue_key)
            diverse.append(item)
            if len(diverse) >= per_level:
                break
        if len(diverse) < per_level:
            for item in ordered:
                clue_key = re.sub(r"\s+", " ", str(item["clue"])).casefold()
                if clue_key in seen_clues:
                    continue
                seen_clues.add(clue_key)
                diverse.append(item)
                if len(diverse) >= per_level:
                    break
        selected[level] = diverse
    return selected


def record_slot(record: dict[str, Any]) -> str:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    place_type = str(metadata.get("place_type") or "*").strip() or "*"
    difficulty = str(metadata.get("difficulty") or "*").strip() or "*"
    return f"{place_type}/{difficulty}"


def record_difficulty(record: dict[str, Any]) -> str:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    return str(metadata.get("difficulty") or "*").strip() or "*"


def record_categories(record: dict[str, Any]) -> list[str]:
    categories = record.get("failure_categories")
    if not isinstance(categories, list):
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        categories = metadata.get("failure_categories") if isinstance(metadata.get("failure_categories"), list) else []
    return [
        str(category).strip()
        for category in categories
        if str(category).strip() and str(category).strip() != "provider_deferred"
    ]


def build_profile(records: list[dict[str, Any]], *, source: Path) -> dict[str, Any]:
    pattern_counts: Counter[str] = Counter()
    feedback_counts: Counter[str] = Counter()
    slot_feedback: dict[str, list[str]] = {"global": list(POSITIVE_GUIDANCE)}

    for record in records:
        feedback = str(record.get("feedback_to_generator") or record.get("failure_reason") or "")
        if isinstance(record.get("feedback_to_generator"), list):
            feedback = " ".join(str(item) for item in record["feedback_to_generator"])
        if feedback:
            feedback_counts[feedback] += 1
        slot = record_slot(record)
        difficulty_slot = f"*/{record_difficulty(record)}"
        slot_feedback.setdefault(slot, [])
        slot_feedback.setdefault(difficulty_slot, [])
        for category in record_categories(record):
            guidance = CATEGORY_GUIDANCE.get(category)
            if not guidance:
                continue
            pattern_counts[category] += 1
            slot_feedback["global"].append(guidance)
            slot_feedback[slot].append(guidance)
            slot_feedback[difficulty_slot].append(guidance)
        for key, pattern, guidance in PATTERNS:
            if pattern.search(feedback):
                pattern_counts[key] += 1
                slot_feedback["global"].append(guidance)
                slot_feedback[slot].append(guidance)
                slot_feedback[difficulty_slot].append(guidance)

    feedback_by_slot = {
        slot: dedupe(values)[:8]
        for slot, values in slot_feedback.items()
        if values
    }
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_negative_file": str(source),
        "negative_count": len(records),
        "feedback_by_slot": feedback_by_slot,
        "pattern_counts": dict(pattern_counts),
        "top_feedback": [
            {"feedback": text, "count": count}
            for text, count in feedback_counts.most_common(10)
        ],
    }


def dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        normalized = re.sub(r"\s+", " ", text).casefold()
        if not text or normalized in seen:
            continue
        seen.add(normalized)
        result.append(text)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a compact map clue learning profile from reviewed negative examples.",
    )
    parser.add_argument("--negative-file", type=Path)
    parser.add_argument("--training-dir", type=Path, default=DEFAULT_TRAINING_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_TRAINING_DIR)
    parser.add_argument("--prefix", default="map_learning_profile")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    negative_file = args.negative_file or latest_negative_file(args.training_dir)
    profile = build_profile(read_jsonl(negative_file), source=negative_file)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = args.out_dir / f"{args.prefix}_{stamp}.json"
    output_path.write_text(json.dumps(profile, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"profile_path": str(output_path), **profile}, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
