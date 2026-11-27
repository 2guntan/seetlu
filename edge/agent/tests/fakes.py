"""In-memory stand-ins for the Seetlu API and Frigate used by agent tests."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi.testclient import TestClient

from fake_frigate.http import create_app as frigate_app
from fake_frigate.publisher import STATE


def fake_frigate() -> TestClient:
    STATE.sim_now = None
    return TestClient(frigate_app())


@dataclass
class FakeCloud:
    """Implements the /v1/edge/* contract closely enough for the agent (the real one is tested in backend)."""

    config: dict[str, Any]
    claimed: bool = True
    token: str = "kit-1.secret"
    events: dict[str, dict[str, Any]] = field(default_factory=dict)
    heartbeats: list[dict[str, Any]] = field(default_factory=list)
    commands: list[dict[str, Any]] = field(default_factory=list)
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    uploads: dict[str, bytes] = field(default_factory=dict)
    fail_events: int = 0
    calls: list[str] = field(default_factory=list)
    streams: dict[str, dict[str, Any]] = field(default_factory=dict)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(f"{request.method} {path}")
        if request.method == "PUT" and path.startswith("/bucket/"):
            self.uploads[path] = request.content
            return httpx.Response(200)
        if path == "/v1/edge/register":
            body = json.loads(request.content)
            if not self.claimed or body["claim_token"] != "dev-claim-token":
                return httpx.Response(403, json={"type": "not-claimed"})
            return httpx.Response(200, json={"kit_id": "kit-1", "device_token": self.token})
        if request.headers.get("Authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"type": "invalid-device-token"})
        if path == "/v1/edge/config":
            etag = f'"{self.config["config_version"]}"'
            if request.headers.get("If-None-Match") == etag:
                return httpx.Response(304)
            return httpx.Response(200, json=self.config, headers={"ETag": etag})
        if path == "/v1/edge/events":
            if self.fail_events > 0:
                self.fail_events -= 1
                return httpx.Response(503)
            batch = json.loads(request.content)["events"]
            assert len(batch) <= 500
            dup = sum(1 for e in batch if e["id"] in self.events)
            for e in batch:
                self.events[e["id"]] = e
            return httpx.Response(200, json={"accepted": len(batch) - dup, "duplicates": dup})
        if request.method == "PUT" and path.startswith("/v1/edge/streams/"):
            self.streams[path.rsplit("/", 1)[1]] = json.loads(request.content)
            return httpx.Response(204)
        if path == "/v1/edge/heartbeat":
            self.heartbeats.append(json.loads(request.content))
            return httpx.Response(204)
        if path == "/v1/edge/commands":
            pending = [c for c in self.commands if c["id"] not in self.results]
            return httpx.Response(200, json=pending)
        if path.startswith("/v1/edge/commands/") and path.endswith("/result"):
            self.results[path.split("/")[4]] = json.loads(request.content)
            return httpx.Response(204)
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(base_url="http://api.test", transport=httpx.MockTransport(self.handler))


def copy_runner(calls: list[list[str]]) -> Callable[[list[str]], None]:
    """ffmpeg stand-in: copies input to output (the real transcode is covered when ffmpeg works)."""

    def run(argv: list[str]) -> None:
        calls.append(argv)
        if argv and argv[0] == "ffmpeg":
            src = argv[argv.index("-i") + 1]
            with open(src, "rb") as f, open(argv[-1], "wb") as g:
                g.write(f.read())

    return run
