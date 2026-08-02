from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.services.replays.media import MediaLimits, ReplayMediaRunner, validate_probe

pytestmark = pytest.mark.replay_ffmpeg

if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
    pytest.skip("ffmpeg and ffprobe are not installed", allow_module_level=True)


async def _generate_test_video(ffmpeg: str, output: Path) -> None:
    import asyncio

    command = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=12:size=640x360:rate=25",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=12",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(output),
    ]
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await process.communicate()
    assert process.returncode == 0, stderr.decode("utf-8", errors="replace")


@pytest.mark.asyncio
async def test_real_ffmpeg_probe_normalize_and_extract(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    assert ffmpeg is not None
    assert ffprobe is not None

    source = tmp_path / "source.mp4"
    normalized = tmp_path / "normalized.mp4"
    await _generate_test_video(ffmpeg, source)
    assert source.is_file()
    assert source.stat().st_size > 0

    runner = ReplayMediaRunner(
        ffmpeg_path=ffmpeg,
        ffprobe_path=ffprobe,
        timeout_seconds=120,
    )
    limits = MediaLimits(min_duration_seconds=1, max_duration_seconds=30)

    probe = await runner.probe(source)
    assert 11.0 <= probe.duration_seconds <= 13.0
    assert len(probe.video_streams) == 1
    assert probe.video_streams[0].width == 640
    assert probe.video_streams[0].height == 360
    assert probe.video_streams[0].avg_frame_rate == 25.0
    assert len(probe.audio_streams) >= 1

    validated = validate_probe(probe, limits)
    assert validated.width == 640
    assert validated.height == 360
    assert validated.has_audio is True

    progress_values: list[int] = []

    async def on_progress(value: int) -> None:
        progress_values.append(value)

    await runner.normalize(source, normalized, probe, progress=on_progress)
    assert normalized.is_file()
    assert normalized.stat().st_size > 0
    # Real ffmpeg reports out_time_ms in microseconds despite the field name.
    # The callback must receive bounded, monotonic stage percentages rather
    # than jumping to 80 immediately from a raw microsecond value.
    assert progress_values
    assert progress_values[-1] == 80
    assert all(15 <= value <= 80 for value in progress_values)
    assert progress_values == sorted(progress_values)

    normalized_probe = await runner.probe(normalized)
    assert normalized_probe.video_streams[0].codec_name == "h264"
    assert normalized_probe.video_streams[0].pix_fmt == "yuv420p"
    assert "mp4" in normalized_probe.format_name
    assert abs(normalized_probe.duration_seconds - probe.duration_seconds) <= 1.0
    assert normalized_probe.video_streams[0].width <= 1280
    assert normalized_probe.video_streams[0].height <= 720
    assert normalized_probe.video_streams[0].avg_frame_rate == 30.0

    for second in (0, 5, 11):
        frame_path = tmp_path / f"frame_{second}.jpg"
        await runner.extract_frame(normalized, second * 1000, frame_path)
        assert frame_path.is_file()
        assert frame_path.stat().st_size > 0
        assert frame_path.read_bytes()[:2] == b"\xff\xd8"
