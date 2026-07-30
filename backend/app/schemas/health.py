from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["lol-ai-coach-backend"] = "lol-ai-coach-backend"
