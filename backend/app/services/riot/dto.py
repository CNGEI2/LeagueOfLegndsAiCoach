from typing import Annotated, Any, Self, TypeVar

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from app.core.errors import ApiError

_SUPPORTED_TIMELINE_EVENT_TYPES = frozenset(
    {
        "CHAMPION_KILL",
        "ELITE_MONSTER_KILL",
        "BUILDING_KILL",
        "ITEM_PURCHASED",
        "ITEM_SOLD",
        "ITEM_DESTROYED",
        "ITEM_UNDO",
    }
)

_EVENT_FIELD_ALLOWLIST: dict[str, frozenset[str]] = {
    "CHAMPION_KILL": frozenset(
        {"type", "timestamp", "killerId", "victimId", "assistingParticipantIds", "position"}
    ),
    "ELITE_MONSTER_KILL": frozenset(
        {
            "type",
            "timestamp",
            "killerId",
            "killerTeamId",
            "monsterType",
            "monsterSubType",
            "position",
        }
    ),
    "BUILDING_KILL": frozenset(
        {
            "type",
            "timestamp",
            "killerId",
            "teamId",
            "buildingType",
            "laneType",
            "towerType",
            "position",
        }
    ),
    "ITEM_PURCHASED": frozenset({"type", "timestamp", "participantId", "itemId"}),
    "ITEM_SOLD": frozenset({"type", "timestamp", "participantId", "itemId"}),
    "ITEM_DESTROYED": frozenset({"type", "timestamp", "participantId", "itemId"}),
    "ITEM_UNDO": frozenset({"type", "timestamp", "participantId", "beforeId", "afterId"}),
}


def _parse_strict_timeline_int(value: object) -> int:
    if isinstance(value, bool) or type(value) is not int:
        raise ValueError("expected a strict integer")
    return value


StrictTimelineInt = Annotated[int, BeforeValidator(_parse_strict_timeline_int)]


