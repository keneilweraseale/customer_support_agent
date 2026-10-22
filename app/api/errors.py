import logging
from collections.abc import Mapping
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


def _error_response(
    status_code: int,
    code: str,
    message: str,
    headers: Mapping[str, str] | None = None,
    details: list[dict[str, Any]] | None = None,
    request_id: str | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    response_headers = dict(headers or {})
    if request_id is not None:
        error["request_id"] = request_id
        response_headers["X-Request-ID"] = request_id

    return JSONResponse(
        status_code=status_code,
        content={"error": error},
        headers=response_headers,
    )


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    code = {
        404: "not_found",
        401: "unauthorized",
        405: "method_not_allowed",
        409: "conflict",
        503: "service_unavailable",
    }.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return _error_response(
        exc.status_code,
        code,
        message,
        exc.headers,
        request_id=getattr(request.state, "request_id", None),
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    details = [
        {
            "location": list(error["loc"]),
            "type": error["type"],
        }
        for error in exc.errors()
    ]
    return _error_response(
        422,
        "validation_error",
        "Request validation failed.",
        details=details,
        request_id=getattr(request.state, "request_id", None),
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.error(
        "Unhandled API exception for %s %s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return _error_response(
        500,
        "internal_server_error",
        "An unexpected error occurred.",
        request_id=getattr(request.state, "request_id", None),
    )
