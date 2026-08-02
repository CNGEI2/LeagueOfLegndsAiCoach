from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from app.core.routing import Platform
from app.schemas.domain import DomainModel, Locale, PlayerView


class DetectPlayerRequest(DomainModel):
    riot_id: str
    locale: Locale


class ConfirmPlatformRequest(DomainModel):
    platform: Platform
    locale: Locale


class PlatformCandidate(DomainModel):
    platform: Platform
    display_name: str = Field(min_length=1)


class ResolvedDetectionResponse(DomainModel):
    status: Literal["resolved"]
    player: PlayerView
    request_id: str


class ConfirmationRequiredResponse(DomainModel):
    status: Literal["confirmation_required"]
    detection_id: UUID
    expires_at: AwareDatetime
    candidates: tuple[PlatformCandidate, ...] = Field(min_length=1)
    request_id: str


DetectPlayerResponse = Annotated[
    ResolvedDetectionResponse | ConfirmationRequiredResponse,
    Field(discriminator="status"),
]