class RiotDto(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class AccountDto(RiotDto):
    puuid: str
    game_name: str = Field(alias="gameName")
    tag_line: str = Field(alias="tagLine")


class SummonerDto(RiotDto):
    id: str | None = None
    account_id: str | None = Field(default=None, alias="accountId")
    puuid: str
    profile_icon_id: int = Field(alias="profileIconId")
    summoner_level: int = Field(alias="summonerLevel")
    revision_date: int = Field(alias="revisionDate")


class MatchMetadataDto(RiotDto):
    match_id: str = Field(alias="matchId")
    participants: tuple[str, ...]


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


class TimelinePositionDto(RiotDto):
    x: StrictTimelineInt = Field(ge=0)
    y: StrictTimelineInt = Field(ge=0)


class TimelineParticipantFrameDto(RiotDto):
    participant_id: StrictTimelineInt = Field(alias="participantId", ge=1)
    level: StrictTimelineInt = Field(ge=0)
    current_gold: StrictTimelineInt = Field(alias="currentGold", ge=0)
    total_gold: StrictTimelineInt = Field(alias="totalGold", ge=0)
    minions_killed: StrictTimelineInt = Field(alias="minionsKilled", ge=0)
    jungle_minions_killed: StrictTimelineInt = Field(alias="jungleMinionsKilled", ge=0)
    xp: StrictTimelineInt = Field(ge=0)
    position: TimelinePositionDto | None = None


class TimelineEventDto(RiotDto):
    type: str
    timestamp: StrictTimelineInt = Field(ge=0)
    killer_id: StrictTimelineInt | None = Field(default=None, alias="killerId")
    victim_id: StrictTimelineInt | None = Field(default=None, alias="victimId")
    assisting_participant_ids: tuple[StrictTimelineInt, ...] | None = Field(
        default=None, alias="assistingParticipantIds"
    )
    killer_team_id: StrictTimelineInt | None = Field(default=None, alias="killerTeamId", ge=0)
    monster_type: str | None = Field(default=None, alias="monsterType")
    monster_sub_type: str | None = Field(default=None, alias="monsterSubType")
    team_id: StrictTimelineInt | None = Field(default=None, alias="teamId", ge=0)
    building_type: str | None = Field(default=None, alias="buildingType")
    lane_type: str | None = Field(default=None, alias="laneType")
    tower_type: str | None = Field(default=None, alias="towerType")
    participant_id: StrictTimelineInt | None = Field(default=None, alias="participantId")
    item_id: StrictTimelineInt | None = Field(default=None, alias="itemId", ge=0)
    before_id: StrictTimelineInt | None = Field(default=None, alias="beforeId", ge=0)
    after_id: StrictTimelineInt | None = Field(default=None, alias="afterId", ge=0)
    position: TimelinePositionDto | None = None

    @model_validator(mode="after")
    def validate_known_event_fields(self) -> Self:
        event_type = self.type
        if event_type not in _SUPPORTED_TIMELINE_EVENT_TYPES:
            return self
        if event_type == "CHAMPION_KILL":
            if self.killer_id is None or self.killer_id < 0:
                raise ValueError("champion kill requires killerId")
            if self.victim_id is None or self.victim_id < 1:
                raise ValueError("champion kill requires victimId")
        elif event_type == "ELITE_MONSTER_KILL":
            if self.killer_id is None or self.killer_id < 0:
                raise ValueError("elite monster kill requires killerId")
            if self.killer_team_id is None:
                raise ValueError("elite monster kill requires killerTeamId")
            if self.monster_type is None:
                raise ValueError("elite monster kill requires monsterType")
        elif event_type == "BUILDING_KILL":
            if self.killer_id is None or self.killer_id < 0:
                raise ValueError("building kill requires killerId")
            if self.team_id is None:
                raise ValueError("building kill requires teamId")
            if self.building_type is None:
                raise ValueError("building kill requires buildingType")
        elif event_type in {"ITEM_PURCHASED", "ITEM_SOLD", "ITEM_DESTROYED"}:
            if self.participant_id is None or self.participant_id < 1:
                raise ValueError("item event requires participantId")
            if self.item_id is None:
                raise ValueError("item event requires itemId")
        elif event_type == "ITEM_UNDO":
            if self.participant_id is None or self.participant_id < 1:
                raise ValueError("item undo requires participantId")
            if self.before_id is None or self.after_id is None:
                raise ValueError("item undo requires beforeId and afterId")
            if self.before_id < 0 or self.after_id < 0:
                raise ValueError("item undo ids must be non-negative")
        return self


class TimelineFrameDto(RiotDto):
    timestamp: StrictTimelineInt = Field(ge=0)
    participant_frames: dict[int, TimelineParticipantFrameDto] = Field(alias="participantFrames")
    events: tuple[TimelineEventDto, ...]


class TimelineInfoDto(RiotDto):
    frame_interval: StrictTimelineInt = Field(alias="frameInterval", ge=1_000, le=120_000)
    frames: tuple[TimelineFrameDto, ...]


class TimelineMetadataDto(RiotDto):
    match_id: str = Field(alias="matchId", min_length=1)
    participants: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_identity_strings(self) -> Self:
        if self.match_id.strip() == "":
            raise ValueError("matchId must not be blank")
        if len(self.participants) == 0:
            raise ValueError("participants must not be empty")
        for participant in self.participants:
            if participant.strip() == "":
                raise ValueError("participant identity must not be blank")
        return self


class TimelineDto(RiotDto):
    metadata: TimelineMetadataDto
    info: TimelineInfoDto


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


def validate_timeline_payload(payload: object, *, match_id: str) -> TimelineDto:
    try:
        prepared = _prepare_timeline_payload(payload)
        timeline = TimelineDto.model_validate(prepared)
        _assert_timeline_invariants(timeline, match_id=match_id)
    except (ValidationError, TypeError, ValueError, KeyError):
        raise _invalid_response() from None
    return timeline


def _prepare_timeline_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("timeline payload must be an object")
    metadata = payload.get("metadata")
    info = payload.get("info")
    if not isinstance(metadata, dict) or not isinstance(info, dict):
        raise TypeError("timeline metadata and info are required")
    frames = info.get("frames")
    if not isinstance(frames, list):
        raise TypeError("timeline frames must be an array")
    prepared_frames: list[dict[str, Any]] = []
    for frame in frames:
        if not isinstance(frame, dict):
            raise TypeError("timeline frame must be an object")
        prepared_frame = dict(frame)
        prepared_frame["participantFrames"] = _convert_participant_frames(
            frame.get("participantFrames")
        )
        prepared_frame["events"] = _prepare_timeline_events(frame.get("events"))
        prepared_frames.append(prepared_frame)
    prepared_info = dict(info)
    prepared_info["frames"] = prepared_frames
    return {"metadata": metadata, "info": prepared_info}


def _prepare_timeline_events(raw_events: object) -> list[dict[str, Any]]:
    if not isinstance(raw_events, list):
        raise TypeError("timeline events must be an array")
    prepared: list[dict[str, Any]] = []
    for event in raw_events:
        if not isinstance(event, dict):
            raise TypeError("timeline event must be an object")
        event_type = event.get("type")
        if not isinstance(event_type, str):
            raise TypeError("timeline event type must be a string")
        if event_type not in _SUPPORTED_TIMELINE_EVENT_TYPES:
            prepared.append({"type": event_type, "timestamp": event.get("timestamp")})
            continue
        allowed = _EVENT_FIELD_ALLOWLIST[event_type]
        prepared.append({key: value for key, value in event.items() if key in allowed})
    return prepared


def _convert_participant_frames(raw_frames: object) -> dict[int, Any]:
    if not isinstance(raw_frames, dict):
        raise TypeError("participantFrames must be an object")
    converted: dict[int, Any] = {}
    for key, value in raw_frames.items():
        participant_id = _parse_participant_frame_key(key)
        if participant_id in converted:
            raise ValueError("duplicate participant frame key")
        converted[participant_id] = value
    return converted


def _parse_participant_frame_key(key: object) -> int:
    if isinstance(key, bool) or key is None:
        raise ValueError("participant frame key must be a decimal participant id")
    if isinstance(key, int):
        if key < 1:
            raise ValueError("participant frame key must be positive")
        return key
    if isinstance(key, str):
        if not key.isdigit():
            raise ValueError("participant frame key must be a decimal participant id")
        parsed = int(key)
        if parsed < 1 or str(parsed) != key:
            raise ValueError("participant frame key must be a decimal participant id")
        return parsed
    raise ValueError("participant frame key must be a decimal participant id")


def _assert_timeline_invariants(timeline: TimelineDto, *, match_id: str) -> None:
    if timeline.metadata.match_id != match_id:
        raise ValueError("timeline identity mismatch")
    participants = timeline.metadata.participants
    if len(participants) != len(set(participants)):
        raise ValueError("timeline participants must be unique")
    known_ids = set(range(1, len(participants) + 1))
    previous_timestamp = 0
    for index, frame in enumerate(timeline.info.frames):
        if index == 0:
            previous_timestamp = frame.timestamp
        elif frame.timestamp < previous_timestamp:
            raise ValueError("frame timestamps must be monotonically non-decreasing")
        else:
            previous_timestamp = frame.timestamp
        for participant_id, participant_frame in frame.participant_frames.items():
            if participant_id not in known_ids:
                raise ValueError("participant frame references unknown participant")
            if participant_frame.participant_id != participant_id:
                raise ValueError("participant frame id must match map key")
        for event in frame.events:
            _assert_event_participant_refs(event, known_ids=known_ids)


def _assert_event_participant_refs(event: TimelineEventDto, *, known_ids: set[int]) -> None:
    if event.type not in _SUPPORTED_TIMELINE_EVENT_TYPES:
        return
    if event.killer_id is not None and event.killer_id != 0 and event.killer_id not in known_ids:
        raise ValueError("event killerId references unknown participant")
    if event.victim_id is not None and event.victim_id not in known_ids:
        raise ValueError("event victimId references unknown participant")
    if event.participant_id is not None and event.participant_id not in known_ids:
        raise ValueError("event participantId references unknown participant")
    if event.assisting_participant_ids is not None:
        if len(event.assisting_participant_ids) != len(set(event.assisting_participant_ids)):
            raise ValueError("assistingParticipantIds must be unique")
        for assistant_id in event.assisting_participant_ids:
            if assistant_id not in known_ids:
                raise ValueError("assistant references unknown participant")
