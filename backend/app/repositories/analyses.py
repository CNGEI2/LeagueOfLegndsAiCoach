from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ApiError
from app.models.analysis import AnalysisEvidenceRow, AnalysisJobRow
from app.services.analyses.domain import DeterministicAnalysisResult

_SHA256 = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class StoredAnalysis:
    analysis_id: UUID
    idempotency_key: str
    result: DeterministicAnalysisResult
    created_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _validate_timezone(self.created_at, "created_at")
        _validate_timezone(self.expires_at, "expires_at")
        _validate_sha256(self.idempotency_key, "idempotency_key")
        _validate_sha256(self.result.input_hash, "input_hash")


class AnalysisRepository(Protocol):
    async def get(self, *, analysis_id: UUID, now: datetime) -> StoredAnalysis | None: ...

    async def create_or_reuse(
        self,
        *,
        idempotency_key: str,
        result: DeterministicAnalysisResult,
        now: datetime,
        expires_at: datetime,
    ) -> tuple[StoredAnalysis, bool]: ...

    async def delete_expired(self, *, now: datetime) -> int: ...


class SqlAnalysisRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, *, analysis_id: UUID, now: datetime) -> StoredAnalysis | None:
        _validate_timezone(now, "now")
        statement = (
            select(AnalysisJobRow, AnalysisEvidenceRow)
            .join(AnalysisEvidenceRow, AnalysisEvidenceRow.analysis_id == AnalysisJobRow.id)
            .where(AnalysisJobRow.id == analysis_id, AnalysisJobRow.expires_at > now)
        )
        async with self._session_factory() as session:
            row = (await session.execute(statement)).one_or_none()
        if row is None:
            return None
        job, evidence = row
        return _stored_from_rows(job, evidence)

    async def create_or_reuse(
        self,
        *,
        idempotency_key: str,
        result: DeterministicAnalysisResult,
        now: datetime,
        expires_at: datetime,
    ) -> tuple[StoredAnalysis, bool]:
        _validate_timezone(now, "now")
        _validate_timezone(expires_at, "expires_at")
        _validate_sha256(idempotency_key, "idempotency_key")
        _validate_sha256(result.input_hash, "input_hash")
        analysis_id = uuid4()
        job_values = {
            "id": analysis_id,
            "platform": result.platform.value,
            "match_id": result.match_id,
            "selected_puuid": result.selected_puuid,
            "idempotency_key": idempotency_key,
            "input_hash": result.input_hash,
            "status": result.status,
            "metric_version": result.metric_version,
            "score_version": result.score_version,
            "rules_version": result.rules_version,
            "created_at": now,
            "updated_at": now,
            "completed_at": now,
            "expires_at": expires_at,
        }
        insert_job = (
            insert(AnalysisJobRow)
            .values(**job_values)
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(AnalysisJobRow)
        )
        async with self._session_factory.begin() as session:
            inserted = (await session.execute(insert_job)).scalar_one_or_none()
            if inserted is not None:
                session.add(
                    AnalysisEvidenceRow(
                        analysis_id=inserted.id,
                        evidence_catalog=[
                            metric.model_dump(mode="json") for metric in result.metrics
                        ],
                        deterministic_result=result.model_dump(mode="json"),
                        input_hash=result.input_hash,
                        schema_version=int(result.schema_version),
                        created_at=now,
                    )
                )
                await session.flush()
                return StoredAnalysis(
                    analysis_id=inserted.id,
                    idempotency_key=inserted.idempotency_key,
                    result=result,
                    created_at=inserted.created_at,
                    expires_at=inserted.expires_at,
                ), True
            winner = (
                await session.execute(
                    select(AnalysisJobRow, AnalysisEvidenceRow)
                    .join(
                        AnalysisEvidenceRow,
                        AnalysisEvidenceRow.analysis_id == AnalysisJobRow.id,
                    )
                    .where(AnalysisJobRow.idempotency_key == idempotency_key)
                )
            ).one_or_none()
            if winner is None:
                raise _persistence_error()
            job, evidence = winner
            stored = _stored_from_rows(job, evidence)
            _assert_reuse_matches(stored, result)
            return stored, False

    async def delete_expired(self, *, now: datetime) -> int:
        _validate_timezone(now, "now")
        async with self._session_factory.begin() as session:
            deleted = await session.execute(
                delete(AnalysisJobRow).where(AnalysisJobRow.expires_at <= now)
            )
        return _rowcount(deleted)


def _validate_timezone(value: datetime, field_name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _validate_sha256(value: str, field_name: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")


def _rowcount(result: object) -> int:
    return cast(CursorResult[object], result).rowcount


def _persistence_error() -> ApiError:
    return ApiError(
        status_code=500,
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected error occurred.",
        retryable=True,
    )


def _parse_result(payload: object) -> DeterministicAnalysisResult:
    try:
        return DeterministicAnalysisResult.model_validate(payload)
    except ValidationError as error:
        raise _persistence_error() from error


def _stored_from_rows(job: AnalysisJobRow, evidence: AnalysisEvidenceRow) -> StoredAnalysis:
    result = _parse_result(evidence.deterministic_result)
    if (
        job.input_hash != result.input_hash
        or evidence.input_hash != result.input_hash
        or job.metric_version != result.metric_version
        or job.score_version != result.score_version
        or job.rules_version != result.rules_version
        or evidence.schema_version != result.schema_version
        or job.status != result.status
    ):
        raise _persistence_error()
    return StoredAnalysis(
        analysis_id=job.id,
        idempotency_key=job.idempotency_key,
        result=result,
        created_at=job.created_at,
        expires_at=job.expires_at,
    )


def _assert_reuse_matches(stored: StoredAnalysis, requested: DeterministicAnalysisResult) -> None:
    if (
        stored.result.input_hash != requested.input_hash
        or stored.result.metric_version != requested.metric_version
        or stored.result.score_version != requested.score_version
        or stored.result.rules_version != requested.rules_version
        or stored.result.schema_version != requested.schema_version
    ):
        raise _persistence_error()
