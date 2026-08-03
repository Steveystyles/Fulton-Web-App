from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import re
import sqlite3
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import daily_map_game
from tools import export_map_place_review_batch as review_export
from tools import map_clue_quality_model
from tools import map_selector_model
from tools import rewrite_map_clues_with_ai as rewriter
from tools import training_data_store

DEFAULT_DB_PATH = PROJECT_DIR / "data" / "fultons.db"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "data" / "training"
DEFAULT_ENV_FILE = PROJECT_DIR / ".env.local"
DEFAULT_PUBLIC_PATH = PROJECT_DIR / "public" / "map-place-review.html"
DEFAULT_GENERATOR_MODEL = rewriter.DEFAULT_MAP_GEMINI_GENERATOR_MODEL
REJECTED_PLACE_TYPES = {
    "continent",
    "country",
    "county",
    "province",
    "region",
    "state",
}
UNSTABLE_VENUE_NAME_RE = re.compile(
    r"\b(?:wanda metropolitano)\b",
    re.IGNORECASE,
)
AWKWARD_MASKED_FACT_RE = re.compile(
    r"\b(?:the\s+this place|this is this place|known as (?:the\s+)?['\"]?this place|"
    r"nicknamed (?:the\s+)?['\"]?this place|call(?:ed|s)? .{0,80}?['\"]?this place|"
    r"translates? to (?:the\s+)?['\"]?this place|this place[-/]|this place (?:of|for|in|at|on))\b",
    re.IGNORECASE,
)
NON_CURRENT_MAP_TARGET_RE = re.compile(
    r"\b(?:demolished|dismantled|no longer exists|no longer standing|"
    r"was temporary|temporary structure|closed permanently|destroyed in)\b",
    re.IGNORECASE,
)
BAD_TEXT_ARTIFACT_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ufffd]")
EASY_CLUE_REQUIRED_WORKOUTABILITY_SCORE = 5
HARD_CLUE_REQUIRED_HOOK_SCORE = 6
MEDIUM_CLUE_REQUIRED_SCOPE_SCORE = 4
MEDIUM_CLUE_SCOPE_ANCHOR_RE = re.compile(
    r"\b(?:city|town|district|neighbou?rhood|borough|country|region|state|province|"
    r"national|local|community|coast|coastal|river|bay|harbou?r|waterfront|island|"
    r"peninsula|strait|valley|canal|park|road|route|university|campus|centre|center|"
    r"northern|southern|eastern|western|central|european|british|english|scottish|"
    r"welsh|irish|french|spanish|italian|german|japanese|american|australian)\b",
    re.IGNORECASE,
)
MEDIUM_CLUE_NAME_INFERENCE_RE = re.compile(
    r"\b(?:named (?:after|for)|name (?:comes|came|derives)|honou?rs?|called|"
    r"nickname|means|meaning|translates?|translation|word for|term for)\b",
    re.IGNORECASE,
)
MEDIUM_CLUE_MAP_INSTRUCTION_RE = re.compile(
    r"\b(?:look for|find|scan|zoom|pin|tap|map|locate|search)\b",
    re.IGNORECASE,
)
HARD_CLUE_DISTINCTIVE_HOOK_RE = re.compile(
    r"\b(?:first|only|last|largest|smallest|tallest|oldest|world(?:'s)?|record|"
    r"famous|famously|known|nicknamed|hosted|designed|built|invented|survived|"
    r"disaster|battle|final|film|song|novel|artist|architect|engineer|king|queen|"
    r"president|statue|tower|bridge|stadium|museum|castle|palace|cathedral|"
    r"monument|festival|waterfall|volcanic|island|prison|war|olympic|cup)\b",
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
GENERIC_RECOGNISABILITY_HOOK_RE = re.compile(
    r"\b(?:one of (?:the )?)?(?:most|best)[-\s]+recogni[sz](?:able|ed)\b",
    re.IGNORECASE,
)
COLOUR_ONLY_HOOK_RE = re.compile(
    r"\b(?:signature\s+)?(?:colou?r|paint|painted|orange|red|blue|green|white)\b",
    re.IGNORECASE,
)
GENERIC_PRISON_ISLAND_HOOK_RE = re.compile(
    r"\b(?:island\b.{0,80}?\b(?:prison|penitentiary|criminals)|"
    r"(?:prison|penitentiary)\b.{0,80}?\b(?:island|notorious criminals))\b",
    re.IGNORECASE,
)
PRISON_SPECIFIC_HOOK_RE = re.compile(
    r"\b(?:escape|riot|siege|occupation|al capone|birdman|morris|anglin|mandela|robben)\b",
    re.IGNORECASE,
)
BRIDGE_SPAN_FACT_RE = re.compile(
    r"\b(?:spans?|cross(?:es|ing)?|connects?|links?)\b",
    re.IGNORECASE,
)
KNOWN_CANONICAL_NAME_CORRECTIONS = {
    "maracanastadium": "Maracanã Stadium",
}


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean_text(value: object, *, limit: int = 400) -> str:
    text = html.unescape(str(value or "").strip())
    text = re.sub(r"\s+", " ", text)
    return text[:limit].strip()


def slugify(value: object) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").casefold()).strip("-")
    return slug or "place"


def normalized_name(value: object) -> str:
    folded = unicodedata.normalize("NFKD", str(value or "").casefold())
    without_marks = "".join(character for character in folded if not unicodedata.combining(character))
    return "".join(character for character in without_marks if character.isalnum())


def normalized_name_variants(value: object) -> set[str]:
    text = re.sub(r"\s+", " ", str(value or "").casefold()).strip()
    variants = {normalized_name(text)}
    stripped = re.sub(r"^(?:the|a|an|la|le|les|el|los|las)\s+", "", text)
    variants.add(normalized_name(stripped))
    return {variant for variant in variants if len(variant) >= 4}


def name_variants_overlap(left: set[str], right: set[str]) -> bool:
    if left & right:
        return True
    for left_value in left:
        for right_value in right:
            if len(left_value) >= 5 and len(right_value) >= 5:
                if left_value in right_value or right_value in left_value:
                    return True
    return False


def string_list(value: object, *, limit: int = 8) -> list[str]:
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = str(value or "").split(";")
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_values:
        text = clean_text(item, limit=240)
        key = normalized_name(text)
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


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


def medium_clue_scope_score(text: object, row: dict[str, Any]) -> int:
    context = clean_text(text, limit=320)
    if not context or daily_map_game.MAP_WORKOUTABILITY_VAGUE_RE.fullmatch(context):
        return 0
    anchors = {
        match.group(0).casefold()
        for match in MEDIUM_CLUE_SCOPE_ANCHOR_RE.finditer(context)
    }
    score = min(6, len(anchors) * 2)
    named_context = [
        row.get("country_name"),
        daily_map_game.country_name(str(row.get("country_code") or "")),
        row.get("continent"),
        row.get("admin1"),
    ]
    if any(str(value or "").strip() and str(value).casefold() in context.casefold() for value in named_context):
        score += 2
    if MEDIUM_CLUE_NAME_INFERENCE_RE.search(context):
        score += 4
    if re.search(r"\b(?:in|from|of|across|through|spans|connects|located|based|serves|used by|home of|home to)\b", context, re.IGNORECASE):
        score += 1
    if len(context.split()) >= 10:
        score += 1
    if any(character.isupper() for character in context[1:]):
        score += 1
    return min(12, score)


def hard_clue_hook_score(text: object) -> int:
    context = clean_text(text, limit=320)
    if not context or daily_map_game.MAP_WORKOUTABILITY_VAGUE_RE.fullmatch(context):
        return 0
    score = daily_map_game.fact_interest_score(context)
    if HARD_CLUE_DISTINCTIVE_HOOK_RE.search(context):
        score += 3
    if daily_map_game.clue_is_location_framed_without_hook(context):
        score -= 3
    return max(0, min(12, score))


def clue_ladder_ordering_reasons(row: dict[str, Any], facts: list[str]) -> list[str]:
    hard_clue = str(row.get("clue_text") or (facts[0] if len(facts) > 0 else "")).strip()
    easy_clue = str(row.get("easy_clue_text") or (facts[2] if len(facts) > 2 else "")).strip()
    reasons: list[str] = []
    if not hard_clue:
        reasons.append("hard clue is missing")
    elif MEDIUM_CLUE_MAP_INSTRUCTION_RE.search(hard_clue):
        reasons.append("hard clue should be a distinctive hook, not a map instruction")
    elif FORMER_HEIGHT_RECORD_RE.search(hard_clue):
        reasons.append("hard clue should not rely on a former height record")
    elif FORMER_RECORD_HOOK_RE.search(hard_clue):
        reasons.append("hard clue should not rely on a former or stale record")
    elif WEAK_ANALOGY_HOOK_RE.search(hard_clue):
        reasons.append("hard clue should not rely on comparison to another landmark")
    elif GENERIC_SKYLINE_HOOK_RE.search(hard_clue):
        reasons.append("hard clue needs a less generic hook than skyline prominence")
    elif GENERIC_RECOGNISABILITY_HOOK_RE.search(hard_clue):
        reasons.append("hard clue should use a concrete specific fact, not generic recognisability")
    elif COLOUR_ONLY_HOOK_RE.search(hard_clue) and hard_clue_hook_score(hard_clue) < HARD_CLUE_REQUIRED_HOOK_SCORE + 3:
        reasons.append("hard clue should not rely mainly on colour or paint")
    elif GENERIC_PRISON_ISLAND_HOOK_RE.search(hard_clue) and not PRISON_SPECIFIC_HOOK_RE.search(hard_clue):
        reasons.append("hard clue needs a specific prison story, person, escape, or incident")
    elif hard_clue_hook_score(hard_clue) < HARD_CLUE_REQUIRED_HOOK_SCORE:
        reasons.append("hard clue needs a distinctive fact, story, record, person, or visual hook")

    hard_map_score = clue_map_workoutability_score(hard_clue)
    easy_map_score = clue_map_workoutability_score(easy_clue)
    if easy_clue and hard_map_score >= EASY_CLUE_REQUIRED_WORKOUTABILITY_SCORE and easy_map_score <= hard_map_score:
        reasons.append("easy clue should be more map-useful than the hard clue")
    return reasons


def clue_distinctness_reasons(row: dict[str, Any], facts: list[str]) -> list[str]:
    medium_clue = str(row.get("medium_clue_text") or (facts[1] if len(facts) > 1 else "")).strip()
    easy_clue = str(row.get("easy_clue_text") or (facts[2] if len(facts) > 2 else "")).strip()
    if (
        row.get("place_type") == "bridge"
        and BRIDGE_SPAN_FACT_RE.search(medium_clue)
        and BRIDGE_SPAN_FACT_RE.search(easy_clue)
    ):
        return ["medium and easy bridge clues should not both describe the span or connection"]
    return []


def candidate_json_schema(max_items: int) -> dict[str, Any]:
    place_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "canonical_name": {"type": "string"},
            "place_type": {"type": "string"},
            "difficulty": {"type": "string"},
            "country_code": {"type": "string"},
            "country_name": {"type": "string"},
            "continent": {"type": "string"},
            "admin1": {"type": "string"},
            "lat": {"type": "number"},
            "lng": {"type": "number"},
            "coordinate_precision": {"type": "string"},
            "suggested_map_zoom": {"type": "integer"},
            "acceptable_aliases": {"type": "array", "items": {"type": "string"}},
            "fun_facts": {
                "type": "array",
                "items": {"type": "string"},
            },
            "why_fun": {"type": "string"},
            "map_guessability": {"type": "string"},
            "avoid_in_clues": {"type": "array", "items": {"type": "string"}},
            "source_search_queries": {"type": "array", "items": {"type": "string"}},
            "source_urls": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "canonical_name",
            "place_type",
            "difficulty",
            "country_code",
            "country_name",
            "continent",
            "admin1",
            "lat",
            "lng",
            "coordinate_precision",
            "suggested_map_zoom",
            "acceptable_aliases",
            "fun_facts",
            "why_fun",
            "map_guessability",
            "avoid_in_clues",
            "source_search_queries",
            "source_urls",
        ],
    }
    return {
        "type": "object",
        "properties": {
            "places": {
                "type": "array",
                "items": place_schema,
            }
        },
        "required": ["places"],
    }


