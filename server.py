from __future__ import annotations

import base64
import hashlib
import html
import hmac
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
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, quote_plus, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

import daily_quiz
import local_ops_settings
import ops_monitor

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
CACHE_VERSION = (
    re.sub(r"[^A-Za-z0-9_.-]", "-", os.environ.get("FULTONS_BUILD_COMMIT", "local"))[:64]
    or "local"
)
SESSION_DAYS = 14
PASSWORD_ITERATIONS = 260_000
USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
SERVER_TZ_NAME = os.environ.get("FULTONS_TIMEZONE", "Europe/London")
NEWS_MONITOR_KEY = os.environ.get("FULTONS_NEWS_MONITOR_KEY", "")
NEWS_LIMIT_DEFAULT = 50
NEWS_LIMIT_MAX = 100
NEWS_MONITOR_ENABLED = os.environ.get("FULTONS_NEWS_MONITOR_ENABLED", "1") != "0"
NEWS_MONITOR_INTERVAL_SEC = max(
    300,
    int(os.environ.get("FULTONS_NEWS_MONITOR_INTERVAL_SEC", "600")),
)
DAILY_QUIZ_SCHEDULER_ENABLED = (
    os.environ.get("FULTONS_DAILY_QUIZ_SCHEDULER_ENABLED", "1") != "0"
)
DAILY_QUIZ_SCHEDULER_HOUR = int(
    os.environ.get("FULTONS_DAILY_QUIZ_SCHEDULER_HOUR", "0")
)
DAILY_QUIZ_SCHEDULER_MINUTE = int(
    os.environ.get("FULTONS_DAILY_QUIZ_SCHEDULER_MINUTE", "5")
)
DAILY_QUIZ_RETRY_INTERVAL_SEC = max(
    60,
    int(os.environ.get("FULTONS_DAILY_QUIZ_RETRY_INTERVAL_SEC", "900")),
)
DAILY_QUIZ_TRANSIENT_RETRY_INTERVAL_SEC = max(
    DAILY_QUIZ_RETRY_INTERVAL_SEC,
    int(os.environ.get("FULTONS_DAILY_QUIZ_TRANSIENT_RETRY_INTERVAL_SEC", "3600")),
)
NEWS_USER_AGENT = os.environ.get(
    "FULTONS_NEWS_USER_AGENT",
    "FultonsQuiz/0.1 (+https://fultons-quiz.co.uk)",
)
HISTORY_USER_AGENT = os.environ.get(
    "UPSTREAM_USER_AGENT",
    "FultonHistory/1.0 (+https://fultons-quiz.co.uk)",
)
HISTORY_CACHE_TTL_SEC = int(os.environ.get("HISTORY_CACHE_TTL_SEC", "86400"))
OPENAI_API_KEY = (
    os.environ.get("FULTONS_OPENAI_API_KEY")
    or os.environ.get("OPENAI_API_KEY")
    or ""
)
OPENAI_MODEL = os.environ.get(
    "FULTONS_OPENAI_MODEL",
    "gpt-4.1-mini",
)
OPENAI_TIMEOUT_SEC = int(os.environ.get("FULTONS_OPENAI_TIMEOUT_SEC", "30"))
FACT_ROTATION_TTL_SEC = int(os.environ.get("FULTONS_FACT_ROTATION_TTL_SEC", "86400"))
FACTS_GEMINI_API_KEY = (
    os.environ.get("FULTONS_FACTS_GEMINI_API_KEY")
    or os.environ.get("GEMINI_API_KEY")
    or ""
)
FACTS_FALLBACK_PROVIDER = os.environ.get(
    "FULTONS_FACTS_FALLBACK_PROVIDER",
    os.environ.get("AI_FALLBACK_PROVIDER", ""),
).strip().lower()
FACTS_FALLBACK_API_KEY = (
    os.environ.get("FULTONS_FACTS_FALLBACK_API_KEY")
    or os.environ.get("AI_FALLBACK_API_KEY")
    or os.environ.get("AI_API_KEY")
    or ""
)
FACTS_FALLBACK_BASE_URL = daily_quiz.default_compatible_base_url(
    FACTS_FALLBACK_PROVIDER,
    os.environ.get(
        "FULTONS_FACTS_FALLBACK_BASE_URL",
        os.environ.get("AI_FALLBACK_BASE_URL", os.environ.get("AI_BASE_URL", "")),
    ),
)
FACTS_FALLBACK2_PROVIDER = os.environ.get(
    "FULTONS_FACTS_FALLBACK2_PROVIDER",
    os.environ.get("AI_FALLBACK2_PROVIDER", ""),
).strip().lower()
FACTS_FALLBACK2_API_KEY = (
    os.environ.get("FULTONS_FACTS_FALLBACK2_API_KEY")
    or os.environ.get("AI_FALLBACK2_API_KEY")
    or os.environ.get("AI_API_KEY")
    or ""
)
FACTS_FALLBACK2_BASE_URL = daily_quiz.default_compatible_base_url(
    FACTS_FALLBACK2_PROVIDER,
    os.environ.get(
        "FULTONS_FACTS_FALLBACK2_BASE_URL",
        os.environ.get("AI_FALLBACK2_BASE_URL", os.environ.get("AI_BASE_URL", "")),
    ),
)
FACTS_AI_GENERATOR_MODEL = os.environ.get(
    "FULTONS_FACTS_AI_GENERATOR_MODEL",
    os.environ.get("AI_GENERATOR_MODEL", "gemini-3.5-flash"),
).strip()
FACTS_AI_CRITIC_MODEL = os.environ.get(
    "FULTONS_FACTS_AI_CRITIC_MODEL",
    os.environ.get("AI_CRITIC_MODEL", "gemini-3.1-flash-lite"),
).strip()
FACTS_FALLBACK_GENERATOR_MODEL = os.environ.get(
    "FULTONS_FACTS_FALLBACK_GENERATOR_MODEL",
    os.environ.get("AI_FALLBACK_GENERATOR_MODEL", ""),
).strip()
FACTS_FALLBACK_CRITIC_MODEL = os.environ.get(
    "FULTONS_FACTS_FALLBACK_CRITIC_MODEL",
    os.environ.get("AI_FALLBACK_CRITIC_MODEL", ""),
).strip()
FACTS_FALLBACK2_GENERATOR_MODEL = os.environ.get(
    "FULTONS_FACTS_FALLBACK2_GENERATOR_MODEL",
    os.environ.get("AI_FALLBACK2_GENERATOR_MODEL", ""),
).strip()
FACTS_FALLBACK2_CRITIC_MODEL = os.environ.get(
    "FULTONS_FACTS_FALLBACK2_CRITIC_MODEL",
    os.environ.get("AI_FALLBACK2_CRITIC_MODEL", ""),
).strip()
FACTS_AI_TIMEOUT_SEC = max(
    3,
    int(os.environ.get("FULTONS_FACTS_AI_TIMEOUT_SEC", "8")),
)
FACTS_AI_REQUEST_DELAY_SEC = max(
    0.0,
    float(
        os.environ.get(
            "FULTONS_FACTS_AI_REQUEST_DELAY_SEC",
            "0.5",
        )
    ),
)
FACTS_AI_TRANSIENT_RETRIES = max(
    0,
    int(
        os.environ.get(
            "FULTONS_FACTS_AI_TRANSIENT_RETRIES",
            "0",
        )
    ),
)
FACTS_AI_GENERATOR_BUDGET_SEC = max(
    4.0,
    float(
        os.environ.get(
            "FULTONS_FACTS_AI_GENERATOR_BUDGET_SEC",
            os.environ.get("FULTONS_FACTS_AI_TOTAL_BUDGET_SEC", "12"),
        )
    ),
)
FACTS_AI_CRITIC_BUDGET_SEC = max(
    2.0,
    float(
        os.environ.get(
            "FULTONS_FACTS_AI_CRITIC_BUDGET_SEC",
            os.environ.get("FULTONS_FACTS_AI_TOTAL_BUDGET_SEC", "6"),
        )
    ),
)
FACTS_WEB_SEARCH_TIMEOUT_SEC = max(
    4,
    int(os.environ.get("FULTONS_FACTS_WEB_SEARCH_TIMEOUT_SEC", "8")),
)
FACT_PREWARM_ENABLED = os.environ.get("FULTONS_FACT_PREWARM_ENABLED", "1") != "0"
FACT_PREWARM_LEAD_SEC = max(
    300,
    int(os.environ.get("FULTONS_FACT_PREWARM_LEAD_SEC", "7200")),
)
FACT_PREWARM_POLL_SEC = max(
    15,
    int(os.environ.get("FULTONS_FACT_PREWARM_POLL_SEC", "60")),
)
FACT_PREWARM_MAX_ATTEMPTS = max(
    1,
    int(os.environ.get("FULTONS_FACT_PREWARM_MAX_ATTEMPTS", "2")),
)
FACT_PREWARM_TIMEOUT_SEC = max(
    FACTS_AI_TIMEOUT_SEC,
    int(os.environ.get("FULTONS_FACT_PREWARM_TIMEOUT_SEC", "12")),
)
FACT_PREWARM_TRANSIENT_RETRIES = max(
    FACTS_AI_TRANSIENT_RETRIES,
    int(os.environ.get("FULTONS_FACT_PREWARM_TRANSIENT_RETRIES", "1")),
)
FACT_PREWARM_GENERATOR_BUDGET_SEC = max(
    FACTS_AI_GENERATOR_BUDGET_SEC,
    float(os.environ.get("FULTONS_FACT_PREWARM_GENERATOR_BUDGET_SEC", "24")),
)
FACT_PREWARM_CRITIC_BUDGET_SEC = max(
    FACTS_AI_CRITIC_BUDGET_SEC,
    float(os.environ.get("FULTONS_FACT_PREWARM_CRITIC_BUDGET_SEC", "12")),
)
FACT_PREWARM_WEB_SEARCH_TIMEOUT_SEC = max(
    FACTS_WEB_SEARCH_TIMEOUT_SEC,
    int(os.environ.get("FULTONS_FACT_PREWARM_WEB_SEARCH_TIMEOUT_SEC", "10")),
)
DAILY_QUIZ_CONFIG = daily_quiz.QuizConfig.from_env()
EXPECTED_DATA_DIR = os.environ.get("FULTONS_EXPECT_DATA_DIR", "").strip()
REQUIRE_EXISTING_DB = os.environ.get("FULTONS_REQUIRE_EXISTING_DB", "0") == "1"
MIN_DB_USERS = int(os.environ.get("FULTONS_MIN_DB_USERS", "0"))
HEALTH_DETAIL = os.environ.get("FULTONS_HEALTH_DETAIL", "0") == "1"
LOCAL_OPS_ENABLED = os.environ.get("FULTONS_LOCAL_OPS_ENABLED", "0") == "1"
COOKIE_SECURE = os.environ.get("FULTONS_COOKIE_SECURE", "0") == "1"
SEED_DEMO_USERS = os.environ.get("FULTONS_SEED_DEMO_USERS", "0") == "1"
BOOTSTRAP_ADMIN_USERNAME = os.environ.get("FULTONS_BOOTSTRAP_ADMIN_USERNAME", "").strip()
BOOTSTRAP_ADMIN_PASSWORD = os.environ.get("FULTONS_BOOTSTRAP_ADMIN_PASSWORD", "")
MIN_PASSWORD_LENGTH = int(os.environ.get("FULTONS_MIN_PASSWORD_LENGTH", "12"))
LOGIN_MAX_FAILURES = int(
    os.environ.get("FULTONS_LOGIN_MAX_FAILURES", os.environ.get("FULTONS_LOGIN_MAX_ATTEMPTS", "5"))
)
LOGIN_LOCKOUT_SECONDS = int(
    os.environ.get(
        "FULTONS_LOGIN_LOCKOUT_SECONDS",
        os.environ.get("FULTONS_LOGIN_BACKOFF_SECONDS", "300"),
    )
)
CORS_ALLOWED_ORIGINS = {
    origin.strip()
    for origin in os.environ.get("FULTONS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
}
WORDLE_POINTS_BY_ATTEMPT = {1: 10, 2: 5, 3: 4, 4: 3, 5: 2, 6: 1}
WORDLE_DIFFICULTY_BONUS_PER_LEVEL = 2
QUIZ_POINTS_BY_DIFFICULTY = {"easy": 1, "medium": 3, "hard": 5}
QUIZ_PERFECT_ROUND_BONUS = 3
WORD_DEFINITION_TIMEOUT_SEC = max(
    1,
    int(os.environ.get("FULTONS_WORD_DEFINITION_TIMEOUT_SEC", "5")),
)
WORD_DEFINITION_CACHE: dict[str, dict[str, Any]] = {}
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
NEWS_QUERIES = tuple(config["query"] for config in NEWS_SCOPED_QUERY_CONFIGS)
SUPPORTED_HISTORY_LANGS = {"en", "fr", "de", "es", "it"}
HISTORY_INTEREST_KEYWORDS = (
    "first",
    "founded",
    "opened",
    "launched",
    "discovered",
    "invented",
    "independence",
    "election",
    "president",
    "prime minister",
    "king",
    "queen",
    "record",
    "award",
    "wins",
    "won",
    "world",
    "historic",
    "landmark",
)
HISTORY_SPORT_KEYWORDS = (
    "football",
    "soccer",
    "cup",
    "league",
    "olympic",
    "olympics",
    "championship",
    "tournament",
    "match",
    "goal",
    "scored",
    "rugby",
    "cricket",
    "tennis",
    "golf",
    "boxing",
    "athletics",
    "racing",
    "sport",
)
HISTORY_SPORT_WEAK_KEYWORDS = (
    "cup",
    "league",
    "match",
)
HISTORY_SPORT_STRONG_KEYWORDS = tuple(
    keyword for keyword in HISTORY_SPORT_KEYWORDS if keyword not in HISTORY_SPORT_WEAK_KEYWORDS
)
HISTORY_MILITARY_KEYWORDS = (
    "war",
    "battle",
    "troops",
    "army",
    "navy",
    "military",
    "offensive",
    "siege",
    "fleet",
    "carrier",
    "destroyer",
    "cruiser",
    "forces",
    "campaign",
    "artillery",
    "bombardment",
)
HISTORY_FAMOUS_BIRTH_KEYWORDS = (
    "actor",
    "actress",
    "singer",
    "musician",
    "footballer",
    "player",
    "athlete",
    "boxer",
    "golfer",
    "tennis",
    "writer",
    "author",
    "poet",
    "artist",
    "scientist",
    "inventor",
    "politician",
    "president",
    "prime minister",
    "king",
    "queen",
    "director",
    "comedian",
    "journalist",
    "broadcaster",
)
PLACE_ALIASES = {
    "paisley": "Paisley, Renfrewshire",
    "paisley, scotland": "Paisley, Renfrewshire",
    "paisley, renfrewshire": "Paisley, Renfrewshire",
}
PLACE_CANDIDATE_POSITIVE_KEYWORDS = (
    "town",
    "city",
    "village",
    "settlement",
    "burgh",
    "suburb",
    "municipality",
    "locality",
    "council area",
    "renfrewshire",
    "scotland",
    "england",
    "wales",
    "ireland",
)
PLACE_CANDIDATE_NEGATIVE_KEYWORDS = (
    "pattern",
    "design",
    "fabric",
    "surname",
    "album",
    "song",
    "film",
    "novel",
    "company",
    "school",
    "ship",
    "disambiguation",
)
FACT_THEME_KEYWORDS = {
    "history": (
        "abbey",
        "founded",
        "historic",
        "history",
        "century",
        "medieval",
        "royal",
        "war",
        "built",
        "opened",
    ),
    "landmark": (
        "abbey",
        "church",
        "cathedral",
        "castle",
        "museum",
        "park",
        "hall",
        "memorial",
        "station",
        "theatre",
        "landmark",
    ),
    "industry": (
        "industry",
        "industrial",
        "weaving",
        "woven",
        "textile",
        "mill",
        "mills",
        "manufacturing",
        "shipbuilding",
        "pattern",
    ),
    "culture": (
        "festival",
        "culture",
        "cultural",
        "music",
        "art",
        "arts",
        "theatre",
        "museum",
        "event",
        "events",
    ),
    "people": (
        "born",
        "writer",
        "poet",
        "artist",
        "actor",
        "singer",
        "footballer",
        "politician",
        "notable people",
        "people",
    ),
    "date": (
        "anniversary",
        "annual",
        "today",
        "date",
        "commemorated",
    ),
}
FACT_THEME_LABELS = {
    "history": "History",
    "landmark": "Landmark",
    "industry": "Industry",
    "culture": "Culture",
    "people": "People",
    "date": "Anniversary",
    "general": "Local fact",
}
FACT_CRITIC_THRESHOLDS = {
    "relevance": 8,
    "interestingness": 7,
    "placeSpecificity": 8,
}
FACT_SEARCH_BLOCKED_DOMAINS = (
    "wikipedia.org",
    "wikidata.org",
    "wikimedia.org",
)
FACT_LOW_QUALITY_SOURCE_TOKENS = (
    "choosewhere",
    "tripadvisor",
    "wanderlog",
    "visitacity",
    "thecrazytourist",
    "traveltriangle",
    "holidays",
    "hotels",
    "booking.com",
    "expedia",
    "whatsonin",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "tiktok.com",
    "imdb.com",
    "people.com",
    "parents.com",
    "momlovesbest",
    "behindthename",
    "robertdyas",
    "robertsspaceindustries",
    "funeral-notices",
)
FACT_GENERIC_PAGE_TERMS = (
    "skip to content",
    "british broadcasting corporation",
    "travel guide",
    "visitor guide",
    "visit guide",
    "things to do",
    "where to stay",
    "where to eat",
    "top attractions",
    "must-see",
    "perfect for visitors",
    "plan your visit",
    "offers visitors",
    "vibrant cultural scene",
    "local news",
    "latest news updates",
    "community guide",
    "best coverage",
    "pictures, video, reaction",
    "business directory",
    "community stories",
    "all-about",
    "what's on in",
    "discover what's on",
    "best places to stay",
    "eat, and explore",
    "a great place to visit",
)
FACT_GENERIC_FACT_TITLES = {
    value.casefold()
    for value in (
        "History",
        "Landmark",
        "Industry",
        "Culture",
        "People",
        "Anniversary",
        "Local fact",
    )
}

NEWS_STREAMS: set[queue.Queue[dict[str, Any]]] = set()
NEWS_STREAMS_LOCK = threading.Lock()
HISTORY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
LOGIN_ATTEMPTS: dict[str, tuple[int, float]] = {}
LOGIN_ATTEMPTS_LOCK = threading.Lock()
FACTS_AI_LOCK = threading.Lock()
FACTS_AI_CONTEXT = threading.local()
DAILY_QUIZ_OPERATION_LOCK = threading.Lock()
FACTS_AI_NEXT_REQUEST_AT = 0.0
HISTORY_FACT_ROTATION_VERSION = "v4"
HISTORY_FACT_PREWARM_EVENT = threading.Event()

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
    load_word_list,
    reset_used_words,
    serialize_feedback,
    valid_guess,
)


def get_server_timezone() -> timezone:
    if ZoneInfo is None:
        return timezone.utc

    try:
        return ZoneInfo(SERVER_TZ_NAME)  # type: ignore[return-value]
    except Exception:
        return timezone.utc


SERVER_TZ = get_server_timezone()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today_game_date() -> str:
    return datetime.now(SERVER_TZ).date().isoformat()


def safe_log(message: str) -> None:
    try:
        print(message, flush=True)
    except OSError:
        pass


