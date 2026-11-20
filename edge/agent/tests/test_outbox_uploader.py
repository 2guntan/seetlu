"""Outbox (SQLite WAL, upsert by id, size cap) and uploader (batches <= 500, backoff, never drop)."""

import random
from pathlib import Path
from typing import Any

import pytest

from seetlu_agent.api import ApiError
from seetlu_agent.outbox import Outbox
from seetlu_agent.uploader import BACKOFF_MAX_S, Uploader


def ev(i: int, kind: str = "entry", **extra: Any) -> dict[str, Any]:
    return {"id": f"e{i:05d}", "type": kind, "camera": "door", "started_at": "2026-11-20T10:00:00Z"} | extra


def test_wal_mode_and_upsert_by_id(tmp_path: Path) -> None:
    box = Outbox(tmp_path / "outbox.db")
    assert box.journal_mode() == "wal"
    box.put(ev(1, "unattended", ended_at=None))
    box.put(ev(1, "unattended", ended_at="2026-11-20T10:30:00Z"))
    [(eid, payload)] = box.due(now=1e12)
    assert eid == "e00001" and payload["ended_at"] == "2026-11-20T10:30:00Z"
    reopened = Outbox(tmp_path / "outbox.db")
    assert reopened.depth() == 1  # survives a restart


def test_cap_drops_oldest_after_hours_motion_first(tmp_path: Path) -> None:
    box = Outbox(tmp_path / "o.db", max_bytes=10**9)
    pad = "x" * 2000
    for i in range(300):
        box.put(ev(i, "after_hours_motion", meta={"pad": pad}), now=float(i))
    for i in range(300, 400):
        box.put(ev(i, "entry", meta={"pad": pad}), now=float(i))
    box.max_bytes = int(box.size_bytes() * 0.6)
    dropped = box.enforce_cap()
    assert dropped > 0
    kept = {e["id"] for _, e in box.due(1e12, limit=1000)}
    assert all(f"e{i:05d}" in kept for i in range(300, 400))  # never drop other events
    assert "e00000" not in kept and "e00299" in kept  # oldest motion went first


def test_batches_of_at_most_500_deleted_on_success() -> None:
    box = Outbox(":memory:")
    for i in range(1201):
        box.put(ev(i), now=float(i))
    sizes: list[int] = []
    up = Uploader(box, lambda batch: sizes.append(len(batch)))
    assert up.run(now=1000.0) == 1201
    assert sizes == [500, 500, 201] and box.depth() == 0


def test_every_60s_or_100_rows() -> None:
    box = Outbox(":memory:")
    calls: list[int] = []
    up = Uploader(box, lambda b: calls.append(len(b)))
    box.put(ev(1))
    up.run(0.0)
    box.put(ev(2))
    assert up.run(30.0) == 0  # too early, too few
    for i in range(3, 103):
        box.put(ev(i))
    assert up.run(31.0) == 101  # >= 100 rows waiting
    box.put(ev(200))
    assert up.run(92.0) == 1


def test_failure_keeps_rows_and_backs_off_with_cap() -> None:
    box = Outbox(":memory:")
    box.put(ev(1))

    def down(_: list[dict[str, Any]]) -> None:
        raise ApiError(503, "unavailable")

    up = Uploader(box, down, rng=random.Random(1))  # noqa: S311
    waits = []
    now = 0.0
    for _ in range(12):
        up.run(now, force=True)
        waits.append(up.blocked_until - now)
        now = up.blocked_until
    assert box.depth() == 1  # never dropped
    assert waits[0] < waits[3] < waits[6]
    assert max(waits) <= BACKOFF_MAX_S
    up.post = lambda b: None
    assert up.run(now) == 1 and box.depth() == 0 and up.failures == 0


def test_invalid_event_is_set_aside_and_the_rest_is_sent() -> None:
    box = Outbox(":memory:")
    for i in range(3):
        box.put(ev(i), now=float(i))
    sent: list[str] = []

    def post(batch: list[dict[str, Any]]) -> None:
        if any(e["id"] == "e00001" for e in batch):
            raise ApiError(422, "bad")
        sent.extend(e["id"] for e in batch)

    assert Uploader(box, post).run(10.0) == 2
    assert sent == ["e00000", "e00002"] and box.depth() == 0


@pytest.mark.parametrize("status", [401, 500])
def test_other_http_errors_retry_later(status: int) -> None:
    box = Outbox(":memory:")
    box.put(ev(1))

    def post(_: list[dict[str, Any]]) -> None:
        raise ApiError(status, "x")

    up = Uploader(box, post)
    assert up.run(0.0) == 0 and box.depth() == 1 and up.blocked_until > 0
