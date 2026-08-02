from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import daily_map_game
from tools import map_selector_model
from tools import map_clue_quality_model
from tools import rewrite_map_clues_with_ai as rewriter

DEFAULT_DB_PATH = PROJECT_DIR / "data" / "fultons.db"
DEFAULT_REPORT_DIR = PROJECT_DIR / "data" / "training"
DEFAULT_EVENT_BRIEF_CACHE_PATH = DEFAULT_REPORT_DIR / "map_event_brief_cache.json"
MIN_RESEARCHABLE_HARD_HOOKS = 1
MIN_RECOGNISABILITY_LEARNED_SCORE = 4.9
MIN_RECOGNISABILITY_SELECTOR_SCORE = 80
PLAYER_FACING_LOCALITY_NAMES = {
    "greater london": "London",
    "greater manchester": "Manchester",
}
WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"
VERIFICATION_EVIDENCE_USER_AGENT = (
    "FultonsQuiz/0.1 (+https://fultons-quiz.co.uk)"
)
VERIFICATION_SEARCH_STOPWORDS = {
    "after",
    "before",
    "during",
    "famous",
    "famously",
    "group",
    "hosted",
    "inside",
    "match",
    "place",
    "pitch",
    "stage",
    "stadium",
    "target",
    "their",
    "there",
    "these",
    "this",
    "venue",
    "where",
    "which",
}
VERIFICATION_EVENT_QUERY_TERMS = {
    "beat",
    "defeat",
    "defeated",
    "defeating",
    "final",
    "cup",
    "champions",
    "league",
    "cricket",
    "football",
    "murdered",
    "discovered",
    "escaped",
    "record",
    "world",
}
VERIFICATION_WORD_RE = re.compile(
    r"\b[0-9]{4}\b|\b[^\W\d_](?:[^\W_]|['’\-]){2,}\b",
    re.UNICODE,
)
DIRECT_EVIDENCE_STOPWORDS = VERIFICATION_SEARCH_STOPWORDS | {
    "about",
    "against",
    "also",
    "among",
    "because",
    "being",
    "between",
    "could",
    "exact",
    "from",
    "happened",
    "have",
    "having",
    "here",
    "into",
    "itself",
    "local",
    "occurred",
    "their",
    "through",
    "upon",
    "using",
    "were",
    "while",
    "with",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def event_brief_cache_key(selected_hook: dict[str, Any], place: dict[str, Any]) -> str:
    identity = (
        f"v3:{selected_hook.get('place_id') or place.get('canonical_name')}:"
        f"{selected_hook.get('verified_hard_hook') or ''}"
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def load_event_brief_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "entries": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "entries": {}}
    entries = payload.get("entries") if isinstance(payload, dict) else None
    return {
        "version": 1,
        "entries": entries if isinstance(entries, dict) else {},
    }


def save_event_brief_cache(
    path: Path,
    *,
    cache_key: str,
    selected_hook: dict[str, Any],
    place: dict[str, Any],
    event_brief: dict[str, Any],
) -> None:
    payload = load_event_brief_cache(path)
    payload["updated_at"] = utc_now()
    payload["entries"][cache_key] = {
        "place_id": selected_hook.get("place_id"),
        "place": str(place.get("canonical_name") or selected_hook.get("place") or ""),
        "verified_hard_hook": str(selected_hook.get("verified_hard_hook") or ""),
        **event_brief,
        "cached_at": utc_now(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary_path.replace(path)


def selection_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "hook_id": {"type": "string"},
            "selection_reason": {"type": "string"},
        },
        "required": ["hook_id", "selection_reason"],
        "additionalProperties": False,
    }


def event_brief_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "enriched_hard_hook": {"type": "string"},
            "supporting_details": {
                "type": "array",
                "items": {"type": "string"},
            },
            "used_source_urls": {
                "type": "array",
                "items": {"type": "string"},
            },
            "confidence": {"type": "integer"},
        },
        "required": [
            "enriched_hard_hook",
            "supporting_details",
            "used_source_urls",
            "confidence",
        ],
        "additionalProperties": False,
    }


def event_place_verification_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "passed": {"type": "boolean"},
            "confidence": {"type": "integer"},
            "failure_reasons": {
                "type": "array",
                "items": {"type": "string"},
            },
            "used_source_urls": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "passed",
            "confidence",
            "failure_reasons",
            "used_source_urls",
        ],
        "additionalProperties": False,
    }


