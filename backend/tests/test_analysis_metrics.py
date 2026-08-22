from __future__ import annotations

import pytest

from app.services.analyses.domain import MetricEvidence
from app.services.analyses.metrics import MetricEngine
from tests.fixtures.analysis_inputs import (
    SELECTED_PUUID,
    replace_participant,
    standard_analysis_match,
    standard_analysis_timeline,
    toggle_won,
)

METRIC_KEYS = (
    "kda",
    "cs_per_min",
    "gold_per_min",
    "damage_per_min",
    "kill_participation",
    "deaths_per_10",
    "vision_per_min",
    "explicit_objective_events",
)


def _catalog(**overrides: object) -> tuple[MetricEvidence, ...]:
    match = overrides.pop("match", standard_analysis_match())
    timeline = overrides.pop("timeline", standard_analysis_timeline())
    selected_puuid = overrides.pop("selected_puuid", SELECTED_PUUID)
    assert not overrides
    return MetricEngine().compute(match=match, timeline=timeline, selected_puuid=selected_puuid)


def _by_key(**overrides: object) -> dict[str, MetricEvidence]:
    return {metric.metric_key: metric for metric in _catalog(**overrides)}


def _same_role_score(selected: float, opponent: float, *, higher_is_better: bool) -> float:
    delta = (selected - opponent) / max(abs(selected), abs(opponent), 1e-9)
    if not higher_is_better:
        delta = -delta
    return round(min(100.0, max(0.0, 50.0 + 50.0 * delta)), 2)


def test_metric_engine_computes_stable_catalog_for_selected_player() -> None:
    catalog = _catalog()
    by_key = {metric.metric_key: metric for metric in catalog}

    assert tuple(metric.metric_key for metric in catalog) == METRIC_KEYS
    assert by_key["kda"].value == 6.0
    assert by_key["cs_per_min"].unit == "per_minute"
    assert by_key["deaths_per_10"].beneficial_direction == "lower"
    assert by_key["explicit_objective_events"].source_fact_ids == (
        "timeline:elite_monster:1",
        "timeline:building:2",
    )
    assert by_key["explicit_objective_events"].value == 2.0
    assert all(metric.evidence_id == f"metric:v1:{metric.metric_key}" for metric in catalog)


def test_kda_uses_kills_plus_assists_when_deaths_are_zero() -> None:
    match = replace_participant(standard_analysis_match(), SELECTED_PUUID, deaths=0)
    metric = _by_key(match=match)["kda"]
    assert metric.status == "available"
    assert metric.value == 6.0
    assert metric.unavailable_reason is None


def test_per_minute_metrics_divide_by_match_duration() -> None:
    by_key = _by_key()
    assert by_key["cs_per_min"].value == 7.0
    assert by_key["gold_per_min"].value == 300.0
    assert by_key["damage_per_min"].value == 200.0
    assert by_key["vision_per_min"].value == 1.0
    assert by_key["deaths_per_10"].value == 0.33


def test_kill_participation_is_unavailable_when_team_kills_are_zero() -> None:
    match = standard_analysis_match()
    for participant in match.participants:
        if participant.team_id == 100:
            match = replace_participant(match, participant.puuid, kills=0, assists=0)
    metric = _by_key(match=match)["kill_participation"]
    assert metric.status == "unavailable"
    assert metric.value is None
    assert metric.unavailable_reason == "division_by_zero"


def test_team_percentile_assigns_average_rank_to_ties() -> None:
    comparison = next(
        item for item in _by_key()["cs_per_min"].comparisons if item.basis == "team_percentile"
    )
    # Blue CS/min: 8.0, 7.0, 6.0, 6.0, 1.0. Selected 7.0 occupies rank 1 of 0..4.
    assert comparison.score == 75.0


def test_lower_is_better_team_rank_rewards_fewer_deaths() -> None:
    comparison = next(
        item for item in _by_key()["deaths_per_10"].comparisons if item.basis == "team_percentile"
    )
    # Blue deaths/10m: 1.00, 0.67, 0.33, 1.33, 1.67. Selected 0.33 is uniquely best.
    assert comparison.score == 100.0


