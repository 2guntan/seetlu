"""Uploader loop step: every 60 s or as soon as 100 rows wait, POST batches of <= 500 events; delete on
success; exponential backoff with jitter (max 15 min) on failure (docs/05)."""

import logging
import random
from collections.abc import Callable
from typing import Any

from seetlu_agent.api import ApiError
from seetlu_agent.outbox import Outbox

log = logging.getLogger(__name__)

BATCH = 500
EVERY_S = 60.0
EAGER_ROWS = 100
BACKOFF_BASE_S = 5.0
BACKOFF_MAX_S = 15 * 60.0

Post = Callable[[list[dict[str, Any]]], Any]


class Uploader:
    def __init__(self, outbox: Outbox, post: Post, rng: random.Random | None = None) -> None:
        self.outbox, self.post = outbox, post
        self.rng = rng or random.Random()  # noqa: S311 - jitter, not security
        self.last_run: float | None = None
        self.failures = 0
        self.blocked_until = 0.0

    def backoff_s(self) -> float:
        base = min(BACKOFF_MAX_S, BACKOFF_BASE_S * 2 ** max(0, self.failures - 1))
        jittered: float = base * self.rng.uniform(0.5, 1.0) + self.rng.uniform(0, 1)
        return min(BACKOFF_MAX_S, jittered)

    def should_run(self, now: float) -> bool:
        if now < self.blocked_until:
            return False
        if self.last_run is None or now - self.last_run >= EVERY_S:
            return True
        return self.outbox.depth() >= EAGER_ROWS

    def run(self, now: float, force: bool = False) -> int:
        """Upload every due batch; returns how many events were accepted by the server."""
        if not force and not self.should_run(now):
            return 0
        self.last_run = now
        sent = 0
        while True:
            rows = self.outbox.due(now if not force else float("inf"), BATCH)
            if not rows:
                break
            ids = [i for i, _ in rows]
            try:
                self.post([p for _, p in rows])
            except ApiError as exc:
                if exc.status != 422:
                    self._fail(ids, now, exc)
                    break
                sent += self._one_by_one(rows, now)
                if self.blocked_until > now:
                    break
                continue
            except Exception as exc:  # network, timeouts: keep the rows, retry later
                self._fail(ids, now, exc)
                break
            self.failures = 0
            self.blocked_until = 0.0
            self.outbox.delete(ids)
            sent += len(ids)
            if len(rows) < BATCH:
                break
        return sent

    def _fail(self, ids: list[str], now: float, exc: Exception) -> None:
        self.failures += 1
        wait = self.backoff_s()
        self.blocked_until = now + wait
        self.outbox.failed(ids, now + wait)
        log.warning("upload of %d events failed (%s); retry in %.0f s", len(ids), exc, wait)

    def _one_by_one(self, rows: list[tuple[str, dict[str, Any]]], now: float) -> int:
        """A batch was refused as invalid: find the bad events, set them aside, send the rest."""
        sent = 0
        for event_id, payload in rows:
            try:
                self.post([payload])
            except ApiError as exc:
                if exc.status == 422:
                    log.error("server rejected event %s: %s", event_id, exc)
                    self.outbox.reject([event_id])
                    continue
                self._fail([event_id], now, exc)
                return sent
            self.outbox.delete([event_id])
            sent += 1
        return sent
