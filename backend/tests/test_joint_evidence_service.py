from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from app.core.errors import ApiError
from app.core.metrics import MetricsRegistry
from app.core.routing import Platform
from app.schemas.domain import Locale, MatchSnapshot, ParticipantSnapshot, StaticDataStatus
from app.schemas.evidence import JointEvidenceRequest
from app.services.evidence.domain import (
    EvidenceArtifactReference,
    EvidenceWindowPlan,
    LinkedEvidenceWindow,
    PlannedEvidenceWindow,
)
from app.services.evidence.service import DisabledJointEvidenceService, JointEvidenceService
from app.services.evidence.windows import EvidenceWindowPlanner
from app.services.replays.domain import ReplayArtifactKind
from app.services.static_data.resolver import EvidenceItem, EvidenceItemCatalog
from app.services.timelines.domain import (
    ChampionKillFact,
    ItemEventFact,
    TimelinePosition,
    TimelineSnapshot,
)
from app.services.timelines.service import TimelineLoadResult

NOW = datetime(2026, 8, 2, tzinfo=UTC)
PUUID = "selected-player-puuid"
MATCH_ID = "NA1_fixture"
REPLAY_ID = uuid4()


def _participant(puuid: str, team_id: int = 100) -> ParticipantSnapshot:
    return ParticipantSnapshot(
        puuid=puuid,
        team_id=team_id,
        champion_id=103,
        role="MIDDLE",
        won=True,
        kills=1,
        deaths=0,
        assists=0,
        cs=10,
        gold_earned=1000,
        damage_to_champions=1000,
        vision_score=1,
        item_ids=(1055,),
    )


def _match(*, queue_id: int = 420) -> MatchSnapshot:
    return MatchSnapshot(
        match_id=MATCH_ID,
        platform=Platform.NA1,
        queue_id=queue_id,
        game_version="16.15.602.1234",
        started_at=NOW,
        duration_seconds=1800,
        participants=(
            _participant(PUUID, 100),
            _participant("ally-2", 100),
            _participant("enemy-6", 200),
        ),
    )


def _kill_fact() -> ChampionKillFact:
    return ChampionKillFact(
        fact_id="timeline:NA1:NA1_fixture:v1:frame:1:event:0",
        kind="champion_kill",
        timestamp_ms=60_000,
        frame_index=1,
        event_index=0,
        killer_id=1,
        victim_id=3,
        assisting_participant_ids=(2,),
        position=TimelinePosition(x=1, y=1),
    )


def _item_fact() -> ItemEventFact:
    return ItemEventFact(
        fact_id="timeline:NA1:NA1_fixture:v1:frame:1:event:1",
        kind="item_purchased",
        timestamp_ms=61_000,
        frame_index=1,
        event_index=1,
        participant_id=1,
        item_id=1055,
    )


def _timeline(*, facts: tuple[Any, ...] | None = None) -> TimelineSnapshot:
    return TimelineSnapshot(
        platform=Platform.NA1,
        match_id=MATCH_ID,
        schema_version=1,
        frame_interval_ms=60_000,
        participant_puuids={1: PUUID, 2: "ally-2", 3: "enemy-6"},
        facts=facts if facts is not None else (_kill_fact(), _item_fact()),
    )


@dataclass
class FakeMatchService:
    snapshot: MatchSnapshot = field(default_factory=_match)
    error: ApiError | None = None
    calls: list[dict[str, object]] = field(default_factory=list)

    async def get_evidence_context(
        self, *, platform: Platform, match_id: str, puuid: str
    ) -> MatchSnapshot:
        self.calls.append({"platform": platform, "match_id": match_id, "puuid": puuid})
        if self.error is not None:
            raise self.error
        return self.snapshot


@dataclass
class FakeTimelineService:
    result: TimelineLoadResult = field(
        default_factory=lambda: TimelineLoadResult(snapshot=_timeline(), cache_status="miss")
    )
    error: ApiError | None = None
    calls: int = 0

    async def get_timeline(self, *, platform: Platform, match_id: str) -> TimelineLoadResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


@dataclass
class FakeStaticResolver:
    available: bool = True
    calls: list[dict[str, object]] = field(default_factory=list)

    async def hydrate_evidence_items(
        self, *, game_version: str, item_ids: tuple[int, ...], locale: Locale
    ) -> EvidenceItemCatalog:
        self.calls.append({"game_version": game_version, "item_ids": item_ids, "locale": locale})
        items = tuple(
            EvidenceItem(
                item_id=item_id,
                name=f"Item {item_id}" if self.available else None,
                image_url=(
                    f"https://ddragon.leagueoflegends.com/cdn/16.15.2/img/item/{item_id}.png"
                    if self.available
                    else None
                ),
            )
            for item_id in item_ids
        )
        return EvidenceItemCatalog(
            items=items,
            static_data_status=StaticDataStatus(
                available=self.available,
                version="16.15.2" if self.available else None,
                code=None if self.available else "STATIC_DATA_UNAVAILABLE",
            ),
        )


