"""Run the Replay R1 local smoke flow without exposing configured values."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode
from uuid import UUID

from app.core.config import ROOT_ENV_FILE

_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,79}$")
_RIGHTS_STATEMENT_VERSION = "2026-08-01"
CommandRunner = Callable[..., object]


class SmokeResponse(Protocol):
    status_code: int

    def raise_for_status(self) -> None: ...

    def json(self) -> object: ...


class SmokeClient(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        content: object | None = None,
        json: object | None = None,
    ) -> SmokeResponse: ...


class SmokeFailure(RuntimeError):
    """A CLI-safe failure that deliberately excludes URL, identifiers, and body text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Replay smoke failed: code={code}")


def require_smoke_configuration(*, match_id: str, puuid: str) -> None:
    if not match_id.strip() or not puuid.strip():
        raise SmokeFailure("SMOKE_CONFIGURATION_REQUIRED")


def generate_smoke_video(
    *,
    output_path: Path,
    ffmpeg_path: str = "ffmpeg",
    runner: CommandRunner | None = None,
) -> None:
    """Create a 600s 320x180 low-bitrate lavfi fixture at runtime."""
    command = [
        ffmpeg_path,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=600:size=320x180:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=600",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-b:v",
        "200k",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-shortest",
        str(output_path),
    ]
    run = runner or subprocess.run
    completed = run(command, check=True, capture_output=True, text=True)
    del completed


