"""Durable outbox: SQLite in WAL mode (docs/05 "Outbox and upload"). Events are never dropped, except
the oldest `after_hours_motion` rows when the database grows beyond its size cap."""

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at REAL NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  next_try_at REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS outbox_next_try ON outbox (next_try_at, created_at);
CREATE TABLE IF NOT EXISTS commands_done (id TEXT PRIMARY KEY, done_at REAL NOT NULL);
"""
MAX_BYTES = 500 * 1024 * 1024


class Outbox:
    def __init__(self, path: Path | str, max_bytes: int = MAX_BYTES) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self.lock = threading.Lock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)

    def journal_mode(self) -> str:
        return str(self.db.execute("PRAGMA journal_mode").fetchone()[0])

    # ---------- events ----------
    def put(self, event: dict[str, Any], kind: str = "event", now: float | None = None) -> None:
        """Insert or replace by event id: a later version of the same event (e.g. an unattended period
        that was announced open and is now closed) replaces the pending one."""
        now = time.time() if now is None else now
        with self.lock:
            self.db.execute(
                "INSERT INTO outbox (id, kind, payload, created_at, attempts, next_try_at)"
                " VALUES (?, ?, ?, ?, 0, 0)"
                " ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, next_try_at = 0",
                (event["id"], kind, json.dumps(event, separators=(",", ":")), now),
            )
        self.enforce_cap()

    def due(self, now: float, limit: int = 500, kind: str = "event") -> list[tuple[str, dict[str, Any]]]:
        with self.lock:
            rows = self.db.execute(
                "SELECT id, payload FROM outbox WHERE kind = ? AND next_try_at <= ?"
                " ORDER BY created_at, id LIMIT ?",
                (kind, now, limit),
            ).fetchall()
        return [(r[0], json.loads(r[1])) for r in rows]

    def delete(self, ids: list[str]) -> None:
        with self.lock:
            self.db.executemany("DELETE FROM outbox WHERE id = ?", [(i,) for i in ids])

    def failed(self, ids: list[str], next_try_at: float) -> None:
        with self.lock:
            self.db.executemany(
                "UPDATE outbox SET attempts = attempts + 1, next_try_at = ? WHERE id = ?",
                [(next_try_at, i) for i in ids],
            )

    def reject(self, ids: list[str]) -> None:
        """The server refused these events as invalid (422): keep them aside for support, stop retrying."""
        with self.lock:
            self.db.executemany("UPDATE outbox SET kind = 'rejected' WHERE id = ?", [(i,) for i in ids])

    def depth(self) -> int:
        with self.lock:
            return int(self.db.execute("SELECT count(*) FROM outbox WHERE kind = 'event'").fetchone()[0])

    def size_bytes(self) -> int:
        with self.lock:
            pages = self.db.execute("PRAGMA page_count").fetchone()[0]
            size = self.db.execute("PRAGMA page_size").fetchone()[0]
        return int(pages) * int(size)

    def enforce_cap(self) -> int:
        """Over the cap: drop the oldest after_hours_motion events first (docs/05), never other events."""
        dropped = 0
        while self.size_bytes() > self.max_bytes:
            with self.lock:
                row = self.db.execute(
                    'SELECT id FROM outbox WHERE payload LIKE \'%"type":"after_hours_motion"%\''
                    " ORDER BY created_at LIMIT 200"
                ).fetchall()
                if not row:
                    break
                self.db.executemany("DELETE FROM outbox WHERE id = ?", row)
                self.db.execute("VACUUM")
            dropped += len(row)
        if dropped:
            log.warning(
                "outbox over %d bytes: dropped %d oldest after_hours_motion events", self.max_bytes, dropped
            )
        return dropped

    # ---------- commands (idempotency) ----------
    def command_done(self, command_id: str) -> bool:
        with self.lock:
            return (
                self.db.execute("SELECT 1 FROM commands_done WHERE id = ?", (command_id,)).fetchone()
                is not None
            )

    def mark_command_done(self, command_id: str, now: float | None = None) -> None:
        with self.lock:
            self.db.execute(
                "INSERT OR IGNORE INTO commands_done (id, done_at) VALUES (?, ?)",
                (command_id, time.time() if now is None else now),
            )
