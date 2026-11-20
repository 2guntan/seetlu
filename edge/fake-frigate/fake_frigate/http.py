"""Frigate-shaped HTTP endpoints used by the agent, plus simulator controls.

Frigate: `GET /api/<camera>/start/<ts>/end/<ts>/clip.mp4`, `GET /api/<camera>/latest.jpg`.
Simulator: `GET /sim/scenarios`, `POST /sim/scenarios/<name>/run?speed=&date=`.
"""

import os
import threading
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from fake_frigate import scenario
from fake_frigate.generator import FRIGATE_VERSION
from fake_frigate.publisher import STATE, run_scenario

MEDIA = Path(__file__).resolve().parent / "media"
CAMERAS = {"door", "counter"}
EDGE_BUFFER_S = 7 * 24 * 3600  # Frigate keeps 7 days of motion recordings (docs/05)


def create_app() -> FastAPI:
    app = FastAPI(title="fake-frigate")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/version")
    def version() -> str:
        return FRIGATE_VERSION

    @app.get("/api/{camera}/latest.jpg")
    def latest(camera: str) -> FileResponse:
        if camera not in CAMERAS:
            raise HTTPException(404, "camera not found")
        return FileResponse(MEDIA / "sample.jpg", media_type="image/jpeg")

    @app.get("/api/{camera}/start/{start}/end/{end}/clip.mp4")
    def clip(camera: str, start: float, end: float) -> FileResponse:
        if camera not in CAMERAS or end <= start:
            raise HTTPException(404, "no recordings")
        now = STATE.sim_now
        if now is not None and start < now - EDGE_BUFFER_S:
            raise HTTPException(404, "no recordings")  # older than the edge buffer (AC-F5-4)
        return FileResponse(MEDIA / "sample.mp4", media_type="video/mp4")

    @app.get("/sim/scenarios")
    def list_scenarios() -> dict[str, object]:
        return {"scenarios": scenario.names(), "running": STATE.running, "sim_now": STATE.sim_now}

    @app.post("/sim/scenarios/{name}/run", status_code=202)
    def run(name: str, speed: float = 600, day: date | None = None) -> dict[str, object]:
        if name not in scenario.names():
            raise HTTPException(404, "unknown scenario")
        if STATE.running:
            raise HTTPException(409, f"{STATE.running} is still running")
        host, port = os.environ.get("MQTT_HOST", "localhost"), int(os.environ.get("MQTT_PORT", "1883"))
        STATE.running = name
        threading.Thread(target=run_scenario, args=(name, host, port, speed, day), daemon=True).start()
        return {"scenario": name, "speed": speed, "date": day.isoformat() if day else None}

    return app