def run_smoke(
    *,
    client: SmokeClient,
    api_base_url: str,
    match_id: str,
    puuid: str,
    platform: str = "NA1",
    video_path: Path | None = None,
    ffmpeg_path: str = "ffmpeg",
    poll_interval_seconds: float = 2.0,
    poll_timeout_seconds: float = 900.0,
) -> None:
    require_smoke_configuration(match_id=match_id, puuid=puuid)
    temporary_dir: tempfile.TemporaryDirectory[str] | None = None
    owned_video = video_path
    try:
        if owned_video is None:
            temporary_dir = tempfile.TemporaryDirectory(prefix="replay-smoke-")
            owned_video = Path(temporary_dir.name) / "authorized-fixture.mp4"
            generate_smoke_video(output_path=owned_video, ffmpeg_path=ffmpeg_path)

        size_bytes = owned_video.stat().st_size
        # Compose provisions an empty database. Fetching detail through the
        # public match route validates the selected player and persists the
        # replay-binding snapshot before the replay create call.
        match_query = urlencode({"platform": platform, "puuid": puuid})
        _request_json(
            client,
            "GET",
            f"{api_base_url.rstrip('/')}/api/v1/matches/{match_id}?{match_query}",
        )
        created = _request_json(
            client,
            "POST",
            f"{api_base_url.rstrip('/')}/api/v1/replays",
            json={
                "match_id": match_id,
                "platform": platform,
                "puuid": puuid,
                "original_filename": owned_video.name,
                "declared_size_bytes": size_bytes,
                "declared_content_type": "video/mp4",
                "game_time_zero_ms": 0,
                "rights_attested": True,
                "rights_statement_version": _RIGHTS_STATEMENT_VERSION,
            },
        )
        replay_id = _required_uuid_string(created, "replay_id")
        access_token = _required_string(created, "access_token")
        upload = _required_mapping(created, "upload")
        upload_method = _required_string(upload, "method")
        upload_url = _required_string(upload, "url")
        upload_headers = upload.get("headers")
        if not isinstance(upload_headers, Mapping):
            raise SmokeFailure("SMOKE_INVALID_RESPONSE")

        absolute_upload = (
            upload_url
            if upload_url.startswith("http://") or upload_url.startswith("https://")
            else f"{api_base_url.rstrip('/')}{upload_url}"
        )
        headers = {str(key): str(value) for key, value in upload_headers.items()}
        if absolute_upload.startswith(api_base_url.rstrip("/")):
            headers["Authorization"] = f"Bearer {access_token}"

        _request(
            client,
            upload_method,
            absolute_upload,
            headers=headers,
            content=owned_video.read_bytes(),
            expect_json=False,
        )
        _request_json(
            client,
            "POST",
            f"{api_base_url.rstrip('/')}/api/v1/replays/{replay_id}/complete",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        status_payload = _poll_ready(
            client,
            api_base_url=api_base_url,
            replay_id=replay_id,
            access_token=access_token,
            poll_interval_seconds=poll_interval_seconds,
            poll_timeout_seconds=poll_timeout_seconds,
        )
        if _required_string(status_payload, "status") != "ready":
            raise SmokeFailure("SMOKE_NOT_READY")

        artifacts_payload = _request_json(
            client,
            "GET",
            f"{api_base_url.rstrip('/')}/api/v1/replays/{replay_id}/artifacts",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        artifacts = artifacts_payload.get("artifacts")
        if not isinstance(artifacts, list):
            raise SmokeFailure("SMOKE_INVALID_RESPONSE")

        _request_json(
            client,
            "DELETE",
            f"{api_base_url.rstrip('/')}/api/v1/replays/{replay_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        _poll_deleted(
            client,
            api_base_url=api_base_url,
            replay_id=replay_id,
            access_token=access_token,
            poll_interval_seconds=poll_interval_seconds,
            poll_timeout_seconds=poll_timeout_seconds,
        )
        print(f"replay=ready artifacts={len(artifacts)} delete=ok")
    finally:
        if temporary_dir is not None:
            temporary_dir.cleanup()


def _poll_ready(
    client: SmokeClient,
    *,
    api_base_url: str,
    replay_id: str,
    access_token: str,
    poll_interval_seconds: float,
    poll_timeout_seconds: float,
) -> dict[str, object]:
    deadline = time.monotonic() + poll_timeout_seconds
    while True:
        payload = _request_json(
            client,
            "GET",
            f"{api_base_url.rstrip('/')}/api/v1/replays/{replay_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        status = payload.get("status")
        if status == "ready":
            return payload
        if status in {"failed", "expired", "deleted"}:
            raise SmokeFailure("SMOKE_TERMINAL_STATUS")
        if time.monotonic() >= deadline:
            raise SmokeFailure("SMOKE_TIMEOUT")
        if poll_interval_seconds > 0:
            time.sleep(poll_interval_seconds)


def _poll_deleted(
    client: SmokeClient,
    *,
    api_base_url: str,
    replay_id: str,
    access_token: str,
    poll_interval_seconds: float,
    poll_timeout_seconds: float,
) -> dict[str, object]:
    deadline = time.monotonic() + poll_timeout_seconds
    while True:
        response = _request(
            client,
            "GET",
            f"{api_base_url.rstrip('/')}/api/v1/replays/{replay_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            expect_json=True,
            accepted_error_codes=frozenset({"REPLAY_NOT_FOUND"}),
        )
        if response.status_code == 404:
            return {"status": "deleted"}
        payload = _response_mapping(response)
        status = payload.get("status")
        if status == "deleted":
            return payload
        if status in {"failed", "expired"}:
            raise SmokeFailure("SMOKE_TERMINAL_STATUS")
        if time.monotonic() >= deadline:
            raise SmokeFailure("SMOKE_DELETE_TIMEOUT")
        if poll_interval_seconds > 0:
            time.sleep(poll_interval_seconds)


def _request_json(
    client: SmokeClient,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    content: object | None = None,
    json: object | None = None,
) -> dict[str, object]:
    response = _request(
        client,
        method,
        url,
        headers=headers,
        content=content,
        json=json,
        expect_json=True,
    )
    return _response_mapping(response)


def _response_mapping(response: SmokeResponse) -> dict[str, object]:
    try:
        payload = response.json()
    except Exception:
        raise SmokeFailure("SMOKE_INVALID_RESPONSE") from None
    if not isinstance(payload, dict):
        raise SmokeFailure("SMOKE_INVALID_RESPONSE")
    return payload


def _request(
    client: SmokeClient,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    content: object | None = None,
    json: object | None = None,
    expect_json: bool,
    accepted_error_codes: frozenset[str] = frozenset(),
) -> SmokeResponse:
    try:
        response = client.request(
            method,
            url,
            headers=headers,
            content=content,
            json=json,
        )
    except Exception:
        raise SmokeFailure("SMOKE_REQUEST_FAILED") from None

    try:
        if response.status_code >= 400:
            if _safe_error_code(response) in accepted_error_codes:
                return response
            response.raise_for_status()
        elif expect_json:
            response.raise_for_status()
    except SmokeFailure:
        raise
    except Exception:
        raise SmokeFailure(_safe_error_code(response)) from None
    return response


def _safe_error_code(response: SmokeResponse) -> str:
    try:
        payload = response.json()
    except Exception:
        return "SMOKE_REQUEST_FAILED"
    if not isinstance(payload, Mapping):
        return "SMOKE_REQUEST_FAILED"
    error = payload.get("error")
    if not isinstance(error, Mapping):
        return "SMOKE_REQUEST_FAILED"
    code = error.get("code")
    if isinstance(code, str) and _SAFE_CODE.fullmatch(code):
        return code
    return "SMOKE_REQUEST_FAILED"


def _required_mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise SmokeFailure("SMOKE_INVALID_RESPONSE")
    return value


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise SmokeFailure("SMOKE_INVALID_RESPONSE")
    return value


def _required_uuid_string(payload: Mapping[str, object], key: str) -> str:
    value = _required_string(payload, key)
    try:
        return str(UUID(value))
    except ValueError as error:
        raise SmokeFailure("SMOKE_INVALID_RESPONSE") from error


def _env_value(name: str) -> str:
    direct = os.environ.get(name)
    if direct is not None:
        return direct
    if not ROOT_ENV_FILE.is_file():
        return ""
    prefix = f"{name}="
    for line in ROOT_ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(prefix):
            return stripped.split("=", 1)[1]
    return ""


def main() -> int:
    try:
        import httpx2

        require_smoke_configuration(
            match_id=_env_value("REPLAY_SMOKE_MATCH_ID"),
            puuid=_env_value("REPLAY_SMOKE_PUUID"),
        )
        with httpx2.Client(timeout=60.0) as client:
            run_smoke(
                client=client,
                api_base_url=_env_value("SMOKE_API_BASE_URL") or "http://localhost:8000",
                match_id=_env_value("REPLAY_SMOKE_MATCH_ID"),
                puuid=_env_value("REPLAY_SMOKE_PUUID"),
                platform=_env_value("REPLAY_SMOKE_PLATFORM") or "NA1",
                ffmpeg_path=_env_value("REPLAY_FFMPEG_PATH") or "ffmpeg",
            )
    except SmokeFailure as error:
        print(error)
        return 1
    except Exception:  # noqa: BLE001 - the CLI boundary must redact unexpected failures.
        print(SmokeFailure("SMOKE_REQUEST_FAILED"))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
