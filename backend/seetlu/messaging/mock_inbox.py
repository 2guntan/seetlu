"""Dev-only mock WhatsApp inbox (docs/07): what MockProvider stored in `mock_messages`, and a way to
reply as a registered phone (runs the real inbound handler, as the webhook worker would).

Run as the `mock-whatsapp` compose service: http://localhost:8025 (page), /messages (JSON).
"""

import html
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from seetlu.db.models import MockMessage, User, WaInbound
from seetlu.db.session import session_factory
from seetlu.i18n import render_template
from seetlu.messaging.processing import process
from seetlu.messaging.provider import MockProvider


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    to_phone: str
    kind: str
    template: str | None
    lang: str | None
    params: list[Any]
    buttons: list[Any]
    body: str | None
    url: str | None
    created_at: datetime


class InboundIn(BaseModel):
    from_phone: str
    text: str


class InboundOut(BaseModel):
    reply: str | None


def get_db() -> Iterator[Session]:
    with session_factory()() as s:
        yield s


DB = Annotated[Session, Depends(get_db)]


def rendered(msg: MockMessage) -> str:
    if msg.kind == "template" and msg.template:
        return render_template(
            msg.template.removesuffix(f"_{msg.lang}"), [str(p) for p in msg.params], msg.lang or "fr"
        )
    if msg.kind == "media":
        return f"[image] {msg.body or ''}\n{msg.url or ''}"
    return msg.body or ""


def receive(s: Session, phone: str, text: str) -> str | None:
    row = WaInbound(wa_message_id=f"mock-{uuid.uuid4()}", from_phone=phone.lstrip("+"), body=text)
    s.add(row)
    s.commit()
    return process(s, row.id, MockProvider(s), datetime.now(UTC))


PAGE = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Seetlu – WhatsApp (mock)</title>
<style>body{{font-family:system-ui,sans-serif;margin:0;background:#e5ddd5}}header{{background:#075e54;color:#fff;
padding:12px 16px}}main{{max-width:720px;margin:0 auto;padding:12px}}.m{{background:#fff;border-radius:8px;
padding:8px 10px;margin:8px 0;white-space:pre-wrap;box-shadow:0 1px 1px #0002}}.meta{{color:#667;font-size:12px}}
form{{display:flex;gap:8px;margin:8px 0}}input,select,button{{font:inherit;padding:6px}}
input[name=text]{{flex:1}}</style></head><body><header>Seetlu – boîte WhatsApp de test (dev)</header><main>
<form id="f"><select name="from_phone">{phones}</select>
<input name="text" placeholder="Répondre : 1, photo, +2500, aide…" required><button>Envoyer</button></form>
{messages}</main><script>document.getElementById("f").onsubmit=async e=>{{e.preventDefault();
const d=new FormData(e.target);await fetch("/inbound",{{method:"POST",headers:{{"Content-Type":"application/json"}},
body:JSON.stringify({{from_phone:d.get("from_phone"),text:d.get("text")}})}});location.reload()}};
setTimeout(()=>location.reload(),15000)</script></body></html>"""


def create_app() -> FastAPI:
    app = FastAPI(title="Seetlu mock WhatsApp")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/messages")
    def list_messages(s: DB, to: str | None = None, limit: int = 100) -> list[MessageOut]:
        q = select(MockMessage).order_by(MockMessage.id.desc()).limit(min(limit, 500))
        if to:
            q = q.where(MockMessage.to_phone == to)
        return [MessageOut.model_validate(r) for r in s.scalars(q)]

    @app.delete("/messages", status_code=204)
    def clear(s: DB) -> None:
        s.execute(delete(MockMessage))
        s.commit()

    @app.post("/inbound")
    def inbound(body: InboundIn, s: DB) -> InboundOut:
        """Simulate a WhatsApp message from `from_phone`; replies land in the inbox."""
        return InboundOut(reply=receive(s, body.from_phone, body.text))

    @app.get("/", response_class=HTMLResponse)
    def page(s: DB) -> str:
        users = s.scalars(select(User).where(User.active.is_(True)).order_by(User.phone_e164)).all()
        names = {u.phone_e164: u.name for u in users}
        phones = "".join(
            f'<option value="{html.escape(u.phone_e164)}">{html.escape(u.name)} {html.escape(u.phone_e164)}</option>'
            for u in users
        )
        msgs = s.scalars(select(MockMessage).order_by(MockMessage.id.desc()).limit(200)).all()
        items = "".join(
            f'<div class="m"><div class="meta">→ {html.escape(names.get(x.to_phone, x.to_phone))} · '
            f"{x.created_at:%Y-%m-%d %H:%M} · {html.escape(x.template or x.kind)}</div>"
            f"{html.escape(rendered(x))}</div>"
            for x in msgs
        )
        return PAGE.format(phones=phones, messages=items or "<p>Aucun message.</p>")

    return app


app = create_app()
