"""Dev-only mock WhatsApp inbox.

Stands in for the WhatsApp Cloud API in dev and tests: stores every outbound message in memory
and lists them. The full MessagingProvider interface arrives in M7.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel


class OutboundMessage(BaseModel):
    to: str
    template: str | None = None
    params: dict[str, Any] = {}
    text: str | None = None


class StoredMessage(OutboundMessage):
    received_at: datetime


def create_app() -> FastAPI:
    app = FastAPI(title="Seetlu mock WhatsApp")
    inbox: list[StoredMessage] = []

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/messages", status_code=201)
    def send(msg: OutboundMessage) -> StoredMessage:
        stored = StoredMessage(**msg.model_dump(), received_at=datetime.now(UTC))
        inbox.append(stored)
        return stored

    @app.get("/messages")
    def list_messages() -> list[StoredMessage]:
        return inbox

    @app.delete("/messages", status_code=204)
    def clear() -> None:
        inbox.clear()

    return app


app = create_app()
