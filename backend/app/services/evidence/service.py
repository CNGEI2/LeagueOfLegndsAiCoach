from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol
from uuid import UUID

from app.core.errors import ApiError, not_found
from app.core.metrics import MetricsRegistry
from app.core.routing import Platform
from app.schemas.domain import Locale, MatchSnapshot
from app.schemas.evidence import (
    EvidenceArtifactReferenceResponse,
    EvidenceRelationship,
    EvidenceWindowResponse,
    JointEvidenceData,
    JointEvidenceRequest,
    PublicBuildingKillFact,
    PublicChampionKillFact,
    PublicEliteMonsterKillFact,
    PublicItemDestroyedFact,
    PublicItemPurchasedFact,
    PublicItemSoldFact,
    PublicItemUndoFact,
    PublicParticipantStateFact,
    PublicTimelineFact,
    ReplayLinkSummary,
)
from app.services.evidence.domain import LinkedEvidenceWindow, PlannedEvidenceWindow
from app.services.evidence.windows import EvidenceWindowPlanner
from app.services.static_data.resolver import EvidenceItemCatalog
from app.services.timelines.domain import (
    BuildingKillFact,
    ChampionKillFact,
    EliteMonsterKillFact,
    ItemEventFact,
    ParticipantStateFact,
    TimelineFact,
    TimelineSnapshot,
)
from app.services.timelines.service import TimelineLoadResult


class MatchEvidenceContext(Protocol):
    async def get_evidence_context(
        self, *, platform: Platform, match_id: str, puuid: str
    ) -> MatchSnapshot: ...


class TimelineEvidenceSource(Protocol):
    async def get_timeline(self, *, platform: Platform, match_id: str) -> TimelineLoadResult: ...


class EvidenceStaticHydrator(Protocol):
    async def hydrate_evidence_items(
        self, *, game_version: str, item_ids: tuple[int, ...], locale: Locale
    ) -> EvidenceItemCatalog: ...


class EvidenceReplayLinker(Protocol):
    async def link(
        self,
        *,
        windows: Sequence[PlannedEvidenceWindow],
        replay_id: UUID | None,
        token: str | None,
        platform: Platform,
        match_id: str,
        selected_puuid: str,
    ) -> Sequence[LinkedEvidenceWindow]: ...


class JointEvidenceResolver(Protocol):
    async def prepare(
        self,
        *,
        match_id: str,
        request: JointEvidenceRequest,
        replay_token: str | None,
    ) -> JointEvidenceData: ...


class DisabledJointEvidenceService:
    async def prepare(
        self,
        *,
        match_id: str,
        request: JointEvidenceRequest,
        replay_token: str | None,
    ) -> JointEvidenceData:
        raise not_found()


class JointEvidenceService:
    WINDOW_RESULTS = frozenset({"planned"})
    TRUNCATION_RESULTS = frozenset({"truncated", "not_truncated"})
    COVERAGE_LABELS = frozenset({"full", "partial", "unavailable"})

    def __init__(
        self,
        *,
        match_service: MatchEvidenceContext,
        timeline_service: TimelineEvidenceSource,
        planner: EvidenceWindowPlanner,
        replay_linker: EvidenceReplayLinker,
        static_resolver: EvidenceStaticHydrator,
        metrics: MetricsRegistry,
    ) -> None:
        self._match_service = match_service
        self._timeline_service = timeline_service
        self._planner = planner
        self._replay_linker = replay_linker
        self._static_resolver = static_resolver
        self._metrics = metrics

    async def prepare(
        self,
        *,
        match_id: str,
        request: JointEvidenceRequest,
        replay_token: str | None,
    ) -> JointEvidenceData:
        return await self._prepare(match_id=match_id, request=request, replay_token=replay_token)

    async def _prepare(
        self,
        *,
        match_id: str,
        request: JointEvidenceRequest,
        replay_token: str | None,
    ) -> JointEvidenceData:
        match = await self._match_service.get_evidence_context(
            platform=request.platform, match_id=match_id, puuid=request.puuid
        )
        timeline_result = await self._timeline_service.get_timeline(
            platform=request.platform, match_id=match_id
        )
        timeline = timeline_result.snapshot
        participant_team_ids, selected_participant_id, selected_team_id = _join_rosters(
            match=match,
            timeline=timeline,
            selected_puuid=request.puuid,
        )
        plan = self._planner.plan(
            platform=request.platform,
            match_id=match_id,
            schema_version=timeline.schema_version,
            match_duration_ms=match.duration_seconds * 1000,
            selected_participant_id=selected_participant_id,
            selected_team_id=selected_team_id,
            participant_team_ids=participant_team_ids,
            facts=timeline.facts,
        )
        linked_windows = await self._replay_linker.link(
            windows=plan.windows,
            replay_id=request.replay_id,
            token=replay_token,
            platform=request.platform,
            match_id=match_id,
            selected_puuid=request.puuid,
        )
        item_ids = _collect_item_ids(timeline.facts)
        catalog = await self._static_resolver.hydrate_evidence_items(
            game_version=match.game_version,
            item_ids=item_ids,
            locale=request.locale,
        )
        facts = tuple(
            _project_fact(
                fact,
                selected_participant_id=selected_participant_id,
                selected_team_id=selected_team_id,
                participant_team_ids=participant_team_ids,
                catalog=catalog,
            )
            for fact in timeline.facts
        )
        windows = tuple(_project_window(linked) for linked in linked_windows)
        replay_link = _replay_summary(request.replay_id, windows)
        self._observe_success(
            plan_window_count=len(plan.windows),
            truncated=plan.truncated,
            windows=windows,
        )
        return JointEvidenceData(
            platform=request.platform,
            match_id=match_id,
            locale=request.locale,
            schema_version=1,
            facts=facts,
            windows=windows,
            timeline_cache_status=timeline_result.cache_status,
            replay_link=replay_link,
            static_data_status=catalog.static_data_status,
            truncated=plan.truncated,
            total_window_count=plan.total_window_count,
        )

    def _observe_success(
        self,
        *,
        plan_window_count: int,
        truncated: bool,
        windows: Sequence[EvidenceWindowResponse],
    ) -> None:
        if plan_window_count:
            self._metrics.joint_evidence_windows_total.inc(
                amount=float(plan_window_count), result="planned"
            )
        self._metrics.joint_evidence_window_truncations_total.inc(
            result="truncated" if truncated else "not_truncated"
        )
        for window in windows:
            self._metrics.joint_evidence_replay_coverage_total.inc(coverage=window.coverage)


