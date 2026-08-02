from __future__ import annotations

import asyncio
import contextlib
import json
import math
import re
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

ProgressCallback = Callable[[int], Coroutine[Any, Any, None]]

_MAX_DIAGNOSTIC_BYTES = 2048
_PATH_RE = re.compile(r"(?:/Users|/home|/var|/tmp|/private|/opt|/[A-Za-z])[^\s\"']+")
_STDERR_TAIL_BYTES = 64 * 1024
_PROGRESS_MIN_INTERVAL_SECONDS = 1.0
_OUT_TIME_RE = re.compile(r"^(\d+):(\d{2}):(\d{2})(?:\.(\d+))?$")


@dataclass(frozen=True)
class VideoStreamProbe:
    index: int
    width: int
    height: int
    codec_name: str
    avg_frame_rate: float
    pix_fmt: str | None = None


@dataclass(frozen=True)
class AudioStreamProbe:
    index: int
    codec_name: str
    channels: int | None = None


@dataclass(frozen=True)
class MediaProbe:
    duration_seconds: float
    format_name: str
    video_streams: tuple[VideoStreamProbe, ...]
    audio_streams: tuple[AudioStreamProbe, ...]
    other_stream_types: tuple[str, ...] = ()
    size_bytes: int | None = None


@dataclass(frozen=True)
class MediaLimits:
    min_duration_seconds: int = 600
    max_duration_seconds: int = 5400
    min_width: int = 320
    min_height: int = 180
    max_width: int = 3840
    max_height: int = 2160
    max_fps: float = 120.0


@dataclass(frozen=True)
class ValidatedMedia:
    duration_seconds: float
    width: int
    height: int
    fps: float
    has_audio: bool
    video: VideoStreamProbe
    audio: AudioStreamProbe | None


@dataclass(frozen=True)
class MediaProcessDiagnostics:
    truncated_stderr: str