def source_urls(row: sqlite3.Row) -> list[str]:
    try:
        payload = json.loads(str(row["sources_json"] or "[]"))
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(payload, list):
        return []
    urls: list[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if url and url not in urls:
            urls.append(url)
    return urls[:5]


def recent_place_ids(conn: sqlite3.Connection, puzzle_date: str) -> set[int]:
    cutoff = (
        datetime.strptime(daily_map_game.valid_game_date(puzzle_date), "%Y-%m-%d")
        - timedelta(days=daily_map_game.RECENT_USE_DAYS)
    ).date().isoformat()
    return {
        int(row["place_id"])
        for row in conn.execute(
            """
            SELECT DISTINCT daily_map_levels.place_id
            FROM daily_map_levels
            INNER JOIN daily_map_puzzles
                ON daily_map_puzzles.id = daily_map_levels.puzzle_id
            WHERE daily_map_puzzles.puzzle_date >= ?
              AND daily_map_puzzles.puzzle_date <= ?
            """,
            (cutoff, puzzle_date),
        ).fetchall()
    }


def candidate_summary(
    row: sqlite3.Row,
    *,
    selector_profile: dict[str, Any],
    selector_model: dict[str, Any],
    clue_quality_model: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    place = daily_map_game.public_place_payload(row)
    hard_hooks = daily_map_game.qualifying_hard_hook_candidates(place)
    if len(hard_hooks) < MIN_RESEARCHABLE_HARD_HOOKS:
        return None
    hard_hooks = [
        {
            **hook,
            "learned_quality": map_clue_quality_model.predict_level(
                clue_quality_model or {},
                "hard",
                hook["text"],
                place_type=place["place_type"],
            ),
        }
        for hook in hard_hooks
    ]
    facts = [item["text"] for item in daily_map_game.persuading_place_facts(place)]
    for hook in hard_hooks:
        text = str(hook["text"])
        if text not in facts:
            facts.append(text)

    selection = daily_map_game.map_place_selection_profile(row, selector_profile)
    hard_text = str(hard_hooks[0]["text"])
    remaining_facts = [fact for fact in facts if fact != hard_text]
    medium_text = str(
        row["medium_clue_text"]
        or (remaining_facts[0] if remaining_facts else "")
        or row["nearby_context"]
        or row["admin1"]
        or row["country_name"]
        or row["country_code"]
    )
    easy_text = str(
        row["easy_clue_text"]
        or row["nearby_context"]
        or (remaining_facts[1] if len(remaining_facts) > 1 else medium_text)
    )
    model_row = {
        **dict(row),
        "facts": facts,
        "hard_clue": hard_text,
        "medium_clue": medium_text,
        "easy_clue": easy_text,
        "machine_score": selection["score"],
        "interest_score": selection["score"],
        "persuading_fact_count": len(facts),
        "workoutability_score": selection["workoutabilityScore"],
        "categories": "; ".join(selection["categories"]),
    }
    prediction = map_selector_model.predict_score(selector_model, model_row)
    return {
        "place_id": int(row["id"]),
        "name": str(row["canonical_name"]),
        "place_type": str(row["place_type"]),
        "difficulty": str(row["difficulty"]),
        "country": str(row["country_name"] or row["country_code"]),
        "region": str(row["admin1"] or ""),
        "verified_facts": facts[:5],
        "hard_hook_candidates": hard_hooks,
        "map_guessability": str(row["nearby_context"] or ""),
        "workoutability_score": int(daily_map_game.map_workoutability_score(row)),
        "selector_score": int(selection["score"]),
        "learned_score": float(prediction.get("ml_score", 0.0)),
        "learned_confidence": float(prediction.get("ml_confidence", 0.0)),
        "categories": selection["categories"],
        "source_urls": source_urls(row),
    }


def candidate_shortlist(
    conn: sqlite3.Connection,
    *,
    puzzle_date: str,
    limit: int = 24,
    eligible_names: set[str] | None = None,
    excluded_names: set[str] | None = None,
    required_place_type: str | None = None,
) -> list[dict[str, Any]]:
    excluded = recent_place_ids(conn, puzzle_date)
    explicitly_excluded_names = {
        str(name).strip().casefold()
        for name in (excluded_names or set())
        if str(name).strip()
    }
    selector_profile = daily_map_game.load_map_selector_profile()
    selector_model = map_selector_model.load_model()
    clue_quality_model_payload = map_clue_quality_model.load_model()
    rows = conn.execute(
        """
        SELECT *
        FROM map_place_pool
        WHERE active = 1
          AND verified_facts_json <> '[]'
          AND nearby_context <> ''
        ORDER BY COALESCE(validation_grade, 0) DESC, id
        """
    ).fetchall()
    candidates: list[dict[str, Any]] = []
    required_type = str(required_place_type or "").strip().casefold()
    for row in rows:
        canonical_name = str(row["canonical_name"]).strip().casefold()
        if (
            eligible_names is not None
            and canonical_name not in eligible_names
        ):
            continue
        if canonical_name in explicitly_excluded_names:
            continue
        if int(row["id"]) in excluded or daily_map_game.place_is_explicitly_excluded(row):
            continue
        if required_type and str(row["place_type"]).strip().casefold() != required_type:
            continue
        summary = candidate_summary(
            row,
            selector_profile=selector_profile,
            selector_model=selector_model,
            clue_quality_model=clue_quality_model_payload,
        )
        if summary is not None:
            candidates.append(summary)
    candidates.sort(
        key=lambda item: (
            max(
                float((hook.get("learned_quality") or {}).get("pass_log_odds") or -30)
                for hook in item["hard_hook_candidates"]
            ),
            max(
                int(hook["specificity_score"])
                for hook in item["hard_hook_candidates"]
            ),
            item["learned_score"] * max(0.35, item["learned_confidence"]),
            item["selector_score"],
            len(item["categories"]),
        ),
        reverse=True,
    )
    return candidates[: max(1, limit)]


def hard_hook_shortlist(
    conn: sqlite3.Connection,
    *,
    puzzle_date: str,
    limit: int = 48,
    eligible_names: set[str] | None = None,
    excluded_names: set[str] | None = None,
    required_place_type: str | None = None,
) -> list[dict[str, Any]]:
    places = candidate_shortlist(
        conn,
        puzzle_date=puzzle_date,
        limit=max(limit * 2, 80),
        eligible_names=eligible_names,
        excluded_names=excluded_names,
        required_place_type=required_place_type,
    )
    hooks: list[dict[str, Any]] = []
    seen_hooks: set[tuple[str, str]] = set()
    for place in places:
        for hook in place["hard_hook_candidates"]:
            text = str(hook["text"])
            hook_key = (str(place["name"]).strip().casefold(), text.strip().casefold())
            if hook_key in seen_hooks:
                continue
            seen_hooks.add(hook_key)
            digest = hashlib.sha256(
                f"{place['place_id']}:{text}".encode("utf-8")
            ).hexdigest()[:12]
            hooks.append(
                {
                    "hook_id": f"{place['place_id']}:{digest}",
                    "place_id": int(place["place_id"]),
                    "place": str(place["name"]),
                    "place_type": str(place["place_type"]),
                    "country": str(place["country"]),
                    "region": str(place["region"]),
                    "verified_hard_hook": text,
                    "hook_specificity_score": int(hook["specificity_score"]),
                    "learned_hard_pass_probability": float(
                        (hook.get("learned_quality") or {}).get("pass_probability") or 0
                    ),
                    "learned_hard_pass_log_odds": float(
                        (hook.get("learned_quality") or {}).get("pass_log_odds") or -30
                    ),
                    "learned_hard_negative_signals": list(
                        (hook.get("learned_quality") or {}).get("negative_signals") or []
                    ),
                    "map_guessability": str(place["map_guessability"]),
                    "workoutability_score": int(place["workoutability_score"]),
                    "remaining_verified_facts": [
                        fact
                        for fact in place["verified_facts"]
                        if fact != text
                    ][:4],
                    "selector_score": int(place["selector_score"]),
                    "learned_score": float(place["learned_score"]),
                    "learned_confidence": float(place["learned_confidence"]),
                    "categories": list(place["categories"]),
                    "source_urls": list(place["source_urls"]),
                }
            )
    hooks.sort(
        key=lambda item: (
            float(item["learned_hard_pass_log_odds"]),
            float(item["learned_score"])
            * max(0.35, float(item["learned_confidence"])),
            int(item["selector_score"]),
            int(item["hook_specificity_score"]),
        ),
        reverse=True,
    )
    return hooks[: max(1, limit)]


def hard_hook_selection_prompt(
    hooks: list[dict[str, Any]],
    *,
    puzzle_date: str,
) -> str:
    return f"""Choose exactly one verified hard hook for the {puzzle_date} Fulton's Quiz map round.

The audience is an adult player. The round should be fun, challenging, and beatable.

The hook determines the place. Do not choose a place first and then try to engineer a hook for it.
Choose from the supplied hook_id values only. Do not invent or rewrite an incident.

Selection requirements:
- Prefer a unique, specific incident or story tied to one place.
- A distinctive record, achievement, discovery, person-linked episode, tradition, natural occurrence, or cultural moment may qualify when it is genuinely recognisable.
- A player who knows the hook should be able to associate it with this place.
- Reject architecture, architects, construction, age, appearance, dimensions, generic destruction, broad war history, UNESCO status, former records presented as current, and ordinary events.
- Opening or being built for a competition is an origin fact, not a qualifying hook.
- Reject vague claims such as "a final was played here" when several events could fit.
- Reject hooks that are technically specific but too obscure or joyless for the adult player.
- The hook is the only interest requirement. Medium and easy can be built afterwards to reduce the map area.
- Check only that the place has one fair pin and enough verified map context to build that route.
- Reject a place that can only be found if the player already knows its exact coordinates.
- Reject a broad, compound, linear, or ambiguous target without one fair pin.
- Use learned scores as evidence, not as an automatic answer.
- Do not write the clues yet. Select the strongest verified recognition hook.

Verified hook candidates:
{json.dumps(hooks, indent=2, ensure_ascii=False)}

Return JSON only."""


def choose_hard_hook(
    provider: rewriter.ConfiguredMapClueProvider,
    hooks: list[dict[str, Any]],
    *,
    puzzle_date: str,
) -> tuple[dict[str, Any], str]:
    if not hooks:
        raise LookupError("No verified, map-playable recognition hooks are available.")
    payload = provider.call_with_fallback(
        model_attr="generator_model",
        prompt=hard_hook_selection_prompt(hooks, puzzle_date=puzzle_date),
        schema=selection_schema(),
    )
    hook_id = str(payload.get("hook_id") or "").strip()
    selected = next(
        (hook for hook in hooks if str(hook["hook_id"]) == hook_id),
        None,
    )
    if selected is None:
        raise ValueError("The model selected a hook outside the verified shortlist.")
    return selected, str(payload.get("selection_reason") or "").strip()


def choose_learned_hard_hook(
    hooks: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    if not hooks:
        raise LookupError("No verified, map-playable recognition hooks are available.")
    eligible = [
        hook
        for hook in hooks
        if float(hook.get("learned_score") or 0)
        >= MIN_RECOGNISABILITY_LEARNED_SCORE
        and int(hook.get("selector_score") or 0)
        >= MIN_RECOGNISABILITY_SELECTOR_SCORE
    ]
    if not eligible:
        best = hooks[0]
        raise LookupError(
            "No verified hook met the minimum human-learned recognisability "
            f"thresholds (learned score >= {MIN_RECOGNISABILITY_LEARNED_SCORE:.1f} "
            f"and selector score >= {MIN_RECOGNISABILITY_SELECTOR_SCORE}); "
            f"best remaining candidate was {best.get('place') or 'unknown'} at "
            f"{float(best.get('learned_score') or 0):.3f}/"
            f"{int(best.get('selector_score') or 0)}."
        )
    selected = eligible[0]
    return selected, (
        "Selected by the trained place-ranking profile using human review, "
        f"with learned score {float(selected.get('learned_score') or 0):.3f}, "
        f"confidence {float(selected.get('learned_confidence') or 0):.3f}, "
        f"and selector score {int(selected.get('selector_score') or 0)}."
    )


def event_brief_prompt(
    selected_hook: dict[str, Any],
    *,
    place: dict[str, Any],
    feedback: list[str] | None = None,
) -> str:
    return f"""Research and enrich one selected recognition hook for Fulton's map quiz.

Target place (for research only):
{json.dumps(place, indent=2, ensure_ascii=False)}

Selected verified recognition hook:
{selected_hook["verified_hard_hook"]}

Preferred source URLs:
{json.dumps(selected_hook.get("source_urls") or [], indent=2)}

Use Google Search to independently verify the event before writing.
Treat preferred source URLs only as starting references; do not assume that they
support the selected hook.

Return one answer-safe enriched hook:
- Prefer one clear sentence, but preserve the information needed to make the hook recognisable.
- Preserve the selected incident, story, record, achievement, discovery, person-linked episode, tradition, natural occurrence, or cultural moment.
- Add concrete narrative information, not adjectives or padding.
- For an event, name useful actors or sides, say what happened, and add at least one of: trigger, defining method, consequence, score, record, or why it mattered.
- For a non-event hook, state the specific record, achievement, association, tradition, or phenomenon and why it is distinctive.
- Name useful people, teams, organisations, forces, works, or records when answer-safe.
- For a team match or final, name both teams and the result; do not replace the competing sides with a scorer or attendance figure.
- Keep the hook to one coherent event, record, or story. Never merge separate matches or incidents, or imply that an event happened during a different match.
- Verify the exact competition stage, date, participants, result, and relationship between every claim. If the supplied capsule conflates separate events, retain only one accurately sourced recognition hook.
- Verify that the event occurred at this exact target place, not merely in the same city, tournament, institution, or venue group.
- A record may cite the separate events that establish it, but omit unrelated anecdotes from those events.
- Country names are allowed when they are the proper names of national teams or other essential event participants. Never replace one with "the host nation", "the visitors", or a similar generic label.
- Tie the hook to the target with "here", "on this pitch", "inside this building", "at this site", or another answer-safe equivalent.
- State the target's concrete answer-safe identity when the supplied place data supports it. For example, write "the federal prison on this island", "on this pitch", or "inside this church"; never collapse useful identities such as prison and island into only "this site" or "here".
- Do not merely state that an event happened or that a record existed.
- Reject a bare headline, date, former record, or destruction percentage even when it is factually correct.
- Apart from essential named event participants, do not add country, nationality, capital, city, region, river, direction, or nearby-place hints.
- Do not include the target place name, an alias, or a distinctive target-name word.
- Do not include unsupported or disputed detail.
- If the hook involves a record, verify whether it is current or former and word it accurately.
- supporting_details must list the factual claims added to the original hook.
- used_source_urls must contain the URLs actually used.
- Set confidence below 80 if the richer details cannot be verified.

Previous rejected attempts to correct:
{json.dumps((feedback or [])[-2:], indent=2, ensure_ascii=False)}

Return JSON only."""


def compress_event_capsule_to_limit(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def research_event_brief(
    provider: rewriter.ConfiguredMapClueProvider,
    selected_hook: dict[str, Any],
    *,
    place: dict[str, Any],
    cache_path: Path | None = DEFAULT_EVENT_BRIEF_CACHE_PATH,
) -> dict[str, Any]:
    cache_key = event_brief_cache_key(selected_hook, place)
    if cache_path is not None:
        cached = load_event_brief_cache(cache_path)["entries"].get(cache_key)
        if isinstance(cached, dict):
            try:
                return validate_event_brief(cached, selected_hook, place=place)
            except ValueError:
                pass

    grounding_tools = [{"googleSearch": {}}]
    feedback: list[str] = []
    last_error: ValueError | None = None
    for _attempt in range(3):
        prompt = event_brief_prompt(selected_hook, place=place, feedback=feedback)
        try:
            payload = provider.call_with_fallback(
                model_attr="generator_model",
                prompt=prompt,
                schema=event_brief_schema(),
                tools=grounding_tools,
            )
        except RuntimeError as grounded_error:
            payload = provider.call_with_fallback(
                model_attr="generator_model",
                prompt=(
                    prompt
                    + "\n\nGrounding tools were unavailable. Preserve only facts you can state "
                    "with high confidence from the supplied capsule and source references. "
                    f"Do not repeat this provider error in the output: {grounded_error}"
                ),
                schema=event_brief_schema(),
            )
        try:
            event_brief = validate_event_brief(payload, selected_hook, place=place)
        except ValueError as error:
            last_error = error
            feedback.append(str(error))
            continue
        if cache_path is not None:
            save_event_brief_cache(
                cache_path,
                cache_key=cache_key,
                selected_hook=selected_hook,
                place=place,
                event_brief=event_brief,
            )
        return event_brief
    raise last_error or ValueError("Grounded hook research did not return a valid result.")


def event_place_verification_prompt(
    selected_hook: dict[str, Any],
    event_brief: dict[str, Any],
    *,
    place: dict[str, Any],
) -> str:
    return f"""Independently verify that a proposed map-quiz recognition hook belongs to the exact target place.

Target place:
{json.dumps(place, indent=2, ensure_ascii=False)}

Original proposed hook:
{selected_hook["verified_hard_hook"]}

Researched hook:
{event_brief["enriched_hard_hook"]}

Do not trust either hook or its supplied source list. Use Google Search and fail closed.

Set passed to true only when reliable sources explicitly support all material claims:
- The exact event, record, incident, person-linked episode, or achievement belongs to this exact target place.
- A match or sporting event occurred at this exact stadium or venue, not another venue in the same city, tournament, group, or club.
- The competition stage, date or year, named participants, score or outcome, and stated significance are accurate.
- Separate events have not been merged or presented as one event.
- A claimed current record is still current; a former record is labelled former.

If the event is real but occurred somewhere else, passed must be false.
If the exact target-event connection cannot be confirmed, passed must be false.
Confidence must reflect the target-event connection, not merely whether the event itself happened.
Return the direct URLs actually used to verify the connection and concise failure reasons.
Return JSON only."""


def wikipedia_verification_evidence(
    selected_hook: dict[str, Any],
    event_brief: dict[str, Any],
    *,
    place: dict[str, Any],
    limit: int = 5,
) -> list[dict[str, str]]:
    canonical_name = str(place.get("canonical_name") or "").strip()
    hook_text = re.sub(
        r"\s+",
        " ",
        " ".join(
            (
                str(selected_hook.get("verified_hard_hook") or ""),
                str(event_brief.get("enriched_hard_hook") or ""),
            )
        ),
    ).strip()
    keywords: list[str] = []
    for token in VERIFICATION_WORD_RE.findall(hook_text):
        normalized = token.casefold()
        if normalized in VERIFICATION_SEARCH_STOPWORDS or normalized in {
            item.casefold() for item in canonical_name.split()
        }:
            continue
        if normalized not in {item.casefold() for item in keywords}:
            keywords.append(token)
    keywords = [
        item
        for _index, item in sorted(
            enumerate(keywords),
            key=lambda pair: (
                0
                if pair[1].isdigit()
                else 1
                if pair[1][0].isupper()
                or pair[1].casefold() in VERIFICATION_EVENT_QUERY_TERMS
                else 2,
                pair[0],
            ),
        )
    ][:12]
    event_keywords = [
        item
        for item in keywords
        if item.isdigit()
        or item[0].isupper()
        or item.casefold() in VERIFICATION_EVENT_QUERY_TERMS
    ][:9]
    quoted_target = f'"{canonical_name}"' if canonical_name else ""
    search_queries = [
        " ".join(event_keywords).strip(),
        " ".join((quoted_target, *event_keywords[:7])).strip(),
        canonical_name,
    ]
    page_ids: list[int] = []
    search_snippets: dict[int, list[str]] = {}
    max_pages = max(1, min(8, limit))
    unique_queries = list(dict.fromkeys(
        re.sub(r"\s+", " ", item).strip()
        for item in search_queries
        if item.strip()
    ))
    pages_per_query = max(1, (max_pages + len(unique_queries) - 1) // len(unique_queries))
    for query in unique_queries:
        search_url = f"{WIKIPEDIA_API_URL}?{urlencode({
            'action': 'query',
            'list': 'search',
            'srsearch': query,
            'srlimit': '4',
            'format': 'json',
            'formatversion': '2',
        })}"
        request = Request(
            search_url,
            headers={
                "Accept": "application/json",
                "User-Agent": VERIFICATION_EVIDENCE_USER_AGENT,
            },
        )
        with urlopen(request, timeout=10) as response:
            search_payload = json.loads(response.read().decode("utf-8"))
        raw_results = (
            search_payload.get("query", {}).get("search", [])
            if isinstance(search_payload, dict)
            else []
        )
        added_for_query = 0
        for item in raw_results:
            if not isinstance(item, dict) or not str(item.get("pageid") or "").isdigit():
                continue
            page_id = int(item["pageid"])
            snippet = re.sub(
                r"\s+",
                " ",
                unescape(re.sub(r"<[^>]+>", " ", str(item.get("snippet") or ""))),
            ).strip()
            if snippet and snippet not in search_snippets.setdefault(page_id, []):
                search_snippets[page_id].append(snippet)
            if page_id not in page_ids:
                page_ids.append(page_id)
                added_for_query += 1
            if added_for_query >= pages_per_query or len(page_ids) >= max_pages:
                break
        if len(page_ids) >= max_pages:
            break
    if not page_ids:
        return []

    extract_url = f"{WIKIPEDIA_API_URL}?{urlencode({
        'action': 'query',
        'prop': 'extracts',
        'explaintext': '1',
        'exintro': '1',
        'exchars': '1200',
        'exlimit': 'max',
        'pageids': '|'.join(str(page_id) for page_id in page_ids),
        'format': 'json',
        'formatversion': '2',
    })}"
    extract_request = Request(
        extract_url,
        headers={
            "Accept": "application/json",
            "User-Agent": VERIFICATION_EVIDENCE_USER_AGENT,
        },
    )
    with urlopen(extract_request, timeout=10) as response:
        extract_payload = json.loads(response.read().decode("utf-8"))
    pages = (
        extract_payload.get("query", {}).get("pages", [])
        if isinstance(extract_payload, dict)
        else []
    )
    evidence: list[dict[str, str]] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_id = str(page.get("pageid") or "").strip()
        title = str(page.get("title") or "").strip()
        extract = re.sub(r"\s+", " ", str(page.get("extract") or "")).strip()
        if not page_id.isdigit() or not title or not extract:
            continue
        snippets = search_snippets.get(int(page_id), [])
        evidence_text = " ".join(
            [
                *(f"Search excerpt: {snippet}" for snippet in snippets),
                f"Page extract: {extract}",
            ]
        )
        evidence.append(
            {
                "title": title,
                "url": f"https://en.wikipedia.org/?curid={page_id}",
                "extract": evidence_text[:1800],
            }
        )
    return evidence