def is_loopback_ip(value: str) -> bool:
    return value in {"127.0.0.1", "::1", "::ffff:127.0.0.1"}


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
            quick_check = conn.execute("PRAGMA quick_check").fetchone()
            payload["quickCheck"] = quick_check[0] if quick_check is not None else None
            if payload["quickCheck"] != "ok":
                errors.append(f"SQLite quick_check returned {payload['quickCheck']!r}")

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
                "userCount": user_count,
            },
        },
        "quiz": {
            "today": today_quiz,
            "tomorrow": tomorrow_quiz,
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


def validate_username(username: str) -> str | None:
    if not USERNAME_RE.fullmatch(username):
        return "Use 3-32 letters, numbers, underscores, or hyphens."
    return None


def validate_password(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    return None


def connect_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database() -> None:
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

            CREATE TABLE IF NOT EXISTS daily_quiz_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                game_date TEXT NOT NULL,
                category TEXT NOT NULL CHECK (category IN ('football', 'general')),
                answers_json TEXT NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                max_score INTEGER NOT NULL DEFAULT 0,
                correct_count INTEGER NOT NULL DEFAULT 0,
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

            CREATE TABLE IF NOT EXISTS history_fact_rotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rotation_key TEXT NOT NULL,
                facts_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_history_fact_rotations_key_created_at
            ON history_fact_rotations (rotation_key, created_at DESC);

            CREATE TABLE IF NOT EXISTS history_fact_review_failures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rotation_key TEXT NOT NULL,
                selection_json TEXT,
                critique_json TEXT,
                failure_reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_history_fact_review_failures_key_created_at
            ON history_fact_review_failures (rotation_key, created_at DESC);

            CREATE TABLE IF NOT EXISTS history_fact_prewarm_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rotation_key TEXT NOT NULL,
                location_query TEXT NOT NULL,
                place_title TEXT NOT NULL,
                lang TEXT NOT NULL,
                limit_facts INTEGER NOT NULL DEFAULT 2,
                source_rotation_created_at TEXT NOT NULL,
                target_not_before_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'ready', 'failed', 'consumed', 'cancelled')),
                facts_json TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                last_error TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_history_fact_prewarm_jobs_rotation_target
            ON history_fact_prewarm_jobs (rotation_key, target_not_before_at DESC);

            CREATE INDEX IF NOT EXISTS idx_history_fact_prewarm_jobs_status_target
            ON history_fact_prewarm_jobs (status, target_not_before_at ASC, created_at ASC);
            """
            )
            ensure_column(conn, "users", "is_moderator", "INTEGER NOT NULL DEFAULT 0")
            ensure_column(conn, "daily_wordle_games", "cycle", "INTEGER NOT NULL DEFAULT 1")
            ensure_column(conn, "wordle_results", "score", "INTEGER NOT NULL DEFAULT 0")
            ensure_column(conn, "daily_quiz_results", "bonus_points", "INTEGER NOT NULL DEFAULT 0")
            ensure_column(conn, "news_items", "story_key", "TEXT NOT NULL DEFAULT ''")
            backfill_wordle_assignment_difficulties(conn)
            backfill_wordle_scores(conn)
            daily_quiz.initialize_database(conn)
            backfill_daily_quiz_scores(conn)
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
            backfill_news_items(conn)
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_news_items_story_key
                ON news_items (story_key)
                WHERE story_key <> ''
                """
            )


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
    now = datetime.now(timezone.utc).replace(microsecond=0)
    expires_at = now + timedelta(days=SESSION_DAYS)
    cleanup_expired_sessions(conn, now=now.isoformat())
    conn.execute(
        """
        INSERT INTO sessions (token, user_id, created_at, expires_at)
        VALUES (?, ?, ?, ?)
        """,
        (token, user_id, now.isoformat(), expires_at.isoformat()),
    )
    return token


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


def current_user(conn: sqlite3.Connection, token: str | None) -> sqlite3.Row | None:
    if token is None:
        return None

    now = utc_now()
    return conn.execute(
        """
        SELECT users.*
        FROM sessions
        JOIN users ON users.id = sessions.user_id
        WHERE sessions.token = ? AND sessions.expires_at > ?
        """,
        (token, now),
    ).fetchone()


def login_attempt_key(username: str, client_ip: str) -> str:
    return f"{username.lower()}|{client_ip}"


def is_login_locked(username: str, client_ip: str) -> bool:
    key = login_attempt_key(username, client_ip)
    now = time.time()

    with LOGIN_ATTEMPTS_LOCK:
        attempts = LOGIN_ATTEMPTS.get(key)
        if attempts is None:
            return False

        failure_count, locked_until = attempts
        if locked_until > 0 and locked_until <= now:
            LOGIN_ATTEMPTS.pop(key, None)
            return False

        return locked_until > now and failure_count >= LOGIN_MAX_FAILURES


def record_login_failure(username: str, client_ip: str) -> None:
    key = login_attempt_key(username, client_ip)
    now = time.time()

    with LOGIN_ATTEMPTS_LOCK:
        failure_count, locked_until = LOGIN_ATTEMPTS.get(key, (0, 0.0))
        if locked_until > 0 and locked_until <= now:
            failure_count = 0
        failure_count += 1
        next_locked_until = (
            now + LOGIN_LOCKOUT_SECONDS if failure_count >= LOGIN_MAX_FAILURES else locked_until
        )
        LOGIN_ATTEMPTS[key] = (failure_count, next_locked_until)


def clear_login_failures(username: str, client_ip: str) -> None:
    with LOGIN_ATTEMPTS_LOCK:
        LOGIN_ATTEMPTS.pop(login_attempt_key(username, client_ip), None)


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

    try:
        cursor = conn.execute(
            """
            INSERT INTO daily_wordle_games (game_date, secret_word, cycle, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (game_date, secret_word, cycle, now),
        )
        game_id = cursor.lastrowid
        conn.execute(
            """
            INSERT INTO wordle_used_words (word, game_id, used_on, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (secret_word, game_id, game_date, now),
        )
    except sqlite3.IntegrityError:
        pass

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
    result = existing_wordle_result(conn, user_id, game_id)
    if result is not None:
        return result

    now = utc_now()
    conn.execute(
        """
        INSERT INTO wordle_results
            (user_id, game_id, status, attempts_used, created_at, updated_at)
        VALUES (?, ?, 'in_progress', 0, ?, ?)
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


def ensure_wordle_assignment(
    conn: sqlite3.Connection,
    user_id: int,
    game: sqlite3.Row,
) -> sqlite3.Row:
    assignment = wordle_assignment_row(conn, user_id, game["id"])
    if assignment is not None:
        return assignment

    streak = user_wordle_solve_streak(
        conn,
        user_id,
        current_date=game["game_date"],
        before_date=game["game_date"],
    )["current"]
    target_difficulty = difficulty_for_streak(streak)
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
    try:
        conn.execute(
            """
            INSERT INTO wordle_user_assignments
                (user_id, game_id, secret_word, difficulty, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, game["id"], secret_word, actual_difficulty, now),
        )
    except sqlite3.IntegrityError:
        pass

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
            "User-Agent": NEWS_USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
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
    cached = WORD_DEFINITION_CACHE.get(normalized_word)
    if cached is not None:
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

    WORD_DEFINITION_CACHE[normalized_word] = result
    return result



def score_day_streak(date_values: list[str], current_date: str | None = None) -> dict[str, int]:
    days = []
    for date_value in set(date_values):
        try:
            days.append(datetime.strptime(date_value, "%Y-%m-%d").date())
        except ValueError:
            continue

    if not days:
        return {"current": 0, "best": 0}

    ordered_days = sorted(days)
    best = 1
    run = 1
    for previous, day in zip(ordered_days, ordered_days[1:]):
        run = run + 1 if day == previous + timedelta(days=1) else 1
        best = max(best, run)

    reference_date = current_date or today_game_date()
    try:
        today = datetime.strptime(reference_date, "%Y-%m-%d").date()
    except ValueError:
        today = ordered_days[-1]

    latest = ordered_days[-1]
    if latest not in {today, today - timedelta(days=1)}:
        return {"current": 0, "best": best}

    active_days = set(ordered_days)
    current = 0
    day = latest
    while day in active_days:
        current += 1
        day -= timedelta(days=1)

    return {"current": current, "best": best}


def score_quiz_answers(
    questions: list[dict[str, Any]],
    answers: list[str],
) -> dict[str, int]:
    score = 0
    max_score = 0
    correct_count = 0
    for index, question in enumerate(questions):
        points = QUIZ_POINTS_BY_DIFFICULTY.get(str(question.get("difficulty", "")), 0)
        max_score += points
        if index < len(answers) and answers[index] == question.get("correct_answer"):
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


def serialize_quiz_result(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "date": row["game_date"],
        "category": row["category"],
        "score": row["score"],
        "maxScore": row["max_score"],
        "correctCount": row["correct_count"],
        "bonusPoints": row["bonus_points"],
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
    payload = daily_quiz.quiz_payload(conn, game_date)
    return [
        question
        for question in payload["questions"]
        if question["subject"] == subject
    ]


def save_daily_quiz_result(
    conn: sqlite3.Connection,
    user_id: int,
    game_date: str,
    category: str,
    answers: list[str],
) -> tuple[dict[str, Any], int]:
    if game_date != today_game_date():
        return {"error": "Only today's quiz can be scored."}, HTTPStatus.BAD_REQUEST
    try:
        questions = quiz_category_questions(conn, game_date, category)
    except ValueError as error:
        return {"error": str(error)}, HTTPStatus.BAD_REQUEST
    except LookupError:
        return {"error": "Today's quiz is not available."}, HTTPStatus.NOT_FOUND
    if len(answers) != len(questions):
        return {"error": "Submit one answer for each quiz question."}, HTTPStatus.BAD_REQUEST

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

    totals = score_quiz_answers(questions, answers)
    now = utc_now()
    try:
        conn.execute(
            """
            INSERT INTO daily_quiz_results (
                user_id, game_date, category, answers_json, score, max_score,
                correct_count, bonus_points, completed_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                game_date,
                category,
                json.dumps(answers),
                totals["score"],
                totals["maxScore"],
                totals["correctCount"],
                totals["bonusPoints"],
                now,
                now,
                now,
            ),
        )
    except sqlite3.IntegrityError:
        pass

    result = conn.execute(
        """
        SELECT *
        FROM daily_quiz_results
        WHERE user_id = ? AND game_date = ? AND category = ?
        """,
        (user_id, game_date, category),
    ).fetchone()
    return {"result": serialize_quiz_result(result)}, HTTPStatus.CREATED


def backfill_daily_quiz_scores(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id, game_date, category, answers_json, score, max_score, correct_count, bonus_points
        FROM daily_quiz_results
        """
    ).fetchall()
    for row in rows:
        try:
            answers = json.loads(row["answers_json"])
            questions = quiz_category_questions(conn, row["game_date"], row["category"])
        except (json.JSONDecodeError, LookupError, ValueError):
            continue
        if not isinstance(answers, list) or not all(isinstance(answer, str) for answer in answers):
            continue
        totals = score_quiz_answers(questions, answers)
        stored_totals = (
            row["score"],
            row["max_score"],
            row["correct_count"],
            row["bonus_points"],
        )
        next_totals = (
            totals["score"],
            totals["maxScore"],
            totals["correctCount"],
            totals["bonusPoints"],
        )
        if stored_totals != next_totals:
            conn.execute(
                """
                UPDATE daily_quiz_results
                SET score = ?, max_score = ?, correct_count = ?, bonus_points = ?
                WHERE id = ?
                """,
                (*next_totals, row["id"]),
            )


def player_wordle_solve_streaks(conn: sqlite3.Connection) -> dict[int, dict[str, int]]:
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

    return {
        user_id: score_wordle_solve_streak(outcomes)
        for user_id, outcomes in outcomes_by_user.items()
    }


def leaderboard_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    period_end = today_game_date()
    period_start = (
        datetime.strptime(period_end, "%Y-%m-%d").date() - timedelta(days=6)
    ).isoformat()
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
            WHERE game_date >= ?
            GROUP BY user_id
        ),
        quiz_scores AS (
            SELECT
                user_id,
                SUM(score) AS points,
                SUM(max_score) AS max_points,
                COUNT(*) AS played,
                SUM(correct_count) AS correct_count
            FROM daily_quiz_results
            GROUP BY user_id
        ),
        weekly_quiz_scores AS (
            SELECT
                user_id,
                SUM(score) AS points
            FROM daily_quiz_results
            WHERE game_date >= ?
            GROUP BY user_id
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
            COALESCE(quiz_scores.correct_count, 0) AS quiz_correct
        FROM users
        LEFT JOIN wordle_scores ON wordle_scores.user_id = users.id
        LEFT JOIN weekly_wordle_scores ON weekly_wordle_scores.user_id = users.id
        LEFT JOIN quiz_scores ON quiz_scores.user_id = users.id
        LEFT JOIN weekly_quiz_scores ON weekly_quiz_scores.user_id = users.id
        WHERE users.role != 'admin'
        ORDER BY
            (COALESCE(weekly_wordle_scores.points, 0) + COALESCE(weekly_quiz_scores.points, 0)) DESC,
            (COALESCE(wordle_scores.points, 0) + COALESCE(quiz_scores.points, 0)) DESC,
            COALESCE(wordle_scores.wins, 0) DESC,
            LOWER(users.username)
        """,
        (WORDLE_DIFFICULTY_BONUS_PER_LEVEL, period_start, period_start),
    ).fetchall()

    streaks = player_wordle_solve_streaks(conn)
    players = []
    for index, row in enumerate(rows):
        streak = streaks.get(row["id"], {"current": 0, "best": 0})
        players.append(
            {
                "rank": index + 1,
                "id": row["id"],
                "username": row["username"],
                "weeklyPoints": row["weekly_wordle_points"] + row["weekly_quiz_points"],
                "weeklyWordlePoints": row["weekly_wordle_points"],
                "weeklyQuizPoints": row["weekly_quiz_points"],
                "totalPoints": row["wordle_points"] + row["quiz_points"],
                "wordlePoints": row["wordle_points"],
                "weeklyWordleDifficultyBonus": row["weekly_wordle_difficulty_bonus"],
                "wordleDifficultyBonus": row["wordle_difficulty_bonus"],
                "wordlePlayed": row["wordle_played"],
                "wordleWins": row["wordle_wins"],
                "quizPoints": row["quiz_points"],
                "quizMaxPoints": row["quiz_max_points"],
                "quizPlayed": row["quiz_played"],
                "quizCorrect": row["quiz_correct"],
                "currentStreak": streak["current"],
                "bestStreak": streak["best"],
                "wordleLevel": difficulty_for_streak(streak["current"]),
                "bestWordleLevel": difficulty_for_streak(streak["best"]),
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
        SELECT id, story_key
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
            SELECT id, title, source, published_at, story_key
            FROM news_items
            ORDER BY published_at DESC, id DESC
            LIMIT 100
            """
        ).fetchall()
        existing = next(
            (row for row in recent_rows if news_rows_are_near_duplicates(item, row)),
            None,
        )

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
        headers={"User-Agent": NEWS_USER_AGENT},
    )
    with urlopen(request, timeout=10) as response:
        raw_xml = response.read()

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
                broadcast_news_item(item)

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


def server_timezone() -> timezone | ZoneInfo:
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(SERVER_TZ_NAME)
    except Exception:
        return timezone.utc


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
    tomorrow = today + timedelta(days=1)
    return [today.isoformat(), tomorrow.isoformat()]


