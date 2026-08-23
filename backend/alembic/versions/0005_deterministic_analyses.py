"""add deterministic analysis storage

Revision ID: 0005_deterministic_analyses
Revises: 0004_match_timelines
Create Date: 2026-08-22 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_deterministic_analyses"
down_revision: str | Sequence[str] | None = "0004_match_timelines"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IX_ANALYSIS_JOBS_EXPIRES_AT = "ix_analysis_jobs_expires_at"
_IX_ANALYSIS_JOBS_PLATFORM_MATCH_PUUID = "ix_analysis_jobs_platform_match_puuid"
_UQ_ANALYSIS_JOBS_IDEMPOTENCY_KEY = "uq_analysis_jobs_idempotency_key"
_CK_ANALYSIS_JOBS_STATUS = "ck_analysis_jobs_status"
_CK_ANALYSIS_EVIDENCE_SCHEMA_VERSION = "ck_analysis_evidence_schema_version"


def upgrade() -> None:
    op.create_table(
        "analysis_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.String(length=8), nullable=False),
        sa.Column("match_id", sa.String(length=64), nullable=False),
        sa.Column("selected_puuid", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("metric_version", sa.String(length=64), nullable=False),
        sa.Column("score_version", sa.String(length=64), nullable=False),
        sa.Column("rules_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('completed', 'partial')", name=_CK_ANALYSIS_JOBS_STATUS),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name=_UQ_ANALYSIS_JOBS_IDEMPOTENCY_KEY),
    )
    op.create_index(
        op.f(_IX_ANALYSIS_JOBS_EXPIRES_AT),
        "analysis_jobs",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f(_IX_ANALYSIS_JOBS_PLATFORM_MATCH_PUUID),
        "analysis_jobs",
        ["platform", "match_id", "selected_puuid"],
        unique=False,
    )
    op.create_table(
        "analysis_evidence",
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_catalog", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("deterministic_result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("schema_version > 0", name=_CK_ANALYSIS_EVIDENCE_SCHEMA_VERSION),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["analysis_jobs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("analysis_id"),
    )


def downgrade() -> None:
    op.drop_table("analysis_evidence")
    op.drop_index(op.f(_IX_ANALYSIS_JOBS_PLATFORM_MATCH_PUUID), table_name="analysis_jobs")
    op.drop_index(op.f(_IX_ANALYSIS_JOBS_EXPIRES_AT), table_name="analysis_jobs")
    op.drop_table("analysis_jobs")
