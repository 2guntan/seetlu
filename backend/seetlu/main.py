"""FastAPI application entry point."""

from fastapi import FastAPI

from seetlu import __version__


def create_app() -> FastAPI:
    app = FastAPI(title="Seetlu API", version=__version__)

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
