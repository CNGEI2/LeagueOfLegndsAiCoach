from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.core.errors import ApiError
from app.core.routing import Platform
from app.repositories.analyses import StoredAnalysis
from app.schemas.domain import MatchSnapshot
from app.services.analyses.domain import Finding, MetricEvidence
from app.services.analyses.metrics import MetricEngine
from app.services.analyses.rules import RuleEngine
from app.services.analyses.rules_v1 import METRIC_VERSION, RULES_VERSION, SCORE_VERSION
from app.services.analyses.scoring import ScoreEngine
from app.services.analyses.service import (
    AnalysisInvariantError,
    AnalysisService,
    DisabledAnalysisService,
    analysis_idempotency_key,
    canonical_analysis_input,
)
from app.services.timelines.domain import TimelineSnapshot
from app.services.timelines.service import TimelineLoadResult
from tests.fixtures.analysis_inputs import (
    SELECTED_PUUID,
    replace_participant,
    standard_analysis_match,
    standard_analysis_timeline,
)

NOW = datetime(2026, 8, 22, 18, 0, tzinfo=UTC)


def _api_error(code: str, status_code: int = 422) -> ApiError:
    return ApiError(status_code=status_code, code=code, message=code, retryable=False)


@dataclass
class FakeMatchService:
    snapshot: MatchSnapshot = field(default_factory=standard_analysis_match)
    error: ApiError | None = None

    async def get_evidence_context(
        self, *, platform: Platform, match_id: str, puuid: str
    ) -> MatchSnapshot:
        if self.error is not None:
            raise self.error
        return self.snapshot


@dataclass
class FakeTimelineService:
    snapshot: TimelineSnapshot | None = field(default_factory=standard_analysis_timeline)
    error: ApiError | None = None

    async def get_timeline(self, *, platform: Platform, match_id: str) -> TimelineLoadResult:
        if self.error is not None:
            raise self.error
        assert self.snapshot is not None
        return TimelineLoadResult(snapshot=self.snapshot, cache_status="hit")


@dataclass
class FakeRepository:
    create_calls: list[dict[str, object]] = field(default_factory=list)
    delete_calls: list[datetime] = field(default_factory=list)
    by_key: dict[str, StoredAnalysis] = field(default_factory=dict)

    async def get(self, *, analysis_id: UUID, now: datetime) -> StoredAnalysis | None:
        for stored in self.by_key.values():
            if stored.analysis_id == analysis_id and stored.expires_at > now:
                return stored
        return None

    async def create_or_reuse(
        self,
        *,
        idempotency_key: str,
        result: object,
        now: datetime,
        expires_at: datetime,
    ) -> tuple[StoredAnalysis, bool]:
        self.create_calls.append({"key": idempotency_key, "result": result, "now": now})
        existing = self.by_key.get(idempotency_key)
        if existing is not None:
            return existing, False
        stored = StoredAnalysis(
            analysis_id=uuid4(),
            idempotency_key=idempotency_key,
            result=result,  # type: ignore[arg-type]
            created_at=now,
            expires_at=expires_at,
        )
        self.by_key[idempotency_key] = stored
        return stored, True

    async def delete_expired(self, *, now: datetime) -> int:
        self.delete_calls.append(now)
        return 0


class ExplodingMetricEngine:
    def compute(self, **kwargs: object) -> tuple[MetricEvidence, ...]:
        raise RuntimeError("compute failed")


class BrokenRuleEngine:
    def evaluate(self, **kwargs: object) -> tuple[tuple[Finding, ...], tuple[object, ...]]:
        finding = Finding(
            rule_id="finding.combat.improvement",
            kind="improvement",
            severity="high",
            message_code="analysis.finding.combat.improvement",
            params={"score": 10.0, "coverage": 1.0},
            evidence_ids=("metric:v1:missing",),
            confidence="high",
        )
        return (finding,), ()


