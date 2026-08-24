from __future__ import annotations

from typing import Literal

from app.schemas.domain import MatchSnapshot, ParticipantSnapshot
from app.services.analyses.domain import (
    DimensionKey,
    MetricComparison,
    MetricEvidence,
    UnavailableReason,
    normalize_analysis_role,
)
from app.services.analyses.rules_v1 import METRIC_VERSION
from app.services.timelines.domain import BuildingKillFact, EliteMonsterKillFact, TimelineSnapshot

_EPSILON = 1e-9
_METRIC_ORDER = (
    "kda",
    "cs_per_min",
    "gold_per_min",
    "damage_per_min",
    "kill_participation",
    "deaths_per_10",
    "vision_per_min",
    "explicit_objective_events",
)
_RATE_FIELDS: dict[str, tuple[str, float, DimensionKey, str, Literal["higher", "lower"]]] = {
    "cs_per_min": ("cs", 1.0, "economy", "per_minute", "higher"),
    "gold_per_min": ("gold_earned", 1.0, "economy", "per_minute", "higher"),
    "damage_per_min": ("damage_to_champions", 1.0, "combat", "per_minute", "higher"),
    "deaths_per_10": ("deaths", 10.0, "survivability", "per_10_minutes", "lower"),
    "vision_per_min": ("vision_score", 1.0, "vision", "per_minute", "higher"),
}


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _clamp_score(value: float) -> float:
    return round(min(100.0, max(0.0, value)), 2)


def _team_percentile(
    values: tuple[float, ...],
    selected_index: int,
    *,
    higher_is_better: bool,
) -> float | None:
    if len(values) < 2:
        return None
    ordered = sorted(enumerate(values), key=lambda item: item[1], reverse=higher_is_better)
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index
        while end + 1 < len(ordered) and ordered[end + 1][1] == ordered[index][1]:
            end += 1
        average_rank = (index + end) / 2
        for occupied in range(index, end + 1):
            ranks[ordered[occupied][0]] = average_rank
        index = end + 1
    return _clamp_score(100.0 * (len(values) - 1 - ranks[selected_index]) / (len(values) - 1))


def _same_role_score(selected: float, opponent: float, *, higher_is_better: bool) -> float:
    delta = (selected - opponent) / max(abs(selected), abs(opponent), _EPSILON)
    if not higher_is_better:
        delta = -delta
    return _clamp_score(50.0 + 50.0 * delta)


def _find_unique_role_opponent(
    match: MatchSnapshot, selected: ParticipantSnapshot
) -> ParticipantSnapshot | None:
    selected_role = normalize_analysis_role(selected.role)
    if selected_role is None:
        return None
    opponents = tuple(
        participant
        for participant in match.participants
        if participant.team_id != selected.team_id
        and normalize_analysis_role(participant.role) == selected_role
    )
    if len(opponents) != 1:
        return None
    return opponents[0]


