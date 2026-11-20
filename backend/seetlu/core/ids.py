"""UUIDv7 (RFC 9562): 48-bit unix ms timestamp, then random bits. Sortable by creation time.

Python 3.12 has no `uuid.uuid7`, so we generate it here. Within one process, ids are strictly
increasing even when several are created in the same millisecond (12-bit counter in rand_a).
"""

import secrets
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms = -1
_counter = 0


def uuid7(now_ms: int | None = None) -> uuid.UUID:
    global _last_ms, _counter
    with _lock:
        ms = time.time_ns() // 1_000_000 if now_ms is None else now_ms
        if ms <= _last_ms:
            ms = _last_ms
            _counter += 1
            if _counter > 0xFFF:  # counter overflow: borrow the next millisecond
                ms += 1
                _counter = secrets.randbits(11)
        else:
            _counter = secrets.randbits(11)  # leave headroom for increments
        _last_ms = ms
        counter = _counter

    value = (ms & 0xFFFF_FFFF_FFFF) << 80
    value |= 0x7 << 76  # version 7
    value |= counter << 64  # rand_a: monotonic counter
    value |= 0b10 << 62  # RFC 4122/9562 variant
    value |= secrets.randbits(62)
    return uuid.UUID(int=value)


def uuid7_timestamp_ms(value: uuid.UUID) -> int:
    return value.int >> 80