@dataclass
class FakeLinker:
    linked: tuple[LinkedEvidenceWindow, ...] = ()
    error: ApiError | None = None
    calls: list[dict[str, object]] = field(default_factory=list)

    async def link(self, **kwargs: object) -> tuple[LinkedEvidenceWindow, ...]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        windows = kwargs["windows"]
        assert isinstance(windows, tuple)
        if self.linked:
            return self.linked
        return tuple(
            LinkedEvidenceWindow(
                window=window,  # type: ignore[arg-type]
                coverage="unavailable",
                covered_game_start_ms=None,
                covered_game_end_ms=None,
                video_start_ms=None,
                video_end_ms=None,
                artifacts=(),
            )
            for window in windows
        )


def _service(
    *,
    match: FakeMatchService | None = None,
    timeline: FakeTimelineService | None = None,
    static: FakeStaticResolver | None = None,
    linker: FakeLinker | None = None,
    metrics: MetricsRegistry | None = None,
) -> tuple[
    JointEvidenceService,
    FakeMatchService,
    FakeTimelineService,
    FakeStaticResolver,
    FakeLinker,
    MetricsRegistry,
]:
    match_service = match or FakeMatchService()
    timeline_service = timeline or FakeTimelineService()
    static_resolver = static or FakeStaticResolver()
    replay_linker = linker or FakeLinker()
    registry = metrics or MetricsRegistry()
    service = JointEvidenceService(
        match_service=match_service,
        timeline_service=timeline_service,
        planner=EvidenceWindowPlanner(),
        replay_linker=replay_linker,
        static_resolver=static_resolver,
        metrics=registry,
    )
    return service, match_service, timeline_service, static_resolver, replay_linker, registry


@pytest.mark.asyncio
async def test_prepare_timeline_only_ready_response() -> None:
    service, match_service, timeline_service, static, linker, _ = _service()
    request = JointEvidenceRequest(platform=Platform.NA1, puuid=PUUID, locale=Locale.ZH_CN)
    data = await service.prepare(match_id=MATCH_ID, request=request, replay_token=None)
    assert data.status == "ready"
    assert data.schema_version == 1
    assert data.scope_notice_code == "EVIDENCE_ONLY_NO_COACHING"
    assert data.timeline_cache_status == "miss"
    assert data.replay_link is None
    assert data.locale == Locale.ZH_CN
    assert any(
        fact.kind == "champion_kill" and fact.relationship == "killer" for fact in data.facts
    )
    assert any(
        fact.kind == "item_purchased" and fact.relationship == "actor" for fact in data.facts
    )
    assert PUUID not in data.model_dump_json()
    assert match_service.calls[0]["puuid"] == PUUID
    assert timeline_service.calls == 1
    assert linker.calls[0]["replay_id"] is None
    assert static.calls


@pytest.mark.asyncio
async def test_prepare_propagates_cache_hit_and_empty_facts() -> None:
    empty = TimelineLoadResult(
        snapshot=_timeline(facts=()),
        cache_status="hit",
    )
    service, _, _, _, _, _ = _service(timeline=FakeTimelineService(result=empty))
    data = await service.prepare(
        match_id=MATCH_ID,
        request=JointEvidenceRequest(platform=Platform.NA1, puuid=PUUID),
        replay_token=None,
    )
    assert data.timeline_cache_status == "hit"
    assert data.facts == ()
    assert data.windows == ()
    assert data.truncated is False
    assert data.total_window_count == 0


