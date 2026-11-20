"""Rendering of the daily report template parameters (docs/06 wording, docs/07 template)."""

from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from seetlu.domain.report import Baseline, Report
from seetlu.domain.report_text import (
    MINUS,
    NNBSP,
    check_wording,
    daily_report_params,
    money,
    pct,
    short_date,
    sources_text,
)
from seetlu.i18n import catalog, render_template
from tests.test_domain_report import B, metrics

TZ = ZoneInfo("Africa/Dakar")
D = date(2026, 11, 20)


def report(verdict: str = "normal", **kw: object) -> Report:
    base: dict[str, object] = {
        "metrics": metrics(),
        "baseline": B,
        "verdict": verdict,
        "valid": True,
        "confidence": {"visitors_in": "high", "served": "high", "sales": "high"},
        "moments": [],
        "vs_last_week": None,
    }
    return Report(**(base | kw))  # type: ignore[arg-type]


def test_money_and_percent_use_french_typography() -> None:
    assert money(125_000) == f"125{NNBSP}000"
    assert pct(-12) == f"{MINUS}12{NNBSP}%"
    assert pct(5) == f"+5{NNBSP}%"
    assert short_date(D) == "ven. 20 nov."


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("normal", "verdict.normal"),
        ("worth_a_look", "verdict.worth_a_look"),
        ("large_gap", "verdict.large_gap"),
        ("not_enough_activity", "verdict.not_enough_activity"),
    ],
)
def test_verdict_wording_is_the_fixed_docs06_text_AC_F4_3(code: str, expected: str) -> None:
    params = daily_report_params("Boutique Awa", D, TZ, report(code))
    assert params[6] == catalog("fr")[expected]


def test_missing_hours_are_named_never_zero_AC_F4_5() -> None:
    r = report(metrics=metrics(missing_hours=[14, 15]))
    text = daily_report_params("Boutique Awa", D, TZ, r)[6]
    assert "14" in text and "15" in text
    assert text.startswith(catalog("fr")["verdict.normal"])


def test_low_confidence_values_are_marked_as_estimates() -> None:
    r = report(confidence={"visitors_in": "low", "served": "medium", "sales": "low"})
    p = daily_report_params("Boutique Awa", D, TZ, r)
    assert p[2].endswith(catalog("fr")["report.estimate"])
    assert p[3] == "50"
    assert p[4] == f"125{NNBSP}000"  # the template adds " F"; the flag goes inside the brackets
    assert p[5].startswith(catalog("fr")["report.estimate_prefix"])


def test_cash_declaration_not_shown_twice_when_quick_logs_exist() -> None:
    text = sources_text({"wave": 50_000, "quick_log": 20_000, "cash_declaration": 20_000})
    assert text.count("20") == 1


def test_rendered_template_has_no_placeholder_left_and_never_accuses() -> None:
    body = render_template("daily_report", daily_report_params("Boutique Awa", D, TZ, report()), "fr")
    assert "{{" not in body
    check_wording(body)
    with pytest.raises(ValueError, match="accusing"):
        check_wording("Possible vol à 14 h")


def test_learning_counts_days_up_to_14_AC_F4_4() -> None:
    r = report("learning", baseline=Baseline(Decimal("0"), Decimal("0"), 6))
    assert "6" in daily_report_params("Boutique Awa", D, TZ, r)[6]
