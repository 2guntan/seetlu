"""Dev-only mock WhatsApp inbox: lists what MockProvider stored in `mock_messages`.

Run as the `mock-whatsapp` compose service (http://localhost:8025/messages). The HTML inbox page
arrives with the rest of the WhatsApp work in M7.
"""

import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from seetlu.db.models import MockMessage
from seetlu.db.session import session_factory


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


def get_db() -> Iterator[Session]:
    with session_factory()() as s:
        yield s


DB = Annotated[Session, Depends(get_db)]


def create_app() -> FastAPI:
    app = FastAPI(title="Seetlu mock WhatsApp")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/messages")
    def list_messages(s: DB, to: str | None = None, limit: int = 100) -> list[MessageOut]:
        q = select(MockMessage).order_by(MockMessage.created_at.desc()).limit(min(limit, 500))
        if to:
            q = q.where(MockMessage.to_phone == to)
        return [MessageOut.model_validate(r) for r in s.scalars(q)]

    @app.delete("/messages", status_code=204)
    def clear(s: DB) -> None:
        s.execute(delete(MockMessage))
        s.commit()

    return app


app = create_app()
