from datetime import datetime
from typing import Literal

from pydantic import model_validator

from app.core.routing import Platform
from app.schemas.domain import (
    DomainModel,
    ParticipantSnapshot,
    PlayerView,
    StaticAsset,
    StaticDataStatus,
)


class HydratedParticipant(ParticipantSnapshot):
    champion: StaticAsset | None
    items: tuple[StaticAsset | None, ...]

    @model_validator(mode="after")
    def item_assets_align_with_item_ids(self) -> "HydratedParticipant":
        if len(self.items) != len(self.item_ids):
            raise ValueError("items must align with item_ids")
        return self


class RecentMatchItem(DomainModel):
    match_id: str
    platform: Platform
    queue_id: int
    started_at: datetime
    duration_seconds: int
    game_version: str
    participant: HydratedParticipant
    analysis_supported: bool
    unsupported_reason_code: str | None
    detail_supported: bool
    detail_unavailable_reason_code: str | None
    static_data_status: StaticDataStatus


class RecentMatchesData(DomainModel):
    player: PlayerView
    matches: tuple[RecentMatchItem, ...]


class RecentMatchesResponse(RecentMatchesData):
    request_id: str


class MatchDetailData(DomainModel):
    match_id: str
    platform: Platform
    queue_id: int
    started_at: datetime
    duration_seconds: int
    game_version: str
    selected_puuid: str
    blue_team: tuple[HydratedParticipant, ...]
    red_team: tuple[HydratedParticipant, ...]
    static_data_status: StaticDataStatus
    scope_notice_code: Literal["DATA_ONLY_NO_COACHING"] = "DATA_ONLY_NO_COACHING"


class MatchDetailResponse(MatchDetailData):
    request_id: str
