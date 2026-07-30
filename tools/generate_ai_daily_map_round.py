from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def event_brief_cache_key(selected_hook: dict[str, Any], place: dict[str, Any]) -> str:
    identity = (
        f"{selected_hook.get('place_id') or place.get('canonical_name')}:"
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
              AND daily_map_puzzles.puzzle_date < ?
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
) -> list[dict[str, Any]]:
    excluded = recent_place_ids(conn, puzzle_date)
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
    for row in rows:
        if (
            eligible_names is not None
            and str(row["canonical_name"]).strip().casefold() not in eligible_names
        ):
            continue
        if int(row["id"]) in excluded or daily_map_game.place_is_explicitly_excluded(row):
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
) -> list[dict[str, Any]]:
    places = candidate_shortlist(
        conn,
        puzzle_date=puzzle_date,
        limit=max(limit * 2, 80),
        eligible_names=eligible_names,
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
    selected = hooks[0]
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

Use URL Context on the preferred source URLs to verify the event before writing.
If no preferred source URL is supplied, use Google Search instead.

Return one answer-safe enriched hook:
- Prefer one clear sentence, but preserve the information needed to make the hook recognisable.
- Preserve the selected incident, story, record, achievement, discovery, person-linked episode, tradition, natural occurrence, or cultural moment.
- Add concrete narrative information, not adjectives or padding.
- For an event, name useful actors or sides, say what happened, and add at least one of: trigger, defining method, consequence, score, record, or why it mattered.
- For a non-event hook, state the specific record, achievement, association, tradition, or phenomenon and why it is distinctive.
- Name useful people, teams, organisations, forces, works, or records when answer-safe.
- For a team match or final, name both teams and the result; do not replace the competing sides with a scorer or attendance figure.
- Country names are allowed when they are the proper names of national teams or other essential event participants. Never replace one with "the host nation", "the visitors", or a similar generic label.
- Tie the hook to the target with "here", "on this pitch", "inside this building", "at this site", or another answer-safe equivalent.
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

    grounding_tools = (
        [{"urlContext": {}}]
        if selected_hook.get("source_urls")
        else [{"googleSearch": {}}]
    )
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
) -> dict[str, Any]:
    daily_map_game.initialize_database(conn)
    hooks = hard_hook_shortlist(
        conn,
        puzzle_date=puzzle_date,
        limit=shortlist_limit,
        eligible_names=eligible_names,
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
    blocked_names: set[str] = set()
    for name in recent_names:
        blocked_names.update(candidate_generator.normalized_name_variants(name))

    discovery = candidate_generator.generate_review_batch(
        db_path=db_path,
        provider=provider,
        limit=max(1, count),
        batch_size=max(4, count),
        max_attempts=max(1, max_attempts),
        retry_after_minutes=0,
        focus=(
            f"Discover the strongest recognition hooks for the {puzzle_date} map round. "
            "Choose the hook first, then return its real, unambiguous, pinnable place."
        ),
        feedback_dir=DEFAULT_REPORT_DIR,
        allow_known_retries=True,
        blocked_names=blocked_names,
        blocked_name_examples=recent_names,
    )
    accepted = discovery.get("accepted") or []
    if not accepted:
        raise RuntimeError(
            "Grounded discovery produced no candidates that passed the objective and learned gates."
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
    if args.discover_count > 0:
        discovery = discover_uncurated_candidates(
            db_path=args.db,
            provider=provider,
            puzzle_date=args.date,
            count=max(1, args.discover_count),
            max_attempts=max(1, args.discovery_attempts),
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
        )
        result["discovery"] = discovery
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
