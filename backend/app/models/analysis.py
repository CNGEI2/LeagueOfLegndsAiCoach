from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AnalysisJobRow(Base):
    __tablename__ = "analysis_jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_analysis_jobs_idempotency_key"),
        Index(
            "ix_analysis_jobs_platform_match_puuid",
            "platform",
            "match_id",
            "selected_puuid",
        ),
        CheckConstraint("status IN ('completed', 'partial')", name="ck_analysis_jobs_status"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    platform: Mapped[str] = mapped_column(String(8))
    match_id: Mapped[str] = mapped_column(String(64))
    selected_puuid: Mapped[str] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    metric_version: Mapped[str] = mapped_column(String(64))
    score_version: Mapped[str] = mapped_column(String(64))
    rules_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AnalysisEvidenceRow(Base):
    __tablename__ = "analysis_evidence"
    __table_args__ = (
        CheckConstraint("schema_version > 0", name="ck_analysis_evidence_schema_version"),
    )

    analysis_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("analysis_jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    evidence_catalog: Mapped[list[object]] = mapped_column(JSONB)
    deterministic_result: Mapped[dict[str, object]] = mapped_column(JSONB)
    input_hash: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
