"""Server-side strings (WhatsApp messages). French is the default; other languages fall back to it key by key.

Wolof and English message catalogs are v2 (docs/07: template keys are language-suffixed so adding them
is configuration only)."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_LANG = "fr"


@lru_cache
def catalog(lang: str) -> dict[str, str]:
    base: dict[str, str] = json.loads((HERE / f"{DEFAULT_LANG}.json").read_text())
    path = HERE / f"{lang}.json"
    if lang != DEFAULT_LANG and path.exists():
        extra: dict[str, str] = json.loads(path.read_text())
        return base | extra
    return base


def t(key: str, lang: str = DEFAULT_LANG, **params: Any) -> str:
    text = catalog(lang)[key]
    return text.format(**params) if params else text


def render_template(name: str, params: list[str], lang: str = DEFAULT_LANG) -> str:
    """Fill a WhatsApp template body (`{{1}}`, `{{2}}`, …) the way WhatsApp shows it."""
    body = catalog(lang)[f"template.{name}"]
    for i, value in enumerate(params, 1):
        body = body.replace(f"{{{{{i}}}}}", value)
    return body
