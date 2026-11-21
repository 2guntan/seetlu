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
    # M3
    ("post", "/v1/edge/register"),
    ("get", "/v1/edge/config"),
    ("post", "/v1/edge/events"),
    ("post", "/v1/edge/heartbeat"),
    ("get", "/v1/edge/commands"),
    ("post", "/v1/edge/commands/{command_id}/result"),
    # M7
    ("post", "/v1/shops/{shop_id}/snapshot"),
    ("get", "/v1/clips/{clip_id}"),
    ("post", "/v1/moments/{report_id}/{rank}/clip"),
    ("get", "/v1/webhooks/whatsapp"),
    ("post", "/v1/webhooks/whatsapp"),
    # M8
    ("get", "/v1/shops/{shop_id}/reports"),
    ("get", "/v1/shops/{shop_id}/today"),
    ("get", "/v1/shops/{shop_id}/hourly"),
    ("get", "/v1/shops/{shop_id}/events"),
    ("get", "/v1/shops/{shop_id}/sales"),
    ("post", "/v1/shops/{shop_id}/sales"),
    ("delete", "/v1/shops/{shop_id}/sales/{sale_id}"),
    ("get", "/v1/shops/{shop_id}/clips"),
    ("post", "/v1/shops/{shop_id}/corrections"),
    ("post", "/v1/clips/{clip_id}/save"),
    ("delete", "/v1/clips/{clip_id}/save"),
    ("get", "/v1/commands/{command_id}"),
    ("get", "/v1/audit-log"),
    ("post", "/v1/support-grants"),
    ("post", "/v1/kits/claim"),
    ("put", "/v1/kits/{kit_id}/cameras"),
    ("post", "/v1/kits/{kit_id}/count-checks"),
    ("post", "/v1/count-checks/{check_id}/stop"),
    ("post", "/v1/kits/{kit_id}/activate"),
    ("get", "/v1/support/kits"),
    ("get", "/v1/support/kits/{kit_id}"),
    ("put", "/v1/support/kits/{kit_id}/target-version"),
    ("post", "/v1/support/kits/{kit_id}/commands"),
    # M9
    ("post", "/v1/shops/{shop_id}/phone-pairing-codes"),
    ("get", "/v1/shops/{shop_id}/phones"),
    ("post", "/v1/phone/pair"),
    ("get", "/v1/phone/parsers"),
    ("post", "/v1/sales/batch"),
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