def _join_rosters(
    *,
    match: MatchSnapshot,
    timeline: TimelineSnapshot,
    selected_puuid: str,
) -> tuple[dict[int, int], int, int]:
    match_teams_by_puuid: dict[str, int] = {}
    for participant in match.participants:
        if participant.puuid in match_teams_by_puuid:
            raise _invalid_roster()
        match_teams_by_puuid[participant.puuid] = participant.team_id

    timeline_puuids = list(timeline.participant_puuids.values())
    if len(timeline_puuids) != len(set(timeline_puuids)):
        raise _invalid_roster()
    timeline_set = set(timeline_puuids)
    match_set = set(match_teams_by_puuid)
    if timeline_set != match_set:
        raise _invalid_roster()

    participant_team_ids: dict[int, int] = {}
    for participant_id, puuid in timeline.participant_puuids.items():
        participant_team_ids[participant_id] = match_teams_by_puuid[puuid]

    selected_ids = [
        participant_id
        for participant_id, puuid in timeline.participant_puuids.items()
        if puuid == selected_puuid
    ]
    if len(selected_ids) != 1:
        raise ApiError(
            status_code=404,
            code="PLAYER_NOT_IN_MATCH",
            message="The selected player did not participate in this match.",
            retryable=False,
        )
    selected_participant_id = selected_ids[0]
    selected_team_id = participant_team_ids[selected_participant_id]
    return participant_team_ids, selected_participant_id, selected_team_id


def _invalid_roster() -> ApiError:
    return ApiError(
        status_code=502,
        code="RIOT_INVALID_RESPONSE",
        message="Riot returned an invalid response.",
        retryable=False,
    )


def _collect_item_ids(facts: Sequence[TimelineFact]) -> tuple[int, ...]:
    values: list[int] = []
    seen: set[int] = set()
    for fact in facts:
        if not isinstance(fact, ItemEventFact):
            continue
        candidates = [fact.item_id, fact.before_id, fact.after_id]
        for item_id in candidates:
            if item_id is None or item_id in seen:
                continue
            seen.add(item_id)
            values.append(item_id)
    return tuple(values)


def _item_lookup(catalog: EvidenceItemCatalog) -> dict[int, tuple[str | None, str | None]]:
    return {item.item_id: (item.name, item.image_url) for item in catalog.items}


