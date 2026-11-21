"""WhatsApp Cloud API webhook (docs/07): Meta verification, signed inbound messages, async processing."""

import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, Request, Response
from sqlalchemy.dialects.postgresql import insert

from seetlu.api.deps import DB
from seetlu.core.config import get_settings
from seetlu.core.problem import Problem
from seetlu.db import models as m

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])
log = logging.getLogger(__name__)


def signature_ok(secret: str, body: bytes, header: str | None) -> bool:
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def inbound_messages(payload: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(message id, from, text) for text messages and quick-reply buttons; statuses are ignored."""
    out = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            for msg in (change.get("value") or {}).get("messages") or []:
                kind = msg.get("type")
                if kind == "text":
                    text = (msg.get("text") or {}).get("body", "")
                elif kind == "button":
                    text = (msg.get("button") or {}).get("text", "")
                elif kind == "interactive":
                    inter = msg.get("interactive") or {}
                    text = (inter.get("button_reply") or inter.get("list_reply") or {}).get("title", "")
                else:
                    text = ""  # media, location…: answered « Je n'ai pas compris »
                out.append((str(msg["id"]), str(msg["from"]), text))
    return out


@router.get("/whatsapp")
def verify(request: Request) -> Response:
    q = request.query_params
    token = get_settings().wa_verify_token
    if (
        q.get("hub.mode") == "subscribe"
        and token
        and hmac.compare_digest(q.get("hub.verify_token", ""), token)
    ):
        return Response(q.get("hub.challenge", ""), media_type="text/plain")
    raise Problem(403, "forbidden", "Verification token mismatch")


@router.post("/whatsapp")
async def receive(request: Request, s: DB) -> dict[str, int]:
    """Stores each new message (Meta retries: unique message id) and hands it to the worker; answers
    within Meta's 3 s budget."""
    from seetlu.workers.tasks import process_inbound  # the API image runs the worker code too

    body = await request.body()
    if not signature_ok(get_settings().wa_app_secret, body, request.headers.get("x-hub-signature-256")):
        raise Problem(401, "invalid-signature", "X-Hub-Signature-256 does not match")
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise Problem(400, "bad-request", "Body is not JSON") from exc
    new = []
    for wa_id, sender, text in inbound_messages(payload):
        stmt = insert(m.WaInbound).values(wa_message_id=wa_id, from_phone=sender, body=text)
        row = s.execute(stmt.on_conflict_do_nothing().returning(m.WaInbound.id)).scalar_one_or_none()
        if row is not None:
            new.append(row)
    s.commit()
    for inbound_id in new:
        try:
            process_inbound.delay(str(inbound_id))
        except Exception:  # broker down: the row stays unprocessed and the sweep picks it up
            log.exception("could not enqueue inbound %s", inbound_id)
    return {"received": len(new)}
