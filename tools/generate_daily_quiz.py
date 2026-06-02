from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import daily_quiz
import server


def parse_args() -> argparse.Namespace:
    tomorrow = (datetime.now().astimezone().date() + timedelta(days=1)).isoformat()
    parser = argparse.ArgumentParser(
        description="Generate and review one six-question daily quiz set.",
    )
    parser.add_argument("--date", default=tomorrow, help="Quiz date in YYYY-MM-DD format.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an already-published quiz for the selected date.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = daily_quiz.QuizConfig.from_env()
    with server.connect_db() as conn:
        daily_quiz.initialize_database(conn)
        result = daily_quiz.generate_daily_quiz(
            conn,
            quiz_date=args.date,
            force=args.force,
            config=config,
            log=lambda message: print(f"[daily-quiz] {message}", flush=True),
        )
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "published" else 1


if __name__ == "__main__":
    raise SystemExit(main())
