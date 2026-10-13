from __future__ import annotations

import base64
from collections import deque
import hashlib
import html
import hmac
import ipaddress
import json
import os
import queue
import re
import secrets
import socket
import sqlite3
import sys
import threading
import time
from contextlib import closing, contextmanager
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from http import HTTPStatus
from http.client import HTTPSConnection
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, quote_plus, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree

import daily_map_game, map_clue_editor
import daily_quiz
import quiz_board
from env_config import env_bool, env_int, env_ip_networks
from safe_http import read_bounded_response
from tools import generate_ai_daily_map_round
from tools import controlled_map_round
from tools import automatic_map_pool
from tools import build_map_selector_profile
from tools import install_map_training_seed
from tools import install_map_reviewed_fallbacks
from tools import map_clue_quality_model
from tools import map_selector_model
from tools import refresh_map_learning_profile
from tools import refresh_quiz_learning_profile
from tools import rewrite_map_clues_with_ai as map_clue_rewriter
from tools import training_data_store

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 fallback
    ZoneInfo = None  # type: ignore[assignment]


APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "fultons.db"
DIST_DIR = APP_DIR / "dist"
SESSION_COOKIE = "fultons_session"
CACHE_VERSION_COOKIE = "fultons_cache_version"
MAP_PROMO_CAMPAIGN_ID = os.environ.get(
    "FULTONS_MAP_PROMO_CAMPAIGN_ID",
    "daily-map-launch-2026-08-04",
).strip()
MAP_PROMO_AVAILABLE_DATE = os.environ.get(
    "FULTONS_MAP_PROMO_AVAILABLE_DATE",
    "2026-08-04",
).strip()
CACHE_VERSION = (
    re.sub(r"[^A-Za-z0-9_.-]", "-", os.environ.get("FULTONS_BUILD_COMMIT", "local"))[:64]
    or "local"
)
SESSION_DAYS = env_int("FULTONS_SESSION_DAYS", 14, minimum=1, maximum=90)
SESSION_MAX_PER_USER = env_int(
    "FULTONS_SESSION_MAX_PER_USER", 10, minimum=1, maximum=100
)
SESSION_ROW_LIMIT = env_int(
    "FULTONS_SESSION_ROW_LIMIT", 50_000, minimum=100, maximum=1_000_000
)
PASSWORD_ITERATIONS = env_int(
    "FULTONS_PASSWORD_ITERATIONS", 260_000, minimum=100_000, maximum=2_000_000
)
USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
SERVER_TZ_NAME = os.environ.get("FULTONS_TIMEZONE", "Europe/London")
NEWS_MONITOR_KEY = os.environ.get("FULTONS_NEWS_MONITOR_KEY", "")
NEWS_LIMIT_DEFAULT = 50
NEWS_LIMIT_MAX = 100
NEWS_RETENTION_DAYS = env_int(
    "FULTONS_NEWS_RETENTION_DAYS", 90, minimum=7, maximum=3650
)
NEWS_ROW_LIMIT = env_int(
    "FULTONS_NEWS_ROW_LIMIT", 5000, minimum=NEWS_LIMIT_MAX, maximum=1_000_000
)
NEWS_MONITOR_ENABLED = env_bool("FULTONS_NEWS_MONITOR_ENABLED", True)
NEWS_MONITOR_INTERVAL_SEC = env_int(
    "FULTONS_NEWS_MONITOR_INTERVAL_SEC", 600, minimum=300, maximum=86_400
)
DAILY_QUIZ_SCHEDULER_ENABLED = env_bool("FULTONS_DAILY_QUIZ_SCHEDULER_ENABLED", True)
DAILY_QUIZ_SCHEDULER_HOUR = env_int(
    "FULTONS_DAILY_QUIZ_SCHEDULER_HOUR", 0, minimum=0, maximum=23
)
DAILY_QUIZ_SCHEDULER_MINUTE = env_int(
    "FULTONS_DAILY_QUIZ_SCHEDULER_MINUTE", 5, minimum=0, maximum=59
)
DAILY_QUIZ_RETRY_INTERVAL_SEC = env_int(
    "FULTONS_DAILY_QUIZ_RETRY_INTERVAL_SEC", 900, minimum=60, maximum=604_800
)
DAILY_QUIZ_RESERVE_DAYS = env_int(
    "FULTONS_DAILY_QUIZ_RESERVE_DAYS", 5, minimum=1, maximum=7
)
DAILY_QUIZ_POOL_ENABLED = env_bool("FULTONS_DAILY_QUIZ_POOL_ENABLED", True)
DAILY_QUIZ_POOL_TARGET_BATCHES = env_int(
    "FULTONS_DAILY_QUIZ_POOL_TARGET_BATCHES", 7, minimum=1, maximum=30
)
DAILY_QUIZ_POOL_MAX_BATCH_ATTEMPTS = env_int(
    "FULTONS_DAILY_QUIZ_POOL_MAX_BATCH_ATTEMPTS", 7, minimum=1, maximum=30
)
DAILY_QUIZ_POOL_RETRY_INTERVAL_SEC = env_int(
    "FULTONS_DAILY_QUIZ_POOL_RETRY_INTERVAL_SEC", 900, minimum=60, maximum=86_400
)
WEEKLY_SUMMARY_NTFY_URL = os.environ.get("FULTONS_WEEKLY_SUMMARY_NTFY_URL", "").strip()
DAILY_QUIZ_TRANSIENT_RETRY_INTERVAL_SEC = max(
    DAILY_QUIZ_RETRY_INTERVAL_SEC,
    env_int(
        "FULTONS_DAILY_QUIZ_TRANSIENT_RETRY_INTERVAL_SEC",
        3600,
        minimum=60,
        maximum=604_800,
    ),
)
DAILY_MAP_GAME_SCHEDULER_ENABLED = env_bool(
    "FULTONS_DAILY_MAP_GAME_SCHEDULER_ENABLED", True
)
DAILY_MAP_FUTURE_REVIEW_ENABLED = env_bool(
    "FULTONS_DAILY_MAP_FUTURE_REVIEW_ENABLED", False
)
DAILY_MAP_GAME_SCHEDULER_HOUR = env_int(
    "FULTONS_DAILY_MAP_GAME_SCHEDULER_HOUR", 0, minimum=0, maximum=23
)
DAILY_MAP_GAME_SCHEDULER_MINUTE = env_int(
    "FULTONS_DAILY_MAP_GAME_SCHEDULER_MINUTE", 2, minimum=0, maximum=59
)
DAILY_QUIZ_RECOVERY_HOUR = env_int(
    "FULTONS_DAILY_QUIZ_RECOVERY_HOUR", 20, minimum=0, maximum=23
)
DAILY_MAP_PREPARE_DAYS_AHEAD = env_int(
    "FULTONS_DAILY_MAP_PREPARE_DAYS_AHEAD", 2, minimum=1, maximum=7
)
DAILY_MAP_GAME_RETRY_INTERVAL_SEC = env_int(
    "FULTONS_DAILY_MAP_GAME_RETRY_INTERVAL_SEC", 300, minimum=60, maximum=604_800
)
DAILY_MAP_GAME_TRANSIENT_RETRY_INTERVAL_SEC = max(
    DAILY_MAP_GAME_RETRY_INTERVAL_SEC,
    env_int(
        "FULTONS_DAILY_MAP_TRANSIENT_RETRY_INTERVAL_SEC",
        3600,
        minimum=60,
        maximum=604_800,
    ),
)
DAILY_MAP_AI_GENERATION_ENABLED = env_bool(
    "FULTONS_DAILY_MAP_AI_GENERATION_ENABLED", True
)
DAILY_MAP_CONTROLLED_ENABLED = env_bool("FULTONS_DAILY_MAP_CONTROLLED_ENABLED", False)
DAILY_MAP_AUTOMATIC_ENABLED = env_bool("FULTONS_DAILY_MAP_AUTOMATIC_ENABLED", False)
DAILY_MAP_CONTROLLED_CATALOG = Path(os.environ.get("MAP_AI_CATALOG_PATH", "").strip() or controlled_map_round.DEFAULT_CATALOG)
DAILY_MAP_AI_SHORTLIST_LIMIT = env_int(
    "FULTONS_DAILY_MAP_AI_SHORTLIST_LIMIT", 24, minimum=4, maximum=500
)
DAILY_MAP_AI_MAX_CLUE_ATTEMPTS = env_int(
    "FULTONS_DAILY_MAP_AI_MAX_CLUE_ATTEMPTS", 7, minimum=1, maximum=50
)
DAILY_MAP_AI_DISCOVER_COUNT = env_int(
    "FULTONS_DAILY_MAP_AI_DISCOVER_COUNT", 4, minimum=0, maximum=100
)
DAILY_MAP_AI_DISCOVERY_ATTEMPTS = env_int(
    "FULTONS_DAILY_MAP_AI_DISCOVERY_ATTEMPTS", 2, minimum=1, maximum=20
)
DAILY_MAP_AI_GENERATION_ROUNDS = env_int(
    "FULTONS_DAILY_MAP_AI_GENERATION_ROUNDS", 3, minimum=1, maximum=6
)
DAILY_MAP_STADIUM_LAUNCH_DATE = os.environ.get(
    "FULTONS_DAILY_MAP_STADIUM_LAUNCH_DATE", ""
).strip()
DAILY_MAP_STADIUM_LAUNCH_ROUNDS = env_int(
    "FULTONS_DAILY_MAP_STADIUM_LAUNCH_ROUNDS", 3, minimum=0, maximum=30
)
NEWS_USER_AGENT = os.environ.get(
    "FULTONS_NEWS_USER_AGENT",
    "FultonsQuiz/0.1 (+https://fultons-quiz.co.uk)",
)
DAILY_QUIZ_CONFIG = daily_quiz.QuizConfig.from_env()
EXPECTED_DATA_DIR = os.environ.get("FULTONS_EXPECT_DATA_DIR", "").strip()
REQUIRE_EXISTING_DB = env_bool("FULTONS_REQUIRE_EXISTING_DB", False)
MIN_DB_USERS = env_int("FULTONS_MIN_DB_USERS", 0, minimum=0, maximum=1_000_000)
HEALTH_DETAIL = env_bool("FULTONS_HEALTH_DETAIL", False)
COOKIE_SECURE = env_bool("FULTONS_COOKIE_SECURE", True)
SEED_DEMO_USERS = env_bool("FULTONS_SEED_DEMO_USERS", False)
BOOTSTRAP_ADMIN_USERNAME = os.environ.get("FULTONS_BOOTSTRAP_ADMIN_USERNAME", "").strip()
BOOTSTRAP_ADMIN_PASSWORD = os.environ.get("FULTONS_BOOTSTRAP_ADMIN_PASSWORD", "")
MIN_PASSWORD_LENGTH = env_int(
    "FULTONS_MIN_PASSWORD_LENGTH", 12, minimum=10, maximum=128
)
LOGIN_MAX_FAILURES = env_int(
    "FULTONS_LOGIN_MAX_FAILURES",
    5,
    minimum=2,
    maximum=100,
    aliases=("FULTONS_LOGIN_MAX_ATTEMPTS",),
)
LOGIN_LOCKOUT_SECONDS = env_int(
    "FULTONS_LOGIN_LOCKOUT_SECONDS",
    300,
    minimum=1,
    maximum=86_400,
    aliases=("FULTONS_LOGIN_BACKOFF_SECONDS",),
)
LOGIN_WINDOW_SECONDS = env_int(
    "FULTONS_LOGIN_WINDOW_SECONDS", 300, minimum=60, maximum=86_400
)
LOGIN_ATTEMPT_BUCKET_LIMIT = env_int(
    "FULTONS_LOGIN_ATTEMPT_BUCKET_LIMIT", 4096, minimum=256, maximum=1_000_000
)
LOGIN_MAX_CONCURRENT_VERIFICATIONS = env_int(
    "FULTONS_LOGIN_MAX_CONCURRENT_VERIFICATIONS", 4, minimum=1, maximum=64
)
PUBLIC_HEALTH_CACHE_SECONDS = env_int(
    "FULTONS_HEALTH_CACHE_SECONDS", 15, minimum=5, maximum=3600
)
HTTP_READ_TIMEOUT_SECONDS = env_int(
    "FULTONS_HTTP_READ_TIMEOUT_SECONDS", 15, minimum=5, maximum=300
)
HTTP_MAX_WORKERS = env_int(
    "FULTONS_HTTP_MAX_WORKERS", 64, minimum=8, maximum=1024
)
HTTP_REQUEST_MAX_BYTES = env_int(
    "FULTONS_HTTP_REQUEST_MAX_BYTES", 1_000_000, minimum=1024, maximum=10_000_000
)
NEWS_STREAM_LIMIT = env_int(
    "FULTONS_NEWS_STREAM_LIMIT", 24, minimum=1, maximum=1000
)
AUDIT_RETENTION_DAYS = env_int(
    "FULTONS_AUDIT_RETENTION_DAYS", 365, minimum=30, maximum=3650
)
AUDIT_ROW_LIMIT = env_int(
    "FULTONS_AUDIT_ROW_LIMIT", 100_000, minimum=1000, maximum=2_000_000
)
SERVER_HOST = os.environ.get("FULTONS_HOST", "127.0.0.1").strip() or "127.0.0.1"
SERVER_PORT = env_int("FULTONS_PORT", 8000, minimum=1, maximum=65_535)
TRUST_PROXY_HEADERS = env_bool("FULTONS_TRUST_PROXY_HEADERS", False)
TRUSTED_PROXY_NETWORKS = env_ip_networks("FULTONS_TRUSTED_PROXY_CIDRS")
if TRUST_PROXY_HEADERS and not TRUSTED_PROXY_NETWORKS:
    raise RuntimeError(
        "FULTONS_TRUSTED_PROXY_CIDRS must be configured when proxy headers are trusted."
    )
CORS_ALLOWED_ORIGINS = {
    origin.strip()
    for origin in os.environ.get("FULTONS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
}
CORS_ALLOWED_ORIGINS.update(
    {
        "https://fultons-quiz.co.uk",
        "https://www.fultons-quiz.co.uk",
    }
)
ALLOWED_HOSTS = {
    host.strip().lower().rstrip(".")
    for host in os.environ.get("FULTONS_ALLOWED_HOSTS", "").split(",")
    if host.strip()
}
ALLOWED_HOSTS.update(
    parsed.hostname.lower().rstrip(".")
    for parsed in (urlparse(origin) for origin in CORS_ALLOWED_ORIGINS)
    if parsed.hostname
)
ALLOWED_HOSTS.update(
    {
        "127.0.0.1",
        "localhost",
        "::1",
        "fultons-quiz.co.uk",
        "www.fultons-quiz.co.uk",
    }
)
WORDLE_POINTS_BY_ATTEMPT = {1: 10, 2: 5, 3: 4, 4: 3, 5: 2, 6: 1}
WORDLE_DIFFICULTY_BONUS_PER_LEVEL = 2
QUIZ_POINTS_BY_DIFFICULTY = {"easy": 1, "medium": 3, "hard": 5}
QUIZ_PERFECT_ROUND_BONUS = 3
QUIZ_SCORING_VERSION = "opaque-choice-v1"
QUIZ_MAX_SUBMITTED_ANSWERS = 6
QUIZ_PUBLIC_ID_MAX_LENGTH = 64
WORD_DEFINITION_TIMEOUT_SEC = env_int(
    "FULTONS_WORD_DEFINITION_TIMEOUT_SEC", 5, minimum=1, maximum=30
)
WORD_DEFINITION_CACHE_MAX_ENTRIES = env_int(
    "FULTONS_WORD_DEFINITION_CACHE_MAX_ENTRIES", 512, minimum=32, maximum=20_000
)
WORD_DEFINITION_CACHE: dict[str, dict[str, Any]] = {}
WORD_DEFINITION_CACHE_LOCK = threading.Lock()
NEWS_MIN_RECENT_SCOPED_ITEMS = 8
NEWS_RECENT_WINDOW_HOURS = 72
NEWS_SCOPED_QUERY_CONFIGS = (
    {"query": '"St Mirren" when:7d', "tags": ("st-mirren", "scottish-football")},
    {"query": '"St Mirren" football when:7d', "tags": ("st-mirren", "scottish-football")},
    {"query": '"St Mirren" transfer when:30d', "tags": ("st-mirren", "scottish-football")},
    {
        "query": '"St Mirren" Scottish Premiership when:30d',
        "tags": ("st-mirren", "scottish-football"),
    },
    {"query": '"St Mirren" live score when:7d', "tags": ("st-mirren", "scottish-football")},
    {
        "query": '"Scottish Premiership" live scores when:7d',
        "tags": ("st-mirren", "scottish-football"),
    },
)
NEWS_SUPPLEMENTAL_QUERY_CONFIGS = (
    {"query": '"snooker" when:7d', "tags": ("sport", "snooker")},
    {"query": '"World Snooker Tour" when:7d', "tags": ("sport", "snooker")},
    {"query": '"darts" when:7d', "tags": ("sport", "darts")},
    {"query": '"Scottish sport" when:3d', "tags": ("sport", "scotland")},
)
NEWS_STREAMS: set[queue.Queue[dict[str, Any]]] = set()
NEWS_STREAMS_LOCK = threading.Lock()
LOGIN_ATTEMPTS: dict[str, tuple[deque[float], float]] = {}
LOGIN_ATTEMPTS_LOCK = threading.Lock()
LOGIN_VERIFY_SEMAPHORE = threading.BoundedSemaphore(
    LOGIN_MAX_CONCURRENT_VERIFICATIONS
)
PUBLIC_HEALTH_CACHE: tuple[float, dict[str, Any]] | None = None
PUBLIC_HEALTH_CACHE_LOCK = threading.Lock()
DATABASE_INITIALIZE_LOCK = threading.Lock()
SQLITE_WAL_INITIALIZE_LOCK = threading.Lock()
SQLITE_WAL_INITIALIZED_PATHS: set[str] = set()
DAILY_QUIZ_OPERATION_LOCK = threading.Lock()
DAILY_MAP_GAME_OPERATION_LOCK = threading.Lock()
MAP_LEARNING_REFRESH_LOCK = threading.Lock()
DAILY_MAP_AUTOMATIC_RETRY_AT: datetime | None = None

sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(APP_DIR))

from wordle_game import (  # noqa: E402
    MAX_ATTEMPTS,
    WORD_LENGTH,
    choose_secret,
    choose_secret_for_difficulty,
    compute_feedback,
    difficulty_for_streak,
    load_answer_words,
    load_word_difficulty_ratings,
    reset_used_words,
    serialize_feedback,
    valid_guess,
)


def server_timezone() -> timezone | ZoneInfo:
    if ZoneInfo is None:
        return timezone.utc

    try:
        return ZoneInfo(SERVER_TZ_NAME)
    except Exception:
        return timezone.utc


SERVER_TZ = server_timezone()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today_game_date() -> str:
    return datetime.now(SERVER_TZ).date().isoformat()


def game_date_period_utc_bounds(period_start: str, period_end: str) -> tuple[str, str]:
    """Return UTC instants bounding inclusive local game dates."""
    start_date = date.fromisoformat(period_start)
    end_exclusive_date = date.fromisoformat(period_end) + timedelta(days=1)
    start_local = datetime.combine(start_date, datetime.min.time(), tzinfo=SERVER_TZ)
    end_exclusive_local = datetime.combine(
        end_exclusive_date,
        datetime.min.time(),
        tzinfo=SERVER_TZ,
    )
    return (
        start_local.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
        end_exclusive_local.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
    )


def safe_log(message: str) -> None:
    try:
        print(message, flush=True)
    except OSError:
        pass


