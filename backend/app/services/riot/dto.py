from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from app.core.errors import ApiError


class RiotDto(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class AccountDto(RiotDto):
    puuid: str
    game_name: str = Field(alias="gameName")
    tag_line: str = Field(alias="tagLine")


class SummonerDto(RiotDto):
    id: str
    account_id: str = Field(alias="accountId")
    puuid: str
    profile_icon_id: int = Field(alias="profileIconId")
    summoner_level: int = Field(alias="summonerLevel")
    revision_date: int | None = Field(default=None, alias="revisionDate")


class MatchMetadataDto(RiotDto):
    match_id: str = Field(alias="matchId")
    participants: tuple[str, ...] = ()


class ParticipantDto(RiotDto):
    puuid: str
    team_id: int = Field(alias="teamId")
    champion_id: int = Field(alias="championId")
    win: bool
    team_position: str | None = Field(default=None, alias="teamPosition")
    kills: int | None = None
    deaths: int | None = None
    assists: int | None = None
    gold_earned: int | None = Field(default=None, alias="goldEarned")
    total_damage_dealt_to_champions: int | None = Field(
        default=None, alias="totalDamageDealtToChampions"
    )
    vision_score: int | None = Field(default=None, alias="visionScore")
    total_minions_killed: int | None = Field(default=None, alias="totalMinionsKilled")
    neutral_minions_killed: int | None = Field(default=None, alias="neutralMinionsKilled")
    item0: int | None = None
    item1: int | None = None
    item2: int | None = None
    item3: int | None = None
    item4: int | None = None
    item5: int | None = None
    item6: int | None = None


class MatchInfoDto(RiotDto):
    game_creation: int = Field(alias="gameCreation")
    game_duration: int = Field(alias="gameDuration")
    game_version: str = Field(alias="gameVersion")
    queue_id: int = Field(alias="queueId")
    participants: tuple[ParticipantDto, ...]


class MatchDto(RiotDto):
    metadata: MatchMetadataDto
    info: MatchInfoDto


RiotModel = TypeVar("RiotModel", bound=BaseModel)
_MATCH_ID_ADAPTER = TypeAdapter(list[str], config=ConfigDict(strict=True))


def _invalid_response() -> ApiError:
    return ApiError(
        status_code=502,
        code="RIOT_INVALID_RESPONSE",
        message="Riot returned an invalid response.",
        retryable=False,
    )


def validate_riot_model(model_type: type[RiotModel], payload: object) -> RiotModel:
    try:
        return model_type.model_validate(payload)
    except ValidationError:
        raise _invalid_response() from None


def validate_match_ids(payload: object, *, max_count: int) -> tuple[str, ...]:
    try:
        match_ids = _MATCH_ID_ADAPTER.validate_python(payload)
    except ValidationError:
        raise _invalid_response() from None
    if len(match_ids) > max_count:
        raise _invalid_response() from None
    return tuple(match_ids)
