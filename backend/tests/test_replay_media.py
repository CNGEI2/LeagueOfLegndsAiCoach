from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from app.services.replays.media import (
    AudioStreamProbe,
    MediaLimits,
    MediaProbe,
    ReplayMediaError,
    ReplayMediaRunner,
    ValidatedMedia,
    VideoStreamProbe,
    build_extract_frame_command,
    build_ffprobe_command,
    build_normalize_command,
    parse_progress_out_time_ms,
    progress_percent_from_out_time,
    validate_probe,
)


def _video(
    *,
    width: int = 1280,
    height: int = 720,
    fps: float = 30.0,
    index: int = 0,
) -> VideoStreamProbe:
    return VideoStreamProbe(
        index=index,
        width=width,
        height=height,
        codec_name="h264",
        avg_frame_rate=fps,
        pix_fmt="yuv420p",
    )


def _audio(*, index: int = 1, codec_name: str = "aac") -> AudioStreamProbe:
    return AudioStreamProbe(index=index, codec_name=codec_name, channels=2)


def _probe(
    *,
    duration_seconds: float = 1800.0,
    video_streams: tuple[VideoStreamProbe, ...] | None = None,
    audio_streams: tuple[AudioStreamProbe, ...] = (),
    other_stream_types: tuple[str, ...] = (),
    format_name: str = "mov,mp4,m4a,3gp,3g2,mj2",
) -> MediaProbe:
    return MediaProbe(
        duration_seconds=duration_seconds,
        format_name=format_name,
        video_streams=video_streams if video_streams is not None else (_video(),),
        audio_streams=audio_streams,
        other_stream_types=other_stream_types,
    )


def test_ffprobe_command_is_list_without_shell() -> None:
    command = build_ffprobe_command("ffprobe", Path("/tmp/input.mp4"))
    assert isinstance(command, list)
    assert all(isinstance(part, str) for part in command)
    assert command[:4] == ["ffprobe", "-v", "error", "-print_format"]
    assert "json" in command
    assert "-show_streams" in command
    assert "-show_format" in command
    assert str(Path("/tmp/input.mp4")) in command


def test_normalize_command_includes_required_flags() -> None:
    command = build_normalize_command(
        "ffmpeg",
        Path("/tmp/input.mp4"),
        Path("/tmp/output.mp4"),
    )
    assert isinstance(command, list)
    assert command[0] == "ffmpeg"
    assert "libx264" in command
    assert "yuv420p" in command
    assert "+faststart" in command
    assert "-map" in command
    assert "0:v:0" in command
    assert "0:a:0?" in command
    assert "-c:v" in command
    assert "-pix_fmt" in command
    assert "-vf" in command
    vf = command[command.index("-vf") + 1]
    assert "fps=30" in vf
    assert "setpts=PTS-STARTPTS" in vf
    assert "1280" in vf and "720" in vf
    assert "-fps_mode" in command
    assert "cfr" in command
    assert "-movflags" in command
    assert "-c:a" in command
    assert "aac" in command
    assert "-ac" in command
    assert "2" in command
    assert "-b:a" in command
    assert "128k" in command
    assert "-af" in command
    assert command[command.index("-af") + 1] == "asetpts=PTS-STARTPTS"
    assert "-progress" in command
    assert "pipe:1" in command
    assert "-nostats" in command


def test_extract_frame_command_seeks_and_strips_metadata() -> None:
    command = build_extract_frame_command(
        "ffmpeg",
        Path("/tmp/input.mp4"),
        video_time_ms=5500,
        output_path=Path("/tmp/frame.jpg"),
    )
    assert command[0] == "ffmpeg"
    assert "-ss" in command
    assert command[command.index("-ss") + 1] == "5.5"
    assert "-frames:v" in command
    assert "1" in command
    assert "-map_metadata" in command
    assert "-1" in command
    vf = command[command.index("-vf") + 1]
    assert "1280" in vf and "720" in vf


