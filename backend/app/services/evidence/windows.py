from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypeVar

from app.core.routing import Platform
from app.services.evidence.domain import (
    EVIDENCE_CATEGORY_ORDER,
    EvidenceCategory,
    EvidenceWindowPlan,
    PlannedEvidenceWindow,
)
from app.services.timelines.domain import (
    BuildingKillFact,
    ChampionKillFact,
    EliteMonsterKillFact,
    TimelineFact,
)

_MAX_WINDOWS = 64
_T = TypeVar("_T")


class EvidenceWindowPlanner:
    def plan(
        self,
        *,
        platform: Platform,
        match_id: str,
        schema_version: int,
        match_duration_ms: int,
        selected_participant_id: int,
        selected_team_id: int,
        participant_team_ids: Mapping[int, int],
        facts: Sequence[TimelineFact],
    ) -> EvidenceWindowPlan:
        if match_duration_ms < 0:
            raise ValueError("match_duration_ms must be non-negative")

        raw: list[tuple[int, int, EvidenceCategory, str]] = []
        for fact in facts:
            for start_ms, end_ms, category in _raw_windows_for_fact(
                fact,
                selected_participant_id=selected_participant_id,
                selected_team_id=selected_team_id,
                participant_team_ids=participant_team_ids,
            ):
                clamped_start, clamped_end = _clamp_interval(
                    start_ms, end_ms, match_duration_ms=match_duration_ms
                )
                if clamped_start > clamped_end:
                    continue
                raw.append((clamped_start, clamped_end, category, fact.fact_id))

        raw.sort(
            key=lambda item: (
                item[0],
                item[1],
                EVIDENCE_CATEGORY_ORDER.index(item[2]),
                item[3],
            )
        )
        merged = _merge_windows(raw)
        total_window_count = len(merged)
        truncated = total_window_count > _MAX_WINDOWS
        kept = merged[:_MAX_WINDOWS]
        windows = tuple(
            PlannedEvidenceWindow(
                window_id=(
                    f"evidence-window:{platform.value}:{match_id}:v{schema_version}:{index}"
                ),
                start_ms=start_ms,
                end_ms=end_ms,
                categories=categories,
                trigger_fact_ids=trigger_fact_ids,
            )
            for index, (start_ms, end_ms, categories, trigger_fact_ids) in enumerate(kept)
        )
        return EvidenceWindowPlan(
            windows=windows,
            truncated=truncated,
            total_window_count=total_window_count,
        )


def _raw_windows_for_fact(
    fact: TimelineFact,
    *,
    selected_participant_id: int,
    selected_team_id: int,
    participant_team_ids: Mapping[int, int],
) -> list[tuple[int, int, EvidenceCategory]]:
    if isinstance(fact, ChampionKillFact):
        timestamp = fact.timestamp_ms
        if (
            fact.killer_id == selected_participant_id
            or selected_participant_id in fact.assisting_participant_ids
        ):
            return [(timestamp - 12_000, timestamp + 8_000, "combat_context")]
        if fact.victim_id == selected_participant_id:
            return [(timestamp - 15_000, timestamp + 10_000, "death_context")]
        return []

    if isinstance(fact, EliteMonsterKillFact):
        if fact.killer_id == 0:
            return []
        if fact.killer_team_id != selected_team_id:
            return []
        return [(fact.timestamp_ms - 20_000, fact.timestamp_ms + 10_000, "objective_context")]

    if isinstance(fact, BuildingKillFact):
        if fact.killer_id == 0:
            return []
        killer_team = participant_team_ids.get(fact.killer_id)
        if killer_team != selected_team_id:
            return []
        return [(fact.timestamp_ms - 20_000, fact.timestamp_ms + 10_000, "building_context")]

    return []


def _clamp_interval(start_ms: int, end_ms: int, *, match_duration_ms: int) -> tuple[int, int]:
    return max(0, start_ms), min(match_duration_ms, end_ms)


def _merge_windows(
    ordered: list[tuple[int, int, EvidenceCategory, str]],
) -> list[tuple[int, int, tuple[EvidenceCategory, ...], tuple[str, ...]]]:
    if not ordered:
        return []

    merged: list[tuple[int, int, list[EvidenceCategory], list[str]]] = []
    for start_ms, end_ms, category, fact_id in ordered:
        if not merged:
            merged.append((start_ms, end_ms, [category], [fact_id]))
            continue
        previous_start, previous_end, categories, trigger_ids = merged[-1]
        if start_ms <= previous_end:
            merged[-1] = (
                previous_start,
                max(previous_end, end_ms),
                _append_unique(categories, category),
                _append_unique(trigger_ids, fact_id),
            )
            continue
        merged.append((start_ms, end_ms, [category], [fact_id]))

    return [
        (start_ms, end_ms, _stable_categories(categories), tuple(trigger_ids))
        for start_ms, end_ms, categories, trigger_ids in merged
    ]


def _append_unique(values: list[_T], value: _T) -> list[_T]:
    if value in values:
        return values
    return [*values, value]


def _stable_categories(categories: list[EvidenceCategory]) -> tuple[EvidenceCategory, ...]:
    ordered = [category for category in EVIDENCE_CATEGORY_ORDER if category in categories]
    return tuple(ordered)
