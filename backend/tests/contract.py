"""Validate payloads against the component schemas in docs/04-api.openapi.yaml."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

SPEC = Path(__file__).resolve().parents[2] / "docs" / "04-api.openapi.yaml"


@lru_cache
def _registry() -> Registry[Any]:
    spec = yaml.safe_load(SPEC.read_text())
    resource: Resource[Any] = Resource.from_contents(spec, default_specification=DRAFT202012)
    registry: Registry[Any] = Registry().with_resource("urn:seetlu-api", resource)
    return registry


def assert_matches(component: str, payload: Any) -> None:
    if not SPEC.exists():
        pytest.skip("docs/ not available")
    validator = Draft202012Validator(
        {"$ref": f"urn:seetlu-api#/components/schemas/{component}"}, registry=_registry()
    )
    errors = sorted(validator.iter_errors(payload), key=str)
    assert not errors, [f"{list(e.absolute_path)}: {e.message}" for e in errors]