def _project_fact(
    fact: TimelineFact,
    *,
    selected_participant_id: int,
    selected_team_id: int,
    participant_team_ids: Mapping[int, int],
    catalog: EvidenceItemCatalog,
) -> PublicTimelineFact:
    items = _item_lookup(catalog)
    if isinstance(fact, ChampionKillFact):
        relationship: EvidenceRelationship
        if fact.killer_id == selected_participant_id:
            relationship = "killer"
        elif fact.victim_id == selected_participant_id:
            relationship = "victim"
        elif selected_participant_id in fact.assisting_participant_ids:
            relationship = "assistant"
        else:
            relationship = "not_involved"
        return PublicChampionKillFact(
            fact_id=fact.fact_id,
            kind="champion_kill",
            timestamp_ms=fact.timestamp_ms,
            relationship=relationship,
            killer_id=fact.killer_id,
            victim_id=fact.victim_id,
            assisting_participant_ids=fact.assisting_participant_ids,
            position_x=None if fact.position is None else fact.position.x,
            position_y=None if fact.position is None else fact.position.y,
        )
    if isinstance(fact, EliteMonsterKillFact):
        killer_team = participant_team_ids.get(fact.killer_id)
        relationship = (
            "team_context"
            if fact.killer_id != 0
            and killer_team == fact.killer_team_id
            and killer_team == selected_team_id
            else "not_involved"
        )
        return PublicEliteMonsterKillFact(
            fact_id=fact.fact_id,
            kind="elite_monster_kill",
            timestamp_ms=fact.timestamp_ms,
            relationship=relationship,
            killer_id=fact.killer_id,
            killer_team_id=fact.killer_team_id,
            monster_type=fact.monster_type,
            monster_sub_type=fact.monster_sub_type,
            position_x=None if fact.position is None else fact.position.x,
            position_y=None if fact.position is None else fact.position.y,
        )
    if isinstance(fact, BuildingKillFact):
        killer_team = participant_team_ids.get(fact.killer_id)
        relationship = (
            "team_context"
            if fact.killer_id != 0 and killer_team == selected_team_id
            else "not_involved"
        )
        return PublicBuildingKillFact(
            fact_id=fact.fact_id,
            kind="building_kill",
            timestamp_ms=fact.timestamp_ms,
            relationship=relationship,
            killer_id=fact.killer_id,
            team_id=fact.team_id,
            building_type=fact.building_type,
            lane_type=fact.lane_type,
            tower_type=fact.tower_type,
            position_x=None if fact.position is None else fact.position.x,
            position_y=None if fact.position is None else fact.position.y,
        )
    if isinstance(fact, ItemEventFact):
        relationship = "actor" if fact.participant_id == selected_participant_id else "not_involved"
        if fact.kind == "item_undo":
            before_name, before_url = items.get(fact.before_id or -1, (None, None))
            after_name, after_url = items.get(fact.after_id or -1, (None, None))
            return PublicItemUndoFact(
                fact_id=fact.fact_id,
                kind="item_undo",
                timestamp_ms=fact.timestamp_ms,
                relationship=relationship,
                participant_id=fact.participant_id,
                before_id=fact.before_id or 0,
                after_id=fact.after_id or 0,
                before_item_name=before_name,
                before_item_image_url=before_url,
                after_item_name=after_name,
                after_item_image_url=after_url,
            )
        name, image_url = items.get(fact.item_id or -1, (None, None))
        common = {
            "fact_id": fact.fact_id,
            "timestamp_ms": fact.timestamp_ms,
            "relationship": relationship,
            "participant_id": fact.participant_id,
            "item_id": fact.item_id or 0,
            "item_name": name,
            "item_image_url": image_url,
        }
        if fact.kind == "item_purchased":
            return PublicItemPurchasedFact(kind="item_purchased", **common)
        if fact.kind == "item_sold":
            return PublicItemSoldFact(kind="item_sold", **common)
        return PublicItemDestroyedFact(kind="item_destroyed", **common)
    if isinstance(fact, ParticipantStateFact):
        relationship = "actor" if fact.participant_id == selected_participant_id else "not_involved"
        return PublicParticipantStateFact(
            fact_id=fact.fact_id,
            kind="participant_state",
            timestamp_ms=fact.timestamp_ms,
            relationship=relationship,
            participant_id=fact.participant_id,
            level=fact.level,
            current_gold=fact.current_gold,
            total_gold=fact.total_gold,
            minions_killed=fact.minions_killed,
            jungle_minions_killed=fact.jungle_minions_killed,
            xp=fact.xp,
            position_x=None if fact.position is None else fact.position.x,
            position_y=None if fact.position is None else fact.position.y,
        )
    raise TypeError("unsupported timeline fact")


def _project_window(linked: LinkedEvidenceWindow) -> EvidenceWindowResponse:
    coverage = linked.coverage
    window = linked.window
    artifacts = tuple(
        EvidenceArtifactReferenceResponse(
            artifact_id=ref.artifact_id,
            kind=ref.kind,
            game_time_ms=ref.game_time_ms,
            video_time_ms=ref.video_time_ms,
        )
        for ref in linked.artifacts
    )
    return EvidenceWindowResponse(
        window_id=window.window_id,
        start_ms=window.start_ms,
        end_ms=window.end_ms,
        categories=window.categories,
        trigger_fact_ids=window.trigger_fact_ids,
        coverage=coverage,
        covered_game_start_ms=linked.covered_game_start_ms,
        covered_game_end_ms=linked.covered_game_end_ms,
        video_start_ms=linked.video_start_ms,
        video_end_ms=linked.video_end_ms,
        artifacts=artifacts,
    )


def _replay_summary(
    replay_id: UUID | None, windows: Sequence[EvidenceWindowResponse]
) -> ReplayLinkSummary | None:
    if replay_id is None:
        return None
    return ReplayLinkSummary(
        full_count=sum(1 for window in windows if window.coverage == "full"),
        partial_count=sum(1 for window in windows if window.coverage == "partial"),
        unavailable_count=sum(1 for window in windows if window.coverage == "unavailable"),
    )
