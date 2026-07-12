from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# Codes for framework-level HTTP errors that are not raised as AppError.
_HTTP_CODE_MAP = {
    400: "BAD_REQUEST",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
}


class AppError(Exception):
    """Domain error rendered through the shared error envelope."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


def _envelope(code: str, message: str, details: dict[str, Any] | None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_envelope(
                "VALIDATION_ERROR",
                "Request validation failed.",
                {"errors": jsonable_encoder(exc.errors())},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODE_MAP.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "HTTP error."
        return JSONResponse(status_code=exc.status_code, content=_envelope(code, message, {}))

    @app.exception_handler(Exception)
    async def _unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
        # Never leak internal stack traces to clients.
        return JSONResponse(
            status_code=500,
            content=_envelope("INTERNAL_ERROR", "Internal server error.", {}),
        )
