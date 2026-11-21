"""Inbound WhatsApp command grammar (docs/07): case-insensitive, accents ignored, trimmed. Pure."""

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

MAX_AMOUNT_XOF = 10_000_000

Kind = Literal[
    "moment", "photo", "faux", "quick_log", "number", "annuler", "stop", "start", "aide",
    "too_large", "unknown",
]  # fmt: skip

QUICK_LOG = re.compile(r"^\+\s?\d[\d\s.]*$")  # AC-F3-4
NUMBER = re.compile(r"^\d[\d\s.]*$")
CURRENCY = re.compile(r"\s*(f\s*cfa|fcfa|cfa|f)\s*$")


@dataclass(frozen=True)
class Command:
    kind: Kind
    value: int | None = None


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(no_accents.lower().split())


def parse_amount(text: str) -> int | None:
    """« 85 000 », « 85.000 F », « 85000fcfa » → 85000; None if it is not an amount."""
    t = CURRENCY.sub("", normalize(text)).strip()
    if not NUMBER.match(t):
        return None
    digits = re.sub(r"[\s.]", "", t)
    return int(digits) if digits else None


def parse(text: str) -> Command:
    t = normalize(text)
    if t in ("1", "2", "3"):
        return Command("moment", int(t))
    words = {"photo": "photo", "faux": "faux", "annuler": "annuler", "stop": "stop", "start": "start",
             "aide": "aide"}  # fmt: skip
    if t in words:
        return Command(words[t])  # type: ignore[arg-type]
    bare = CURRENCY.sub("", t).strip()
    if bare.startswith("+") and QUICK_LOG.match(bare):
        amount = parse_amount(bare[1:])
        return _amount("quick_log", amount)
    amount = parse_amount(t)
    if amount is not None:
        return _amount("number", amount)
    return Command("unknown")


def _amount(kind: Kind, amount: int | None) -> Command:
    if amount is None or amount <= 0:
        return Command("unknown")
    if amount > MAX_AMOUNT_XOF:
        return Command("too_large", amount)
    return Command(kind, amount)
