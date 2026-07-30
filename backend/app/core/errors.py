from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

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
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.params = params or {}
        self.retryable = retryable


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):
        raise exc
    request_id = request.scope["state"]["request_id"]
    response = ErrorResponse(
        error=ErrorDetail(
            code=exc.code,
            message=exc.message,
            params=exc.params,
            retryable=exc.retryable,
            request_id=request_id,
        )
    )
    return JSONResponse(status_code=exc.status_code, content=response.model_dump())