def _service(**overrides: object) -> tuple[AnalysisService, FakeRepository]:
    repository = FakeRepository()
    values: dict[str, object] = {
        "match_service": FakeMatchService(),
        "timeline_service": FakeTimelineService(),
        "repository": repository,
        "metric_engine": MetricEngine(),
        "score_engine": ScoreEngine(),
        "rule_engine": RuleEngine(),
        "retention_days": 30,
        "clock": lambda: NOW,
    }
    values.update(overrides)
    return AnalysisService(**values), repository  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_disabled_analysis_service_is_dark() -> None:
    service = DisabledAnalysisService()
    with pytest.raises(ApiError) as raised:
        await service.create_or_reuse(platform=Platform.NA1, match_id="NA1_1", puuid="p")
    assert raised.value.code == "NOT_FOUND"
    with pytest.raises(ApiError) as raised:
        await service.get(analysis_id=uuid4())
    assert raised.value.code == "NOT_FOUND"


@pytest.mark.asyncio
async def test_completed_flow_persists_and_cleans_expired() -> None:
    service, repository = _service()
    analysis_id, result, created = await service.create_or_reuse(
        platform=Platform.NA1, match_id="NA1_ANALYSIS_FIXTURE", puuid=SELECTED_PUUID
    )
    assert created is True
    assert result.status == "completed"
    assert result.role == "mid"
    assert repository.create_calls
    assert repository.delete_calls == [NOW]
    loaded = await service.get(analysis_id=analysis_id)
    assert loaded == result


@pytest.mark.asyncio
async def test_timeline_not_found_and_upstream_failures_are_partial() -> None:
    for code in (
        "MATCH_TIMELINE_NOT_FOUND",
        "RIOT_AUTH_FAILED",
        "RIOT_RATE_LIMITED",
        "RIOT_UNAVAILABLE",
    ):
        service, repository = _service(
            timeline_service=FakeTimelineService(error=_api_error(code, status_code=503))
        )
        _analysis_id, result, created = await service.create_or_reuse(
            platform=Platform.NA1, match_id="NA1_ANALYSIS_FIXTURE", puuid=SELECTED_PUUID
        )
        assert created is True
        assert result.status == "partial"
        assert "timeline_unavailable" in result.unavailable_reasons
        assert result.metrics[-1].value is None
        assert len(repository.create_calls) == 1


@pytest.mark.asyncio
async def test_malformed_timeline_is_a_hard_failure() -> None:
    service, repository = _service(
        timeline_service=FakeTimelineService(error=_api_error("RIOT_INVALID_RESPONSE", 502))
    )
    with pytest.raises(ApiError) as raised:
        await service.create_or_reuse(
            platform=Platform.NA1, match_id="NA1_ANALYSIS_FIXTURE", puuid=SELECTED_PUUID
        )
    assert raised.value.code == "RIOT_INVALID_RESPONSE"
    assert repository.create_calls == []
    assert repository.delete_calls == []


@pytest.mark.asyncio
async def test_match_timeline_roster_mismatch_fails_before_persistence() -> None:
    timeline = standard_analysis_timeline()
    mismatched = timeline.model_copy(
        update={
            "participant_puuids": {
                participant_id: puuid
                for participant_id, puuid in timeline.participant_puuids.items()
                if puuid != SELECTED_PUUID
            }
        }
    )
    service, repository = _service(timeline_service=FakeTimelineService(snapshot=mismatched))

    with pytest.raises(ApiError) as raised:
        await service.create_or_reuse(
            platform=Platform.NA1, match_id="NA1_ANALYSIS_FIXTURE", puuid=SELECTED_PUUID
        )

    assert raised.value.code == "RIOT_INVALID_RESPONSE"
    assert repository.create_calls == []
    assert repository.delete_calls == []


@pytest.mark.asyncio
async def test_unsupported_mode_is_mapped_and_player_absence_is_preserved() -> None:
    service, _repository = _service(
        match_service=FakeMatchService(error=_api_error("MATCH_EVIDENCE_UNSUPPORTED_MODE"))
    )
    with pytest.raises(ApiError) as raised:
        await service.create_or_reuse(
            platform=Platform.NA1, match_id="NA1_ANALYSIS_FIXTURE", puuid=SELECTED_PUUID
        )
    assert raised.value.code == "MATCH_ANALYSIS_UNSUPPORTED_MODE"
    assert raised.value.status_code == 422

    service, repository = _service(
        match_service=FakeMatchService(error=_api_error("PLAYER_NOT_IN_MATCH", 404))
    )
    with pytest.raises(ApiError) as raised:
        await service.create_or_reuse(
            platform=Platform.NA1, match_id="NA1_ANALYSIS_FIXTURE", puuid="missing"
        )
    assert raised.value.code == "PLAYER_NOT_IN_MATCH"
    assert repository.create_calls == []