def refresh_map_learning_after_review(training_dir: Path) -> dict[str, Any]:
    feedback_files = training_data_store.default_map_place_review_feedback_files(
        training_dir
    )
    feedback_rows = training_data_store.read_map_place_review_feedback_rows(
        feedback_files
    )

    selector_profile = build_map_selector_profile.build_profile(
        feedback_rows,
        source_files=feedback_files,
    )
    selector_profile_path = training_dir / "map_selector_profile_latest.json"
    selector_profile_path.write_text(
        json.dumps(selector_profile, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )

    selector_model = map_selector_model.fit_model(feedback_rows)
    selector_model_path = training_dir / "map_selector_model_latest.json"
    map_selector_model.save_model(selector_model, selector_model_path)

    clue_model = map_clue_quality_model.build_model_from_training_dir(training_dir)
    clue_model_path = training_dir / "map_clue_quality_model_latest.json"
    map_clue_quality_model.save_model(clue_model, clue_model_path)

    generation_profile_path = ""
    generation_profile_validation: dict[str, Any] = {}
    try:
        generation_profile = refresh_map_learning_profile.build_candidate_profile(
            negative_files=refresh_map_learning_profile.latest_negative_files(
                training_dir
            ),
            failure_log_files=refresh_map_learning_profile.latest_failure_log_files(
                training_dir
            ),
            review_rows_files=refresh_map_learning_profile.latest_review_rows_files(
                training_dir
            ),
            place_review_feedback_files=feedback_files,
            gold_examples_file=None,
        )
        generation_profile_validation = (
            generation_profile.get("validation")
            if isinstance(generation_profile.get("validation"), dict)
            else {}
        )
        if generation_profile_validation.get("passed", False):
            generation_profile_path = str(
                training_dir / "map_learning_profile_latest.json"
            )
            Path(generation_profile_path).write_text(
                json.dumps(generation_profile, indent=2, ensure_ascii=True),
                encoding="utf-8",
            )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        generation_profile_validation = {
            "passed": False,
            "errors": [str(error)],
        }

    return {
        "feedbackRowCount": len(feedback_rows),
        "selectorModel": {
            "path": str(selector_model_path),
            "rowCount": selector_model.get("row_count", 0),
            "trainingMae": selector_model.get("training_mae"),
            "baselineMae": selector_model.get("baseline_mae"),
        },
        "clueQualityModel": {
            "path": str(clue_model_path),
            "rowCount": clue_model.get("row_count", 0),
            "validation": clue_model.get("validation", {}),
            "validationByLevel": clue_model.get("validation_by_level", {}),
        },
        "selectorProfilePath": str(selector_profile_path),
        "generationProfilePath": generation_profile_path,
        "generationProfileValidation": generation_profile_validation,
    }


def refresh_map_learning_from_corrections() -> dict[str, Any]:
    """Replay durable admin corrections into training and rebuild the Map profiles."""
    with MAP_LEARNING_REFRESH_LOCK:
        with closing(connect_db()) as conn:
            rows = map_clue_editor.correction_feedback_rows(conn)
            conn.commit()
        if not rows:
            return {"ok": True, "feedbackRows": 0}
        training_dir = DATA_DIR / "training"
        training_data_store.merge_map_place_review_feedback_rows(
            training_data_store.consolidated_map_place_review_feedback_file(training_dir),
            rows,
            source_file="admin-map-clue-corrections",
        )
        summary = refresh_map_learning_after_review(training_dir)
        validation = summary.get("generationProfileValidation") or {}
        if not validation.get("passed"):
            raise RuntimeError("Map generation profile did not pass validation.")
        return {"ok": True, "feedbackRows": len(rows)}


def is_loopback_ip(value: str) -> bool:
    return value in {"127.0.0.1", "::1", "::ffff:127.0.0.1"}


def is_development_origin_host(value: str | None) -> bool:
    if value in {"localhost", "127.0.0.1"}:
        return True
    if value is None:
        return False
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.is_loopback or address.is_private


def db_user_count(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM sqlite_master WHERE type = 'table' AND name = 'users'"
    ).fetchone()
    if row is None or row["count"] == 0:
        return None
    return int(conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"])


def runtime_storage_health(
    *,
    write_check: bool = False,
    deep_check: bool = True,
    require_existing_db: bool | None = None,
    min_users: int | None = None,
) -> dict[str, Any]:
    require_db = REQUIRE_EXISTING_DB if require_existing_db is None else require_existing_db
    minimum_users = MIN_DB_USERS if min_users is None else min_users
    errors: list[str] = []
    payload: dict[str, Any] = {
        "ok": True,
        "dataDir": str(DATA_DIR),
        "dbPath": str(DB_PATH),
        "expectedDataDir": EXPECTED_DATA_DIR or None,
        "uid": os.getuid() if hasattr(os, "getuid") else None,
        "gid": os.getgid() if hasattr(os, "getgid") else None,
        "writeCheck": write_check,
        "requireExistingDb": require_db,
        "minUsers": minimum_users,
    }

    if EXPECTED_DATA_DIR and str(DATA_DIR) != EXPECTED_DATA_DIR:
        errors.append(f"DATA_DIR is {DATA_DIR}, expected {EXPECTED_DATA_DIR}")

    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        errors.append(f"Cannot create data directory: {error}")

    payload["dataDirExists"] = DATA_DIR.exists()
    payload["dataDirIsDir"] = DATA_DIR.is_dir()
    payload["dataDirWritable"] = os.access(DATA_DIR, os.W_OK) if DATA_DIR.exists() else False

    if write_check and DATA_DIR.exists():
        probe_path = DATA_DIR / ".fultons-startup-write-test"
        try:
            probe_path.write_text("ok", encoding="utf-8")
            probe_path.unlink(missing_ok=True)
            payload["dataDirWriteProbe"] = "ok"
        except OSError as error:
            errors.append(f"Cannot write to data directory: {error}")
            payload["dataDirWriteProbe"] = "failed"

    payload["dbExists"] = DB_PATH.exists()
    if require_db and not DB_PATH.exists():
        errors.append(f"Required database is missing at {DB_PATH}")

    if DB_PATH.exists():
        try:
            payload["dbSizeBytes"] = DB_PATH.stat().st_size
            payload["dbWritable"] = os.access(DB_PATH, os.W_OK)
        except OSError as error:
            errors.append(f"Cannot stat database: {error}")

    if require_db and not DB_PATH.exists():
        payload["errors"] = errors
        payload["ok"] = not errors
        return payload

    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            if deep_check:
                quick_check = conn.execute("PRAGMA quick_check").fetchone()
                payload["quickCheck"] = quick_check[0] if quick_check is not None else None
                if payload["quickCheck"] != "ok":
                    errors.append(f"SQLite quick_check returned {payload['quickCheck']!r}")
            else:
                conn.execute("SELECT 1").fetchone()
                payload["quickCheck"] = "deferred"

            table_row = conn.execute(
                "SELECT COUNT(*) AS count FROM sqlite_master WHERE type = 'table'"
            ).fetchone()
            payload["tableCount"] = int(table_row["count"]) if table_row else 0
            user_count = db_user_count(conn)
            payload["userCount"] = user_count
            if minimum_users > 0 and (user_count is None or user_count < minimum_users):
                errors.append(
                    f"Database user count is {user_count or 0}, expected at least {minimum_users}"
                )

            if write_check:
                now = utc_now()
                with conn:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS startup_checks (
                            checked_at TEXT PRIMARY KEY
                        )
                        """
                    )
                    conn.execute(
                        "INSERT OR REPLACE INTO startup_checks (checked_at) VALUES (?)",
                        (now,),
                    )
                    conn.execute("DELETE FROM startup_checks WHERE checked_at = ?", (now,))
                payload["dbWriteProbe"] = "ok"
        finally:
            conn.close()
    except sqlite3.Error as error:
        errors.append(f"SQLite access failed: {error}")
    except OSError as error:
        errors.append(f"Database filesystem access failed: {error}")

    payload["errors"] = errors
    payload["ok"] = not errors
    return payload


def public_runtime_storage_health() -> dict[str, Any]:
    """Return a cheap, briefly cached readiness result for the public probe."""
    global PUBLIC_HEALTH_CACHE
    now = time.monotonic()
    with PUBLIC_HEALTH_CACHE_LOCK:
        cached = PUBLIC_HEALTH_CACHE
        if cached is not None and now - cached[0] < PUBLIC_HEALTH_CACHE_SECONDS:
            return dict(cached[1])
        storage = runtime_storage_health(deep_check=False)
        PUBLIC_HEALTH_CACHE = now, dict(storage)
        return storage


def assert_runtime_storage_ready(stage: str) -> None:
    payload = runtime_storage_health(write_check=True)
    if payload["ok"]:
        safe_log(
            "Runtime storage check passed "
            f"({stage}): db={payload.get('dbPath')} users={payload.get('userCount')}"
        )
        return

    safe_log(f"Runtime storage check failed ({stage}): {json.dumps(payload, sort_keys=True)}")
    raise RuntimeError("; ".join(payload["errors"]))


def health_storage_payload(storage: dict[str, Any]) -> dict[str, Any]:
    if HEALTH_DETAIL:
        return storage
    return {
        "ok": storage["ok"],
        "errorCount": len(storage.get("errors", [])),
    }


def health_payload(storage: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": storage["ok"],
        "date": today_game_date(),
        "storage": health_storage_payload(storage),
        "build": {
            "version": CACHE_VERSION,
        },
    }


def ops_quiz_preview(conn: sqlite3.Connection, quiz_date: str) -> dict[str, Any]:
    status = daily_quiz.quiz_status(conn, quiz_date)
    preview = {
        "date": quiz_date,
        "status": status["status"],
        "acceptedQuestions": int(status.get("accepted_questions") or 0),
        "failedAttempts": int(status.get("failed_attempts") or 0),
        "failureReason": status.get("failure_reason"),
        "lastFailureReason": status.get("last_failure_reason"),
        "lastFailureTransient": bool(status.get("last_failure_transient")),
        "questions": [],
        "updatedAt": None,
    }
    if int(status.get("accepted_questions") or 0) <= 0:
        return preview
    try:
        payload = daily_quiz.quiz_questions_payload(
            conn,
            quiz_date,
            allow_unpublished=True,
        )
    except LookupError:
        return preview
    preview["questions"] = [
        {
            "subject": str(question.get("subject") or ""),
            "difficulty": str(question.get("difficulty") or ""),
            "question": str(question.get("question") or ""),
            "choices": [str(choice) for choice in question.get("choices", [])],
            "correctAnswer": str(question.get("correct_answer") or ""),
            "explanation": str(question.get("explanation") or ""),
        }
        for question in payload.get("questions", [])
        if isinstance(question, dict)
    ]
    preview["acceptedQuestions"] = len(preview["questions"])
    return preview


def internal_ops_summary_payload() -> dict[str, Any]:
    tz = server_timezone()
    local_now = datetime.now(tz)
    today_date = local_now.date().isoformat()
    tomorrow_date = (local_now.date() + timedelta(days=1)).isoformat()
    storage = runtime_storage_health()
    tests: list[dict[str, Any]] = []
    with connect_db() as conn:
        quick_check_row = conn.execute("PRAGMA quick_check").fetchone()
        quick_check = quick_check_row[0] if quick_check_row is not None else None
        table_counts: dict[str, int] = {}
        for table in (
            "users",
            "news_items",
            "daily_quiz_sets",
            "daily_quiz_questions",
            "daily_quiz_attempts",
            "daily_map_puzzles",
            "daily_map_levels",
            "quiz_results",
            "wordle_results",
        ):
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            if row and row["count"]:
                table_counts[table] = int(
                    conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]
                )
        today_quiz = ops_quiz_preview(conn, today_date)
        tomorrow_quiz = ops_quiz_preview(conn, tomorrow_date)
        quiz_pool = daily_quiz.quiz_pool_status(conn)
        current_map_date = daily_map_game.active_map_round_date(today_date)
        next_day_map_date = daily_map_game.active_map_round_date(tomorrow_date)
        today_map = daily_map_game.puzzle_status(conn, current_map_date)
        tomorrow_map = daily_map_game.puzzle_status(conn, next_day_map_date)
        queue_exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='automatic_map_entries'").fetchone()
        if queue_exists:
            tests.append(
                ops_map_reserve_test(conn)
            )
        tests.append(
            {
                "id": "quiz_pool",
                "label": "Quiz reserve pool",
                "status": (
                    "pass"
                    if quiz_pool["ready"] >= DAILY_QUIZ_POOL_TARGET_BATCHES
                    else "warn"
                ),
                "detail": (
                    f"{quiz_pool['ready']}/{DAILY_QUIZ_POOL_TARGET_BATCHES} "
                    "verified batches ready"
                ),
            }
        )
        quiz_failures = conn.execute("SELECT COUNT(*) FROM daily_quiz_attempts WHERE quiz_date=? AND passed=0", (tomorrow_date,)).fetchone()[0]
        tests.append({"id": "quiz_generation_retries", "label": "Tomorrow quiz generation retries", "status": "warn" if quiz_failures >= 60 else "pass", "detail": f"{quiz_failures} rejected attempts"})
        if local_now.hour >= DAILY_QUIZ_RECOVERY_HOUR and tomorrow_quiz.get("status") != "published":
            tests.append({"id": "quiz_publication_deadline", "label": "Tomorrow quiz readiness", "status": "fail", "detail": "Quiz is still unpublished after the evening recovery deadline"})
        user_count = db_user_count(conn)

    application_health = health_payload(storage)
    tests.append(
        {
            "id": "sqlite_quick_check",
            "label": "SQLite quick_check",
            "status": "pass" if quick_check == "ok" else "fail",
            "detail": str(quick_check),
        }
    )
    tests.append(
        {
            "id": "internal_health",
            "label": "Internal /api/health",
            "status": "pass" if storage["ok"] else "fail",
            "detail": "HTTP 200 in 0ms",
        }
    )
    today_status = str(today_quiz.get("status") or "missing")
    tests.append(
        {
            "id": "today_quiz",
            "label": "Today quiz",
            "status": "pass" if today_status == "published" else "fail",
            "detail": f"{today_status} / accepted {today_quiz.get('acceptedQuestions', 0)}",
        }
    )
    tomorrow_status = str(tomorrow_quiz.get("status") or "missing")
    tests.append(
        {
            "id": "tomorrow_quiz",
            "label": "Tomorrow quiz",
            "status": "pass"
            if tomorrow_status == "published"
            else "warn"
            if tomorrow_status in {"generating", "ready", "draft"}
            else "fail",
            "detail": f"{tomorrow_status} / accepted {tomorrow_quiz.get('acceptedQuestions', 0)}",
        }
    )
    for test_id, label, map_status in (
        ("today_map", "Current map round", today_map),
        ("tomorrow_map", "Next day map round", tomorrow_map),
    ):
        map_test = ops_map_readiness_test(test_id, current_map_date if test_id == "today_map" else next_day_map_date, label, map_status)
        tests.append(
            {
                "id": map_test["id"],
                "label": map_test["label"],
                "status": map_test["status"],
                "detail": map_test["detail"],
            }
        )
    return {
        "ok": bool(storage["ok"]),
        "generatedAt": utc_now(),
        "transport": "https-fallback",
        "host": {
            "hostname": socket.gethostname(),
            "power": {"acOnline": None, "batteries": []},
        },
        "resources": {
            "memory": {},
            "disks": [],
        },
        "docker": {
            "containers": [],
            "volumes": [],
            "networks": [],
        },
        "application": {
            "composeFile": "",
            "envFile": "",
            "dataDir": str(DATA_DIR),
            "dbPath": str(DB_PATH),
            "health": {
                "url": "internal://api/health",
                "status": 200,
                "responseTimeMs": 0,
                "payload": application_health,
                "ok": bool(storage["ok"]),
                "probeSource": "in-process",
            },
            "sqlite": {
                "dbExists": DB_PATH.exists(),
                "dbPath": str(DB_PATH),
                "dbSizeBytes": DB_PATH.stat().st_size if DB_PATH.exists() else None,
                "quickCheck": quick_check,
                "tableCounts": table_counts,
                "todayQuiz": today_quiz,
                "tomorrowQuiz": tomorrow_quiz,
                "todayMap": today_map,
                "tomorrowMap": tomorrow_map,
                "userCount": user_count,
            },
        },
        "quiz": {
            "today": today_quiz,
            "tomorrow": tomorrow_quiz,
        },
        "map": {
            "today": today_map,
            "tomorrow": tomorrow_map,
        },
        "tests": tests,
        "errors": [],
        "partial": True,
    }


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return "$".join(
        [
            "pbkdf2_sha256",
            str(PASSWORD_ITERATIONS),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False

        salt = base64.b64decode(salt_b64)
        expected_digest = base64.b64decode(digest_b64)
        actual_digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations),
        )
        return hmac.compare_digest(actual_digest, expected_digest)
    except Exception:
        return False


# Missing accounts are checked against a real PBKDF2 hash so username existence is
# not exposed through the large valid-vs-invalid password verification timing gap.
DUMMY_PASSWORD_HASH = hash_password("fultons-invalid-account-placeholder")


def validate_username(username: str) -> str | None:
    if not USERNAME_RE.fullmatch(username):
        return "Use 3-32 letters, numbers, underscores, or hyphens."
    return None


def validate_password(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > 512:
        return "Use no more than 512 characters."
    return None


def initialize_wal_once(conn: sqlite3.Connection, database_path: Path) -> None:
    """Enable persistent WAL mode once per database path, serialized per process."""
    path_key = str(database_path.resolve())
    if path_key in SQLITE_WAL_INITIALIZED_PATHS:
        return
    with SQLITE_WAL_INITIALIZE_LOCK:
        if path_key in SQLITE_WAL_INITIALIZED_PATHS:
            return
        if conn.in_transaction:
            raise RuntimeError("SQLite WAL initialization requires an idle connection.")
        row = conn.execute("PRAGMA journal_mode = WAL").fetchone()
        mode = str(row[0] if row is not None else "").lower()
        if mode != "wal":
            raise RuntimeError(
                f"Could not enable SQLite WAL mode for {database_path}; got {mode or 'no mode'}."
            )
        SQLITE_WAL_INITIALIZED_PATHS.add(path_key)


def connect_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 10000")
        initialize_wal_once(conn, DB_PATH)
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    except Exception:
        conn.close()
        raise


def run_schema_migration(
    conn: sqlite3.Connection,
    version: str,
    operation: Any,
) -> bool:
    """Run an idempotent data migration once and record it transactionally."""
    exists = conn.execute(
        "SELECT 1 FROM schema_migrations WHERE version = ?",
        (version,),
    ).fetchone()
    if exists is not None:
        return False
    operation(conn)
    conn.execute(
        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (version, utc_now()),
    )
    return True


def backfill_released_quiz_locks(conn: sqlite3.Connection) -> None:
    """Protect quizzes that may already have been loaded before this release."""
    conn.execute(
        """
        UPDATE daily_quiz_sets
        SET locked_at = COALESCE(locked_at, ?)
        WHERE status = 'published' AND quiz_date <= ?
        """,
        (utc_now(), today_game_date()),
    )


def _initialize_database_locked() -> None:
    with closing(connect_db()) as conn:
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_lower
            ON users (LOWER(username));

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_expires_at
            ON sessions (expires_at);

            CREATE INDEX IF NOT EXISTS idx_sessions_user_created_at
            ON sessions (user_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                actor_user_id INTEGER,
                target_user_id INTEGER,
                client_ip TEXT NOT NULL DEFAULT '',
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_audit_events_created_at
            ON audit_events (created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_audit_events_actor_created_at
            ON audit_events (actor_user_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS user_announcement_acknowledgements (
                user_id INTEGER NOT NULL,
                campaign_id TEXT NOT NULL,
                action TEXT NOT NULL CHECK (action IN ('played', 'dismissed')),
                acknowledged_at TEXT NOT NULL,
                PRIMARY KEY (user_id, campaign_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS daily_wordle_games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_date TEXT NOT NULL UNIQUE,
                secret_word TEXT NOT NULL,
                cycle INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS wordle_used_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT NOT NULL,
                game_id INTEGER NOT NULL,
                used_on TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (game_id) REFERENCES daily_wordle_games(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS wordle_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                game_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'in_progress'
                    CHECK (status IN ('in_progress', 'won', 'lost')),
                attempts_used INTEGER NOT NULL DEFAULT 0,
                completed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (game_id) REFERENCES daily_wordle_games(id) ON DELETE CASCADE,
                UNIQUE (user_id, game_id)
            );

            CREATE TABLE IF NOT EXISTS wordle_user_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                game_id INTEGER NOT NULL,
                secret_word TEXT NOT NULL,
                difficulty INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (game_id) REFERENCES daily_wordle_games(id) ON DELETE CASCADE,
                UNIQUE (user_id, game_id)
            );

            CREATE TABLE IF NOT EXISTS wordle_guesses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                result_id INTEGER NOT NULL,
                attempt_number INTEGER NOT NULL,
                guess TEXT NOT NULL,
                feedback_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (result_id) REFERENCES wordle_results(id) ON DELETE CASCADE,
                UNIQUE (result_id, attempt_number)
            );

            CREATE TABLE IF NOT EXISTS daily_quiz_progress (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                game_date TEXT NOT NULL,
                category TEXT NOT NULL CHECK (category IN ('football', 'general')),
                answers_json TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, game_date, category)
            );

            CREATE TABLE IF NOT EXISTS daily_quiz_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                game_date TEXT NOT NULL,
                category TEXT NOT NULL CHECK (category IN ('football', 'general')),
                answers_json TEXT NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                max_score INTEGER NOT NULL DEFAULT 0,
                correct_count INTEGER NOT NULL DEFAULT 0,
                bonus_points INTEGER NOT NULL DEFAULT 0,
                quiz_version TEXT NOT NULL DEFAULT 'legacy',
                scoring_version TEXT NOT NULL DEFAULT 'legacy',
                adjudication_json TEXT NOT NULL DEFAULT '[]',
                completed_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE (user_id, game_date, category)
            );

            CREATE TABLE IF NOT EXISTS news_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_key TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL DEFAULT 'article',
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                source TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL,
                host TEXT NOT NULL DEFAULT '',
                priority TEXT NOT NULL DEFAULT 'media',
                tags_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_news_items_published_at
            ON news_items (published_at DESC);
            """
            )
            ensure_column(conn, "users", "is_moderator", "INTEGER NOT NULL DEFAULT 0")
            ensure_column(conn, "daily_wordle_games", "cycle", "INTEGER NOT NULL DEFAULT 1")
            ensure_column(conn, "wordle_results", "score", "INTEGER NOT NULL DEFAULT 0")
            ensure_column(conn, "daily_quiz_results", "bonus_points", "INTEGER NOT NULL DEFAULT 0")
            ensure_column(
                conn,
                "daily_quiz_results",
                "quiz_version",
                "TEXT NOT NULL DEFAULT 'legacy'",
            )
            ensure_column(
                conn,
                "daily_quiz_results",
                "scoring_version",
                "TEXT NOT NULL DEFAULT 'legacy'",
            )
            ensure_column(
                conn,
                "daily_quiz_results",
                "adjudication_json",
                "TEXT NOT NULL DEFAULT '[]'",
            )
            ensure_column(conn, "news_items", "story_key", "TEXT NOT NULL DEFAULT ''")
            cleanup_expired_sessions(conn)
            run_schema_migration(
                conn,
                "2026-08-13-session-token-digests",
                migrate_plaintext_session_tokens,
            )
            prune_session_rows(conn, all_users=True)
            prune_audit_events(conn)
            run_schema_migration(
                conn,
                "2026-08-13-wordle-assignment-difficulties",
                backfill_wordle_assignment_difficulties,
            )
            run_schema_migration(
                conn,
                "2026-08-13-wordle-scores",
                backfill_wordle_scores,
            )
            daily_quiz.initialize_database(conn)
            quiz_board.initialize_database(conn)
            run_schema_migration(
                conn,
                "2026-08-16-lock-released-daily-quizzes",
                backfill_released_quiz_locks,
            )
            daily_map_game.initialize_database(conn)
            user_count = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
            if user_count == 0:
                bootstrap_error = validate_bootstrap_admin()
                if bootstrap_error is None and BOOTSTRAP_ADMIN_USERNAME and BOOTSTRAP_ADMIN_PASSWORD:
                    seed_user(conn, BOOTSTRAP_ADMIN_USERNAME, BOOTSTRAP_ADMIN_PASSWORD, "admin")
                    safe_log(f"Bootstrapped admin user {BOOTSTRAP_ADMIN_USERNAME!r}")
                elif SEED_DEMO_USERS:
                    seed_user(conn, "admin", "adminadmin123", "admin")
                    seed_user(conn, "user1", "user1user1234", "user")
                    seed_user(conn, "user2", "user2user1234", "user")
                    safe_log("Seeded demo users because FULTONS_SEED_DEMO_USERS=1")
                else:
                    if bootstrap_error is not None:
                        safe_log(f"Admin bootstrap skipped: {bootstrap_error}")
                    safe_log("No users exist and demo seeding is disabled.")


def initialize_database() -> None:
    with DATABASE_INITIALIZE_LOCK:
        _initialize_database_locked()


def ensure_column(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})")
    }
    if column_name in columns:
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def seed_user(conn: sqlite3.Connection, username: str, password: str, role: str) -> None:
    row = conn.execute(
        "SELECT id FROM users WHERE LOWER(username) = LOWER(?)",
        (username,),
    ).fetchone()
    if row is not None:
        return

    now = utc_now()
    conn.execute(
        """
        INSERT INTO users (username, password_hash, role, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (username, hash_password(password), role, now, now),
    )


def validate_bootstrap_admin() -> str | None:
    if not BOOTSTRAP_ADMIN_USERNAME and not BOOTSTRAP_ADMIN_PASSWORD:
        return None
    if not BOOTSTRAP_ADMIN_USERNAME or not BOOTSTRAP_ADMIN_PASSWORD:
        return "set both FULTONS_BOOTSTRAP_ADMIN_USERNAME and FULTONS_BOOTSTRAP_ADMIN_PASSWORD"

    username_error = validate_username(BOOTSTRAP_ADMIN_USERNAME)
    if username_error is not None:
        return f"bootstrap username invalid: {username_error}"

    password_error = validate_password(BOOTSTRAP_ADMIN_PASSWORD)
    if password_error is not None:
        return f"bootstrap password invalid: {password_error}"

    return None


def row_has_value(row: sqlite3.Row, key: str) -> bool:
    return key in row.keys() and bool(row[key])


def effective_user_role(row: sqlite3.Row) -> str:
    if row["role"] == "admin":
        return "admin"
    return "mod" if row_has_value(row, "is_moderator") else "user"


def user_can_manage_players(row: sqlite3.Row) -> bool:
    return row["role"] == "admin" or row_has_value(row, "is_moderator")


def user_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "username": row["username"], "role": effective_user_role(row)}


def map_promo_is_available() -> bool:
    if not MAP_PROMO_CAMPAIGN_ID:
        return False
    try:
        available_date = date.fromisoformat(MAP_PROMO_AVAILABLE_DATE)
        current_date = date.fromisoformat(today_game_date())
    except ValueError:
        return False
    return current_date >= available_date


def available_announcements() -> list[dict[str, str]]:
    if not map_promo_is_available():
        return []
    return [{"id": MAP_PROMO_CAMPAIGN_ID, "kind": "daily-map-promo"}]


def pending_announcements(conn: sqlite3.Connection, user_id: int) -> list[dict[str, str]]:
    announcements = available_announcements()
    if not announcements:
        return []
    acknowledged = conn.execute(
        """
        SELECT 1
        FROM user_announcement_acknowledgements
        WHERE user_id = ? AND campaign_id = ?
        """,
        (user_id, MAP_PROMO_CAMPAIGN_ID),
    ).fetchone()
    if acknowledged is not None:
        return []
    return announcements


def auth_payload(conn: sqlite3.Connection, user: sqlite3.Row) -> dict[str, Any]:
    return {
        "user": user_payload(user),
        "availableAnnouncements": available_announcements(),
        "pendingAnnouncements": pending_announcements(conn, int(user["id"])),
    }


def admin_user_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "role": effective_user_role(row),
        "createdAt": row["created_at"],
        "gamesPlayed": row["games_played"] or 0,
        "wins": row["wins"] or 0,
        "losses": row["losses"] or 0,
    }


def create_session(conn: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    stored_token = session_token_digest(token)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    expires_at = now + timedelta(days=SESSION_DAYS)
    cleanup_expired_sessions(conn, now=now.isoformat())
    conn.execute(
        """
        INSERT INTO sessions (token, user_id, created_at, expires_at)
        VALUES (?, ?, ?, ?)
        """,
        (stored_token, user_id, now.isoformat(), expires_at.isoformat()),
    )
    prune_session_rows(conn, user_id=user_id)
    return token


def session_token_digest(token: str) -> str:
    """Return the non-reversible representation persisted for new sessions."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


SESSION_TOKEN_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def migrate_plaintext_session_tokens(conn: sqlite3.Connection) -> None:
    """Hash legacy session rows without invalidating the client-side token."""
    rows = conn.execute("SELECT token FROM sessions").fetchall()
    for row in rows:
        token = str(row["token"])
        if SESSION_TOKEN_DIGEST_RE.fullmatch(token):
            continue
        digest = session_token_digest(token)
        updated = conn.execute(
            "UPDATE OR IGNORE sessions SET token = ? WHERE token = ?",
            (digest, token),
        )
        if updated.rowcount == 0:
            # A digest row already exists. Keeping both would preserve an
            # ambiguous plaintext credential, so retain the hashed row only.
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def get_cookie_value(headers: Any, name: str) -> str | None:
    raw_cookie = headers.get("Cookie")
    if not raw_cookie:
        return None

    cookie = SimpleCookie()
    cookie.load(raw_cookie)
    morsel = cookie.get(name)
    return morsel.value if morsel is not None else None


def cookie_attributes(max_age: int) -> str:
    attributes = [f"Path=/", "HttpOnly", "SameSite=Lax", f"Max-Age={max_age}"]
    if COOKIE_SECURE:
        attributes.append("Secure")
    return "; ".join(attributes)


def session_header(token: str) -> str:
    max_age = SESSION_DAYS * 24 * 60 * 60
    return f"{SESSION_COOKIE}={token}; {cookie_attributes(max_age)}"


def clear_session_header() -> str:
    return f"{SESSION_COOKIE}=; {cookie_attributes(0)}"


def cache_version_header() -> str:
    max_age = 365 * 24 * 60 * 60
    return f"{CACHE_VERSION_COOKIE}={CACHE_VERSION}; {cookie_attributes(max_age)}"


def cleanup_expired_sessions(conn: sqlite3.Connection, now: str | None = None) -> None:
    conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now or utc_now(),))


def prune_session_rows(
    conn: sqlite3.Connection,
    *,
    user_id: int | None = None,
    all_users: bool = False,
) -> None:
    """Bound live session storage globally and per account."""
    if all_users:
        conn.execute(
            """
            DELETE FROM sessions
            WHERE token IN (
                SELECT token
                FROM (
                    SELECT
                        token,
                        ROW_NUMBER() OVER (
                            PARTITION BY user_id
                            ORDER BY created_at DESC, token DESC
                        ) AS session_rank
                    FROM sessions
                )
                WHERE session_rank > ?
            )
            """,
            (SESSION_MAX_PER_USER,),
        )
    elif user_id is not None:
        conn.execute(
            """
            DELETE FROM sessions
            WHERE token IN (
                SELECT token
                FROM sessions
                WHERE user_id = ?
                ORDER BY created_at DESC, token DESC
                LIMIT -1 OFFSET ?
            )
            """,
            (user_id, SESSION_MAX_PER_USER),
        )

    conn.execute(
        """
        DELETE FROM sessions
        WHERE token IN (
            SELECT token
            FROM sessions
            ORDER BY created_at DESC, token DESC
            LIMIT -1 OFFSET ?
        )
        """,
        (SESSION_ROW_LIMIT,),
    )


AUDIT_EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,63}$")


def prune_audit_events(conn: sqlite3.Connection) -> None:
    cutoff = (
        datetime.now(timezone.utc).replace(microsecond=0)
        - timedelta(days=AUDIT_RETENTION_DAYS)
    ).isoformat()
    conn.execute("DELETE FROM audit_events WHERE created_at < ?", (cutoff,))
    conn.execute(
        """
        DELETE FROM audit_events
        WHERE id IN (
            SELECT id
            FROM audit_events
            ORDER BY created_at DESC, id DESC
            LIMIT -1 OFFSET ?
        )
        """,
        (AUDIT_ROW_LIMIT,),
    )


