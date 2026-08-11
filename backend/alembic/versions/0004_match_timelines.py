"""add normalized match timeline cache

Revision ID: 0004_match_timelines
Revises: 0003_player_platform_detection
Create Date: 2026-08-02 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_match_timelines"
down_revision: str | Sequence[str] | None = "0003_player_platform_detection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IX_MATCH_TIMELINES_EXPIRES_AT = "ix_match_timelines_expires_at"
_CK_MATCH_TIMELINES_SCHEMA_VERSION = "ck_match_timelines_schema_version_positive"
_CK_MATCH_TIMELINES_RESULT_STATUS = "ck_match_timelines_result_status"
_CK_MATCH_TIMELINES_RESULT_SHAPE = "ck_match_timelines_result_shape"


def upgrade() -> None:
    op.create_table(
        "match_timelines",
        sa.Column("platform", sa.String(length=8), nullable=False),
        sa.Column("match_id", sa.String(length=64), nullable=False),
        sa.Column("result_status", sa.String(length=16), nullable=False),
        sa.Column("normalized_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("schema_version > 0", name=_CK_MATCH_TIMELINES_SCHEMA_VERSION),
        sa.CheckConstraint(
            "result_status IN ('available', 'not_found')",
            name=_CK_MATCH_TIMELINES_RESULT_STATUS,
        ),
        sa.CheckConstraint(
            "("
            "result_status = 'available' AND "
            "normalized_snapshot IS NOT NULL AND "
            "snapshot_hash IS NOT NULL"
            ") OR ("
            "result_status = 'not_found' AND "
            "normalized_snapshot IS NULL AND "
            "snapshot_hash IS NULL"
            ")",
            name=_CK_MATCH_TIMELINES_RESULT_SHAPE,
        ),
        sa.PrimaryKeyConstraint("platform", "match_id"),
    )
    op.create_index(
        op.f(_IX_MATCH_TIMELINES_EXPIRES_AT),
        "match_timelines",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f(_IX_MATCH_TIMELINES_EXPIRES_AT), table_name="match_timelines")
    op.drop_table("match_timelines")
