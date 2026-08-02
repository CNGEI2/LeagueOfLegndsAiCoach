from typing import Any

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.schemas.errors import ErrorDetail, ErrorResponse


class ApiError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        params: dict[str, Any] | None = None,
        retryable: bool,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.params = params or {}
        self.retryable = retryable
        self.headers = headers or {}


def replay_not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code="REPLAY_NOT_FOUND",
        message="The requested replay was not found.",
        retryable=False,
    )


def replay_too_large() -> ApiError:
    return ApiError(
        status_code=413,
        code="REPLAY_TOO_LARGE",
        message="The uploaded replay exceeds the maximum allowed size.",
        retryable=False,
    )


def replay_rate_limiter_unavailable() -> ApiError:
    return ApiError(
        status_code=503,
        code="REPLAY_RATE_LIMITER_UNAVAILABLE",
        message="Replay gateway rate limiting is temporarily unavailable.",
        retryable=True,
    )


def replay_rate_limited(retry_after_seconds: float | None = None) -> ApiError:
    params: dict[str, Any] = {}
    headers: dict[str, str] = {}
    if retry_after_seconds is not None:
        params["retry_after_seconds"] = round(retry_after_seconds, 3)
        headers["Retry-After"] = str(max(1, round(retry_after_seconds)))
    return ApiError(
        status_code=429,
        code="REPLAY_RATE_LIMITED",
        message="Too many replay requests. Please slow down and try again later.",
        params=params,
        retryable=True,
        headers=headers,
    )


def _error_response(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
    retryable: bool,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    response = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            params=params or {},
            retryable=retryable,
            request_id=request.state.request_id,
        )
    )
    return JSONResponse(status_code=status_code, content=response.model_dump(), headers=headers)


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, ApiError):
        return _error_response(
            request=request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            params=exc.params,
            retryable=exc.retryable,
            headers=exc.headers or None,
        )
    if isinstance(exc, RequestValidationError):
        return _error_response(
            request=request,
            status_code=422,
            code="VALIDATION_ERROR",
            message="Request validation failed.",
            retryable=False,
        )
    if isinstance(exc, StarletteHTTPException):
        if exc.status_code == 404:
            return _error_response(
                request=request,
                status_code=404,
                code="NOT_FOUND",
                message="The requested resource was not found.",
                retryable=False,
            )
        return _error_response(
            request=request,
            status_code=exc.status_code,
            code="HTTP_ERROR",
            message="The request could not be completed.",
            retryable=False,
        )
    return _error_response(
        request=request,
        status_code=500,
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected error occurred.",
        retryable=True,
    )


class UnhandledExceptionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            return await call_next(request)
        except Exception as exc:
            return await api_error_handler(request, exc)
