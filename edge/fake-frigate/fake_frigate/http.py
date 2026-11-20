"""Frigate-shaped HTTP endpoints used by the agent (M0 stub)."""

from fastapi import FastAPI

FRIGATE_VERSION = "0.16.0-fake"


def create_app() -> FastAPI:
    app = FastAPI(title="fake-frigate")

    @app.get("/api/version")
    def version() -> str:
        return FRIGATE_VERSION

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
