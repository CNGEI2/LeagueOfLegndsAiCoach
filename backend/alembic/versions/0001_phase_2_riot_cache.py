"""add PostgreSQL Riot cache tables

Revision ID: 0001_phase_2_riot_cache
Revises:
Create Date: 2026-07-30 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_phase_2_riot_cache"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "players",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("puuid", sa.String(length=128), nullable=False),
        sa.Column("platform", sa.String(length=8), nullable=False),
        sa.Column("game_name", sa.String(length=128), nullable=False),
        sa.Column("tag_line", sa.String(length=64), nullable=False),
        sa.Column("game_name_key", sa.String(length=128), nullable=False),
        sa.Column("tag_line_key", sa.String(length=64), nullable=False),
        sa.Column("summoner_level", sa.Integer(), nullable=False),
        sa.Column("profile_icon_id", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("puuid"),
    )
    op.create_index(op.f("ix_players_puuid"), "players", ["puuid"], unique=False)
    op.create_index(op.f("ix_players_platform"), "players", ["platform"], unique=False)
    op.create_index(op.f("ix_players_game_name_key"), "players", ["game_name_key"], unique=False)
    op.create_index(op.f("ix_players_tag_line_key"), "players", ["tag_line_key"], unique=False)
    op.create_index(op.f("ix_players_fetched_at"), "players", ["fetched_at"], unique=False)

    op.create_table(
        "recent_match_caches",
        sa.Column("platform", sa.String(length=8), nullable=False),
        sa.Column("puuid", sa.String(length=128), nullable=False),
        sa.Column("match_ids", postgresql.ARRAY(sa.String(length=32)), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("platform", "puuid"),
    )
    op.create_index(
        op.f("ix_recent_match_caches_expires_at"),
        "recent_match_caches",
        ["expires_at"],
        unique=False,
    )

    op.create_table(
        "matches",
        sa.Column("match_id", sa.String(length=32), nullable=False),
        sa.Column("platform", sa.String(length=8), nullable=False),
        sa.Column("queue_id", sa.Integer(), nullable=False),
        sa.Column("game_version", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("match_id"),
    )
    op.create_index(op.f("ix_matches_platform"), "matches", ["platform"], unique=False)
    op.create_index(op.f("ix_matches_fetched_at"), "matches", ["fetched_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_matches_fetched_at"), table_name="matches")
    op.drop_index(op.f("ix_matches_platform"), table_name="matches")
    op.drop_table("matches")
    op.drop_index(op.f("ix_recent_match_caches_expires_at"), table_name="recent_match_caches")
    op.drop_table("recent_match_caches")
    op.drop_index(op.f("ix_players_fetched_at"), table_name="players")
    op.drop_index(op.f("ix_players_tag_line_key"), table_name="players")
    op.drop_index(op.f("ix_players_game_name_key"), table_name="players")
    op.drop_index(op.f("ix_players_platform"), table_name="players")
    op.drop_index(op.f("ix_players_puuid"), table_name="players")
    op.drop_table("players")
