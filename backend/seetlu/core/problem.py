"""RFC 9457 problem+json errors."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_BASE = "https://seetlu.sn/problems/"
MEDIA_TYPE = "application/problem+json"

TITLES = {
    400: "Bad request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not found",
    405: "Method not allowed",
    409: "Conflict",
    410: "Gone",
    422: "Validation error",
    429: "Too many requests",
}


class Problem(Exception):  # noqa: N818 - named after the RFC object
    def __init__(self, status: int, slug: str, detail: str | None = None, **extra: Any) -> None:
        super().__init__(detail or slug)
        self.status = status
        self.slug = slug
        self.detail = detail
        self.extra = extra


def problem_response(status: int, slug: str, detail: str | None = None, **extra: Any) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"{PROBLEM_BASE}{slug}",
        "title": TITLES.get(status, "Error"),
        "status": status,
    }
    if detail:
        body["detail"] = detail
    body.update(extra)
    return JSONResponse(body, status_code=status, media_type=MEDIA_TYPE)


def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(Problem)
    async def _problem(_: Request, exc: Problem) -> JSONResponse:
        return problem_response(exc.status, exc.slug, exc.detail, **exc.extra)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        slug = TITLES.get(exc.status_code, "error").lower().replace(" ", "-")
        detail = (
            exc.detail if isinstance(exc.detail, str) and exc.detail != TITLES.get(exc.status_code) else None
        )
        resp = problem_response(exc.status_code, slug, detail)
        if exc.headers:
            resp.headers.update(exc.headers)
        return resp

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return problem_response(
            422, "validation-error", "Request body or parameters are invalid", errors=errors
        )