@pytest.mark.parametrize(
    ("probe", "limits", "expect_ok", "error_code"),
    [
        (_probe(duration_seconds=599), MediaLimits(), False, "REPLAY_DURATION_UNSUPPORTED"),
        (_probe(duration_seconds=600), MediaLimits(), True, None),
        (_probe(duration_seconds=5400), MediaLimits(), True, None),
        (_probe(duration_seconds=5401), MediaLimits(), False, "REPLAY_DURATION_UNSUPPORTED"),
        (
            _probe(video_streams=()),
            MediaLimits(),
            False,
            "REPLAY_MEDIA_UNSUPPORTED",
        ),
        (
            _probe(video_streams=(_video(),)),
            MediaLimits(),
            True,
            None,
        ),
        (
            _probe(video_streams=(_video(), _video(index=1))),
            MediaLimits(),
            False,
            "REPLAY_MEDIA_UNSUPPORTED",
        ),
        (
            _probe(video_streams=(_video(width=319, height=180),)),
            MediaLimits(),
            False,
            "REPLAY_MEDIA_UNSUPPORTED",
        ),
        (
            _probe(video_streams=(_video(width=3840, height=2160),)),
            MediaLimits(),
            True,
            None,
        ),
        (
            _probe(video_streams=(_video(fps=121),)),
            MediaLimits(),
            False,
            "REPLAY_MEDIA_UNSUPPORTED",
        ),
        (
            _probe(other_stream_types=("subtitle",)),
            MediaLimits(),
            False,
            "REPLAY_MEDIA_UNSUPPORTED",
        ),
        (
            _probe(other_stream_types=("data",)),
            MediaLimits(),
            False,
            "REPLAY_MEDIA_UNSUPPORTED",
        ),
        (
            _probe(duration_seconds=float("nan")),
            MediaLimits(),
            False,
            "REPLAY_MEDIA_UNSUPPORTED",
        ),
        (
            _probe(duration_seconds=float("inf")),
            MediaLimits(),
            False,
            "REPLAY_MEDIA_UNSUPPORTED",
        ),
        (
            _probe(audio_streams=()),
            MediaLimits(),
            True,
            None,
        ),
        (
            _probe(audio_streams=(_audio(index=1), _audio(index=2))),
            MediaLimits(),
            True,
            None,
        ),
    ],
)
def test_validate_probe_boundaries(
    probe: MediaProbe,
    limits: MediaLimits,
    expect_ok: bool,
    error_code: str | None,
) -> None:
    if expect_ok:
        validated = validate_probe(probe, limits)
        assert isinstance(validated, ValidatedMedia)
        assert validated.duration_seconds == probe.duration_seconds
        assert validated.video == probe.video_streams[0]
        if probe.audio_streams:
            assert validated.audio == probe.audio_streams[0]
            assert validated.has_audio is True
        else:
            assert validated.audio is None
            assert validated.has_audio is False
    else:
        with pytest.raises(ReplayMediaError) as exc_info:
            validate_probe(probe, limits)
        assert exc_info.value.code == error_code
        assert "stderr" not in str(exc_info.value).lower()


def test_progress_maps_out_time_ms_to_stage_15_80() -> None:
    assert progress_percent_from_out_time(0, 10_000) == 15
    assert progress_percent_from_out_time(10_000, 10_000) == 80
    assert 15 < progress_percent_from_out_time(5_000, 10_000) < 80
    assert parse_progress_out_time_ms("out_time_ms=2500\n") == 2500
    assert parse_progress_out_time_ms("bitrate=1.2kbits/s\n") is None


def test_parse_progress_supports_out_time_us() -> None:
    assert parse_progress_out_time_ms("out_time_us=2500000\n") == 2500
    assert parse_progress_out_time_ms("out_time_us=0\n") == 0
    assert parse_progress_out_time_ms("out_time_us=not-a-number\n") is None


def test_parse_progress_supports_out_time_timestamp_string() -> None:
    assert parse_progress_out_time_ms("out_time=00:00:02.500000\n") == 2500
    assert parse_progress_out_time_ms("out_time=01:02:03.250000") == (
        (1 * 3600 + 2 * 60 + 3) * 1000 + 250
    )
    assert parse_progress_out_time_ms("out_time=00:00:00.000000\n") == 0
    assert parse_progress_out_time_ms("out_time=N/A\n") is None
    assert parse_progress_out_time_ms("out_time=garbage\n") is None


