"""Optional SQLite observation history for Moni."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Any
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
CREATE TABLE IF NOT EXISTS check_state (
    name TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    ok INTEGER NOT NULL CHECK (ok IN (0, 1)),
    changed_at REAL NOT NULL,
    last_checked_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS notification_deliveries (
    event_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    previous_ok INTEGER,
    current_ok INTEGER NOT NULL CHECK (current_ok IN (0, 1)),
    changed_at REAL NOT NULL,
    delivered INTEGER NOT NULL CHECK (delivered IN (0, 1)),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_at REAL
);
"""


@dataclass(frozen=True)
class StateTransition:
    name: str
    type: str
    previous_ok: bool | None
    current_ok: bool
    changed_at: float

    @property
    def changed(self) -> bool:
        return self.previous_ok is not None and self.previous_ok != self.current_ok


def record_results(
    path: Path, results: list["CheckResult"], checked_at: float | None = None
) -> list[StateTransition]:
    """Append observations and update last-known state, returning transitions."""
    timestamp = time.time() if checked_at is None else checked_at
    transitions: list[StateTransition] = []
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        database = sqlite3.connect(path)
        try:
            database.executescript(SCHEMA)
            previous_states = {
                result.name: database.execute(
                    "SELECT ok FROM check_state WHERE name = ?", (result.name,)
                ).fetchone()
                for result in results
            }
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
            for result in results:
                previous = previous_states[result.name]
                previous_ok = None if previous is None else bool(previous[0])
                changed_at = timestamp if previous is None or previous_ok != result.ok else database.execute(
                    "SELECT changed_at FROM check_state WHERE name = ?", (result.name,)
                ).fetchone()[0]
                database.execute(
                    """
                    INSERT INTO check_state(name, type, ok, changed_at, last_checked_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        type = excluded.type,
                        ok = excluded.ok,
                        changed_at = excluded.changed_at,
                        last_checked_at = excluded.last_checked_at
                    """,
                    (result.name, result.type, int(result.ok), changed_at, timestamp),
                )
                transitions.append(
                    StateTransition(result.name, result.type, previous_ok, result.ok, changed_at)
                )
            database.commit()
        finally:
            database.close()
    except sqlite3.Error as exc:
        raise RuntimeError(f"cannot write history {path}: {exc}") from exc
    return transitions


def recent_observations(path: Path, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent observations in newest-first order without mutating the DB."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    try:
        database = sqlite3.connect(path)
        try:
            rows = database.execute(
                """
                SELECT checked_at, name, type, ok, latency_ms, status, error
                FROM observations
                ORDER BY checked_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        finally:
            database.close()
    except sqlite3.Error as exc:
        raise RuntimeError(f"cannot read history {path}: {exc}") from exc
    return [
        {
            "checked_at": row[0],
            "name": row[1],
            "type": row[2],
            "ok": bool(row[3]),
            "latency_ms": row[4],
            "status": row[5],
            "error": row[6],
        }
        for row in rows
    ]


def summarize_observations(path: Path) -> list[dict[str, Any]]:
    """Return all-time per-check success, failure, and latency summaries."""
    try:
        database = sqlite3.connect(path)
        try:
            rows = database.execute(
                """
                SELECT name, type, COUNT(*), SUM(ok), AVG(latency_ms)
                FROM observations
                GROUP BY name, type
                ORDER BY name
                """
            ).fetchall()
        finally:
            database.close()
    except sqlite3.Error as exc:
        raise RuntimeError(f"cannot read history {path}: {exc}") from exc
    return [
        {
            "name": row[0],
            "type": row[1],
            "observations": row[2],
            "passed": row[3],
            "failed": row[2] - row[3],
            "success_rate": round(row[3] / row[2], 4),
            "average_latency_ms": None if row[4] is None else round(row[4], 2),
        }
        for row in rows
    ]


def _event_key(transition: "StateTransition") -> str:
    return f"{transition.name}|{transition.type}|{transition.changed_at}|{int(transition.current_ok)}"


def pending_notifications(path: Path) -> list["StateTransition"]:
    """Load changed notifications that were not delivered successfully."""
    from history import StateTransition

    try:
        database = sqlite3.connect(path)
        try:
            database.executescript(SCHEMA)
            rows = database.execute(
                """SELECT name, type, previous_ok, current_ok, changed_at
                   FROM notification_deliveries WHERE delivered = 0 ORDER BY changed_at, event_key"""
            ).fetchall()
        finally:
            database.close()
    except sqlite3.Error as exc:
        raise RuntimeError(f"cannot read notification history {path}: {exc}") from exc
    return [StateTransition(row[0], row[1], None if row[2] is None else bool(row[2]), bool(row[3]), row[4]) for row in rows]


def record_notification_delivery(
    path: Path, transitions: list["StateTransition"], delivered: bool, attempted_at: float | None = None
) -> None:
    """Record delivery outcome so failed events survive process restarts."""
    changed = [transition for transition in transitions if transition.changed]
    if not changed:
        return
    timestamp = time.time() if attempted_at is None else attempted_at
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        database = sqlite3.connect(path)
        try:
            database.executescript(SCHEMA)
            database.executemany(
                """INSERT INTO notification_deliveries
                   (event_key, name, type, previous_ok, current_ok, changed_at, delivered, attempts, last_attempt_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                   ON CONFLICT(event_key) DO UPDATE SET
                     delivered = excluded.delivered, attempts = notification_deliveries.attempts + 1,
                     last_attempt_at = excluded.last_attempt_at""",
                [
                    (_event_key(item), item.name, item.type, item.previous_ok, int(item.current_ok), item.changed_at, int(delivered), timestamp)
                    for item in changed
                ],
            )
            database.commit()
        finally:
            database.close()
    except sqlite3.Error as exc:
        raise RuntimeError(f"cannot write notification history {path}: {exc}") from exc


def prune_observations(path: Path, max_rows: int) -> int:
    """Keep the newest observation rows and return the number removed."""
    if max_rows <= 0:
        raise ValueError("max_rows must be positive")
    try:
        database = sqlite3.connect(path)
        try:
            database.executescript(SCHEMA)
            cursor = database.execute(
                "DELETE FROM observations WHERE id NOT IN "
                "(SELECT id FROM observations ORDER BY checked_at DESC, id DESC LIMIT ?)",
                (max_rows,),
            )
            database.commit()
            return cursor.rowcount
        finally:
            database.close()
    except sqlite3.Error as exc:
        raise RuntimeError(f"cannot prune history {path}: {exc}") from exc
