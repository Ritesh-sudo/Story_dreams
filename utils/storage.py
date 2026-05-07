"""
SQLite-backed story history store.

Stories are written once (at generation time) and read many times.
The DB file lives next to this module: utils/stories.db
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH = Path(__file__).parent / "stories.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stories (
            id            TEXT PRIMARY KEY,
            timestamp     TEXT NOT NULL,
            prompt        TEXT NOT NULL,
            age           INTEGER NOT NULL DEFAULT 7,
            category      TEXT NOT NULL DEFAULT '',
            title         TEXT NOT NULL DEFAULT '',
            story         TEXT NOT NULL,
            narrator_story TEXT NOT NULL DEFAULT '',
            overall_score REAL NOT NULL DEFAULT 0,
            judgment_json TEXT NOT NULL DEFAULT '{}',
            image_url     TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.commit()


def save_story(
    *,
    prompt: str,
    age: int,
    category: str,
    title: str,
    story: str,
    narrator_story: str,
    judgment: dict,
    image_url: str | None,
) -> str:
    """Persists a completed story and returns its UUID."""
    story_id = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()
    overall = judgment.get("overall_score", 0.0) if judgment else 0.0

    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO stories
              (id, timestamp, prompt, age, category, title,
               story, narrator_story, overall_score, judgment_json, image_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                story_id, ts, prompt, age, category, title,
                story, narrator_story or story,
                overall, json.dumps(judgment or {}),
                image_url or "",
            ),
        )
    return story_id


def get_all_stories(limit: int = 50) -> list[dict]:
    """Returns recent stories, newest first, without full text (for list views)."""
    with _connect() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT id, timestamp, prompt, age, category, title, overall_score, image_url
            FROM stories
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_story(story_id: str) -> dict | None:
    """Returns the full story record or None if not found."""
    with _connect() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT * FROM stories WHERE id = ?", (story_id,)
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["judgment"] = json.loads(d.pop("judgment_json", "{}"))
    return d
