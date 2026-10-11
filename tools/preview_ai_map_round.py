"""Generate a reviewable Map round with isolated Gemini quota and SQLite state."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Any
from urllib.error import HTTPError
from uuid import uuid4

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import daily_map_game
import daily_quiz
from safe_http import ResponseTooLarge, read_bounded_response
from tools import generate_ai_daily_map_round as generator
from tools import rewrite_map_clues_with_ai as rewriter


class MapGeminiProvider(daily_quiz.GeminiProvider):
    """Preserve the provider's retry hint for the automatic Map scheduler."""

    last_retry_after_seconds: float | None = None

    def _http_error_detail(self, error: HTTPError) -> str:
        retry_header = (error.headers or {}).get('Retry-After', '')
        try:
            retry_seconds = float(retry_header)
        except (TypeError, ValueError):
            try:
                retry_seconds = (parsedate_to_datetime(retry_header) - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                retry_seconds = 0.0
        try:
            body, charset = read_bounded_response(error, max_bytes=64_000, label='Gemini error')
            payload = json.loads(body.decode(charset, errors='replace'))
        except (OSError, ValueError, ResponseTooLarge, UnicodeDecodeError):
            payload = {}
        error_payload = payload.get('error', {}) if isinstance(payload, dict) else {}
        if not isinstance(error_payload, dict):
            error_payload = {}
        for item in error_payload.get('details', []):
            if not isinstance(item, dict) or not str(item.get('@type', '')).endswith('RetryInfo'):
                continue
            delay = str(item.get('retryDelay', ''))
            try:
                retry_seconds = max(retry_seconds, float(delay[:-1]) if delay.endswith('s') else 0)
            except ValueError:
                pass
        self.last_retry_after_seconds = retry_seconds if 0 < retry_seconds <= 172800 else None
        detail = ' '.join(str(error_payload.get(key) or '').strip() for key in ('status', 'code', 'message')).strip()
        if daily_quiz.is_daily_quota_failure(json.dumps(error_payload)) and not daily_quiz.is_daily_quota_failure(detail):
            detail = f'{detail} daily quota exceeded'.strip()
        return detail[:700]


class PreviewGeminiProvider(rewriter.ConfiguredMapClueProvider):
    """One explicit Gemini credential; count every attempt, including failures."""

    def __init__(self, config: daily_quiz.QuizConfig, *, max_requests: int = 30):
        if not 1 <= max_requests <= 30:
            raise ValueError("Preview request budget must be between 1 and 30.")
        super().__init__([rewriter.ProviderClient(MapGeminiProvider(config), config)])
        self.max_requests = max_requests
        self.requests: list[dict[str, Any]] = []
        self.stop_reason = ""
        self.retry_after_seconds: float | None = None
        self.provider_error_detail = ""

    @classmethod
    def from_preview_env(cls, *, max_requests: int = 30, generator_model: str = "") -> "PreviewGeminiProvider":
        key = os.environ.get("GEMINI_API_KEY_DEV", "").strip()
        if not key:
            raise ValueError(
                "GEMINI_API_KEY_DEV is required. Use a separate Google AI "
                "project with independent quota; production credentials are never used."
            )
        if any(
            value.strip() == key
            for name, value in os.environ.items()
            if name.endswith("API_KEY") and name != "GEMINI_API_KEY_DEV"
        ):
            raise ValueError("Preview key matches another configured API key; independent quota is required.")
        return cls.from_explicit_key(key, generator_model=generator_model, max_requests=max_requests)

    @classmethod
    def from_explicit_key(cls, key: str, *, generator_model: str = "", max_requests: int = 30):
        # Construct explicitly: no provider fallback or hidden retries.
        config = daily_quiz.QuizConfig(
            provider="gemini",
            generator_model=generator_model.strip() or os.environ.get("MAP_PREVIEW_GENERATOR_MODEL", "").strip()
            or rewriter.DEFAULT_MAP_GEMINI_GENERATOR_MODEL,
            critic_model=os.environ.get("MAP_PREVIEW_CRITIC_MODEL", "").strip()
            or rewriter.DEFAULT_MAP_GEMINI_CRITIC_MODEL,
            gemini_api_key=key,
            compatible_api_key="",
            compatible_base_url="",
            fallback_provider="", fallback_generator_model="", fallback_critic_model="",
            fallback_gemini_api_key="", fallback_compatible_api_key="", fallback_compatible_base_url="",
            fallback2_provider="", fallback2_generator_model="", fallback2_critic_model="",
            fallback2_gemini_api_key="", fallback2_compatible_api_key="", fallback2_compatible_base_url="",
            timeout_sec=60, request_delay_sec=12.0, transient_retries=0,
            max_attempts_per_slot=1, question_history_days=90,
            learning_profile_path="", internal_token="",
        )
        return cls(config, max_requests=max_requests)

    def call_with_fallback(self, **kwargs: Any) -> dict[str, Any]:
        if self.stop_reason:
            raise RuntimeError(self.stop_reason)
        if len(self.requests) >= self.max_requests:
            self.stop_reason = "Map preview request budget exhausted."
            raise RuntimeError(self.stop_reason)
        client = self.clients[0]
        model = getattr(client.config, kwargs["model_attr"])
        record = {"number": len(self.requests) + 1, "model": model,
                  "stage": kwargs["model_attr"], "grounded": bool(kwargs.get("tools"))}
        self.requests.append(record)
        try:
            result = self.request_json(
                client, model=model, prompt=kwargs["prompt"], schema=kwargs["schema"],
                tools=kwargs.get("tools"),
            )
        except Exception as error:
            # Preserve enough detail to diagnose access/model errors, without the key.
            record["status"] = "failed"
            record["error_type"] = type(error).__name__
            record["error_detail"] = str(error).replace(client.config.gemini_api_key, "[REDACTED]")[:500]
            self.provider_error_detail = record["error_detail"]
            self.retry_after_seconds = getattr(client.provider, "last_retry_after_seconds", None)
            self.stop_reason = "Map preview provider failed; stopped to preserve quota."
            raise RuntimeError(self.stop_reason) from None
        record["status"] = "completed"
        return result


def snapshot_database(source: Path, destination: Path) -> None:
    source = source.resolve(strict=True)
    if source == destination.resolve():
        raise ValueError("Preview database must differ from its source.")
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
        with closing(sqlite3.connect(destination)) as snapshot:
            original.backup(snapshot)
            if snapshot.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Source database snapshot failed integrity validation.")


def preview_round(
    *, source_db: Path, output_dir: Path, puzzle_date: str,
    provider: PreviewGeminiProvider, discover_count: int = 8,
) -> dict[str, Any]:
    puzzle_date = daily_map_game.valid_game_date(puzzle_date)
    if not 1 <= discover_count <= 12:
        raise ValueError("Discover count must be between 1 and 12.")
    source_db = source_db.resolve(strict=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "puzzle_date": puzzle_date, "mode": "preview", "production_modified": False,
        "status": "failed", "human_review": "pending",
        "models": provider.model_summary(), "max_requests": provider.max_requests,
    }
    # The snapshot may contain private game history; it is temporary, never exported.
    with tempfile.TemporaryDirectory(prefix="map-preview-", dir=output_dir) as workspace:
        snapshot = Path(workspace) / "preview.db"
        try:
            snapshot_database(source_db, snapshot)
            with closing(sqlite3.connect(snapshot)) as conn:
                conn.row_factory = sqlite3.Row
                daily_map_game.initialize_database(conn)
                if daily_map_game.puzzle_status(conn, puzzle_date)["status"] == "published":
                    raise ValueError("Choose an unpublished date; an existing round cannot count as a new preview.")
                conn.commit()
            discovery = generator.discover_uncurated_candidates(
                db_path=snapshot, provider=provider, puzzle_date=puzzle_date,
                count=discover_count, max_attempts=2,
            )
            report["discovery"] = discovery
            ids = set(discovery.get("candidate_place_ids") or [])
            if not ids:
                raise ValueError("Discovery resolved no places; refusing to substitute stored fallback content.")
            with closing(sqlite3.connect(snapshot)) as conn:
                conn.row_factory = sqlite3.Row
                result = generator.generate_round(
                    conn, provider=provider, puzzle_date=puzzle_date,
                    shortlist_limit=24, max_clue_attempts=5, max_place_attempts=4,
                    eligible_place_ids=ids,
                    event_brief_cache_path=Path(workspace) / "event-briefs.json",
                )
                conn.commit()
            report.update(status="ready_for_review", result=result)
        except Exception as error:
            report["error"] = str(error)
    report["requests"] = provider.requests
    report["request_count"] = len(provider.requests)
    report["stop_reason"] = provider.stop_reason
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = output_dir / f"map-preview-{stamp}-{uuid4().hex[:8]}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    review_path = report_path.with_suffix(".md")
    review_path.write_text(review_markdown(report), encoding="utf-8")
    return {**report, "report_path": str(report_path), "review_path": str(review_path)}


def review_markdown(report: dict[str, Any]) -> str:
    lines = ["# Map AI preview", "", f"Status: {report['status']}",
             f"Date: {report['puzzle_date']}", "", "Production was not modified.", ""]
    result = report.get("result") or {}
    if result:
        # Indented text keeps model-generated content inert in the review document.
        for label, value in [("Selected place", result["place"]),
                             ("Selection reason", result["selection_reason"]),
                             *[(level.title() + " clue", result["clue_ladder"][level])
                               for level in ("hard", "medium", "easy")]]:
            lines.extend([f"## {label}", "", *["    " + line for line in str(value).splitlines()], ""])
        lines.extend(["## Human review", "",
                      "- [ ] Hard clue has an interesting, accurate story owned by this place.",
                      "- [ ] Medium narrows the search area without revealing the answer.",
                      "- [ ] Easy makes the target findable on a phone map.",
                      "- [ ] Three distinct clues; no answer or alias leaks.",
                      "- [ ] Evidence and staged map boundaries match the claims and target.",
                      "", "Evidence, map geometry and request accounting are in the adjacent JSON report."])
    else:
        lines.extend(["    " + line for line in str(report.get("error") or "No accepted round.").splitlines()])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, default=generator.DEFAULT_DB_PATH)
    parser.add_argument("--date", required=True)
    parser.add_argument("--env-file", type=Path, default=rewriter.DEFAULT_ENV_FILE)
    parser.add_argument("--out-dir", type=Path, default=PROJECT_DIR / "data" / "qa" / "map-previews")
    parser.add_argument("--max-requests", type=int, default=30)
    args = parser.parse_args()
    rewriter.load_env_file(args.env_file)
    try:
        provider = PreviewGeminiProvider.from_preview_env(max_requests=args.max_requests)
        result = preview_round(source_db=args.source_db, output_dir=args.out_dir,
                               puzzle_date=args.date, provider=provider)
    except (ValueError, OSError) as error:
        parser.exit(2, f"{error}\n")
    print(json.dumps({key: result[key] for key in ("status", "request_count", "report_path", "review_path")}))
    return 0 if result["status"] == "ready_for_review" else 1


if __name__ == "__main__":
    raise SystemExit(main())