def record_audit_event(
    conn: sqlite3.Connection,
    event_type: str,
    *,
    actor_user_id: int | None = None,
    target_user_id: int | None = None,
    client_ip: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    """Persist a bounded, secret-free security event in the caller's transaction."""
    if not AUDIT_EVENT_TYPE_RE.fullmatch(event_type):
        raise ValueError(f"Invalid audit event type: {event_type!r}")
    details_json = json.dumps(
        details or {},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(details_json) > 4096:
        raise ValueError("Audit event details exceed 4096 characters.")
    conn.execute(
        """
        INSERT INTO audit_events (
            event_type, actor_user_id, target_user_id, client_ip,
            details_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            event_type,
            actor_user_id,
            target_user_id,
            str(client_ip).strip()[:64],
            details_json,
            utc_now(),
        ),
    )
    prune_audit_events(conn)


def is_username_unique_conflict(error: sqlite3.IntegrityError) -> bool:
    message = str(error).casefold()
    expected_target = (
        "idx_users_username_lower" in message
        or "users.username" in message
    )
    if not expected_target:
        return False
    error_code = getattr(error, "sqlite_errorcode", None)
    return error_code in {
        None,
        getattr(sqlite3, "SQLITE_CONSTRAINT_UNIQUE", 2067),
    }


def current_user(conn: sqlite3.Connection, token: str | None) -> sqlite3.Row | None:
    if token is None or not token or len(token) > 256:
        return None

    now = utc_now()
    return conn.execute(
        """
        SELECT users.*
        FROM sessions
        JOIN users ON users.id = sessions.user_id
        WHERE sessions.token = ? AND sessions.expires_at > ?
        """,
        (session_token_digest(token), now),
    ).fetchone()


def normalized_login_username(username: str) -> str:
    value = username.strip().casefold()
    return value if USERNAME_RE.fullmatch(value) else "<invalid>"


def normalized_login_ip(client_ip: str) -> str:
    try:
        return str(ipaddress.ip_address(client_ip))
    except ValueError:
        return "<unknown>"


def login_attempt_keys(username: str, client_ip: str) -> tuple[str, str]:
    normalized_ip = normalized_login_ip(client_ip)
    return (
        f"account:{normalized_login_username(username)}|ip:{normalized_ip}",
        f"ip:{normalized_ip}",
    )


def prune_login_attempts_locked(now: float) -> None:
    cutoff = now - LOGIN_WINDOW_SECONDS
    for key, (failures, locked_until) in list(LOGIN_ATTEMPTS.items()):
        while failures and failures[0] < cutoff:
            failures.popleft()
        if not failures and locked_until <= now:
            LOGIN_ATTEMPTS.pop(key, None)

    overflow = len(LOGIN_ATTEMPTS) - LOGIN_ATTEMPT_BUCKET_LIMIT
    if overflow > 0:
        oldest_keys = sorted(
            LOGIN_ATTEMPTS,
            key=lambda key: (
                LOGIN_ATTEMPTS[key][0][-1] if LOGIN_ATTEMPTS[key][0] else 0.0
            ),
        )[:overflow]
        for key in oldest_keys:
            LOGIN_ATTEMPTS.pop(key, None)


def is_login_locked(username: str, client_ip: str) -> bool:
    now = time.time()

    with LOGIN_ATTEMPTS_LOCK:
        prune_login_attempts_locked(now)
        return any(
            (attempts := LOGIN_ATTEMPTS.get(key)) is not None
            and attempts[1] > now
            for key in login_attempt_keys(username, client_ip)
        )


def record_login_failure(username: str, client_ip: str) -> None:
    now = time.time()

    with LOGIN_ATTEMPTS_LOCK:
        prune_login_attempts_locked(now)
        for key in login_attempt_keys(username, client_ip):
            failures, locked_until = LOGIN_ATTEMPTS.get(key, (deque(), 0.0))
            failures.append(now)
            if len(failures) >= LOGIN_MAX_FAILURES:
                locked_until = max(locked_until, now + LOGIN_LOCKOUT_SECONDS)
            LOGIN_ATTEMPTS[key] = failures, locked_until
        prune_login_attempts_locked(now)


def clear_login_failures(username: str, client_ip: str) -> None:
    with LOGIN_ATTEMPTS_LOCK:
        account_key, ip_key = login_attempt_keys(username, client_ip)
        LOGIN_ATTEMPTS.pop(account_key, None)
        LOGIN_ATTEMPTS.pop(ip_key, None)


def ensure_daily_game(conn: sqlite3.Connection) -> sqlite3.Row:
    game_date = today_game_date()
    game = conn.execute(
        "SELECT * FROM daily_wordle_games WHERE game_date = ?",
        (game_date,),
    ).fetchone()
    if game is not None:
        return game

    words = load_answer_words()
    cycle = conn.execute(
        "SELECT COALESCE(MAX(cycle), 1) AS cycle FROM daily_wordle_games"
    ).fetchone()["cycle"]
    used_words = {
        row["secret_word"]
        for row in conn.execute(
            "SELECT secret_word FROM daily_wordle_games WHERE cycle = ?",
            (cycle,),
        )
    }
    if len(used_words) >= len(words):
        cycle += 1
        used_words = set()
        reset_used_words()

    secret_word = choose_secret(words, used_words, include_local_used=False)
    now = utc_now()

    cursor = conn.execute(
        """
        INSERT INTO daily_wordle_games (game_date, secret_word, cycle, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(game_date) DO NOTHING
        """,
        (game_date, secret_word, cycle, now),
    )
    if cursor.rowcount == 1:
        game_id = cursor.lastrowid
        conn.execute(
            """
            INSERT INTO wordle_used_words (word, game_id, used_on, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (secret_word, game_id, game_date, now),
        )

    return conn.execute(
        "SELECT * FROM daily_wordle_games WHERE game_date = ?",
        (game_date,),
    ).fetchone()


def wordle_assignment_row(
    conn: sqlite3.Connection,
    user_id: int,
    game_id: int,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM wordle_user_assignments
        WHERE user_id = ? AND game_id = ?
        """,
        (user_id, game_id),
    ).fetchone()


def existing_wordle_result(
    conn: sqlite3.Connection,
    user_id: int,
    game_id: int,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM wordle_results
        WHERE user_id = ? AND game_id = ?
        """,
        (user_id, game_id),
    ).fetchone()


def get_or_create_wordle_result(
    conn: sqlite3.Connection,
    user_id: int,
    game_id: int,
) -> sqlite3.Row:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO wordle_results
            (user_id, game_id, status, attempts_used, created_at, updated_at)
        VALUES (?, ?, 'in_progress', 0, ?, ?)
        ON CONFLICT(user_id, game_id) DO NOTHING
        """,
        (user_id, game_id, now, now),
    )
    return conn.execute(
        """
        SELECT * FROM wordle_results
        WHERE user_id = ? AND game_id = ?
        """,
        (user_id, game_id),
    ).fetchone()


def wordle_result_outcomes(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    before_date: str | None = None,
) -> list[tuple[str, str]]:
    where = ["wordle_results.user_id = ?", "wordle_results.status IN ('won', 'lost')"]
    params: list[Any] = [user_id]
    if before_date is not None:
        where.append("daily_wordle_games.game_date < ?")
        params.append(before_date)

    rows = conn.execute(
        f"""
        SELECT daily_wordle_games.game_date, wordle_results.status
        FROM wordle_results
        INNER JOIN daily_wordle_games ON daily_wordle_games.id = wordle_results.game_id
        WHERE {' AND '.join(where)}
        ORDER BY daily_wordle_games.game_date
        """,
        params,
    ).fetchall()
    return [(row["game_date"], row["status"]) for row in rows]


def score_wordle_solve_streak(
    outcomes: list[tuple[str, str]],
    current_date: str | None = None,
) -> dict[str, int]:
    if not outcomes:
        return {"current": 0, "best": 0}

    ordered_outcomes: list[tuple[date, str]] = []
    for date_value, status in outcomes:
        if status not in {"won", "lost"}:
            continue
        try:
            day = datetime.strptime(date_value, "%Y-%m-%d").date()
        except ValueError:
            continue
        ordered_outcomes.append((day, status))

    if not ordered_outcomes:
        return {"current": 0, "best": 0}

    ordered_outcomes.sort(key=lambda item: item[0])
    status_by_day = {day: status for day, status in ordered_outcomes}

    best = 0
    run = 0
    previous_day: date | None = None
    for day, status in ordered_outcomes:
        if status == "won":
            run = run + 1 if previous_day == day - timedelta(days=1) and run > 0 else 1
            best = max(best, run)
        else:
            run = 0
        previous_day = day

    reference_date = current_date or today_game_date()
    try:
        reference_day = datetime.strptime(reference_date, "%Y-%m-%d").date()
    except ValueError:
        reference_day = ordered_outcomes[-1][0]

    latest_day = ordered_outcomes[-1][0]
    if latest_day < reference_day - timedelta(days=1):
        return {"current": 0, "best": best}

    current = 0
    day = reference_day
    if day not in status_by_day:
        day -= timedelta(days=1)

    while status_by_day.get(day) == "won":
        current += 1
        day -= timedelta(days=1)

    return {"current": current, "best": best}


def user_wordle_solve_streak(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    current_date: str | None = None,
    before_date: str | None = None,
) -> dict[str, int]:
    return score_wordle_solve_streak(
        wordle_result_outcomes(conn, user_id, before_date=before_date),
        current_date=current_date,
    )


def score_wordle_level_progress(outcomes: list[tuple[str, str]]) -> dict[str, int]:
    if not outcomes:
        return {"current": 0, "best": 0}

    ordered_outcomes: list[tuple[date, str]] = []
    for date_value, status in outcomes:
        if status not in {"won", "lost"}:
            continue
        try:
            day = datetime.strptime(date_value, "%Y-%m-%d").date()
        except ValueError:
            continue
        ordered_outcomes.append((day, status))

    if not ordered_outcomes:
        return {"current": 0, "best": 0}

    ordered_outcomes.sort(key=lambda item: item[0])
    best = 0
    run = 0
    for _day, status in ordered_outcomes:
        if status == "won":
            run += 1
            best = max(best, run)
        else:
            run = 0

    return {"current": run, "best": best}


def user_wordle_level_progress(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    before_date: str | None = None,
) -> dict[str, int]:
    return score_wordle_level_progress(
        wordle_result_outcomes(conn, user_id, before_date=before_date),
    )


def ensure_wordle_assignment(
    conn: sqlite3.Connection,
    user_id: int,
    game: sqlite3.Row,
) -> sqlite3.Row:
    progress = user_wordle_level_progress(
        conn,
        user_id,
        before_date=game["game_date"],
    )["current"]
    target_difficulty = difficulty_for_streak(progress)
    assignment = wordle_assignment_row(conn, user_id, game["id"])
    if assignment is not None:
        existing_result = existing_wordle_result(conn, user_id, game["id"])
        has_guesses = (
            existing_result is not None
            and conn.execute(
                "SELECT 1 FROM wordle_guesses WHERE result_id = ? LIMIT 1",
                (existing_result["id"],),
            ).fetchone()
            is not None
        )
        can_refresh_assignment = (
            existing_result is None
            or (
                existing_result["status"] == "in_progress"
                and existing_result["attempts_used"] == 0
                and not has_guesses
            )
        )
        if can_refresh_assignment and assignment["difficulty"] < target_difficulty:
            used_words = {
                row["secret_word"]
                for row in conn.execute(
                    """
                    SELECT secret_word
                    FROM wordle_user_assignments
                    WHERE user_id = ? AND game_id != ?
                    """,
                    (user_id, game["id"]),
                )
            }
            secret_word, actual_difficulty = choose_secret_for_difficulty(
                target_difficulty,
                used_words,
            )
            conn.execute(
                """
                UPDATE wordle_user_assignments
                SET secret_word = ?, difficulty = ?
                WHERE id = ?
                """,
                (secret_word, actual_difficulty, assignment["id"]),
            )
            assignment = wordle_assignment_row(conn, user_id, game["id"])
        return assignment

    existing_result = existing_wordle_result(conn, user_id, game["id"])
    legacy_secret_word = None
    if (
        existing_result is not None
        and (
            existing_result["status"] != "in_progress"
            or existing_result["attempts_used"] > 0
        )
    ):
        legacy_secret_word = str(game["secret_word"]).strip().lower()

    if legacy_secret_word is not None:
        actual_difficulty = load_word_difficulty_ratings().get(
            legacy_secret_word,
            target_difficulty,
        )
        secret_word = legacy_secret_word
    else:
        used_words = {
            row["secret_word"]
            for row in conn.execute(
                """
                SELECT secret_word
                FROM wordle_user_assignments
                WHERE user_id = ?
                """,
                (user_id,),
            )
        }
        secret_word, actual_difficulty = choose_secret_for_difficulty(
            target_difficulty,
            used_words,
        )

    now = utc_now()
    conn.execute(
        """
        INSERT INTO wordle_user_assignments
            (user_id, game_id, secret_word, difficulty, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, game_id) DO NOTHING
        """,
        (user_id, game["id"], secret_word, actual_difficulty, now),
    )

    assignment = wordle_assignment_row(conn, user_id, game["id"])
    if assignment is None:
        raise LookupError("Wordle assignment could not be created.")
    return assignment


def wordle_difficulty_bonus(difficulty: int) -> int:
    try:
        level = int(difficulty)
    except (TypeError, ValueError):
        level = 1
    normalized_level = max(1, min(20, level))
    return (normalized_level - 1) * WORDLE_DIFFICULTY_BONUS_PER_LEVEL


def wordle_score(status: str, attempts_used: int, difficulty: int = 1) -> int:
    if status != "won":
        return 0
    base_score = WORDLE_POINTS_BY_ATTEMPT.get(attempts_used, 0)
    return base_score + wordle_difficulty_bonus(difficulty) if base_score > 0 else 0


def backfill_wordle_scores(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT
            wordle_results.id,
            wordle_results.status,
            wordle_results.attempts_used,
            wordle_results.score,
            COALESCE(wordle_user_assignments.difficulty, 1) AS difficulty
        FROM wordle_results
        LEFT JOIN wordle_user_assignments
            ON wordle_user_assignments.user_id = wordle_results.user_id
            AND wordle_user_assignments.game_id = wordle_results.game_id
        WHERE status != 'in_progress'
        """
    ).fetchall()
    for row in rows:
        next_score = wordle_score(row["status"], row["attempts_used"], row["difficulty"])
        if row["score"] != next_score:
            conn.execute("UPDATE wordle_results SET score = ? WHERE id = ?", (next_score, row["id"]))


def backfill_wordle_assignment_difficulties(conn: sqlite3.Connection) -> None:
    ratings = load_word_difficulty_ratings()
    rows = conn.execute(
        """
        SELECT id, secret_word, difficulty
        FROM wordle_user_assignments
        """
    ).fetchall()
    for row in rows:
        difficulty = ratings.get(str(row["secret_word"]).strip().lower())
        if difficulty is not None and row["difficulty"] != difficulty:
            conn.execute(
                "UPDATE wordle_user_assignments SET difficulty = ? WHERE id = ?",
                (difficulty, row["id"]),
            )


def wordle_stats(conn: sqlite3.Connection, user_id: int) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT
            SUM(CASE WHEN status IN ('won', 'lost') THEN 1 ELSE 0 END) AS played,
            SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN status = 'lost' THEN 1 ELSE 0 END) AS losses,
            SUM(score) AS points
        FROM wordle_results
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()
    streak = user_wordle_solve_streak(conn, user_id)
    return {
        "played": row["played"] or 0,
        "wins": row["wins"] or 0,
        "losses": row["losses"] or 0,
        "points": row["points"] or 0,
        "currentSolveStreak": streak["current"],
        "bestSolveStreak": streak["best"],
    }


def serialize_wordle_state(
    conn: sqlite3.Connection,
    user_id: int,
    game: sqlite3.Row,
) -> dict[str, Any]:
    assignment = ensure_wordle_assignment(conn, user_id, game)
    result = get_or_create_wordle_result(conn, user_id, game["id"])
    return build_wordle_state(conn, user_id, game, assignment, result)


def build_wordle_state(
    conn: sqlite3.Connection,
    user_id: int,
    game: sqlite3.Row,
    assignment: sqlite3.Row,
    result: sqlite3.Row,
) -> dict[str, Any]:
    """Serialize already-existing Wordle rows without mutating a GET request."""
    guesses = [
        {
            "attemptNumber": row["attempt_number"],
            "guess": row["guess"],
            "feedback": json.loads(row["feedback_json"]),
        }
        for row in conn.execute(
            """
            SELECT attempt_number, guess, feedback_json
            FROM wordle_guesses
            WHERE result_id = ?
            ORDER BY attempt_number
            """,
            (result["id"],),
        )
    ]
    status = result["status"]

    return {
        "game": {
            "date": game["game_date"],
            "wordLength": WORD_LENGTH,
            "maxAttempts": MAX_ATTEMPTS,
            "difficulty": assignment["difficulty"],
        },
        "result": {
            "status": status,
            "attemptsUsed": result["attempts_used"],
            "score": result["score"],
            "guesses": guesses,
            "answer": assignment["secret_word"] if status != "in_progress" else None,
        },
        "stats": wordle_stats(conn, user_id),
    }


def existing_wordle_state(
    conn: sqlite3.Connection,
    user_id: int,
    game: sqlite3.Row,
) -> dict[str, Any] | None:
    assignment = wordle_assignment_row(conn, user_id, game["id"])
    result = existing_wordle_result(conn, user_id, game["id"])
    if assignment is None or result is None:
        return None
    return build_wordle_state(conn, user_id, game, assignment, result)


@contextmanager
def sqlite_immediate_transaction(conn: sqlite3.Connection) -> Any:
    """Serialize a write while remaining safe inside an existing transaction."""
    owns_transaction = not conn.in_transaction
    savepoint = (
        f"wordle_guess_{threading.get_ident()}_{time.monotonic_ns()}"
        if not owns_transaction
        else ""
    )
    if owns_transaction:
        conn.execute("BEGIN IMMEDIATE")
    else:
        conn.execute(f'SAVEPOINT "{savepoint}"')
    try:
        yield
    except BaseException:
        if owns_transaction:
            conn.rollback()
        else:
            conn.execute(f'ROLLBACK TO SAVEPOINT "{savepoint}"')
            conn.execute(f'RELEASE SAVEPOINT "{savepoint}"')
        raise
    else:
        if owns_transaction:
            conn.commit()
        else:
            conn.execute(f'RELEASE SAVEPOINT "{savepoint}"')


def is_wordle_attempt_unique_conflict(error: sqlite3.IntegrityError) -> bool:
    message = str(error).casefold()
    expected_target = (
        "wordle_guesses.result_id" in message
        and "wordle_guesses.attempt_number" in message
    )
    if not expected_target:
        return False
    return getattr(error, "sqlite_errorcode", None) in {
        None,
        getattr(sqlite3, "SQLITE_CONSTRAINT_UNIQUE", 2067),
    }


def submit_wordle_guess(
    conn: sqlite3.Connection,
    user_id: int,
    guess: str,
    expected_attempts_used: Any,
    expected_game_date: Any,
) -> tuple[dict[str, Any], int]:
    """Apply one idempotent, compare-and-swap Wordle guess."""
    if type(expected_attempts_used) is not int or not (
        0 <= expected_attempts_used <= MAX_ATTEMPTS
    ):
        return (
            {"error": f"expectedAttemptsUsed must be an integer from 0 to {MAX_ATTEMPTS}."},
            HTTPStatus.BAD_REQUEST,
        )

    if not isinstance(expected_game_date, str):
        return (
            {"error": "expectedGameDate must be a date in YYYY-MM-DD format."},
            HTTPStatus.BAD_REQUEST,
        )
    try:
        normalized_expected_game_date = date.fromisoformat(expected_game_date).isoformat()
    except ValueError:
        return (
            {"error": "expectedGameDate must be a date in YYYY-MM-DD format."},
            HTTPStatus.BAD_REQUEST,
        )
    if normalized_expected_game_date != expected_game_date:
        return (
            {"error": "expectedGameDate must be a date in YYYY-MM-DD format."},
            HTTPStatus.BAD_REQUEST,
        )

    with sqlite_immediate_transaction(conn):
        game = ensure_daily_game(conn)
        if game["game_date"] != expected_game_date:
            return (
                {
                    "error": (
                        "The Wordle day changed before this guess was saved. "
                        "Refresh the game and try again."
                    )
                },
                HTTPStatus.CONFLICT,
            )
        assignment = ensure_wordle_assignment(conn, user_id, game)
        result = get_or_create_wordle_result(conn, user_id, game["id"])

        if result["status"] != "in_progress":
            return (
                build_wordle_state(conn, user_id, game, assignment, result),
                HTTPStatus.OK,
            )

        requested_attempt = expected_attempts_used + 1
        existing_attempt = conn.execute(
            """
            SELECT guess
            FROM wordle_guesses
            WHERE result_id = ? AND attempt_number = ?
            """,
            (result["id"], requested_attempt),
        ).fetchone()
        if existing_attempt is not None:
            if existing_attempt["guess"] == guess:
                current_result = existing_wordle_result(conn, user_id, game["id"])
                return (
                    build_wordle_state(
                        conn,
                        user_id,
                        game,
                        assignment,
                        current_result,
                    ),
                    HTTPStatus.OK,
                )
            return (
                {
                    "error": (
                        "This Wordle attempt has already been used. "
                        "Refresh the game before guessing again."
                    )
                },
                HTTPStatus.CONFLICT,
            )

        if result["attempts_used"] != expected_attempts_used:
            return (
                {
                    "error": (
                        "The Wordle game changed before this guess was saved. "
                        "Refresh the game and try again."
                    )
                },
                HTTPStatus.CONFLICT,
            )

        if requested_attempt > MAX_ATTEMPTS:
            return ({"error": "No attempts remain."}, HTTPStatus.BAD_REQUEST)

        feedback = serialize_feedback(compute_feedback(assignment["secret_word"], guess))
        won = all(tile["color"] == "green" for tile in feedback)
        status = (
            "won"
            if won
            else "lost"
            if requested_attempt >= MAX_ATTEMPTS
            else "in_progress"
        )
        now = utc_now()
        completed_at = now if status != "in_progress" else None
        score = wordle_score(status, requested_attempt, assignment["difficulty"])

        try:
            conn.execute(
                """
                INSERT INTO wordle_guesses
                    (result_id, attempt_number, guess, feedback_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    result["id"],
                    requested_attempt,
                    guess,
                    json.dumps(feedback),
                    now,
                ),
            )
        except sqlite3.IntegrityError as error:
            if not is_wordle_attempt_unique_conflict(error):
                raise
            conflicting_attempt = conn.execute(
                """
                SELECT guess
                FROM wordle_guesses
                WHERE result_id = ? AND attempt_number = ?
                """,
                (result["id"], requested_attempt),
            ).fetchone()
            if conflicting_attempt is None or conflicting_attempt["guess"] != guess:
                return (
                    {"error": "This Wordle attempt has already been used."},
                    HTTPStatus.CONFLICT,
                )
            current_result = existing_wordle_result(conn, user_id, game["id"])
            return (
                build_wordle_state(
                    conn,
                    user_id,
                    game,
                    assignment,
                    current_result,
                ),
                HTTPStatus.OK,
            )

        updated = conn.execute(
            """
            UPDATE wordle_results
            SET status = ?, attempts_used = ?, score = ?, completed_at = ?, updated_at = ?
            WHERE id = ? AND status = 'in_progress' AND attempts_used = ?
            """,
            (
                status,
                requested_attempt,
                score,
                completed_at,
                now,
                result["id"],
                expected_attempts_used,
            ),
        )
        if updated.rowcount != 1:
            raise RuntimeError("Wordle result changed during a serialized guess.")

        updated_result = existing_wordle_result(conn, user_id, game["id"])
        if updated_result is None:
            raise RuntimeError("Wordle result disappeared after saving a guess.")
        return (
            build_wordle_state(conn, user_id, game, assignment, updated_result),
            HTTPStatus.OK,
        )


def word_definition_payload(
    normalized_word: str,
    definitions: list[dict[str, str | None]],
    source_url: str,
) -> dict[str, Any] | None:
    if not definitions:
        return None
    first_definition = definitions[0]
    return {
        "word": normalized_word,
        "definition": first_definition["definition"],
        "partOfSpeech": first_definition.get("partOfSpeech"),
        "definitions": definitions,
        "sourceUrl": source_url,
    }


def word_definition_from_dictionary_api(normalized_word: str) -> dict[str, Any] | None:
    request = Request(
        f"https://api.dictionaryapi.dev/api/v2/entries/en/{quote(normalized_word, safe='')}",
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": NEWS_USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=WORD_DEFINITION_TIMEOUT_SEC) as response:
            body, charset = read_bounded_response(
                response,
                max_bytes=512_000,
                label="Dictionary API",
            )
            payload = json.loads(body.decode(charset))
    except Exception:
        return None

    if not isinstance(payload, list):
        return None

    collected_definitions: list[dict[str, str | None]] = []
    seen_definitions: set[str] = set()
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        meanings = entry.get("meanings")
        if not isinstance(meanings, list):
            continue
        for meaning in meanings:
            if not isinstance(meaning, dict):
                continue
            part_of_speech = str(meaning.get("partOfSpeech") or "").strip() or None
            definitions = meaning.get("definitions")
            if not isinstance(definitions, list):
                continue
            for definition_entry in definitions:
                if not isinstance(definition_entry, dict):
                    continue
                definition = str(definition_entry.get("definition") or "").strip()
                if not definition:
                    continue
                definition_key = definition.casefold()
                if definition_key in seen_definitions:
                    continue
                seen_definitions.add(definition_key)
                collected_definitions.append(
                    {
                        "definition": definition,
                        "partOfSpeech": part_of_speech,
                    }
                )
                if len(collected_definitions) >= 3:
                    return word_definition_payload(
                        normalized_word,
                        collected_definitions,
                        "https://dictionaryapi.dev/",
                    )
    return word_definition_payload(
        normalized_word,
        collected_definitions,
        "https://dictionaryapi.dev/",
    )


def strip_wiktionary_markup(value: str) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"<ref[^>]*>.*?</ref>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"\{\{[^{}]*\}\}", " ", text)
    text = re.sub(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]", r"\1", text)
    text = re.sub(
        r"\[https?://[^\s\]]+(?:\s+([^\]]+))?\]",
        lambda match: match.group(1) or "",
        text,
    )
    text = text.replace("'''", " ").replace("''", " ")
    text = re.sub(r"^[#*:;]+\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" ,;:-")


def extract_wiktionary_section(
    wikitext: str,
    *section_names: str,
) -> tuple[str | None, str | None]:
    wanted = {section.casefold() for section in section_names if section.strip()}
    headers = list(re.finditer(r"(?m)^==[^=].*?==\s*$", wikitext))
    for index, header_match in enumerate(headers):
        header = re.sub(r"^==\s*|\s*==\s*$", "", header_match.group(0)).strip().casefold()
        if header not in wanted:
            continue
        start = header_match.end()
        end = headers[index + 1].start() if index + 1 < len(headers) else len(wikitext)
        section = wikitext[start:end].strip()
        return (section or None), header
    return None, None


def fetch_json_url(url: str, timeout: int | None = None) -> dict[str, Any]:
    """Fetch a JSON object for non-retired shared integrations such as Wiktionary."""
    request = Request(
        url,
        headers={"Accept-Encoding": "identity", "User-Agent": NEWS_USER_AGENT},
    )
    with urlopen(request, timeout=timeout or WORD_DEFINITION_TIMEOUT_SEC) as response:
        body, charset = read_bounded_response(
            response,
            max_bytes=1_000_000,
            label="Wiktionary",
        )
        payload = json.loads(body.decode(charset))
    return payload if isinstance(payload, dict) else {}


def word_definition_from_wiktionary(normalized_word: str) -> dict[str, Any] | None:
    try:
        payload = fetch_json_url(
            "https://en.wiktionary.org/w/api.php"
            f"?action=parse&page={quote(normalized_word, safe='')}"
            "&prop=wikitext&format=json&formatversion=2&redirects=1"
        )
    except Exception:
        return None

    parse_payload = payload.get("parse", {})
    if not isinstance(parse_payload, dict):
        return None
    wikitext = parse_payload.get("wikitext")
    if not isinstance(wikitext, str) or not wikitext.strip():
        return None

    definition_section, _section_name = extract_wiktionary_section(wikitext, "English", "Scots")
    if not definition_section:
        return None

    supported_parts_of_speech = {
        "noun",
        "verb",
        "adjective",
        "adverb",
        "pronoun",
        "proper noun",
        "preposition",
        "interjection",
        "determiner",
        "conjunction",
        "phrase",
        "proverb",
        "abbreviation",
        "article",
        "letter",
        "suffix",
        "prefix",
    }
    collected_definitions: list[dict[str, str | None]] = []
    seen_definitions: set[str] = set()
    part_of_speech: str | None = None
    for raw_line in definition_section.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading_match = re.match(r"^===+\s*([^=]+?)\s*===+$", line)
        if heading_match:
            heading = re.sub(r"\s+", " ", heading_match.group(1).strip()).casefold()
            part_of_speech = heading if heading in supported_parts_of_speech else None
            continue
        if not line.startswith("#") or line.startswith(("#:", "#*", "#;")):
            continue
        definition = strip_wiktionary_markup(line)
        if not definition:
            continue
        definition_key = definition.casefold()
        if definition_key in seen_definitions:
            continue
        seen_definitions.add(definition_key)
        collected_definitions.append(
            {
                "definition": definition,
                "partOfSpeech": part_of_speech,
            }
        )
        if len(collected_definitions) >= 3:
            break
    return word_definition_payload(
        normalized_word,
        collected_definitions,
        f"https://en.wiktionary.org/wiki/{quote(normalized_word, safe='')}",
    )


def word_definition(word: str) -> dict[str, Any]:
    normalized_word = re.sub(r"[^a-z]", "", word.casefold())
    with WORD_DEFINITION_CACHE_LOCK:
        cached = WORD_DEFINITION_CACHE.pop(normalized_word, None)
        if cached is not None:
            WORD_DEFINITION_CACHE[normalized_word] = cached
            return cached

    empty_result = {
        "word": normalized_word,
        "definition": None,
        "partOfSpeech": None,
        "definitions": [],
        "sourceUrl": "https://dictionaryapi.dev/",
    }
    if not normalized_word:
        return empty_result

    result = word_definition_from_dictionary_api(normalized_word)
    if result is None:
        result = word_definition_from_wiktionary(normalized_word)
    if result is None:
        result = empty_result

    with WORD_DEFINITION_CACHE_LOCK:
        WORD_DEFINITION_CACHE[normalized_word] = result
        while len(WORD_DEFINITION_CACHE) > WORD_DEFINITION_CACHE_MAX_ENTRIES:
            oldest_key = next(iter(WORD_DEFINITION_CACHE))
            WORD_DEFINITION_CACHE.pop(oldest_key, None)
    return result



def score_quiz_adjudications(
    questions: list[dict[str, Any]],
    adjudications: list[dict[str, Any]],
) -> dict[str, int]:
    score = 0
    max_score = 0
    correct_count = 0
    for index, question in enumerate(questions):
        points = QUIZ_POINTS_BY_DIFFICULTY.get(str(question.get("difficulty", "")), 0)
        max_score += points
        if index < len(adjudications) and adjudications[index].get("correct") is True:
            score += points
            correct_count += 1
    bonus_points = (
        QUIZ_PERFECT_ROUND_BONUS
        if questions and correct_count == len(questions)
        else 0
    )
    return {
        "score": score + bonus_points,
        "maxScore": max_score + QUIZ_PERFECT_ROUND_BONUS,
        "correctCount": correct_count,
        "bonusPoints": bonus_points,
    }


def quiz_content_version(questions: list[dict[str, Any]]) -> str:
    canonical = [
        {
            "id": int(question["id"]),
            "subject": str(question["subject"]),
            "difficulty": str(question["difficulty"]),
            "question": str(question["question"]),
            "choices": [str(choice) for choice in question["choices"]],
            "correctAnswer": str(question["correct_answer"]),
            "explanation": str(question["explanation"]),
        }
        for question in questions
    ]
    digest = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return f"quiz-v1-{digest}"


def serialize_quiz_result(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    adjudications: list[dict[str, Any]] = []
    if "adjudication_json" in keys:
        try:
            parsed = json.loads(row["adjudication_json"] or "[]")
        except (json.JSONDecodeError, TypeError):
            parsed = []
        if isinstance(parsed, list):
            adjudications = [dict(item) for item in parsed if isinstance(item, dict)]
            for item in adjudications:
                for field in ("correctAnswer", "explanation", "interestingReason"):
                    if field in item:
                        item[field] = daily_quiz.display_text(item[field])
    return {
        "date": row["game_date"],
        "category": row["category"],
        "score": row["score"],
        "maxScore": row["max_score"],
        "correctCount": row["correct_count"],
        "bonusPoints": row["bonus_points"],
        "quizVersion": row["quiz_version"] if "quiz_version" in keys else "legacy",
        "scoringVersion": (
            row["scoring_version"] if "scoring_version" in keys else "legacy"
        ),
        "adjudications": adjudications,
        "completedAt": row["completed_at"],
    }


def quiz_category_questions(
    conn: sqlite3.Connection,
    game_date: str,
    category: str,
) -> list[dict[str, Any]]:
    if category not in {"football", "general"}:
        raise ValueError("Quiz category must be football or general.")
    subject = "football" if category == "football" else "general_knowledge"
    payload = daily_quiz.quiz_questions_payload(conn, game_date)
    return [
        question
        for question in payload["questions"]
        if question["subject"] == subject
    ]


def adjudicate_quiz_answers(
    questions: list[dict[str, Any]],
    answers: list[Any],
) -> tuple[list[dict[str, str]], list[dict[str, Any]], dict[str, int]]:
    if len(answers) != len(questions):
        raise ValueError("Submit one answer for each quiz question.")
    submitted: dict[str, str] = {}
    for answer in answers:
        if not isinstance(answer, dict) or set(answer) != {"questionId", "choiceId"}:
            raise ValueError("Quiz answers must use question and choice IDs.")
        question_id = answer.get("questionId")
        choice_id = answer.get("choiceId")
        if (
            not isinstance(question_id, str)
            or not isinstance(choice_id, str)
            or not question_id
            or not choice_id
            or len(question_id) > QUIZ_PUBLIC_ID_MAX_LENGTH
            or len(choice_id) > QUIZ_PUBLIC_ID_MAX_LENGTH
        ):
            raise ValueError("Quiz question and choice IDs are invalid.")
        if question_id in submitted:
            raise ValueError("Each quiz question can only be answered once.")
        submitted[question_id] = choice_id

    normalized_answers: list[dict[str, str]] = []
    adjudications: list[dict[str, Any]] = []
    for question in questions:
        stored_question_id = int(question["id"])
        question_id = daily_quiz.public_question_id(stored_question_id)
        if question_id not in submitted:
            raise ValueError("Submit one answer for each quiz question.")
        choices = [str(choice) for choice in question.get("choices", [])]
        allowed_choices = {
            daily_quiz.public_choice_id(stored_question_id, index): (index, choice)
            for index, choice in enumerate(choices)
        }
        selected_choice_id = submitted[question_id]
        selected = allowed_choices.get(selected_choice_id)
        if selected is None:
            raise ValueError("A submitted choice does not belong to that quiz question.")
        correct_answer = str(question.get("correct_answer") or "")
        try:
            correct_index = choices.index(correct_answer)
        except ValueError as error:
            raise RuntimeError("Published quiz answer data is inconsistent.") from error
        correct_choice_id = daily_quiz.public_choice_id(stored_question_id, correct_index)
        points = QUIZ_POINTS_BY_DIFFICULTY.get(str(question.get("difficulty") or ""), 0)
        is_correct = selected_choice_id == correct_choice_id
        normalized_answers.append(
            {"questionId": question_id, "choiceId": selected_choice_id}
        )
        adjudications.append(
            {
                "questionId": question_id,
                "choiceId": selected_choice_id,
                "correct": is_correct,
                "correctChoiceId": correct_choice_id,
                "correctAnswer": daily_quiz.display_text(correct_answer),
                "explanation": daily_quiz.display_text(question.get("explanation") or ""),
                "interestingReason": daily_quiz.display_text(question.get("interesting_reason") or ""),
                "pointsAwarded": points if is_correct else 0,
            }
        )
    if len(submitted) != len(questions):
        raise ValueError("A submitted question does not belong to this quiz category.")
    return normalized_answers, adjudications, score_quiz_adjudications(questions, adjudications)


def daily_quiz_player_state(conn: sqlite3.Connection, user_id: int, game_date: str) -> dict[str, Any]:
    results = {
        row["category"]: serialize_quiz_result(row)
        for row in conn.execute(
            "SELECT * FROM daily_quiz_results WHERE user_id = ? AND game_date = ?",
            (user_id, game_date),
        )
    }
    progress = {
        row["category"]: json.loads(row["answers_json"])
        for row in conn.execute(
            "SELECT category, answers_json FROM daily_quiz_progress WHERE user_id = ? AND game_date = ?",
            (user_id, game_date),
        )
    }
    return {"results": results, "progress": progress}


def save_daily_quiz_progress(conn: sqlite3.Connection, user_id: int, game_date: str,
                             category: str, answers: Any) -> tuple[dict[str, Any], int]:
    if game_date != today_game_date() or category not in {"football", "general"}:
        return {"error": "Only today's football or general quiz can be saved."}, HTTPStatus.BAD_REQUEST
    if not isinstance(answers, list) or not 1 <= len(answers) <= 3:
        return {"error": "Send between one and three answers."}, HTTPStatus.BAD_REQUEST
    try:
        questions = quiz_category_questions(conn, game_date, category)
    except (LookupError, ValueError):
        return {"error": "Today's quiz is not available."}, HTTPStatus.NOT_FOUND
    if len(answers) > len(questions):
        return {"error": "Too many answers."}, HTTPStatus.BAD_REQUEST
    normalized = []
    for question, answer in zip(questions, answers):
        question_id = daily_quiz.public_question_id(int(question["id"]))
        choices = {daily_quiz.public_choice_id(int(question["id"]), index) for index in range(len(question["choices"]))}
        if (not isinstance(answer, dict) or set(answer) != {"questionId", "choiceId"}
                or answer.get("questionId") != question_id or not isinstance(answer.get("choiceId"), str)
                or answer["choiceId"] not in choices):
            return {"error": "Select a valid answer for each question in order."}, HTTPStatus.BAD_REQUEST
        normalized.append({"questionId": question_id, "choiceId": answer["choiceId"]})
    # Acquire the SQLite write lock before checking progress, including competing devices.
    conn.execute(
        "INSERT INTO daily_quiz_progress (user_id, game_date, category, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id, game_date, category) DO NOTHING", (user_id, game_date, category, utc_now()),
    )
    state = daily_quiz_player_state(conn, user_id, game_date)
    if category in state["results"]:
        return {"result": state["results"][category], "answers": state["progress"].get(category, [])}, HTTPStatus.OK
    stored = state["progress"].get(category, [])
    if normalized[:len(stored)] != stored:
        return {"error": "This round has advanced on another device. Refresh to resume your saved answers."}, HTTPStatus.CONFLICT
    conn.execute(
        "UPDATE daily_quiz_progress SET answers_json = ?, updated_at = ? "
        "WHERE user_id = ? AND game_date = ? AND category = ?",
        (json.dumps(normalized), utc_now(), user_id, game_date, category),
    )
    if len(normalized) == len(questions):
        payload, status = save_daily_quiz_result(conn, user_id, game_date, category, normalized)
        return {**payload, "answers": normalized}, status
    return {"answers": normalized}, HTTPStatus.OK


def save_daily_quiz_result(
    conn: sqlite3.Connection,
    user_id: int,
    game_date: str,
    category: str,
    answers: Any,
) -> tuple[dict[str, Any], int]:
    if game_date != today_game_date():
        return {"error": "Only today's quiz can be scored."}, HTTPStatus.BAD_REQUEST
    if category not in {"football", "general"}:
        return {
            "error": "Quiz category must be football or general."
        }, HTTPStatus.BAD_REQUEST
    if not isinstance(answers, list) or len(answers) > QUIZ_MAX_SUBMITTED_ANSWERS:
        return {"error": "Quiz answers must be a bounded list."}, HTTPStatus.BAD_REQUEST

    # Serialize direct final submissions with per-question progress on other devices.
    conn.execute(
        "INSERT INTO daily_quiz_progress (user_id, game_date, category, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id, game_date, category) DO NOTHING", (user_id, game_date, category, utc_now()),
    )

    existing = conn.execute(
        """
        SELECT *
        FROM daily_quiz_results
        WHERE user_id = ? AND game_date = ? AND category = ?
        """,
        (user_id, game_date, category),
    ).fetchone()
    if existing is not None:
        return {"result": serialize_quiz_result(existing)}, HTTPStatus.OK

    try:
        questions = quiz_category_questions(conn, game_date, category)
    except LookupError:
        return {"error": "Today's quiz is not available."}, HTTPStatus.NOT_FOUND
    try:
        normalized_answers, adjudications, totals = adjudicate_quiz_answers(
            questions, answers
        )
    except ValueError as error:
        return {"error": str(error)}, HTTPStatus.BAD_REQUEST
    progress = conn.execute(
        "SELECT answers_json FROM daily_quiz_progress WHERE user_id = ? AND game_date = ? AND category = ?",
        (user_id, game_date, category),
    ).fetchone()
    if progress is not None:
        locked_answers = json.loads(progress["answers_json"])
        if normalized_answers[:len(locked_answers)] != locked_answers:
            return {"error": "Saved answers cannot be changed. Refresh to resume this round."}, HTTPStatus.CONFLICT
    quiz_version = quiz_content_version(questions)
    now = utc_now()
    cursor = conn.execute(
        """
        INSERT INTO daily_quiz_results (
            user_id, game_date, category, answers_json, score, max_score,
            correct_count, bonus_points, quiz_version, scoring_version,
            adjudication_json, completed_at, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, game_date, category) DO NOTHING
        """,
        (
            user_id,
            game_date,
            category,
            json.dumps(normalized_answers, ensure_ascii=True, separators=(",", ":")),
            totals["score"],
            totals["maxScore"],
            totals["correctCount"],
            totals["bonusPoints"],
            quiz_version,
            QUIZ_SCORING_VERSION,
            json.dumps(adjudications, ensure_ascii=True, separators=(",", ":")),
            now,
            now,
            now,
        ),
    )

    result = conn.execute(
        """
        SELECT *
        FROM daily_quiz_results
        WHERE user_id = ? AND game_date = ? AND category = ?
        """,
        (user_id, game_date, category),
    ).fetchone()
    if result is None:
        raise RuntimeError("Quiz result could not be stored.")
    status = HTTPStatus.CREATED if cursor.rowcount == 1 else HTTPStatus.OK
    return {"result": serialize_quiz_result(result)}, status


def player_wordle_outcomes(conn: sqlite3.Connection) -> dict[int, list[tuple[str, str]]]:
    outcome_rows = conn.execute(
        """
        SELECT
            wordle_results.user_id,
            daily_wordle_games.game_date,
            wordle_results.status
        FROM wordle_results
        INNER JOIN daily_wordle_games ON daily_wordle_games.id = wordle_results.game_id
        WHERE wordle_results.status IN ('won', 'lost')
        """
    ).fetchall()
    outcomes_by_user: dict[int, list[tuple[str, str]]] = {}
    for row in outcome_rows:
        outcomes_by_user.setdefault(row["user_id"], []).append(
            (row["game_date"], row["status"])
        )

    return outcomes_by_user


def leaderboard_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    period_end = today_game_date()
    period_start = (
        datetime.strptime(period_end, "%Y-%m-%d").date() - timedelta(days=6)
    ).isoformat()
    map_period_start_utc, map_period_end_exclusive_utc = game_date_period_utc_bounds(
        period_start,
        period_end,
    )
    rows = conn.execute(
        """
        WITH wordle_scored_results AS (
            SELECT
                wordle_results.user_id,
                daily_wordle_games.game_date,
                wordle_results.status,
                wordle_results.score,
                CASE
                    WHEN wordle_results.status = 'won'
                        AND COALESCE(wordle_user_assignments.difficulty, 1) > 1
                    THEN (COALESCE(wordle_user_assignments.difficulty, 1) - 1) * ?
                    ELSE 0
                END AS difficulty_bonus
            FROM wordle_results
            INNER JOIN daily_wordle_games ON daily_wordle_games.id = wordle_results.game_id
            LEFT JOIN wordle_user_assignments
                ON wordle_user_assignments.user_id = wordle_results.user_id
                AND wordle_user_assignments.game_id = wordle_results.game_id
        ),
        wordle_scores AS (
            SELECT
                user_id,
                SUM(score) AS points,
                SUM(difficulty_bonus) AS difficulty_bonus,
                SUM(CASE WHEN status IN ('won', 'lost') THEN 1 ELSE 0 END) AS played,
                SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END) AS wins
            FROM wordle_scored_results
            GROUP BY user_id
        ),
        weekly_wordle_scores AS (
            SELECT
                user_id,
                SUM(score) AS points,
                SUM(difficulty_bonus) AS difficulty_bonus
            FROM wordle_scored_results
            WHERE game_date >= ? AND game_date <= ?
            GROUP BY user_id
        ),
        all_quiz_results AS (
            SELECT user_id, game_date, score, max_score, correct_count
            FROM daily_quiz_results
            UNION ALL
            SELECT user_id, game_date, score, max_score, correct_count
            FROM quiz_boards
            WHERE mode = 'daily' AND status = 'completed'
        ),
        quiz_scores AS (
            SELECT
                user_id,
                SUM(score) AS points,
                SUM(max_score) AS max_points,
                COUNT(*) AS played,
                SUM(correct_count) AS correct_count
            FROM all_quiz_results
            GROUP BY user_id
        ),
        weekly_quiz_scores AS (
            SELECT
                user_id,
                SUM(score) AS points
            FROM all_quiz_results
            WHERE game_date >= ? AND game_date <= ?
            GROUP BY user_id
        ),
        map_scores AS (
            SELECT
                user_id,
                SUM(score) AS points,
                COUNT(*) AS played
            FROM daily_map_guesses
            GROUP BY user_id
        ),
        weekly_map_scores AS (
            SELECT
                daily_map_guesses.user_id,
                SUM(daily_map_guesses.score) AS points
            FROM daily_map_guesses
            INNER JOIN daily_map_levels
                ON daily_map_levels.id = daily_map_guesses.level_id
            INNER JOIN daily_map_puzzles
                ON daily_map_puzzles.id = daily_map_levels.puzzle_id
            WHERE julianday(daily_map_guesses.completed_at) >= julianday(?)
                AND julianday(daily_map_guesses.completed_at) < julianday(?)
            GROUP BY daily_map_guesses.user_id
        )
        SELECT
            users.id,
            users.username,
            COALESCE(wordle_scores.points, 0) AS wordle_points,
            COALESCE(weekly_wordle_scores.points, 0) AS weekly_wordle_points,
            COALESCE(wordle_scores.difficulty_bonus, 0) AS wordle_difficulty_bonus,
            COALESCE(weekly_wordle_scores.difficulty_bonus, 0) AS weekly_wordle_difficulty_bonus,
            COALESCE(wordle_scores.played, 0) AS wordle_played,
            COALESCE(wordle_scores.wins, 0) AS wordle_wins,
            COALESCE(quiz_scores.points, 0) AS quiz_points,
            COALESCE(weekly_quiz_scores.points, 0) AS weekly_quiz_points,
            COALESCE(quiz_scores.max_points, 0) AS quiz_max_points,
            COALESCE(quiz_scores.played, 0) AS quiz_played,
            COALESCE(quiz_scores.correct_count, 0) AS quiz_correct,
            COALESCE(map_scores.points, 0) AS map_points,
            COALESCE(weekly_map_scores.points, 0) AS weekly_map_points,
            COALESCE(map_scores.played, 0) AS map_played
        FROM users
        LEFT JOIN wordle_scores ON wordle_scores.user_id = users.id
        LEFT JOIN weekly_wordle_scores ON weekly_wordle_scores.user_id = users.id
        LEFT JOIN quiz_scores ON quiz_scores.user_id = users.id
        LEFT JOIN weekly_quiz_scores ON weekly_quiz_scores.user_id = users.id
        LEFT JOIN map_scores ON map_scores.user_id = users.id
        LEFT JOIN weekly_map_scores ON weekly_map_scores.user_id = users.id
        ORDER BY
            (
                COALESCE(weekly_wordle_scores.points, 0)
                + COALESCE(weekly_quiz_scores.points, 0)
                + COALESCE(weekly_map_scores.points, 0)
            ) DESC,
            (
                COALESCE(wordle_scores.points, 0)
                + COALESCE(quiz_scores.points, 0)
                + COALESCE(map_scores.points, 0)
            ) DESC,
            COALESCE(wordle_scores.wins, 0) DESC,
            LOWER(users.username)
        """,
        (
            WORDLE_DIFFICULTY_BONUS_PER_LEVEL,
            period_start,
            period_end,
            period_start,
            period_end,
            map_period_start_utc,
            map_period_end_exclusive_utc,
        ),
    ).fetchall()

    outcomes_by_user = player_wordle_outcomes(conn)
    streaks = {
        user_id: score_wordle_solve_streak(outcomes)
        for user_id, outcomes in outcomes_by_user.items()
    }
    level_progress_by_user = {
        user_id: score_wordle_level_progress(outcomes)
        for user_id, outcomes in outcomes_by_user.items()
    }
    players = []
    for index, row in enumerate(rows):
        streak = streaks.get(row["id"], {"current": 0, "best": 0})
        level_progress = level_progress_by_user.get(row["id"], {"current": 0, "best": 0})
        players.append(
            {
                "rank": index + 1,
                "id": row["id"],
                "username": row["username"],
                "weeklyPoints": row["weekly_wordle_points"]
                + row["weekly_quiz_points"]
                + row["weekly_map_points"],
                "weeklyWordlePoints": row["weekly_wordle_points"],
                "weeklyQuizPoints": row["weekly_quiz_points"],
                "weeklyMapPoints": row["weekly_map_points"],
                "totalPoints": row["wordle_points"] + row["quiz_points"] + row["map_points"],
                "wordlePoints": row["wordle_points"],
                "weeklyWordleDifficultyBonus": row["weekly_wordle_difficulty_bonus"],
                "wordleDifficultyBonus": row["wordle_difficulty_bonus"],
                "wordlePlayed": row["wordle_played"],
                "wordleWins": row["wordle_wins"],
                "quizPoints": row["quiz_points"],
                "quizMaxPoints": row["quiz_max_points"],
                "quizPlayed": row["quiz_played"],
                "quizCorrect": row["quiz_correct"],
                "mapPoints": row["map_points"],
                "mapPlayed": row["map_played"],
                "currentStreak": streak["current"],
                "bestStreak": streak["best"],
                "wordleLevel": difficulty_for_streak(level_progress["current"]),
                "bestWordleLevel": difficulty_for_streak(level_progress["best"]),
            }
        )

    return {
        "players": players,
        "summary": {
            "periodStart": period_start,
            "periodEnd": period_end,
            "playerCount": len(players),
            "weeklyPoints": sum(player["weeklyPoints"] for player in players),
            "totalPoints": sum(player["totalPoints"] for player in players),
            "quizPlays": sum(player["quizPlayed"] for player in players),
            "wordlePlays": sum(player["wordlePlayed"] for player in players),
            "mapPlays": sum(player["mapPlayed"] for player in players),
            "bestStreak": max((player["bestStreak"] for player in players), default=0),
        },
    }


def serialize_news_item(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "sourceKey": row["source_key"],
        "kind": row["kind"],
        "title": row["title"],
        "url": row["url"],
        "source": row["source"],
        "summary": row["summary"],
        "publishedAt": row["published_at"],
        "host": row["host"],
        "priority": row["priority"],
        "tags": json.loads(row["tags_json"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def bounded_text(value: Any, max_length: int) -> str:
    text = str(value or "").strip()
    return text[:max_length]


def normalise_news_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def clean_news_title(title: str, source: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    source = re.sub(r"\s+", " ", source).strip()
    if not source:
        return title

    escaped_source = re.escape(source)
    return re.sub(
        rf"(?:\s+[-|:]\s+|\s+\(){escaped_source}\)?$",
        "",
        title,
        flags=re.IGNORECASE,
    ).strip()


def clean_news_summary(summary: str, title: str, source: str) -> str:
    summary = strip_html(summary)
    source = re.sub(r"\s+", " ", source).strip()
    if source:
        summary = re.sub(rf"\s+{re.escape(source)}$", "", summary, flags=re.IGNORECASE).strip()

    summary_key = normalise_news_text(summary)
    title_key = normalise_news_text(title)
    if not summary_key or summary_key == title_key:
        return ""
    if len(summary_key) >= 24 and (
        summary_key.startswith(title_key) or title_key.startswith(summary_key)
    ):
        return ""
    return summary


def news_story_key(title: str) -> str:
    title_key = normalise_news_text(title)
    return hashlib.sha256(title_key.encode("utf-8")).hexdigest() if title_key else ""


def news_titles_are_near_duplicates(left: str, right: str) -> bool:
    left_key = normalise_news_text(left)
    right_key = normalise_news_text(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    left_words = set(left_key.split())
    right_words = set(right_key.split())
    shorter_word_count = min(len(left_words), len(right_words))
    word_overlap = (
        len(left_words & right_words) / shorter_word_count
        if shorter_word_count
        else 0
    )
    return SequenceMatcher(None, left_key, right_key).ratio() >= 0.9 or word_overlap >= 0.75


def news_rows_are_near_duplicates(left: dict[str, Any], right: sqlite3.Row) -> bool:
    if left["source"].casefold() != str(right["source"]).casefold():
        return False
    if left["published_at"] != str(right["published_at"]):
        return False
    return news_titles_are_near_duplicates(left["title"], str(right["title"]))


def validate_news_payload(payload: dict[str, Any]) -> dict[str, Any]:
    source_key = bounded_text(payload.get("sourceKey"), 160)
    url = bounded_text(payload.get("url"), 600)
    source = bounded_text(payload.get("source"), 120) or "Unknown source"
    title = clean_news_title(bounded_text(payload.get("title"), 220), source)
    summary = clean_news_summary(bounded_text(payload.get("summary"), 500), title, source)
    host = bounded_text(payload.get("host"), 160)
    kind = bounded_text(payload.get("kind"), 40) or "article"
    published_at = bounded_text(payload.get("publishedAt"), 80) or utc_now()

    if not source_key:
        source_key = hashlib.sha256(url.encode("utf-8")).hexdigest() if url else ""
    if not source_key:
        raise ValueError("News item requires sourceKey or url.")
    if not title:
        raise ValueError("News item requires title.")
    if not url.startswith(("http://", "https://")):
        raise ValueError("News item requires an http or https url.")

    raw_tags = payload.get("tags", [])
    tags = raw_tags if isinstance(raw_tags, list) else []
    clean_tags = [bounded_text(tag, 40) for tag in tags if bounded_text(tag, 40)]
    priority, clean_tags = classify_news_item(title, summary, clean_tags)
    story_key = news_story_key(title)

    return {
        "source_key": source_key,
        "story_key": story_key,
        "kind": kind,
        "title": title,
        "url": url,
        "source": source,
        "summary": summary,
        "published_at": published_at,
        "host": host,
        "priority": priority,
        "tags_json": json.dumps(clean_tags[:8]),
    }


def upsert_news_item(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    item = validate_news_payload(payload)
    now = utc_now()
    existing = conn.execute(
        """
        SELECT *
        FROM news_items
        WHERE source_key = ? OR story_key = ?
        ORDER BY published_at DESC, id DESC
        LIMIT 1
        """,
        (item["source_key"], item["story_key"]),
    ).fetchone()
    if existing is None:
        recent_rows = conn.execute(
            """
            SELECT *
            FROM news_items
            ORDER BY published_at DESC, id DESC
            LIMIT 100
            """
        ).fetchall()
        existing = next(
            (row for row in recent_rows if news_rows_are_near_duplicates(item, row)),
            None,
        )

    if existing is not None and all(existing[key] == item[key] for key in (
        "kind", "title", "url", "source", "summary", "published_at", "host", "priority", "tags_json"
    )):
        return serialize_news_item(existing), False
    if existing is None:
        cursor = conn.execute(
            """
            INSERT INTO news_items (
                source_key, story_key, kind, title, url, source, summary, published_at,
                host, priority, tags_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["source_key"],
                item["story_key"],
                item["kind"],
                item["title"],
                item["url"],
                item["source"],
                item["summary"],
                item["published_at"],
                item["host"],
                item["priority"],
                item["tags_json"],
                now,
                now,
            ),
        )
        row_id = cursor.lastrowid
        inserted = True
    else:
        row_id = existing["id"]
        item_story_key = str(existing["story_key"] or item["story_key"])
        conn.execute(
            """
            UPDATE news_items
            SET story_key = ?, kind = ?, title = ?, url = ?, source = ?, summary = ?,
                published_at = ?, host = ?, priority = ?, tags_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                item_story_key,
                item["kind"],
                item["title"],
                item["url"],
                item["source"],
                item["summary"],
                item["published_at"],
                item["host"],
                item["priority"],
                item["tags_json"],
                now,
                row_id,
            ),
        )
        inserted = False

    row = conn.execute("SELECT * FROM news_items WHERE id = ?", (row_id,)).fetchone()
    return serialize_news_item(row), inserted


def list_news_items(
    conn: sqlite3.Connection,
    limit: int,
    category: str = "all",
) -> list[dict[str, Any]]:
    filters = {
        "breaking": "priority = 'breaking'",
        "live-scores": "priority = 'live-scores'",
        "news": "priority = 'news'",
    }
    where_clause = f"WHERE {filters[category]}" if category in filters else ""
    rows = conn.execute(
        f"""
        SELECT *
        FROM news_items
        {where_clause}
        ORDER BY published_at DESC, created_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [serialize_news_item(row) for row in rows]


def prune_news_items(conn: sqlite3.Connection) -> int:
    """Bound continuously ingested news by age and total row count."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=NEWS_RETENTION_DAYS)
    ).replace(microsecond=0).isoformat()
    before = conn.total_changes
    conn.execute("DELETE FROM news_items WHERE published_at < ?", (cutoff,))
    conn.execute(
        """
        DELETE FROM news_items
        WHERE id NOT IN (
            SELECT id
            FROM news_items
            ORDER BY published_at DESC, created_at DESC, id DESC
            LIMIT ?
        )
        """,
        (NEWS_ROW_LIMIT,),
    )
    return conn.total_changes - before


def broadcast_news_item(item: dict[str, Any]) -> None:
    with NEWS_STREAMS_LOCK:
        streams = list(NEWS_STREAMS)

    for stream in streams:
        try:
            stream.put_nowait(item)
        except queue.Full:
            pass


def contains_news_term(text: str, terms: tuple[str, ...]) -> bool:
    for term in terms:
        pattern = rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])"
        if re.search(pattern, text):
            return True
    return False


def classify_news_item(
    title: str,
    summary: str,
    tags: list[str],
) -> tuple[str, list[str]]:
    haystack = f"{title} {summary}".lower()
    clean_tags = [
        tag
        for tag in list(dict.fromkeys(tags))
        if tag not in {"breaking", "news", "live-scores"}
    ]

    live_score_terms = (
        "live score",
        "livescore",
        "live scores",
        "match centre",
        "match center",
        "fixtures",
        "results",
        "full-time",
        "half-time",
        "kick-off",
    )
    explicit_breaking_terms = (
        "breaking",
        "exclusive",
        "urgent",
        "just in",
        "developing",
    )
    high_impact_breaking_terms = (
        "sacked",
        "dismissed",
        "appointed",
        "resigns",
        "resigned",
        "dies",
        "died",
        "death",
        "postponed",
        "cancelled",
        "called off",
    )
    club_change_breaking_terms = (
        "leaves st mirren",
        "left st mirren",
        "exits st mirren",
        "joins st mirren",
        "joined st mirren",
        "st mirren appoint",
        "st mirren sign",
        "st mirren sack",
        "st mirren release",
        "st mirren name new",
        "new recruitment chief named",
        "new head of recruitment",
    )
    result_breaking_terms = (
        "secure premiership status",
        "secured premiership status",
        "remain in the premiership",
        "remains in the premiership",
        "staying in the premiership",
        "stayed in the premiership",
        "stay up",
        "stays up",
        "stayed up",
        "avoid relegation",
        "avoids relegation",
        "avoided relegation",
        "avoiding relegation",
        "survival secured",
        "premiership survival",
        "salvages positive season",
        "massive win",
        "priceless victory",
        "dramatic win",
    )
    stale_result_context_terms = (
        "preview",
        "warm-up",
        "build-up",
        "could",
        "would",
        "should",
        "need to",
        "must",
        "look to",
        "survival battle",
        "bid for survival",
        "bid for premiership survival",
    )

    if contains_news_term(haystack, live_score_terms):
        clean_tags.append("live-scores")
        return "live-scores", list(dict.fromkeys(clean_tags))

    if contains_news_term(haystack, explicit_breaking_terms) or contains_news_term(
        haystack,
        high_impact_breaking_terms,
    ) or contains_news_term(
        haystack,
        club_change_breaking_terms,
    ):
        clean_tags.append("breaking")
        return "breaking", list(dict.fromkeys(clean_tags))

    if contains_news_term(haystack, result_breaking_terms) and not contains_news_term(
        haystack,
        stale_result_context_terms,
    ):
        clean_tags.append("breaking")
        return "breaking", list(dict.fromkeys(clean_tags))

    clean_tags.append("news")
    return "news", list(dict.fromkeys(clean_tags))


def backfill_news_items(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id, title, source, summary, published_at, priority, tags_json
        FROM news_items
        ORDER BY published_at DESC, id DESC
        """
    ).fetchall()
    if not rows:
        return

    # Release the partial unique index before recomputing normalized story keys.
    conn.execute("UPDATE news_items SET story_key = '' WHERE story_key <> ''")

    seen_story_keys: set[str] = set()
    kept_rows: list[dict[str, Any]] = []
    for row in rows:
        title = clean_news_title(row["title"], row["source"])
        summary = clean_news_summary(row["summary"], title, row["source"])
        story_key = news_story_key(title)
        duplicate = story_key in seen_story_keys or any(
            news_rows_are_near_duplicates(
                {
                    "title": title,
                    "source": row["source"],
                    "published_at": row["published_at"],
                },
                kept_row,  # type: ignore[arg-type]
            )
            for kept_row in kept_rows
        )
        if duplicate:
            conn.execute("DELETE FROM news_items WHERE id = ?", (row["id"],))
            continue

        try:
            tags = json.loads(row["tags_json"])
        except json.JSONDecodeError:
            tags = []
        clean_tags = tags if isinstance(tags, list) else []
        priority, next_tags = classify_news_item(title, summary, clean_tags)
        next_tags_json = json.dumps(next_tags[:8])
        conn.execute(
            """
            UPDATE news_items
            SET story_key = ?, title = ?, summary = ?, priority = ?, tags_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (story_key, title, summary, priority, next_tags_json, utc_now(), row["id"]),
        )
        seen_story_keys.add(story_key)
        kept_rows.append(
            {
                "title": title,
                "source": row["source"],
                "published_at": row["published_at"],
            }
        )


def strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(value))).strip()


def parse_news_datetime(value: str) -> str:
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    except Exception:
        return utc_now()


def google_news_rss_url(query: str) -> str:
    return (
        "https://news.google.com/rss/search"
        f"?q={quote_plus(query)}&hl=en-GB&gl=GB&ceid=GB:en"
    )


def fetch_news_feed(
    query: str,
    tags: tuple[str, ...] | list[str] | None = None,
) -> list[dict[str, Any]]:
    request = Request(
        google_news_rss_url(query),
        headers={"Accept-Encoding": "identity", "User-Agent": NEWS_USER_AGENT},
    )
    with urlopen(request, timeout=10) as response:
        raw_xml, _charset = read_bounded_response(
            response,
            max_bytes=1_000_000,
            label="Google News",
        )

    root = ElementTree.fromstring(raw_xml)
    items: list[dict[str, Any]] = []

    for entry in root.findall("./channel/item")[:10]:
        title = strip_html(entry.findtext("title") or "")
        url = (entry.findtext("link") or "").strip()
        summary = strip_html(entry.findtext("description") or "")
        published_at = parse_news_datetime(entry.findtext("pubDate") or "")
        source = strip_html(entry.findtext("source") or "Google News")
        host = urlparse(url).netloc

        if not title or not url.startswith(("http://", "https://")):
            continue

        source_key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        items.append(
            {
                "sourceKey": source_key,
                "kind": "article",
                "title": title,
                "url": url,
                "source": source,
                "summary": summary,
                "publishedAt": published_at,
                "host": host,
                "priority": "media",
                "tags": list(tags or ("st-mirren", "scottish-football")),
            }
        )

    return items


def news_feed_identity(payload: dict[str, Any]) -> tuple[str, str]:
    source = bounded_text(payload.get("source"), 120) or "Unknown source"
    title = clean_news_title(bounded_text(payload.get("title"), 220), source)
    url = bounded_text(payload.get("url"), 600)
    source_key = bounded_text(payload.get("sourceKey"), 160)
    if not source_key and url:
        source_key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return source_key, news_story_key(title)


def is_recent_news_payload(
    payload: dict[str, Any],
    now: datetime | None = None,
) -> bool:
    published_at = bounded_text(payload.get("publishedAt"), 80)
    if not published_at:
        return False
    try:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(hours=NEWS_RECENT_WINDOW_HOURS)
    return published.astimezone(timezone.utc) >= cutoff


def collect_news_feed_items() -> tuple[list[dict[str, Any]], int]:
    collected: list[dict[str, Any]] = []
    seen_source_keys: set[str] = set()
    seen_story_keys: set[str] = set()
    recent_scoped_count = 0

    def extend_feed(
        query_configs: tuple[dict[str, Any], ...],
        *,
        track_recent_scoped: bool,
    ) -> None:
        nonlocal recent_scoped_count

        for query_config in query_configs:
            query = str(query_config["query"])
            tags = query_config.get("tags", ())
            try:
                items = fetch_news_feed(query, tags=tags)
            except Exception as error:
                safe_log(f"News monitor fetch failed for {query}: {error}")
                continue

            for payload in items:
                source_key, story_key = news_feed_identity(payload)
                dedupe_key = story_key or source_key
                if not source_key or not dedupe_key:
                    continue
                if source_key in seen_source_keys or dedupe_key in seen_story_keys:
                    continue
                seen_source_keys.add(source_key)
                seen_story_keys.add(dedupe_key)
                collected.append(payload)
                if track_recent_scoped and is_recent_news_payload(payload):
                    recent_scoped_count += 1

    extend_feed(NEWS_SCOPED_QUERY_CONFIGS, track_recent_scoped=True)
    if recent_scoped_count < NEWS_MIN_RECENT_SCOPED_ITEMS:
        safe_log(
            "News monitor supplementing wider sports feed "
            f"({recent_scoped_count} recent scoped item(s))"
        )
        extend_feed(NEWS_SUPPLEMENTAL_QUERY_CONFIGS, track_recent_scoped=False)

    return collected, recent_scoped_count


def ingest_news_once() -> int:
    inserted_count = 0
    items, _recent_scoped_count = collect_news_feed_items()

    with connect_db() as conn:
        for payload in items:
            try:
                item, inserted = upsert_news_item(conn, payload)
            except ValueError as error:
                safe_log(f"News monitor skipped item: {error}")
                continue

            if inserted:
                inserted_count += 1
            # Existing stories can contain corrections or live-score updates too.
            broadcast_news_item(item)
        pruned_count = prune_news_items(conn)
        if pruned_count:
            safe_log(f"News retention removed {pruned_count} stale item(s)")

    return inserted_count


def news_monitor_loop() -> None:
    safe_log("News monitor started")

    while True:
        try:
            inserted_count = ingest_news_once()
            if inserted_count:
                safe_log(f"News monitor inserted {inserted_count} item(s)")
        except Exception as error:
            safe_log(f"News monitor error: {error}")
        time.sleep(NEWS_MONITOR_INTERVAL_SEC)


def start_news_monitor() -> None:
    if not NEWS_MONITOR_ENABLED:
        safe_log("News monitor disabled")
        return

    thread = threading.Thread(target=news_monitor_loop, daemon=True)
    thread.start()


def next_daily_quiz_run(now: datetime | None = None) -> datetime:
    tz = server_timezone()
    local_now = now.astimezone(tz) if now is not None else datetime.now(tz)
    next_run = local_now.replace(
        hour=DAILY_QUIZ_SCHEDULER_HOUR,
        minute=DAILY_QUIZ_SCHEDULER_MINUTE,
        second=0,
        microsecond=0,
    )
    if next_run <= local_now:
        next_run += timedelta(days=1)
    return next_run


def active_daily_quiz_dates(now: datetime | None = None) -> list[str]:
    tz = server_timezone()
    local_now = now.astimezone(tz) if now is not None else datetime.now(tz)
    today = local_now.date()
    return [
        (today + timedelta(days=offset)).isoformat()
        for offset in range(DAILY_QUIZ_RESERVE_DAYS + 1)
    ]


def daily_quiz_generation_mode(
    quiz_date: str,
    now: datetime | None = None,
) -> str:
    tz = server_timezone()
    local_now = now.astimezone(tz) if now is not None else datetime.now(tz)
    target = date.fromisoformat(daily_quiz.valid_quiz_date(quiz_date))
    if target <= local_now.date():
        return "recovery"
    tomorrow = local_now.date() + timedelta(days=1)
    if target == tomorrow and local_now.hour >= DAILY_QUIZ_RECOVERY_HOUR:
        return "recovery"
    return "normal"


def ensure_daily_quiz_dates(target_dates: list[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen_dates: set[str] = set()
    normalized_targets = [daily_quiz.valid_quiz_date(value) for value in target_dates]
    if not normalized_targets:
        return results
    reserve_start = min(normalized_targets)
    with DAILY_QUIZ_OPERATION_LOCK:
        with closing(connect_db()) as conn:
            with conn:
                for normalized_date in normalized_targets:
                    if normalized_date in seen_dates:
                        continue
                    seen_dates.add(normalized_date)
                    status = daily_quiz.quiz_status(conn, normalized_date)
                    if status["status"] == "published":
                        safe_log(f"Daily quiz for {normalized_date} is already published")
                        results.append(status)
                        continue
                    if DAILY_QUIZ_POOL_ENABLED:
                        try:
                            result = daily_quiz.publish_quiz_from_pool(
                                conn,
                                normalized_date,
                                answer_embargo_days=DAILY_QUIZ_CONFIG.answer_embargo_days,
                            )
                            safe_log(
                                f"Daily quiz pool published a verified batch for {normalized_date}"
                            )
                            results.append(result)
                            continue
                        except (
                            LookupError,
                            ValueError,
                            daily_quiz.QuizRegenerationBlocked,
                        ) as error:
                            safe_log(
                                f"Daily quiz pool unavailable for {normalized_date}: {error}"
                            )
                    reserve_cards = int(
                        conn.execute(
                            """SELECT COUNT(*) FROM daily_quiz_questions q
                               JOIN daily_quiz_sets s ON s.id=q.quiz_set_id
                               WHERE s.status='published' AND s.quiz_date >= ?""",
                            (reserve_start,),
                        ).fetchone()[0]
                    )
                    if reserve_cards < quiz_board.LAUNCH_RESERVE_CARDS:
                        try:
                            result = daily_quiz.publish_verified_archive_fallback(
                                conn,
                                normalized_date,
                                answer_embargo_days=DAILY_QUIZ_CONFIG.answer_embargo_days,
                            )
                            safe_log(
                                f"Daily quiz reserve published verified archive content for {normalized_date}"
                            )
                            results.append(result)
                            continue
                        except (
                            LookupError,
                            ValueError,
                            daily_quiz.QuizRegenerationBlocked,
                        ) as error:
                            safe_log(
                                f"Daily quiz reserve prefill unavailable for {normalized_date}: {error}"
                            )
                    generation_kwargs: dict[str, Any] = {}
                    if bool(
                        getattr(DAILY_QUIZ_CONFIG, "candidate_pipeline_enabled", False)
                    ):
                        generation_kwargs["generation_mode"] = daily_quiz_generation_mode(
                            normalized_date
                        )
                    result = daily_quiz.generate_daily_quiz(
                        conn,
                        quiz_date=normalized_date,
                        config=DAILY_QUIZ_CONFIG,
                        log=lambda message: safe_log(f"Daily quiz: {message}"),
                        **generation_kwargs,
                    )
                    if result.get("status") != "published":
                        try:
                            result = daily_quiz.publish_verified_archive_fallback(
                                conn,
                                normalized_date,
                                answer_embargo_days=DAILY_QUIZ_CONFIG.answer_embargo_days,
                            )
                            safe_log(
                                f"Daily quiz reserve published verified archive content for {normalized_date}"
                            )
                        except (
                            LookupError,
                            ValueError,
                            daily_quiz.QuizRegenerationBlocked,
                        ) as error:
                            safe_log(
                                f"Daily quiz verified archive unavailable for {normalized_date}: {error}"
                            )
                    results.append(result)
                    if result.get("status") != "published":
                        break
    return results


def ensure_tomorrow_daily_quiz(now: datetime | None = None) -> dict[str, Any]:
    tomorrow_date = active_daily_quiz_dates(now)[1]
    return ensure_daily_quiz_dates([tomorrow_date])[0]


def ensure_active_daily_quizzes(now: datetime | None = None) -> list[dict[str, Any]]:
    return ensure_daily_quiz_dates(active_daily_quiz_dates(now))


def maintain_daily_quiz_pool() -> dict[str, Any]:
    if not DAILY_QUIZ_POOL_ENABLED:
        return {"status": "disabled", "ready": 0}
    with DAILY_QUIZ_OPERATION_LOCK:
        with closing(connect_db()) as conn:
            with conn:
                if DAILY_QUIZ_CONFIG.learning_profile_path:
                    try:
                        refreshed = refresh_quiz_learning_profile.refresh_runtime_profile(
                            conn, DAILY_QUIZ_CONFIG.learning_profile_path
                        )
                        if refreshed["status"] == "updated":
                            safe_log(
                                f"Daily quiz learning profile refreshed across "
                                f"{refreshed['slots']} slot(s)."
                            )
                    except (OSError, ValueError, sqlite3.DatabaseError) as error:
                        safe_log(f"Daily quiz learning profile refresh deferred: {type(error).__name__}")
                result = daily_quiz.replenish_quiz_pool(
                    conn,
                    config=DAILY_QUIZ_CONFIG,
                    target_ready=DAILY_QUIZ_POOL_TARGET_BATCHES,
                    max_batch_attempts=DAILY_QUIZ_POOL_MAX_BATCH_ATTEMPTS,
                    log=lambda message: safe_log(f"Daily quiz pool: {message}"),
                )
    safe_log(
        f"Daily quiz pool maintenance: {result['status']}; "
        f"ready={result.get('ready', 0)}/{DAILY_QUIZ_POOL_TARGET_BATCHES}"
    )
    return result


def daily_quiz_retry_interval_sec(results: list[dict[str, Any]]) -> int:
    if any(bool(result.get("last_failure_transient")) for result in results):
        return DAILY_QUIZ_TRANSIENT_RETRY_INTERVAL_SEC
    return DAILY_QUIZ_RETRY_INTERVAL_SEC


def daily_quiz_scheduler_loop() -> None:
    safe_log("Daily quiz scheduler started")
    while True:
        results: list[dict[str, Any]] = []
        pool_maintenance: dict[str, Any] | None = None
        retry_required = False
        try:
            results = ensure_active_daily_quizzes()
            retry_required = any(
                result.get("status") != "published"
                for result in results
            )
        except Exception as error:
            safe_log(f"Daily quiz scheduler generation failed: {error}")
            retry_required = True

        if DAILY_QUIZ_POOL_ENABLED:
            try:
                pool_maintenance = maintain_daily_quiz_pool()
            except Exception as error:
                safe_log(f"Daily quiz pool maintenance failed: {error}")
                pool_maintenance = {
                    "status": "failed",
                    "reason": str(error),
                    "ready": 0,
                }

        next_run = next_daily_quiz_run()
        now = datetime.now(next_run.tzinfo)
        if retry_required:
            retry_at = now + timedelta(seconds=daily_quiz_retry_interval_sec(results))
            wake_at = retry_at if retry_at < next_run else next_run
        else:
            wake_at = next_run
        if pool_maintenance is not None and pool_maintenance.get("status") != "stocked":
            pool_retry_at = now + timedelta(seconds=DAILY_QUIZ_POOL_RETRY_INTERVAL_SEC)
            retry_at_value = str(pool_maintenance.get("retry_at") or "").strip()
            if retry_at_value:
                try:
                    provider_retry_at = datetime.fromisoformat(
                        retry_at_value.replace("Z", "+00:00")
                    )
                    if provider_retry_at.tzinfo is None:
                        provider_retry_at = provider_retry_at.replace(tzinfo=timezone.utc)
                    pool_retry_at = provider_retry_at.astimezone(now.tzinfo)
                except ValueError:
                    pass
            if pool_retry_at <= now:
                pool_retry_at = now + timedelta(seconds=DAILY_QUIZ_POOL_RETRY_INTERVAL_SEC)
            wake_at = min(wake_at, pool_retry_at)
        delay = max(1.0, (wake_at - now).total_seconds())
        safe_log(f"Daily quiz scheduler sleeping until {wake_at.isoformat()}")
        time.sleep(delay)


def start_daily_quiz_scheduler() -> None:
    if not DAILY_QUIZ_SCHEDULER_ENABLED:
        safe_log("Daily quiz scheduler disabled")
        return
    thread = threading.Thread(target=daily_quiz_scheduler_loop, daemon=True)
    thread.start()


def weekly_product_summary_loop() -> None:
    """Send one aggregate, privacy-minimal report each Monday after 08:00 UK time."""
    while True:
        try:
            local_now = datetime.now(server_timezone())
            if WEEKLY_SUMMARY_NTFY_URL and local_now.weekday() == 0 and local_now.hour >= 8:
                week_start = local_now.date().isoformat()
                with connect_db() as conn:
                    delivered = conn.execute(
                        "SELECT 1 FROM weekly_summary_deliveries WHERE week_start=?", (week_start,)
                    ).fetchone()
                    if delivered is None:
                        end = (local_now.date() - timedelta(days=1)).isoformat()
                        start = (local_now.date() - timedelta(days=7)).isoformat()
                        report = quiz_board.admin_report(conn, start, end)
                        ratings = ", ".join(
                            f"{item['game']} {item['rating']}={item['count']}"
                            for item in report["feedback"]
                        ) or "no feedback"
                        body = (
                            f"Fulton's weekly product summary ({start} to {end})\n"
                            f"Quiz starts {report['quiz']['started']}; completed {report['quiz']['completed']} "
                            f"({round(report['quiz']['completionRate'] * 100)}%); "
                            f"average score {report['quiz']['averageScore']}.\n"
                            + "Journeys: " + ", ".join(
                                f"{item['game']} {item['completed']}/{item['started']} complete"
                                for item in report["journey"]
                            ) + f".\nFeedback: {ratings}."
                        )
                        destination = urlparse(WEEKLY_SUMMARY_NTFY_URL)
                        if destination.scheme != "https" or not destination.hostname:
                            raise ValueError("Weekly ntfy destination must be an HTTPS URL.")
                        connection = HTTPSConnection(destination.hostname, destination.port or 443, timeout=10)
                        try:
                            target = destination.path or "/"
                            if destination.query:
                                target = f"{target}?{destination.query}"
                            connection.request(
                                "POST", target, body=body.encode("utf-8"),
                                headers={"Title": "Fulton's weekly summary", "Tags": "bar_chart", "Content-Type": "text/plain; charset=utf-8"},
                            )
                            response = connection.getresponse()
                            response.read(1024)
                            if response.status >= 400:
                                raise RuntimeError(f"ntfy returned HTTP {response.status}")
                        finally:
                            connection.close()
                        conn.execute(
                            "INSERT INTO weekly_summary_deliveries (week_start, delivered_at) VALUES (?, ?)",
                            (week_start, utc_now()),
                        )
                        conn.commit()
        except Exception as error:
            safe_log(f"Weekly product summary failed: {error}")
        time.sleep(60)


def start_weekly_product_summary_scheduler() -> None:
    if not WEEKLY_SUMMARY_NTFY_URL:
        safe_log("Weekly product summary disabled: no ntfy destination configured")
        return
    threading.Thread(target=weekly_product_summary_loop, daemon=True).start()


def next_daily_map_game_run(now: datetime | None = None) -> datetime:
    tz = server_timezone()
    local_now = now.astimezone(tz) if now is not None else datetime.now(tz)
    next_run = local_now.replace(
        hour=DAILY_MAP_GAME_SCHEDULER_HOUR,
        minute=DAILY_MAP_GAME_SCHEDULER_MINUTE,
        second=0,
        microsecond=0,
    )
    if next_run <= local_now:
        next_run += timedelta(days=1)
    return next_run


def active_daily_map_game_dates(now: datetime | None = None) -> list[str]:
    tz = server_timezone()
    local_now = now.astimezone(tz) if now is not None else datetime.now(tz)
    today = local_now.date()
    return [
        (today + timedelta(days=offset)).isoformat()
        for offset in range(DAILY_MAP_PREPARE_DAYS_AHEAD + 1)
    ]


def daily_map_date_is_requestable(puzzle_date: str) -> bool:
    return DAILY_MAP_FUTURE_REVIEW_ENABLED or puzzle_date <= today_game_date()


def daily_map_level_is_requestable(conn: sqlite3.Connection, level_id: int) -> bool:
    row = conn.execute(
        """SELECT p.puzzle_date FROM daily_map_levels l
           JOIN daily_map_puzzles p ON p.id=l.puzzle_id WHERE l.id=?""",
        (level_id,),
    ).fetchone()
    return (
        row is not None
        and date.fromisoformat(str(row["puzzle_date"])).weekday() in {2, 5}
        and (
            (DAILY_MAP_FUTURE_REVIEW_ENABLED and daily_map_date_is_requestable(str(row["puzzle_date"])))
            or str(row["puzzle_date"]) == daily_map_game.playable_map_round_date(conn, today_game_date())
        )
    )


def daily_map_submission_date(conn: sqlite3.Connection, level_id: int) -> str:
    if not DAILY_MAP_FUTURE_REVIEW_ENABLED:
        return daily_map_game.playable_map_round_date(conn, today_game_date())
    row = conn.execute(
        """
        SELECT daily_map_puzzles.puzzle_date
        FROM daily_map_levels
        INNER JOIN daily_map_puzzles
            ON daily_map_puzzles.id = daily_map_levels.puzzle_id
        WHERE daily_map_levels.id = ?
        """,
        (level_id,),
    ).fetchone()
    return str(row["puzzle_date"]) if row is not None else today_game_date()


def daily_map_launch_preferred_place_type(puzzle_date: str) -> str | None:
    if not DAILY_MAP_STADIUM_LAUNCH_DATE or DAILY_MAP_STADIUM_LAUNCH_ROUNDS <= 0:
        return None
    launch_date = datetime.strptime(
        daily_map_game.valid_game_date(DAILY_MAP_STADIUM_LAUNCH_DATE),
        "%Y-%m-%d",
    ).date()
    target_date = datetime.strptime(
        daily_map_game.valid_game_date(puzzle_date),
        "%Y-%m-%d",
    ).date()
    launch_index = (target_date - launch_date).days
    if 0 <= launch_index < DAILY_MAP_STADIUM_LAUNCH_ROUNDS:
        return "stadium"
    return None


def publish_reviewed_daily_map_fallback(
    conn: sqlite3.Connection,
    *,
    puzzle_date: str,
    required_place_type: str | None,
    ai_failure_reason: str,
    preserve_published: bool = False,
) -> dict[str, Any]:
    # The generator checks publication after acquiring its database write lock.
    # Automatic callers must also preserve rounds published by another process.
    result = daily_map_game.generate_daily_map_game(
        conn,
        puzzle_date=puzzle_date,
        force=not preserve_published,
        required_place_type=required_place_type,
        log=lambda message: safe_log(f"Daily map fallback: {message}"),
    )
    if result.get("status") != "published" and required_place_type:
        safe_log(
            f"Daily map fallback has no unused {required_place_type} for {puzzle_date}; "
            "trying any reviewed place."
        )
        result = daily_map_game.generate_daily_map_game(
            conn,
            puzzle_date=puzzle_date,
            force=not preserve_published,
            log=lambda message: safe_log(f"Daily map fallback: {message}"),
        )
    if result.get("status") == "published":
        safe_log(
            f"Daily map fallback published a reviewed round for {puzzle_date} "
            f"after AI failure: {ai_failure_reason}"
        )
        return result

    fallback_reason = str(result.get("failureReason") or "No reviewed fallback was available.")
    daily_map_game.set_puzzle_status(
        conn,
        puzzle_date,
        "failed",
        failure_reason=(
            f"{ai_failure_reason}; reviewed fallback failed: {fallback_reason}"
        ),
    )
    return daily_map_game.puzzle_status(conn, puzzle_date)


def generate_daily_map_game_for_date(
    conn: sqlite3.Connection,
    *,
    puzzle_date: str,
    force: bool = False,
    preferred_place_id: int | None = None,
) -> dict[str, Any]:
    normalized_date = daily_map_game.valid_game_date(puzzle_date)
    required_place_type = daily_map_launch_preferred_place_type(normalized_date)
    existing = daily_map_game.puzzle_status(conn, normalized_date)
    if existing["status"] == "published" and not force:
        return existing
    if not DAILY_MAP_AI_GENERATION_ENABLED or preferred_place_id is not None:
        return daily_map_game.generate_daily_map_game(
            conn,
            puzzle_date=normalized_date,
            force=force,
            preferred_place_id=preferred_place_id,
            allow_recent_preferred_place=preferred_place_id is not None,
            log=lambda message: safe_log(f"Daily map game: {message}"),
        )

    if DAILY_MAP_AUTOMATIC_ENABLED:
        if existing["status"] == "published":
            return existing
        try:
            return automatic_map_pool.publish(conn, puzzle_date=normalized_date)
        except Exception as error:
            safe_log(f"Automatic map queue unavailable for {normalized_date}: {type(error).__name__}")
            return publish_reviewed_daily_map_fallback(
                conn, puzzle_date=normalized_date, required_place_type=required_place_type,
                ai_failure_reason=f"Automatic map queue unavailable: {type(error).__name__}",
                preserve_published=True,
            )

    if DAILY_MAP_CONTROLLED_ENABLED:
        # Published rounds remain immutable in this mode, including force requests.
        if existing["status"] == "published":
            return existing
        try:
            controlled_provider = controlled_map_round.ControlledProvider.from_runtime_env()
            generated = controlled_map_round.generate_and_publish(
                conn, puzzle_date=normalized_date, provider=controlled_provider, catalog=DAILY_MAP_CONTROLLED_CATALOG,
            )
            safe_log(f"Daily map controlled generation completed for {normalized_date} in {generated['request_count']} request(s).")
            return dict(generated["publish_result"])
        except Exception as error:
            safe_log(f"Daily map controlled generation failed for {normalized_date}: {type(error).__name__}")
            return publish_reviewed_daily_map_fallback(
                conn, puzzle_date=normalized_date, required_place_type=required_place_type,
                ai_failure_reason=f"Controlled generation failed: {type(error).__name__}",
            )

    try:
        provider = map_clue_rewriter.ConfiguredMapClueProvider.from_env()
    except Exception as error:
        reason = f"AI map provider failed: {error}"
        safe_log(f"Daily map AI provider failed for {normalized_date}: {error}")
        return publish_reviewed_daily_map_fallback(
            conn,
            puzzle_date=normalized_date,
            required_place_type=required_place_type,
            ai_failure_reason=reason,
        )

    generation_rounds = (
        DAILY_MAP_AI_GENERATION_ROUNDS if DAILY_MAP_AI_DISCOVER_COUNT > 0 else 1
    )
    excluded_discovery_names: set[str] = set()
    generation_failures: list[str] = []
    for generation_round in range(1, generation_rounds + 1):
        eligible_place_ids: set[int] | None = None
        eligible_names: set[str] | None = None
        if DAILY_MAP_AI_DISCOVER_COUNT > 0:
            try:
                discovery = generate_ai_daily_map_round.discover_uncurated_candidates(
                    db_path=DB_PATH,
                    provider=provider,
                    puzzle_date=normalized_date,
                    count=DAILY_MAP_AI_DISCOVER_COUNT,
                    max_attempts=DAILY_MAP_AI_DISCOVERY_ATTEMPTS,
                    excluded_names=set(excluded_discovery_names),
                    required_place_type=required_place_type,
                )
                eligible_place_ids = set(discovery.get("candidate_place_ids") or []) or None
                eligible_names = set(discovery["candidate_names"])
                safe_log(
                    "Daily map AI: discovered "
                    f"{discovery['accepted_count']} eligible candidates "
                    f"({len(eligible_place_ids or [])} resolved places) for {normalized_date} "
                    f"on generation round {generation_round}/{generation_rounds}."
                )
            except Exception as error:
                generation_failures.append(f"discovery round {generation_round}: {error}")
                safe_log(
                    f"Daily map AI discovery failed for {normalized_date} on round "
                    f"{generation_round}/{generation_rounds}: {error}"
                )
                break

        try:
            generated = generate_ai_daily_map_round.generate_round(
                conn,
                provider=provider,
                puzzle_date=normalized_date,
                shortlist_limit=DAILY_MAP_AI_SHORTLIST_LIMIT,
                max_clue_attempts=DAILY_MAP_AI_MAX_CLUE_ATTEMPTS,
                eligible_place_ids=eligible_place_ids,
                eligible_names=eligible_names,
                required_place_type=required_place_type,
            )
            safe_log(
                "Daily map AI: selected "
                f"{generated['place']} with profile {generated['learning_profile_hash']} "
                f"and {generated['critic_mode']} criticism on generation round "
                f"{generation_round}/{generation_rounds}."
            )
            return dict(generated["publish_result"])
        except Exception as error:
            conn.rollback()
            generation_failures.append(f"generation round {generation_round}: {error}")
            safe_log(
                f"Daily map AI generation failed for {normalized_date} on round "
                f"{generation_round}/{generation_rounds}: {error}"
            )
            excluded_discovery_names.update(eligible_names or set())
            if generation_round < generation_rounds:
                safe_log(
                    f"Daily map AI: rejecting that candidate batch and discovering fresh "
                    f"places for {normalized_date}."
                )

    failure_count = len(generation_failures)
    final_failure = generation_failures[-1] if generation_failures else "unknown failure"
    reason = (
        f"AI map generation exhausted {failure_count} failed round(s); "
        f"last failure: {final_failure}"
    )
    return publish_reviewed_daily_map_fallback(
        conn,
        puzzle_date=normalized_date,
        required_place_type=required_place_type,
        ai_failure_reason=reason,
    )


def ensure_daily_map_game_dates(target_dates: list[str]) -> list[dict[str, Any]]:
    global DAILY_MAP_AUTOMATIC_RETRY_AT
    results: list[dict[str, Any]] = []
    seen_dates: set[str] = set()
    with DAILY_MAP_GAME_OPERATION_LOCK:
        if DAILY_MAP_AUTOMATIC_ENABLED and DAILY_MAP_AI_GENERATION_ENABLED:
            try:
                maintenance = automatic_map_pool.maintain_until_stocked(
                    Path(DB_PATH),
                    Path(DB_PATH).parent / "qa" / "automatic-map",
                )
                retry_at_value = str(maintenance.get("retry_at") or "").strip()
                DAILY_MAP_AUTOMATIC_RETRY_AT = (
                    datetime.fromisoformat(retry_at_value.replace("Z", "+00:00"))
                    if retry_at_value
                    else None
                )
                safe_log(f"Automatic map maintenance: {maintenance['status']}; ready={maintenance.get('ready', 0)}")
            except Exception as error:
                DAILY_MAP_AUTOMATIC_RETRY_AT = None
                safe_log(f"Automatic map maintenance deferred: {type(error).__name__}")
        with closing(connect_db()) as conn:
            with conn:
                for puzzle_date in target_dates:
                    normalized_date = daily_map_game.valid_game_date(puzzle_date)
                    if normalized_date in seen_dates:
                        continue
                    seen_dates.add(normalized_date)
                    status = daily_map_game.puzzle_status(conn, normalized_date)
                    if status["status"] == "published":
                        results.append(status)
                        continue
                    result = generate_daily_map_game_for_date(
                        conn,
                        puzzle_date=normalized_date,
                    )
                    results.append(result)
                    if result.get("status") != "published":
                        break
    return results


def ensure_active_daily_map_games(now: datetime | None = None) -> list[dict[str, Any]]:
    tz = server_timezone()
    local_now = now.astimezone(tz) if now is not None else datetime.now(tz)
    featured: list[str] = []
    cursor = local_now.date()
    while len(featured) < DAILY_MAP_PREPARE_DAYS_AHEAD:
        if cursor.weekday() in {2, 5}:
            featured.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return ensure_daily_map_game_dates(featured)


def daily_map_game_retry_interval_sec(results: list[dict[str, Any]]) -> int:
    if any(
        daily_quiz.is_transient_provider_failure(str(result.get("failureReason") or ""))
        for result in results
    ):
        return DAILY_MAP_GAME_TRANSIENT_RETRY_INTERVAL_SEC
    return DAILY_MAP_GAME_RETRY_INTERVAL_SEC


def daily_map_game_scheduler_loop() -> None:
    safe_log("Daily map game scheduler started")
    while True:
        results: list[dict[str, Any]] = []
        retry_required = False
        try:
            results = ensure_active_daily_map_games()
            retry_required = any(result.get("status") != "published" for result in results)
        except Exception as error:
            safe_log(f"Daily map game scheduler generation failed: {error}")
            results = [{"failureReason": str(error)}]
            retry_required = True

        next_run = next_daily_map_game_run()
        now = datetime.now(next_run.tzinfo)
        if retry_required:
            retry_at = now + timedelta(seconds=daily_map_game_retry_interval_sec(results))
            wake_at = retry_at if retry_at < next_run else next_run
        else:
            wake_at = next_run
        if DAILY_MAP_AUTOMATIC_ENABLED and DAILY_MAP_AI_GENERATION_ENABLED:
            maintenance_wake = now + timedelta(minutes=15)
            if DAILY_MAP_AUTOMATIC_RETRY_AT is not None:
                maintenance_wake = DAILY_MAP_AUTOMATIC_RETRY_AT
                if maintenance_wake.tzinfo is None:
                    maintenance_wake = maintenance_wake.replace(tzinfo=timezone.utc)
                maintenance_wake = maintenance_wake.astimezone(now.tzinfo)
                if maintenance_wake <= now:
                    maintenance_wake = now + timedelta(minutes=15)
            wake_at = min(wake_at, maintenance_wake)
        delay = max(1.0, (wake_at - now).total_seconds())
        safe_log(f"Daily map game scheduler sleeping until {wake_at.isoformat()}")
        time.sleep(delay)


def start_daily_map_game_scheduler() -> None:
    if not DAILY_MAP_GAME_SCHEDULER_ENABLED:
        safe_log("Daily map game scheduler disabled")
        return
    thread = threading.Thread(target=daily_map_game_scheduler_loop, daemon=True)
    thread.start()





































def current_index_asset(suffix: str) -> Path | None:
    assets_dir = DIST_DIR / "assets"
    if suffix not in {".css", ".js"} or not assets_dir.exists():
        return None
    matches = [path for path in assets_dir.glob(f"index-*{suffix}") if path.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def requested_dist_asset(parsed_path: str) -> Path | None:
    target = (DIST_DIR / parsed_path.lstrip("/")).resolve()
    dist_root = DIST_DIR.resolve()
    try:
        target.relative_to(dist_root)
    except ValueError:
        return None
    if target.is_file():
        return target
    return None


STATIC_MEDIA_RANGE_SUFFIXES = {".m4v", ".mov", ".mp3", ".mp4", ".wav", ".webm"}


def parse_static_byte_range(value: str, file_size: int) -> tuple[int, int]:
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
    if match is None or file_size <= 0:
        raise ValueError("Invalid byte range.")

    start_text, end_text = match.groups()
    if not start_text and not end_text:
        raise ValueError("Invalid byte range.")

    if not start_text:
        suffix_length = int(end_text)
        if suffix_length <= 0:
            raise ValueError("Invalid byte range.")
        return max(0, file_size - suffix_length), file_size - 1

    start = int(start_text)
    if start >= file_size:
        raise ValueError("Byte range starts beyond the file.")

    end = file_size - 1 if not end_text else min(int(end_text), file_size - 1)
    if end < start:
        raise ValueError("Invalid byte range.")
    return start, end


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """Threading server with a hard connection-worker ceiling."""

    daemon_threads = True
    request_queue_size = 64

    def __init__(self, server_address: Any, handler_class: Any) -> None:
        self._worker_slots = threading.BoundedSemaphore(HTTP_MAX_WORKERS)
        super().__init__(server_address, handler_class)

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._worker_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._worker_slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._worker_slots.release()


class FultonsHandler(SimpleHTTPRequestHandler):
    server_version = "FultonsQuiz/0.1"
    sys_version = ""

    def version_string(self) -> str:
        return self.server_version

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(HTTP_READ_TIMEOUT_SECONDS)

    def do_OPTIONS(self) -> None:
        origin = self.headers.get("Origin")
        if origin and not self.request_origin_allowed():
            self.send_error_json(HTTPStatus.FORBIDDEN, "Origin is not allowed.")
            return

        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-News-Monitor-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.end_headers()

    def end_headers(self) -> None:
        self.send_cache_version_headers()
        self.send_static_cache_headers()
        self.send_security_headers()
        self.send_cors_headers()
        super().end_headers()

    def send_cache_version_headers(self) -> None:
        if CACHE_VERSION == "local":
            return
        if get_cookie_value(self.headers, CACHE_VERSION_COOKIE) == CACHE_VERSION:
            return
        self.send_header("Clear-Site-Data", '"cache"')
        self.send_header("Set-Cookie", cache_version_header())

    def send_static_cache_headers(self) -> None:
        if getattr(self, "_json_response", False):
            return

        parsed_path = urlparse(self.path).path
        if parsed_path.startswith("/api/") or parsed_path.startswith("/internal/"):
            return

        if parsed_path.startswith("/assets/"):
            if requested_dist_asset(parsed_path) is not None:
                self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            else:
                self.send_header("Cache-Control", "no-store, max-age=0")
            return

        if Path(parsed_path).suffix.lower() in STATIC_MEDIA_RANGE_SUFFIXES:
            self.send_header("Accept-Ranges", "bytes")

        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")

    def send_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(self)")
        self.send_header(
            "Content-Security-Policy",
            "; ".join(
                (
                    "default-src 'self'",
                    "base-uri 'self'",
                    "object-src 'none'",
                    "frame-ancestors 'none'",
                    "form-action 'self'",
                    "script-src 'self'",
                    "style-src 'self' 'unsafe-inline'",
                    "img-src 'self' data: blob: https://server.arcgisonline.com https://*.basemaps.cartocdn.com",
                    "connect-src 'self'",
                    "font-src 'self' data:",
                    "media-src 'self' blob:",
                )
            ),
        )
        if COOKIE_SECURE:
            self.send_header(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )

    def cors_allowed_origin(self) -> str | None:
        origin = self.headers.get("Origin")
        if origin and origin in CORS_ALLOWED_ORIGINS:
            return origin
        return None

    def send_cors_headers(self) -> None:
        origin = self.cors_allowed_origin()
        if origin is None:
            return
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Vary", "Origin")

    def client_ip(self) -> str:
        peer_text = str(self.client_address[0] if self.client_address else "").split("%", 1)[0]
        try:
            peer_address = ipaddress.ip_address(peer_text)
        except ValueError:
            return "unknown"
        if isinstance(peer_address, ipaddress.IPv6Address) and peer_address.ipv4_mapped is not None:
            peer_address = peer_address.ipv4_mapped
        peer = str(peer_address)
        if not TRUST_PROXY_HEADERS or not any(
            peer_address in network for network in TRUSTED_PROXY_NETWORKS
        ):
            return peer

        forwarded = str(self.headers.get("X-Forwarded-For") or "").strip()
        candidates = [item.strip() for item in forwarded.split(",") if item.strip()]
        if not candidates:
            real_ip = str(self.headers.get("X-Real-IP") or "").strip()
            candidates = [real_ip] if real_ip else []
        if not candidates or len(candidates) > 32 or len(forwarded) > 2048:
            return peer
        parsed_candidates: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
        for candidate in candidates:
            try:
                address = ipaddress.ip_address(candidate.split("%", 1)[0])
            except ValueError:
                return peer
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
                address = address.ipv4_mapped
            parsed_candidates.append(address)
        return str(parsed_candidates[-1])

    def is_loopback_request(self) -> bool:
        return is_loopback_ip(self.client_ip())

    def request_host_allowed(self) -> bool:
        raw_host = self.headers.get("Host", "").strip()
        if not raw_host:
            return False
        parsed = urlparse(f"//{raw_host}")
        hostname = (parsed.hostname or "").lower().rstrip(".")
        return hostname in ALLOWED_HOSTS

    def request_origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            # Bearer-authenticated automation may omit Origin, but cookie-authenticated
            # browser mutations require an explicit trusted origin as a CSRF boundary.
            return get_cookie_value(self.headers, SESSION_COOKIE) is None
        if origin in CORS_ALLOWED_ORIGINS:
            return True
        parsed_origin = urlparse(origin)
        if (
            not COOKIE_SECURE
            and self.request_host_allowed()
            and is_development_origin_host(parsed_origin.hostname)
        ):
            return True

        return False

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/") or parsed.path.startswith("/internal/"):
            self.handle_api("GET", parsed.path, parsed.query)
            return

        self.serve_static()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        self.handle_api("POST", parsed.path, parsed.query)

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        self.handle_api("PATCH", parsed.path, parsed.query)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        self.handle_api("DELETE", parsed.path, parsed.query)

    def _write_json(
        self,
        status: int,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        self._json_response = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def send_json(
        self,
        status: int,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        if getattr(self, "_defer_json_response", False):
            self._pending_json_response = (status, payload, headers)
            return
        self._write_json(status, payload, headers)

    def send_error_json(self, status: int, message: str) -> None:
        self.send_json(status, {"error": message})

    def send_sse_headers(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

    def write_sse(self, event: str, payload: dict[str, Any]) -> None:
        message = f"event: {event}\ndata: {json.dumps(payload)}\n\n"
        self.wfile.write(message.encode("utf-8"))
        self.wfile.flush()

    def read_json(self) -> dict[str, Any]:
        raw_content_length = self.headers.get("Content-Length", "0").strip()
        try:
            content_length = int(raw_content_length)
        except ValueError as error:
            raise ValueError("Content-Length must be a non-negative integer.") from error
        if content_length < 0:
            raise ValueError("Content-Length must be a non-negative integer.")
        if content_length == 0:
            return {}
        if content_length > HTTP_REQUEST_MAX_BYTES:
            raise ValueError("Request body is too large.")
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise ValueError("Content-Type must be application/json.")

        raw_body = self.rfile.read(content_length)
        if len(raw_body) != content_length:
            raise ValueError("Request body ended before Content-Length bytes were received.")

        decoded = json.loads(raw_body.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("Expected a JSON object.")
        return decoded

    def handle_api(self, method: str, path: str, query: str = "") -> None:
        self._defer_json_response = True
        self._pending_json_response = None
        try:
            if not self.request_host_allowed():
                self.send_error_json(HTTPStatus.BAD_REQUEST, "Host is not allowed.")
            elif method in {"POST", "PATCH", "DELETE"} and not self.request_origin_allowed():
                self.send_error_json(HTTPStatus.FORBIDDEN, "Origin is not allowed.")
            else:
                self.route_api(method, path.rstrip("/") or "/", query)
        except json.JSONDecodeError:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Invalid JSON body.")
        except ValueError as error:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
        except (BrokenPipeError, ConnectionResetError):
            self._pending_json_response = None
        except Exception as error:
            safe_log(f"API error: {error}")
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "Server error.")
        finally:
            self._defer_json_response = False

        pending = self._pending_json_response
        self._pending_json_response = None
        if pending is not None:
            try:
                self._write_json(*pending)
            except (BrokenPipeError, ConnectionResetError):
                return

    def route_api(self, method: str, path: str, query: str = "") -> None:
        params = parse_qs(query)

        if path == "/api/health" and method == "GET":
            storage = public_runtime_storage_health()
            status = HTTPStatus.OK if storage["ok"] else HTTPStatus.SERVICE_UNAVAILABLE
            self.send_json(status, health_payload(storage))
            return

        if path in {"/api/history", "/api/facts", "/api/fact-image"}:
            self.send_error_json(
                HTTPStatus.GONE,
                "This retired API is no longer available.",
            )
            return

        if path == "/internal/generate-daily-quiz" and method == "POST":
            configured_token = DAILY_QUIZ_CONFIG.internal_token
            submitted_token = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            if not configured_token:
                self.send_error_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "Internal quiz generation token is not configured.",
                )
                return
            if not hmac.compare_digest(submitted_token, configured_token):
                self.send_error_json(HTTPStatus.UNAUTHORIZED, "Invalid internal token.")
                return
            payload = self.read_json()
            quiz_date = str(payload.get("date") or today_game_date())
            force = payload.get("force", False)
            if type(force) is not bool:
                self.send_error_json(
                    HTTPStatus.BAD_REQUEST,
                    "force must be a JSON boolean.",
                )
                return
            with DAILY_QUIZ_OPERATION_LOCK:
                with connect_db() as conn:
                    result = daily_quiz.generate_daily_quiz(
                        conn,
                        quiz_date=quiz_date,
                        force=force,
                        config=DAILY_QUIZ_CONFIG,
                        log=safe_log,
                    )
                    record_audit_event(
                        conn,
                        "quiz.generate.internal",
                        client_ip=self.client_ip(),
                        details={
                            "date": quiz_date,
                            "force": force,
                            "status": str(result.get("status") or "unknown")[:64],
                            "blocked": bool(result.get("regeneration_blocked")),
                            "failed": bool(result.get("regeneration_failed")),
                        },
                    )
            status = (
                HTTPStatus.CONFLICT
                if result.get("regeneration_blocked")
                else (
                    HTTPStatus.OK
                    if result.get("status") == "published"
                    and not result.get("regeneration_failed")
                    else HTTPStatus.SERVICE_UNAVAILABLE
                )
            )
            self.send_json(status, result)
            return

        if path == "/internal/generate-daily-map-game" and method == "POST":
            configured_token = DAILY_QUIZ_CONFIG.internal_token
            submitted_token = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            if not configured_token:
                self.send_error_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "Internal generation token is not configured.",
                )
                return
            if not hmac.compare_digest(submitted_token, configured_token):
                self.send_error_json(HTTPStatus.UNAUTHORIZED, "Invalid internal token.")
                return
            payload = self.read_json()
            force_value = payload.get("force", False)
            if type(force_value) is not bool:
                self.send_error_json(
                    HTTPStatus.BAD_REQUEST,
                    "force must be a JSON boolean.",
                )
                return
            puzzle_date = str(payload.get("date") or today_game_date())
            with DAILY_MAP_GAME_OPERATION_LOCK:
                with connect_db() as conn:
                    result = generate_daily_map_game_for_date(
                        conn,
                        puzzle_date=puzzle_date,
                        force=force_value,
                        preferred_place_id=(
                            int(payload["placeId"])
                            if payload.get("placeId") is not None
                            else None
                        ),
                    )
                    record_audit_event(
                        conn,
                        "map.generate.internal",
                        client_ip=self.client_ip(),
                        details={
                            "date": puzzle_date,
                            "force": force_value,
                            "preferredPlaceId": payload.get("placeId"),
                            "status": str(result.get("status") or "unknown")[:64],
                        },
                    )
            status = (
                HTTPStatus.OK
                if result.get("status") == "published"
                else HTTPStatus.SERVICE_UNAVAILABLE
            )
            self.send_json(status, result)
            return

        if path == "/internal/ops-summary" and method == "GET":
            configured_token = DAILY_QUIZ_CONFIG.internal_token
            submitted_token = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            if not configured_token:
                self.send_error_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "Internal quiz generation token is not configured.",
                )
                return
            if not hmac.compare_digest(submitted_token, configured_token):
                self.send_error_json(HTTPStatus.UNAUTHORIZED, "Invalid internal token.")
                return
            self.send_json(HTTPStatus.OK, internal_ops_summary_payload())
            return

        if path in {"/internal/map-place-review-feedback", "/api/map-place-review-feedback"} and method == "POST":
            review_actor_user_id: int | None = None
            review_source = "internal"
            if path.startswith("/internal/"):
                configured_token = DAILY_QUIZ_CONFIG.internal_token
                submitted_token = (
                    self.headers.get("Authorization", "")
                    .removeprefix("Bearer ")
                    .strip()
                )
                if not configured_token:
                    self.send_error_json(
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        "Internal generation token is not configured.",
                    )
                    return
                if not hmac.compare_digest(submitted_token, configured_token):
                    self.send_error_json(HTTPStatus.UNAUTHORIZED, "Invalid internal token.")
                    return
            else:
                with connect_db() as auth_conn:
                    token = get_cookie_value(self.headers, SESSION_COOKIE)
                    review_user = current_user(auth_conn, token)
                if review_user is None:
                    self.send_error_json(HTTPStatus.UNAUTHORIZED, "Login required.")
                    return
                if review_user["role"] != "admin":
                    self.send_error_json(HTTPStatus.FORBIDDEN, "Admin access required.")
                    return
                review_actor_user_id = int(review_user["id"])
                review_source = "admin"
            payload = self.read_json()
            rows = payload.get("rows")
            if not isinstance(rows, list):
                self.send_error_json(HTTPStatus.BAD_REQUEST, "rows must be a list.")
                return
            clean_rows: list[dict[str, Any]] = []
            for row in rows[:500]:
                if not isinstance(row, dict):
                    continue
                clue_uses: list[dict[str, Any]] = []
                if isinstance(row.get("clue_uses"), list):
                    for clue in row.get("clue_uses", [])[:4]:
                        if not isinstance(clue, dict):
                            continue
                        clue_uses.append(
                            {
                                "level": str(clue.get("level") or "").strip(),
                                "maxPoints": clue.get("maxPoints"),
                                "role": str(clue.get("role") or "").strip(),
                                "fact": str(clue.get("fact") or "").strip(),
                                "usedAs": str(clue.get("usedAs") or "").strip(),
                                "yourScore": clue.get("yourScore"),
                            }
                        )
                clues = row.get("clues") if isinstance(row.get("clues"), dict) else {}
                clue_scores_source = row.get("clue_scores") if isinstance(row.get("clue_scores"), dict) else {}
                clue_reviews_source = (
                    row.get("clue_reviews")
                    if isinstance(row.get("clue_reviews"), dict)
                    else {}
                )
                clue_reviews: dict[str, dict[str, str]] = {}
                for level in ("hard", "medium", "easy"):
                    source = (
                        clue_reviews_source.get(level)
                        if isinstance(clue_reviews_source.get(level), dict)
                        else {}
                    )
                    verdict = str(
                        source.get("pass_fail") or source.get("passFail") or ""
                    ).strip().casefold()
                    if verdict not in {"pass", "fail"}:
                        verdict = ""
                    clue_reviews[level] = {
                        "level": level,
                        "clue": str(source.get("clue") or clues.get(level) or "").strip(),
                        "pass_fail": verdict,
                        "reason": str(source.get("reason") or "").strip(),
                    }
                overall_review_source = (
                    row.get("overall_review")
                    if isinstance(row.get("overall_review"), dict)
                    else {}
                )
                overall_verdict = str(
                    overall_review_source.get("pass_fail")
                    or overall_review_source.get("passFail")
                    or ""
                ).strip().casefold()
                if overall_verdict not in {"pass", "fail"}:
                    overall_verdict = ""
                hard_review_source = row.get("hard_review") if isinstance(row.get("hard_review"), dict) else {}
                hard_pass_fail = str(
                    hard_review_source.get("pass_fail")
                    or hard_review_source.get("passFail")
                    or clue_reviews["hard"]["pass_fail"]
                    or ""
                ).strip().casefold()
                if hard_pass_fail not in {"pass", "fail"}:
                    hard_pass_fail = ""
                clean_rows.append(
                    {
                        "rank": row.get("rank"),
                        "review_phase": str(row.get("review_phase") or "").strip(),
                        "place": str(row.get("place") or "").strip(),
                        "machine_score": row.get("machine_score"),
                        "ml_score": row.get("ml_score"),
                        "ml_confidence": row.get("ml_confidence"),
                        "ml_rank_score": row.get("ml_rank_score"),
                        "your_score": row.get("your_score"),
                        "notes": str(row.get("notes") or "").strip(),
                        "type": str(row.get("type") or "").strip(),
                        "difficulty": str(row.get("difficulty") or "").strip(),
                        "categories": str(row.get("categories") or "").strip(),
                        "source": str(row.get("source") or "").strip(),
                        "candidate_id": str(row.get("candidate_id") or "").strip(),
                        "facts": [
                            str(fact).strip()
                            for fact in row.get("facts", [])
                            if str(fact).strip()
                        ]
                        if isinstance(row.get("facts"), list)
                        else [],
                        "clue_uses": clue_uses,
                        "clue_scores": {
                            str(level).strip(): score
                            for level, score in clue_scores_source.items()
                            if str(level).strip()
                        },
                        "clue_reviews": clue_reviews,
                        "overall_review": {
                            "pass_fail": overall_verdict,
                            "reason": str(overall_review_source.get("reason") or "").strip(),
                        },
                        "clues": {
                            "hard": str(clues.get("hard") or "").strip(),
                            "medium": str(clues.get("medium") or "").strip(),
                            "easy": str(clues.get("easy") or "").strip(),
                            "reveal": str(clues.get("reveal") or "").strip(),
                        },
                        "hard_review": {
                            "level": "Hard",
                            "clue": str(
                                hard_review_source.get("clue")
                                or clue_reviews["hard"]["clue"]
                                or ""
                            ).strip(),
                            "fact": str(hard_review_source.get("fact") or "").strip(),
                            "pass_fail": hard_pass_fail,
                            "reason": str(
                                hard_review_source.get("reason")
                                or clue_reviews["hard"]["reason"]
                                or ""
                            ).strip(),
                            "better_direction": str(
                                hard_review_source.get("better_direction")
                                or hard_review_source.get("betterDirection")
                                or ""
                            ).strip(),
                        },
                        "why_fun": str(row.get("why_fun") or "").strip(),
                        "map_guessability": str(row.get("map_guessability") or "").strip(),
                    }
                )
            output_dir = DATA_DIR / "training"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"map_place_review_feedback_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
            output_path.write_text(
                json.dumps(
                    {
                        "created_at": utc_now(),
                        "row_count": len(clean_rows),
                        "rows": clean_rows,
                    },
                    indent=2,
                    ensure_ascii=True,
                ),
                encoding="utf-8",
            )
            consolidated_path = training_data_store.consolidated_map_place_review_feedback_file(output_dir)
            try:
                with MAP_LEARNING_REFRESH_LOCK:
                    consolidated_path = training_data_store.write_consolidated_map_place_review_feedback(
                        output_dir
                    )
                    training_summary = refresh_map_learning_after_review(output_dir)
            except Exception as error:
                safe_log(f"Map review was saved but model refresh failed: {error}")
                training_summary = {
                    "ok": False,
                    "error": str(error),
                }
            else:
                training_summary["ok"] = True
            try:
                with connect_db() as audit_conn:
                    record_audit_event(
                        audit_conn,
                        "map.review_feedback.save",
                        actor_user_id=review_actor_user_id,
                        client_ip=self.client_ip(),
                        details={
                            "source": review_source,
                            "rowCount": len(clean_rows),
                            "trainingRefreshOk": bool(training_summary.get("ok")),
                        },
                    )
            except Exception as error:
                safe_log(f"Map review audit record failed: {error}")
            self.send_json(
                HTTPStatus.CREATED,
                {
                    "ok": True,
                    "rowCount": len(clean_rows),
                    "path": str(output_path),
                    "consolidatedPath": str(consolidated_path),
                    "training": training_summary,
                },
            )
            return

        if path == "/internal/regenerate-daily-quiz-question" and method == "POST":
            configured_token = DAILY_QUIZ_CONFIG.internal_token
            submitted_token = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            if not configured_token:
                self.send_error_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "Internal quiz generation token is not configured.",
                )
                return
            if not hmac.compare_digest(submitted_token, configured_token):
                self.send_error_json(HTTPStatus.UNAUTHORIZED, "Invalid internal token.")
                return
            payload = self.read_json()
            quiz_date = str(payload.get("date") or today_game_date()).strip()
            subject = str(payload.get("subject") or "").strip()
            difficulty = str(payload.get("difficulty") or "").strip()
            with DAILY_QUIZ_OPERATION_LOCK:
                with connect_db() as conn:
                    result = daily_quiz.regenerate_question(
                        conn,
                        quiz_date=quiz_date,
                        subject=subject,
                        difficulty=difficulty,
                        config=DAILY_QUIZ_CONFIG,
                        log=safe_log,
                    )
                    if result.get("status") == "published" and "questions" not in result:
                        full_payload = daily_quiz.quiz_questions_payload(conn, quiz_date)
                        full_payload.update(
                            {
                                key: value
                                for key, value in result.items()
                                if key.startswith("regeneration_")
                            }
                        )
                        result = full_payload
                    record_audit_event(
                        conn,
                        "quiz.question_regenerate.internal",
                        client_ip=self.client_ip(),
                        details={
                            "date": quiz_date,
                            "subject": subject[:64],
                            "difficulty": difficulty[:32],
                            "status": str(result.get("status") or "unknown")[:64],
                            "blocked": bool(result.get("regeneration_blocked")),
                            "failed": bool(result.get("regeneration_failed")),
                        },
                    )
            status = (
                HTTPStatus.CONFLICT
                if result.get("regeneration_blocked")
                else (
                    HTTPStatus.OK
                    if result.get("status") == "published"
                    and not result.get("regeneration_failed")
                    else HTTPStatus.SERVICE_UNAVAILABLE
                )
            )
            self.send_json(status, result)
            return

        with connect_db() as conn:
            token = get_cookie_value(self.headers, SESSION_COOKIE)
            user = current_user(conn, token)

            if path == "/api/auth/login" and method == "POST":
                self.handle_login(conn)
                return

            if path == "/api/auth/logout" and method == "POST":
                if token is not None:
                    if user is not None:
                        record_audit_event(
                            conn,
                            "auth.logout",
                            actor_user_id=int(user["id"]),
                            target_user_id=int(user["id"]),
                            client_ip=self.client_ip(),
                        )
                    conn.execute(
                        "DELETE FROM sessions WHERE token = ?",
                        (session_token_digest(token),),
                    )
                self.send_json(
                    HTTPStatus.OK,
                    {"ok": True},
                    {"Set-Cookie": clear_session_header()},
                )
                return

            if path == "/api/auth/me" and method == "GET":
                if user is None:
                    self.send_error_json(HTTPStatus.UNAUTHORIZED, "Login required.")
                    return
                self.send_json(HTTPStatus.OK, auth_payload(conn, user))
                return

            if user is None:
                self.send_error_json(HTTPStatus.UNAUTHORIZED, "Login required.")
                return

            announcement_match = re.fullmatch(
                r"/api/announcements/([^/]+)/acknowledge",
                path,
            )
            if announcement_match and method == "POST":
                campaign_id = announcement_match.group(1)
                if (
                    campaign_id != MAP_PROMO_CAMPAIGN_ID
                    or not campaign_id
                    or not map_promo_is_available()
                ):
                    self.send_error_json(HTTPStatus.NOT_FOUND, "Announcement not found.")
                    return
                payload = self.read_json()
                action = str(payload.get("action") or "").strip().lower()
                if action not in {"played", "dismissed"}:
                    self.send_error_json(
                        HTTPStatus.BAD_REQUEST,
                        "Announcement action must be played or dismissed.",
                    )
                    return
                conn.execute(
                    """
                    INSERT INTO user_announcement_acknowledgements (
                        user_id, campaign_id, action, acknowledged_at
                    )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id, campaign_id) DO UPDATE SET
                        action = excluded.action,
                        acknowledged_at = excluded.acknowledged_at
                    """,
                    (user["id"], campaign_id, action, utc_now()),
                )
                self.send_json(HTTPStatus.OK, {"ok": True})
                return

            if path == "/api/me" and method == "PATCH":
                self.handle_update_me(conn, user, token)
                return

            if path == "/api/wordle/today" and method == "POST":
                game = ensure_daily_game(conn)
                self.send_json(
                    HTTPStatus.OK,
                    serialize_wordle_state(conn, user["id"], game),
                )
                return

            if path == "/api/wordle/today" and method == "GET":
                game = conn.execute(
                    "SELECT * FROM daily_wordle_games WHERE game_date = ?",
                    (today_game_date(),),
                ).fetchone()
                state = (
                    existing_wordle_state(conn, user["id"], game)
                    if game is not None
                    else None
                )
                if state is None:
                    self.send_error_json(
                        HTTPStatus.NOT_FOUND,
                        "Today's Wordle has not been started.",
                    )
                    return
                self.send_json(HTTPStatus.OK, state)
                return

            if path == "/api/wordle/definition" and method == "GET":
                game = conn.execute(
                    "SELECT * FROM daily_wordle_games WHERE game_date = ?",
                    (today_game_date(),),
                ).fetchone()
                if game is None:
                    self.send_error_json(HTTPStatus.NOT_FOUND, "Today's Wordle has not been started.")
                    return
                assignment = wordle_assignment_row(conn, user["id"], game["id"])
                result = existing_wordle_result(conn, user["id"], game["id"])
                if assignment is None or result is None:
                    self.send_error_json(HTTPStatus.NOT_FOUND, "Today's Wordle has not been started.")
                    return
                if result["status"] == "in_progress":
                    self.send_error_json(
                        HTTPStatus.CONFLICT,
                        "Finish today's Wordle before requesting its definition.",
                    )
                    return
                self.send_json(HTTPStatus.OK, word_definition(assignment["secret_word"]))
                return

            if path == "/api/daily-quiz" and method == "GET":
                current_quiz_date = today_game_date()
                quiz_date = str(params.get("date", [current_quiz_date])[0]).strip()
                if quiz_date != current_quiz_date:
                    self.send_error_json(
                        HTTPStatus.NOT_FOUND,
                        "Only today's published quiz is available.",
                    )
                    return
                try:
                    daily_quiz.lock_published_quiz_for_play(conn, quiz_date)
                    self.send_json(HTTPStatus.OK, {
                        **daily_quiz.quiz_payload(conn, quiz_date),
                        **daily_quiz_player_state(conn, user["id"], quiz_date),
                    })
                except (LookupError, ValueError):
                    self.send_error_json(HTTPStatus.NOT_FOUND, "No published quiz exists for that date.")
                return

            if path == "/api/quiz/board" and method == "GET":
                mode = str(params.get("mode", ["daily"])[0]).strip().lower()
                if mode not in {"daily", "practice"}:
                    self.send_error_json(HTTPStatus.BAD_REQUEST, "Quiz mode must be daily or practice.")
                    return
                try:
                    board = quiz_board.ensure_board(
                        conn, int(user["id"]), today_game_date(), mode, utc_now()
                    )
                    self.send_json(HTTPStatus.OK, quiz_board.board_payload(conn, board))
                except LookupError as error:
                    self.send_error_json(HTTPStatus.NOT_FOUND, str(error))
                return

            if path == "/api/quiz/board/select" and method == "POST":
                payload = self.read_json()
                mode = str(payload.get("mode") or "daily").strip().lower()
                try:
                    board = quiz_board.ensure_board(
                        conn, int(user["id"]), today_game_date(), mode, utc_now()
                    )
                    response = quiz_board.select_card(
                        conn, board, str(payload.get("cardId") or ""), utc_now()
                    )
                    self.send_json(HTTPStatus.OK, response)
                except (LookupError, ValueError) as error:
                    self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
                return

            if path == "/api/quiz/board/answer" and method == "POST":
                payload = self.read_json()
                mode = str(payload.get("mode") or "daily").strip().lower()
                try:
                    board = quiz_board.ensure_board(
                        conn, int(user["id"]), today_game_date(), mode, utc_now()
                    )
                    response = quiz_board.answer_card(
                        conn,
                        board,
                        str(payload.get("cardId") or ""),
                        str(payload.get("choiceId") or ""),
                        utc_now(),
                    )
                    self.send_json(HTTPStatus.OK, response)
                except (LookupError, ValueError) as error:
                    self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
                return

            if path == "/api/feedback" and method == "POST":
                payload = self.read_json()
                try:
                    quiz_board.save_feedback(
                        conn,
                        int(user["id"]),
                        today_game_date(),
                        str(payload.get("game") or ""),
                        str(payload.get("rating") or ""),
                        utc_now(),
                    )
                    self.send_json(HTTPStatus.OK, {"ok": True})
                except ValueError as error:
                    self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
                return

            if path == "/api/today" and method == "GET":
                import playability
                self.send_json(HTTPStatus.OK, playability.today_payload(conn, user["id"], today_game_date(), SERVER_TZ))
                return

            if path == "/api/practice/quizzes" and method == "GET":
                dates = [row[0] for row in conn.execute(
                    "SELECT quiz_date FROM daily_quiz_sets WHERE status = 'published' AND quiz_date < ? "
                    "ORDER BY quiz_date DESC LIMIT 30", (today_game_date(),),
                )]
                self.send_json(HTTPStatus.OK, {"dates": dates})
                return

            if path == "/api/practice/quiz" and method == "GET":
                practice_date = str(params.get("date", [""])[0])
                try:
                    if datetime.strptime(practice_date, "%Y-%m-%d").date().isoformat() >= today_game_date():
                        raise ValueError("Practice uses past rounds only.")
                    self.send_json(HTTPStatus.OK, daily_quiz.quiz_payload(conn, practice_date))
                except (LookupError, ValueError):
                    self.send_error_json(HTTPStatus.NOT_FOUND, "Choose an available past round.")
                return

            if path == "/api/practice/quiz/result" and method == "POST":
                payload = self.read_json()
                practice_date = str(payload.get("date", ""))
                category = str(payload.get("category", ""))
                try:
                    if datetime.strptime(practice_date, "%Y-%m-%d").date().isoformat() >= today_game_date():
                        raise ValueError("Practice uses past rounds only.")
                    answers = payload.get("answers")
                    if not isinstance(answers, list) or len(answers) > QUIZ_MAX_SUBMITTED_ANSWERS:
                        raise ValueError("Quiz answers must be a bounded list.")
                    questions = quiz_category_questions(conn, practice_date, category)
                    _, adjudications, totals = adjudicate_quiz_answers(questions, answers)
                    self.send_json(HTTPStatus.OK, {"result": {
                        **totals, "date": practice_date, "category": category,
                        "quizVersion": quiz_content_version(questions), "scoringVersion": "practice-only",
                        "adjudications": adjudications, "completedAt": utc_now(),
                    }})
                except (LookupError, ValueError) as error:
                    self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
                return

            if path == "/api/league" and method == "GET":
                import playability
                self.send_json(HTTPStatus.OK, playability.league_payload(conn, today_game_date(), SERVER_TZ))
                return

            if path == "/api/daily-quiz/progress" and method == "POST":
                payload = self.read_json()
                result_payload, status = save_daily_quiz_progress(
                    conn, user["id"], str(payload.get("date", "")),
                    str(payload.get("category", "")), payload.get("answers"),
                )
                self.send_json(status, result_payload)
                return

            if path == "/api/daily-quiz/result" and method == "POST":
                payload = self.read_json()
                game_date = str(payload.get("date", "")).strip()
                category = str(payload.get("category", "")).strip()
                result_payload, status = save_daily_quiz_result(
                    conn,
                    user["id"],
                    game_date,
                    category,
                    payload.get("answers"),
                )
                self.send_json(status, result_payload)
                return

            if path == "/api/daily-map-game" and method == "GET":
                requested_date = str(params.get("date", [""])[0]).strip()
                try:
                    normalized_date = (
                        daily_map_game.valid_game_date(requested_date)
                        if DAILY_MAP_FUTURE_REVIEW_ENABLED and requested_date
                        else daily_map_game.playable_map_round_date(conn, today_game_date())
                    )
                    if not daily_map_date_is_requestable(normalized_date):
                        self.send_error_json(
                            HTTPStatus.NOT_FOUND,
                            "No published map game exists for that date.",
                        )
                        return
                    self.send_json(
                        HTTPStatus.OK,
                        daily_map_game.daily_bundle_payload(
                            conn,
                            puzzle_date=normalized_date,
                            user_id=user["id"],
                        ),
                    )
                except LookupError:
                    self.send_error_json(
                        HTTPStatus.NOT_FOUND,
                        "No published map game exists for that date.",
                    )
                return

            if path == "/api/leaderboard" and method == "GET":
                self.send_json(HTTPStatus.OK, leaderboard_payload(conn))
                return

            validate_match = re.fullmatch(r"/api/wordle/validate/([A-Za-z]+)", path)
            if validate_match is not None and method == "GET":
                guess = validate_match.group(1).lower()
                self.send_json(HTTPStatus.OK, {"valid": valid_guess(guess)})
                return

            if path == "/api/wordle/guess" and method == "POST":
                self.handle_wordle_guess(conn, user)
                return

            map_snap_match = re.fullmatch(r"/api/daily-map-game/(\d+)/snap", path)
            if map_snap_match is not None and method == "POST":
                payload = self.read_json()
                level_id = int(map_snap_match.group(1))
                if not daily_map_level_is_requestable(conn, level_id):
                    self.send_error_json(HTTPStatus.NOT_FOUND, "This map round is not available.")
                    return
                selection_payload, status = daily_map_game.snap_guess(
                    conn,
                    user_id=user["id"],
                    level_id=level_id,
                    lat=payload.get("lat"),
                    lng=payload.get("lng"),
                    zoom=payload.get("zoom"),
                    today=daily_map_submission_date(conn, level_id),
                )
                if status == HTTPStatus.OK:
                    conn.commit()
                self.send_json(status, selection_payload)
                return

            map_reveal_match = re.fullmatch(r"/api/daily-map-game/(\d+)/reveal", path)
            if map_reveal_match is not None and method == "POST":
                payload = self.read_json()
                level_id = int(map_reveal_match.group(1))
                if not daily_map_level_is_requestable(conn, level_id):
                    self.send_error_json(HTTPStatus.NOT_FOUND, "This map round is not available.")
                    return
                reveal_payload, status = daily_map_game.reveal_next_clue(
                    conn,
                    user_id=user["id"],
                    level_id=level_id,
                    expected_revealed_hint_count=payload.get(
                        "expectedRevealedHintCount"
                    ),
                    today=daily_map_submission_date(conn, level_id),
                )
                if status == HTTPStatus.OK:
                    conn.commit()
                self.send_json(status, reveal_payload)
                return

            map_guess_match = re.fullmatch(r"/api/daily-map-game/(\d+)/guess", path)
            if map_guess_match is not None and method == "POST":
                payload = self.read_json()
                level_id = int(map_guess_match.group(1))
                if not daily_map_level_is_requestable(conn, level_id):
                    self.send_error_json(HTTPStatus.NOT_FOUND, "This map round is not available.")
                    return
                result_payload, status = daily_map_game.submit_guess(
                    conn,
                    user_id=user["id"],
                    level_id=level_id,
                    selection_id=payload.get("selectionId"),
                    today=daily_map_submission_date(conn, level_id),
                )
                if status in {HTTPStatus.OK, HTTPStatus.CREATED}:
                    conn.commit()
                    result = result_payload.get("result")
                    if isinstance(result, dict):
                        safe_log(
                            "Daily map guess saved "
                            f"user={user['id']} level={level_id} "
                            f"score={result.get('score')} band={result.get('band')}"
                        )
                self.send_json(status, result_payload)
                return

            if path == "/api/admin/daily-quiz-status" and method == "GET":
                if user["role"] != "admin":
                    self.send_error_json(HTTPStatus.FORBIDDEN, "Admin access required.")
                    return
                quiz_date = str(params.get("date", [today_game_date()])[0]).strip()
                self.send_json(HTTPStatus.OK, daily_quiz.quiz_status(conn, quiz_date))
                return

            if path == "/api/admin/product-report" and method == "GET":
                if user["role"] != "admin":
                    self.send_error_json(HTTPStatus.FORBIDDEN, "Admin access required.")
                    return
                end = str(params.get("end", [today_game_date()])[0]).strip()
                start = str(params.get("start", [(date.fromisoformat(end) - timedelta(days=6)).isoformat()])[0]).strip()
                try:
                    date.fromisoformat(start)
                    date.fromisoformat(end)
                except ValueError:
                    self.send_error_json(HTTPStatus.BAD_REQUEST, "Report dates must use YYYY-MM-DD.")
                    return
                self.send_json(HTTPStatus.OK, quiz_board.admin_report(conn, start, end))
                return

            if path == "/api/admin/daily-map-game-status" and method == "GET":
                if user["role"] != "admin":
                    self.send_error_json(HTTPStatus.FORBIDDEN, "Admin access required.")
                    return
                puzzle_date = str(params.get("date", [today_game_date()])[0]).strip()
                self.send_json(HTTPStatus.OK, daily_map_game.puzzle_status(conn, puzzle_date))
                return

            if path == "/api/admin/daily-map-clues" and method in {"GET", "POST"}:
                if user["role"] != "admin":
                    self.send_error_json(HTTPStatus.FORBIDDEN, "Admin access required.")
                    return
                if method == "GET":
                    puzzle_date = str(params.get("date", [today_game_date()])[0]).strip()
                    try:
                        result = map_clue_editor.admin_puzzle_clues(conn, puzzle_date)
                    except ValueError as error:
                        self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
                        return
                    self.send_json(HTTPStatus.OK, result)
                    return
                payload = self.read_json()
                puzzle_date = str(payload.get("date") or today_game_date()).strip()
                try:
                    with DAILY_MAP_GAME_OPERATION_LOCK:
                        result = map_clue_editor.revise_published_clues(
                            conn,
                            puzzle_date=puzzle_date,
                            level_slug=payload.get("level"),
                            expected_place_id=payload.get("expectedPlaceId"),
                            clues=payload.get("clues"),
                            reason=payload.get("reason"),
                        )
                except ValueError as error:
                    self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
                    return
                except LookupError as error:
                    self.send_error_json(HTTPStatus.NOT_FOUND, str(error))
                    return
                except RuntimeError as error:
                    conn.rollback()
                    self.send_error_json(HTTPStatus.CONFLICT, str(error))
                    return
                record_audit_event(
                    conn,
                    "map.clues_revised.admin",
                    actor_user_id=int(user["id"]),
                    client_ip=self.client_ip(),
                    details={"date": puzzle_date, "level": str(payload.get("level"))[:16]},
                )
                conn.commit()
                try:
                    result["learning"] = refresh_map_learning_from_corrections()
                except Exception as error:
                    safe_log(f"Map clues saved but learning refresh failed: {error}")
                    result["learning"] = {"ok": False, "message": "Learning refresh is pending."}
                self.send_json(HTTPStatus.OK, result)
                return

            if path == "/api/admin/question-attempts" and method == "GET":
                if user["role"] != "admin":
                    self.send_error_json(HTTPStatus.FORBIDDEN, "Admin access required.")
                    return
                quiz_date = str(params.get("date", [today_game_date()])[0]).strip()
                self.send_json(HTTPStatus.OK, daily_quiz.question_attempts(conn, quiz_date))
                return

            if path == "/api/admin/regenerate-question" and method == "POST":
                if user["role"] != "admin":
                    self.send_error_json(HTTPStatus.FORBIDDEN, "Admin access required.")
                    return
                payload = self.read_json()
                quiz_date = str(payload.get("date") or today_game_date())
                with DAILY_QUIZ_OPERATION_LOCK:
                    result = daily_quiz.regenerate_question(
                        conn,
                        quiz_date=quiz_date,
                        subject=str(payload.get("subject") or ""),
                        difficulty=str(payload.get("difficulty") or ""),
                        config=DAILY_QUIZ_CONFIG,
                        log=safe_log,
                    )
                    if result.get("status") == "published" and "questions" not in result:
                        full_payload = daily_quiz.quiz_questions_payload(conn, quiz_date)
                        full_payload.update(
                            {
                                key: value
                                for key, value in result.items()
                                if key.startswith("regeneration_")
                            }
                        )
                        result = full_payload
                record_audit_event(
                    conn,
                    "quiz.question_regenerate.admin",
                    actor_user_id=int(user["id"]),
                    client_ip=self.client_ip(),
                    details={
                        "date": quiz_date,
                        "subject": str(payload.get("subject") or "")[:64],
                        "difficulty": str(payload.get("difficulty") or "")[:32],
                        "status": str(result.get("status") or "unknown")[:64],
                        "blocked": bool(result.get("regeneration_blocked")),
                        "failed": bool(result.get("regeneration_failed")),
                    },
                )
                status = (
                    HTTPStatus.CONFLICT
                    if result.get("regeneration_blocked")
                    else (
                        HTTPStatus.SERVICE_UNAVAILABLE
                        if result.get("regeneration_failed")
                        else HTTPStatus.OK
                    )
                )
                self.send_json(status, result)
                return

            if path == "/api/admin/publish-quiz" and method == "POST":
                if user["role"] != "admin":
                    self.send_error_json(HTTPStatus.FORBIDDEN, "Admin access required.")
                    return
                payload = self.read_json()
                quiz_date = str(payload.get("date") or today_game_date())
                with DAILY_QUIZ_OPERATION_LOCK:
                    result = daily_quiz.publish_quiz(conn, quiz_date)
                record_audit_event(
                    conn,
                    "quiz.publish.admin",
                    actor_user_id=int(user["id"]),
                    client_ip=self.client_ip(),
                    details={
                        "date": quiz_date,
                        "status": str(result.get("status") or "unknown")[:64],
                    },
                )
                self.send_json(HTTPStatus.OK, result)
                return

            if path.startswith("/api/admin/"):
                player_management_route = (
                    path == "/api/admin/users" and method in {"GET", "POST"}
                ) or (
                    method == "DELETE"
                    and re.fullmatch(r"/api/admin/users/\d+", path) is not None
                )
                if user["role"] != "admin" and not (
                    player_management_route and user_can_manage_players(user)
                ):
                    self.send_error_json(HTTPStatus.FORBIDDEN, "Admin access required.")
                    return
                self.handle_admin(conn, user, method, path)
                return

            self.send_error_json(HTTPStatus.NOT_FOUND, "API route not found.")

    def query_int(
        self,
        params: dict[str, list[str]],
        name: str,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        raw_value = params.get(name, [str(default)])[0]
        try:
            value = int(raw_value)
        except ValueError:
            return default
        return max(minimum, min(maximum, value))

    def handle_news_add(self, conn: sqlite3.Connection) -> None:
        if not NEWS_MONITOR_KEY:
            self.send_error_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "News monitor key is not configured.",
            )
            return

        submitted_key = self.headers.get("X-News-Monitor-Key", "")
        if not hmac.compare_digest(submitted_key, NEWS_MONITOR_KEY):
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Invalid news monitor key.")
            return

        item, inserted = upsert_news_item(conn, self.read_json())
        if inserted:
            broadcast_news_item(item)
        self.send_json(
            HTTPStatus.CREATED if inserted else HTTPStatus.OK,
            {"item": item, "inserted": inserted},
        )

    def handle_news_stream(self) -> None:
        stream: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=25)
        with NEWS_STREAMS_LOCK:
            if len(NEWS_STREAMS) >= NEWS_STREAM_LIMIT:
                self.send_error_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "Too many live news streams.",
                )
                return
            NEWS_STREAMS.add(stream)

        try:
            self.send_sse_headers()
            self.write_sse("ready", {"ok": True, "date": today_game_date()})

            while True:
                try:
                    item = stream.get(timeout=20)
                    self.write_sse("news", item)
                except queue.Empty:
                    self.write_sse("ping", {"date": utc_now()})
        finally:
            with NEWS_STREAMS_LOCK:
                NEWS_STREAMS.discard(stream)

    def handle_login(self, conn: sqlite3.Connection) -> None:
        payload = self.read_json()
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", ""))
        lookup_username = username if len(username) <= 32 else ""
        password_to_verify = password if len(password) <= 512 else password[:512]
        client_ip = self.client_ip()

        if is_login_locked(username, client_ip):
            self.send_error_json(
                HTTPStatus.TOO_MANY_REQUESTS,
                "Too many login attempts. Try again later.",
            )
            return

        user = conn.execute(
            "SELECT * FROM users WHERE LOWER(username) = LOWER(?)",
            (lookup_username,),
        ).fetchone()
        stored_hash = user["password_hash"] if user is not None else DUMMY_PASSWORD_HASH
        if not LOGIN_VERIFY_SEMAPHORE.acquire(blocking=False):
            self.send_error_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "Authentication service is busy. Try again shortly.",
            )
            return
        try:
            password_matches = verify_password(password_to_verify, stored_hash)
        finally:
            LOGIN_VERIFY_SEMAPHORE.release()
        if user is None or not password_matches or len(password) > 512:
            record_login_failure(username, client_ip)
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Invalid username or password.")
            return

        clear_login_failures(username, client_ip)
        token = create_session(conn, user["id"])
        record_audit_event(
            conn,
            "auth.login",
            actor_user_id=int(user["id"]),
            target_user_id=int(user["id"]),
            client_ip=client_ip,
        )
        self.send_json(
            HTTPStatus.OK,
            auth_payload(conn, user),
            {"Set-Cookie": session_header(token)},
        )

    def handle_update_me(
        self,
        conn: sqlite3.Connection,
        user: sqlite3.Row,
        current_token: str | None = None,
    ) -> None:
        payload = self.read_json()
        new_username = payload.get("username")
        current_password = str(payload.get("currentPassword", ""))
        new_password = payload.get("newPassword")
        now = utc_now()

        normalized_username = (
            str(new_username).strip() if new_username is not None else str(user["username"])
        )
        username_error = validate_username(normalized_username)
        if username_error is not None:
            self.send_error_json(HTTPStatus.BAD_REQUEST, username_error)
            return

        password_requested = new_password is not None and bool(str(new_password))
        password_hash = str(user["password_hash"])
        if password_requested:
            password = str(new_password)
            password_error = validate_password(password)
            if password_error is not None:
                self.send_error_json(HTTPStatus.BAD_REQUEST, password_error)
                return

            if not verify_password(current_password, user["password_hash"]):
                self.send_error_json(HTTPStatus.UNAUTHORIZED, "Current password is incorrect.")
                return

            password_hash = hash_password(password)

        conflict = conn.execute(
            "SELECT 1 FROM users WHERE LOWER(username) = LOWER(?) AND id != ?",
            (normalized_username, user["id"]),
        ).fetchone()
        if conflict is not None:
            self.send_error_json(HTTPStatus.CONFLICT, "Username is already taken.")
            return

        try:
            conn.execute(
                """
                UPDATE users
                SET username = ?, password_hash = ?, updated_at = ?
                WHERE id = ?
                """,
                (normalized_username, password_hash, now, user["id"]),
            )
        except sqlite3.IntegrityError:
            self.send_error_json(HTTPStatus.CONFLICT, "Username is already taken.")
            return

        response_headers = None
        if password_requested:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
            replacement_token = create_session(conn, user["id"])
            response_headers = {"Set-Cookie": session_header(replacement_token)}

        record_audit_event(
            conn,
            "account.profile_update",
            actor_user_id=int(user["id"]),
            target_user_id=int(user["id"]),
            client_ip=self.client_ip(),
            details={
                "usernameChanged": normalized_username != str(user["username"]),
                "passwordChanged": password_requested,
                "sessionsRotated": password_requested,
            },
        )

        updated_user = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        self.send_json(
            HTTPStatus.OK,
            {"user": user_payload(updated_user)},
            response_headers,
        )

    def handle_wordle_guess(self, conn: sqlite3.Connection, user: sqlite3.Row) -> None:
        payload = self.read_json()
        raw_guess = payload.get("guess")
        if not isinstance(raw_guess, str) or len(raw_guess) > WORD_LENGTH:
            self.send_error_json(
                HTTPStatus.BAD_REQUEST,
                "Enter a valid five-letter word from the game list.",
            )
            return
        guess = raw_guess.strip().lower()

        if not valid_guess(guess):
            self.send_error_json(
                HTTPStatus.BAD_REQUEST,
                "Enter a valid five-letter word from the game list.",
            )
            return
        result_payload, status = submit_wordle_guess(
            conn,
            int(user["id"]),
            guess,
            payload.get("expectedAttemptsUsed"),
            payload.get("expectedGameDate"),
        )
        self.send_json(status, result_payload)

    def handle_admin(
        self,
        conn: sqlite3.Connection,
        user: sqlite3.Row,
        method: str,
        path: str,
    ) -> None:
        if path == "/api/admin/users" and method == "GET":
            rows = conn.execute(
                """
                SELECT
                    users.id,
                    users.username,
                    users.role,
                    users.is_moderator,
                    users.created_at,
                    SUM(CASE WHEN wordle_results.status IN ('won', 'lost') THEN 1 ELSE 0 END)
                        AS games_played,
                    SUM(CASE WHEN wordle_results.status = 'won' THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN wordle_results.status = 'lost' THEN 1 ELSE 0 END) AS losses
                FROM users
                LEFT JOIN wordle_results ON wordle_results.user_id = users.id
                WHERE ? = 'admin' OR (users.role = 'user' AND users.is_moderator = 0)
                GROUP BY users.id
                ORDER BY users.role ASC, LOWER(users.username)
                """
                ,
                (user["role"],),
            ).fetchall()
            self.send_json(HTTPStatus.OK, {"users": [admin_user_payload(row) for row in rows]})
            return

        if path == "/api/admin/users" and method == "POST":
            payload = self.read_json()
            username = str(payload.get("username", "")).strip()
            password = str(payload.get("password", ""))
            role = str(payload.get("role", "user"))

            username_error = validate_username(username)
            password_error = validate_password(password)
            if username_error is not None:
                self.send_error_json(HTTPStatus.BAD_REQUEST, username_error)
                return
            if password_error is not None:
                self.send_error_json(HTTPStatus.BAD_REQUEST, password_error)
                return
            if role not in {"admin", "mod", "user"}:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "Role must be admin, mod, or user.")
                return
            if user["role"] != "admin" and role != "user":
                self.send_error_json(HTTPStatus.FORBIDDEN, "Moderators can only add players.")
                return

            now = utc_now()
            stored_role = "admin" if role == "admin" else "user"
            is_moderator = 1 if role == "mod" else 0
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO users (
                        username, password_hash, role, is_moderator, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (username, hash_password(password), stored_role, is_moderator, now, now),
                )
            except sqlite3.IntegrityError:
                self.send_error_json(HTTPStatus.CONFLICT, "Username is already taken.")
                return

            target_id = int(cursor.lastrowid)
            record_audit_event(
                conn,
                "admin.user_create",
                actor_user_id=int(user["id"]),
                target_user_id=target_id,
                client_ip=self.client_ip(),
                details={"role": role},
            )
            self.send_json(HTTPStatus.CREATED, {"ok": True})
            return

        reset_match = re.fullmatch(r"/api/admin/users/(\d+)/reset-password", path)
        if reset_match is not None and method == "POST":
            if user["role"] != "admin":
                self.send_error_json(HTTPStatus.FORBIDDEN, "Admin access required.")
                return
            target_id = int(reset_match.group(1))
            payload = self.read_json()
            password = str(payload.get("password", ""))
            password_error = validate_password(password)
            if password_error is not None:
                self.send_error_json(HTTPStatus.BAD_REQUEST, password_error)
                return

            cursor = conn.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (hash_password(password), utc_now(), target_id),
            )
            if cursor.rowcount == 0:
                self.send_error_json(HTTPStatus.NOT_FOUND, "User not found.")
                return

            conn.execute("DELETE FROM sessions WHERE user_id = ?", (target_id,))
            record_audit_event(
                conn,
                "admin.password_reset",
                actor_user_id=int(user["id"]),
                target_user_id=target_id,
                client_ip=self.client_ip(),
                details={"sessionsRevoked": True},
            )
            self.send_json(HTTPStatus.OK, {"ok": True})
            return

        delete_match = re.fullmatch(r"/api/admin/users/(\d+)", path)
        if delete_match is not None and method == "DELETE":
            target_id = int(delete_match.group(1))
            if target_id == user["id"]:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "You cannot delete your own account.")
                return

            target = conn.execute(
                "SELECT role, is_moderator FROM users WHERE id = ?",
                (target_id,),
            ).fetchone()
            if target is None:
                self.send_error_json(HTTPStatus.NOT_FOUND, "User not found.")
                return
            if user["role"] != "admin" and (
                target["role"] != "user" or target["is_moderator"]
            ):
                self.send_error_json(HTTPStatus.FORBIDDEN, "Moderators can only delete players.")
                return

            cursor = conn.execute("DELETE FROM users WHERE id = ?", (target_id,))
            if cursor.rowcount == 0:
                self.send_error_json(HTTPStatus.NOT_FOUND, "User not found.")
                return

            record_audit_event(
                conn,
                "admin.user_delete",
                actor_user_id=int(user["id"]),
                target_user_id=target_id,
                client_ip=self.client_ip(),
                details={
                    "targetRole": str(target["role"]),
                    "targetWasModerator": bool(target["is_moderator"]),
                },
            )
            self.send_json(HTTPStatus.OK, {"ok": True})
            return

        self.send_error_json(HTTPStatus.NOT_FOUND, "Admin route not found.")

    def translate_path(self, path: str) -> str:
        parsed_path = urlparse(path).path
        if parsed_path.startswith("/assets/"):
            target = requested_dist_asset(parsed_path)
            if target is not None:
                return str(target)
            asset_name = Path(parsed_path).name
            suffix = Path(parsed_path).suffix
            if asset_name.startswith("index-"):
                current_asset = current_index_asset(suffix)
                if current_asset is not None:
                    return str(current_asset)
            return str(DIST_DIR / "__missing_asset__")

        if parsed_path == "/" or Path(parsed_path).suffix == "":
            return str(DIST_DIR / "index.html")

        target = requested_dist_asset(parsed_path)
        if target is None:
            return str(DIST_DIR / "index.html")
        return str(target)

    def send_head(self) -> Any:
        self._static_range_remaining = None
        range_header = self.headers.get("Range", "").strip()
        parsed_path = urlparse(self.path).path
        if (
            not range_header
            or Path(parsed_path).suffix.lower() not in STATIC_MEDIA_RANGE_SUFFIXES
        ):
            return super().send_head()

        target = Path(self.translate_path(self.path))
        if not target.is_file():
            return super().send_head()

        file_size = target.stat().st_size
        try:
            start, end = parse_static_byte_range(range_header, file_size)
        except ValueError:
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", f"bytes */{file_size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None

        source = target.open("rb")
        self.send_response(HTTPStatus.PARTIAL_CONTENT)
        self.send_header("Content-Type", self.guess_type(str(target)))
        self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Last-Modified", self.date_time_string(target.stat().st_mtime))
        self.end_headers()
        source.seek(start)
        self._static_range_remaining = end - start + 1
        return source

    def copyfile(self, source: Any, outputfile: Any) -> None:
        remaining = getattr(self, "_static_range_remaining", None)
        if remaining is None:
            super().copyfile(source, outputfile)
            return

        try:
            while remaining > 0:
                chunk = source.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                outputfile.write(chunk)
                remaining -= len(chunk)
        finally:
            self._static_range_remaining = None

    def serve_static(self) -> None:
        if not (DIST_DIR / "index.html").exists():
            self.send_error_json(
                HTTPStatus.NOT_FOUND,
                "Build the frontend first with npm run build, or use npm run dev with the API server.",
            )
            return
        super().do_GET()

    def log_message(self, format: str, *args: Any) -> None:
        safe_log(f"{self.address_string()} - {format % args}")


def ops_map_readiness_test(test_id: str, game_date: str, label: str, map_status: dict[str, Any]) -> dict[str, str]:
    status = str(map_status.get("status") or "missing")
    return {
        "id": test_id,
        "label": label,
        "status": "pass" if status == "published" else "fail",
        "detail": f"{game_date}: {status} / accepted {map_status.get('acceptedLevels', 0)}",
    }


def ops_map_reserve_test(conn: sqlite3.Connection) -> dict[str, str]:
    target_date = automatic_map_pool.next_date(conn)
    publishable = len(automatic_map_pool.eligible(conn, target_date))
    stored = conn.execute(
        "SELECT COUNT(*) FROM automatic_map_entries WHERE state='ready' AND expires_at>?",
        (utc_now(),),
    ).fetchone()[0]
    return {
        "id": "map_reserve",
        "label": "Map reserve queue",
        "status": "pass" if publishable >= automatic_map_pool.TARGET_READY else "warn",
        "detail": (
            f"{publishable}/{automatic_map_pool.TARGET_READY} publishable for {target_date}; "
            f"{stored} unexpired rounds stored"
        ),
    }


def run() -> None:
    assert_runtime_storage_ready("before database initialization")
    training_seed = install_map_training_seed.install_seed(
        Path(os.environ.get("FULTONS_MAP_TRAINING_SEED_DIR", APP_DIR / "map-training-seed")),
        DATA_DIR / "training",
    )
    safe_log(
        "Map training seed: "
        f"copied={len(training_seed['copied'])}, "
        f"feedback_rows_added={training_seed['feedback_rows_added']}"
    )
    initialize_database()
    with closing(connect_db()) as conn:
        with conn:
            fallback_seed = install_map_reviewed_fallbacks.install_seed(
                conn,
                Path(
                    os.environ.get(
                        "FULTONS_MAP_REVIEWED_FALLBACKS_PATH",
                        APP_DIR / "map-reviewed-fallbacks.json",
                    )
                ),
            )
    safe_log(
        "Map reviewed fallbacks: "
        f"added={len(fallback_seed['added'])}, "
        f"updated={len(fallback_seed['updated'])}, "
        f"existing={len(fallback_seed['existing'])}"
    )
    try:
        correction_learning = refresh_map_learning_from_corrections()
        if correction_learning["feedbackRows"]:
            safe_log(
                "Map admin correction learning refreshed: "
                f"{correction_learning['feedbackRows']} feedback row(s)."
            )
    except Exception as error:
        safe_log(f"Map admin correction learning refresh pending: {error}")
    assert_runtime_storage_ready("after database initialization")
    start_daily_quiz_scheduler()
    start_daily_map_game_scheduler()
    start_weekly_product_summary_scheduler()
    server = BoundedThreadingHTTPServer((SERVER_HOST, SERVER_PORT), FultonsHandler)
    safe_log(f"Fulton's Quiz server running at http://{SERVER_HOST}:{SERVER_PORT}")
    safe_log(f"SQLite database: {DB_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    run()
