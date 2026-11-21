"""Versioned notification parser rules served to shop phones (GET /v1/phone/parsers, docs/08).

The phone applies them; the server only keeps the reference copy so it can tell whether a phone runs
the current version (sales confidence, docs/06). Python's `(?P<name>…)` is accepted as an alias of
`(?<name>…)` so the same JSON is checked here and compiled by Kotlin on the phone.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

RULES_FILE = Path(__file__).with_name("rules.json")


@dataclass(frozen=True)
class Parsed:
    rule_id: str
    source: str
    amount_xof: int
    external_ref: str | None


@lru_cache
def load() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(RULES_FILE.read_text("utf-8"))
    return data


def current_version() -> str:
    return str(load()["version"])


def etag() -> str:
    return '"' + hashlib.sha256(RULES_FILE.read_bytes()).hexdigest()[:16] + '"'


def _py(regex: str) -> re.Pattern[str]:
    return re.compile(regex.replace("(?<", "(?P<").replace("(?P<=", "(?<=").replace("(?P<!", "(?<!"), re.S)


def amount_of(text: str) -> int | None:
    digits = re.sub(r"\D", "", text)
    return int(digits) if digits else None


def parse(package: str, text: str) -> Parsed | str | None:
    """Parsed sale, "unparsed" (looks like a payment, no rule matched), or None (ignore)."""
    hinted = False
    for rule in load()["rules"]:
        if rule["package"] != package or rule.get("direction") != "in":
            continue
        m = _py(rule["match_regex"]).search(text)
        if m:
            amount = amount_of(m.group(rule["amount_group"]))
            if amount is None:
                return "unparsed"
            ref = m.group(rule["ref_group"]) if rule.get("ref_group") else None
            return Parsed(rule["id"], rule["source"], amount, ref)
        if rule.get("hint_regex") and _py(rule["hint_regex"]).search(text):
            hinted = True
    return "unparsed" if hinted else None
