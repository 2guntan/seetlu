"""Seetlu cloud API client for the kit (docs/04 /v1/edge/*). Device token auth, ETag config polling."""

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from seetlu_agent.edge_config import EdgeConfig

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status


class Api:
    def __init__(self, base_url: str, state_path: Path, client: httpx.Client | None = None) -> None:
        self.http = client or httpx.Client(base_url=base_url, timeout=30)
        self.state_path = state_path
        self.state: dict[str, Any] = {}
        if state_path.exists():
            self.state = json.loads(state_path.read_text())
        self.etag: str | None = None

    @property
    def token(self) -> str | None:
        t = self.state.get("device_token")
        return str(t) if t else None

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state))
        tmp.chmod(0o600)
        tmp.replace(self.state_path)

    def forget_token(self) -> None:
        self.state.pop("device_token", None)
        self._save()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _check(self, r: httpx.Response) -> httpx.Response:
        if r.status_code == 401 and self.token and r.request.url.path != "/v1/edge/register":
            # the device token was rotated (re-registration elsewhere): forget it, register again
            self.forget_token()
        if r.status_code >= 400:
            raise ApiError(r.status_code, r.text)
        return r

    def register(self, serial: str, claim_token: str, agent_version: str) -> str:
        r = self._check(
            self.http.post(
                "/v1/edge/register",
                json={"serial": serial, "claim_token": claim_token, "agent_version": agent_version},
            )
        )
        body = r.json()
        self.state.update(kit_id=body["kit_id"], device_token=body["device_token"])
        self._save()
        return str(body["kit_id"])

    def config(self) -> EdgeConfig | None:
        """None when unchanged (304)."""
        headers = self._headers() | ({"If-None-Match": self.etag} if self.etag else {})
        r = self.http.get("/v1/edge/config", headers=headers)
        if r.status_code == 304:
            return None
        self._check(r)
        self.etag = r.headers.get("ETag")
        return EdgeConfig.model_validate(r.json())

    def post_events(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        r = self._check(self.http.post("/v1/edge/events", json={"events": events}, headers=self._headers()))
        out: dict[str, Any] = r.json()
        return out

    def heartbeat(self, body: dict[str, Any]) -> None:
        self._check(self.http.post("/v1/edge/heartbeat", json=body, headers=self._headers()))

    def put_stream(self, camera: str, report: dict[str, Any]) -> None:
        """AC-F8-7: stream check of one camera slot; `source` carries no credentials."""
        self._check(self.http.put(f"/v1/edge/streams/{camera}", json=report, headers=self._headers()))

    def commands(self) -> list[dict[str, Any]]:
        r = self._check(self.http.get("/v1/edge/commands", headers=self._headers()))
        out: list[dict[str, Any]] = r.json()
        return out

    def command_result(self, command_id: str, status: str, result: dict[str, Any]) -> None:
        self._check(
            self.http.post(
                f"/v1/edge/commands/{command_id}/result",
                json={"status": status, "result": result},
                headers=self._headers(),
            )
        )
