from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import daily_map_game

DEFAULT_DB_PATH = PROJECT_DIR / "data" / "fultons.db"

REQUIRED_COLUMNS = {
    "canonical_name",
    "place_type",
    "country_code",
    "country_name",
    "admin1",
    "lat",
    "lng",
    "difficulty",
    "verified_fact_1",
    "landmark_or_visual_hook",
    "source_1_name",
    "source_1_url",
    "reveal_text",
    "review_status",
}

ALLOWED_REVIEW_STATUS = {"approved", "draft", "rejected"}
READY_MIN_VALIDATION_GRADE = 7.0
CLUE_FIELDS = ("example_hard_clue", "example_medium_clue", "example_easy_clue")


def slugify(value: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in value.lower()).strip("-")


def split_semicolon(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(";") if part.strip()]


def normalized_text(value: object) -> str:
    return "".join(character for character in str(value or "").lower() if character.isalnum())


def has_answer_leak(row: dict[str, str], field: str) -> bool:
    text = normalized_text(row.get(field, ""))
    if not text:
        return False
    candidates = [row.get("canonical_name", "")]
    candidates.extend(split_semicolon(row.get("acceptable_aliases", "")))
    return any(
        len(normalized_text(candidate)) >= 5 and normalized_text(candidate) in text
        for candidate in candidates
        if str(candidate).strip()
    )


def clue_uses_poor_targeting(text: str) -> bool:
    normalized = str(text or "").casefold()
    return any(
        token in normalized
        for token in (
            "iso country code",
            "degrees north",
            "degrees south",
            "degrees east",
            "degrees west",
            "latitude",
            "longitude",
        )
    )


def parse_float(value: object, *, field: str, name: str) -> float:
    try:
        return float(str(value or "").strip())
    except ValueError as error:
        raise ValueError(f"{name}: {field} must be numeric.") from error