def _selected_timeline_participant_id(timeline: TimelineSnapshot, puuid: str) -> int | None:
    matches = [
        participant_id
        for participant_id, mapped in timeline.participant_puuids.items()
        if mapped == puuid
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def _explicit_objective_facts(timeline: TimelineSnapshot, participant_id: int) -> tuple[str, ...]:
    return tuple(
        fact.fact_id
        for fact in timeline.facts
        if isinstance(fact, EliteMonsterKillFact | BuildingKillFact)
        and fact.killer_id == participant_id
    )


def _round_value(value: float) -> float:
    return round(value, 2)


def _kda_value(participant: ParticipantSnapshot) -> float | None:
    if participant.kills is None or participant.deaths is None or participant.assists is None:
        return None
    if participant.deaths == 0:
        return _round_value(float(participant.kills + participant.assists))
    ratio = _safe_ratio(participant.kills + participant.assists, participant.deaths)
    return None if ratio is None else _round_value(ratio)


def _scaled_rate(
    value: int | None, duration_seconds: int, *, minutes: float
) -> tuple[float | None, UnavailableReason | None]:
    if value is None:
        return None, "missing_match_value"
    if duration_seconds < 0:
        return None, "invalid_duration"
    ratio = _safe_ratio(value * minutes * 60, duration_seconds)
    if ratio is None:
        return None, "division_by_zero"
    return _round_value(ratio), None


def _team_kills(match: MatchSnapshot, team_id: int) -> int | None:
    total = 0
    found = False
    for participant in match.participants:
        if participant.team_id != team_id or participant.kills is None:
            continue
        total += participant.kills
        found = True
    return total if found else None


def _kill_participation_value(
    participant: ParticipantSnapshot, team_kills: int | None
) -> float | None:
    if participant.kills is None or participant.assists is None or team_kills is None:
        return None
    ratio = _safe_ratio(participant.kills + participant.assists, team_kills)
    return None if ratio is None else _round_value(ratio)


def _objective_count(timeline: TimelineSnapshot, puuid: str) -> float | None:
    participant_id = _selected_timeline_participant_id(timeline, puuid)
    if participant_id is None:
        return None
    return _round_value(float(len(_explicit_objective_facts(timeline, participant_id))))


def _participant_metric_value(
    participant: ParticipantSnapshot,
    metric_key: str,
    *,
    duration_seconds: int,
    team_kills: int | None,
    timeline: TimelineSnapshot | None,
) -> float | None:
    if metric_key == "kda":
        return _kda_value(participant)
    if metric_key == "kill_participation":
        return _kill_participation_value(participant, team_kills)
    if metric_key == "explicit_objective_events":
        if timeline is None:
            return None
        return _objective_count(timeline, participant.puuid)
    field_name, minutes, _category, _unit, _direction = _RATE_FIELDS[metric_key]
    value, _reason = _scaled_rate(
        getattr(participant, field_name),
        duration_seconds,
        minutes=minutes,
    )
    return value


def _team_comparison(
    match: MatchSnapshot,
    selected: ParticipantSnapshot,
    metric_key: str,
    selected_value: float,
    *,
    duration_seconds: int,
    team_kills: int | None,
    timeline: TimelineSnapshot | None,
    higher_is_better: bool,
) -> MetricComparison | None:
    values: list[float] = []
    selected_index: int | None = None
    for participant in match.participants:
        if participant.team_id != selected.team_id:
            continue
        value = _participant_metric_value(
            participant,
            metric_key,
            duration_seconds=duration_seconds,
            team_kills=team_kills,
            timeline=timeline,
        )
        if value is None:
            continue
        if participant.puuid == selected.puuid:
            selected_index = len(values)
        values.append(value)
    if selected_index is None:
        return None
    score = _team_percentile(tuple(values), selected_index, higher_is_better=higher_is_better)
    if score is None:
        return None
    return MetricComparison(basis="team_percentile", score=score, opponent_value=None)


def _same_role_comparison(
    match: MatchSnapshot,
    selected: ParticipantSnapshot,
    metric_key: str,
    selected_value: float,
    *,
    duration_seconds: int,
    team_kills: int | None,
    timeline: TimelineSnapshot | None,
    higher_is_better: bool,
) -> MetricComparison | None:
    opponent = _find_unique_role_opponent(match, selected)
    if opponent is None:
        return None
    opponent_value = _participant_metric_value(
        opponent,
        metric_key,
        duration_seconds=duration_seconds,
        team_kills=team_kills,
        timeline=timeline,
    )
    if opponent_value is None:
        return None
    return MetricComparison(
        basis="same_role",
        score=_same_role_score(selected_value, opponent_value, higher_is_better=higher_is_better),
        opponent_value=opponent_value,
    )


def _comparisons(
    match: MatchSnapshot,
    selected: ParticipantSnapshot,
    metric_key: str,
    selected_value: float,
    *,
    duration_seconds: int,
    team_kills: int | None,
    timeline: TimelineSnapshot | None,
    higher_is_better: bool,
) -> tuple[MetricComparison, ...]:
    items: list[MetricComparison] = []
    team = _team_comparison(
        match,
        selected,
        metric_key,
        selected_value,
        duration_seconds=duration_seconds,
        team_kills=team_kills,
        timeline=timeline,
        higher_is_better=higher_is_better,
    )
    if team is not None:
        items.append(team)
    same_role = _same_role_comparison(
        match,
        selected,
        metric_key,
        selected_value,
        duration_seconds=duration_seconds,
        team_kills=team_kills,
        timeline=timeline,
        higher_is_better=higher_is_better,
    )
    if same_role is not None:
        items.append(same_role)
    return tuple(items)


def _unavailable(
    metric_key: str,
    *,
    category: DimensionKey,
    beneficial_direction: Literal["higher", "lower"],
    source_type: Literal["match", "timeline", "match_and_timeline"],
    reason: UnavailableReason,
) -> MetricEvidence:
    return MetricEvidence(
        evidence_id=f"metric:v1:{metric_key}",
        metric_key=metric_key,
        category=category,
        status="unavailable",
        value=None,
        unit=None,
        beneficial_direction=beneficial_direction,
        comparisons=(),
        confidence="low",
        source_type=source_type,
        source_fact_ids=(),
        unavailable_reason=reason,
        metric_version=METRIC_VERSION,
    )


def _available(
    metric_key: str,
    *,
    category: DimensionKey,
    unit: str,
    beneficial_direction: Literal["higher", "lower"],
    source_type: Literal["match", "timeline", "match_and_timeline"],
    value: float,
    comparisons: tuple[MetricComparison, ...],
    source_fact_ids: tuple[str, ...] = (),
) -> MetricEvidence:
    return MetricEvidence(
        evidence_id=f"metric:v1:{metric_key}",
        metric_key=metric_key,
        category=category,
        status="available",
        value=value,
        unit=unit,
        beneficial_direction=beneficial_direction,
        comparisons=comparisons,
        confidence="high",
        source_type=source_type,
        source_fact_ids=source_fact_ids,
        unavailable_reason=None,
        metric_version=METRIC_VERSION,
    )


def _selected_participant(match: MatchSnapshot, selected_puuid: str) -> ParticipantSnapshot:
    matches = [
        participant for participant in match.participants if participant.puuid == selected_puuid
    ]
    if len(matches) != 1:
        raise ValueError("selected player is not in the match")
    return matches[0]


class MetricEngine:
    def compute(
        self,
        *,
        match: MatchSnapshot,
        timeline: TimelineSnapshot | None,
        selected_puuid: str,
    ) -> tuple[MetricEvidence, ...]:
        selected = _selected_participant(match, selected_puuid)
        team_kills = _team_kills(match, selected.team_id)
        duration_seconds = match.duration_seconds
        builders = {
            "kda": lambda: _compute_kda(match, selected, duration_seconds, team_kills, timeline),
            "kill_participation": lambda: _compute_kill_participation(
                match, selected, duration_seconds, team_kills, timeline
            ),
            "explicit_objective_events": lambda: _compute_objectives(
                match, selected, duration_seconds, team_kills, timeline
            ),
        }
        metrics: list[MetricEvidence] = []
        for metric_key in _METRIC_ORDER:
            if metric_key in _RATE_FIELDS:
                metrics.append(
                    _compute_rate(
                        match,
                        selected,
                        metric_key,
                        duration_seconds,
                        team_kills,
                        timeline,
                    )
                )
                continue
            metrics.append(builders[metric_key]())
        return tuple(metrics)


def _compute_kda(
    match: MatchSnapshot,
    selected: ParticipantSnapshot,
    duration_seconds: int,
    team_kills: int | None,
    timeline: TimelineSnapshot | None,
) -> MetricEvidence:
    value = _kda_value(selected)
    if value is None:
        return _unavailable(
            "kda",
            category="combat",
            beneficial_direction="higher",
            source_type="match",
            reason="missing_match_value",
        )
    return _available(
        "kda",
        category="combat",
        unit="ratio",
        beneficial_direction="higher",
        source_type="match",
        value=value,
        comparisons=_comparisons(
            match,
            selected,
            "kda",
            value,
            duration_seconds=duration_seconds,
            team_kills=team_kills,
            timeline=timeline,
            higher_is_better=True,
        ),
    )


def _compute_kill_participation(
    match: MatchSnapshot,
    selected: ParticipantSnapshot,
    duration_seconds: int,
    team_kills: int | None,
    timeline: TimelineSnapshot | None,
) -> MetricEvidence:
    if selected.kills is None or selected.assists is None:
        reason: UnavailableReason = "missing_match_value"
        value = None
    else:
        value = _kill_participation_value(selected, team_kills)
        reason = "missing_match_value" if team_kills is None else "division_by_zero"
    if value is None:
        return _unavailable(
            "kill_participation",
            category="combat",
            beneficial_direction="higher",
            source_type="match",
            reason=reason,
        )
    return _available(
        "kill_participation",
        category="combat",
        unit="ratio",
        beneficial_direction="higher",
        source_type="match",
        value=value,
        comparisons=_comparisons(
            match,
            selected,
            "kill_participation",
            value,
            duration_seconds=duration_seconds,
            team_kills=team_kills,
            timeline=timeline,
            higher_is_better=True,
        ),
    )


def _compute_rate(
    match: MatchSnapshot,
    selected: ParticipantSnapshot,
    metric_key: str,
    duration_seconds: int,
    team_kills: int | None,
    timeline: TimelineSnapshot | None,
) -> MetricEvidence:
    field_name, minutes, category, unit, direction = _RATE_FIELDS[metric_key]
    value, reason = _scaled_rate(getattr(selected, field_name), duration_seconds, minutes=minutes)
    higher_is_better = direction == "higher"
    if value is None:
        return _unavailable(
            metric_key,
            category=category,
            beneficial_direction=direction,
            source_type="match",
            reason=reason or "missing_match_value",
        )
    return _available(
        metric_key,
        category=category,
        unit=unit,
        beneficial_direction=direction,
        source_type="match",
        value=value,
        comparisons=_comparisons(
            match,
            selected,
            metric_key,
            value,
            duration_seconds=duration_seconds,
            team_kills=team_kills,
            timeline=timeline,
            higher_is_better=higher_is_better,
        ),
    )


def _compute_objectives(
    match: MatchSnapshot,
    selected: ParticipantSnapshot,
    duration_seconds: int,
    team_kills: int | None,
    timeline: TimelineSnapshot | None,
) -> MetricEvidence:
    if timeline is None:
        return _unavailable(
            "explicit_objective_events",
            category="team_objectives",
            beneficial_direction="higher",
            source_type="timeline",
            reason="timeline_unavailable",
        )
    participant_id = _selected_timeline_participant_id(timeline, selected.puuid)
    if participant_id is None:
        return _unavailable(
            "explicit_objective_events",
            category="team_objectives",
            beneficial_direction="higher",
            source_type="timeline",
            reason="timeline_unavailable",
        )
    fact_ids = _explicit_objective_facts(timeline, participant_id)
    value = _round_value(float(len(fact_ids)))
    return _available(
        "explicit_objective_events",
        category="team_objectives",
        unit="count",
        beneficial_direction="higher",
        source_type="timeline",
        value=value,
        source_fact_ids=fact_ids,
        comparisons=_comparisons(
            match,
            selected,
            "explicit_objective_events",
            value,
            duration_seconds=duration_seconds,
            team_kills=team_kills,
            timeline=timeline,
            higher_is_better=True,
        ),
    )
