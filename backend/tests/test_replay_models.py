from datetime import UTC, datetime

from app.models.replay import ReplayUploadRow
from app.services.replays.domain import ReplayStatus


def test_replay_model_maps_security_sensitive_fields_explicitly() -> None:
    row = ReplayUploadRow(
        match_id="NA1_1",
        platform="NA1",
        selected_puuid="private",
        match_duration_ms=1_800_000,
        token_digest="a" * 64,
        original_filename="owned.mp4",
        declared_content_type="video/mp4",
        declared_size_bytes=100,
        game_time_zero_ms=1_000,
        rights_statement_version="2026-08-01",
        rights_attested_at=datetime.now(UTC),
        upload_expires_at=datetime.now(UTC),
        status=ReplayStatus.CREATED.value,
        progress_percent=0,
        warning_codes=[],
        version=1,
    )
    assert row.status == ReplayStatus.CREATED.value
    assert row.progress_percent == 0
    assert row.selected_puuid == "private"
    assert row.token_digest == "a" * 64
    assert row.original_filename == "owned.mp4"
