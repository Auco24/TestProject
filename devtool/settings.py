"""Simple JSON key/value settings stored in SQLite."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

DEFAULTS: dict[str, Any] = {
    "git_roots": [],
}


def get(conn: sqlite3.Connection, key: str) -> Any:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        default = DEFAULTS.get(key)
        return json.loads(json.dumps(default))  # copy
    return json.loads(row[0])


def set(conn: sqlite3.Connection, key: str, value: Any) -> Any:  # noqa: A001 - module-level API
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value, ensure_ascii=False)),
    )
    return value
