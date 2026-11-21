"""MessagingProvider interface (docs/07): WhatsApp Cloud API client and the MockProvider used in dev
and tests (`MESSAGING_PROVIDER=mock | whatsapp_cloud`)."""

from typing import Any, Protocol

import httpx
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


class WhatsAppCloudProvider:
    """Meta Graph API `/{phone_number_id}/messages`. Phone numbers are sent without the leading `+`."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        st = get_settings()
        if not (st.wa_phone_number_id and st.wa_access_token):
            raise RuntimeError("WA_PHONE_NUMBER_ID and WA_ACCESS_TOKEN are required for whatsapp_cloud")
        self.url = f"{st.wa_graph_url.rstrip('/')}/{st.wa_phone_number_id}/messages"
        self.client = client or httpx.Client(timeout=10.0)
        self.headers = {"Authorization": f"Bearer {st.wa_access_token}"}

    def _post(self, to: str, body: dict[str, Any]) -> str:
        payload = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to.lstrip("+")}
        r = self.client.post(self.url, json=payload | body, headers=self.headers)
        r.raise_for_status()
        return str(r.json()["messages"][0]["id"])

    def send_template(
        self, to: str, template: str, lang: str, params: list[str], buttons: list[str] | None = None
    ) -> str:
        components: list[dict[str, Any]] = [
            {"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}
        ]
        for i, b in enumerate(buttons or []):
            components.append(
                {
                    "type": "button",
                    "sub_type": "url",
                    "index": str(i),
                    "parameters": [{"type": "text", "text": b}],
                }
            )
        template_body = {"name": template, "language": {"code": lang}, "components": components}
        return self._post(to, {"type": "template", "template": template_body})

    def send_text(self, to: str, text: str) -> str:
        return self._post(to, {"type": "text", "text": {"body": text, "preview_url": True}})

    def send_media_link(self, to: str, url: str, caption: str) -> str:
        return self._post(to, {"type": "image", "image": {"link": url, "caption": caption}})


def get_provider(session: Session) -> MessagingProvider:
    name = get_settings().messaging_provider
    if name == "mock":
        return MockProvider(session)
    if name == "whatsapp_cloud":
        return WhatsAppCloudProvider()
    raise RuntimeError(f"unknown messaging provider {name!r} (mock | whatsapp_cloud)")
