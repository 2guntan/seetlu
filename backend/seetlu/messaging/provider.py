"""MessagingProvider interface (docs/07) and the MockProvider used in dev and tests.

The WhatsApp Cloud API client arrives in M7; until then `MESSAGING_PROVIDER` must be `mock`.
"""

from typing import Protocol

from sqlalchemy.orm import Session

from seetlu.core.config import get_settings
from seetlu.db.models import MockMessage


class MessagingProvider(Protocol):
    def send_template(
        self, to: str, template: str, lang: str, params: list[str], buttons: list[str] | None = None
    ) -> str: ...

    def send_text(self, to: str, text: str) -> str: ...

    def send_media_link(self, to: str, url: str, caption: str) -> str: ...


class MockProvider:
    """Stores every outbound message in `mock_messages` (same transaction as the caller)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _store(self, msg: MockMessage) -> str:
        self.session.add(msg)
        self.session.flush()
        return f"mock-{msg.id}"

    def send_template(
        self, to: str, template: str, lang: str, params: list[str], buttons: list[str] | None = None
    ) -> str:
        return self._store(
            MockMessage(to_phone=to, kind="template", template=template, lang=lang, params=params,
                        buttons=buttons or [])
        )  # fmt: skip

    def send_text(self, to: str, text: str) -> str:
        return self._store(MockMessage(to_phone=to, kind="text", body=text))

    def send_media_link(self, to: str, url: str, caption: str) -> str:
        return self._store(MockMessage(to_phone=to, kind="media", url=url, body=caption))


def get_provider(session: Session) -> MessagingProvider:
    name = get_settings().messaging_provider
    if name == "mock":
        return MockProvider(session)
    raise RuntimeError(f"messaging provider {name!r} is not available yet (WhatsApp Cloud lands in M7)")