def test_parse_progress_ignores_unrelated_lines() -> None:
    assert parse_progress_out_time_ms("progress=continue\n") is None
    assert parse_progress_out_time_ms("frame=120\n") is None
    assert parse_progress_out_time_ms("") is None


@dataclass
class FakeProcessResult:
    returncode: int = 0
    stdout: bytes = b""
    stderr: bytes = b""


@dataclass
class FakeProcessRunner:
    results: list[FakeProcessResult] = field(default_factory=list)
    calls: list[list[str]] = field(default_factory=list)
    on_stdout_chunks: list[bytes] = field(default_factory=list)

    async def run(
        self,
        args: list[str],
        *,
        timeout_seconds: float,
        on_stdout_line: Callable[[str], None] | None = None,
    ) -> FakeProcessResult:
        del timeout_seconds
        self.calls.append(list(args))
        binary = Path(args[0]).name
        if binary == "ffmpeg" and args[-1] not in {"pipe:1", "-"}:
            output = Path(args[-1])

            def _touch_output() -> None:
                output.parent.mkdir(parents=True, exist_ok=True)
                if not output.exists():
                    output.write_bytes(b"fake-media-output")

            await asyncio.to_thread(_touch_output)
        if on_stdout_line is not None:
            for chunk in self.on_stdout_chunks:
                for line in chunk.decode("utf-8", errors="replace").splitlines():
                    on_stdout_line(line)
        if not self.results:
            return FakeProcessResult()
        return self.results.pop(0)


def _ffprobe_json(
    *,
    duration: str = "1800.000000",
    width: int = 1280,
    height: int = 720,
    fps: str = "30/1",
    audio: bool = True,
) -> bytes:
    streams: list[dict[str, Any]] = [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": "h264",
            "width": width,
            "height": height,
            "avg_frame_rate": fps,
            "pix_fmt": "yuv420p",
        }
    ]
    if audio:
        streams.append(
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "channels": 2,
            }
        )
    payload = {
        "streams": streams,
        "format": {
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "duration": duration,
            "size": "123456",
        },
    }
    return json.dumps(payload).encode("utf-8")


@pytest.mark.asyncio
async def test_probe_uses_configured_ffprobe_path_and_parses_json(tmp_path: Path) -> None:
    source = tmp_path / "input.mp4"
    source.write_bytes(b"fake")
    runner = FakeProcessRunner(results=[FakeProcessResult(stdout=_ffprobe_json())])
    media = ReplayMediaRunner(
        ffmpeg_path="/opt/bin/ffmpeg",
        ffprobe_path="/opt/bin/ffprobe",
        process_runner=runner,
        timeout_seconds=30,
    )
    probe = await media.probe(source)
    assert runner.calls[0][0] == "/opt/bin/ffprobe"
    assert runner.calls[0][:4] == ["/opt/bin/ffprobe", "-v", "error", "-print_format"]
    assert probe.duration_seconds == 1800.0
    assert len(probe.video_streams) == 1
    assert probe.video_streams[0].width == 1280
    assert len(probe.audio_streams) == 1


@pytest.mark.asyncio
async def test_normalize_reports_progress_from_out_time_ms(tmp_path: Path) -> None:
    source = tmp_path / "input.mp4"
    output = tmp_path / "normalized.mp4"
    source.write_bytes(b"fake")
    probe = _probe(duration_seconds=10.0, audio_streams=(_audio(),))
    normalized_probe = _ffprobe_json(duration="10.000000", width=640, height=360)
    runner = FakeProcessRunner(
        results=[
            FakeProcessResult(returncode=0, stdout=b""),
            FakeProcessResult(returncode=0, stdout=normalized_probe),
        ],
        on_stdout_chunks=[b"out_time_ms=0\n", b"out_time_ms=5000\n", b"out_time_ms=10000\n"],
    )
    ticking_clock = {"value": 0.0}

    def _clock() -> float:
        # Advance well past the 1s rate-limit window between callbacks so each
        # distinct progress value in this test is observable.
        ticking_clock["value"] += 2.0
        return ticking_clock["value"]

    media = ReplayMediaRunner(
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
        process_runner=runner,
        timeout_seconds=30,
        progress_clock=_clock,
    )
    seen: list[int] = []

    async def on_progress(value: int) -> None:
        seen.append(value)

    await media.normalize(source, output, probe, progress=on_progress)
    assert runner.calls[0][0] == "ffmpeg"
    assert "libx264" in runner.calls[0]
    assert seen[0] == 15
    assert seen[-1] == 80
    assert any(15 < value < 80 for value in seen)


