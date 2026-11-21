"""docs/07 inbound grammar table, fully tested (docs/11 M7)."""

import pytest

from seetlu.domain.grammar import Command, normalize, parse, parse_amount


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1", Command("moment", 1)),
        (" 2 ", Command("moment", 2)),
        ("3", Command("moment", 3)),
        ("4", Command("number", 4)),
        ("Photo", Command("photo")),
        ("PHOTO ", Command("photo")),
        ("faux", Command("faux")),
        ("Faux", Command("faux")),
        ("annuler", Command("annuler")),
        ("Annulér", Command("annuler")),
        ("stop", Command("stop")),
        ("START", Command("start")),
        ("aide", Command("aide")),
        ("Aidé", Command("aide")),
        ("bonjour", Command("unknown")),
        ("", Command("unknown")),
        ("photo svp", Command("unknown")),
    ],
)
def test_commands_case_and_accents_ignored(text: str, expected: Command) -> None:
    assert parse(text) == expected


@pytest.mark.parametrize(
    ("text", "amount"),
    [("+2500", 2500), ("+ 2 500", 2500), ("+2.500", 2500), ("+2500 F", 2500), ("+ 15 000 fcfa", 15000)],
)
def test_quick_log_pattern_AC_F3_4(text: str, amount: int) -> None:
    assert parse(text) == Command("quick_log", amount)


@pytest.mark.parametrize(
    ("text", "amount"),
    [("85000", 85000), ("85 000", 85000), ("85.000 F", 85000), ("85000fcfa", 85000), ("85 000 FCFA", 85000)],
)
def test_bare_amount_for_cash_declaration_AC_F3_5(text: str, amount: int) -> None:
    assert parse(text) == Command("number", amount)


def test_amount_over_ten_million_is_rejected() -> None:
    assert parse("+10000001") == Command("too_large", 10_000_001)
    assert parse("12 000 000") == Command("too_large", 12_000_000)
    assert parse("+10 000 000") == Command("quick_log", 10_000_000)


@pytest.mark.parametrize("text", ["+", "+abc", "++2500", "+0", "2500 euros", "-2500", "0"])
def test_not_amounts(text: str) -> None:
    assert parse(text).kind == "unknown"


def test_normalize_and_parse_amount() -> None:
    assert normalize("  Équipe   Médina ") == "equipe medina"
    assert parse_amount("1 250 F") == 1250
    assert parse_amount("deux mille") is None
