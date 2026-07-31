from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.core.routing import Platform


class Locale(StrEnum):
    ZH_CN = "zh-CN"
    EN_US = "en-US"


class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RiotAccount(DomainModel):
    puuid: str
    game_name: str
    tag_line: str


class PlayerProfile(RiotAccount):
    platform: Platform
    summoner_level: int
    profile_icon_id: int


class StaticAsset(DomainModel):
    entity_id: int
    name: str
    image_url: str


class StaticDataStatus(DomainModel):
    available: bool
    version: str | None
    code: str | None


class PlayerView(PlayerProfile):
    profile_icon: StaticAsset | None
    profile_static_data_status: StaticDataStatus


class ParticipantSnapshot(DomainModel):
    puuid: str
    team_id: int
    champion_id: int
    role: str | None
    won: bool
    kills: int | None
    deaths: int | None
    assists: int | None
    cs: int | None
    gold_earned: int | None
    damage_to_champions: int | None
    vision_score: int | None
    item_ids: tuple[int, ...]


class MatchSnapshot(DomainModel):
    match_id: str
    platform: Platform
    queue_id: int
    game_version: str
    started_at: datetime
    duration_seconds: int
    participants: tuple[ParticipantSnapshot, ...]
