from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

from app.services.analyses.domain import AnalysisRole, DimensionKey

METRIC_VERSION = "deterministic-metrics-v1"
SCORE_VERSION = "deterministic-score-v1"
RULES_VERSION = "deterministic-rules-v1"
RESULT_SCHEMA_VERSION = 1

OVERALL_COVERAGE_THRESHOLD = 0.60
MIN_DIMENSION_COVERAGE_FOR_FINDING = 0.50
FINDING_STRENGTH_MIN = 75
FINDING_STRENGTH_HIGH_MIN = 90
FINDING_IMPROVEMENT_MAX = 35
FINDING_IMPROVEMENT_HIGH_MAX = 20
MAX_FINDINGS = 3
MAX_GOALS = 3

SEVERITY_ORDER: tuple[Literal["high", "medium", "low"], ...] = ("high", "medium", "low")
FINDING_KIND_ORDER: tuple[Literal["improvement", "strength"], ...] = ("improvement", "strength")

GoalMetricKey = Literal[
    "cs_per_min",
    "deaths_per_10",
    "damage_per_min",
    "kill_participation",
    "vision_per_min",
]


def _freeze_role_weights(
    mapping: dict[AnalysisRole, dict[DimensionKey, int]],
) -> Mapping[AnalysisRole, Mapping[DimensionKey, int]]:
    return MappingProxyType({role: MappingProxyType(weights) for role, weights in mapping.items()})


def _freeze_dimension_signals(
    mapping: dict[DimensionKey, dict[str, int]],
) -> Mapping[DimensionKey, Mapping[str, int]]:
    return MappingProxyType(
        {dimension: MappingProxyType(signals) for dimension, signals in mapping.items()}
    )


def _freeze_goal_targets(
    mapping: dict[AnalysisRole, dict[GoalMetricKey, float | None]],
) -> Mapping[AnalysisRole, Mapping[GoalMetricKey, float | None]]:
    return MappingProxyType({role: MappingProxyType(targets) for role, targets in mapping.items()})


_ROLE_WEIGHTS: dict[AnalysisRole, dict[DimensionKey, int]] = {
    "top": {
        "economy": 25,
        "combat": 25,
        "survivability": 20,
        "team_objectives": 15,
        "vision": 15,
    },
    "mid": {
        "economy": 25,
        "combat": 25,
        "survivability": 20,
        "team_objectives": 15,
        "vision": 15,
    },
    "bottom": {
        "economy": 25,
        "combat": 25,
        "survivability": 20,
        "team_objectives": 15,
        "vision": 15,
    },
    "jungle": {
        "economy": 20,
        "combat": 20,
        "survivability": 20,
        "team_objectives": 25,
        "vision": 15,
    },
    "support": {
        "economy": 10,
        "combat": 20,
        "survivability": 20,
        "team_objectives": 20,
        "vision": 30,
    },
}

_DIMENSION_SIGNALS: dict[DimensionKey, dict[str, int]] = {
    "economy": {
        "cs_per_min_team": 25,
        "gold_per_min_team": 25,
        "cs_per_min_same_role": 25,
        "gold_per_min_same_role": 25,
    },
    "combat": {
        "kda_team": 20,
        "kill_participation_team": 20,
        "damage_per_min_team": 30,
        "damage_per_min_same_role": 30,
    },
    "survivability": {
        "deaths_per_10_team": 50,
        "deaths_per_10_same_role": 50,
    },
    "team_objectives": {
        "kill_participation_team": 60,
        "explicit_objective_events_team": 40,
    },
    "vision": {
        "vision_per_min_team": 70,
        "vision_per_min_same_role": 30,
    },
}

_DIMENSION_PRIORITIES: dict[DimensionKey, int] = {
    "economy": 10,
    "combat": 20,
    "survivability": 30,
    "team_objectives": 40,
    "vision": 50,
}

_GOAL_TARGETS: dict[AnalysisRole, dict[GoalMetricKey, float | None]] = {
    "top": {
        "cs_per_min": 6.5,
        "deaths_per_10": 2.0,
        "damage_per_min": 450,
        "kill_participation": 0.45,
        "vision_per_min": 0.60,
    },
    "jungle": {
        "cs_per_min": 5.5,
        "deaths_per_10": 2.0,
        "damage_per_min": 400,
        "kill_participation": 0.55,
        "vision_per_min": 0.80,
    },
    "mid": {
        "cs_per_min": 6.5,
        "deaths_per_10": 2.0,
        "damage_per_min": 500,
        "kill_participation": 0.50,
        "vision_per_min": 0.70,
    },
    "bottom": {
        "cs_per_min": 7.0,
        "deaths_per_10": 2.0,
        "damage_per_min": 550,
        "kill_participation": 0.50,
        "vision_per_min": 0.55,
    },
    "support": {
        "cs_per_min": None,
        "deaths_per_10": 2.0,
        "damage_per_min": 250,
        "kill_participation": 0.60,
        "vision_per_min": 1.20,
    },
}

ROLE_WEIGHTS: Mapping[AnalysisRole, Mapping[DimensionKey, int]] = _freeze_role_weights(
    _ROLE_WEIGHTS
)
DIMENSION_SIGNALS: Mapping[DimensionKey, Mapping[str, int]] = _freeze_dimension_signals(
    _DIMENSION_SIGNALS
)
DIMENSION_PRIORITIES: Mapping[DimensionKey, int] = MappingProxyType(_DIMENSION_PRIORITIES)
GOAL_TARGETS: Mapping[AnalysisRole, Mapping[GoalMetricKey, float | None]] = _freeze_goal_targets(
    _GOAL_TARGETS
)