@pytest.mark.asyncio
async def test_normalize_rate_limits_progress_callbacks_to_one_per_second(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.mp4"
    output = tmp_path / "normalized.mp4"
    source.write_bytes(b"fake")
    probe = _probe(duration_seconds=10.0, audio_streams=(_audio(),))
    normalized_probe = _ffprobe_json(duration="10.000000", width=640, height=360)

    # A burst of distinct progress values that all arrive at the same instant
    # (per the fake clock below) should still collapse to a single callback.
    burst = [f"out_time_ms={i * 100}\n".encode() for i in range(1, 50)]
    runner = FakeProcessRunner(
        results=[
            FakeProcessResult(returncode=0, stdout=b""),
            FakeProcessResult(returncode=0, stdout=normalized_probe),
        ],
        on_stdout_chunks=burst,
    )

    fake_now = {"value": 1_000.0}

    def _clock() -> float:
        return fake_now["value"]

    media = ReplayMediaRunner(
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
        process_runner=runner,
        timeout_seconds=30,
        progress_clock=_clock,
    )

    seen: list[int] = []

    async def on_progress(value: int) -> None:
        seen.append(value)

    await media.normalize(source, output, probe, progress=on_progress)
    # Only the first value in the burst (no prior emission to rate-limit against)
    # plus the guaranteed final emission should have been delivered.
    assert len(seen) == 2
    assert seen[0] == 15
    assert seen[-1] == 80


@pytest.mark.asyncio
async def test_normalize_serializes_progress_callbacks_without_overlap(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.mp4"
    output = tmp_path / "normalized.mp4"
    source.write_bytes(b"fake")
    probe = _probe(duration_seconds=10.0, audio_streams=(_audio(),))
    normalized_probe = _ffprobe_json(duration="10.000000", width=640, height=360)

    lines = [f"out_time_ms={i * 1000}\n".encode() for i in range(10)]
    runner = FakeProcessRunner(
        results=[
            FakeProcessResult(returncode=0, stdout=b""),
            FakeProcessResult(returncode=0, stdout=normalized_probe),
        ],
        on_stdout_chunks=lines,
    )

    ticking_clock = {"value": 0.0}

    def _clock() -> float:
        # Always advances well past the 1s rate-limit window so every distinct
        # value is eligible to be delivered, maximizing overlap opportunity.
        ticking_clock["value"] += 2.0
        return ticking_clock["value"]

    media = ReplayMediaRunner(
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
        process_runner=runner,
        timeout_seconds=30,
        progress_clock=_clock,
    )

    active = 0
    max_active = 0

    async def on_progress(value: int) -> None:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0)
        active -= 1

    await media.normalize(source, output, probe, progress=on_progress)
    assert max_active == 1


@pytest.mark.asyncio
async def test_public_errors_use_stable_codes_and_hide_raw_stderr(tmp_path: Path) -> None:
    source = tmp_path / "input.mp4"
    source.write_bytes(b"fake")
    runner = FakeProcessRunner(
        results=[
            FakeProcessResult(
                returncode=1,
                stderr=b"ffmpeg: /secret/path/input.mp4: Invalid data found",
            )
        ]
    )
    media = ReplayMediaRunner(
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
        process_runner=runner,
        timeout_seconds=30,
    )
    with pytest.raises(ReplayMediaError) as exc_info:
        await media.probe(source)
    assert exc_info.value.code in {
        "REPLAY_PROCESSING_FAILED",
        "REPLAY_MEDIA_UNSUPPORTED",
        "REPLAY_FFMPEG_UNAVAILABLE",
    }
    assert "/secret/path" not in str(exc_info.value)
    assert "Invalid data found" not in str(exc_info.value)
    assert exc_info.value.diagnostics is not None
    assert "Invalid data found" in exc_info.value.diagnostics.truncated_stderr
    assert len(exc_info.value.diagnostics.truncated_stderr) <= 2048


@pytest.mark.asyncio
async def test_subprocess_runner_uses_create_subprocess_exec_and_kills_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.replays import media as media_mod

    created: dict[str, Any] = {}

    class FakeProcess:
        def __init__(self) -> None:
            self.terminated = False
            self.killed = False
            self.returncode: int | None = None
            self._done = asyncio.Event()

        async def communicate(self) -> tuple[bytes, bytes]:
            await self._done.wait()
            return b"", b""

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9
            self._done.set()

        async def wait(self) -> int:
            await self._done.wait()
            return self.returncode if self.returncode is not None else -9

    fake_process = FakeProcess()

    async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> FakeProcess:
        created["args"] = args
        created["kwargs"] = kwargs
        return fake_process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    wait_for_calls: list[float] = []
    real_wait_for = asyncio.wait_for

    async def tracking_wait_for(awaitable: Any, *, timeout: float | None = None) -> Any:  # noqa: ASYNC109
        wait_for_calls.append(float(timeout) if timeout is not None else -1.0)
        return await real_wait_for(awaitable, timeout=timeout)

    monkeypatch.setattr(asyncio, "wait_for", tracking_wait_for)

    runner = media_mod.AsyncSubprocessRunner()
    with pytest.raises(ReplayMediaError) as exc_info:
        await runner.run(["ffmpeg", "-version"], timeout_seconds=0.01)
    assert created["kwargs"]["stdout"] == asyncio.subprocess.PIPE
    assert created["kwargs"]["stderr"] == asyncio.subprocess.PIPE
    assert "shell" not in created["kwargs"]
    assert wait_for_calls
    assert fake_process.terminated is True
    assert fake_process.killed is True
    assert exc_info.value.code == "REPLAY_PROCESSING_FAILED"
    assert exc_info.value.diagnostics is not None


@pytest.mark.asyncio
async def test_streaming_run_bounds_stderr_tail_and_drops_full_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.replays import media as media_mod

    class FakeStream:
        def __init__(self, chunks: list[bytes]) -> None:
            self._chunks = list(chunks)

        async def read(self, _n: int) -> bytes:
            if not self._chunks:
                return b""
            return self._chunks.pop(0)

    class FakeStreamingProcess:
        def __init__(self, stdout_chunks: list[bytes], stderr_chunks: list[bytes]) -> None:
            self.stdout = FakeStream(stdout_chunks)
            self.stderr = FakeStream(stderr_chunks)
            self.returncode = 0

        async def wait(self) -> int:
            return 0

        def terminate(self) -> None:
            pass

        def kill(self) -> None:
            pass

    # ~120 KiB total, well over the 64 KiB tail retention target.
    stderr_chunks = [f"line-{i:04d}-".encode() + b"z" * 4090 for i in range(30)]
    stdout_chunks = [b"out_time_ms=1000\n", b"out_time_ms=2000\n"]
    fake_process = FakeStreamingProcess(stdout_chunks, stderr_chunks)

    async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> FakeStreamingProcess:
        del args, kwargs
        return fake_process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    runner = media_mod.AsyncSubprocessRunner()
    seen_lines: list[str] = []
    result = await runner.run(
        ["ffmpeg", "-progress", "pipe:1"],
        timeout_seconds=5,
        on_stdout_line=seen_lines.append,
    )

    assert seen_lines == ["out_time_ms=1000", "out_time_ms=2000"]
    # Full stdout must not be retained once lines have been parsed out of it.
    assert result.stdout == b""
    # stderr must be a bounded tail buffer, not the full unbounded history.
    assert len(result.stderr) <= 64 * 1024
    assert result.stderr.endswith(stderr_chunks[-1])
    assert stderr_chunks[0] not in result.stderr