def test_same_role_formula_matches_approved_delta_mapping() -> None:
    metric = _by_key()["cs_per_min"]
    comparison = next(item for item in metric.comparisons if item.basis == "same_role")
    assert comparison.opponent_value == 5.0
    assert comparison.score == _same_role_score(7.0, 5.0, higher_is_better=True)


def test_ambiguous_same_role_opponent_omits_same_role_comparison() -> None:
    match = replace_participant(standard_analysis_match(), "red-top", role="MIDDLE")
    comparisons = _by_key(match=match)["cs_per_min"].comparisons
    assert all(item.basis != "same_role" for item in comparisons)


def test_missing_same_role_opponent_omits_same_role_comparison() -> None:
    match = replace_participant(standard_analysis_match(), "red-mid", role="TOP")
    comparisons = _by_key(match=match)["cs_per_min"].comparisons
    assert all(item.basis != "same_role" for item in comparisons)


def test_utility_maps_to_support_for_unique_same_role_matching() -> None:
    metric = _by_key(selected_puuid="blue-support")["cs_per_min"]
    comparison = next(item for item in metric.comparisons if item.basis == "same_role")
    assert comparison.opponent_value == pytest.approx(25 / 30, rel=0, abs=0.01)


def test_absent_timeline_makes_objective_events_unavailable() -> None:
    metric = _by_key(timeline=None)["explicit_objective_events"]
    assert metric.status == "unavailable"
    assert metric.value is None
    assert metric.unavailable_reason == "timeline_unavailable"
    assert metric.source_fact_ids == ()


def test_negative_duration_makes_rate_metrics_unavailable() -> None:
    match = standard_analysis_match().model_copy(update={"duration_seconds": -1})
    by_key = _by_key(match=match)
    for key in ("cs_per_min", "gold_per_min", "damage_per_min", "deaths_per_10", "vision_per_min"):
        assert by_key[key].status == "unavailable"
        assert by_key[key].value is None
        assert by_key[key].unavailable_reason == "invalid_duration"
    assert by_key["kda"].status == "available"
    assert by_key["kda"].value == 6.0


def test_missing_participant_fields_are_typed_unavailable() -> None:
    match = replace_participant(
        standard_analysis_match(),
        SELECTED_PUUID,
        kills=None,
        deaths=None,
        assists=None,
        cs=None,
        gold_earned=None,
        damage_to_champions=None,
        vision_score=None,
    )
    by_key = _by_key(match=match)
    for key in (
        "kda",
        "cs_per_min",
        "gold_per_min",
        "damage_per_min",
        "kill_participation",
        "deaths_per_10",
        "vision_per_min",
    ):
        assert by_key[key].status == "unavailable"
        assert by_key[key].value is None
        assert by_key[key].unavailable_reason == "missing_match_value"


def test_win_loss_does_not_change_the_metric_catalog() -> None:
    baseline = _catalog()
    flipped = _catalog(match=toggle_won(standard_analysis_match()))
    assert flipped == baseline


def test_same_role_comparison_scores_stay_within_zero_to_one_hundred() -> None:
    engine = MetricEngine()
    timeline = standard_analysis_timeline()
    for index in range(100):
        selected_gold = index * 17
        opponent_gold = (index * 31 + 5) % 200
        match = replace_participant(
            standard_analysis_match(), SELECTED_PUUID, gold_earned=selected_gold
        )
        match = replace_participant(match, "red-mid", gold_earned=opponent_gold)
        catalog = engine.compute(match=match, timeline=timeline, selected_puuid=SELECTED_PUUID)
        metric = next(item for item in catalog if item.metric_key == "gold_per_min")
        if metric.status != "available":
            continue
        comparison = next(item for item in metric.comparisons if item.basis == "same_role")
        assert 0 <= comparison.score <= 100
        assert comparison.score == _same_role_score(
            metric.value or 0.0,
            comparison.opponent_value or 0.0,
            higher_is_better=True,
        )
