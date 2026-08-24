import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ApiError
from app.models.analysis import AnalysisEvidenceRow, AnalysisJobRow
from app.repositories.analyses import SqlAnalysisRepository
from app.services.analyses.domain import DeterministicAnalysisResult
from tests.test_analysis_repository_contract import VALID_KEY, make_analysis_result

pytestmark = pytest.mark.integration


def _now() -> datetime:
    return datetime.now(UTC)


async def _count(session_factory: async_sessionmaker[AsyncSession], model: type[object]) -> int:
    async with session_factory() as session:
        return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


@pytest.mark.asyncio
async def test_create_or_reuse_inserts_once_and_reuses_the_same_uuid(session_factory) -> None:
    repository = SqlAnalysisRepository(session_factory)
    now = _now()
    result = make_analysis_result()
    first, created = await repository.create_or_reuse(
        idempotency_key=VALID_KEY,
        result=result,
        now=now,
        expires_at=now + timedelta(days=30),
    )
    second, created_again = await repository.create_or_reuse(
        idempotency_key=VALID_KEY,
        result=result,
        now=now,
        expires_at=now + timedelta(days=30),
    )
    assert created is True
    assert created_again is False
    assert first.analysis_id == second.analysis_id
    assert first.result == result
    restored = DeterministicAnalysisResult.model_validate(second.result.model_dump(mode="json"))
    assert restored == result


@pytest.mark.asyncio
async def test_concurrent_identical_inserts_create_one_job_and_one_evidence_row(
    session_factory,
) -> None:
    repository = SqlAnalysisRepository(session_factory)
    now = _now()
    result = make_analysis_result(match_id="NA1_concurrent")
    key = "cd" * 32

    async def _attempt() -> tuple[object, bool]:
        return await repository.create_or_reuse(
            idempotency_key=key,
            result=result,
            now=now,
            expires_at=now + timedelta(days=30),
        )

    outcomes = await asyncio.gather(*[_attempt() for _ in range(10)])
    ids = {stored.analysis_id for stored, _created in outcomes}
    assert len(ids) == 1
    assert sum(created for _stored, created in outcomes) == 1
    assert await _count(session_factory, AnalysisJobRow) == 1
    assert await _count(session_factory, AnalysisEvidenceRow) == 1


@pytest.mark.asyncio
async def test_get_round_trips_and_hides_expired_rows(session_factory) -> None:
    repository = SqlAnalysisRepository(session_factory)
    now = _now()
    stored, created = await repository.create_or_reuse(
        idempotency_key="ef" * 32,
        result=make_analysis_result(match_id="NA1_expired"),
        now=now - timedelta(days=31),
        expires_at=now - timedelta(seconds=1),
    )
    assert created is True
    assert await repository.get(analysis_id=stored.analysis_id, now=now) is None
    deleted = await repository.delete_expired(now=now)
    assert deleted == 1
    assert await _count(session_factory, AnalysisJobRow) == 0
    assert await _count(session_factory, AnalysisEvidenceRow) == 0


@pytest.mark.asyncio
async def test_create_after_expiry_replaces_the_conflicting_idempotency_row(
    session_factory,
) -> None:
    repository = SqlAnalysisRepository(session_factory)
    now = _now()
    result = make_analysis_result(match_id="NA1_expired_reuse")
    expired, created = await repository.create_or_reuse(
        idempotency_key="bd" * 32,
        result=result,
        now=now - timedelta(days=31),
        expires_at=now - timedelta(seconds=1),
    )
    assert created is True

    fresh, created_again = await repository.create_or_reuse(
        idempotency_key="bd" * 32,
        result=result,
        now=now,
        expires_at=now + timedelta(days=30),
    )

    assert created_again is True
    assert fresh.analysis_id != expired.analysis_id
    assert await repository.get(analysis_id=expired.analysis_id, now=now) is None
    assert await repository.get(analysis_id=fresh.analysis_id, now=now) == fresh
    assert await _count(session_factory, AnalysisJobRow) == 1
    assert await _count(session_factory, AnalysisEvidenceRow) == 1


