import time
import uuid

import pytest

import seetlu.core.ids as ids_module
from seetlu.core.ids import uuid7, uuid7_timestamp_ms


def test_m1_uuid7_version_and_variant() -> None:
    u = uuid7()
    assert u.version == 7
    assert u.variant == uuid.RFC_4122


def test_m1_uuid7_is_monotonic_within_process() -> None:
    ids = [uuid7() for _ in range(20_000)]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


def test_m1_uuid7_monotonic_with_frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ids_module, "_last_ms", -1)  # restored after the test
    monkeypatch.setattr(ids_module, "_counter", 0)
    ids = [uuid7(now_ms=1_800_000_000_000) for _ in range(5_000)]  # forces counter overflow path
    assert ids == sorted(ids) and len(set(ids)) == len(ids)


def test_m1_uuid7_embeds_timestamp() -> None:
    before = time.time_ns() // 1_000_000
    u = uuid7()
    after = time.time_ns() // 1_000_000
    assert before <= uuid7_timestamp_ms(u) <= after + 2