def ensure_daily_quiz_dates(target_dates: list[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen_dates: set[str] = set()
    with DAILY_QUIZ_OPERATION_LOCK:
        with closing(connect_db()) as conn:
            with conn:
                for quiz_date in target_dates:
                    normalized_date = daily_quiz.valid_quiz_date(quiz_date)
                    if normalized_date in seen_dates:
                        continue
                    seen_dates.add(normalized_date)
                    status = daily_quiz.quiz_status(conn, normalized_date)
                    if status["status"] == "published":
                        safe_log(f"Daily quiz for {normalized_date} is already published")
                        results.append(status)
                        continue
                    result = daily_quiz.generate_daily_quiz(
                        conn,
                        quiz_date=normalized_date,
                        config=DAILY_QUIZ_CONFIG,
                        log=lambda message: safe_log(f"Daily quiz: {message}"),
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


def daily_quiz_retry_interval_sec(results: list[dict[str, Any]]) -> int:
    if any(bool(result.get("last_failure_transient")) for result in results):
        return DAILY_QUIZ_TRANSIENT_RETRY_INTERVAL_SEC
    return DAILY_QUIZ_RETRY_INTERVAL_SEC


def daily_quiz_scheduler_loop() -> None:
    safe_log("Daily quiz scheduler started")
    while True:
        results: list[dict[str, Any]] = []
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

        next_run = next_daily_quiz_run()
        now = datetime.now(next_run.tzinfo)
        if retry_required:
            retry_at = now + timedelta(seconds=daily_quiz_retry_interval_sec(results))
            wake_at = retry_at if retry_at < next_run else next_run
        else:
            wake_at = next_run
        delay = max(1.0, (wake_at - now).total_seconds())
        safe_log(f"Daily quiz scheduler sleeping until {wake_at.isoformat()}")
        time.sleep(delay)


def start_daily_quiz_scheduler() -> None:
    if not DAILY_QUIZ_SCHEDULER_ENABLED:
        safe_log("Daily quiz scheduler disabled")
        return
    thread = threading.Thread(target=daily_quiz_scheduler_loop, daemon=True)
    thread.start()


def normalise_history_lang(value: str) -> str:
    lang = str(value or "en").lower().split("-")[0]
    return lang if lang in SUPPORTED_HISTORY_LANGS else "en"


def normalise_history_location(value: str) -> str:
    location = unicodedata.normalize("NFC", str(value or "")).strip()
    if len(location) > 120:
        raise ValueError("Location must be 120 characters or fewer.")
    if any(ord(character) < 32 for character in location):
        raise ValueError("Location contains invalid characters.")
    return location


def parse_history_date(value: str) -> tuple[str, int, int] | None:
    raw = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return None

    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return None

    return raw, parsed.month, parsed.day


def history_cache_get(key: str) -> dict[str, Any] | None:
    cached = HISTORY_CACHE.get(key)
    if cached is None:
        return None

    expires_at, payload = cached
    if time.time() > expires_at:
        HISTORY_CACHE.pop(key, None)
        return None
    if not history_payload_is_cacheable(payload):
        HISTORY_CACHE.pop(key, None)
        return None

    result = dict(payload)
    result["meta"] = {**payload.get("meta", {}), "cached": True}
    return result


def history_cache_set(key: str, payload: dict[str, Any]) -> None:
    history_cache_set_with_expiry(
        key,
        payload,
        expires_at=time.time() + HISTORY_CACHE_TTL_SEC,
    )


def history_cache_set_with_expiry(
    key: str,
    payload: dict[str, Any],
    *,
    expires_at: float,
) -> None:
    HISTORY_CACHE[key] = (expires_at, payload)


def history_payload_is_cacheable(payload: dict[str, Any]) -> bool:
    return isinstance(payload.get("location"), dict)


def history_cache_expiry_timestamp(
    *,
    rotation_created_at: datetime | None = None,
    now_ts: float | None = None,
) -> float:
    reference_now = now_ts if now_ts is not None else time.time()
    expires_at = reference_now + HISTORY_CACHE_TTL_SEC
    if rotation_created_at is not None:
        expires_at = min(
            expires_at,
            rotation_created_at.astimezone(timezone.utc).timestamp() + FACT_ROTATION_TTL_SEC,
        )
    return expires_at


def history_rotation_expiry_isoformat(rotation_created_at: datetime | None) -> str | None:
    if rotation_created_at is None:
        return None
    expires_at = rotation_created_at.astimezone(timezone.utc) + timedelta(seconds=FACT_ROTATION_TTL_SEC)
    return expires_at.replace(microsecond=0).isoformat()


def history_rotation_expiry_datetime(rotation_created_at: datetime | None) -> datetime | None:
    if rotation_created_at is None:
        return None
    return rotation_created_at.astimezone(timezone.utc) + timedelta(seconds=FACT_ROTATION_TTL_SEC)


def fetch_json_url(url: str, timeout: int = 8) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": HISTORY_USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_text_url(url: str, timeout: int = 8) -> str:
    request = Request(url, headers={"User-Agent": HISTORY_USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="ignore")


def clean_search_text(value: str, limit: int = 700) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def blocked_fact_source(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(blocked in host for blocked in FACT_SEARCH_BLOCKED_DOMAINS)


def bing_rss_search_url(query: str) -> str:
    return (
        "https://www.bing.com/search?format=rss&mkt=en-GB&q="
        f"{quote_plus(query)}"
    )


def fact_text_match_key(value: str) -> str:
    return str(value or "").lower().replace("’", "'")


class FactExcerptHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta_descriptions: list[str] = []
        self.page_title = ""
        self.blocks: list[str] = []
        self._active_tag: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {str(key).lower(): str(value or "") for key, value in attrs}
        if tag == "meta":
            name = attr_map.get("name", "").lower()
            prop = attr_map.get("property", "").lower()
            if name in {"description", "twitter:description"} or prop in {"og:description"}:
                content = clean_search_text(attr_map.get("content", ""), 420)
                if content:
                    self.meta_descriptions.append(content)
            return
        if tag in {"title", "p", "li"}:
            self._active_tag = tag
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._active_tag is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != self._active_tag:
            return
        text = clean_search_text(" ".join(self._parts), 700)
        if text:
            if tag == "title" and not self.page_title:
                self.page_title = text
            elif tag in {"p", "li"}:
                self.blocks.append(text)
        self._active_tag = None
        self._parts = []


def clean_web_excerpt_candidate(value: str, limit: int = 320) -> str:
    cleaned = clean_search_text(value, limit)
    lower = fact_text_match_key(cleaned)
    if len(cleaned) < 40:
        return ""
    if any(phrase in lower for phrase in FACT_GENERIC_PAGE_TERMS):
        return ""
    if lower.count("|") >= 2:
        return ""
    return cleaned


def web_search_result_is_promising(title: str, source_url: str, snippet: str) -> bool:
    combined = fact_text_match_key(" ".join((title, source_url, snippet)))
    if any(token in combined for token in FACT_LOW_QUALITY_SOURCE_TOKENS):
        return False
    specific_signal = bool(
        re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b", combined)
        or any(
            token in combined
            for token in ("born", "founded", "abbey", "pattern", "festival", "museum", "castle", "royal", "king", "queen")
        )
    )
    if any(term in combined for term in FACT_GENERIC_PAGE_TERMS) and not specific_signal:
        return False
    return True


def extract_web_page_excerpt(html_text: str) -> str:
    parser = FactExcerptHTMLParser()
    try:
        parser.feed(html_text)
    except Exception:
        parser = FactExcerptHTMLParser()

    candidates: list[str] = []
    for value in parser.meta_descriptions[:2]:
        cleaned = clean_web_excerpt_candidate(value)
        if cleaned:
            candidates.append(cleaned)
    for value in parser.blocks[:8]:
        cleaned = clean_web_excerpt_candidate(value)
        if cleaned:
            candidates.append(cleaned)

    if not candidates:
        cleaned = clean_web_excerpt_candidate(html_text, 900)
        return cleaned

    sentences: list[str] = []
    seen_sentences: set[str] = set()
    for candidate in candidates:
        for sentence in split_fact_sentences(candidate):
            cleaned_sentence = clean_fact_sentence(sentence)
            if cleaned_sentence is None:
                continue
            sentence_key = history_fact_text_key(cleaned_sentence)
            if sentence_key in seen_sentences:
                continue
            seen_sentences.add(sentence_key)
            sentences.append(cleaned_sentence)
            if len(sentences) >= 3:
                break
        if len(sentences) >= 3:
            break

    excerpt = " ".join(sentences[:2]).strip()
    return excerpt[:900] if excerpt else ""


def fetch_web_page_excerpt(url: str) -> str:
    if blocked_fact_source(url):
        return ""
    try:
        return extract_web_page_excerpt(
            fetch_text_url(url, timeout=current_facts_web_search_timeout_sec()),
        )
    except Exception:
        return ""


def candidate_fact_search_queries(
    place_title: str,
    candidates: list[dict[str, Any]] | None,
) -> list[str]:
    if not candidates:
        return []
    place_name = place_title.split(",", 1)[0].strip()
    queries: list[str] = []
    seen_queries: set[str] = set()

    for candidate in candidates[:6]:
        text = str(candidate.get("text") or "").strip()
        title = str(candidate.get("title") or "").strip()
        theme = str(candidate.get("theme") or "general")
        lower = text.lower()
        subject = extract_fact_subject(text, place_title)
        candidate_queries = []
        if subject:
            candidate_queries.append(f'"{place_name}" "{subject}"')
        if fact_title_is_specific(title, place_title):
            candidate_queries.append(f'"{place_name}" "{trim_fact_title(title)}"')
        if theme == "history" or "abbey" in lower:
            candidate_queries.append(f'"{place_name}" abbey history')
        if theme == "industry" or any(token in lower for token in ("pattern", "textile", "weav")):
            candidate_queries.append(f'"{place_name}" pattern textile history')
        if theme == "people" and subject:
            candidate_queries.append(f'"{subject}" "{place_name}" born')
        if theme == "culture" and any(token in lower for token in ("festival", "museum", "arts")):
            candidate_queries.append(f'"{place_name}" festival museum heritage')

        for query in candidate_queries:
            if query in seen_queries:
                continue
            seen_queries.add(query)
            queries.append(query)
    return queries[:8]


def search_web_fact_evidence(
    place_title: str,
    *,
    candidates: list[dict[str, Any]] | None = None,
    limit: int = 8,
) -> list[dict[str, str]]:
    place_name = place_title.split(",", 1)[0].strip()
    base_queries = [
        f'"{place_name}" local history heritage museum',
        f'"{place_name}" abbey castle landmark founded',
        f'"{place_name}" textile pattern industry',
        f'"{place_name}" born here king queen notable',
        f'"{place_title}" council heritage festival',
    ]
    queries = candidate_fact_search_queries(place_title, candidates) + base_queries
    evidence: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for query in queries:
        try:
            payload = fetch_text_url(
                bing_rss_search_url(query),
                timeout=current_facts_web_search_timeout_sec(),
            )
            root = ElementTree.fromstring(payload)
        except Exception as error:
            safe_log(f"Fact web search failed: {error}")
            continue

        for item in root.findall(".//item"):
            title = clean_search_text(item.findtext("title", default=""), 160)
            url = str(item.findtext("link", default="") or "").strip()
            snippet = clean_search_text(item.findtext("description", default=""), 320)
            if not title or not url.startswith(("http://", "https://")):
                continue
            if blocked_fact_source(url):
                continue
            if not web_search_result_is_promising(title, url, snippet):
                continue
            normalized_url = url.split("#", 1)[0]
            if normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            host = urlparse(url).netloc.lower().removeprefix("www.")
            excerpt = fetch_web_page_excerpt(url)
            evidence.append(
                {
                    "title": title,
                    "sourceName": host or "web",
                    "sourceUrl": normalized_url,
                    "snippet": snippet,
                    "excerpt": excerpt or snippet,
                }
            )
            if len(evidence) >= limit:
                return evidence

    return evidence


def fact_source_quality_bonus(source_name: str, source_url: str) -> int:
    host = (source_name or urlparse(source_url).netloc or "").lower()
    path = urlparse(source_url).path.lower()
    title_hint = f"{host} {path}"
    score = 0
    if host.endswith(".gov.uk") or any(token in host for token in ("council", "museum", "university", "ac.uk")):
        score += 14
    elif host.endswith(".org") or host.endswith(".org.uk"):
        score += 8
    elif host.endswith(".co.uk"):
        score += 3
    if any(token in title_hint for token in FACT_LOW_QUALITY_SOURCE_TOKENS):
        score -= 18
    if path in {"", "/"}:
        score -= 12
    if any(token in path for token in ("/category/", "/categories/", "/tag/", "/tags/", "/all-about/")):
        score -= 10
    if any(token in title_hint for token in ("/visit/", "travel-guide", "visitor-guide", "things-to-do")):
        score -= 8
    return score


def web_evidence_item_is_useful(
    source_name: str,
    source_url: str,
    evidence_title: str,
    snippet: str,
) -> bool:
    metadata = fact_text_match_key(" ".join((source_name, source_url, evidence_title)))
    if any(token in metadata for token in FACT_LOW_QUALITY_SOURCE_TOKENS):
        return False
    snippet_lower = fact_text_match_key(snippet)
    snippet_has_specific_signal = bool(
        re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b", snippet_lower)
        or any(
            token in snippet_lower
            for token in ("born", "founded", "abbey", "pattern", "festival", "museum", "castle", "royal", "king", "queen")
        )
    )
    if any(term in metadata for term in FACT_GENERIC_PAGE_TERMS) and not snippet_has_specific_signal:
        return False
    combined = f"{metadata} {snippet_lower}"
    if "|" in evidence_title and any(term in combined for term in ("news", "guide", "daily record", "community")) and not snippet_has_specific_signal:
        return False
    if any(term in combined for term in ("latest news", "best coverage", "business directory", "community stories")) and not snippet_has_specific_signal:
        return False
    if source_url.rstrip("/").count("/") <= 2 and any(term in combined for term in ("news", "guide", "directory")) and not snippet_has_specific_signal:
        return False
    return True


def fact_title_is_specific(title: str, place_title: str) -> bool:
    cleaned = clean_search_text(title, 72).strip(" -|:")
    if len(cleaned) < 4:
        return False
    lower = cleaned.casefold()
    place_name = place_title.split(",", 1)[0].strip().casefold()
    place_full = place_title.casefold()
    if lower in FACT_GENERIC_FACT_TITLES:
        return False
    if lower in {place_name, place_full}:
        return False
    if any(term in lower for term in FACT_GENERIC_PAGE_TERMS):
        return False
    if "|" in cleaned:
        return False
    return True


def trim_fact_title(value: str) -> str:
    cleaned = clean_search_text(value, 72).strip(" -|:")
    cleaned = re.sub(r"\s+[-|]\s+[A-Z][A-Za-z0-9.&' ]{1,28}$", "", cleaned).strip(" -|:")
    cleaned = re.sub(
        r"\b(history|heritage|visitor guide|visit guide|travel guide|official guide|official site)\b$",
        "",
        cleaned,
        flags=re.I,
    ).strip(" -|:")
    return re.sub(r"\s+", " ", cleaned).strip()


def extract_fact_subject(sentence: str, place_title: str) -> str:
    place_name = place_title.split(",", 1)[0].strip().casefold()
    candidates: list[tuple[int, int, str]] = []
    for match in re.finditer(r"\b([A-Z][A-Za-z0-9'&.-]+(?:\s+[A-Z0-9][A-Za-z0-9'&.-]+){0,3})\b", sentence):
        candidate = match.group(1).strip(" -|:")
        if candidate.casefold() == place_name:
            continue
        if candidate.casefold() in {"the", "a", "an"}:
            continue
        token_count = len(candidate.split())
        score = 0
        if token_count >= 2:
            score += 4
        if any(character.isdigit() for character in candidate):
            score += 4
        if any(
            token in candidate.casefold()
            for token in ("abbey", "pattern", "festival", "museum", "castle", "cathedral", "hall")
        ):
            score += 2
        candidates.append((score, token_count, candidate))
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    return candidates[0][2]


def meaningful_fact_title(
    suggested_title: str,
    sentence: str,
    evidence_title: str,
    place_title: str,
    theme: str,
) -> str:
    place_name = place_title.split(",", 1)[0].strip()
    title_prefix_pattern = rf"^{re.escape(place_name)}\s*(?:[:|\-])\s*"

    trimmed_suggested = re.sub(title_prefix_pattern, "", trim_fact_title(suggested_title), flags=re.I)
    if fact_title_is_specific(trimmed_suggested, place_title):
        return trimmed_suggested

    trimmed_evidence = re.sub(title_prefix_pattern, "", trim_fact_title(evidence_title), flags=re.I)
    if fact_title_is_specific(trimmed_evidence, place_title):
        return trimmed_evidence

    subject = extract_fact_subject(sentence, place_title)
    if fact_title_is_specific(subject, place_title):
        return subject

    lower = sentence.lower()
    if theme == "industry" and any(token in lower for token in ("pattern", "textile", "weav")):
        return "Textile legacy"
    if theme == "culture" and "festival" in lower:
        return "Festival scene"
    if theme == "history" and "abbey" in lower:
        return "Abbey history"
    if theme == "people" and any(token in lower for token in ("born", "birthplace", "king", "queen")):
        return "Notable connection"
    return FACT_THEME_LABELS.get(theme, "Local fact")


def web_fact_sentence_is_useful(sentence: str, place_title: str, evidence_title: str) -> bool:
    cleaned = clean_fact_sentence(sentence)
    if cleaned is None:
        return False
    lower = fact_text_match_key(cleaned)
    if any(
        phrase in lower
        for phrase in (
            "you are using an outdated browser",
            "skip to main content",
            "search for:",
            "find out more",
            "all the latest news",
            "this page brings together the latest news",
            "what's on in ",
            "planning to visit",
            "things to do in ",
            "british broadcasting corporation",
            "cookie policy",
            "privacy policy",
            "sign up for",
            "newsletter",
            "where to stay",
            "where to eat",
            "business directory",
            "community stories",
            "best coverage",
            "daily record",
            "latest news updates",
        )
    ):
        return False
    if any(
        phrase in lower
        for phrase in (
            "with its ",
            "offers visitors",
            "perfect for visitors",
            "must-see",
            "plan your visit",
            "top attractions",
            "vibrant cultural scene",
            "we bring you",
            "seven days a week",
        )
    ):
        return False
    place_name = place_title.split(",", 1)[0].strip().lower()
    title_lower = fact_text_match_key(evidence_title)
    theme = classify_fact_theme(cleaned)
    score = fact_candidate_score(cleaned, theme)
    mentions_place = place_name in lower or place_name in title_lower
    if theme == "general" and not any(
        token in lower
        for token in ("born", "founded", "abbey", "pattern", "festival", "museum", "castle", "king", "queen", "textile")
    ):
        return False
    if not mentions_place and theme == "general":
        return False
    if not mentions_place and score < 34:
        return False
    return True


def web_evidence_fact_candidates(
    place_title: str,
    evidence_items: list[dict[str, str]],
) -> list[dict[str, Any]]:
    candidates: list[tuple[int, dict[str, Any]]] = []
    seen_sentences: set[str] = set()
    place_name = place_title.split(",", 1)[0].strip().lower()

    for item in evidence_items:
        source_name = str(item.get("sourceName") or "").strip()
        source_url = str(item.get("sourceUrl") or "").strip()
        evidence_title = str(item.get("title") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        if not source_name or not source_url.startswith(("http://", "https://")):
            continue
        if blocked_fact_source(source_url):
            continue
        if not web_evidence_item_is_useful(source_name, source_url, evidence_title, snippet):
            continue
        source_bonus = fact_source_quality_bonus(source_name, source_url)
        raw_text = " ".join(
            part
            for part in (
                str(item.get("excerpt") or "").strip(),
                snippet,
            )
            if part
        )
        for sentence in split_fact_sentences(raw_text):
            if not web_fact_sentence_is_useful(sentence, place_title, evidence_title):
                continue
            cleaned = clean_fact_sentence(sentence)
            if cleaned is None:
                continue
            sentence_key = history_fact_text_key(cleaned)
            if sentence_key in seen_sentences:
                continue
            seen_sentences.add(sentence_key)
            theme = classify_fact_theme(cleaned)
            score = fact_candidate_score(cleaned, theme) + source_bonus
            if place_name in cleaned.lower():
                score += 10
            fact = make_history_fact(
                title=meaningful_fact_title("", cleaned, evidence_title, place_title, theme),
                text=cleaned,
                theme=theme,
                source_name=source_name,
                source_url=source_url,
                confidence="medium",
            )
            candidates.append((score, fact))

    candidates.sort(key=lambda candidate: candidate[0], reverse=True)
    return [fact for _score, fact in candidates]


def web_evidence_fallback_facts(
    place_title: str,
    evidence_items: list[dict[str, str]],
    *,
    limit: int,
    recent_texts: list[str],
) -> list[dict[str, Any]]:
    selected = rotated_location_facts(
        web_evidence_fact_candidates(place_title, evidence_items),
        limit=limit,
        recent_texts=recent_texts,
        place_title=place_title,
    )
    if len(selected) < limit:
        return []
    return attach_fact_critiques(selected, place_title)


def extract_first_json_object_text(text: str) -> str:
    start = text.find("{")
    if start == -1:
        raise ValueError("AI response does not contain a JSON object.")
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError("AI response does not contain a complete JSON object.")


def parse_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise ValueError("AI response is not JSON text.")
    text = value.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    payload = json.loads(extract_first_json_object_text(text))
    if not isinstance(payload, dict):
        raise ValueError("AI response JSON is not an object.")
    return payload


def parse_utc_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def history_fact_text_key(value: str) -> str:
    return re.sub(r"\W+", "", str(value or "").casefold())[:160]


def history_fact_rotation_key(title: str, lang: str) -> str:
    return (
        f"{HISTORY_FACT_ROTATION_VERSION}:"
        f"{normalise_history_lang(lang)}:{history_fact_text_key(resolve_place_alias(title))}"
    )


def history_fact_rotation_limit(now: datetime | None = None) -> datetime:
    reference = now or datetime.now(timezone.utc)
    return reference - timedelta(seconds=FACT_ROTATION_TTL_SEC)


def deserialize_history_facts(value: str) -> list[dict[str, Any]]:
    payload = json.loads(value)
    if not isinstance(payload, list):
        raise ValueError("Stored facts payload is not a list.")
    facts = [fact for fact in payload if isinstance(fact, dict)]
    if not facts:
        raise ValueError("Stored facts payload is empty.")
    return facts


def latest_history_fact_rotation_row(
    rotation_key: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> sqlite3.Row | None:
    owns_connection = conn is None
    if owns_connection:
        conn = connect_db()
    assert conn is not None
    try:
        return conn.execute(
            """
            SELECT id, facts_json, created_at
            FROM history_fact_rotations
            WHERE rotation_key = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (rotation_key,),
        ).fetchone()
    finally:
        if owns_connection:
            conn.close()


def latest_history_fact_rotation_created_at(
    rotation_key: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> datetime | None:
    row = latest_history_fact_rotation_row(rotation_key, conn=conn)
    if row is None:
        return None
    return parse_utc_timestamp(str(row["created_at"]))


def current_rotated_history_facts_record(
    rotation_key: str,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], datetime] | None:
    cutoff = history_fact_rotation_limit(now)
    row = latest_history_fact_rotation_row(rotation_key)
    if row is None:
        return None

    created_at = parse_utc_timestamp(str(row["created_at"]))
    if created_at is None or created_at < cutoff:
        return None

    try:
        return deserialize_history_facts(str(row["facts_json"])), created_at
    except Exception as error:
        safe_log(f"History fact rotation read failed: {error}")
        return None


def current_rotated_history_facts(
    rotation_key: str,
    now: datetime | None = None,
) -> list[dict[str, Any]] | None:
    record = current_rotated_history_facts_record(rotation_key, now=now)
    if record is None:
        return None
    facts, _created_at = record
    return facts


def history_rotation_has_moved_on(
    rotation_key: str,
    target_not_before_at: datetime,
    *,
    conn: sqlite3.Connection | None = None,
) -> bool:
    latest_created_at = latest_history_fact_rotation_created_at(rotation_key, conn=conn)
    if latest_created_at is None:
        return False
    return latest_created_at > target_not_before_at


def deserialize_history_fact_prewarm_job(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "rotationKey": str(row["rotation_key"] or ""),
        "locationQuery": str(row["location_query"] or ""),
        "placeTitle": str(row["place_title"] or ""),
        "lang": str(row["lang"] or "en"),
        "limitFacts": int(row["limit_facts"] or 0),
        "sourceRotationCreatedAt": str(row["source_rotation_created_at"] or ""),
        "targetNotBeforeAt": str(row["target_not_before_at"] or ""),
        "status": str(row["status"] or ""),
        "attempts": int(row["attempts"] or 0),
        "createdAt": str(row["created_at"] or ""),
        "startedAt": str(row["started_at"] or ""),
        "completedAt": str(row["completed_at"] or ""),
        "lastError": str(row["last_error"] or ""),
    }


def cleanup_history_fact_prewarm_jobs(
    conn: sqlite3.Connection,
    *,
    rotation_key: str | None = None,
) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).replace(microsecond=0).isoformat()
    if rotation_key is not None:
        conn.execute(
            """
            DELETE FROM history_fact_prewarm_jobs
            WHERE rotation_key = ?
              AND completed_at IS NOT NULL
              AND completed_at < ?
            """,
            (rotation_key, cutoff),
        )
        conn.execute(
            """
            DELETE FROM history_fact_prewarm_jobs
            WHERE rotation_key = ?
              AND id NOT IN (
                SELECT id
                FROM history_fact_prewarm_jobs
                WHERE rotation_key = ?
                ORDER BY target_not_before_at DESC, created_at DESC
                LIMIT 12
              )
            """,
            (rotation_key, rotation_key),
        )
        return

    conn.execute(
        """
        DELETE FROM history_fact_prewarm_jobs
        WHERE completed_at IS NOT NULL
          AND completed_at < ?
        """,
        (cutoff,),
    )


def schedule_history_fact_prewarm(
    *,
    rotation_key: str,
    location_query: str,
    place_title: str,
    lang: str,
    limit_facts: int,
    source_rotation_created_at: datetime,
    now: datetime | None = None,
) -> bool:
    if not FACT_PREWARM_ENABLED or limit_facts <= 0:
        return False
    reference_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    target_not_before_at = history_rotation_expiry_datetime(source_rotation_created_at)
    if target_not_before_at is None:
        return False
    remaining_sec = (target_not_before_at - reference_now).total_seconds()
    if remaining_sec <= 0 or remaining_sec > FACT_PREWARM_LEAD_SEC:
        return False

    target_iso = target_not_before_at.replace(microsecond=0).isoformat()
    created_at = utc_now()
    with closing(connect_db()) as conn:
        with conn:
            existing = conn.execute(
                """
                SELECT id
                FROM history_fact_prewarm_jobs
                WHERE rotation_key = ?
                  AND target_not_before_at = ?
                  AND status IN ('pending', 'running', 'ready')
                LIMIT 1
                """,
                (rotation_key, target_iso),
            ).fetchone()
            if existing is not None:
                return False
            conn.execute(
                """
                INSERT INTO history_fact_prewarm_jobs (
                    rotation_key,
                    location_query,
                    place_title,
                    lang,
                    limit_facts,
                    source_rotation_created_at,
                    target_not_before_at,
                    status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    rotation_key,
                    location_query,
                    place_title,
                    normalise_history_lang(lang),
                    limit_facts,
                    source_rotation_created_at.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
                    target_iso,
                    created_at,
                ),
            )
            cleanup_history_fact_prewarm_jobs(conn, rotation_key=rotation_key)
    HISTORY_FACT_PREWARM_EVENT.set()
    return True


def reset_stale_history_fact_prewarm_jobs(conn: sqlite3.Connection) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=30)).replace(microsecond=0).isoformat()
    conn.execute(
        """
        UPDATE history_fact_prewarm_jobs
        SET status = 'pending',
            started_at = NULL
        WHERE status = 'running'
          AND started_at IS NOT NULL
          AND started_at < ?
          AND attempts < ?
        """,
        (cutoff, FACT_PREWARM_MAX_ATTEMPTS),
    )
    conn.execute(
        """
        UPDATE history_fact_prewarm_jobs
        SET status = 'failed',
            completed_at = ?,
            last_error = COALESCE(last_error, 'Prewarm job exceeded retry limit.')
        WHERE status IN ('pending', 'running')
          AND attempts >= ?
        """,
        (utc_now(), FACT_PREWARM_MAX_ATTEMPTS),
    )


def claim_history_fact_prewarm_job() -> sqlite3.Row | None:
    with closing(connect_db()) as conn:
        with conn:
            reset_stale_history_fact_prewarm_jobs(conn)
            row = conn.execute(
                """
                SELECT *
                FROM history_fact_prewarm_jobs
                WHERE status = 'pending'
                ORDER BY target_not_before_at ASC, created_at ASC, id ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            started_at = utc_now()
            updated = conn.execute(
                """
                UPDATE history_fact_prewarm_jobs
                SET status = 'running',
                    attempts = attempts + 1,
                    started_at = ?
                WHERE id = ?
                  AND status = 'pending'
                """,
                (started_at, row["id"]),
            )
            if updated.rowcount != 1:
                return None
            return conn.execute(
                "SELECT * FROM history_fact_prewarm_jobs WHERE id = ?",
                (row["id"],),
            ).fetchone()


def complete_history_fact_prewarm_job(
    job_id: int,
    *,
    status: str,
    facts: list[dict[str, Any]] | None = None,
    last_error: str | None = None,
) -> None:
    completed_at = utc_now()
    with closing(connect_db()) as conn:
        with conn:
            conn.execute(
                """
                UPDATE history_fact_prewarm_jobs
                SET status = ?,
                    facts_json = ?,
                    completed_at = ?,
                    last_error = ?
                WHERE id = ?
                """,
                (
                    status,
                    json.dumps(facts, ensure_ascii=True) if facts is not None else None,
                    completed_at,
                    last_error,
                    job_id,
                ),
            )


def requeue_history_fact_prewarm_job(job_id: int, *, last_error: str) -> None:
    with closing(connect_db()) as conn:
        with conn:
            conn.execute(
                """
                UPDATE history_fact_prewarm_jobs
                SET status = 'pending',
                    started_at = NULL,
                    completed_at = NULL,
                    last_error = ?
                WHERE id = ?
                """,
                (last_error, job_id),
            )


def next_ready_history_fact_prewarm(
    rotation_key: str,
    *,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], sqlite3.Row] | None:
    reference_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    reference_now_iso = reference_now.isoformat()
    with closing(connect_db()) as conn:
        while True:
            row = conn.execute(
                """
                SELECT *
                FROM history_fact_prewarm_jobs
                WHERE rotation_key = ?
                  AND status = 'ready'
                  AND target_not_before_at <= ?
                ORDER BY target_not_before_at DESC, completed_at DESC, id DESC
                LIMIT 1
                """,
                (rotation_key, reference_now_iso),
            ).fetchone()
            if row is None:
                return None

            target_not_before_at = parse_utc_timestamp(str(row["target_not_before_at"]))
            if target_not_before_at is None:
                with conn:
                    conn.execute(
                        """
                        UPDATE history_fact_prewarm_jobs
                        SET status = 'cancelled',
                            completed_at = COALESCE(completed_at, ?),
                            last_error = 'Invalid prewarm target timestamp.'
                        WHERE id = ?
                        """,
                        (utc_now(), row["id"]),
                    )
                continue
            if history_rotation_has_moved_on(rotation_key, target_not_before_at, conn=conn):
                with conn:
                    conn.execute(
                        """
                        UPDATE history_fact_prewarm_jobs
                        SET status = 'cancelled',
                            completed_at = COALESCE(completed_at, ?),
                            last_error = 'Prewarmed facts became stale before promotion.'
                        WHERE id = ?
                        """,
                        (utc_now(), row["id"]),
                    )
                continue
            try:
                return deserialize_history_facts(str(row["facts_json"])), row
            except Exception:
                with conn:
                    conn.execute(
                        """
                        UPDATE history_fact_prewarm_jobs
                        SET status = 'failed',
                            completed_at = COALESCE(completed_at, ?),
                            last_error = 'Stored prewarmed facts could not be decoded.'
                        WHERE id = ?
                        """,
                        (utc_now(), row["id"]),
                    )
                continue


def recent_rotated_history_texts(
    rotation_key: str,
    *,
    limit: int = 6,
) -> list[str]:
    rows: list[sqlite3.Row]
    with closing(connect_db()) as conn:
        rows = conn.execute(
            """
            SELECT facts_json
            FROM history_fact_rotations
            WHERE rotation_key = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (rotation_key, max(1, limit)),
        ).fetchall()

    seen: set[str] = set()
    texts: list[str] = []
    for row in rows:
        try:
            facts = deserialize_history_facts(str(row["facts_json"]))
        except Exception:
            continue
        for fact in facts:
            text = str(fact.get("text") or "").strip()
            text_key = history_fact_text_key(text)
            if not text or text_key in seen:
                continue
            seen.add(text_key)
            texts.append(text)
    return texts


def store_rotated_history_facts(
    rotation_key: str,
    facts: list[dict[str, Any]],
    *,
    created_at: str | None = None,
) -> None:
    with closing(connect_db()) as conn:
        with conn:
            store_rotated_history_facts_in_conn(
                conn,
                rotation_key,
                facts,
                created_at=created_at,
            )


def store_rotated_history_facts_in_conn(
    conn: sqlite3.Connection,
    rotation_key: str,
    facts: list[dict[str, Any]],
    *,
    created_at: str | None = None,
) -> None:
    timestamp = created_at or utc_now()
    conn.execute(
        """
        INSERT INTO history_fact_rotations (rotation_key, facts_json, created_at)
        VALUES (?, ?, ?)
        """,
        (rotation_key, json.dumps(facts, ensure_ascii=True), timestamp),
    )
    conn.execute(
        """
        DELETE FROM history_fact_rotations
        WHERE rotation_key = ?
          AND id NOT IN (
            SELECT id
            FROM history_fact_rotations
            WHERE rotation_key = ?
            ORDER BY created_at DESC
            LIMIT 8
          )
        """,
        (rotation_key, rotation_key),
    )


def promote_ready_history_fact_prewarm(
    rotation_key: str,
    *,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], datetime] | None:
    ready = next_ready_history_fact_prewarm(rotation_key, now=now)
    if ready is None:
        return None
    facts, row = ready
    created_at = utc_now()
    with closing(connect_db()) as conn:
        with conn:
            store_rotated_history_facts_in_conn(
                conn,
                rotation_key,
                facts,
                created_at=created_at,
            )
            conn.execute(
                """
                UPDATE history_fact_prewarm_jobs
                SET status = 'consumed',
                    completed_at = COALESCE(completed_at, ?)
                WHERE id = ?
                """,
                (created_at, row["id"]),
            )
    created_at_dt = parse_utc_timestamp(created_at)
    if created_at_dt is None:
        raise ValueError("Promoted prewarmed facts used an invalid timestamp.")
    return facts, created_at_dt


def normalise_place_alias_key(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def resolve_place_alias(location: str) -> str:
    return PLACE_ALIASES.get(normalise_place_alias_key(location), location)


def wikipedia_summary_url(lang: str, title: str) -> str:
    safe_title = quote_plus(title.replace(" ", "_"), safe=",")
    return f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{safe_title}"


def wikipedia_search_url(lang: str, query: str, limit: int = 8) -> str:
    return (
        f"https://{lang}.wikipedia.org/w/rest.php/v1/search/page"
        f"?q={quote_plus(query)}&limit={limit}"
    )


def wikipedia_plain_extract_url(lang: str, title: str) -> str:
    return (
        f"https://{lang}.wikipedia.org/w/api.php?action=query&format=json"
        f"&prop=extracts&explaintext=1&exlimit=1&redirects=1&titles={quote_plus(title)}"
    )


def wikipedia_article_images_url(lang: str, title: str, limit: int = 18) -> str:
    return (
        f"https://{lang}.wikipedia.org/w/api.php?action=query&format=json"
        f"&generator=images&gimlimit={limit}&prop=imageinfo&iiprop=url"
        f"&iiurlwidth=960&redirects=1&titles={quote_plus(title)}"
    )


def commons_fact_image_search_url(query: str, limit: int = 5) -> str:
    return (
        "https://commons.wikimedia.org/w/api.php?action=query&format=json"
        f"&generator=search&gsrnamespace=6&gsrlimit={limit}"
        f"&gsrsearch={quote_plus(query)}&prop=imageinfo&iiprop=url&iiurlwidth=960"
    )


def wikidata_entity_url(qid: str) -> str:
    return f"https://www.wikidata.org/wiki/Special:EntityData/{quote_plus(qid)}.json"


def wikidata_labels_url(qids: list[str], lang: str) -> str:
    return (
        "https://www.wikidata.org/w/api.php?action=wbgetentities&format=json"
        f"&ids={quote_plus('|'.join(qids), safe='|')}&props=labels&languages={quote_plus(lang)}|en"
    )


def wikipedia_candidate_score(query: str, page: dict[str, Any]) -> int:
    title = strip_html(str(page.get("title", "")))
    description = strip_html(str(page.get("description", "")))
    excerpt = strip_html(str(page.get("excerpt", "")))
    title_lower = title.lower()
    query_lower = normalise_place_alias_key(query)
    combined = f"{title} {description} {excerpt}".lower()
    score = 0

    if title_lower == query_lower:
        score += 20
    if title_lower.startswith(f"{query_lower},"):
        score += 30
    if query_lower and query_lower in title_lower:
        score += 20
    if "," in title:
        score += 8
    score += history_keyword_score(combined, PLACE_CANDIDATE_POSITIVE_KEYWORDS, 18)
    score -= history_keyword_score(combined, PLACE_CANDIDATE_NEGATIVE_KEYWORDS, 40)
    return score


def resolve_wikipedia_place_title(location: str, lang: str) -> str:
    aliased = resolve_place_alias(location)
    if aliased != location:
        return aliased

    try:
        search = fetch_json_url(wikipedia_search_url(lang, location))
    except Exception:
        return location

    pages = search.get("pages")
    if not isinstance(pages, list) or not pages:
        return location

    candidates: list[tuple[int, str]] = []
    for page in pages:
        if not isinstance(page, dict) or not page.get("title"):
            continue
        candidates.append((wikipedia_candidate_score(location, page), str(page["title"])))

    if not candidates:
        return location

    candidates.sort(reverse=True)
    best_score, best_title = candidates[0]
    return best_title if best_score > 0 else location


def fetch_wikipedia_summary(location: str, lang: str) -> dict[str, Any]:
    title = resolve_wikipedia_place_title(location, lang)
    try:
        return fetch_json_url(wikipedia_summary_url(lang, title))
    except Exception:
        search = fetch_json_url(wikipedia_search_url(lang, location, 1))
        pages = search.get("pages")
        if not isinstance(pages, list) or not pages:
            raise LookupError("Location not found.")

        title = pages[0].get("title")
        if not title:
            raise LookupError("Location not found.")
        return fetch_json_url(wikipedia_summary_url(lang, str(title)))


def fetch_wikipedia_plain_extract(title: str, lang: str) -> str:
    payload = fetch_json_url(wikipedia_plain_extract_url(lang, title))
    pages = payload.get("query", {}).get("pages", {}) if isinstance(payload, dict) else {}
    if not isinstance(pages, dict):
        return ""

    for page in pages.values():
        if isinstance(page, dict) and isinstance(page.get("extract"), str):
            return page["extract"]
    return ""


WIKIPEDIA_IMAGE_REJECT_TERMS = (
    "arms",
    "badge",
    "coat",
    "commons-logo",
    "diagram",
    "flag",
    "icon",
    "locator",
    "logo",
    "map",
    "seal",
    "shield",
    "symbol",
)
FACT_IMAGE_STOP_TERMS = {
    "after",
    "among",
    "annual",
    "based",
    "became",
    "been",
    "before",
    "building",
    "buildings",
    "centre",
    "century",
    "closed",
    "during",
    "either",
    "example",
    "file",
    "first",
    "focus",
    "former",
    "from",
    "geograph",
    "giving",
    "global",
    "history",
    "image",
    "important",
    "into",
    "late",
    "main",
    "many",
    "most",
    "name",
    "named",
    "noticeable",
    "still",
    "that",
    "their",
    "this",
    "today",
    "town",
    "used",
    "were",
    "which",
    "with",
}


def summary_location_image(
    summary: dict[str, Any],
    article_url: str | None,
) -> dict[str, str | None] | None:
    thumbnail = summary.get("thumbnail", {})
    source = thumbnail.get("source") if isinstance(thumbnail, dict) else None
    if not isinstance(source, str) or not source.startswith("https://"):
        return None

    return {
        "url": source,
        "title": str(summary.get("title") or "Location image"),
        "sourceName": "Wikipedia",
        "sourceUrl": article_url,
    }


def wikipedia_image_title_is_useful(title: str) -> bool:
    clean_title = re.sub(r"^File:", "", str(title or ""), flags=re.IGNORECASE).strip()
    title_lower = clean_title.lower()
    if not re.search(r"\.(?:jpe?g|png|webp)$", title_lower):
        return False
    return not any(term in title_lower for term in WIKIPEDIA_IMAGE_REJECT_TERMS)


def normalise_wikipedia_image(page: dict[str, Any]) -> dict[str, str | None] | None:
    title = str(page.get("title") or "")
    if not wikipedia_image_title_is_useful(title):
        return None

    image_info = page.get("imageinfo", [])
    first_info = image_info[0] if isinstance(image_info, list) and image_info else {}
    if not isinstance(first_info, dict):
        return None

    url = first_info.get("thumburl") or first_info.get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        return None

    source_url = first_info.get("descriptionurl")
    return {
        "url": url,
        "title": re.sub(r"^File:", "", title, flags=re.IGNORECASE).strip(),
        "sourceName": "Wikimedia Commons",
        "sourceUrl": source_url if isinstance(source_url, str) else None,
    }


def fetch_wikipedia_images(
    summary: dict[str, Any],
    lang: str,
    article_url: str | None,
    limit: int = 5,
) -> list[dict[str, str | None]]:
    images: list[dict[str, str | None]] = []
    seen_urls: set[str] = set()

    def append_image(image: dict[str, str | None] | None) -> None:
        if image is None or not isinstance(image.get("url"), str):
            return
        image_url = str(image["url"])
        if image_url in seen_urls:
            return
        images.append(image)
        seen_urls.add(image_url)

    append_image(summary_location_image(summary, article_url))
    title = str(summary.get("title") or "").strip()
    if not title or len(images) >= limit:
        return images[:limit]

    try:
        payload = fetch_json_url(wikipedia_article_images_url(lang, title), timeout=5)
    except Exception as error:
        safe_log(f"History Wikipedia image fetch failed: {error}")
        return images[:limit]

    pages = payload.get("query", {}).get("pages", {}) if isinstance(payload, dict) else {}
    if not isinstance(pages, dict):
        return images[:limit]

    for page in pages.values():
        if not isinstance(page, dict):
            continue
        append_image(normalise_wikipedia_image(page))
        if len(images) >= limit:
            break

    return images[:limit]


def fact_image_terms(value: str, excluded_terms: set[str] | None = None) -> set[str]:
    terms = {
        term.lower()
        for term in re.findall(r"[A-Za-z][A-Za-z0-9']+", str(value or ""))
        if len(term) >= 4
    }
    terms.difference_update(FACT_IMAGE_STOP_TERMS)
    if excluded_terms:
        terms.difference_update(excluded_terms)
    return terms


def fact_image_query(fact: dict[str, Any], place_title: str) -> str:
    queries = fact_image_queries(fact, place_title)
    return queries[0] if queries else ""


def fact_image_queries(fact: dict[str, Any], place_title: str) -> list[str]:
    place_name = place_title.split(",", 1)[0].strip()
    place_terms = fact_image_terms(place_title)
    proper_terms: list[str] = []
    fallback_terms: list[str] = []
    seen_terms: set[str] = set()

    for term in re.findall(r"[A-Za-z][A-Za-z0-9']+", str(fact.get("text") or "")):
        normalised = term.lower()
        if (
            len(normalised) < 4
            or normalised in seen_terms
            or normalised in place_terms
            or normalised in FACT_IMAGE_STOP_TERMS
        ):
            continue
        fallback_terms.append(term)
        if term[0].isupper():
            proper_terms.append(term)
        seen_terms.add(normalised)

    term_groups: list[list[str]] = []
    if proper_terms:
        term_groups.extend([proper_terms[:4], proper_terms[:2]])
    if fallback_terms:
        term_groups.extend([
            fallback_terms[:4],
            fallback_terms[-3:],
            fallback_terms[-2:],
            fallback_terms[:2],
        ])

    queries: list[str] = []
    for term_group in term_groups:
        query = " ".join(part for part in (place_name, *term_group) if part).strip()
        if query and query not in queries:
            queries.append(query)
    return queries


def named_roman_numerals(value: str) -> dict[str, str]:
    return {
        name.lower(): numeral.upper()
        for name, numeral in re.findall(r"\b([A-Z][a-z]+)\s+([IVXLCDM]+)\b", str(value or ""))
    }


def fact_image_match_score(
    fact: dict[str, Any],
    image: dict[str, str | None],
    place_terms: set[str],
) -> int:
    fact_text = f"{fact.get('title', '')} {fact.get('text', '')}"
    image_title = str(image.get("title") or "")
    fact_roman_names = named_roman_numerals(fact_text)
    image_roman_names = named_roman_numerals(image_title)
    if any(
        name in fact_roman_names and fact_roman_names[name] != numeral
        for name, numeral in image_roman_names.items()
    ):
        return 0

    fact_terms = fact_image_terms(
        fact_text,
        place_terms,
    )
    image_terms = fact_image_terms(image_title, place_terms)
    shared_terms = fact_terms.intersection(image_terms)
    if not shared_terms:
        return 0

    score = len(shared_terms) * 10
    text = str(fact.get("text") or "").lower()
    title = image_title.lower()
    if any(term in text and term in title for term in shared_terms):
        score += 4
    return score


def fetch_commons_fact_image(
    fact: dict[str, Any],
    place_title: str,
) -> dict[str, str | None] | None:
    queries = fact_image_queries(fact, place_title)
    if not queries:
        return None

    place_terms = fact_image_terms(place_title)
    seen_urls: set[str] = set()
    for query in queries:
        try:
            payload = fetch_json_url(commons_fact_image_search_url(query), timeout=5)
        except Exception as error:
            safe_log(f"History Commons fact image fetch failed: {error}")
            continue

        pages = payload.get("query", {}).get("pages", {}) if isinstance(payload, dict) else {}
        if not isinstance(pages, dict):
            continue

        candidates: list[tuple[int, dict[str, str | None]]] = []
        for page in pages.values():
            if not isinstance(page, dict):
                continue
            image = normalise_wikipedia_image(page)
            if image is None or not isinstance(image.get("url"), str):
                continue
            image_url = str(image["url"])
            if image_url in seen_urls:
                continue
            score = fact_image_match_score(fact, image, place_terms)
            if score > 0:
                candidates.append((score, image))
                seen_urls.add(image_url)

        candidates.sort(key=lambda candidate: candidate[0], reverse=True)
        if candidates:
            return candidates[0][1]

    return None


def attach_fact_images(
    facts: list[dict[str, Any]],
    images: list[dict[str, str | None]],
    place_title: str,
) -> list[dict[str, Any]]:
    place_terms = fact_image_terms(place_title)
    used_urls: set[str] = set()
    facts_with_images: list[dict[str, Any]] = []

    for fact in facts:
        ranked_images = sorted(
            (
                (fact_image_match_score(fact, image, place_terms), image)
                for image in images
                if isinstance(image.get("url"), str) and image["url"] not in used_urls
            ),
            key=lambda candidate: candidate[0],
            reverse=True,
        )
        next_fact = dict(fact)
        if ranked_images and ranked_images[0][0] > 0:
            image = ranked_images[0][1]
            next_fact["image"] = image
            used_urls.add(str(image["url"]))
        facts_with_images.append(next_fact)

    return facts_with_images


def fetch_missing_fact_images(
    facts: list[dict[str, Any]],
    place_title: str,
) -> list[dict[str, Any]]:
    missing_facts = [
        (index, fact)
        for index, fact in enumerate(facts)
        if not isinstance(fact.get("image"), dict)
    ]
    if not missing_facts:
        return facts

    used_urls = {
        str(image["url"])
        for fact in facts
        if isinstance((image := fact.get("image")), dict) and isinstance(image.get("url"), str)
    }
    with ThreadPoolExecutor(max_workers=min(3, len(missing_facts))) as executor:
        futures = [
            (index, executor.submit(fetch_commons_fact_image, fact, place_title))
            for index, fact in missing_facts
        ]
        for index, future in futures:
            try:
                image = future.result()
            except Exception as error:
                safe_log(f"History Commons fact image task failed: {error}")
                continue
            if image is None or not isinstance(image.get("url"), str):
                continue
            image_url = str(image["url"])
            if image_url in used_urls:
                continue
            facts[index]["image"] = image
            used_urls.add(image_url)

    return facts


def fetch_wikidata_entity(qid: str) -> dict[str, Any] | None:
    if not re.fullmatch(r"Q\d+", str(qid or "")):
        return None

    payload = fetch_json_url(wikidata_entity_url(qid))
    entity = payload.get("entities", {}).get(qid)
    return entity if isinstance(entity, dict) else None


def fetch_wikidata_labels(qids: list[str], lang: str) -> dict[str, str]:
    clean_qids = sorted({qid for qid in qids if re.fullmatch(r"Q\d+", qid)})
    if not clean_qids:
        return {}

    try:
        payload = fetch_json_url(wikidata_labels_url(clean_qids, lang))
    except Exception:
        return {}

    entities = payload.get("entities", {})
    if not isinstance(entities, dict):
        return {}

    labels: dict[str, str] = {}
    for qid, entity in entities.items():
        if not isinstance(entity, dict):
            continue
        label_map = entity.get("labels", {})
        if not isinstance(label_map, dict):
            continue
        label = label_map.get(lang) or label_map.get("en")
        if isinstance(label, dict) and isinstance(label.get("value"), str):
            labels[str(qid)] = label["value"]
    return labels


def split_fact_sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\[[^\]]+\]", "", str(text or ""))
    cleaned = re.sub(r"\s+", " ", cleaned)
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    return [sentence.strip() for sentence in sentences if sentence.strip()]


def clean_fact_sentence(sentence: str) -> str | None:
    cleaned = re.sub(r"=+\s*[^=]+\s*=+", " ", str(sentence or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) < 38 or len(cleaned) > 260:
        return None
    if " may refer to:" in cleaned.lower() or " may refer to " in cleaned.lower():
        return None
    if "according to" in cleaned.lower():
        return None
    if cleaned.count(",") > 8:
        return None
    return cleaned


def fact_keyword_score(text: str, keywords: tuple[str, ...], points: int) -> int:
    score = 0
    for keyword in keywords:
        pattern = rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])"
        if re.search(pattern, text.lower()):
            score += points
    return score


def classify_fact_theme(sentence: str) -> str:
    scored = [
        (fact_keyword_score(sentence, keywords, 1), theme)
        for theme, keywords in FACT_THEME_KEYWORDS.items()
    ]
    scored.sort(reverse=True)
    return scored[0][1] if scored and scored[0][0] > 0 else "general"


def fact_candidate_score(sentence: str, theme: str) -> int:
    score = 0 if theme == "general" else 30
    score += fact_keyword_score(sentence, FACT_THEME_KEYWORDS.get(theme, ()), 5)
    if re.search(r"\b(1[0-9]{3}|20[0-9]{2}|[0-9]{1,2}(st|nd|rd|th) century)\b", sentence):
        score += 12
    if 70 <= len(sentence) <= 190:
        score += 8
    return score


def make_history_fact(
    *,
    title: str,
    text: str,
    theme: str,
    source_name: str,
    source_url: str | None,
    confidence: str,
) -> dict[str, Any]:
    return {
        "title": title,
        "text": text,
        "theme": theme,
        "sourceName": source_name,
        "sourceUrl": source_url,
        "confidence": confidence,
    }


def wikipedia_facts(
    summary: dict[str, Any],
    plain_extract: str,
    limit: int,
    article_url: str | None,
) -> list[dict[str, Any]]:
    candidates: list[tuple[int, dict[str, Any]]] = []
    seen_sentences: set[str] = set()
    source_texts = [
        (str(summary.get("extract", "")), "medium"),
        (plain_extract, "medium"),
    ]

    for text, confidence in source_texts:
        for sentence in split_fact_sentences(text):
            cleaned = clean_fact_sentence(sentence)
            if cleaned is None:
                continue
            sentence_key = re.sub(r"\W+", "", cleaned.lower())[:120]
            if sentence_key in seen_sentences:
                continue
            seen_sentences.add(sentence_key)
            theme = classify_fact_theme(cleaned)
            fact = make_history_fact(
                title=FACT_THEME_LABELS.get(theme, "Local fact"),
                text=cleaned,
                theme=theme,
                source_name="Wikipedia",
                source_url=article_url,
                confidence=confidence,
            )
            candidates.append((fact_candidate_score(cleaned, theme), fact))

    candidates.sort(key=lambda candidate: candidate[0], reverse=True)
    selected: list[dict[str, Any]] = []
    selected_themes: set[str] = set()

    for _, fact in candidates:
        theme = str(fact.get("theme", "general"))
        if theme == "general" or theme in selected_themes:
            continue
        selected.append(fact)
        selected_themes.add(theme)
        if len(selected) >= limit:
            return selected

    for _, fact in candidates:
        if fact in selected:
            continue
        selected.append(fact)
        if len(selected) >= limit:
            break

    return selected


def wikidata_claims(entity: dict[str, Any], property_id: str) -> list[dict[str, Any]]:
    claims = entity.get("claims", {})
    values = claims.get(property_id, []) if isinstance(claims, dict) else []
    return values if isinstance(values, list) else []


def wikidata_claim_value(claim: dict[str, Any]) -> Any:
    mainsnak = claim.get("mainsnak", {}) if isinstance(claim, dict) else {}
    datavalue = mainsnak.get("datavalue", {}) if isinstance(mainsnak, dict) else {}
    return datavalue.get("value") if isinstance(datavalue, dict) else None


def wikidata_time_text(value: Any) -> str | None:
    if not isinstance(value, dict) or not isinstance(value.get("time"), str):
        return None
    match = re.search(r"([+-]\d{4,})-(\d{2})-(\d{2})", value["time"])
    if match is None:
        return None
    year = int(match.group(1))
    month = int(match.group(2))
    day = int(match.group(3))
    if month == 1 and day == 1:
        return str(year)
    return f"{year:04d}-{month:02d}-{day:02d}"


def wikidata_quantity_text(value: Any) -> str | None:
    if not isinstance(value, dict) or not isinstance(value.get("amount"), str):
        return None
    try:
        number = float(value["amount"])
    except ValueError:
        return None
    return f"{number:,.0f}" if number.is_integer() else f"{number:,.2f}"


def wikidata_entity_id(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    numeric_id = value.get("numeric-id")
    return f"Q{numeric_id}" if isinstance(numeric_id, int) else None


def wikidata_entity_label(entity: dict[str, Any], lang: str, fallback: str) -> str:
    labels = entity.get("labels", {})
    if isinstance(labels, dict):
        label = labels.get(lang) or labels.get("en")
        if isinstance(label, dict) and isinstance(label.get("value"), str):
            return label["value"]
    return fallback


def wikidata_profile(
    entity: dict[str, Any] | None,
    lang: str,
    fallback_title: str,
) -> dict[str, Any] | None:
    if entity is None:
        return None

    qid = str(entity.get("id", ""))
    source_url = f"https://www.wikidata.org/wiki/{qid}" if qid else None
    title = wikidata_entity_label(entity, lang, fallback_title)
    related_ids: list[str] = []

    for property_id in ("P31", "P131", "P17"):
        for claim in wikidata_claims(entity, property_id)[:3]:
            entity_id = wikidata_entity_id(wikidata_claim_value(claim))
            if entity_id:
                related_ids.append(entity_id)

    related_labels = fetch_wikidata_labels(related_ids, lang)
    instance_labels = [
        related_labels[entity_id]
        for claim in wikidata_claims(entity, "P31")[:3]
        if (entity_id := wikidata_entity_id(wikidata_claim_value(claim))) in related_labels
    ]
    population = None
    for claim in wikidata_claims(entity, "P1082")[:1]:
        population = wikidata_quantity_text(wikidata_claim_value(claim))

    inception = None
    for claim in wikidata_claims(entity, "P571")[:1]:
        inception = wikidata_time_text(wikidata_claim_value(claim))
    containing_places = [
        related_labels[entity_id]
        for claim in wikidata_claims(entity, "P131")[:2]
        if (entity_id := wikidata_entity_id(wikidata_claim_value(claim))) in related_labels
    ]
    countries = [
        related_labels[entity_id]
        for claim in wikidata_claims(entity, "P17")[:1]
        if (entity_id := wikidata_entity_id(wikidata_claim_value(claim))) in related_labels
    ]

    return {
        "title": title,
        "types": instance_labels,
        "population": population,
        "areas": containing_places,
        "country": countries[0] if countries else None,
        "inception": inception,
        "sourceName": "Wikidata",
        "sourceUrl": source_url,
    }


def wikidata_facts(
    entity: dict[str, Any] | None,
    lang: str,
    fallback_title: str,
) -> list[dict[str, Any]]:
    profile = wikidata_profile(entity, lang, fallback_title)
    if profile is None:
        return []

    title = str(profile.get("title") or fallback_title)
    source_url = profile.get("sourceUrl")
    facts: list[dict[str, Any]] = []
    place_parts = [str(area).strip() for area in profile.get("areas", []) if str(area).strip()]
    country = str(profile.get("country") or "").strip()
    if country and country not in place_parts:
        place_parts.append(country)

    if profile.get("types"):
        type_label = str(profile["types"][0]).strip()
        if type_label:
            place_text = f" in {', '.join(place_parts)}" if place_parts else ""
            facts.append(
                make_history_fact(
                    title="Wikidata record",
                    text=f"Wikidata lists {title} as a {type_label}{place_text}.",
                    theme="general",
                    source_name="Wikidata",
                    source_url=source_url,
                    confidence="high",
                )
            )

    population = str(profile.get("population") or "").strip()
    if population:
        facts.append(
            make_history_fact(
                title="Population",
                text=f"Wikidata records a population of about {population} for {title}.",
                theme="general",
                source_name="Wikidata",
                source_url=source_url,
                confidence="high",
            )
        )

    inception = str(profile.get("inception") or "").strip()
    if inception:
        facts.append(
            make_history_fact(
                title="Recorded in Wikidata",
                text=f"Wikidata traces {title} to {inception}.",
                theme="history",
                source_name="Wikidata",
                source_url=source_url,
                confidence="high",
            )
        )

    return facts


def build_location_facts(
    summary: dict[str, Any],
    plain_extract: str,
    limit: int,
    article_url: str | None,
    wikidata_entity: dict[str, Any] | None = None,
    lang: str = "en",
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    existing_texts: set[str] = set()
    title = str(summary.get("title") or "")
    candidate_facts = [
        *wikipedia_facts(summary, plain_extract, max(limit, 6), article_url),
        *wikidata_facts(wikidata_entity, lang, title),
    ]
    for fact in candidate_facts:
        text = str(fact.get("text", "")).lower()
        if text in existing_texts:
            continue
        facts.append(fact)
        existing_texts.add(text)
        if len(facts) >= limit:
            break

    return facts[:limit]


def fallback_fact_critique(fact: dict[str, Any], place_title: str) -> dict[str, Any]:
    text = str(fact.get("text") or "")
    theme = str(fact.get("theme") or "general")
    place_name = place_title.split(",", 1)[0].strip()
    score = fact_candidate_score(text, theme)
    mentions_place = place_name.lower() in text.lower()

    relevance = 9 if theme != "general" else 7
    if mentions_place:
        relevance = min(10, relevance + 1)
    place_specificity = 9 if theme in {"landmark", "history", "industry", "people"} else 8
    if theme == "general":
        place_specificity = 7
    interestingness = max(6, min(10, 5 + score // 10))
    theme_summary = {
        "history": "It highlights a historical detail tied directly to the place.",
        "landmark": "It names a recognisable local landmark rather than a generic town description.",
        "industry": "It points to a trade or industry strongly associated with the place.",
        "culture": "It surfaces a cultural detail that feels distinctive rather than generic.",
        "people": "It connects the place to notable people associated with it.",
        "date": "It gives a date-linked detail that is still rooted in the place itself.",
        "general": "It is still place-specific, but broader than the stronger themed facts.",
    }
    return {
        "relevance": relevance,
        "interestingness": interestingness,
        "placeSpecificity": place_specificity,
        "summary": theme_summary.get(theme, theme_summary["general"]),
    }


def attach_fact_critiques(
    facts: list[dict[str, Any]],
    place_title: str,
    critiques: dict[int, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for index, fact in enumerate(facts):
        critique = critiques.get(index) if critiques is not None else None
        next_fact = dict(fact)
        next_fact["critique"] = critique or fallback_fact_critique(fact, place_title)
        enriched.append(next_fact)
    return enriched


def public_history_fact(fact: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in fact.items()
        if key != "critique"
    }


def history_fact_diversity_key(fact: dict[str, Any], place_title: str) -> str:
    subject = extract_fact_subject(
        " ".join(
            part
            for part in (
                str(fact.get("title") or "").strip(),
                str(fact.get("text") or "").strip(),
            )
            if part
        ),
        place_title,
    )
    if subject:
        return history_fact_text_key(subject)
    title = str(fact.get("title") or "").strip()
    if title and title.casefold() not in FACT_GENERIC_FACT_TITLES:
        return history_fact_text_key(title)
    source_url = str(fact.get("sourceUrl") or "").strip()
    if source_url:
        parsed = urlparse(source_url)
        return history_fact_text_key(f"{parsed.netloc}{parsed.path}")
    return history_fact_text_key(str(fact.get("text") or "")[:80])


def history_fact_source_key(fact: dict[str, Any]) -> str:
    source_url = str(fact.get("sourceUrl") or "").strip()
    if source_url:
        parsed = urlparse(source_url)
        return history_fact_text_key(parsed.netloc)
    return history_fact_text_key(str(fact.get("sourceName") or ""))


def rotated_location_facts(
    candidates: list[dict[str, Any]],
    *,
    limit: int,
    recent_texts: list[str],
    place_title: str,
) -> list[dict[str, Any]]:
    recent_keys = {history_fact_text_key(text) for text in recent_texts}

    def choose(
        pool: list[dict[str, Any]],
        selected: list[dict[str, Any]],
        require_new_theme: bool,
        require_new_source: bool,
    ) -> None:
        selected_keys = {history_fact_text_key(str(item.get("text") or "")) for item in selected}
        selected_themes = {str(item.get("theme") or "general") for item in selected}
        selected_diversity = {history_fact_diversity_key(item, place_title) for item in selected}
        selected_sources = {history_fact_source_key(item) for item in selected}
        selected_title_keys = {
            history_fact_text_key(str(item.get("title") or ""))
            for item in selected
            if str(item.get("title") or "").strip()
        }
        for fact in pool:
            text_key = history_fact_text_key(str(fact.get("text") or ""))
            theme = str(fact.get("theme") or "general")
            diversity_key = history_fact_diversity_key(fact, place_title)
            source_key = history_fact_source_key(fact)
            title_key = history_fact_text_key(str(fact.get("title") or ""))
            if text_key in selected_keys:
                continue
            if diversity_key in selected_diversity:
                continue
            if title_key and any(
                title_key.startswith(existing_key) or existing_key.startswith(title_key)
                for existing_key in selected_title_keys
            ):
                continue
            if require_new_theme and theme != "general" and theme in selected_themes:
                continue
            if require_new_source and source_key in selected_sources:
                continue
            selected.append(dict(fact))
            selected_keys.add(text_key)
            selected_themes.add(theme)
            selected_diversity.add(diversity_key)
            selected_sources.add(source_key)
            if title_key:
                selected_title_keys.add(title_key)
            if len(selected) >= limit:
                return

    fresh_candidates = [
        fact
        for fact in candidates
        if history_fact_text_key(str(fact.get("text") or "")) not in recent_keys
    ]
    selected: list[dict[str, Any]] = []
    choose(fresh_candidates, selected, True, True)
    if len(selected) < limit:
        choose(fresh_candidates, selected, False, True)
    if len(selected) < limit:
        choose(candidates, selected, True, False)
    if len(selected) < limit:
        choose(candidates, selected, False, False)
    return selected[:limit]


def store_history_fact_review_failure(
    rotation_key: str,
    *,
    selection: dict[str, Any] | None,
    critique: dict[str, Any] | None,
    failure_reason: str,
    created_at: str | None = None,
) -> None:
    timestamp = created_at or utc_now()
    with closing(connect_db()) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO history_fact_review_failures (
                    rotation_key,
                    selection_json,
                    critique_json,
                    failure_reason,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    rotation_key,
                    json.dumps(selection, ensure_ascii=True) if selection is not None else None,
                    json.dumps(critique, ensure_ascii=True) if critique is not None else None,
                    failure_reason,
                    timestamp,
                ),
            )
            conn.execute(
                """
                DELETE FROM history_fact_review_failures
                WHERE rotation_key = ?
                  AND id NOT IN (
                    SELECT id
                    FROM history_fact_review_failures
                    WHERE rotation_key = ?
                    ORDER BY created_at DESC
                    LIMIT 16
                  )
                """,
                (rotation_key, rotation_key),
            )


def recent_history_fact_review_failures(
    rotation_key: str,
    *,
    limit: int = 4,
) -> list[dict[str, Any]]:
    with closing(connect_db()) as conn:
        rows = conn.execute(
            """
            SELECT selection_json, critique_json, failure_reason, created_at
            FROM history_fact_review_failures
            WHERE rotation_key = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (rotation_key, max(1, limit)),
        ).fetchall()

    failures: list[dict[str, Any]] = []
    for row in rows:
        payload: dict[str, Any] = {
            "failureReason": str(row["failure_reason"] or ""),
            "createdAt": str(row["created_at"] or ""),
        }
        if row["selection_json"]:
            try:
                payload["selection"] = json.loads(str(row["selection_json"]))
            except json.JSONDecodeError:
                pass
        if row["critique_json"]:
            try:
                payload["critique"] = json.loads(str(row["critique_json"]))
            except json.JSONDecodeError:
                pass
        failures.append(payload)
    return failures


def ai_fact_generation_schema(limit: int) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "facts": {
                "type": "array",
                "minItems": limit,
                "maxItems": limit,
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "text": {"type": "string"},
                        "theme": {"type": "string", "enum": list(FACT_THEME_LABELS)},
                        "sourceEvidenceIndex": {"type": "integer", "minimum": 0},
                    },
                    "required": ["title", "text", "theme", "sourceEvidenceIndex"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["facts"],
        "additionalProperties": False,
    }


def ai_single_fact_generation_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "text": {"type": "string"},
            "theme": {"type": "string", "enum": list(FACT_THEME_LABELS)},
            "sourceEvidenceIndex": {"type": "integer", "minimum": 0},
        },
        "required": ["title", "text", "theme", "sourceEvidenceIndex"],
        "additionalProperties": False,
    }


def ai_fact_critique_schema(limit: int) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "overallPassed": {"type": "boolean"},
            "notes": {"type": "string"},
            "facts": {
                "type": "array",
                "minItems": limit,
                "maxItems": limit,
                "items": {
                    "type": "object",
                    "properties": {
                        "candidateIndex": {"type": "integer", "minimum": 0},
                        "passed": {"type": "boolean"},
                        "relevance": {"type": "integer", "minimum": 0, "maximum": 10},
                        "interestingness": {"type": "integer", "minimum": 0, "maximum": 10},
                        "placeSpecificity": {"type": "integer", "minimum": 0, "maximum": 10},
                        "summary": {"type": "string"},
                    },
                    "required": [
                        "candidateIndex",
                        "passed",
                        "relevance",
                        "interestingness",
                        "placeSpecificity",
                        "summary",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["overallPassed", "notes", "facts"],
        "additionalProperties": False,
    }

def current_facts_ai_timeout_sec() -> float:
    override = getattr(FACTS_AI_CONTEXT, "timeout_sec", None)
    if isinstance(override, (int, float)) and override > 0:
        return float(override)
    return float(FACTS_AI_TIMEOUT_SEC)


def current_facts_ai_request_delay_sec() -> float:
    override = getattr(FACTS_AI_CONTEXT, "request_delay_sec", None)
    if isinstance(override, (int, float)) and override >= 0:
        return float(override)
    return FACTS_AI_REQUEST_DELAY_SEC


def current_facts_ai_transient_retries() -> int:
    override = getattr(FACTS_AI_CONTEXT, "transient_retries", None)
    if isinstance(override, int) and override >= 0:
        return override
    return FACTS_AI_TRANSIENT_RETRIES


def current_facts_ai_budget_sec(task: str) -> float:
    attribute = "critic_budget_sec" if task == "critic" else "generator_budget_sec"
    override = getattr(FACTS_AI_CONTEXT, attribute, None)
    if isinstance(override, (int, float)) and override > 0:
        return float(override)
    return FACTS_AI_CRITIC_BUDGET_SEC if task == "critic" else FACTS_AI_GENERATOR_BUDGET_SEC


def current_facts_web_search_timeout_sec() -> int:
    override = getattr(FACTS_AI_CONTEXT, "web_search_timeout_sec", None)
    if isinstance(override, int) and override > 0:
        return override
    return FACTS_WEB_SEARCH_TIMEOUT_SEC


@contextmanager
def facts_ai_overrides(
    *,
    timeout_sec: int | None = None,
    transient_retries: int | None = None,
    generator_budget_sec: float | None = None,
    critic_budget_sec: float | None = None,
    web_search_timeout_sec: int | None = None,
) -> Any:
    fields = {
        "timeout_sec": timeout_sec,
        "transient_retries": transient_retries,
        "generator_budget_sec": generator_budget_sec,
        "critic_budget_sec": critic_budget_sec,
        "web_search_timeout_sec": web_search_timeout_sec,
    }
    marker = object()
    previous: dict[str, object] = {}
    for field, value in fields.items():
        previous[field] = getattr(FACTS_AI_CONTEXT, field, marker)
        if value is None:
            continue
        setattr(FACTS_AI_CONTEXT, field, value)
    try:
        yield
    finally:
        for field, prior in previous.items():
            if prior is marker:
                if hasattr(FACTS_AI_CONTEXT, field):
                    delattr(FACTS_AI_CONTEXT, field)
            else:
                setattr(FACTS_AI_CONTEXT, field, prior)


def facts_ai_budget_deadline(task: str) -> float:
    budget_sec = current_facts_ai_budget_sec(task)
    return time.monotonic() + budget_sec


def set_facts_ai_deadline(deadline_monotonic: float | None) -> None:
    FACTS_AI_CONTEXT.deadline_monotonic = deadline_monotonic


def current_facts_ai_deadline() -> float | None:
    deadline = getattr(FACTS_AI_CONTEXT, "deadline_monotonic", None)
    return deadline if isinstance(deadline, (int, float)) else None


def facts_ai_remaining_budget_sec(deadline_monotonic: float | None) -> float | None:
    if deadline_monotonic is None:
        return None
    return deadline_monotonic - time.monotonic()


def facts_ai_request_timeout(deadline_monotonic: float | None) -> float:
    remaining = facts_ai_remaining_budget_sec(deadline_monotonic)
    if remaining is None:
        return current_facts_ai_timeout_sec()
    if remaining <= 0.25:
        raise TimeoutError("Facts AI budget exceeded.")
    return min(current_facts_ai_timeout_sec(), remaining)


def facts_ai_wait_for_request_slot(deadline_monotonic: float | None = None) -> None:
    global FACTS_AI_NEXT_REQUEST_AT
    request_delay_sec = current_facts_ai_request_delay_sec()
    with FACTS_AI_LOCK:
        now = time.monotonic()
        wait_sec = FACTS_AI_NEXT_REQUEST_AT - now
        if deadline_monotonic is not None:
            remaining_sec = deadline_monotonic - now
            if remaining_sec <= 0:
                raise TimeoutError("Facts AI budget exceeded.")
            wait_sec = min(wait_sec, remaining_sec)
        if wait_sec > 0:
            time.sleep(wait_sec)
        now = time.monotonic()
        if deadline_monotonic is not None and now >= deadline_monotonic:
            raise TimeoutError("Facts AI budget exceeded.")
        FACTS_AI_NEXT_REQUEST_AT = now + request_delay_sec


def facts_ai_defer_retry(
    attempt: int,
    error: HTTPError | None = None,
    deadline_monotonic: float | None = None,
) -> None:
    global FACTS_AI_NEXT_REQUEST_AT
    retry_after_sec = 0.0
    if error is not None:
        retry_after = error.headers.get("Retry-After", "").strip()
        try:
            retry_after_sec = float(retry_after)
        except ValueError:
            retry_after_sec = 0.0
        try:
            error_payload = json.loads(error.read().decode("utf-8"))
            details = error_payload.get("error", {}).get("details", [])
            retry_info = next(
                (
                    detail
                    for detail in details
                    if str(detail.get("@type", "")).endswith("RetryInfo")
                ),
                {},
            )
            retry_delay = str(retry_info.get("retryDelay", "")).rstrip("s")
            retry_after_sec = max(retry_after_sec, float(retry_delay or 0))
        except (AttributeError, json.JSONDecodeError, TypeError, ValueError):
            pass
    delay = max(
        current_facts_ai_request_delay_sec(),
        retry_after_sec,
        min(45.0, 3.0 * (2**attempt)),
    )
    remaining = facts_ai_remaining_budget_sec(deadline_monotonic)
    if remaining is not None:
        if remaining <= 0:
            return
        delay = min(delay, remaining)
    with FACTS_AI_LOCK:
        FACTS_AI_NEXT_REQUEST_AT = max(FACTS_AI_NEXT_REQUEST_AT, time.monotonic() + delay)


def facts_fallback_spec(stage: int, task: str) -> tuple[str, str, str, str]:
    if stage == 1:
        provider = FACTS_FALLBACK_PROVIDER
        api_key = FACTS_FALLBACK_API_KEY
        base_url = FACTS_FALLBACK_BASE_URL
        model = FACTS_FALLBACK_CRITIC_MODEL if task == "critic" else FACTS_FALLBACK_GENERATOR_MODEL
        return provider, api_key, base_url, model
    if stage == 2:
        provider = FACTS_FALLBACK2_PROVIDER
        api_key = FACTS_FALLBACK2_API_KEY
        base_url = FACTS_FALLBACK2_BASE_URL
        model = FACTS_FALLBACK2_CRITIC_MODEL if task == "critic" else FACTS_FALLBACK2_GENERATOR_MODEL
        return provider, api_key, base_url, model
    return "", "", "", ""


def facts_fallback_configured(stage: int, task: str) -> bool:
    provider, api_key, base_url, model = facts_fallback_spec(stage, task)
    return bool(
        provider in {"groq", "openrouter", "openai-compatible"}
        and api_key
        and base_url
        and model
    )


def facts_ai_available() -> bool:
    return bool(FACTS_GEMINI_API_KEY) or (
        (facts_fallback_configured(1, "generator") and facts_fallback_configured(1, "critic"))
        or (facts_fallback_configured(2, "generator") and facts_fallback_configured(2, "critic"))
    )


def facts_gemini_json_response(
    *,
    model: str,
    prompt: str,
    schema: dict[str, Any],
    google_search: bool = False,
) -> dict[str, Any]:
    if not FACTS_GEMINI_API_KEY:
        raise ValueError("Gemini API key is not configured.")

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{quote(model, safe='')}:generateContent"
    )
    request = Request(
        url,
        data=json.dumps(
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "tools": [{"google_search": {}}] if google_search else [],
                "generationConfig": {
                    "temperature": 0.4,
                    "responseMimeType": "application/json",
                    "responseJsonSchema": schema,
                },
            }
        ).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": FACTS_GEMINI_API_KEY,
        },
        method="POST",
    )

    transient_retries = current_facts_ai_transient_retries()
    for attempt in range(transient_retries + 1):
        deadline_monotonic = current_facts_ai_deadline()
        facts_ai_wait_for_request_slot(deadline_monotonic)
        try:
            with urlopen(request, timeout=facts_ai_request_timeout(deadline_monotonic)) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except HTTPError as error:
            if error.code in {429, 500, 502, 503, 504} and attempt < transient_retries:
                facts_ai_defer_retry(attempt, error, deadline_monotonic)
                continue
            raise RuntimeError(f"Gemini request failed with HTTP {error.code}.") from error
        except (TimeoutError, URLError, OSError) as error:
            if attempt < transient_retries:
                facts_ai_defer_retry(attempt, deadline_monotonic=deadline_monotonic)
                continue
            raise RuntimeError(f"Gemini request timed out or failed: {error}") from error
    else:  # pragma: no cover - loop exits through break or raise
        raise RuntimeError("Gemini request failed.")

    try:
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
    except (IndexError, KeyError, TypeError) as error:
        raise ValueError("Gemini returned no structured content.") from error
    return parse_json_object(text)


def facts_compatible_json_response(
    *,
    provider_name: str,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not api_key or not base_url:
        raise ValueError("Compatible fallback provider is not configured.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if provider_name == "openrouter":
        headers["HTTP-Referer"] = "https://fultons-quiz.co.uk"
        headers["X-Title"] = "Fultons Quiz"

    request = Request(
        f"{base_url}/chat/completions",
        data=json.dumps(
            {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": "Return one valid JSON object only. Do not use markdown.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.4,
                "max_tokens": 1000,
                "stream": False,
                "response_format": (
                    {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "fultons_fact_response",
                            "strict": True,
                            "schema": schema,
                        },
                    }
                    if schema is not None
                    else {"type": "json_object"}
                ),
            }
        ).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    transient_retries = current_facts_ai_transient_retries()
    for attempt in range(transient_retries + 1):
        deadline_monotonic = current_facts_ai_deadline()
        facts_ai_wait_for_request_slot(deadline_monotonic)
        try:
            with urlopen(request, timeout=facts_ai_request_timeout(deadline_monotonic)) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except HTTPError as error:
            if error.code in {408, 429, 500, 502, 503, 504} and attempt < transient_retries:
                facts_ai_defer_retry(attempt, error, deadline_monotonic)
                continue
            raise RuntimeError(f"{provider_name} request failed with HTTP {error.code}.") from error
        except (TimeoutError, URLError, OSError) as error:
            if attempt < transient_retries:
                facts_ai_defer_retry(attempt, deadline_monotonic=deadline_monotonic)
                continue
            raise RuntimeError(f"{provider_name} request timed out or failed: {error}") from error
    else:  # pragma: no cover - loop exits through break or raise
        raise RuntimeError(f"{provider_name} request failed.")

    try:
        text = payload["choices"][0]["message"]["content"]
    except (IndexError, KeyError, TypeError) as error:
        raise ValueError(f"{provider_name} returned no chat completion content.") from error
    if isinstance(text, list):
        parts: list[str] = []
        for part in text:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(str(part["text"]))
        text = "\n".join(part for part in parts if part.strip())
    return parse_json_object(text)


def facts_ai_json_response(
    *,
    task: str,
    model: str,
    prompt: str,
    schema: dict[str, Any],
    google_search: bool = False,
) -> dict[str, Any]:
    deadline_monotonic = current_facts_ai_deadline()
    created_deadline = deadline_monotonic is None
    if deadline_monotonic is None:
        deadline_monotonic = facts_ai_budget_deadline(task)
    primary_error: Exception | None = None
    if created_deadline:
        set_facts_ai_deadline(deadline_monotonic)
    try:
        if FACTS_GEMINI_API_KEY:
            try:
                return facts_gemini_json_response(
                    model=model,
                    prompt=prompt,
                    schema=schema,
                    google_search=google_search,
                )
            except Exception as error:
                primary_error = error
                if not facts_fallback_configured(1, task) and not facts_fallback_configured(2, task):
                    raise
                safe_log(f"Facts AI falling back from Gemini: {error}")

        fallback_errors: list[str] = []
        for stage in (1, 2):
            if not facts_fallback_configured(stage, task):
                continue
            provider_name, api_key, base_url, model = facts_fallback_spec(stage, task)
            try:
                return facts_compatible_json_response(
                    provider_name=provider_name,
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    prompt=prompt,
                    schema=schema,
                )
            except Exception as error:
                fallback_errors.append(f"{provider_name}:{model}: {error}")
                continue

        if primary_error is not None:
            if fallback_errors:
                raise RuntimeError(
                    f"{primary_error} | Fallback failures: {' | '.join(fallback_errors)}"
                ) from primary_error
            raise primary_error
        if fallback_errors:
            raise RuntimeError(f"Fallback failures: {' | '.join(fallback_errors)}")
        raise ValueError("No facts AI provider is configured.")
    finally:
        if created_deadline:
            set_facts_ai_deadline(None)


def normalize_ai_generated_fact_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items: list[Any] = []
    facts_value = payload.get("facts")
    if isinstance(facts_value, list):
        raw_items.extend(facts_value)
    elif isinstance(facts_value, dict):
        raw_items.append(facts_value)
    elif isinstance(facts_value, str):
        raw_items.append({"text": facts_value})

    for field in ("items", "results"):
        value = payload.get(field)
        if not raw_items and isinstance(value, list):
            raw_items.extend(value)

    if not raw_items and any(
        key in payload
        for key in (
            "title",
            "text",
            "fact",
            "sentence",
            "content",
            "sourceEvidenceIndex",
            "evidenceIndex",
            "sourceIndex",
        )
    ):
        raw_items.append(payload)

    normalized: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if isinstance(raw_item, str):
            item: dict[str, Any] = {"text": raw_item}
        elif isinstance(raw_item, dict):
            item = raw_item
        else:
            continue

        text = str(
            item.get("text")
            or item.get("fact")
            or item.get("sentence")
            or item.get("content")
            or ""
        ).strip()
        title = trim_fact_title(str(item.get("title") or item.get("headline") or item.get("label") or ""))
        theme = str(item.get("theme") or "").strip().casefold()
        if theme not in FACT_THEME_LABELS:
            theme = classify_fact_theme(" ".join(part for part in (title, text) if part))
        evidence_value = (
            item.get("sourceEvidenceIndex")
            if item.get("sourceEvidenceIndex") is not None
            else item.get("evidenceIndex", item.get("sourceIndex"))
        )
        try:
            source_evidence_index = int(str(evidence_value).strip())
        except (TypeError, ValueError, AttributeError):
            source_evidence_index = -1
        normalized.append(
            {
                "title": title,
                "text": text,
                "theme": theme if theme in FACT_THEME_LABELS else "general",
                "sourceEvidenceIndex": source_evidence_index,
            }
        )
    return normalized


def build_selected_ai_fact(
    item: dict[str, Any],
    *,
    place_title: str,
    web_evidence: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], str]:
    evidence_index = int(item.get("sourceEvidenceIndex", -1))
    if evidence_index < 0 or evidence_index >= len(web_evidence):
        raise ValueError("Facts AI generated fact referenced an unknown web evidence item.")
    evidence_item = web_evidence[evidence_index]
    source_name = str(evidence_item.get("sourceName") or "").strip()
    source_url = str(evidence_item.get("sourceUrl") or "").strip()
    if not source_name or not source_url.startswith(("http://", "https://")):
        raise ValueError("Web evidence is missing a valid source.")
    if blocked_fact_source(source_url):
        raise ValueError("Facts AI selected blocked evidence from Wikipedia or Wikidata.")
    fact_text = str(item.get("text") or "").strip()
    if not fact_text:
        raise ValueError("Facts AI generated fact text is empty.")
    theme = str(item.get("theme") or "general")
    if theme not in FACT_THEME_LABELS:
        theme = classify_fact_theme(" ".join(part for part in (str(item.get("title") or ""), fact_text) if part))
    selected_fact = {
        "title": meaningful_fact_title(
            str(item.get("title") or ""),
            fact_text,
            str(evidence_item.get("title") or ""),
            place_title,
            theme,
        ),
        "text": fact_text,
        "theme": theme,
        "sourceName": source_name,
        "sourceUrl": source_url,
        "confidence": "medium",
    }
    critique_payload = {
        "title": selected_fact["title"],
        "text": selected_fact["text"],
        "theme": selected_fact.get("theme"),
        "sourceName": source_name,
        "sourceUrl": source_url,
        "evidenceTitle": str(evidence_item.get("title") or ""),
        "evidenceSnippet": str(evidence_item.get("snippet") or ""),
        "evidenceExcerpt": str(evidence_item.get("excerpt") or ""),
    }
    return selected_fact, critique_payload, history_fact_text_key(fact_text)


def combine_distinct_history_facts(
    preferred: list[dict[str, Any]],
    supplemental: list[dict[str, Any]],
    *,
    place_title: str,
    limit: int,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for fact in [*preferred, *supplemental]:
        if not isinstance(fact, dict):
            continue
        fact_key = history_fact_diversity_key(fact, place_title)
        if not fact_key or fact_key in seen_keys:
            continue
        seen_keys.add(fact_key)
        merged.append({key: value for key, value in fact.items() if key != "critique"})
        if len(merged) >= limit:
            break
    return merged


def reviewed_location_facts(
    rotation_key: str,
    place_title: str,
    candidates: list[dict[str, Any]],
    *,
    limit: int,
    recent_texts: list[str],
) -> list[dict[str, Any]]:
    fallback = attach_fact_critiques(
        rotated_location_facts(
            candidates,
            limit=limit,
            recent_texts=recent_texts,
            place_title=place_title,
        ),
        place_title,
    )
    web_evidence = search_web_fact_evidence(
        place_title,
        candidates=candidates,
        limit=max(limit * 6, 12),
    )
    web_fallback = web_evidence_fallback_facts(
        place_title,
        web_evidence,
        limit=limit,
        recent_texts=recent_texts,
    )
    if not facts_ai_available():
        return web_fallback or fallback

    failed_attempts = recent_history_fact_review_failures(rotation_key)
    if not web_evidence:
        safe_log(
            "Interesting fact review fell back to heuristics: "
            f"insufficient usable web evidence found for {place_title}."
        )
        return fallback

    candidate_payload = [
        {
            "candidateIndex": index,
            "title": str(candidate.get("title") or ""),
            "text": str(candidate.get("text") or ""),
            "theme": str(candidate.get("theme") or "general"),
            "sourceName": str(candidate.get("sourceName") or ""),
            "sourceUrl": candidate.get("sourceUrl"),
            "confidence": str(candidate.get("confidence") or "medium"),
        }
        for index, candidate in enumerate(candidates)
    ]
    evidence_payload = [
        {
            "evidenceIndex": index,
            "title": str(item.get("title") or ""),
            "sourceName": str(item.get("sourceName") or ""),
            "sourceUrl": str(item.get("sourceUrl") or ""),
            "snippet": str(item.get("snippet") or ""),
            "excerpt": str(item.get("excerpt") or ""),
        }
        for index, item in enumerate(web_evidence)
    ]
    selection_result: dict[str, Any] | None = None
    critique_result: dict[str, Any] | None = None
    selection_attempts: list[dict[str, Any]] = []
    normalized_selection_items: list[dict[str, Any]] = []
    selected_facts: list[dict[str, Any]] = []
    selected_for_critique: list[dict[str, Any]] = []
    selector_prompt = (
        "You are writing two reviewed local-interest facts for a live facts page.\n\n"
        f"Place: {place_title}\n"
        f"Web evidence gathered for this place:\n{json.dumps(evidence_payload, ensure_ascii=True, indent=2)}\n"
        f"Local reference context:\n{json.dumps(candidate_payload, ensure_ascii=True, indent=2)}\n"
        f"Recent facts to avoid repeating in the next 24-hour rotation:\n"
        f"{json.dumps(recent_texts[:6], ensure_ascii=True, indent=2)}\n"
        f"Previous failed selections and feedback:\n{json.dumps(failed_attempts, ensure_ascii=True, indent=2)}\n\n"
        f"Write exactly {limit} facts.\n"
        "Use the web evidence as the source base and the local reference context only as background support.\n"
        "Each fact must be clearly about the named place, genuinely interesting, and distinct from the other fact.\n"
        "Prefer evidence from local councils, museums, universities, tourism boards, official organisations, or reputable reporting.\n"
        "Avoid generic summary lines and avoid repeating the recent facts or prior failed ideas.\n"
        "The output text should feel freshly written by the AI, not copied from one source sentence.\n"
        "Do not add unsupported claims.\n"
        "For each fact, return the sourceEvidenceIndex for the best single supporting evidence item from the web evidence list."
    )

    try:
        generator_deadline = facts_ai_budget_deadline("generator")
        set_facts_ai_deadline(generator_deadline)
        seen_fact_keys: set[str] = set()
        recent_fact_keys = {history_fact_text_key(text) for text in recent_texts}
        try:
            initial_selection = facts_ai_json_response(
                task="generator",
                model=FACTS_AI_GENERATOR_MODEL,
                schema=ai_fact_generation_schema(limit),
                prompt=selector_prompt,
            )
            selection_attempts.append(initial_selection)
            normalized_selection_items.extend(normalize_ai_generated_fact_items(initial_selection))

            while len(selected_facts) < limit and normalized_selection_items:
                item = normalized_selection_items.pop(0)
                try:
                    selected_fact, critique_fact, fact_key = build_selected_ai_fact(
                        item,
                        place_title=place_title,
                        web_evidence=web_evidence,
                    )
                except ValueError:
                    continue
                if fact_key in seen_fact_keys or fact_key in recent_fact_keys:
                    continue
                seen_fact_keys.add(fact_key)
                critique_fact["factIndex"] = len(selected_for_critique)
                selected_facts.append(selected_fact)
                selected_for_critique.append(critique_fact)

            max_top_up_attempts = max(1, (limit - len(selected_facts)) * 2)
            for _ in range(max_top_up_attempts):
                if len(selected_facts) >= limit:
                    break
                top_up_prompt = (
                    "You are filling one remaining fact slot for a live local facts page.\n\n"
                    f"Place: {place_title}\n"
                    f"Web evidence gathered for this place:\n{json.dumps(evidence_payload, ensure_ascii=True, indent=2)}\n"
                    f"Already accepted facts:\n{json.dumps(selected_for_critique, ensure_ascii=True, indent=2)}\n"
                    f"Recent facts to avoid repeating:\n{json.dumps(recent_texts[:6], ensure_ascii=True, indent=2)}\n"
                    f"Previous failed selections and feedback:\n{json.dumps(failed_attempts, ensure_ascii=True, indent=2)}\n\n"
                    "Return exactly one additional fact as one JSON object, not an array.\n"
                    "It must be clearly about the named place, distinct from the accepted facts, and backed by one web evidence item.\n"
                    "Use sourceEvidenceIndex for the strongest supporting evidence item."
                )
                top_up_selection = facts_ai_json_response(
                    task="generator",
                    model=FACTS_AI_GENERATOR_MODEL,
                    schema=ai_single_fact_generation_schema(),
                    prompt=top_up_prompt,
                )
                selection_attempts.append(top_up_selection)
                top_up_items = normalize_ai_generated_fact_items(top_up_selection)
                if not top_up_items:
                    continue
                for item in top_up_items:
                    if len(selected_facts) >= limit:
                        break
                    try:
                        selected_fact, critique_fact, fact_key = build_selected_ai_fact(
                            item,
                            place_title=place_title,
                            web_evidence=web_evidence,
                        )
                    except ValueError:
                        continue
                    if fact_key in seen_fact_keys or fact_key in recent_fact_keys:
                        continue
                    seen_fact_keys.add(fact_key)
                    critique_fact["factIndex"] = len(selected_for_critique)
                    selected_facts.append(selected_fact)
                    selected_for_critique.append(critique_fact)
        finally:
            set_facts_ai_deadline(None)

        selection_result = {
            "attempts": selection_attempts,
            "facts": [
                {
                    "title": fact.get("title"),
                    "text": fact.get("text"),
                    "theme": fact.get("theme"),
                    "sourceUrl": fact.get("sourceUrl"),
                    "sourceName": fact.get("sourceName"),
                }
                for fact in selected_facts
            ],
        }
        if len(selected_facts) != limit:
            raise ValueError("Facts AI did not produce enough usable facts.")

        critique_prompt = (
            "You are the critic for a live local facts page.\n\n"
            f"Place: {place_title}\n"
            f"Web evidence gathered for this place:\n{json.dumps(evidence_payload, ensure_ascii=True, indent=2)}\n"
            f"Local reference context:\n{json.dumps(candidate_payload, ensure_ascii=True, indent=2)}\n"
            f"Generated facts:\n{json.dumps(selected_for_critique, ensure_ascii=True, indent=2)}\n"
            f"Recent facts already used for this place:\n{json.dumps(recent_texts[:6], ensure_ascii=True, indent=2)}\n"
            f"Previous failed selections and feedback:\n{json.dumps(failed_attempts, ensure_ascii=True, indent=2)}\n\n"
            "Critique the generated facts for place relevance and interestingness.\n"
            "A fact should pass only if it is clearly about the named place, says something distinctive, "
            "and stays faithful to its cited source evidence.\n"
            "Fail facts if the cited evidence does not support them, if they are too generic, or if they repeat recent ideas.\n"
            "Use the recent facts list to penalise repetition.\n"
            "Set overallPassed to true only if every fact passes."
        )
        critique_result = facts_ai_json_response(
            task="critic",
            model=FACTS_AI_CRITIC_MODEL,
            schema=ai_fact_critique_schema(limit),
            prompt=critique_prompt,
        )
        critique_items = critique_result.get("facts", [])
        if not critique_result.get("overallPassed") or not isinstance(critique_items, list):
            raise ValueError("Gemini critique rejected the selected facts.")

        critique_map: dict[int, dict[str, Any]] = {}
        for critique_item in critique_items:
            if not isinstance(critique_item, dict):
                raise ValueError("Gemini critique fact is not an object.")
            fact_index = int(critique_item.get("candidateIndex", critique_item.get("factIndex", -1)))
            if fact_index < 0 or fact_index >= len(selected_facts):
                raise ValueError("Gemini critique referenced an unknown generated fact.")
            if not bool(critique_item.get("passed")):
                raise ValueError("Gemini critique failed a selected fact.")
            if any(
                int(critique_item.get(field, 0)) < threshold
                for field, threshold in FACT_CRITIC_THRESHOLDS.items()
            ):
                raise ValueError("Gemini critique scores did not meet the thresholds.")
            critique_map[fact_index] = {
                "relevance": int(critique_item.get("relevance", 0)),
                "interestingness": int(critique_item.get("interestingness", 0)),
                "placeSpecificity": int(critique_item.get("placeSpecificity", 0)),
                "summary": str(critique_item.get("summary") or "").strip(),
            }

        if len(critique_map) != len(selected_facts):
            raise ValueError("Gemini critique did not cover every selected fact.")
        return attach_fact_critiques(selected_facts, place_title, critique_map)
    except Exception as error:
        store_history_fact_review_failure(
            rotation_key,
            selection=selection_result,
            critique=critique_result,
            failure_reason=str(error),
        )
        if selected_facts:
            supplemented = combine_distinct_history_facts(
                selected_facts,
                web_fallback or fallback,
                place_title=place_title,
                limit=limit,
            )
            if len(supplemented) >= limit:
                safe_log(
                    "Interesting fact review kept generated facts and filled remaining slots heuristically: "
                    f"{error}"
                )
                return attach_fact_critiques(supplemented, place_title)
            safe_log(
                "Interesting fact review kept generated facts with heuristic critiques: "
                f"{error}"
            )
            return attach_fact_critiques(selected_facts, place_title)
        safe_log(f"Interesting fact review fell back to web evidence heuristics: {error}")
        return web_fallback or fallback


def history_year_value(value: object) -> int | None:
    raw = str(value or "").strip()
    match = re.search(r"\d+", raw)
    if match is None:
        return None
    year = int(match.group(0))
    return -year if "BC" in raw.upper() or "BCE" in raw.upper() else year


def history_keyword_score(text: str, keywords: tuple[str, ...], points: int) -> int:
    text_lower = text.lower()
    return sum(points for keyword in keywords if keyword in text_lower)


def history_recency_score(year: int | None) -> int:
    if year is None:
        return 0
    if year < 0:
        return -20

    current_year = datetime.now(timezone.utc).year
    age = current_year - year
    if age < 0:
        return 0
    if age <= 40:
        return 60
    if age <= 100:
        return 48
    if age <= 180:
        return 34
    if age <= 300:
        return 22
    if age <= 500:
        return 10
    return 0


def normalise_history_item(item: object, category: str) -> dict[str, Any] | None:
    if not isinstance(item, dict) or not item.get("text"):
        return None

    return {
        "year": str(item.get("year", "")),
        "text": str(item.get("text", "")),
        "links": item.get("links", []) if isinstance(item.get("links"), list) else [],
        "category": category,
    }


def history_item_search_text(item: dict[str, Any]) -> str:
    link_titles = " ".join(
        str(link.get("title") or "")
        for link in item.get("links", [])
        if isinstance(link, dict)
    )
    return f"{item.get('text', '')} {link_titles}".strip()


def history_is_sport_event(item: dict[str, Any]) -> bool:
    search_text = history_item_search_text(item)
    strong_score = history_keyword_score(search_text, HISTORY_SPORT_STRONG_KEYWORDS, 1)
    weak_score = history_keyword_score(search_text, HISTORY_SPORT_WEAK_KEYWORDS, 1)
    military_score = history_keyword_score(search_text, HISTORY_MILITARY_KEYWORDS, 1)
    if military_score > 0 and strong_score == 0:
        return False
    return strong_score > 0 or weak_score > 0


def ranked_history_items(items: list[dict[str, Any]], category: str) -> list[dict[str, Any]]:
    scored: list[tuple[int, int, dict[str, Any]]] = []

    for item in items:
        text = history_item_search_text(item)
        year = history_year_value(item.get("year"))
        score = history_recency_score(year)

        if category == "sport":
            score += history_keyword_score(text, HISTORY_SPORT_KEYWORDS, 24)
        elif category == "born":
            score += history_keyword_score(text, HISTORY_FAMOUS_BIRTH_KEYWORDS, 18)
        else:
            score += history_keyword_score(text, HISTORY_INTEREST_KEYWORDS, 12)

        scored.append((score, year if year is not None else -9999, item))

    scored.sort(key=lambda candidate: (candidate[0], candidate[1]), reverse=True)
    return [item for _, _, item in scored]


def fetch_history_events(month: int, day: int, limit: int) -> list[dict[str, Any]]:
    payload = fetch_json_url(f"https://history.muffinlabs.com/date/{month}/{day}")
    data = payload.get("data", {})
    events = data.get("Events", []) if isinstance(data, dict) else []
    births = data.get("Births", []) if isinstance(data, dict) else []
    if not isinstance(events, list):
        return []

    normalised_events = [
        normalised
        for item in events
        if (normalised := normalise_history_item(item, "history")) is not None
    ]
    sport_events = [
        {**item, "category": "sport"}
        for item in normalised_events
        if history_is_sport_event(item)
    ]
    history_events = [
        item
        for item in normalised_events
        if not history_is_sport_event(item)
    ]
    birth_events = [
        normalised
        for item in births
        if (normalised := normalise_history_item(item, "born")) is not None
    ] if isinstance(births, list) else []
    famous_birth_events = [
        item
        for item in birth_events
        if history_keyword_score(str(item.get("text", "")), HISTORY_FAMOUS_BIRTH_KEYWORDS, 1) > 0
    ] or birth_events

    selected: list[dict[str, Any]] = []
    selected.extend(ranked_history_items(history_events, "history")[: max(2, limit - 3)])
    selected.extend(ranked_history_items(sport_events, "sport")[:1])
    selected.extend(ranked_history_items(famous_birth_events, "born")[:2])

    if len(selected) < limit:
        selected_keys = {
            (item.get("category"), item.get("year"), item.get("text")) for item in selected
        }
        fallback_pool = ranked_history_items(
            [*history_events, *sport_events, *birth_events],
            "history",
        )
        for item in fallback_pool:
            key = (item.get("category"), item.get("year"), item.get("text"))
            if key in selected_keys:
                continue
            selected.append(item)
            selected_keys.add(key)
            if len(selected) >= limit:
                break

    return selected[:limit]


def load_history_location_context(location: str, lang: str) -> dict[str, Any]:
    wiki = fetch_wikipedia_summary(location, lang)
    content_urls = wiki.get("content_urls", {})
    desktop_urls = content_urls.get("desktop", {}) if isinstance(content_urls, dict) else {}
    thumbnail = wiki.get("thumbnail", {})
    article_url = desktop_urls.get("page")
    plain_extract = ""
    wikidata_entity = None

    try:
        plain_extract = fetch_wikipedia_plain_extract(str(wiki.get("title") or location), lang)
    except Exception as error:
        safe_log(f"History Wikipedia extract fetch failed: {error}")

    qid = str(wiki.get("wikibase_item", ""))
    if qid:
        try:
            wikidata_entity = fetch_wikidata_entity(qid)
        except Exception as error:
            safe_log(f"History Wikidata fetch failed: {error}")

    title = str(wiki.get("title") or location)
    return {
        "wiki": wiki,
        "title": title,
        "description": wiki.get("description"),
        "articleUrl": article_url,
        "thumbnailUrl": thumbnail.get("source") if isinstance(thumbnail, dict) else None,
        "plainExtract": plain_extract,
        "wikidataEntity": wikidata_entity,
        "locationImages": fetch_wikipedia_images(wiki, lang, article_url),
    }


def build_history_rotation_facts_from_context(
    location_context: dict[str, Any],
    *,
    rotation_key: str,
    lang: str,
    limit_facts: int,
    recent_texts: list[str],
) -> list[dict[str, Any]]:
    title = str(location_context.get("title") or "")
    article_url = location_context.get("articleUrl")
    candidate_limit = max(6, limit_facts * 4)
    candidate_facts = build_location_facts(
        location_context.get("wiki", {}),
        str(location_context.get("plainExtract") or ""),
        max(10, candidate_limit),
        article_url if isinstance(article_url, str) else None,
        location_context.get("wikidataEntity"),
        lang,
    )
    rotated_facts = reviewed_location_facts(
        rotation_key,
        title,
        candidate_facts,
        limit=limit_facts,
        recent_texts=recent_texts,
    )
    return fetch_missing_fact_images(
        attach_fact_images(
            rotated_facts,
            location_context.get("locationImages", []),
            title,
        ),
        title,
    )


def process_history_fact_prewarm_job(job_row: sqlite3.Row) -> None:
    job = deserialize_history_fact_prewarm_job(job_row)
    job_id = job["id"]
    rotation_key = job["rotationKey"]
    attempts = job["attempts"]
    target_not_before_at = parse_utc_timestamp(job["targetNotBeforeAt"])
    if target_not_before_at is None:
        complete_history_fact_prewarm_job(
            job_id,
            status="failed",
            last_error="Prewarm job target timestamp is invalid.",
        )
        return

    with closing(connect_db()) as conn:
        if history_rotation_has_moved_on(rotation_key, target_not_before_at, conn=conn):
            complete_history_fact_prewarm_job(
                job_id,
                status="cancelled",
                last_error="Rotation advanced before prewarm could complete.",
            )
            return

    try:
        with facts_ai_overrides(
            timeout_sec=FACT_PREWARM_TIMEOUT_SEC,
            transient_retries=FACT_PREWARM_TRANSIENT_RETRIES,
            generator_budget_sec=FACT_PREWARM_GENERATOR_BUDGET_SEC,
            critic_budget_sec=FACT_PREWARM_CRITIC_BUDGET_SEC,
            web_search_timeout_sec=FACT_PREWARM_WEB_SEARCH_TIMEOUT_SEC,
        ):
            location_context = load_history_location_context(job["placeTitle"], job["lang"])
            facts = build_history_rotation_facts_from_context(
                location_context,
                rotation_key=rotation_key,
                lang=job["lang"],
                limit_facts=job["limitFacts"],
                recent_texts=recent_rotated_history_texts(rotation_key),
            )
    except Exception as error:
        if attempts < FACT_PREWARM_MAX_ATTEMPTS:
            requeue_history_fact_prewarm_job(job_id, last_error=str(error))
            HISTORY_FACT_PREWARM_EVENT.set()
        else:
            complete_history_fact_prewarm_job(
                job_id,
                status="failed",
                last_error=str(error),
            )
        return

    with closing(connect_db()) as conn:
        if history_rotation_has_moved_on(rotation_key, target_not_before_at, conn=conn):
            complete_history_fact_prewarm_job(
                job_id,
                status="cancelled",
                last_error="Rotation advanced before prewarmed facts were stored.",
            )
            return

    complete_history_fact_prewarm_job(
        job_id,
        status="ready",
        facts=facts,
    )


def history_fact_prewarm_worker_loop() -> None:
    safe_log("History fact prewarm worker started")
    while True:
        try:
            job_row = claim_history_fact_prewarm_job()
            if job_row is None:
                HISTORY_FACT_PREWARM_EVENT.wait(FACT_PREWARM_POLL_SEC)
                HISTORY_FACT_PREWARM_EVENT.clear()
                continue
            process_history_fact_prewarm_job(job_row)
        except Exception as error:
            safe_log(f"History fact prewarm worker error: {error}")
            time.sleep(5)


def start_history_fact_prewarm_worker() -> None:
    if not FACT_PREWARM_ENABLED:
        safe_log("History fact prewarm worker disabled")
        return
    thread = threading.Thread(target=history_fact_prewarm_worker_loop, daemon=True)
    thread.start()


def maybe_enqueue_history_fact_prewarm_from_payload(
    payload: dict[str, Any],
    *,
    limit_facts: int,
) -> bool:
    if not history_payload_is_cacheable(payload) or limit_facts <= 0:
        return False
    location_payload = payload.get("location")
    request_payload = payload.get("request")
    meta_payload = payload.get("meta")
    if not isinstance(location_payload, dict) or not isinstance(request_payload, dict) or not isinstance(meta_payload, dict):
        return False
    title = str(location_payload.get("title") or request_payload.get("location") or "").strip()
    lang = str(request_payload.get("lang") or "en")
    rotation_created_at = parse_utc_timestamp(str(meta_payload.get("rotationCreatedAt") or ""))
    if not title or rotation_created_at is None:
        return False
    return schedule_history_fact_prewarm(
        rotation_key=history_fact_rotation_key(title, lang),
        location_query=title,
        place_title=title,
        lang=lang,
        limit_facts=limit_facts,
        source_rotation_created_at=rotation_created_at,
    )


def history_payload(
    location: str,
    date_value: str,
    lang: str,
    limit_facts: int,
    limit_events: int,
) -> tuple[dict[str, Any], int]:
    location = normalise_history_location(location)
    parsed_date = parse_history_date(date_value)
    if not location:
        return {"error": "Location is required."}, HTTPStatus.BAD_REQUEST
    if parsed_date is None:
        return {"error": "Date must be a valid YYYY-MM-DD date."}, HTTPStatus.BAD_REQUEST

    iso_date, month, day = parsed_date
    cache_key = f"{lang}:{location.lower()}:{iso_date}:{limit_facts}:{limit_events}"
    cached = history_cache_get(cache_key)
    if cached is not None:
        maybe_enqueue_history_fact_prewarm_from_payload(cached, limit_facts=limit_facts)
        return cached, HTTPStatus.OK

    warnings: list[dict[str, str]] = []
    location_payload: dict[str, Any] | None = None
    global_events: list[dict[str, Any]] = []
    cache_rotation_created_at: datetime | None = None

    with ThreadPoolExecutor(max_workers=2) as executor:
        wiki_future = executor.submit(load_history_location_context, location, lang)
        events_future = executor.submit(fetch_history_events, month, day, limit_events)

        try:
            location_context = wiki_future.result()
            title = str(location_context.get("title") or location)
            rotation_key = history_fact_rotation_key(title, lang)
            rotated_record = current_rotated_history_facts_record(rotation_key)
            if rotated_record is None:
                promoted = promote_ready_history_fact_prewarm(rotation_key)
                if promoted is not None:
                    rotated_facts, cache_rotation_created_at = promoted
                else:
                    rotated_facts = build_history_rotation_facts_from_context(
                        location_context,
                        rotation_key=rotation_key,
                        lang=lang,
                        limit_facts=limit_facts,
                        recent_texts=recent_rotated_history_texts(rotation_key),
                    )
                    created_at = utc_now()
                    store_rotated_history_facts(rotation_key, rotated_facts, created_at=created_at)
                    cache_rotation_created_at = parse_utc_timestamp(created_at)
            else:
                rotated_facts, cache_rotation_created_at = rotated_record
                if cache_rotation_created_at is not None:
                    schedule_history_fact_prewarm(
                        rotation_key=rotation_key,
                        location_query=title,
                        place_title=title,
                        lang=lang,
                        limit_facts=limit_facts,
                        source_rotation_created_at=cache_rotation_created_at,
                    )
            location_payload = {
                "title": title,
                "description": location_context.get("description"),
                "profile": wikidata_profile(
                    location_context.get("wikidataEntity"),
                    lang,
                    title,
                ),
                "facts": [public_history_fact(fact) for fact in rotated_facts[:limit_facts]],
                "articleUrl": location_context.get("articleUrl"),
                "thumbnailUrl": location_context.get("thumbnailUrl"),
                "images": location_context.get("locationImages", []),
            }
        except LookupError:
            return {"error": f"No location facts found for {location}."}, HTTPStatus.NOT_FOUND
        except Exception as error:
            safe_log(f"History Wikipedia fetch failed: {error}")
            warnings.append(
                {
                    "source": "wikipedia",
                    "code": "upstream_unavailable",
                    "detail": "Location facts are currently unavailable.",
                }
            )

        try:
            global_events = events_future.result()
        except Exception as error:
            safe_log(f"History events fetch failed: {error}")
            warnings.append(
                {
                    "source": "history-muffinlabs",
                    "code": "upstream_unavailable",
                    "detail": "This day in history is currently unavailable.",
                }
            )

    if location_payload is None and not global_events:
        return {"error": "History sources are currently unavailable."}, HTTPStatus.SERVICE_UNAVAILABLE

    payload = {
        "request": {"location": location, "date": iso_date, "lang": lang},
        "location": location_payload,
        "globalEvents": global_events,
        "partial": bool(warnings),
        "warnings": warnings,
        "meta": {
            "cached": False,
            "eventsLanguage": "en",
            "generatedAt": utc_now(),
            "rotationCreatedAt": (
                cache_rotation_created_at.replace(microsecond=0).astimezone(timezone.utc).isoformat()
                if cache_rotation_created_at is not None
                else None
            ),
            "rotationExpiresAt": history_rotation_expiry_isoformat(cache_rotation_created_at),
        },
    }
    if history_payload_is_cacheable(payload):
        history_cache_set_with_expiry(
            cache_key,
            payload,
            expires_at=history_cache_expiry_timestamp(
                rotation_created_at=cache_rotation_created_at,
            ),
        )
    return payload, HTTPStatus.OK


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


class FultonsHandler(SimpleHTTPRequestHandler):
    server_version = "FultonsQuiz/0.1"

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

        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")

    def send_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(self)")
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
        return self.client_address[0] if self.client_address else "unknown"

    def is_loopback_request(self) -> bool:
        return is_loopback_ip(self.client_ip())

    def request_origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        if origin in CORS_ALLOWED_ORIGINS:
            return True

        host = self.headers.get("Host", "")
        parsed_origin = urlparse(origin)
        if parsed_origin.netloc == host:
            return True

        if not COOKIE_SECURE and parsed_origin.hostname in {"127.0.0.1", "localhost"}:
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

    def send_json(
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
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length == 0:
            return {}
        if content_length > 1_000_000:
            raise ValueError("Request body is too large.")

        raw_body = self.rfile.read(content_length)
        if not raw_body:
            return {}

        decoded = json.loads(raw_body.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("Expected a JSON object.")
        return decoded

    def handle_api(self, method: str, path: str, query: str = "") -> None:
        try:
            if method in {"POST", "PATCH", "DELETE"} and not self.request_origin_allowed():
                self.send_error_json(HTTPStatus.FORBIDDEN, "Origin is not allowed.")
                return
            self.route_api(method, path.rstrip("/") or "/", query)
        except json.JSONDecodeError:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Invalid JSON body.")
        except ValueError as error:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as error:
            safe_log(f"API error: {error}")
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "Server error.")

    def route_api(self, method: str, path: str, query: str = "") -> None:
        params = parse_qs(query)

        if path == "/api/health" and method == "GET":
            storage = runtime_storage_health()
            status = HTTPStatus.OK if storage["ok"] else HTTPStatus.SERVICE_UNAVAILABLE
            self.send_json(status, health_payload(storage))
            return

        if path == "/api/local/ops-monitor" and method == "GET":
            if not LOCAL_OPS_ENABLED:
                self.send_error_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "Local ops dashboard is disabled.",
                )
                return
            if not self.is_loopback_request():
                self.send_error_json(
                    HTTPStatus.FORBIDDEN,
                    "Local ops dashboard is available only from localhost.",
                )
                return
            force = str(params.get("force", ["0"])[0]).strip().lower() in {"1", "true", "yes"}
            self.send_json(HTTPStatus.OK, ops_monitor.collect_dashboard_snapshot(force=force))
            return

        if path == "/api/local/ops-config" and method == "GET":
            if not LOCAL_OPS_ENABLED:
                self.send_error_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "Local ops dashboard is disabled.",
                )
                return
            if not self.is_loopback_request():
                self.send_error_json(
                    HTTPStatus.FORBIDDEN,
                    "Local ops dashboard is available only from localhost.",
                )
                return
            self.send_json(HTTPStatus.OK, local_ops_settings.monitor_settings_response())
            return

        if path == "/api/local/ops-config" and method == "POST":
            if not LOCAL_OPS_ENABLED:
                self.send_error_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "Local ops dashboard is disabled.",
                )
                return
            if not self.is_loopback_request():
                self.send_error_json(
                    HTTPStatus.FORBIDDEN,
                    "Local ops dashboard is available only from localhost.",
                )
                return
            payload = self.read_json()
            saved = local_ops_settings.save_monitor_settings(payload)
            self.send_json(
                HTTPStatus.OK,
                {
                    "config": saved,
                    "settingsPath": str(local_ops_settings.SETTINGS_PATH),
                },
            )
            return

        if path == "/api/local/ops-action" and method == "POST":
            if not LOCAL_OPS_ENABLED:
                self.send_error_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "Local ops dashboard is disabled.",
                )
                return
            if not self.is_loopback_request():
                self.send_error_json(
                    HTTPStatus.FORBIDDEN,
                    "Local ops dashboard is available only from localhost.",
                )
                return
            payload = self.read_json()
            action = str(payload.get("action") or "").strip()
            params_payload = payload.get("params")
            params = params_payload if isinstance(params_payload, dict) else None
            try:
                if ops_monitor.is_async_local_action(action):
                    self.send_json(
                        HTTPStatus.ACCEPTED,
                        ops_monitor.start_local_action_job(action, params=params),
                    )
                else:
                    self.send_json(HTTPStatus.OK, ops_monitor.run_local_action(action, params=params))
            except ValueError as error:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
            except RuntimeError as error:
                self.send_error_json(HTTPStatus.BAD_GATEWAY, str(error))
            return

        if path == "/api/local/ops-action-status" and method == "GET":
            if not LOCAL_OPS_ENABLED:
                self.send_error_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "Local ops dashboard is disabled.",
                )
                return
            if not self.is_loopback_request():
                self.send_error_json(
                    HTTPStatus.FORBIDDEN,
                    "Local ops dashboard is available only from localhost.",
                )
                return
            job_id = str(params.get("jobId", [""])[0] or "").strip()
            try:
                self.send_json(HTTPStatus.OK, ops_monitor.get_local_action_job(job_id))
            except ValueError as error:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
            except LookupError as error:
                self.send_error_json(HTTPStatus.NOT_FOUND, str(error))
            return

        if path == "/api/news/stream" and method == "GET":
            with connect_db() as conn:
                token = get_cookie_value(self.headers, SESSION_COOKIE)
                user = current_user(conn, token)
                if user is None:
                    self.send_error_json(HTTPStatus.UNAUTHORIZED, "Login required.")
                    return
            self.handle_news_stream()
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
            with DAILY_QUIZ_OPERATION_LOCK:
                with connect_db() as conn:
                    result = daily_quiz.generate_daily_quiz(
                        conn,
                        quiz_date=quiz_date,
                        force=bool(payload.get("force", False)),
                        config=DAILY_QUIZ_CONFIG,
                        log=safe_log,
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
                        result = daily_quiz.quiz_payload(conn, quiz_date)
            status = (
                HTTPStatus.OK
                if result.get("status") == "published"
                else HTTPStatus.SERVICE_UNAVAILABLE
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
                    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
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
                self.send_json(HTTPStatus.OK, {"user": user_payload(user)})
                return

            if path == "/api/news/add" and method == "POST":
                self.handle_news_add(conn)
                return

            if user is None:
                self.send_error_json(HTTPStatus.UNAUTHORIZED, "Login required.")
                return

            if path == "/api/me" and method == "PATCH":
                self.handle_update_me(conn, user)
                return

            if path == "/api/wordle/today" and method == "GET":
                game = ensure_daily_game(conn)
                self.send_json(
                    HTTPStatus.OK,
                    serialize_wordle_state(conn, user["id"], game),
                )
                return

            if path == "/api/wordle/definition" and method == "GET":
                game = ensure_daily_game(conn)
                assignment = ensure_wordle_assignment(conn, user["id"], game)
                result = get_or_create_wordle_result(conn, user["id"], game["id"])
                if result["status"] == "in_progress":
                    self.send_error_json(
                        HTTPStatus.CONFLICT,
                        "Finish today's Wordle before requesting its definition.",
                    )
                    return
                self.send_json(HTTPStatus.OK, word_definition(assignment["secret_word"]))
                return

            if path == "/api/daily-quiz" and method == "GET":
                quiz_date = str(params.get("date", [today_game_date()])[0]).strip()
                try:
                    self.send_json(HTTPStatus.OK, daily_quiz.quiz_payload(conn, quiz_date))
                except LookupError:
                    self.send_error_json(HTTPStatus.NOT_FOUND, "No published quiz exists for that date.")
                return

            if path == "/api/daily-quiz/result" and method == "POST":
                payload = self.read_json()
                game_date = str(payload.get("date", "")).strip()
                category = str(payload.get("category", "")).strip()
                raw_answers = payload.get("answers", [])
                answers = raw_answers if isinstance(raw_answers, list) else []
                if not all(isinstance(answer, str) for answer in answers):
                    self.send_error_json(HTTPStatus.BAD_REQUEST, "Quiz answers must be text.")
                    return
                result_payload, status = save_daily_quiz_result(
                    conn,
                    user["id"],
                    game_date,
                    category,
                    answers,
                )
                self.send_json(status, result_payload)
                return

            if path == "/api/leaderboard" and method == "GET":
                self.send_json(HTTPStatus.OK, leaderboard_payload(conn))
                return

            if path in {"/api/history", "/api/facts"} and method == "GET":
                location = str(params.get("location", [""])[0]).strip()
                date_value = str(params.get("date", [today_game_date()])[0]).strip()
                lang = normalise_history_lang(params.get("lang", ["en"])[0])
                limit_facts = self.query_int(params, "limitFacts", 2, 2, 2)
                limit_events = self.query_int(params, "limitEvents", 5, 1, 10)
                payload, status = history_payload(
                    location,
                    date_value,
                    lang,
                    limit_facts,
                    limit_events,
                )
                self.send_json(status, payload)
                return

            if path == "/api/news" and method == "GET":
                limit = self.query_int(params, "limit", NEWS_LIMIT_DEFAULT, 1, NEWS_LIMIT_MAX)
                category = params.get("category", ["all"])[0]
                if category not in {"all", "breaking", "news", "live-scores"}:
                    category = "all"
                self.send_json(
                    HTTPStatus.OK,
                    {"items": list_news_items(conn, limit, category), "category": category},
                )
                return

            validate_match = re.fullmatch(r"/api/wordle/validate/([A-Za-z]+)", path)
            if validate_match is not None and method == "GET":
                guess = validate_match.group(1).lower()
                self.send_json(HTTPStatus.OK, {"valid": valid_guess(guess)})
                return

            if path == "/api/wordle/guess" and method == "POST":
                self.handle_wordle_guess(conn, user)
                return

            if path == "/api/admin/daily-quiz-status" and method == "GET":
                if user["role"] != "admin":
                    self.send_error_json(HTTPStatus.FORBIDDEN, "Admin access required.")
                    return
                quiz_date = str(params.get("date", [today_game_date()])[0]).strip()
                self.send_json(HTTPStatus.OK, daily_quiz.quiz_status(conn, quiz_date))
                return

            if path == "/api/admin/question-attempts" and method == "GET":
                if user["role"] != "admin":
                    self.send_error_json(HTTPStatus.FORBIDDEN, "Admin access required.")
                    return
                quiz_date = str(params.get("date", [today_game_date()])[0]).strip()
                self.send_json(HTTPStatus.OK, daily_quiz.question_attempts(conn, quiz_date))
                return

            if path == "/api/admin/ops-monitor" and method == "GET":
                if user["role"] != "admin":
                    self.send_error_json(HTTPStatus.FORBIDDEN, "Admin access required.")
                    return
                force = str(params.get("force", ["0"])[0]).strip().lower() in {"1", "true", "yes"}
                self.send_json(HTTPStatus.OK, ops_monitor.collect_dashboard_snapshot(force=force))
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
                        result = daily_quiz.quiz_payload(conn, quiz_date)
                self.send_json(HTTPStatus.OK, result)
                return

            if path == "/api/admin/publish-quiz" and method == "POST":
                if user["role"] != "admin":
                    self.send_error_json(HTTPStatus.FORBIDDEN, "Admin access required.")
                    return
                payload = self.read_json()
                quiz_date = str(payload.get("date") or today_game_date())
                with DAILY_QUIZ_OPERATION_LOCK:
                    self.send_json(HTTPStatus.OK, daily_quiz.publish_quiz(conn, quiz_date))
                return

            if path.startswith("/api/admin/"):
                if not user_can_manage_players(user):
                    self.send_error_json(HTTPStatus.FORBIDDEN, "Player management access required.")
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
        client_ip = self.client_ip()

        if is_login_locked(username, client_ip):
            self.send_error_json(
                HTTPStatus.TOO_MANY_REQUESTS,
                "Too many login attempts. Try again later.",
            )
            return

        user = conn.execute(
            "SELECT * FROM users WHERE LOWER(username) = LOWER(?)",
            (username,),
        ).fetchone()
        if user is None or not verify_password(password, user["password_hash"]):
            record_login_failure(username, client_ip)
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Invalid username or password.")
            return

        clear_login_failures(username, client_ip)
        token = create_session(conn, user["id"])
        self.send_json(
            HTTPStatus.OK,
            {"user": user_payload(user)},
            {"Set-Cookie": session_header(token)},
        )

    def handle_update_me(self, conn: sqlite3.Connection, user: sqlite3.Row) -> None:
        payload = self.read_json()
        new_username = payload.get("username")
        current_password = str(payload.get("currentPassword", ""))
        new_password = payload.get("newPassword")
        now = utc_now()

        if new_username is not None:
            normalized_username = str(new_username).strip()
            username_error = validate_username(normalized_username)
            if username_error is not None:
                self.send_error_json(HTTPStatus.BAD_REQUEST, username_error)
                return

            if normalized_username.lower() != user["username"].lower():
                try:
                    conn.execute(
                        "UPDATE users SET username = ?, updated_at = ? WHERE id = ?",
                        (normalized_username, now, user["id"]),
                    )
                except sqlite3.IntegrityError:
                    self.send_error_json(HTTPStatus.CONFLICT, "Username is already taken.")
                    return

        if new_password is not None and str(new_password):
            password = str(new_password)
            password_error = validate_password(password)
            if password_error is not None:
                self.send_error_json(HTTPStatus.BAD_REQUEST, password_error)
                return

            if not verify_password(current_password, user["password_hash"]):
                self.send_error_json(HTTPStatus.UNAUTHORIZED, "Current password is incorrect.")
                return

            conn.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (hash_password(password), now, user["id"]),
            )

        updated_user = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        self.send_json(HTTPStatus.OK, {"user": user_payload(updated_user)})

    def handle_wordle_guess(self, conn: sqlite3.Connection, user: sqlite3.Row) -> None:
        payload = self.read_json()
        guess = str(payload.get("guess", "")).strip().lower()
        words = load_word_list()

        if not valid_guess(guess, words):
            self.send_error_json(
                HTTPStatus.BAD_REQUEST,
                "Enter a valid five-letter word from the game list.",
            )
            return

        game = ensure_daily_game(conn)
        assignment = ensure_wordle_assignment(conn, user["id"], game)
        result = get_or_create_wordle_result(conn, user["id"], game["id"])

        if result["status"] != "in_progress":
            self.send_json(HTTPStatus.OK, serialize_wordle_state(conn, user["id"], game))
            return

        attempt_number = result["attempts_used"] + 1
        if attempt_number > MAX_ATTEMPTS:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "No attempts remain.")
            return

        feedback = serialize_feedback(compute_feedback(assignment["secret_word"], guess))
        won = all(tile["color"] == "green" for tile in feedback)
        status = "won" if won else "lost" if attempt_number >= MAX_ATTEMPTS else "in_progress"
        completed_at = utc_now() if status != "in_progress" else None
        score = wordle_score(status, attempt_number, assignment["difficulty"])
        now = utc_now()

        conn.execute(
            """
            INSERT INTO wordle_guesses
                (result_id, attempt_number, guess, feedback_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (result["id"], attempt_number, guess, json.dumps(feedback), now),
        )
        conn.execute(
            """
            UPDATE wordle_results
            SET status = ?, attempts_used = ?, score = ?, completed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, attempt_number, score, completed_at, now, result["id"]),
        )

        self.send_json(HTTPStatus.OK, serialize_wordle_state(conn, user["id"], game))

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
                conn.execute(
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


def run() -> None:
    assert_runtime_storage_ready("before database initialization")
    initialize_database()
    assert_runtime_storage_ready("after database initialization")
    start_news_monitor()
    start_daily_quiz_scheduler()
    start_history_fact_prewarm_worker()
    host = os.environ.get("FULTONS_HOST", "127.0.0.1")
    port = int(os.environ.get("FULTONS_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), FultonsHandler)
    safe_log(f"Fulton's Quiz server running at http://{host}:{port}")
    safe_log(f"SQLite database: {DB_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    run()
