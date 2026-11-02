"""SQLite storage: connection handling and schema migrations."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

MIGRATIONS: list[str] = [
    # 1 — snippets
    """
    CREATE TABLE snippets (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        title       TEXT    NOT NULL,
        content     TEXT    NOT NULL,
        language    TEXT    NOT NULL DEFAULT 'text',
        description TEXT    NOT NULL DEFAULT '',
        favorite    INTEGER NOT NULL DEFAULT 0,
        use_count   INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT    NOT NULL,
        updated_at  TEXT    NOT NULL,
        last_used_at TEXT
    );
    CREATE TABLE snippet_tags (
        snippet_id INTEGER NOT NULL REFERENCES snippets(id) ON DELETE CASCADE,
        tag        TEXT    NOT NULL,
        PRIMARY KEY (snippet_id, tag)
    );
    CREATE INDEX idx_snippet_tags_tag ON snippet_tags(tag);
    """,
]


def db_path() -> Path:
    env = os.environ.get("DEVTOOL_DB")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".devtool" / "devtool.sqlite3"


def _migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for i, sql in enumerate(MIGRATIONS[version:], start=version + 1):
        conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {i};\nCOMMIT;")


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or db_path()
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    _migrate(conn)
    return conn


@contextmanager
def session(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        with conn:  # commit on success, rollback on error
            yield conn
    finally:
        conn.close()