@pytest.mark.asyncio
async def test_identical_requests_reuse_one_key_and_input_changes_create_another() -> None:
    service, repository = _service()
    first_id, first, created = await service.create_or_reuse(
        platform=Platform.NA1, match_id="NA1_ANALYSIS_FIXTURE", puuid=SELECTED_PUUID
    )
    second_id, second, created_again = await service.create_or_reuse(
        platform=Platform.NA1, match_id="NA1_ANALYSIS_FIXTURE", puuid=SELECTED_PUUID
    )
    assert created is True
    assert created_again is False
    assert first_id == second_id
    assert first.input_hash == second.input_hash
    changed_match = standard_analysis_match().model_copy(update={"duration_seconds": 1700})
    other, other_repo = _service(match_service=FakeMatchService(snapshot=changed_match))
    _id, changed, _created = await other.create_or_reuse(
        platform=Platform.NA1, match_id="NA1_ANALYSIS_FIXTURE", puuid=SELECTED_PUUID
    )
    assert changed.input_hash != first.input_hash
    assert other_repo.create_calls[0]["key"] != repository.create_calls[0]["key"]


def test_locale_replay_and_static_data_are_absent_from_the_service_contract() -> None:
    assert "locale" not in inspect.signature(AnalysisService.create_or_reuse).parameters
    assert "replay" not in inspect.signature(AnalysisService.__init__).parameters
    assert "static" not in inspect.signature(AnalysisService.__init__).parameters
    payload = canonical_analysis_input(
        match=standard_analysis_match(),
        timeline=standard_analysis_timeline(),
        selected_puuid=SELECTED_PUUID,
    )
    assert b"locale" not in payload
    assert b"replay" not in payload
    key = analysis_idempotency_key(
        platform=Platform.NA1,
        match_id="NA1_1",
        selected_puuid=SELECTED_PUUID,
        input_hash="ab" * 32,
        metric_version=METRIC_VERSION,
        score_version=SCORE_VERSION,
        rules_version=RULES_VERSION,
    )
    other = analysis_idempotency_key(
        platform=Platform.NA1,
        match_id="NA1_1",
        selected_puuid=SELECTED_PUUID,
        input_hash="ab" * 32,
        metric_version="other",
        score_version=SCORE_VERSION,
        rules_version=RULES_VERSION,
    )
    assert key != other
    assert len(key) == 64
    assert key == key.lower()


@pytest.mark.asyncio
async def test_broken_references_and_compute_failures_never_persist() -> None:
    service, repository = _service(rule_engine=BrokenRuleEngine())
    with pytest.raises(AnalysisInvariantError):
        await service.create_or_reuse(
            platform=Platform.NA1, match_id="NA1_ANALYSIS_FIXTURE", puuid=SELECTED_PUUID
        )
    assert repository.create_calls == []
    exploding, exploding_repo = _service(metric_engine=ExplodingMetricEngine())
    with pytest.raises(RuntimeError):
        await exploding.create_or_reuse(
            platform=Platform.NA1, match_id="NA1_ANALYSIS_FIXTURE", puuid=SELECTED_PUUID
        )
    assert exploding_repo.create_calls == []
    assert exploding_repo.delete_calls == []


@pytest.mark.asyncio
async def test_unknown_role_is_partial_without_overall_score() -> None:
    match = replace_participant(standard_analysis_match(), SELECTED_PUUID, role=None)
    service, _repository = _service(match_service=FakeMatchService(snapshot=match))
    _analysis_id, result, _created = await service.create_or_reuse(
        platform=Platform.NA1, match_id="NA1_ANALYSIS_FIXTURE", puuid=SELECTED_PUUID
    )
    assert result.status == "partial"
    assert result.role is None
    assert result.scores.overall_score is None
    assert result.findings == ()
    assert "role_unavailable" in result.unavailable_reasons