class ReplayMediaError(Exception):
    def __init__(
        self,
        code: str,
        message: str = "",
        *,
        diagnostics: MediaProcessDiagnostics | None = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.diagnostics = diagnostics


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes


class ProcessRunner(Protocol):
    async def run(
        self,
        args: list[str],
        *,
        timeout_seconds: float,
        on_stdout_line: Callable[[str], None] | None = None,
    ) -> ProcessResult: ...


class _TailBuffer:
    """Bounded byte buffer retaining only the most recent `max_bytes`.

    Used for stderr retention so a long-running ffmpeg process cannot grow
    memory unboundedly; only the tail is needed for diagnostics.
    """

    __slots__ = ("_max_bytes", "_data")

    def __init__(self, max_bytes: int) -> None:
        self._max_bytes = max_bytes
        self._data = bytearray()

    def append(self, chunk: bytes) -> None:
        self._data.extend(chunk)
        overflow = len(self._data) - self._max_bytes
        if overflow > 0:
            del self._data[:overflow]

    def getvalue(self) -> bytes:
        return bytes(self._data)


class _RateLimitedProgress:
    """Serializes progress callbacks and rate-limits them to at most one per
    `min_interval_seconds`, while always allowing a final, non-rate-limited
    emission via `submit_final`.
    """

    def __init__(
        self,
        callback: ProgressCallback,
        *,
        min_interval_seconds: float = _PROGRESS_MIN_INTERVAL_SECONDS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._callback = callback
        self._min_interval_seconds = min_interval_seconds
        self._clock = clock or time.monotonic
        self._lock = asyncio.Lock()
        self._last_emitted_value: int | None = None
        self._last_emitted_at: float | None = None

    async def submit(self, value: int) -> None:
        async with self._lock:
            if value == self._last_emitted_value:
                return
            now = self._clock()
            if (
                self._last_emitted_at is not None
                and (now - self._last_emitted_at) < self._min_interval_seconds
            ):
                return
            await self._callback(value)
            self._last_emitted_value = value
            self._last_emitted_at = now

    async def submit_final(self, value: int) -> None:
        async with self._lock:
            if value == self._last_emitted_value:
                return
            await self._callback(value)
            self._last_emitted_value = value
            self._last_emitted_at = self._clock()


def _truncate_diagnostics(raw: bytes | str) -> str:
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    text = _PATH_RE.sub("<path>", text)
    if len(text) > _MAX_DIAGNOSTIC_BYTES:
        text = text[:_MAX_DIAGNOSTIC_BYTES]
    return text


def _scale_filter() -> str:
    return (
        "scale=w='min(1280,iw)':h='min(720,ih)':"
        "force_original_aspect_ratio=decrease:force_divisible_by=2"
    )


def build_ffprobe_command(ffprobe_path: str, input_path: Path) -> list[str]:
    return [
        ffprobe_path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(input_path),
    ]


def build_normalize_command(
    ffmpeg_path: str,
    input_path: Path,
    output_path: Path,
) -> list[str]:
    vf = f"{_scale_filter()},fps=30,setpts=PTS-STARTPTS"
    return [
        ffmpeg_path,
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-vf",
        vf,
        "-fps_mode",
        "cfr",
        "-movflags",
        "+faststart",
        "-c:a",
        "aac",
        "-ac",
        "2",
        "-b:a",
        "128k",
        "-af",
        "asetpts=PTS-STARTPTS",
        "-progress",
        "pipe:1",
        "-nostats",
        str(output_path),
    ]


def build_extract_frame_command(
    ffmpeg_path: str,
    input_path: Path,
    *,
    video_time_ms: int,
    output_path: Path,
) -> list[str]:
    seconds = video_time_ms / 1000
    seek_text = str(int(seconds)) if video_time_ms % 1000 == 0 else str(seconds)
    return [
        ffmpeg_path,
        "-y",
        "-ss",
        seek_text,
        "-i",
        str(input_path),
        "-frames:v",
        "1",
        "-map_metadata",
        "-1",
        "-vf",
        _scale_filter(),
        str(output_path),
    ]


def parse_frame_rate(value: str | float | int | None) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = value.strip()
    if not text or text == "0/0":
        return 0.0
    if "/" in text:
        numerator_text, denominator_text = text.split("/", 1)
        numerator = float(numerator_text)
        denominator = float(denominator_text)
        if denominator == 0:
            return 0.0
        return numerator / denominator
    return float(text)


def parse_progress_out_time_ms(line: str) -> int | None:
    """Parse an ffmpeg `-progress` output line into elapsed milliseconds.

    ffmpeg's `-progress` stream emits several time-carrying keys; supporting
    all of them makes parsing robust across ffmpeg versions/builds:
      - `out_time_ms=<microseconds>` (historical field name)
      - `out_time_us=<microseconds>` (converted to milliseconds)
      - `out_time=HH:MM:SS.micro` (converted to milliseconds)
    """
    if line.startswith("out_time_ms="):
        raw = line.split("=", 1)[1].strip()
        try:
            return int(raw) // 1000
        except ValueError:
            return None
    if line.startswith("out_time_us="):
        raw = line.split("=", 1)[1].strip()
        try:
            return int(raw) // 1000
        except ValueError:
            return None
    if line.startswith("out_time="):
        raw = line.split("=", 1)[1].strip()
        return _parse_out_time_timestamp(raw)
    return None


def _parse_out_time_timestamp(raw: str) -> int | None:
    match = _OUT_TIME_RE.match(raw)
    if not match:
        return None
    hours, minutes, seconds, fraction = match.groups()
    total_ms = (int(hours) * 3600 + int(minutes) * 60 + int(seconds)) * 1000
    if fraction:
        micros = int((fraction + "000000")[:6])
        total_ms += micros // 1000
    return total_ms


def progress_percent_from_out_time(out_time_ms: int, duration_ms: int) -> int:
    if duration_ms <= 0:
        return 15
    ratio = min(1.0, max(0.0, out_time_ms / duration_ms))
    return int(15 + ratio * (80 - 15))


def validate_probe(probe: MediaProbe, limits: MediaLimits) -> ValidatedMedia:
    duration = probe.duration_seconds
    if not math.isfinite(duration):
        raise ReplayMediaError("REPLAY_MEDIA_UNSUPPORTED", "Media duration is not finite.")

    if duration < limits.min_duration_seconds or duration > limits.max_duration_seconds:
        raise ReplayMediaError(
            "REPLAY_DURATION_UNSUPPORTED",
            "Media duration is outside the supported range.",
        )

    if len(probe.video_streams) != 1:
        raise ReplayMediaError(
            "REPLAY_MEDIA_UNSUPPORTED",
            "Exactly one video stream is required.",
        )

    if probe.other_stream_types:
        raise ReplayMediaError(
            "REPLAY_MEDIA_UNSUPPORTED",
            "Unsupported stream types are present.",
        )

    video = probe.video_streams[0]
    if (
        video.width < limits.min_width
        or video.height < limits.min_height
        or video.width > limits.max_width
        or video.height > limits.max_height
    ):
        raise ReplayMediaError(
            "REPLAY_MEDIA_UNSUPPORTED",
            "Video dimensions are outside the supported range.",
        )

    if not math.isfinite(video.avg_frame_rate) or video.avg_frame_rate <= 0:
        raise ReplayMediaError("REPLAY_MEDIA_UNSUPPORTED", "Frame rate must be positive.")
    if video.avg_frame_rate > limits.max_fps:
        raise ReplayMediaError(
            "REPLAY_MEDIA_UNSUPPORTED",
            "Frame rate exceeds the supported maximum.",
        )

    audio = probe.audio_streams[0] if probe.audio_streams else None
    return ValidatedMedia(
        duration_seconds=duration,
        width=video.width,
        height=video.height,
        fps=video.avg_frame_rate,
        has_audio=audio is not None,
        video=video,
        audio=audio,
    )


def parse_ffprobe_payload(payload: dict[str, Any]) -> MediaProbe:
    format_section = payload.get("format") or {}
    duration_raw = format_section.get("duration")
    try:
        duration_seconds = float(duration_raw) if duration_raw is not None else float("nan")
    except (TypeError, ValueError):
        duration_seconds = float("nan")

    size_raw = format_section.get("size")
    size_bytes: int | None
    try:
        size_bytes = int(size_raw) if size_raw is not None else None
    except (TypeError, ValueError):
        size_bytes = None

    video_streams: list[VideoStreamProbe] = []
    audio_streams: list[AudioStreamProbe] = []
    other_stream_types: list[str] = []

    for stream in payload.get("streams") or []:
        if not isinstance(stream, dict):
            continue
        codec_type = str(stream.get("codec_type") or "")
        index = int(stream.get("index") or 0)
        if codec_type == "video":
            video_streams.append(
                VideoStreamProbe(
                    index=index,
                    width=int(stream.get("width") or 0),
                    height=int(stream.get("height") or 0),
                    codec_name=str(stream.get("codec_name") or ""),
                    avg_frame_rate=parse_frame_rate(stream.get("avg_frame_rate")),
                    pix_fmt=str(stream["pix_fmt"]) if stream.get("pix_fmt") is not None else None,
                )
            )
        elif codec_type == "audio":
            channels_raw = stream.get("channels")
            channels = int(channels_raw) if channels_raw is not None else None
            audio_streams.append(
                AudioStreamProbe(
                    index=index,
                    codec_name=str(stream.get("codec_name") or ""),
                    channels=channels,
                )
            )
        elif codec_type:
            other_stream_types.append(codec_type)

    return MediaProbe(
        duration_seconds=duration_seconds,
        format_name=str(format_section.get("format_name") or ""),
        video_streams=tuple(video_streams),
        audio_streams=tuple(audio_streams),
        other_stream_types=tuple(other_stream_types),
        size_bytes=size_bytes,
    )


class AsyncSubprocessRunner:
    """Runs ffmpeg/ffprobe via create_subprocess_exec with timeouts."""

    async def run(
        self,
        args: list[str],
        *,
        timeout_seconds: float,
        on_stdout_line: Callable[[str], None] | None = None,
    ) -> ProcessResult:
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise ReplayMediaError(
                "REPLAY_FFMPEG_UNAVAILABLE",
                "Required media binary is unavailable.",
            ) from exc

        try:
            if on_stdout_line is None:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout_seconds,
                )
                return ProcessResult(
                    returncode=process.returncode or 0,
                    stdout=stdout,
                    stderr=stderr,
                )

            return await self._run_with_stdout_lines(
                process,
                timeout_seconds=timeout_seconds,
                on_stdout_line=on_stdout_line,
            )
        except TimeoutError as exc:
            await self._terminate_then_kill(process)
            raise ReplayMediaError(
                "REPLAY_PROCESSING_FAILED",
                "Media processing timed out.",
                diagnostics=MediaProcessDiagnostics(truncated_stderr="process timed out"),
            ) from exc

    async def _run_with_stdout_lines(
        self,
        process: asyncio.subprocess.Process,
        *,
        timeout_seconds: float,
        on_stdout_line: Callable[[str], None],
    ) -> ProcessResult:
        # Only the trailing, not-yet-newline-terminated fragment is kept for
        # parsing; completed lines are discarded once parsed and the full
        # stdout stream is never retained, since callers stream progress
        # lines rather than needing the accumulated output.
        stderr_tail = _TailBuffer(_STDERR_TAIL_BYTES)

        async def _read_stdout() -> None:
            assert process.stdout is not None
            buffer = b""
            while True:
                chunk = await process.stdout.read(4096)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    on_stdout_line(line.decode("utf-8", errors="replace").strip())
            if buffer:
                on_stdout_line(buffer.decode("utf-8", errors="replace").strip())

        async def _read_stderr() -> None:
            assert process.stderr is not None
            while True:
                chunk = await process.stderr.read(4096)
                if not chunk:
                    break
                stderr_tail.append(chunk)

        async def _gather() -> None:
            await asyncio.gather(_read_stdout(), _read_stderr(), process.wait())

        await asyncio.wait_for(_gather(), timeout=timeout_seconds)
        return ProcessResult(
            returncode=process.returncode or 0,
            stdout=b"",
            stderr=stderr_tail.getvalue(),
        )

    async def _terminate_then_kill(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        process.terminate()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=2.0)
        if process.returncode is None:
            process.kill()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=2.0)


