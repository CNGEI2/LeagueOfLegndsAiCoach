from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol, get_args
from uuid import UUID

from pydantic import ValidationError

from app.core.errors import ApiError, match_analysis_unsupported_mode, not_found
from app.core.metrics import (
    ANALYSIS_API_OUTCOMES,
    ANALYSIS_CACHE_STATUSES,
    ANALYSIS_COVERAGE_BUCKETS,
    ANALYSIS_IDEMPOTENCY_RESULTS,
    ANALYSIS_RESULT_STATUSES,
    ANALYSIS_STAGES,
    ANALYSIS_UNAVAILABLE_REASONS,
    MetricsRegistry,
    analysis_coverage_bucket,
    record_analysis_cache,
    record_analysis_coverage,
    record_analysis_duration,
    record_analysis_finding_count,
    record_analysis_goal_count,
    record_analysis_idempotency,
    record_analysis_result,
    record_analysis_unavailable,
)
from app.core.routing import Platform
from app.repositories.analyses import AnalysisRepository
from app.schemas.domain import MatchSnapshot
from app.services.analyses.domain import (
    DIMENSION_ORDER,
    AnalysisRole,
    DeterministicAnalysisResult,
    MetricEvidence,
    UnavailableReason,
    normalize_analysis_role,
)
from app.services.analyses.metrics import MetricEngine
from app.services.analyses.rules import RuleEngine
from app.services.analyses.rules_v1 import (
    METRIC_VERSION,
    RESULT_SCHEMA_VERSION,
    RULES_VERSION,
    SCORE_VERSION,
)
from app.services.analyses.scoring import ScoreEngine
from app.services.evidence.roster import join_match_timeline_rosters
from app.services.timelines.domain import TimelineSnapshot
from app.services.timelines.service import TimelineLoadResult

_SAFE_TIMELINE_ERRORS = frozenset(
    {
        "MATCH_TIMELINE_NOT_FOUND",
        "RIOT_AUTH_FAILED",
        "RIOT_RATE_LIMITED",
        "RIOT_UNAVAILABLE",
    }
)
_MATCH_METRIC_KEYS = frozenset(
    {
        "kda",
        "cs_per_min",
        "gold_per_min",
        "damage_per_min",
        "kill_participation",
        "deaths_per_10",
        "vision_per_min",
    }
)
_UNAVAILABLE_ORDER = get_args(UnavailableReason)


class AnalysisInvariantError(Exception):
    """Raised when a computed analysis violates V1 closure or bound invariants."""


class MatchEvidenceContext(Protocol):
    async def get_evidence_context(
        self, *, platform: Platform, match_id: str, puuid: str
    ) -> MatchSnapshot: ...


class TimelineEvidenceSource(Protocol):
    async def get_timeline(self, *, platform: Platform, match_id: str) -> TimelineLoadResult: ...


class AnalysisResolver(Protocol):
    async def create_or_reuse(
        self, *, platform: Platform, match_id: str, puuid: str
    ) -> tuple[UUID, DeterministicAnalysisResult, bool]: ...

    async def get(self, *, analysis_id: UUID) -> DeterministicAnalysisResult: ...


class DisabledAnalysisService:
    async def create_or_reuse(
        self, *, platform: Platform, match_id: str, puuid: str
    ) -> tuple[UUID, DeterministicAnalysisResult, bool]:
        raise not_found()

    async def get(self, *, analysis_id: UUID) -> DeterministicAnalysisResult:
        raise not_found()


