from typing import Any

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    params: dict[str, Any]
    retryable: bool
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
