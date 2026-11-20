"""FastAPI application entry point."""

from fastapi import FastAPI

from seetlu import __version__
from seetlu.api import auth, shops
from seetlu.core.problem import install_problem_handlers


def create_app() -> FastAPI:
    app = FastAPI(
        title="Seetlu API",
        version=__version__,
        description=(
            "Contract: docs/04-api.openapi.yaml. Errors are RFC 9457 problem+json. Money in integer XOF."
        ),
    )
    install_problem_handlers(app)
    app.include_router(auth.router)
    app.include_router(shops.router)

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
