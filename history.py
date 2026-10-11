"""Optional SQLite observation history for Moni."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moni import CheckResult


SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY,
    checked_at REAL NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    ok INTEGER NOT NULL CHECK (ok IN (0, 1)),
    latency_ms REAL,
    status INTEGER,
    error TEXT
);
CREATE INDEX IF NOT EXISTS observations_check_time
    ON observations(name, checked_at);
"""


def record_results(path: Path, results: list["CheckResult"], checked_at: float | None = None) -> None:
    """Append one observation row per result, creating the database if needed."""
    timestamp = time.time() if checked_at is None else checked_at
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        database = sqlite3.connect(path)
        try:
            database.executescript(SCHEMA)
            database.executemany(
                """
                INSERT INTO observations
                    (checked_at, name, type, ok, latency_ms, status, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        timestamp,
                        result.name,
                        result.type,
                        int(result.ok),
                        result.latency_ms,
                        result.status,
                        result.error,
                    )
                    for result in results
                ],
            )
            database.commit()
        finally:
            database.close()
    except sqlite3.Error as exc:
        raise RuntimeError(f"cannot write history {path}: {exc}") from exc
