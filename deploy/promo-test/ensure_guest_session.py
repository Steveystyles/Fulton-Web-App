from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


DB_PATH = Path(os.environ.get("FULTONS_DB_PATH", "/app/data/fultons.db"))
TOKEN_PATH = Path(
    os.environ.get("FULTONS_PROMO_GUEST_TOKEN_PATH", "/app/data/promo_guest_session")
)
USERNAME = "PromoGuest"


def utc_timestamp(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def main() -> None:
    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(48)

    with sqlite3.connect(DB_PATH) as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE LOWER(username) = LOWER(?)",
            (USERNAME,),
        ).fetchone()
        if user is None:
            cursor = conn.execute(
                """
                INSERT INTO users (username, password_hash, role, created_at, updated_at)
                VALUES (?, ?, 'user', ?, ?)
                """,
                (USERNAME, "disabled", utc_timestamp(now), utc_timestamp(now)),
            )
            user_id = int(cursor.lastrowid)
        else:
            user_id = int(user[0])

        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute(
            """
            INSERT INTO sessions (token, user_id, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                token,
                user_id,
                utc_timestamp(now),
                utc_timestamp(now + timedelta(days=90)),
            ),
        )

    TOKEN_PATH.write_text(token, encoding="ascii")
    TOKEN_PATH.chmod(0o600)
    print(f"Guest review session is ready for user {USERNAME}.")


if __name__ == "__main__":
    main()
