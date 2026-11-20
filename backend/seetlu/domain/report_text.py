"""Report → `daily_report_fr` template parameters (docs/07), with the fixed verdict wording of docs/06."""

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from seetlu.domain.report import Report
from seetlu.i18n import t

NNBSP = chr(0x202F)  # narrow no-break space: French thousands separator and before %
MINUS = chr(0x2212)  # typographic minus sign
FORBIDDEN_WORDS = ("vol", "voleur", "fraude")  # docs/06: never in automatic messages


def money(xof: int) -> str:
    return f"{xof:,}".replace(",", NNBSP)


def pct(value: int | None) -> str:
    if value is None:
        return chr(0x2013)  # en dash: no value
    sign = "+" if value > 0 else (MINUS if value < 0 else "")
    return f"{sign}{abs(value)}{NNBSP}%"


def short_date(d: date, lang: str = "fr") -> str:
    return f"{t(f'weekday_short.{d.weekday()}', lang)} {d.day} {t(f'month_short.{d.month}', lang)}"


def hhmm(ts: datetime, tz: ZoneInfo, lang: str = "fr") -> str:
    local = ts.astimezone(tz)
    return t("report.time", lang, h=local.hour, m=f"{local.minute:02d}")


def hours_list(hours: list[int], lang: str = "fr") -> str:
    return ", ".join(t("report.hour", lang, h=h) for h in hours)


def verdict_text(r: Report, lang: str = "fr") -> str:
    m = r.metrics
    if r.verdict == "learning":
        text = t("verdict.learning", lang, n=min(r.baseline.n_days, 14))
    elif r.verdict == "incomplete_data":
        return t("verdict.incomplete_data", lang, hours=hours_list(m.missing_hours, lang))
    else:
        text = t(f"verdict.{r.verdict}", lang)
    if m.missing_hours:  # AC-F4-5: any missing opening hour is listed, never shown as zero
        text += " " + t("report.missing_hours", lang, hours=hours_list(m.missing_hours, lang))
    return text


def _estimate(value: str, level: str | None, lang: str) -> str:
    return f"{value} {t('report.estimate', lang)}" if level == "low" else value


def _estimate_prefix(value: str, level: str | None, lang: str) -> str:
    return f"{t('report.estimate_prefix', lang)} {value}" if level == "low" else value


def sources_text(by_source: dict[str, int], lang: str = "fr") -> str:
    parts: dict[str, int] = {}
    cash_logged = by_source.get("quick_log", 0) > 0
    for src, amount in by_source.items():
        if src == "cash_declaration" and cash_logged:
            continue  # shown through quick logs; never counted twice
        label = t(f"source.{src}", lang)
        parts[label] = parts.get(label, 0) + amount
    shown = [f"{label} {money(v)}" for label, v in parts.items() if v > 0]
    return " · ".join(shown) if shown else t("report.no_sales", lang)


def moments_text(r: Report, tz: ZoneInfo, lang: str = "fr") -> str:
    if not r.moments:
        return t("report.no_moment", lang)
    items = []
    for mo in r.moments:
        label = t(
            f"moment.{mo.kind}",
            lang,
            time=hhmm(mo.started_at, tz, lang),
            min=max(1, round(mo.duration_s / 60)),
        )
        items.append(f"{mo.rank}) {label}")
    return " ".join(items)


def comparison_text(r: Report, lang: str = "fr") -> str:
    if not r.vs_last_week:
        return t("report.no_comparison", lang)
    keys = ("visitors_in", "served", "sales_xof")
    return ", ".join(t(f"report.delta.{k}", lang, pct=pct(r.vs_last_week[k]["pct"])) for k in keys)


def daily_report_params(shop_name: str, d: date, tz: ZoneInfo, r: Report, lang: str = "fr") -> list[str]:
    m, c = r.metrics, r.confidence
    busiest = (
        t("report.hour_range", lang, a=m.busiest_hour, b=m.busiest_hour + 1)
        if m.busiest_hour is not None
        else t("report.no_busiest_hour", lang)
    )
    params = [
        shop_name,
        short_date(d, lang),
        _estimate(str(m.visitors_in), c.get("visitors_in"), lang),
        _estimate(str(m.served), c.get("served"), lang),
        money(m.sales_xof),
        # the template reads "{{5}} F ({{6}})": a low-confidence total is flagged inside the brackets
        _estimate_prefix(sources_text(m.sales_by_source, lang), c.get("sales"), lang),
        verdict_text(r, lang),
        str(m.unattended_min),
        busiest,
        t(f"weekday.{d.weekday()}", lang),
        comparison_text(r, lang),
        moments_text(r, tz, lang),
    ]
    for p in params[1:]:  # the shop name is the owner's own text
        check_wording(p)
    return params


def check_wording(text: str) -> None:
    """Rule 4 (never accuse): automatic text must not contain accusing words."""
    words = re.findall(r"\w+", text.lower())
    if any(w in FORBIDDEN_WORDS for w in words):
        raise ValueError(f"accusing word in automatic text: {text!r}")
