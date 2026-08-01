import pytest

from app.services.replays.domain import (
    ReplayCoverage,
    calculate_coverage,
    game_to_video_time,
    video_to_game_time,
)


def test_time_mapping_and_partial_coverage() -> None:
    assert game_to_video_time(60_000, 48_231) == 108_231
    assert video_to_game_time(108_231, 48_231) == 60_000
    assert calculate_coverage(1_000_000, 50_000, 1_800_000) == ReplayCoverage(
        start_ms=0, end_ms=950_000, partial=True
    )


def test_full_coverage_when_video_covers_match() -> None:
    assert calculate_coverage(2_000_000, 50_000, 1_800_000) == ReplayCoverage(
        start_ms=0, end_ms=1_800_000, partial=False
    )


def test_coverage_rejects_negative_times() -> None:
    with pytest.raises(ValueError):
        calculate_coverage(-1, 0, 1_000)
    with pytest.raises(ValueError):
        calculate_coverage(1_000, -1, 1_000)
    with pytest.raises(ValueError):
        calculate_coverage(1_000, 0, -1)


def test_coverage_rejects_anchor_outside_video() -> None:
    with pytest.raises(ValueError):
        calculate_coverage(1_000, 1_000, 1_800_000)
    with pytest.raises(ValueError):
        calculate_coverage(1_000, 1_001, 1_800_000)


def test_time_mapping_rejects_negative_inputs() -> None:
    with pytest.raises(ValueError):
        game_to_video_time(-1, 0)
    with pytest.raises(ValueError):
        game_to_video_time(0, -1)
    with pytest.raises(ValueError):
        video_to_game_time(-1, 0)