@pytest.mark.asyncio
async def test_deleting_analysis_jobs_cascades_to_evidence(session_factory) -> None:
    repository = SqlAnalysisRepository(session_factory)
    now = _now()
    stored, _created = await repository.create_or_reuse(
        idempotency_key="aa" * 32,
        result=make_analysis_result(match_id="NA1_cascade"),
        now=now,
        expires_at=now + timedelta(days=30),
    )
    async with session_factory.begin() as session:
        await session.execute(
            text("DELETE FROM analysis_jobs WHERE id = CAST(:id AS uuid)"),
            {"id": str(stored.analysis_id)},
        )
    assert await _count(session_factory, AnalysisEvidenceRow) == 0


@pytest.mark.asyncio
async def test_mismatched_winning_row_is_an_internal_persistence_error(session_factory) -> None:
    repository = SqlAnalysisRepository(session_factory)
    now = _now()
    result = make_analysis_result()
    await repository.create_or_reuse(
        idempotency_key=VALID_KEY,
        result=result,
        now=now,
        expires_at=now + timedelta(days=30),
    )
    with pytest.raises(ApiError) as exc_info:
        await repository.create_or_reuse(
            idempotency_key=VALID_KEY,
            result=make_analysis_result(input_hash="ff" * 32),
            now=now,
            expires_at=now + timedelta(days=30),
        )
    assert exc_info.value.code == "INTERNAL_SERVER_ERROR"


@pytest.mark.asyncio
async def test_get_rejects_evidence_catalog_drift(session_factory) -> None:
    repository = SqlAnalysisRepository(session_factory)
    now = _now()
    stored, _created = await repository.create_or_reuse(
        idempotency_key="ce" * 32,
        result=make_analysis_result(match_id="NA1_catalog_drift"),
        now=now,
        expires_at=now + timedelta(days=30),
    )
    async with session_factory.begin() as session:
        await session.execute(
            update(AnalysisEvidenceRow)
            .where(AnalysisEvidenceRow.analysis_id == stored.analysis_id)
            .values(evidence_catalog=[])
        )

    with pytest.raises(ApiError) as exc_info:
        await repository.get(analysis_id=stored.analysis_id, now=now)
    assert exc_info.value.code == "INTERNAL_SERVER_ERROR"


@pytest.mark.asyncio
async def test_get_rejects_job_identity_drift(session_factory) -> None:
    repository = SqlAnalysisRepository(session_factory)
    now = _now()
    stored, _created = await repository.create_or_reuse(
        idempotency_key="cf" * 32,
        result=make_analysis_result(match_id="NA1_identity_drift"),
        now=now,
        expires_at=now + timedelta(days=30),
    )
    async with session_factory.begin() as session:
        await session.execute(
            update(AnalysisJobRow)
            .where(AnalysisJobRow.id == stored.analysis_id)
            .values(match_id="NA1_other")
        )

    with pytest.raises(ApiError) as exc_info:
        await repository.get(analysis_id=stored.analysis_id, now=now)
    assert exc_info.value.code == "INTERNAL_SERVER_ERROR"


@pytest.mark.parametrize("drift", ["duplicate_comparison", "invalid_overall"])
@pytest.mark.asyncio
async def test_get_rejects_invalid_result_invariants(session_factory, drift: str) -> None:
    repository = SqlAnalysisRepository(session_factory)
    now = _now()
    stored, _created = await repository.create_or_reuse(
        idempotency_key=("d0" if drift == "duplicate_comparison" else "d1") * 32,
        result=make_analysis_result(match_id="NA1_result_drift"),
        now=now,
        expires_at=now + timedelta(days=30),
    )
    payload = stored.result.model_dump(mode="json")
    if drift == "duplicate_comparison":
        comparison = {
            "basis": "team_percentile",
            "score": 50.0,
            "opponent_value": None,
        }
        payload["metrics"][0]["comparisons"] = [comparison, comparison]
    else:
        payload["role"] = None
        payload["scores"]["role"] = None
    async with session_factory.begin() as session:
        await session.execute(
            update(AnalysisEvidenceRow)
            .where(AnalysisEvidenceRow.analysis_id == stored.analysis_id)
            .values(deterministic_result=payload)
        )

    with pytest.raises(ApiError) as exc_info:
        await repository.get(analysis_id=stored.analysis_id, now=now)
    assert exc_info.value.code == "INTERNAL_SERVER_ERROR"