def existing_place_names(conn: sqlite3.Connection) -> set[str]:
    names: set[str] = set()
    for row in conn.execute(
        """
        SELECT canonical_name, acceptable_aliases
        FROM map_place_pool
        """
    ).fetchall():
        names.update(normalized_name_variants(row["canonical_name"]))
        for alias in daily_map_game.split_list_text(row["acceptable_aliases"]):
            names.update(normalized_name_variants(alias))
    return {name for name in names if len(name) >= 4}


def existing_place_context(conn: sqlite3.Connection, *, limit: int = 220) -> list[dict[str, str]]:
    rows = conn.execute(
        """
        SELECT canonical_name, place_type, country_name, country_code, difficulty
        FROM map_place_pool
        WHERE active = 1
        ORDER BY validation_grade DESC NULLS LAST, canonical_name
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "name": row["canonical_name"],
            "type": row["place_type"],
            "country": row["country_name"] or daily_map_game.country_name(row["country_code"]),
            "difficulty": row["difficulty"],
        }
        for row in rows
    ]


def existing_place_name_examples(conn: sqlite3.Connection, *, limit: int = 2000) -> list[str]:
    rows = conn.execute(
        """
        SELECT canonical_name
        FROM map_place_pool
        WHERE active = 1
        ORDER BY validation_grade DESC NULLS LAST, canonical_name
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [str(row["canonical_name"]) for row in rows if str(row["canonical_name"]).strip()]


def reviewed_feedback_place_names(training_dir: Path = DEFAULT_OUTPUT_DIR) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    paths = training_data_store.default_map_place_review_feedback_files(training_dir)
    try:
        rows = training_data_store.read_map_place_review_feedback_rows(paths)
    except (OSError, json.JSONDecodeError):
        rows = []
    for row in rows:
        name = clean_text(row.get("place"), limit=160)
        key = normalized_name(name)
        if not name or key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def selector_profile_summary(profile: dict[str, Any]) -> dict[str, Any]:
    def sorted_adjustments(key: str, *, reverse: bool) -> list[dict[str, Any]]:
        values = profile.get(key)
        if not isinstance(values, dict):
            return []
        items = [
            {"name": str(name), "adjustment": int(round(float(value)))}
            for name, value in values.items()
            if str(name).strip()
        ]
        items.sort(key=lambda item: item["adjustment"], reverse=reverse)
        return items[:8]

    return {
        "positive_place_types": sorted_adjustments("type_adjustments", reverse=True),
        "negative_place_types": sorted_adjustments("type_adjustments", reverse=False),
        "positive_hook_categories": sorted_adjustments("category_adjustments", reverse=True),
        "negative_hook_categories": sorted_adjustments("category_adjustments", reverse=False),
        "note_guidance": profile.get("note_guidance", [])[:8] if isinstance(profile.get("note_guidance"), list) else [],
        "clue_level_guidance": profile.get("clue_level_guidance", [])[:6] if isinstance(profile.get("clue_level_guidance"), list) else [],
        "hard_clue_review": profile.get("hard_clue_review", {}) if isinstance(profile.get("hard_clue_review"), dict) else {},
        "feedback_rows": profile.get("accepted_row_count", 0),
    }


def candidate_generation_prompt(
    *,
    limit: int,
    existing_places: list[dict[str, str]],
    existing_name_examples: list[str],
    blocked_name_examples: list[str],
    selector_profile: dict[str, Any],
    feedback: list[str],
    focus: str = "",
    allow_known_retries: bool = False,
) -> str:
    profile = selector_profile_summary(selector_profile)
    retry_mode_text = (
        "Beta retry mode is ON. Existing or previously reviewed names may be proposed again when they are familiar, "
        "map-workoutable, and useful for learning what a good place feels like."
        if allow_known_retries
        else "Beta retry mode is OFF. Existing and previously reviewed names should be avoided."
    )
    existing_sample_heading = (
        "Existing/reviewed place sample that may be retried in beta"
        if allow_known_retries
        else "Existing place bank sample to avoid duplicating"
    )
    existing_name_heading = (
        "Exact existing/reviewed names that may be retried if they are high-quality beta examples"
        if allow_known_retries
        else "Exact existing names to avoid duplicating"
    )
    obvious_place_rule = (
        "Do not avoid obvious famous places just because they may already exist; in beta, familiar retry examples are valuable when they are map-workoutable."
        if allow_known_retries
        else "Avoid very obvious global defaults that are likely already in the bank unless you are certain they are absent."
    )
    candidate_goal = (
        "Suggest exactly {limit} beta review candidates that are likely to be enjoyable to guess. They may be fresh places or retries of known/reviewed places."
        if allow_known_retries
        else "Suggest exactly {limit} new map-game places that are likely to be enjoyable to guess."
    ).format(limit=limit)
    candidate_type_rule = (
        "These are beta review candidates, not final inserts. Their three fun_facts will be reviewed as a draft hard/medium/easy clue ladder."
        if allow_known_retries
        else "These must be new candidate choices. Their three fun_facts will be reviewed as a draft hard/medium/easy clue ladder."
    )
    return f"""You are proposing new candidate places for Fulton's Quiz daily map game.

Audience:
- The main tester is an adult football fan. Do not write for children.
- The choices should feel fun, memorable, and worth chatting about.

Goal:
- {candidate_goal}
- {candidate_type_rule}
- Discover candidates from grounded web information. The existing place bank is only for duplicate detection, never an eligibility or recommendation list.
- Use the learned preference profile and trained clue judgements to choose candidates, but keep the set varied.
- {retry_mode_text}

Learned preference profile:
{json.dumps(profile, indent=2)}

User note guidance:
- Treat note_guidance as direct human feedback from scored batches.
- Follow these guidance items even when the numeric score was still acceptable.
- If a note says a fact was subjective, vague, repeated, leaked the answer, or not map-guessable, avoid that pattern in all new candidates.
- Treat clue_level_guidance as targeted feedback on the hard, medium, and easy clue roles.
- Treat hard_clue_review as the strongest signal for hard clue writing. Pass examples are acceptable hard hooks; fail examples and better_direction fields show what must be rewritten.
- If hard_clue_review contains qualified_pass_examples, do not copy their style. They are near misses: technically defensible, but too boring, padded, unclear, or not interesting enough for the game.
- Aim for hard clues that would become strong pass examples, not merely qualified passes.
- Treat a specific incident or story as the preferred hard hook. A current record, achievement, discovery, person-linked episode, tradition, natural occurrence, or cultural moment may also qualify when it is genuinely famous and strongly identifying.
- If a pass note says wording could be dropped, expanded, or focused, keep the famous incident and remove the filler around it. One strong incident beats a bundled list of lesser facts.
- Keep clue wording plain and grammatical. If a hard clue starts with a pronoun that hides the target type, use "this bridge", "this stadium", "this island", or similar instead.
- Overall score affects whether a place is liked; clue-level scores affect how the ladder should be written.

{existing_sample_heading}:
{json.dumps(existing_places[:220], indent=2)}

{existing_name_heading}:
{json.dumps(existing_name_examples[:2000], indent=2)}

Blocked names for this run. Never return these, even when beta retry mode is ON:
{json.dumps(blocked_name_examples[:500], indent=2)}

Additional feedback from previous failed/rejected generation:
{json.dumps(feedback[-12:], indent=2)}

This run's focus:
{focus or "Varied, map-friendly places with strong fun hooks."}

Selection rules:
- Never return a blocked name from the run-specific blocked list.
- Search for the recognition hook first; the place attached to the strongest hook becomes the candidate.
- Prefer places known for something specific: sport, dramatic visual form, a good story, famous culture, industry, invention, oddity, event, or iconic design.
- Do not pick a place just because it is near a castle, near a city, a capital, or a UNESCO listing.
- Do not overfit to stadiums. They are currently liked, but the batch must include other fun types too.
- {obvious_place_rule}
- Avoid broad countries, regions, mountain ranges, vague cultural landscapes, ancient areas with unclear pin targets, and ambiguous ruins.
- A user should be able to work out where to look on the map from the clues, not merely know the answer name.
- Prefer places with a map-solving route: a recognisable city/region plus a visible shape, waterfront, river, bridge, route, park, skyline object, stadium area, or labelled landmark.
- Avoid answers that are famous but only findable if the player already knows the exact district or city.
- Avoid sponsor-name venues unless the map target has a stable official/common name.
- A user should be able to tap the map target confidently after clues reveal the name.
- The coordinates must identify the actual guessable object or city centre, not a whole region.
- Use stable, source-checkable facts only. Avoid current events. Verify whether every claimed record is current or former.
- For every event hook, verify that the event occurred at the exact target place. Do not transfer a match or incident from another venue in the same city, tournament, group, or institution.
- Supply direct source_urls actually used for the hook, map identity, and coordinates. Do not invent URLs.

Clue ladder intention:
- The aim is a fun but beatable map puzzle for the tester, not a trivia trap.
- The three fun_facts are draft clue text. They should narrow the answer step by step: recognition hook -> broad area -> local map route.
- Hard clue style: prefer a unique incident or story. A distinctive current record, achievement, discovery, person-linked episode, tradition, natural occurrence, or cultural moment may also qualify.
- Hard must use one coherent recognition hook. Never bundle separate matches or incidents, and never imply that an event occurred during a different match.
- Verify the exact competition stage, date, participants, result, and relationship between claims. If a record needs multiple events to establish it, state only that record and those events; omit unrelated anecdotes.
- Select the hook first; its place becomes the answer. Static facts like capacity, age, gift origin, height, plant count, or "built for an expo" are usually weak.
- Keep hard clear, but do not delete defining people, action, outcome, consequence, record, or significance to meet a word count.
- Medium clue style: materially reduce the geographic search area to a useful country, region, culture, language, city, or equivalent scope.
- Medium may add a place-owned fact, naming story, institution, or cultural connection for character, but that extra fact is optional and geographic progress is mandatory.
- Easy clue style: narrow within medium's area to a borough, district, quarter, neighbourhood, city sector, river crossing, park, station, or named nearby landmark visible at city zoom.
- map_guessability must explicitly name the city, town, or municipality that a player can see at zoom 10 or 11. Never use "the city" or "the area" as a substitute for that name.
- The easy route may add a district, road, or smaller feature, but it must first establish a named low-zoom locality; do not make an unlabelled neighbourhood the essential anchor.
- Give a broad route within that locality, such as northern, southern, eastern, western, central, or the city centre, before any smaller district, road, or station detail.
- Prefer persistent map geography such as a city centre, cardinal city sector, major river, coast, or large park over motorway and road numbers. Treat a road number as supplementary only when it is visibly labelled on the quiz map.
- Medium should not be a full map instruction. Avoid "look for", "find", "locate", "scan", "search", or pin/map language in the medium clue.
- Medium should not be merely another hard hook. If it uses a record, famous incident, survival story, or famous person, it must also narrow the search or help infer the name.
- Before returning, check the order. If the first clue tells the player where to look, move it later. If the strongest story or famous incident is in clue 2 or 3, move it to clue 1 and rewrite the later clues to narrow the area and then the map target.
- Do not use a former height record as the hard clue, such as "once the tallest" or "was the tallest from X to Y". Prefer a current distinctive feature, famous event, unusual design, or story that still feels specific.
- Do not use stale-record hooks such as "historically held the world record" as the hard clue. They are usually less interesting than a named event, person, design feature, or current identity.
- Do not use lazy analogy hooks such as "often compared to [another landmark]" as the hard clue. Say what is distinctive about this place itself.
- Do not rely on generic skyline wording as the hard clue. Many landmarks define a skyline; explain what makes this one specifically interesting.
- Do not use subjective claims like "one of the most recognisable" as the hard clue. Give the concrete story, event, design feature, record, or incident instead.
- Do not use a colour or paint choice as the hard clue unless it is tied to a genuinely memorable story or incident.
- For prison islands, avoid generic "held notorious criminals" wording; name a specific escape, incident, prisoner, or story.
- Do not make medium and easy repeat the same bridge-span or connection fact in different words.
- Treat those styles as guidance, not rigid templates. Do not force superlatives, famous people, or records where they are not natural.
- The player should feel they can succeed or beat the game after using more clues.

Fact rules:
- Provide exactly the three draft clues needed for each place, ordered as hard, medium, then easy.
- Do not include the canonical_name or aliases inside fun_facts.
- avoid_in_clues must contain only the canonical answer, accepted aliases, and distinctive answer-name fragments. Never add a country, region, city, district, road, river, station, or other map anchor unless it is itself the answer or an alias.
- Hard must contain the interesting recognition hook.
- Medium and Easy do not need separate spectacular stories: their primary job is to narrow the map search progressively.
- Write facts in natural adult wording. Avoid dry official phrasing.

Map guessability rule:
- map_guessability must be one or two plain sentences explaining how a player can narrow the map search.
- It must include concrete map anchors such as the city/region, visible land/water shape, route, river, district, skyline object, labelled public park, bridge, or stadium area.
- Do not return one-word ratings such as "easy", "medium", "hard", "high", or "low".
- Bad: "high".
- Good: "A player can work from Manhattan, then look for the long elevated park running through Chelsea on the west side."

Return JSON only. Do not include markdown. Use this schema:
{json.dumps(candidate_json_schema(limit), indent=2)}
"""


def parse_candidate_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_places = payload.get("places", payload.get("candidates", []))
    if not isinstance(raw_places, list):
        return []
    return [dict(item) for item in raw_places if isinstance(item, dict)]


def candidate_aliases(candidate: dict[str, Any]) -> list[str]:
    return [
        clean_text(candidate.get("canonical_name"), limit=120),
        *string_list(candidate.get("acceptable_aliases")),
        *string_list(candidate.get("avoid_in_clues")),
    ]


def fact_contains_candidate_name(fact: str, candidate: dict[str, Any]) -> bool:
    normalized_fact = normalized_name(fact)
    for name in candidate_aliases(candidate):
        normalized = normalized_name(name)
        if len(normalized) >= 5 and normalized in normalized_fact:
            return True
    return False


def candidate_facts(candidate: dict[str, Any]) -> list[str]:
    return string_list(candidate.get("fun_facts"), limit=5)


def candidate_row_id(candidate: dict[str, Any]) -> str:
    basis = json.dumps(
        {
            "name": candidate.get("canonical_name"),
            "lat": candidate.get("lat"),
            "lng": candidate.get("lng"),
            "facts": candidate_facts(candidate),
        },
        sort_keys=True,
        ensure_ascii=True,
    )
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def parse_coordinate(value: object, *, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be numeric.") from error
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite.")
    return number


def candidate_to_pool_row(candidate: dict[str, Any]) -> dict[str, Any]:
    name = clean_text(candidate.get("canonical_name"), limit=120)
    name = KNOWN_CANONICAL_NAME_CORRECTIONS.get(normalized_name(name), name)
    difficulty = clean_text(candidate.get("difficulty"), limit=20).casefold()
    lat = parse_coordinate(candidate.get("lat"), field="lat")
    lng = parse_coordinate(candidate.get("lng"), field="lng")
    daily_map_game.valid_coordinate(lat, lng)
    aliases = [
        alias
        for alias in string_list(candidate.get("acceptable_aliases"), limit=8)
        if normalized_name(alias) != normalized_name(name)
    ]
    avoid = string_list(candidate.get("avoid_in_clues"), limit=12)
    facts = candidate_facts(candidate)
    source_queries = string_list(candidate.get("source_search_queries"), limit=6)
    source_urls = [
        url
        for url in string_list(candidate.get("source_urls"), limit=8)
        if url.startswith(("https://", "http://"))
    ]
    candidate_id = candidate_row_id(candidate)
    return {
        "candidate_id": candidate_id,
        "slug": f"ai-{difficulty}-{slugify(name)}-{candidate_id[:6]}",
        "canonical_name": name,
        "country_code": clean_text(candidate.get("country_code"), limit=8).upper(),
        "country_name": clean_text(candidate.get("country_name"), limit=80),
        "continent": clean_text(candidate.get("continent"), limit=80),
        "admin1": clean_text(candidate.get("admin1"), limit=120),
        "place_type": slugify(candidate.get("place_type")).replace("-", "_"),
        "difficulty": difficulty,
        "lat": lat,
        "lng": lng,
        "coordinate_precision": clean_text(candidate.get("coordinate_precision"), limit=80) or "candidate",
        "suggested_map_zoom": int(float(candidate.get("suggested_map_zoom") or 5)),
        "clue_text": facts[0] if len(facts) > 0 else "",
        "medium_clue_text": facts[1] if len(facts) > 1 else "",
        "easy_clue_text": facts[2] if len(facts) > 2 else "",
        "reveal_text": clean_text(candidate.get("reveal_text"), limit=220)
        or f"{name} is a proposed map-game candidate with several distinct hooks.",
        "acceptable_aliases": "; ".join(aliases),
        "nearby_context": clean_text(candidate.get("map_guessability"), limit=320),
        "verified_facts_json": json.dumps(facts, ensure_ascii=True),
        "sources_json": json.dumps(
            [
                *[
                    {"name": "Grounded source", "url": url}
                    for url in source_urls
                ],
                *[
                    {"name": "Verification search query", "query": query}
                    for query in source_queries
                ],
            ],
            ensure_ascii=True,
        ),
        "coordinate_source_name": "Grounded AI candidate",
        "coordinate_source_url": source_urls[0] if source_urls else "",
        "avoid_in_clues": "; ".join([name, *aliases, *avoid]),
        "deconflict_group": normalized_name(name),
        "fact_stability": "grounded_candidate",
        "review_status": "machine_candidate",
        "review_notes": "Grounded AI candidate; automated validity, learned-quality, and critic gates still apply.",
        "reviewed_on": "",
        "validation_grade": 7.0,
        "validation_reasoning": clean_text(candidate.get("why_fun"), limit=500),
        "scoring_radius_m": daily_map_game.normalized_scoring_radius_m(difficulty),
        "why_fun": clean_text(candidate.get("why_fun"), limit=500),
        "map_guessability": clean_text(candidate.get("map_guessability"), limit=500),
        "source_search_queries": source_queries,
        "source_urls": source_urls,
    }


def validate_candidate_row(
    row: dict[str, Any],
    *,
    candidate: dict[str, Any],
    existing_names: set[str],
    seen_names: set[str],
    excluded_place_types: set[str] | None = None,
    allow_known_retries: bool = False,
    blocked_names: set[str] | None = None,
) -> list[str]:
    reasons: list[str] = []
    excluded_place_types = excluded_place_types or set()
    blocked_names = blocked_names or set()
    name = str(row["canonical_name"])
    normalized_variants = normalized_name_variants(name)
    normalized = next(iter(normalized_variants), "")
    if not name:
        reasons.append("missing canonical_name")
    if len(normalized) < 4:
        reasons.append("canonical_name is too short")
    if name_variants_overlap(normalized_variants, blocked_names):
        reasons.append("name is blocked for this review batch")
    if name_variants_overlap(normalized_variants, existing_names) and not allow_known_retries:
        reasons.append("already exists in the map place bank")
    if name_variants_overlap(normalized_variants, seen_names):
        reasons.append("duplicate within this generated batch")
    if UNSTABLE_VENUE_NAME_RE.search(name):
        reasons.append("uses an unstable sponsor-style venue name")
    if row["difficulty"] not in daily_map_game.DIFFICULTIES:
        reasons.append("difficulty must be easy, medium, or hard")
    if row["place_type"] in REJECTED_PLACE_TYPES:
        reasons.append("place_type is too broad for a tappable map quiz answer")
    if row["place_type"] in excluded_place_types:
        reasons.append(f"place_type {row['place_type']} is excluded for this focused run")
    if not row["country_code"]:
        reasons.append("missing country_code")
    if abs(float(row["lat"])) < 0.0001 and abs(float(row["lng"])) < 0.0001:
        reasons.append("coordinates look like a null island placeholder")
    if not row["why_fun"]:
        reasons.append("missing why_fun")
    if not row["map_guessability"]:
        reasons.append("missing map_guessability")
    workoutability_score = daily_map_game.map_workoutability_score(row)
    if workoutability_score < daily_map_game.MAP_PLACE_REQUIRED_WORKOUTABILITY_SCORE:
        reasons.append("map_guessability must explain how a player can work out where to look on the map")

    facts = json.loads(row["verified_facts_json"])
    masked_facts = [
        review_export.mask_names(
            str(fact),
            [row["canonical_name"], *daily_map_game.split_list_text(row["acceptable_aliases"])],
            replacement="this place",
        )
        for fact in facts
    ]
    if any(AWKWARD_MASKED_FACT_RE.search(fact) for fact in masked_facts):
        reasons.append("facts or aliases produce awkward masked review wording")
    current_target_text = " ".join(
        [
            row["canonical_name"],
            row["reveal_text"],
            row["nearby_context"],
            row["validation_reasoning"],
            *facts,
        ]
    )
    if BAD_TEXT_ARTIFACT_RE.search(current_target_text):
        reasons.append("candidate text contains encoding artifacts or control characters")
    if NON_CURRENT_MAP_TARGET_RE.search(current_target_text):
        reasons.append("candidate appears to be a non-current or demolished map target")
    if len(facts) < 3:
        reasons.append("needs a hard hook, medium geographic clue, and easy local map clue")
    reasons.extend(clue_ladder_ordering_reasons(row, facts))
    reasons.extend(clue_distinctness_reasons(row, facts))
    medium_clue = str(row["medium_clue_text"] or (facts[1] if len(facts) > 1 else "")).strip()
    if MEDIUM_CLUE_MAP_INSTRUCTION_RE.search(medium_clue):
        reasons.append("medium clue should narrow context, not give the map instruction")
    elif medium_clue_scope_score(medium_clue, row) < MEDIUM_CLUE_REQUIRED_SCOPE_SCORE:
        reasons.append("medium clue must narrow the search or help infer the place name")
    easy_clue = str(row["easy_clue_text"] or (facts[2] if len(facts) > 2 else "")).strip()
    if clue_map_workoutability_score(easy_clue) < EASY_CLUE_REQUIRED_WORKOUTABILITY_SCORE:
        reasons.append("easy clue must include a practical anchor visible from a reasonable starting zoom")
    hard_hooks = daily_map_game.qualifying_hard_hook_candidates(
        daily_map_game.public_place_payload(row)
    )
    if not hard_hooks:
        reasons.append("hard clue needs one qualifying recognition hook")
    if not row["source_urls"]:
        reasons.append("grounded candidate needs at least one supporting source URL")
    return reasons


def validated_review_rows(
    raw_candidates: list[dict[str, Any]],
    *,
    existing_names: set[str],
    selector_profile: dict[str, Any],
    excluded_place_types: set[str] | None = None,
    allow_known_retries: bool = False,
    blocked_names: set[str] | None = None,
    selector_model: dict[str, Any] | None = None,
    clue_quality_model: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for raw in raw_candidates:
        try:
            row = candidate_to_pool_row(raw)
            reasons = validate_candidate_row(
                row,
                candidate=raw,
                existing_names=existing_names,
                seen_names=seen_names,
                excluded_place_types=excluded_place_types,
                allow_known_retries=allow_known_retries,
                blocked_names=blocked_names,
            )
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
            rejected.append({"candidate": raw, "reasons": [str(error)]})
            continue
        normalized_variants = normalized_name_variants(row["canonical_name"])
        is_known_retry = name_variants_overlap(normalized_variants, existing_names)
        if reasons:
            rejected.append({"candidate": raw, "row": row, "reasons": reasons})
            continue
        seen_names.update(normalized_variants)
        profile = daily_map_game.map_place_selection_profile(row, selector_profile)
        aliases = [row["canonical_name"], *daily_map_game.split_list_text(row["acceptable_aliases"])]
        source_facts = [
            review_export.mask_names(
                str(fact),
                aliases,
                replacement="this place",
            )
            for fact in json.loads(row["verified_facts_json"])
        ]
        clue_ladder = daily_map_game.clue_ladder_for_row(row)
        clue_text_by_id = {
            str(clue["id"]): review_export.mask_names(
                str(clue["text"]),
                aliases,
                replacement="this place",
            )
            for clue in clue_ladder
            if str(clue.get("id") or "") != "name"
        }
        persuading_facts = [
            review_export.mask_names(str(item["text"]), aliases, replacement="this place")
            for item in profile["persuadingFacts"]
        ]
        review_row = {
            "candidate_id": row["candidate_id"],
            "source": "ai_candidate_retry" if is_known_retry else "ai_candidate",
            "existing_retry": is_known_retry,
            "interest_score": int(profile["score"]),
            "base_score": int(profile["baseScore"]),
            "feedback_adjustment": int(profile["feedbackAdjustment"]),
            "persuading_fact_count": int(profile["persuadingFactCount"]),
            "workoutability_score": int(profile["workoutabilityScore"]),
            "canonical_name": row["canonical_name"],
            "place_type": row["place_type"],
            "difficulty": row["difficulty"],
            "country_name": row["country_name"] or daily_map_game.country_name(row["country_code"]),
            "admin1": row["admin1"],
            "categories": "; ".join(profile["categories"]),
            "fact_1": source_facts[0] if len(source_facts) > 0 else "",
            "fact_2": source_facts[1] if len(source_facts) > 1 else "",
            "fact_3": source_facts[2] if len(source_facts) > 2 else "",
            "hard_clue": clue_text_by_id.get("hard") or (persuading_facts[0] if len(persuading_facts) > 0 else ""),
            "medium_clue": clue_text_by_id.get("medium") or (persuading_facts[1] if len(persuading_facts) > 1 else ""),
            "easy_clue": clue_text_by_id.get("easy") or (persuading_facts[2] if len(persuading_facts) > 2 else ""),
            "reveal_text": row["canonical_name"],
            "your_score_0_10": "",
            "your_notes": "",
            "why_fun": row["why_fun"],
            "map_guessability": row["map_guessability"],
            "source_search_queries": "; ".join(row["source_search_queries"]),
            "_pool_row": row,
        }
        review_row.update(map_selector_model.predict_score(selector_model or {}, review_row))
        review_row["clue_quality"] = {
            level: map_clue_quality_model.predict_level(
                clue_quality_model or {},
                level,
                review_row[f"{level}_clue"],
                place_type=row["place_type"],
            )
            for level in ("hard", "medium", "easy")
        }
        review_row["hard_learned_pass_probability"] = float(
            review_row["clue_quality"]["hard"].get("pass_probability") or 0
        )
        review_row["hard_learned_pass_log_odds"] = float(
            review_row["clue_quality"]["hard"].get("pass_log_odds") or -30
        )
        accepted.append(review_row)
    accepted.sort(
        key=lambda item: (
            float(item.get("hard_learned_pass_log_odds") or -30),
            float(item.get("ml_rank_score") or item["interest_score"]),
            float(item.get("ml_score") or 0),
            int(item["interest_score"]),
            int(item["persuading_fact_count"]),
            str(item["canonical_name"]),
        ),
        reverse=True,
    )
    return accepted, rejected


def rejection_feedback(rejected: list[dict[str, Any]], *, limit: int = 8) -> list[str]:
    counts: dict[str, int] = {}
    duplicate_names: list[str] = []
    for item in rejected:
        candidate = item.get("candidate", {})
        candidate_name = str(candidate.get("canonical_name") or "").strip() if isinstance(candidate, dict) else ""
        for reason in item.get("reasons", []):
            reason_text = str(reason)
            counts[reason_text] = counts.get(reason_text, 0) + 1
            if candidate_name and "already exists" in reason_text:
                duplicate_names.append(candidate_name)
    ordered = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    feedback = [f"{count} candidate(s): {reason}" for reason, count in ordered[:limit]]
    if duplicate_names:
        feedback.append(
            "Avoid these duplicate names next time: "
            + ", ".join(sorted(set(duplicate_names))[:30])
        )
    return feedback[: limit + 1]


def unique_review_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for row in rows:
        variants = normalized_name_variants(row.get("canonical_name", ""))
        if name_variants_overlap(variants, seen_names):
            continue
        seen_names.update(variants)
        unique.append(row)
    return unique


def generate_raw_candidates(
    *,
    provider: rewriter.ConfiguredMapClueProvider,
    limit: int,
    existing_places: list[dict[str, str]],
    existing_name_examples: list[str],
    blocked_name_examples: list[str],
    selector_profile: dict[str, Any],
    feedback: list[str],
    focus: str = "",
    allow_known_retries: bool = False,
) -> list[dict[str, Any]]:
    prompt = candidate_generation_prompt(
        limit=limit,
        existing_places=existing_places,
        existing_name_examples=existing_name_examples,
        blocked_name_examples=blocked_name_examples,
        selector_profile=selector_profile,
        feedback=feedback,
        focus=focus,
        allow_known_retries=allow_known_retries,
    )
    try:
        payload = provider.call_with_fallback(
            model_attr="generator_model",
            prompt=prompt,
            schema=candidate_json_schema(limit),
            tools=[{"googleSearch": {}}],
        )
    except RuntimeError as grounded_error:
        payload = provider.call_with_fallback(
            model_attr="generator_model",
            prompt=(
                prompt
                + "\n\nGrounded search was unavailable. Use only stable facts you can state "
                "with high confidence, and still provide direct source URLs for later validation. "
                f"Do not repeat this provider error in the output: {grounded_error}"
            ),
            schema=candidate_json_schema(limit),
        )
    return parse_candidate_payload(payload)


def write_candidate_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "interest_score",
        "ml_score",
        "ml_confidence",
        "ml_rank_score",
        "base_score",
        "feedback_adjustment",
        "your_score_0_10",
        "your_notes",
        "canonical_name",
        "place_type",
        "difficulty",
        "country_name",
        "admin1",
        "persuading_fact_count",
        "workoutability_score",
        "categories",
        "fact_1",
        "fact_2",
        "fact_3",
        "hard_clue",
        "medium_clue",
        "easy_clue",
        "reveal_text",
        "why_fun",
        "map_guessability",
        "source_search_queries",
        "candidate_id",
        "source",
        "existing_retry",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def insert_draft_rows(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> int:
    inserted = 0
    retry_targets: dict[str, int] = {}
    for existing in conn.execute(
        """
        SELECT id, canonical_name, reveal_text, acceptable_aliases
        FROM map_place_pool
        """
    ).fetchall():
        names = [
            existing["canonical_name"],
            existing["reveal_text"],
            *daily_map_game.split_list_text(existing["acceptable_aliases"]),
        ]
        for name in names:
            for variant in normalized_name_variants(name):
                retry_targets.setdefault(variant, int(existing["id"]))

    for review_row in rows:
        row = review_row.get("_pool_row")
        if not isinstance(row, dict):
            continue
        source = str(review_row.get("source") or "")
        if source == "ai_candidate_retry":
            candidate_variants: set[str] = set()
            for name in [
                row["canonical_name"],
                *daily_map_game.split_list_text(row["acceptable_aliases"]),
            ]:
                candidate_variants.update(normalized_name_variants(name))
            target_id = next(
                (
                    retry_targets[variant]
                    for variant in candidate_variants
                    if variant in retry_targets
                ),
                None,
            )
            if target_id is None:
                continue
            conn.execute(
                """
                UPDATE map_place_pool
                SET clue_text = ?,
                    medium_clue_text = ?,
                    easy_clue_text = ?,
                    nearby_context = ?,
                    verified_facts_json = ?,
                    sources_json = ?,
                    avoid_in_clues = ?,
                    fact_stability = ?,
                    review_status = 'machine_candidate',
                    review_notes = ?,
                    reviewed_on = ?,
                    validation_grade = ?,
                    validation_reasoning = ?,
                    active = 1
                WHERE id = ?
                """,
                (
                    row["clue_text"],
                    row["medium_clue_text"],
                    row["easy_clue_text"],
                    row["nearby_context"],
                    row["verified_facts_json"],
                    row["sources_json"],
                    row["avoid_in_clues"],
                    row["fact_stability"],
                    row["review_notes"],
                    row["reviewed_on"],
                    row["validation_grade"],
                    row["validation_reasoning"],
                    target_id,
                ),
            )
            inserted += 1
            continue
        if source != "ai_candidate":
            continue
        conn.execute(
            """
            INSERT INTO map_place_pool (
                slug, canonical_name, country_code, country_name, continent, admin1,
                place_type, difficulty, lat, lng, coordinate_precision, suggested_map_zoom,
                clue_text, medium_clue_text, easy_clue_text, reveal_text,
                acceptable_aliases, nearby_context, verified_facts_json, sources_json,
                coordinate_source_name, coordinate_source_url, avoid_in_clues,
                deconflict_group, fact_stability, review_status, review_notes, reviewed_on,
                validation_grade, validation_reasoning, scoring_radius_m, active, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'machine_candidate', ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(slug) DO UPDATE SET
                canonical_name = excluded.canonical_name,
                country_code = excluded.country_code,
                country_name = excluded.country_name,
                continent = excluded.continent,
                admin1 = excluded.admin1,
                place_type = excluded.place_type,
                difficulty = excluded.difficulty,
                lat = excluded.lat,
                lng = excluded.lng,
                coordinate_precision = excluded.coordinate_precision,
                suggested_map_zoom = excluded.suggested_map_zoom,
                clue_text = excluded.clue_text,
                medium_clue_text = excluded.medium_clue_text,
                easy_clue_text = excluded.easy_clue_text,
                reveal_text = excluded.reveal_text,
                acceptable_aliases = excluded.acceptable_aliases,
                nearby_context = excluded.nearby_context,
                verified_facts_json = excluded.verified_facts_json,
                sources_json = excluded.sources_json,
                coordinate_source_name = excluded.coordinate_source_name,
                coordinate_source_url = excluded.coordinate_source_url,
                avoid_in_clues = excluded.avoid_in_clues,
                deconflict_group = excluded.deconflict_group,
                fact_stability = excluded.fact_stability,
                review_status = 'machine_candidate',
                review_notes = excluded.review_notes,
                reviewed_on = excluded.reviewed_on,
                validation_grade = excluded.validation_grade,
                validation_reasoning = excluded.validation_reasoning,
                scoring_radius_m = excluded.scoring_radius_m,
                active = 1
            """,
            (
                row["slug"],
                row["canonical_name"],
                row["country_code"],
                row["country_name"],
                row["continent"],
                row["admin1"],
                row["place_type"],
                row["difficulty"],
                row["lat"],
                row["lng"],
                row["coordinate_precision"],
                row["suggested_map_zoom"],
                row["clue_text"],
                row["medium_clue_text"],
                row["easy_clue_text"],
                row["reveal_text"],
                row["acceptable_aliases"],
                row["nearby_context"],
                row["verified_facts_json"],
                row["sources_json"],
                row["coordinate_source_name"],
                row["coordinate_source_url"],
                row["avoid_in_clues"],
                row["deconflict_group"],
                row["fact_stability"],
                row["review_notes"],
                row["reviewed_on"],
                row["validation_grade"],
                row["validation_reasoning"],
                row["scoring_radius_m"],
                now_iso(),
            ),
        )
        inserted += 1
    return inserted


def generate_review_batch(
    *,
    db_path: Path,
    provider: rewriter.ConfiguredMapClueProvider,
    limit: int,
    batch_size: int,
    max_attempts: int,
    retry_after_minutes: int,
    focus: str = "",
    excluded_place_types: set[str] | None = None,
    feedback_dir: Path = DEFAULT_OUTPUT_DIR,
    allow_known_retries: bool = False,
    blocked_names: set[str] | None = None,
    blocked_name_examples: list[str] | None = None,
) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        daily_map_game.initialize_database(conn)
        conn.commit()
        selector_profile = daily_map_game.load_map_selector_profile()
        selector_model = map_selector_model.load_model()
        clue_quality_model_payload = map_clue_quality_model.load_model()
        existing_names = existing_place_names(conn)
        existing_context = existing_place_context(conn)
        existing_name_list = existing_place_name_examples(conn)
        reviewed_names = reviewed_feedback_place_names(feedback_dir)
        for name in reviewed_names:
            existing_names.update(normalized_name_variants(name))
        existing_name_list = [*existing_name_list, *reviewed_names]
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        feedback: list[str] = []
        attempts: list[dict[str, Any]] = []
        for attempt in range(1, max_attempts + 1):
            requested = min(batch_size, max(limit - len(accepted), 0) + max(3, batch_size // 3))
            if requested <= 0:
                break
            try:
                raw = generate_raw_candidates(
                    provider=provider,
                    limit=requested,
                    existing_places=existing_context,
                    existing_name_examples=existing_name_list,
                    blocked_name_examples=blocked_name_examples or [],
                    selector_profile=selector_profile,
                    feedback=feedback,
                    focus=focus,
                    allow_known_retries=allow_known_retries,
                )
            except Exception as error:
                reason = str(error)
                attempts.append(
                    {
                        "attempt": attempt,
                        "provider_error": reason,
                        "deferred": rewriter.provider_failure_is_deferred(reason),
                    }
                )
                if rewriter.provider_failure_is_deferred(reason) and attempt < max_attempts:
                    time.sleep(max(0, retry_after_minutes) * 60)
                    continue
                raise
            batch_accepted, batch_rejected = validated_review_rows(
                raw,
                existing_names=existing_names,
                selector_profile=selector_profile,
                excluded_place_types=excluded_place_types,
                allow_known_retries=allow_known_retries,
                blocked_names=blocked_names,
                selector_model=selector_model,
                clue_quality_model=clue_quality_model_payload,
            )
            for row in batch_accepted:
                existing_names.update(normalized_name_variants(row["canonical_name"]))
            accepted.extend(batch_accepted)
            rejected.extend(batch_rejected)
            feedback = rejection_feedback(batch_rejected)
            attempts.append(
                {
                    "attempt": attempt,
                    "requested": requested,
                    "raw_count": len(raw),
                    "accepted_count": len(batch_accepted),
                    "rejected_count": len(batch_rejected),
                    "feedback": feedback,
                }
            )
            if len(accepted) >= limit:
                break
        selected = review_export.diversified_batch(unique_review_rows(accepted), limit)
        return {
            "accepted": selected,
            "accepted_total": len(accepted),
            "rejected": rejected,
            "attempts": attempts,
            "selector_profile_summary": selector_profile_summary(selector_profile),
        }
    finally:
        conn.close()


def write_outputs(
    *,
    output_dir: Path,
    public_page: Path,
    result: dict[str, Any],
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp()
    rows = result["accepted"]
    csv_path = output_dir / f"map_ai_place_candidates_{len(rows)}_{stamp}.csv"
    json_path = output_dir / f"map_ai_place_candidates_{len(rows)}_{stamp}.json"
    write_candidate_csv(csv_path, rows)
    serializable = {
        **result,
        "accepted": [
            {key: value for key, value in row.items() if key != "_pool_row"}
            for row in rows
        ],
    }
    json_path.write_text(json.dumps(serializable, indent=2, ensure_ascii=True), encoding="utf-8")
    review_export.write_review_page(public_page, rows)
    return {
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "public_page": str(public_page),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate AI-suggested map place candidates for review.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--public-page", type=Path, default=DEFAULT_PUBLIC_PATH)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--override-env", action="store_true")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument("--retry-after-minutes", type=int, default=30)
    parser.add_argument("--insert-drafts", action="store_true")
    parser.add_argument(
        "--allow-known-retries",
        action="store_true",
        help="Beta review mode: allow existing or previously reviewed places to appear again for scoring.",
    )
    parser.add_argument("--focus", default="")
    parser.add_argument("--exclude-types", default="")
    parser.add_argument(
        "--avoid-names",
        default="",
        help="Comma or semicolon separated canonical names to block from this review batch.",
    )
    parser.add_argument("--generator-model", default="")
    parser.add_argument("--critic-model", default="")
    parser.add_argument("--timeout-sec", type=int, default=None)
    parser.add_argument("--request-delay-sec", type=float, default=None)
    parser.add_argument("--transient-retries", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"Database not found: {args.db}")
    rewriter.load_env_file(args.env_file, override=args.override_env)
    rewriter.apply_runtime_env_overrides(args)
    blocked_name_examples = [
        clean_text(value, limit=120)
        for value in re.split(r"[,;]", args.avoid_names)
        if value.strip()
    ]
    try:
        provider = rewriter.ConfiguredMapClueProvider.from_env(
            generator_model=args.generator_model,
            critic_model=args.critic_model,
        )
    except ValueError as error:
        raise SystemExit(
            f"{error} Configure GEMINI_API_KEY, or set AI_PROVIDER=openai-compatible with AI_API_KEY and AI_BASE_URL."
        ) from error

    result = generate_review_batch(
        db_path=args.db,
        provider=provider,
        limit=max(1, args.limit),
        batch_size=max(1, args.batch_size),
        max_attempts=max(1, args.max_attempts),
        retry_after_minutes=args.retry_after_minutes,
        focus=args.focus,
        excluded_place_types={
            slugify(value).replace("-", "_")
            for value in re.split(r"[,;]", args.exclude_types)
            if value.strip()
        },
        feedback_dir=args.out_dir,
        allow_known_retries=args.allow_known_retries,
        blocked_names={
            variant
            for value in blocked_name_examples
            for variant in normalized_name_variants(value)
        },
        blocked_name_examples=blocked_name_examples,
    )
    paths = write_outputs(output_dir=args.out_dir, public_page=args.public_page, result=result)
    inserted_count = 0
    if args.insert_drafts:
        conn = sqlite3.connect(args.db)
        conn.row_factory = sqlite3.Row
        try:
            daily_map_game.initialize_database(conn)
            inserted_count = insert_draft_rows(conn, result["accepted"])
            conn.commit()
        finally:
            conn.close()

    print(
        json.dumps(
            {
                "accepted_count": len(result["accepted"]),
                "accepted_total_before_diversity": result["accepted_total"],
                "rejected_count": len(result["rejected"]),
                "inserted_draft_count": inserted_count,
                "provider": provider.model_summary(),
                **paths,
                "top_10": [
                    {
                        "place": row["canonical_name"],
                        "type": row["place_type"],
                        "score": row["interest_score"],
                        "mlScore": row.get("ml_score", ""),
                        "mlRankScore": row.get("ml_rank_score", ""),
                        "categories": row["categories"],
                    }
                    for row in result["accepted"][:10]
                ],
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