@pytest.mark.asyncio
async def test_prepare_links_replay_coverage_and_safe_artifacts() -> None:
    planned = PlannedEvidenceWindow(
        window_id="evidence-window:NA1:NA1_fixture:v1:0",
        start_ms=48_000,
        end_ms=68_000,
        categories=("combat_context",),
        trigger_fact_ids=("timeline:NA1:NA1_fixture:v1:frame:1:event:0",),
    )
    artifact_id = uuid4()
    linked = (
        LinkedEvidenceWindow(
            window=planned,
            coverage="full",
            covered_game_start_ms=48_000,
            covered_game_end_ms=68_000,
            video_start_ms=49_000,
            video_end_ms=69_000,
            artifacts=(
                EvidenceArtifactReference(
                    artifact_id=artifact_id,
                    kind=ReplayArtifactKind.VERIFICATION_FRAME,
                    game_time_ms=60_000,
                    video_time_ms=61_000,
                ),
            ),
        ),
        LinkedEvidenceWindow(
            window=PlannedEvidenceWindow(
                window_id="evidence-window:NA1:NA1_fixture:v1:1",
                start_ms=100_000,
                end_ms=120_000,
                categories=("death_context",),
                trigger_fact_ids=("timeline:NA1:NA1_fixture:v1:frame:1:event:9",),
            ),
            coverage="partial",
            covered_game_start_ms=100_000,
            covered_game_end_ms=110_000,
            video_start_ms=101_000,
            video_end_ms=111_000,
            artifacts=(),
        ),
        LinkedEvidenceWindow(
            window=PlannedEvidenceWindow(
                window_id="evidence-window:NA1:NA1_fixture:v1:2",
                start_ms=200_000,
                end_ms=220_000,
                categories=("building_context",),
                trigger_fact_ids=("timeline:NA1:NA1_fixture:v1:frame:1:event:10",),
            ),
            coverage="unavailable",
            covered_game_start_ms=None,
            covered_game_end_ms=None,
            video_start_ms=None,
            video_end_ms=None,
            artifacts=(),
        ),
    )

    class StubPlanner:
        def plan(self, **kwargs: object) -> EvidenceWindowPlan:
            return EvidenceWindowPlan(
                windows=(planned, linked[1].window, linked[2].window),
                truncated=False,
                total_window_count=3,
            )

    service, _, _, _, linker, _ = _service(linker=FakeLinker(linked=linked))
    service._planner = StubPlanner()  # type: ignore[method-assign]
    data = await service.prepare(
        match_id=MATCH_ID,
        request=JointEvidenceRequest(platform=Platform.NA1, puuid=PUUID, replay_id=REPLAY_ID),
        replay_token="capability-token",
    )
    assert data.replay_link is not None
    assert data.replay_link.status == "linked"
    assert data.replay_link.full_count == 1
    assert data.replay_link.partial_count == 1
    assert data.replay_link.unavailable_count == 1
    assert "replay_id" not in data.replay_link.model_dump()
    assert data.windows[0].coverage == "full"
    assert data.windows[0].artifacts[0].artifact_id == artifact_id
    dumped = data.model_dump_json()
    assert "object_key" not in dumped
    assert "capability-token" not in dumped
    assert PUUID not in dumped
    assert linker.calls[0]["token"] == "capability-token"
    assert linker.calls[0]["selected_puuid"] == PUUID


@pytest.mark.asyncio
async def test_prepare_static_degradation_does_not_fail_evidence() -> None:
    service, _, _, static, _, _ = _service(static=FakeStaticResolver(available=False))
    data = await service.prepare(
        match_id=MATCH_ID,
        request=JointEvidenceRequest(platform=Platform.NA1, puuid=PUUID),
        replay_token=None,
    )
    assert data.static_data_status.code == "STATIC_DATA_UNAVAILABLE"
    item = next(fact for fact in data.facts if fact.kind == "item_purchased")
    assert item.item_id == 1055
    assert item.item_name is None
    assert item.item_image_url is None
    assert static.calls


@pytest.mark.asyncio
async def test_prepare_records_truncation_metadata() -> None:
    facts = tuple(
        ChampionKillFact(
            fact_id=f"timeline:NA1:NA1_fixture:v1:frame:1:event:{index}",
            kind="champion_kill",
            timestamp_ms=50_000 + index * 40_000,
            frame_index=1,
            event_index=index,
            killer_id=1,
            victim_id=3,
            assisting_participant_ids=(),
            position=None,
        )
        for index in range(65)
    )
    timeline = TimelineLoadResult(
        snapshot=_timeline(facts=facts).model_copy(update={"match_id": MATCH_ID}),
        cache_status="miss",
    )
    # Extend match duration via snapshot duration
    match = _match()
    match = match.model_copy(update={"duration_seconds": 3000})
    service, _, _, _, _, registry = _service(
        match=FakeMatchService(snapshot=match),
        timeline=FakeTimelineService(result=timeline),
    )
    data = await service.prepare(
        match_id=MATCH_ID,
        request=JointEvidenceRequest(platform=Platform.NA1, puuid=PUUID),
        replay_token=None,
    )
    assert data.truncated is True
    assert data.total_window_count == 65
    assert len(data.windows) == 64
    assert registry.joint_evidence_window_truncations_total.value(result="truncated") == 1.0


@pytest.mark.asyncio
async def test_disabled_service_returns_not_found() -> None:
    with pytest.raises(ApiError) as raised:
        await DisabledJointEvidenceService().prepare(
            match_id=MATCH_ID,
            request=JointEvidenceRequest(platform=Platform.NA1, puuid=PUUID),
            replay_token=None,
        )
    assert raised.value.code == "NOT_FOUND"
    assert raised.value.status_code == 404


@pytest.mark.asyncio
async def test_prepare_propagates_public_errors() -> None:
    service, _, _, _, _, _ = _service(
        match=FakeMatchService(
            error=ApiError(
                status_code=422,
                code="MATCH_EVIDENCE_UNSUPPORTED_MODE",
                message="Match evidence is not supported for this game mode.",
                retryable=False,
            )
        )
    )
    with pytest.raises(ApiError) as raised:
        await service.prepare(
            match_id=MATCH_ID,
            request=JointEvidenceRequest(platform=Platform.NA1, puuid=PUUID),
            replay_token=None,
        )
    assert raised.value.code == "MATCH_EVIDENCE_UNSUPPORTED_MODE"
