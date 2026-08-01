"""add replay r1 upload, job, and artifact tables

Revision ID: 0002_replay_r1
Revises: 0001_phase_2_riot_cache
Create Date: 2026-08-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_replay_r1"
down_revision: str | Sequence[str] | None = "0001_phase_2_riot_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "replay_uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_id", sa.String(length=32), nullable=False),
        sa.Column("platform", sa.String(length=8), nullable=False),
        sa.Column("selected_puuid", sa.String(length=128), nullable=True),
        sa.Column("match_duration_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("processing_stage", sa.String(length=64), nullable=True),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=True),
        sa.Column("original_filename", sa.String(length=512), nullable=True),
        sa.Column("declared_content_type", sa.String(length=128), nullable=True),
        sa.Column("declared_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("actual_container", sa.String(length=64), nullable=True),
        sa.Column("actual_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=True),
        sa.Column("source_duration_ms", sa.Integer(), nullable=True),
        sa.Column("normalized_duration_ms", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("frame_rate_numerator", sa.Integer(), nullable=True),
        sa.Column("frame_rate_denominator", sa.Integer(), nullable=True),
        sa.Column("game_time_zero_ms", sa.Integer(), nullable=False),
        sa.Column("available_game_time_start_ms", sa.Integer(), nullable=True),
        sa.Column("available_game_time_end_ms", sa.Integer(), nullable=True),
        sa.Column("source_object_key", sa.String(length=512), nullable=True),
        sa.Column("normalized_object_key", sa.String(length=512), nullable=True),
        sa.Column("rights_statement_version", sa.String(length=32), nullable=False),
        sa.Column("rights_attested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("upload_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_delete_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("derived_delete_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "warning_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_retryable", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_replay_uploads_progress_percent",
        ),
        sa.CheckConstraint("match_duration_ms >= 0", name="ck_replay_uploads_match_duration_ms"),
        sa.CheckConstraint("declared_size_bytes >= 0", name="ck_replay_uploads_declared_size"),
        sa.CheckConstraint(
            "actual_size_bytes IS NULL OR actual_size_bytes >= 0",
            name="ck_replay_uploads_actual_size",
        ),
        sa.CheckConstraint("game_time_zero_ms >= 0", name="ck_replay_uploads_game_time_zero"),
        sa.CheckConstraint(
            "source_duration_ms IS NULL OR source_duration_ms >= 0",
            name="ck_replay_uploads_source_duration",
        ),
        sa.CheckConstraint(
            "normalized_duration_ms IS NULL OR normalized_duration_ms >= 0",
            name="ck_replay_uploads_normalized_duration",
        ),
        sa.CheckConstraint(
            "available_game_time_start_ms IS NULL OR available_game_time_start_ms >= 0",
            name="ck_replay_uploads_available_start",
        ),
        sa.CheckConstraint(
            "available_game_time_end_ms IS NULL OR available_game_time_end_ms >= 0",
            name="ck_replay_uploads_available_end",
        ),
        sa.CheckConstraint("version >= 1", name="ck_replay_uploads_version"),
        sa.CheckConstraint(
            "status = 'deleted' OR ("
            "selected_puuid IS NOT NULL AND "
            "token_digest IS NOT NULL AND "
            "original_filename IS NOT NULL AND "
            "declared_content_type IS NOT NULL"
            ")",
            name="ck_replay_uploads_active_sensitive_fields",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_replay_uploads_match_id"), "replay_uploads", ["match_id"], unique=False
    )
    op.create_index(
        op.f("ix_replay_uploads_platform"), "replay_uploads", ["platform"], unique=False
    )
    op.create_index(op.f("ix_replay_uploads_status"), "replay_uploads", ["status"], unique=False)
    op.create_index(
        op.f("ix_replay_uploads_upload_expires_at"),
        "replay_uploads",
        ["upload_expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_replay_uploads_source_delete_after"),
        "replay_uploads",
        ["source_delete_after"],
        unique=False,
    )
    op.create_index(
        op.f("ix_replay_uploads_derived_delete_after"),
        "replay_uploads",
        ["derived_delete_after"],
        unique=False,
    )
    op.create_index(
        op.f("ix_replay_uploads_deleted_at"),
        "replay_uploads",
        ["deleted_at"],
        unique=False,
    )

    op.create_table(
        "replay_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("replay_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempt_count >= 0", name="ck_replay_jobs_attempt_count"),
        sa.CheckConstraint("max_attempts >= 1", name="ck_replay_jobs_max_attempts"),
        sa.ForeignKeyConstraint(["replay_id"], ["replay_uploads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_replay_jobs_replay_id"), "replay_jobs", ["replay_id"], unique=False)
    op.create_index(op.f("ix_replay_jobs_status"), "replay_jobs", ["status"], unique=False)
    op.create_index(
        op.f("ix_replay_jobs_available_at"),
        "replay_jobs",
        ["available_at"],
        unique=False,
    )
    op.create_index(
        "uq_replay_active_job",
        "replay_jobs",
        ["replay_id", "kind"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running', 'retry_scheduled')"),
    )

    op.create_table(
        "replay_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("replay_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("game_time_ms", sa.Integer(), nullable=False),
        sa.Column("video_time_ms", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delete_after", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("game_time_ms >= 0", name="ck_replay_artifacts_game_time"),
        sa.CheckConstraint("video_time_ms >= 0", name="ck_replay_artifacts_video_time"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_replay_artifacts_size"),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_replay_artifacts_duration",
        ),
        sa.ForeignKeyConstraint(["replay_id"], ["replay_uploads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "replay_id",
            "kind",
            "game_time_ms",
            "video_time_ms",
            name="uq_replay_artifact_timestamp",
        ),
    )
    op.create_index(
        op.f("ix_replay_artifacts_replay_id"),
        "replay_artifacts",
        ["replay_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_replay_artifacts_delete_after"),
        "replay_artifacts",
        ["delete_after"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_replay_artifacts_delete_after"), table_name="replay_artifacts")
    op.drop_index(op.f("ix_replay_artifacts_replay_id"), table_name="replay_artifacts")
    op.drop_table("replay_artifacts")
    op.drop_index("uq_replay_active_job", table_name="replay_jobs")
    op.drop_index(op.f("ix_replay_jobs_available_at"), table_name="replay_jobs")
    op.drop_index(op.f("ix_replay_jobs_status"), table_name="replay_jobs")
    op.drop_index(op.f("ix_replay_jobs_replay_id"), table_name="replay_jobs")
    op.drop_table("replay_jobs")
    op.drop_index(op.f("ix_replay_uploads_deleted_at"), table_name="replay_uploads")
    op.drop_index(op.f("ix_replay_uploads_derived_delete_after"), table_name="replay_uploads")
    op.drop_index(op.f("ix_replay_uploads_source_delete_after"), table_name="replay_uploads")
    op.drop_index(op.f("ix_replay_uploads_upload_expires_at"), table_name="replay_uploads")
    op.drop_index(op.f("ix_replay_uploads_status"), table_name="replay_uploads")
    op.drop_index(op.f("ix_replay_uploads_platform"), table_name="replay_uploads")
    op.drop_index(op.f("ix_replay_uploads_match_id"), table_name="replay_uploads")
    op.drop_table("replay_uploads")
