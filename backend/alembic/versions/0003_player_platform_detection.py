"""migrate player identity and add platform detection cache

Revision ID: 0003_player_platform_detection
Revises: 0002_replay_r1
Create Date: 2026-08-02 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_player_platform_detection"
down_revision: str | Sequence[str] | None = "0002_replay_r1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UQ_PLAYERS_PLATFORM_PUUID = "uq_players_platform_puuid"
_UQ_DETECTION_LOOKUP = "uq_player_platform_detections_lookup_key"
_IX_DETECTION_EXPIRES_AT = "ix_player_platform_detections_expires_at"
_CK_DETECTION_RESULT_SHAPE = "ck_player_platform_detections_result_shape"


def _drop_players_puuid_unique() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for constraint in inspector.get_unique_constraints("players"):
        if constraint["column_names"] == ["puuid"]:
            op.drop_constraint(constraint["name"], "players", type_="unique")
            return
    for index in inspector.get_indexes("players"):
        if index.get("unique") and index["column_names"] == ["puuid"]:
            op.drop_index(index["name"], table_name="players")
            return
    raise RuntimeError("expected a unique constraint or index on players.puuid")


def _ensure_players_puuid_index() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for index in inspector.get_indexes("players"):
        if index["column_names"] == ["puuid"] and not index.get("unique"):
            return
    op.create_index(op.f("ix_players_puuid"), "players", ["puuid"], unique=False)


def _drop_players_platform_puuid_unique() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for constraint in inspector.get_unique_constraints("players"):
        if constraint["column_names"] == ["platform", "puuid"]:
            op.drop_constraint(constraint["name"], "players", type_="unique")
            return
    for index in inspector.get_indexes("players"):
        if index.get("unique") and index["column_names"] == ["platform", "puuid"]:
            op.drop_index(index["name"], table_name="players")
            return
    raise RuntimeError("expected a unique constraint or index on players.(platform, puuid)")


def upgrade() -> None:
    _drop_players_puuid_unique()
    _ensure_players_puuid_index()
    op.create_unique_constraint(_UQ_PLAYERS_PLATFORM_PUUID, "players", ["platform", "puuid"])

    op.create_table(
        "player_platform_detections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("game_name_key", sa.String(length=128), nullable=False),
        sa.Column("tag_line_key", sa.String(length=64), nullable=False),
        sa.Column("canonical_game_name", sa.String(length=128), nullable=True),
        sa.Column("canonical_tag_line", sa.String(length=64), nullable=True),
        sa.Column("puuid", sa.String(length=128), nullable=True),
        sa.Column("result_status", sa.String(length=16), nullable=False),
        sa.Column(
            "candidate_platforms",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmation_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "("
            "result_status = 'resolved' AND "
            "puuid IS NOT NULL AND "
            "jsonb_typeof(candidate_platforms) = 'array' AND "
            "jsonb_array_length(candidate_platforms) = 1 AND "
            "confirmation_expires_at IS NULL"
            ") OR ("
            "result_status = 'ambiguous' AND "
            "puuid IS NOT NULL AND "
            "jsonb_typeof(candidate_platforms) = 'array' AND "
            "jsonb_array_length(candidate_platforms) >= 2 AND "
            "confirmation_expires_at IS NOT NULL"
            ") OR ("
            "result_status = 'not_found' AND "
            "puuid IS NULL AND "
            "canonical_game_name IS NULL AND "
            "canonical_tag_line IS NULL AND "
            "candidate_platforms = '[]'::jsonb AND "
            "confirmation_expires_at IS NULL"
            ")",
            name=_CK_DETECTION_RESULT_SHAPE,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_name_key", "tag_line_key", name=_UQ_DETECTION_LOOKUP),
    )
    op.create_index(
        op.f(_IX_DETECTION_EXPIRES_AT),
        "player_platform_detections",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f(_IX_DETECTION_EXPIRES_AT), table_name="player_platform_detections")
    op.drop_table("player_platform_detections")

    _drop_players_platform_puuid_unique()
    op.create_unique_constraint("players_puuid_key", "players", ["puuid"])
    _ensure_players_puuid_index()