def verification_token(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(
        character for character in folded if not unicodedata.combining(character)
    )
    if normalized.isdigit():
        return normalized
    if len(normalized) > 6 and normalized.endswith("ing"):
        return normalized[:-3]
    if len(normalized) > 5 and normalized.endswith("ied"):
        return normalized[:-3] + "y"
    if len(normalized) > 5 and normalized.endswith("ed"):
        return normalized[:-2]
    if len(normalized) > 5 and normalized.endswith("es"):
        return normalized[:-2]
    if len(normalized) > 4 and normalized.endswith("s"):
        return normalized[:-1]
    return normalized


def exact_target_page_support(
    evidence: list[dict[str, str]],
    selected_hook: dict[str, Any],
    *,
    place: dict[str, Any],
) -> dict[str, Any] | None:
    canonical_name = verification_token(str(place.get("canonical_name") or ""))
    canonical_phrase = re.sub(r"[^a-z0-9]+", " ", canonical_name).strip()
    candidate_pages = sorted(
        (
            item
            for item in evidence
            if verification_token(str(item.get("title") or "")) == canonical_name
            or canonical_phrase
            in re.sub(
                r"[^a-z0-9]+",
                " ",
                verification_token(str(item.get("extract") or "")),
            ).strip()
        ),
        key=lambda item: (
            verification_token(str(item.get("title") or "")) != canonical_name
        ),
    )
    if not candidate_pages:
        return None
    hook_text = str(selected_hook.get("verified_hard_hook") or "")
    claim_tokens = {
        verification_token(token)
        for token in VERIFICATION_WORD_RE.findall(hook_text)
        if token.casefold() not in DIRECT_EVIDENCE_STOPWORDS
    }
    claim_tokens.discard("")
    years = set(re.findall(r"\b[0-9]{4}\b", hook_text))
    for target_page in candidate_pages:
        evidence_tokens = {
            verification_token(token)
            for token in VERIFICATION_WORD_RE.findall(str(target_page.get("extract") or ""))
        }
        matched = claim_tokens & evidence_tokens
        coverage = len(matched) / max(1, len(claim_tokens))
        exact_title = (
            verification_token(str(target_page.get("title") or "")) == canonical_name
        )
        minimum_coverage = 0.8 if exact_title else 0.75
        if (
            len(claim_tokens) >= 4
            and coverage >= minimum_coverage
            and years.issubset(evidence_tokens)
        ):
            return {
                "url": str(target_page.get("url") or ""),
                "coverage": coverage,
                "matched_tokens": sorted(matched),
            }
    return None


def verify_event_place_connection(
    provider: rewriter.ConfiguredMapClueProvider,
    selected_hook: dict[str, Any],
    event_brief: dict[str, Any],
    *,
    place: dict[str, Any],
) -> dict[str, Any]:
    prompt = event_place_verification_prompt(
        selected_hook,
        event_brief,
        place=place,
    )
    evidence: list[dict[str, str]] = []
    payload: dict[str, Any] | None = None
    try:
        payload = provider.call_with_fallback(
            model_attr="critic_model",
            prompt=prompt,
            schema=event_place_verification_schema(),
            tools=[{"googleSearch": {}}],
        )
    except RuntimeError:
        pass

    try:
        grounded_confidence = int((payload or {}).get("confidence") or 0)
    except (TypeError, ValueError):
        grounded_confidence = 0
    grounded_reasons = [
        str(reason).strip()
        for reason in (payload or {}).get("failure_reasons") or []
        if str(reason).strip()
    ]
    grounded_urls = [
        str(url).strip()
        for url in (payload or {}).get("used_source_urls") or []
        if str(url).strip()
    ]
    grounded_passed = (
        (payload or {}).get("passed") is True
        and grounded_confidence >= 90
        and not grounded_reasons
        and bool(grounded_urls)
    )
    if not grounded_passed:
        try:
            evidence = wikipedia_verification_evidence(
                selected_hook,
                event_brief,
                place=place,
            )
        except Exception as evidence_error:
            raise ValueError(
                "Independent target-event verification had no grounded provider "
                f"and Wikipedia evidence failed: {evidence_error}"
            ) from evidence_error
        if not evidence:
            payload = payload or {}
        else:
            direct_support = exact_target_page_support(
                evidence,
                selected_hook,
                place=place,
            )
            if direct_support and direct_support["url"]:
                return {
                    "passed": True,
                    "confidence": 100,
                    "failure_reasons": [],
                    "used_source_urls": [direct_support["url"]],
                    "evidence_source": "wikipedia_exact_page",
                    "direct_evidence_coverage": direct_support["coverage"],
                }
            payload = provider.call_with_fallback(
                model_attr="critic_model",
                prompt=(
                    prompt
                    + "\n\nJudge only the following independently retrieved "
                    "Wikipedia evidence. Do not use memory or infer a target-event "
                    "connection that the extracts do not state explicitly. "
                    "used_source_urls may contain only supplied URLs:\n"
                    + json.dumps(evidence, indent=2, ensure_ascii=False)
                ),
                schema=event_place_verification_schema(),
                prefer_non_gemini=True,
            )
    payload = payload or {}
    try:
        confidence = int(payload.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0
    reasons = [
        str(reason).strip()
        for reason in payload.get("failure_reasons") or []
        if str(reason).strip()
    ]
    used_urls = [
        str(url).strip()
        for url in payload.get("used_source_urls") or []
        if str(url).strip()
    ]
    if evidence:
        allowed_urls = {item["url"] for item in evidence}
        unsupported_urls = [url for url in used_urls if url not in allowed_urls]
        if unsupported_urls:
            reasons.append(
                "fallback verifier cited URLs outside the supplied evidence"
            )
    if (
        payload.get("passed") is not True
        or confidence < 90
        or not used_urls
        or reasons
    ):
        detail = "; ".join(reasons) or "exact target-event connection was not verified"
        raise ValueError(
            f"Independent target-event verification failed at confidence {confidence}: {detail}"
        )
    return {
        "passed": True,
        "confidence": confidence,
        "failure_reasons": [],
        "used_source_urls": used_urls,
        "evidence_source": "wikipedia" if evidence else "provider_web_search",
    }


def reverse_geocoded_locality(place: dict[str, Any]) -> str:
    if str(place.get("place_type") or "").strip().casefold() in {
        "city",
        "town",
        "municipality",
        "village",
    }:
        canonical_name = str(place.get("canonical_name") or "").strip()
        if canonical_name:
            return canonical_name
    result = daily_map_game.fetch_reverse_geocode(
        float(place["lat"]),
        float(place["lng"]),
        10,
    )
    if not isinstance(result, dict):
        raise ValueError("No low-zoom locality could be verified for this map target.")
    address = result.get("address")
    if not isinstance(address, dict):
        address = {}
    for key in ("city", "town", "municipality", "village"):
        value = str(address.get(key) or "").strip()
        if value:
            return PLAYER_FACING_LOCALITY_NAMES.get(value.casefold(), value)
    raise ValueError(
        "Reverse geocoding did not return a city, town, municipality, or village at zoom 10."
    )


def map_anchor_reveal_index(name: str, clue_ladder: dict[str, Any]) -> int | None:
    name_key = daily_map_game.normalized_place_name(name)
    if not name_key:
        return None
    for reveal_index, field in ((1, "medium"), (2, "easy")):
        clue_key = daily_map_game.normalized_place_name(clue_ladder.get(field))
        if name_key in clue_key:
            return reveal_index
    return None


def geocode_result_matches_anchor(result: dict[str, Any], anchor_name: str) -> bool:
    address = result.get("address") if isinstance(result.get("address"), dict) else {}
    values = [
        str(result.get("display_name") or ""),
        *[
            str(address.get(key) or "")
            for key in (
                "city",
                "town",
                "municipality",
                "village",
                "state",
                "province",
                "region",
                "county",
            )
        ],
    ]
    anchor_key = daily_map_game.normalized_place_name(anchor_name)
    return any(
        anchor_key and anchor_key in daily_map_game.normalized_place_name(value)
        for value in values
    )


def geocode_anchor_scope_rank(result: dict[str, Any], anchor_name: str) -> int:
    address = result.get("address") if isinstance(result.get("address"), dict) else {}
    anchor_key = daily_map_game.normalized_place_name(anchor_name)
    for rank, keys in enumerate(
        (
            ("city", "town", "municipality", "village"),
            ("state", "province", "region"),
            ("county",),
        )
    ):
        if any(
            anchor_key
            and anchor_key == daily_map_game.normalized_place_name(address.get(key))
            for key in keys
        ):
            return rank
    return 3


def build_verified_map_search_anchors(
    place: dict[str, Any],
    clue_ladder: dict[str, Any],
    *,
    locality_name: str,
) -> list[dict[str, Any]]:
    answer_names = {
        daily_map_game.normalized_place_name(name)
        for name in (
            str(place.get("canonical_name") or ""),
            *[str(item) for item in place.get("acceptable_aliases") or []],
        )
        if str(name or "").strip()
    }
    candidates = [
        str(locality_name or "").strip(),
        str(place.get("admin1") or "").strip(),
    ]
    anchor_name = ""
    min_hint_count: int | None = None
    for candidate in candidates:
        candidate_key = daily_map_game.normalized_place_name(candidate)
        reveal_index = map_anchor_reveal_index(candidate, clue_ladder)
        if candidate_key and candidate_key not in answer_names and reveal_index is not None:
            anchor_name = candidate
            min_hint_count = reveal_index
            break
    if not anchor_name or min_hint_count is None:
        raise ValueError(
            "No answer-safe locality or region named by the medium/easy clues could be used as a map search anchor."
        )

    query_parts = [
        anchor_name,
        str(place.get("admin1") or "").strip(),
        str(place.get("country_name") or "").strip(),
    ]
    query_text = ", ".join(dict.fromkeys(part for part in query_parts if part))
    results = daily_map_game.fetch_forward_geocode(
        query_text,
        country_code=str(place.get("country_code") or ""),
        include_boundary_geometry=True,
    )
    verified: list[tuple[int, int, float, float, float, dict[str, Any] | None]] = []
    for result in results:
        if not geocode_result_matches_anchor(result, anchor_name):
            continue
        point = daily_map_game.reverse_geocode_point(result)
        if point is None:
            continue
        distance_m = daily_map_game.haversine_m(
            float(place["lat"]),
            float(place["lng"]),
            point[0],
            point[1],
        )
        if distance_m <= 250_000:
            try:
                importance = float(result.get("importance") or 0)
            except (TypeError, ValueError):
                importance = 0
            verified.append(
                (
                    geocode_anchor_scope_rank(result, anchor_name),
                    distance_m,
                    point[0],
                    point[1],
                    importance,
                    daily_map_game.serialize_map_boundary(result.get("geojson")),
                )
            )
    if not verified:
        raise ValueError(
            f"The named map search anchor {anchor_name} could not be geocoded within 250 km of the answer."
        )
    _scope_rank, _distance_m, anchor_lat, anchor_lng, importance, boundary = min(
        verified,
        key=lambda item: (item[0], item[5] is None, item[1], -item[4]),
    )
    display_zoom = 4 if importance >= 0.55 else 5 if importance >= 0.35 else 6
    anchors = [
        {
            "name": anchor_name,
            "lat": anchor_lat,
            "lng": anchor_lng,
            "min_hint_count": min_hint_count,
            "min_zoom": display_zoom,
            "max_zoom": 9,
        }
    ]
    if boundary is not None:
        anchors[0]["boundary"] = boundary
        anchors[0]["boundary_min_zoom"] = max(5, display_zoom)
    canonical_name = str(place.get("canonical_name") or "").strip()
    if canonical_name:
        anchors.append(
            {
                "name": canonical_name,
                "lat": float(place["lat"]),
                "lng": float(place["lng"]),
                "min_hint_count": 2,
                "min_zoom": 12,
                "max_zoom": 19,
            }
        )
    return anchors


def save_map_search_anchors(
    conn: sqlite3.Connection,
    *,
    place_id: int,
    anchors: list[dict[str, Any]],
) -> None:
    conn.execute(
        "UPDATE map_place_pool SET map_search_anchors_json = ? WHERE id = ?",
        (json.dumps(anchors, ensure_ascii=False), place_id),
    )


def validate_event_brief(
    payload: dict[str, Any],
    selected_hook: dict[str, Any],
    *,
    place: dict[str, Any],
) -> dict[str, Any]:
    enriched = compress_event_capsule_to_limit(payload.get("enriched_hard_hook"))
    errors: list[str] = []
    try:
        confidence = int(payload.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0
    if confidence < 80:
        errors.append("confidence was below 80")
    missing_hook_requirements = daily_map_game.hard_hook_missing_requirements(enriched)
    if missing_hook_requirements:
        errors.append(
            "missing " + "; ".join(missing_hook_requirements)
        )
    if daily_map_game.hard_clue_reveals_target_token(enriched, place):
        errors.append("revealed a distinctive target-name word")
    if daily_map_game.MAP_HARD_GEO_SCOPE_RE.search(enriched):
        errors.append("borrowed geographic scope from medium or easy")
    if daily_map_game.MAP_HARD_NAMED_GEOGRAPHIC_FEATURE_RE.search(enriched):
        errors.append("named a geographic map feature that belongs in medium or easy")
    hard_geographic_names = daily_map_game.hard_nonparticipant_geographic_names(
        enriched,
        place,
    )
    if hard_geographic_names:
        errors.append(
            "named geographic scope that belongs in medium or easy "
            f"({', '.join(hard_geographic_names)})"
        )
    missing_target_identities = daily_map_game.hard_missing_target_identities(
        enriched,
        place,
    )
    if missing_target_identities:
        errors.append(
            "replaced answer-safe target identity with a generic site reference "
            f"(missing {', '.join(missing_target_identities)})"
        )
    if not daily_map_game.clue_preserves_required_hard_hook(
        enriched,
        str(selected_hook["verified_hard_hook"]),
    ):
        errors.append("did not preserve the selected recognition hook")
    used_urls = [
        str(url).strip()
        for url in payload.get("used_source_urls") or []
        if str(url).strip()
    ]
    if not used_urls:
        errors.append("returned no supporting source URL")
    if errors:
        raise ValueError(
            "Grounded recognition hook failed validation: "
            + "; ".join(errors)
            + f". Rejected capsule: {enriched}"
        )
    return {
        "enriched_hard_hook": enriched,
        "supporting_details": [
            str(detail).strip()
            for detail in payload.get("supporting_details") or []
            if str(detail).strip()
        ],
        "used_source_urls": used_urls,
        "confidence": confidence,
    }


def generate_round(
    conn: sqlite3.Connection,
    *,
    provider: rewriter.ConfiguredMapClueProvider,
    puzzle_date: str,
    shortlist_limit: int,
    max_clue_attempts: int,
    max_place_attempts: int = 4,
    eligible_names: set[str] | None = None,
    excluded_names: set[str] | None = None,
    required_place_type: str | None = None,
) -> dict[str, Any]:
    daily_map_game.initialize_database(conn)
    hooks = hard_hook_shortlist(
        conn,
        puzzle_date=puzzle_date,
        limit=shortlist_limit,
        eligible_names=eligible_names,
        excluded_names=excluded_names,
        required_place_type=required_place_type,
    )
    available = list(hooks)
    rejected_places: list[dict[str, Any]] = []
    while available and len(rejected_places) < max(1, max_place_attempts):
        selected_hook, selection_reason = choose_learned_hard_hook(available)
        place_id = int(selected_hook["place_id"])
        available = [
            hook for hook in available if int(hook["place_id"]) != place_id
        ]
        place = conn.execute(
            "SELECT * FROM map_place_pool WHERE id = ?",
            (place_id,),
        ).fetchone()
        if place is None:
            rejected_places.append(
                {
                    "place_id": place_id,
                    "place": str(selected_hook.get("place") or ""),
                    "stage": "selection",
                    "reason": "Place disappeared before generation.",
                }
            )
            continue

        place_payload = daily_map_game.public_place_payload(place)
        try:
            locality_name = reverse_geocoded_locality(place_payload)
        except Exception as error:
            rejection = {
                "place_id": place_id,
                "place": str(place["canonical_name"]),
                "stage": "locality_verification",
                "reason": str(error),
            }
            rejected_places.append(rejection)
            print(json.dumps({"stage": "place_rejected", **rejection}), flush=True)
            continue
        place_payload["locality_name"] = locality_name
        try:
            event_brief = research_event_brief(
                provider,
                selected_hook,
                place=place_payload,
            )
        except Exception as error:
            rejection = {
                "place_id": place_id,
                "place": str(place["canonical_name"]),
                "stage": "event_research",
                "reason": str(error),
            }
            rejected_places.append(rejection)
            print(json.dumps({"stage": "place_rejected", **rejection}), flush=True)
            continue
        try:
            event_verification = verify_event_place_connection(
                provider,
                selected_hook,
                event_brief,
                place=place_payload,
            )
        except Exception as error:
            rejection = {
                "place_id": place_id,
                "place": str(place["canonical_name"]),
                "stage": "event_verification",
                "reason": str(error),
            }
            rejected_places.append(rejection)
            print(json.dumps({"stage": "place_rejected", **rejection}), flush=True)
            continue

        enriched_hard_hook = str(event_brief["enriched_hard_hook"])
        print(
            json.dumps(
                {
                    "stage": "place_selected",
                    "place_attempt": len(rejected_places) + 1,
                    "place_id": place_id,
                    "place": str(place["canonical_name"]),
                    "verified_hard_hook": str(selected_hook["verified_hard_hook"]),
                    "enriched_hard_hook": enriched_hard_hook,
                    "selection_reason": selection_reason,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

        try:
            clue_result = daily_map_game.generate_reviewed_clue_ladder(
                conn,
                place_id=place_id,
                provider=provider,
                config=daily_map_game.MapClueConfig(
                    learning_profile_path=daily_map_game.DEFAULT_MAP_LEARNING_PROFILE_PATH,
                    clue_quality_model_path=daily_map_game.DEFAULT_MAP_CLUE_QUALITY_MODEL_PATH,
                    max_attempts_per_place=max(1, max_clue_attempts),
                    require_ai_critic=True,
                ),
                save=True,
                required_hard_hook=enriched_hard_hook,
                locality_name=locality_name,
            )
        except Exception as error:
            rejection = {
                "place_id": place_id,
                "place": str(place["canonical_name"]),
                "stage": "clue_generation",
                "reason": str(error),
            }
            rejected_places.append(rejection)
            print(json.dumps({"stage": "place_rejected", **rejection}), flush=True)
            continue

        if clue_result.get("status") != "accepted" or not clue_result.get("saved"):
            attempt_summary = []
            for attempt in clue_result.get("attempts") or []:
                critic = (
                    attempt.get("critic")
                    if isinstance(attempt.get("critic"), dict)
                    else {}
                )
                local_critic = (
                    attempt.get("local_critic")
                    if isinstance(attempt.get("local_critic"), dict)
                    else {}
                )
                attempt_summary.append(
                    {
                        "critic_source": attempt.get("critic_source"),
                        "failure_reasons": critic.get("failure_reasons") or [],
                        "local_failure_reasons": local_critic.get("failure_reasons")
                        or [],
                    }
                )
            rejection = {
                "place_id": place_id,
                "place": str(place["canonical_name"]),
                "stage": "clue_criticism",
                "reason": "No clue ladder passed both critics.",
                "attempts": attempt_summary,
            }
            rejected_places.append(rejection)
            print(
                json.dumps(
                    {
                        "stage": "place_rejected",
                        "place_id": place_id,
                        "place": str(place["canonical_name"]),
                        "reason": rejection["reason"],
                    }
                ),
                flush=True,
            )
            continue

        try:
            map_anchors = build_verified_map_search_anchors(
                place_payload,
                clue_result.get("clue_ladder") or {},
                locality_name=locality_name,
            )
            save_map_search_anchors(
                conn,
                place_id=place_id,
                anchors=map_anchors,
            )
        except Exception as error:
            rejection = {
                "place_id": place_id,
                "place": str(place["canonical_name"]),
                "stage": "map_anchor_validation",
                "reason": str(error),
            }
            rejected_places.append(rejection)
            print(json.dumps({"stage": "place_rejected", **rejection}), flush=True)
            continue

        publish_result = daily_map_game.generate_daily_map_game(
            conn,
            puzzle_date=puzzle_date,
            force=True,
            preferred_place_id=place_id,
            require_current_profile_for_qa=True,
        )
        if publish_result.get("status") != "published":
            raise RuntimeError(
                str(
                    publish_result.get("failureReason")
                    or "The AI-generated map round was not published."
                )
            )
        return {
            "created_at": utc_now(),
            "puzzle_date": puzzle_date,
            "place_id": place_id,
            "place": str(place["canonical_name"]),
            "place_type": str(place["place_type"]),
            "selection_reason": selection_reason,
            "verified_hard_hook": str(selected_hook["verified_hard_hook"]),
            "event_brief": event_brief,
            "event_verification": event_verification,
            "shortlist_count": len(hooks),
            "place_attempts": len(rejected_places) + 1,
            "rejected_places": rejected_places,
            "learning_profile_hash": daily_map_game.map_learning_profile_hash(),
            "critic_mode": clue_result.get("critic_mode"),
            "clue_ladder": clue_result.get("clue_ladder"),
            "generation_attempts": len(clue_result.get("attempts") or []),
            "publish_result": publish_result,
        }

    raise RuntimeError(
        "No shortlisted place produced a critic-approved clue ladder: "
        + json.dumps(rejected_places, ensure_ascii=False)
    )


def discover_uncurated_candidates(
    *,
    db_path: Path,
    provider: rewriter.ConfiguredMapClueProvider,
    puzzle_date: str,
    count: int,
    max_attempts: int,
    excluded_names: set[str] | None = None,
    required_place_type: str | None = None,
) -> dict[str, Any]:
    from tools import generate_map_place_candidates_with_ai as candidate_generator

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        daily_map_game.initialize_database(conn)
        recent_names = [
            str(item.get("canonical_name") or "").strip()
            for item in daily_map_game.recent_map_places(
                conn,
                exclude_puzzle_date=puzzle_date,
            )
            if str(item.get("canonical_name") or "").strip()
        ]
    finally:
        conn.close()
    excluded = {
        str(name).strip()
        for name in (excluded_names or set())
        if str(name).strip()
    }
    blocked_examples = [*recent_names, *sorted(excluded)]
    blocked_names: set[str] = set()
    for name in blocked_examples:
        blocked_names.update(candidate_generator.normalized_name_variants(name))

    required_type = str(required_place_type or "").strip().casefold()
    focus = (
        f"Discover the strongest recognition hooks for the {puzzle_date} map round. "
        "Choose the hook first, then return its real, unambiguous, pinnable place."
    )
    if required_type:
        focus += (
            f" This launch round requires place_type '{required_type}'. Return only "
            f"{required_type} places, but do not lower any interest, evidence, or map-playability gate."
        )
    discovery = candidate_generator.generate_review_batch(
        db_path=db_path,
        provider=provider,
        limit=max(1, count),
        batch_size=max(4, count),
        max_attempts=max(1, max_attempts),
        retry_after_minutes=0,
        focus=focus,
        feedback_dir=DEFAULT_REPORT_DIR,
        allow_known_retries=True,
        blocked_names=blocked_names,
        blocked_name_examples=blocked_examples,
    )
    generated_accepted = discovery.get("accepted") or []
    accepted = [
        row
        for row in generated_accepted
        if not required_type
        or str(row.get("place_type") or "").strip().casefold() == required_type
    ]
    if not accepted:
        type_context = f" for required place_type '{required_type}'" if required_type else ""
        raise RuntimeError(
            "Grounded discovery produced no candidates"
            f"{type_context} that passed the objective and learned gates."
        )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        daily_map_game.initialize_database(conn)
        inserted = candidate_generator.insert_draft_rows(conn, accepted)
        conn.commit()
    finally:
        conn.close()
    names = {
        str(row.get("canonical_name") or "").strip().casefold()
        for row in accepted
        if str(row.get("canonical_name") or "").strip()
    }
    return {
        "accepted_count": len(accepted),
        "inserted_count": inserted,
        "candidate_names": sorted(names),
        "attempts": discovery.get("attempts") or [],
        "rejected_count": len(discovery.get("rejected") or []),
        "wrong_type_count": len(generated_accepted) - len(accepted),
        "required_place_type": required_type,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Use the learned selector and AI clue loop to publish one daily map round.",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--date", default=datetime.now().date().isoformat())
    parser.add_argument("--shortlist-limit", type=int, default=24)
    parser.add_argument("--max-clue-attempts", type=int, default=5)
    parser.add_argument(
        "--max-place-attempts",
        type=int,
        default=4,
        help="Try this many learned-ranked places before failing the round.",
    )
    parser.add_argument(
        "--discover-count",
        type=int,
        default=8,
        help="Generate this many grounded, learned-ranked candidates before selecting the round. Use 0 only for offline QA.",
    )
    parser.add_argument("--discovery-attempts", type=int, default=4)
    parser.add_argument("--env-file", type=Path, default=rewriter.DEFAULT_ENV_FILE)
    parser.add_argument("--generator-model", default="")
    parser.add_argument("--critic-model", default="")
    parser.add_argument(
        "--exclude-place",
        action="append",
        default=[],
        help="Exclude an exact canonical place name from this QA run; repeat as needed.",
    )
    parser.add_argument(
        "--place-type",
        default="",
        help="Require one exact place type, such as stadium, without relaxing quality gates.",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--timeout-sec", type=int, default=None)
    parser.add_argument("--request-delay-sec", type=float, default=None)
    parser.add_argument("--transient-retries", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"Database not found: {args.db}")
    rewriter.load_env_file(args.env_file)
    rewriter.apply_runtime_env_overrides(args)
    provider = rewriter.ConfiguredMapClueProvider.from_env(
        generator_model=args.generator_model,
        critic_model=args.critic_model,
    )
    discovery: dict[str, Any] | None = None
    eligible_names: set[str] | None = None
    excluded_names = {
        str(name).strip().casefold()
        for name in args.exclude_place
        if str(name).strip()
    }
    if args.discover_count > 0:
        discovery = discover_uncurated_candidates(
            db_path=args.db,
            provider=provider,
            puzzle_date=args.date,
            count=max(1, args.discover_count),
            max_attempts=max(1, args.discovery_attempts),
            excluded_names=excluded_names,
            required_place_type=args.place_type,
        )
        eligible_names = set(discovery["candidate_names"])
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        result = generate_round(
            conn,
            provider=provider,
            puzzle_date=args.date,
            shortlist_limit=max(4, args.shortlist_limit),
            max_clue_attempts=max(1, args.max_clue_attempts),
            max_place_attempts=max(1, args.max_place_attempts),
            eligible_names=eligible_names,
            excluded_names=excluded_names,
            required_place_type=args.place_type,
        )
        result["discovery"] = discovery
        result["excluded_places"] = sorted(excluded_names)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = args.out_dir / f"map_ai_daily_round_{stamp}.json"
    report_path.write_text(json.dumps(result, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({**result, "report_path": str(report_path)}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
