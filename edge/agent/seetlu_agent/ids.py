"""Deterministic UUIDv7 for edge events.

The id is the idempotency key on the server (docs/03: events PK). We derive it from the event start time
(48-bit ms timestamp, so ids sort by time) and a hash of a stable key (kit serial + camera + track or
start), so re-processing the same Frigate data, re-sending, or updating an open event reuses the same id.
"""

import hashlib
import uuid


def event_uuid(started_at: float, key: str) -> uuid.UUID:
    ms = int(started_at * 1000) & 0xFFFF_FFFF_FFFF
    digest = int.from_bytes(hashlib.sha256(key.encode()).digest()[:10], "big")  # 80 bits
    rand_a = (digest >> 68) & 0xFFF
    rand_b = digest & ((1 << 62) - 1)
    value = (ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)