def parse_optional_float(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    return float(text)


def parse_optional_int(value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    return int(float(text))


def valid_url(value: str) -> bool:
    return not value or bool(re.match(r"https?://", value.strip()))


def require_columns(fieldnames: list[str] | None) -> None:
    available = set(fieldnames or [])
    missing = sorted(REQUIRED_COLUMNS - available)
    if missing:
        raise ValueError(f"Missing required map place-bank columns: {', '.join(missing)}")


def normalized_row(row: dict[str, str]) -> dict[str, Any]:
    name = row["canonical_name"].strip()
    difficulty = row["difficulty"].strip().lower()
    if difficulty not in daily_map_game.DIFFICULTIES:
        raise ValueError(f"{name}: difficulty must be easy, medium, or hard.")
    lat = parse_float(row["lat"], field="lat", name=name)
    lng = parse_float(row["lng"], field="lng", name=name)
    daily_map_game.valid_coordinate(lat, lng)

    facts = [
        row.get("verified_fact_1", ""),
        row.get("verified_fact_2", ""),
        row.get("verified_fact_3", ""),
        row.get("landmark_or_visual_hook", ""),
    ]
    facts = [fact.strip() for fact in facts if fact.strip()]
    sources = []
    for index in (1, 2):
        source_name = row.get(f"source_{index}_name", "").strip()
        source_url = row.get(f"source_{index}_url", "").strip()
        if source_name or source_url:
            sources.append({"name": source_name, "url": source_url})
    if not facts:
        raise ValueError(f"{name}: at least one verified fact is required.")
    if not sources:
        raise ValueError(f"{name}: at least one source is required.")
    if not valid_url(row.get("source_1_url", "")):
        raise ValueError(f"{name}: source_1_url must start with http:// or https://.")
    if not valid_url(row.get("source_2_url", "")):
        raise ValueError(f"{name}: source_2_url must start with http:// or https://.")
    if not valid_url(row.get("coordinate_source_url", "")):
        raise ValueError(f"{name}: coordinate_source_url must start with http:// or https://.")

    row_id = row.get("row_id", "").strip()
    slug = row.get("slug", "").strip() or f"{difficulty}-{slugify(row_id + '-' if row_id else '')}{slugify(name)}"
    radius_km = parse_optional_float(row.get("answer_radius_km"))
    scoring_radius_m = (
        int(round(radius_km * 1000))
        if radius_km is not None and radius_km > 0
        else daily_map_game.normalized_scoring_radius_m(difficulty)
    )
    validation_grade = parse_optional_float(row.get("validation_grade"))
    return {
        "slug": slug,
        "canonical_name": name,
        "country_code": row["country_code"].strip().upper(),
        "country_name": row.get("country_name", "").strip(),
        "continent": row.get("continent", "").strip(),
        "admin1": row["admin1"].strip(),
        "place_type": row["place_type"].strip() or "place",
        "difficulty": difficulty,
        "lat": lat,
        "lng": lng,
        "coordinate_precision": row.get("coordinate_precision", "").strip(),
        "suggested_map_zoom": parse_optional_int(row.get("suggested_map_zoom")),
        "clue_text": row.get("example_hard_clue", "").strip() or facts[0],
        "medium_clue_text": row.get("example_medium_clue", "").strip(),
        "easy_clue_text": row.get("example_easy_clue", "").strip(),
        "reveal_text": row["reveal_text"].strip(),
        "acceptable_aliases": "; ".join(split_semicolon(row.get("acceptable_aliases", ""))),
        "nearby_context": row.get("nearby_context", "").strip(),
        "verified_facts_json": json.dumps(facts, ensure_ascii=True),
        "sources_json": json.dumps(sources, ensure_ascii=True),
        "coordinate_source_name": row.get("coordinate_source_name", "").strip(),
        "coordinate_source_url": row.get("coordinate_source_url", "").strip(),
        "avoid_in_clues": row.get("avoid_in_clues", "").strip(),
        "deconflict_group": row.get("deconflict_group", "").strip(),
        "fact_stability": row.get("fact_stability", "").strip(),
        "review_status": row.get("review_status", "draft").strip().lower() or "draft",
        "review_notes": row.get("review_notes", "").strip(),
        "reviewed_on": row.get("reviewed_on", "").strip(),
        "validation_grade": validation_grade,
        "validation_reasoning": row.get("validation_reasoning", "").strip(),
        "scoring_radius_m": scoring_radius_m,
    }


def classify_raw_row(
    row: dict[str, str],
    *,
    min_validation_grade: float = READY_MIN_VALIDATION_GRADE,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    name = row.get("canonical_name", "").strip() or "unknown"
    status = row.get("review_status", "").strip().lower()
    if status not in ALLOWED_REVIEW_STATUS:
        reasons.append("invalid review_status")
        return "hold", reasons
    if status != "approved":
        reasons.append(f"review_status is {status}")
        return "review", reasons
    grade_text = str(row.get("validation_grade", "")).strip()
    if grade_text:
        try:
            grade = float(grade_text)
        except ValueError:
            reasons.append("validation_grade is not numeric")
            return "hold", reasons
        if grade < min_validation_grade:
            reasons.append(f"validation_grade {grade:g} is below {min_validation_grade:g}")
            return "review", reasons
    for field in CLUE_FIELDS:
        if has_answer_leak(row, field):
            reasons.append(f"{field} appears to reveal {name}")
            return "hold", reasons
        if clue_uses_poor_targeting(row.get(field, "")):
            reasons.append(f"{field} uses coordinate/ISO-code targeting")
    if reasons:
        return "review", reasons
    return "ready", reasons


def insert_place(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
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
            review_status = excluded.review_status,
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
            row["review_status"],
            row["review_notes"],
            row["reviewed_on"],
            row["validation_grade"],
            row["validation_reasoning"],
            row["scoring_radius_m"],
            daily_map_game.utc_now(),
        ),
    )


def import_place_bank(
    csv_path: Path,
    db_path: Path = DEFAULT_DB_PATH,
    *,
    min_validation_grade: float = READY_MIN_VALIDATION_GRADE,
    include_review_rows: bool = False,
) -> dict[str, Any]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        require_columns(reader.fieldnames)
        raw_rows = list(reader)

    report: dict[str, Any] = {
        "total": len(raw_rows),
        "imported": 0,
        "ready": 0,
        "review": 0,
        "hold": 0,
        "skipped": 0,
        "warnings": [],
        "errors": [],
        "duplicates": [],
    }
    seen_names: dict[str, list[str]] = {}
    for row in raw_rows:
        name_key = normalized_text(row.get("canonical_name", ""))
        if name_key:
            seen_names.setdefault(name_key, []).append(row.get("row_id") or row.get("canonical_name", ""))
    report["duplicates"] = [
        {"canonical_name": key, "rows": values}
        for key, values in seen_names.items()
        if len(values) > 1
    ][:25]

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        daily_map_game.initialize_database(conn)
        for line_number, raw_row in enumerate(raw_rows, start=2):
            tier, reasons = classify_raw_row(
                raw_row,
                min_validation_grade=min_validation_grade,
            )
            alias_text = str(raw_row.get("acceptable_aliases", "")).strip()
            name_prefix = f"{str(raw_row.get('canonical_name', '')).strip()},"
            alias_warning = (
                "," in alias_text
                and ";" not in alias_text
                and not alias_text.casefold().startswith(name_prefix.casefold())
            )
            report[tier] += 1
            row_label = raw_row.get("row_id") or raw_row.get("canonical_name") or f"line {line_number}"
            if alias_warning and len(report["warnings"]) < 50:
                report["warnings"].append(
                    {
                        "row": row_label,
                        "tier": tier,
                        "reasons": ["acceptable_aliases should use semicolons"],
                    }
                )
            if reasons:
                target = "errors" if tier == "hold" else "warnings"
                if len(report[target]) < 50:
                    report[target].append(
                        {"row": row_label, "tier": tier, "reasons": reasons}
                    )
            if tier == "hold" or (tier == "review" and not include_review_rows):
                report["skipped"] += 1
                continue
            try:
                row = normalized_row(raw_row)
            except ValueError as error:
                report["hold"] += 1
                report["skipped"] += 1
                if len(report["errors"]) < 50:
                    report["errors"].append({"row": row_label, "tier": "hold", "reasons": [str(error)]})
                continue
            insert_place(conn, row)
            report["imported"] += 1
        conn.commit()
        return report
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import a curated daily-map place bank CSV.")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--min-validation-grade",
        type=float,
        default=READY_MIN_VALIDATION_GRADE,
        help="Rows below this grade are held for review by default.",
    )
    parser.add_argument(
        "--include-review-rows",
        action="store_true",
        help="Import review-tier rows as active rows instead of skipping them.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(
        json.dumps(
            import_place_bank(
                args.csv_path,
                args.db,
                min_validation_grade=args.min_validation_grade,
                include_review_rows=args.include_review_rows,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