class ReplayMediaRunner:
    def __init__(
        self,
        *,
        ffmpeg_path: str = "ffmpeg",
        ffprobe_path: str = "ffprobe",
        process_runner: ProcessRunner | None = None,
        timeout_seconds: float = 7200,
        progress_clock: Callable[[], float] | None = None,
    ) -> None:
        self._ffmpeg_path = ffmpeg_path
        self._ffprobe_path = ffprobe_path
        self._runner: ProcessRunner = process_runner or AsyncSubprocessRunner()
        self._timeout_seconds = timeout_seconds
        self._progress_clock = progress_clock

    async def probe(self, input_path: Path) -> MediaProbe:
        command = build_ffprobe_command(self._ffprobe_path, input_path)
        result = await self._runner.run(command, timeout_seconds=self._timeout_seconds)
        if result.returncode != 0:
            raise ReplayMediaError(
                "REPLAY_PROCESSING_FAILED",
                "Media probe failed.",
                diagnostics=MediaProcessDiagnostics(
                    truncated_stderr=_truncate_diagnostics(result.stderr)
                ),
            )
        try:
            payload = json.loads(result.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReplayMediaError(
                "REPLAY_MEDIA_UNSUPPORTED",
                "Media probe returned invalid metadata.",
                diagnostics=MediaProcessDiagnostics(
                    truncated_stderr=_truncate_diagnostics(result.stderr)
                ),
            ) from exc
        if not isinstance(payload, dict):
            raise ReplayMediaError(
                "REPLAY_MEDIA_UNSUPPORTED",
                "Media probe returned invalid metadata.",
            )
        return parse_ffprobe_payload(payload)

    async def normalize(
        self,
        input_path: Path,
        output_path: Path,
        probe: MediaProbe,
        progress: ProgressCallback | None = None,
    ) -> MediaProbe:
        await asyncio.to_thread(output_path.parent.mkdir, parents=True, exist_ok=True)
        temp_path = output_path.with_name(f"{output_path.stem}.partial{output_path.suffix}")
        if await asyncio.to_thread(temp_path.exists):
            await asyncio.to_thread(temp_path.unlink)

        duration_ms = max(1, int(probe.duration_seconds * 1000))
        last_progress = -1
        progress_tasks: list[asyncio.Task[None]] = []
        gate = (
            _RateLimitedProgress(progress, clock=self._progress_clock)
            if progress is not None
            else None
        )

        def _on_line(line: str) -> None:
            nonlocal last_progress
            out_time_ms = parse_progress_out_time_ms(line)
            if out_time_ms is None:
                return
            value = progress_percent_from_out_time(out_time_ms, duration_ms)
            if value == last_progress:
                return
            last_progress = value
            if gate is not None:
                progress_tasks.append(asyncio.create_task(gate.submit(value)))

        command = build_normalize_command(self._ffmpeg_path, input_path, temp_path)
        result = await self._runner.run(
            command,
            timeout_seconds=self._timeout_seconds,
            on_stdout_line=_on_line if progress is not None else None,
        )
        if progress_tasks:
            await asyncio.gather(*progress_tasks)
        if result.returncode != 0:
            if await asyncio.to_thread(temp_path.exists):
                await asyncio.to_thread(temp_path.unlink)
            raise ReplayMediaError(
                "REPLAY_PROCESSING_FAILED",
                "Media normalization failed.",
                diagnostics=MediaProcessDiagnostics(
                    truncated_stderr=_truncate_diagnostics(result.stderr)
                ),
            )

        if gate is not None:
            await gate.submit_final(80)

        normalized = await self.probe(temp_path)
        self._assert_normalized_output(normalized, source=probe)
        await asyncio.to_thread(temp_path.replace, output_path)
        return normalized

    async def extract_frame(
        self,
        input_path: Path,
        video_time_ms: int,
        output_path: Path,
    ) -> None:
        if video_time_ms < 0:
            raise ReplayMediaError("REPLAY_MEDIA_UNSUPPORTED", "Frame time must be non-negative.")
        await asyncio.to_thread(output_path.parent.mkdir, parents=True, exist_ok=True)
        command = build_extract_frame_command(
            self._ffmpeg_path,
            input_path,
            video_time_ms=video_time_ms,
            output_path=output_path,
        )
        result = await self._runner.run(command, timeout_seconds=self._timeout_seconds)
        output_exists = await asyncio.to_thread(output_path.is_file)
        if result.returncode != 0 or not output_exists:
            if await asyncio.to_thread(output_path.exists):
                await asyncio.to_thread(output_path.unlink)
            raise ReplayMediaError(
                "REPLAY_PROCESSING_FAILED",
                "Frame extraction failed.",
                diagnostics=MediaProcessDiagnostics(
                    truncated_stderr=_truncate_diagnostics(result.stderr)
                ),
            )

    def _assert_normalized_output(self, normalized: MediaProbe, *, source: MediaProbe) -> None:
        if not normalized.video_streams:
            raise ReplayMediaError(
                "REPLAY_PROCESSING_FAILED",
                "Normalized media has no video stream.",
            )
        video = normalized.video_streams[0]
        if video.codec_name not in {"h264", "avc1"}:
            raise ReplayMediaError(
                "REPLAY_PROCESSING_FAILED",
                "Normalized video codec is invalid.",
            )
        if video.pix_fmt is not None and video.pix_fmt != "yuv420p":
            raise ReplayMediaError(
                "REPLAY_PROCESSING_FAILED",
                "Normalized pixel format is invalid.",
            )
        if "mp4" not in normalized.format_name:
            raise ReplayMediaError(
                "REPLAY_PROCESSING_FAILED",
                "Normalized container is invalid.",
            )
        if video.avg_frame_rate > 0 and abs(video.avg_frame_rate - 30.0) > 0.5:
            raise ReplayMediaError(
                "REPLAY_PROCESSING_FAILED",
                "Normalized frame rate is invalid.",
            )
        if video.width > 1280 or video.height > 720:
            raise ReplayMediaError(
                "REPLAY_PROCESSING_FAILED",
                "Normalized dimensions exceed bounds.",
            )
        duration_ok = math.isfinite(normalized.duration_seconds) and math.isfinite(
            source.duration_seconds
        )
        if duration_ok and abs(normalized.duration_seconds - source.duration_seconds) > 2.0:
            raise ReplayMediaError(
                "REPLAY_PROCESSING_FAILED",
                "Normalized duration differs from source.",
            )
