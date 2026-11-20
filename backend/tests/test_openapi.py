"""M2 done-when: OpenAPI served at /docs matches docs/04-api.openapi.yaml for what is implemented.

`IMPLEMENTED` grows milestone by milestone; the final milestone asserts every path in 04 exists.
"""

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from seetlu.main import create_app

SPEC = Path(__file__).resolve().parents[2] / "docs" / "04-api.openapi.yaml"

IMPLEMENTED: set[tuple[str, str]] = {
    ("post", "/v1/auth/otp/request"),
    ("post", "/v1/auth/otp/verify"),
    ("post", "/v1/auth/refresh"),
    ("get", "/v1/me"),
    ("get", "/v1/shops"),
    ("post", "/v1/shops"),
    ("get", "/v1/shops/{shop_id}"),
    ("patch", "/v1/shops/{shop_id}"),
    ("get", "/v1/shops/{shop_id}/users"),
    ("post", "/v1/shops/{shop_id}/users"),
    ("get", "/v1/shops/{shop_id}/alert-rules"),
    ("put", "/v1/shops/{shop_id}/alert-rules"),
}
METHODS = {"get", "post", "put", "patch", "delete"}


def _ops(paths: dict[str, dict[str, object]]) -> set[tuple[str, str]]:
    return {(meth, p) for p, item in paths.items() for meth in item if meth in METHODS}


@pytest.fixture(scope="module")
def spec_ops() -> set[tuple[str, str]]:
    if not SPEC.exists():
        pytest.skip("docs/ not available")
    return _ops(yaml.safe_load(SPEC.read_text())["paths"])


def test_m2_docs_served() -> None:
    client = TestClient(create_app())
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_m2_implemented_operations_are_in_contract(spec_ops: set[tuple[str, str]]) -> None:
    assert spec_ops >= IMPLEMENTED


def test_m2_app_serves_implemented_and_nothing_outside_contract(spec_ops: set[tuple[str, str]]) -> None:
    served = {op for op in _ops(create_app().openapi()["paths"]) if op[1].startswith("/v1/")}
    assert served >= IMPLEMENTED
    assert served <= spec_ops, served - spec_ops