def canonical_analysis_input(
    *, match: MatchSnapshot, timeline: TimelineSnapshot | None, selected_puuid: str
) -> bytes:
    payload = {
        "match": match.model_dump(mode="json"),
        "timeline": None if timeline is None else timeline.model_dump(mode="json"),
        "selected_puuid": selected_puuid,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def analysis_idempotency_key(
    *,
    platform: Platform,
    match_id: str,
    selected_puuid: str,
    input_hash: str,
    metric_version: str,
    score_version: str,
    rules_version: str,
) -> str:
    payload = {
        "input_hash": input_hash,
        "match_id": match_id,
        "metric_version": metric_version,
        "platform": platform.value,
        "rules_version": rules_version,
        "score_version": score_version,
        "selected_puuid": selected_puuid,
    }
    material = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def validate_reference_closure(
    result: DeterministicAnalysisResult, *, timeline: TimelineSnapshot | None
) -> None:
    evidence_ids = tuple(metric.evidence_id for metric in result.metrics)
    if len(evidence_ids) != len(set(evidence_ids)):
        raise AnalysisInvariantError("metric evidence ids must be unique")
    catalog = set(evidence_ids)
    referenced = (
        *(evidence_id for finding in result.findings for evidence_id in finding.evidence_ids),
        *(evidence_id for goal in result.goals for evidence_id in goal.evidence_ids),
    )
    if any(evidence_id not in catalog for evidence_id in referenced):
        raise AnalysisInvariantError("finding or goal references missing evidence")
    fact_ids = {fact.fact_id for fact in timeline.facts} if timeline is not None else set()
    for metric in result.metrics:
        if timeline is None and metric.source_fact_ids:
            raise AnalysisInvariantError("timeline fact ids require a timeline snapshot")
        for fact_id in metric.source_fact_ids:
            if fact_id not in fact_ids:
                raise AnalysisInvariantError("metric references a missing timeline fact")
    if tuple(item.dimension for item in result.scores.dimensions) != DIMENSION_ORDER:
        raise AnalysisInvariantError("scores require five canonical dimensions")
    scores = [item.score for item in result.scores.dimensions if item.score is not None]
    if result.scores.overall_score is not None:
        scores.append(result.scores.overall_score)
    if any(score < 0 or score > 100 for score in scores):
        raise AnalysisInvariantError("scores must stay within 0..100")


class AnalysisService:
    API_OUTCOMES = ANALYSIS_API_OUTCOMES
    CACHE_STATUSES = ANALYSIS_CACHE_STATUSES
    RESULT_STATUSES = ANALYSIS_RESULT_STATUSES
    COVERAGE_BUCKETS = ANALYSIS_COVERAGE_BUCKETS
    STAGES = ANALYSIS_STAGES
    IDEMPOTENCY_RESULTS = ANALYSIS_IDEMPOTENCY_RESULTS
    UNAVAILABLE_REASONS = ANALYSIS_UNAVAILABLE_REASONS

    def __init__(
        self,
        *,
        match_service: MatchEvidenceContext,
        timeline_service: TimelineEvidenceSource,
        repository: AnalysisRepository,
        metric_engine: MetricEngine,
        score_engine: ScoreEngine,
        rule_engine: RuleEngine,
        retention_days: int,
        clock: Callable[[], datetime] | None = None,
        metrics: MetricsRegistry | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._match_service = match_service
        self._timeline_service = timeline_service
        self._repository = repository
        self._metric_engine = metric_engine
        self._score_engine = score_engine
        self._rule_engine = rule_engine
        self._retention_days = retention_days
        self._clock = clock or (lambda: datetime.now(UTC))
        self._metrics = metrics
        self._monotonic = monotonic or time.monotonic

    async def create_or_reuse(
        self, *, platform: Platform, match_id: str, puuid: str
    ) -> tuple[UUID, DeterministicAnalysisResult, bool]:
        started = self._monotonic()
        match = await self._load_match(platform=platform, match_id=match_id, puuid=puuid)
        timeline, timeline_unavailable = await self._load_timeline(
            platform=platform, match_id=match_id
        )
        if timeline is not None:
            join_match_timeline_rosters(
                match=match,
                timeline=timeline,
                selected_puuid=puuid,
            )
        selected = next(
            participant for participant in match.participants if participant.puuid == puuid
        )
        role = normalize_analysis_role(selected.role)
        metrics = self._metric_engine.compute(match=match, timeline=timeline, selected_puuid=puuid)
        scores = self._score_engine.compute(role=role, metrics=metrics)
        findings, goals = self._rule_engine.evaluate(role=role, metrics=metrics, scores=scores)
        unavailable_reasons = _collect_unavailable_reasons(
            metrics=metrics, role=role, timeline_unavailable=timeline_unavailable
        )
        input_hash = hashlib.sha256(
            canonical_analysis_input(match=match, timeline=timeline, selected_puuid=puuid)
        ).hexdigest()
        match_metric_gap = any(
            metric.metric_key in _MATCH_METRIC_KEYS and metric.status == "unavailable"
            for metric in metrics
        )
        status = (
            "partial"
            if timeline is None or match_metric_gap or scores.overall_score is None
            else "completed"
        )
        try:
            result = DeterministicAnalysisResult(
                status=status,
                platform=platform,
                match_id=match.match_id,
                selected_puuid=puuid,
                role=role,
                metrics=metrics,
                scores=scores,
                findings=findings,
                goals=goals,
                unavailable_reasons=unavailable_reasons,
                input_hash=input_hash,
                metric_version=METRIC_VERSION,
                score_version=SCORE_VERSION,
                rules_version=RULES_VERSION,
                schema_version=RESULT_SCHEMA_VERSION,
            )
        except ValidationError as error:
            raise AnalysisInvariantError("computed analysis failed integrity validation") from error
        validate_reference_closure(result, timeline=timeline)
        after_compute = self._monotonic()
        now = self._clock()
        stored, created = await self._repository.create_or_reuse(
            idempotency_key=analysis_idempotency_key(
                platform=platform,
                match_id=match_id,
                selected_puuid=puuid,
                input_hash=input_hash,
                metric_version=METRIC_VERSION,
                score_version=SCORE_VERSION,
                rules_version=RULES_VERSION,
            ),
            result=result,
            now=now,
            expires_at=now + timedelta(days=self._retention_days),
        )
        await self._repository.delete_expired(now=now)
        after_persist = self._monotonic()
        self._record_create_metrics(
            result=stored.result,
            created=created,
            compute_seconds=after_compute - started,
            persist_seconds=after_persist - after_compute,
            total_seconds=after_persist - started,
        )
        return stored.analysis_id, stored.result, created

    async def get(self, *, analysis_id: UUID) -> DeterministicAnalysisResult:
        stored = await self._repository.get(analysis_id=analysis_id, now=self._clock())
        if stored is None:
            raise not_found()
        if self._metrics is not None:
            record_analysis_cache(self._metrics, status="hit")
        return stored.result

    def _record_create_metrics(
        self,
        *,
        result: DeterministicAnalysisResult,
        created: bool,
        compute_seconds: float,
        persist_seconds: float,
        total_seconds: float,
    ) -> None:
        if self._metrics is None:
            return
        record_analysis_duration(self._metrics, stage="compute", seconds=compute_seconds)
        record_analysis_duration(self._metrics, stage="persist", seconds=persist_seconds)
        record_analysis_duration(self._metrics, stage="total", seconds=total_seconds)
        record_analysis_cache(self._metrics, status="miss" if created else "hit")
        record_analysis_idempotency(self._metrics, result="created" if created else "reused")
        record_analysis_result(self._metrics, status=result.status)
        record_analysis_coverage(
            self._metrics, bucket=analysis_coverage_bucket(result.scores.coverage)
        )
        for reason in result.unavailable_reasons:
            record_analysis_unavailable(self._metrics, reason=reason)
        record_analysis_finding_count(self._metrics, count=len(result.findings))
        record_analysis_goal_count(self._metrics, count=len(result.goals))

    async def _load_match(self, *, platform: Platform, match_id: str, puuid: str) -> MatchSnapshot:
        try:
            return await self._match_service.get_evidence_context(
                platform=platform, match_id=match_id, puuid=puuid
            )
        except ApiError as error:
            if error.code == "MATCH_EVIDENCE_UNSUPPORTED_MODE":
                raise match_analysis_unsupported_mode() from error
            raise

    async def _load_timeline(
        self, *, platform: Platform, match_id: str
    ) -> tuple[TimelineSnapshot | None, bool]:
        try:
            loaded = await self._timeline_service.get_timeline(platform=platform, match_id=match_id)
        except ApiError as error:
            if error.code in _SAFE_TIMELINE_ERRORS:
                return None, True
            raise
        return loaded.snapshot, False


def _collect_unavailable_reasons(
    *,
    metrics: tuple[MetricEvidence, ...],
    role: AnalysisRole | None,
    timeline_unavailable: bool,
) -> tuple[UnavailableReason, ...]:
    collected: set[UnavailableReason] = set()
    if timeline_unavailable:
        collected.add("timeline_unavailable")
    if role is None:
        collected.add("role_unavailable")
    for metric in metrics:
        if metric.status == "unavailable" and metric.unavailable_reason is not None:
            collected.add(metric.unavailable_reason)
    return tuple(reason for reason in _UNAVAILABLE_ORDER if reason in collected)
