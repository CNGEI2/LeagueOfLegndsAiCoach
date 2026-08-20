"""Contracts for Replay R1 Makefile targets and privacy-safe smoke flow."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SMOKE_SCRIPT = REPOSITORY_ROOT / "scripts" / "smoke_replay.py"


def _load_smoke_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("smoke_replay", SMOKE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class FakeResponse:
    payload: object
    status_code: int = 200
    raise_error: Exception | None = None
    json_error: Exception | None = None
    content: bytes = b""

    def raise_for_status(self) -> None:
        if self.raise_error is not None:
            raise self.raise_error
        if self.status_code >= 400:
            raise RuntimeError("request failed")

    def json(self) -> object:
        if self.json_error is not None:
            raise self.json_error
        return self.payload


@dataclass
class FakeSmokeClient:
    responses: dict[str, list[FakeResponse]]
    requests: list[tuple[str, str, dict[str, str] | None, object | None]] = field(
        default_factory=list
    )

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        content: object | None = None,
        json: object | None = None,
    ) -> FakeResponse:
        del content
        self.requests.append((method, url, headers, json))
        queue = self.responses.get(method.upper())
        if not queue:
            raise AssertionError(f"no fake response queued for {method} {url}")
        return queue.pop(0)


def test_makefile_exposes_replay_verification_targets() -> None:
    """Replay acceptance commands must stay discoverable through Make."""
    makefile = (REPOSITORY_ROOT / "Makefile").read_text()

    assert "dev-replay-worker:" in makefile
    assert "python -m app.workers.replay" in makefile
    assert "verify-replay:" in makefile
    assert 'tests/test_replay_*.py -m "not integration and not replay_ffmpeg"' in makefile
    assert (
        "pnpm test -- replay-api-client.test.ts replay-storage.test.ts replay-section.test.tsx"
        in makefile
    )
    assert "verify-replay-ffmpeg:" in makefile
    assert "tests/integration/test_replay_ffmpeg.py -m replay_ffmpeg" in makefile
    assert "verify-replay-postgres:" in makefile
    assert 'tests/integration -m "integration and not replay_ffmpeg"' in makefile
    assert '-m "not integration and not replay_ffmpeg"' in makefile
    assert "smoke-replay:" in makefile
    assert "scripts/smoke_replay.py" in makefile


def test_smoke_script_requires_match_id_and_puuid_from_configuration() -> None:
    smoke = _load_smoke_module()

    with pytest.raises(smoke.SmokeFailure) as raised:
        smoke.require_smoke_configuration(match_id="", puuid="player-puuid")
    assert "SMOKE_CONFIGURATION_REQUIRED" in str(raised.value)

    with pytest.raises(smoke.SmokeFailure):
        smoke.require_smoke_configuration(match_id="NA1_1", puuid="")


def test_smoke_generates_low_bitrate_lavfi_video_contract(tmp_path: Path) -> None:
    """The fixture must be generated at runtime as a 600s 320x180 lavfi pattern."""
    smoke = _load_smoke_module()
    recorded: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> None:
        recorded.append(command)

    output = tmp_path / "authorized-smoke.mp4"
    smoke.generate_smoke_video(
        output_path=output,
        ffmpeg_path="/usr/bin/ffmpeg",
        runner=fake_run,
    )

    assert len(recorded) == 1
    command = recorded[0]
    assert command[0] == "/usr/bin/ffmpeg"
    assert "lavfi" in command
    joined = " ".join(command)
    assert "320x180" in joined
    assert "600" in joined
    assert str(output) in command


def test_smoke_reports_generic_ready_counts_without_secrets(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Success output must stay generic; identifiers and tokens must never print."""
    smoke = _load_smoke_module()
    replay_id = str(uuid4())
    access_token = "smoke-secret-token-value"
    match_id = "NA1_9876543210"
    puuid = "private-smoke-puuid"
    object_key = "source/private/object-key"
    filename = "owned-authorized-smoke.mp4"
    video_path = tmp_path / filename
    video_path.write_bytes(b"fake-mp4-bytes")

    client = FakeSmokeClient(
        responses={
            "POST": [
                FakeResponse(
                    {
                        "replay_id": replay_id,
                        "access_token": access_token,
                        "status": "created",
                        "upload": {
                            "method": "PUT",
                            "url": f"/api/v1/replays/{replay_id}/content",
                            "headers": {},
                            "expires_at": "2026-08-01T16:00:00Z",
                        },
                        "retention": {
                            "source_hours_after_processing": 24,
                            "derived_days_after_ready": 7,
                        },
                        "request_id": "a" * 32,
                    }
                ),
                FakeResponse(
                    {
                        "replay_id": replay_id,
                        "status": "queued",
                        "processing_stage": "queued",
                        "progress_percent": 5,
                        "normalized_duration_ms": None,
                        "width": None,
                        "height": None,
                        "available_game_time_start_ms": None,
                        "available_game_time_end_ms": None,
                        "warning_codes": [],
                        "error_code": None,
                        "error_retryable": None,
                        "source_delete_after": None,
                        "derived_delete_after": None,
                        "request_id": "b" * 32,
                    }
                ),
            ],
            "PUT": [FakeResponse({}, status_code=204)],
            "GET": [
                FakeResponse({"match_id": match_id, "platform": "NA1"}),
                FakeResponse(
                    {
                        "replay_id": replay_id,
                        "status": "ready",
                        "processing_stage": "ready",
                        "progress_percent": 100,
                        "normalized_duration_ms": 600000,
                        "width": 320,
                        "height": 180,
                        "available_game_time_start_ms": 0,
                        "available_game_time_end_ms": 600000,
                        "warning_codes": [],
                        "error_code": None,
                        "error_retryable": None,
                        "source_delete_after": "2026-08-02T15:00:00Z",
                        "derived_delete_after": "2026-08-08T15:00:00Z",
                        "request_id": "c" * 32,
                    }
                ),
                FakeResponse(
                    {
                        "artifacts": [
                            {"artifact_id": str(uuid4())},
                            {"artifact_id": str(uuid4())},
                            {"artifact_id": str(uuid4())},
                        ],
                        "request_id": "d" * 32,
                    }
                ),
                FakeResponse(
                    {
                        "error": {"code": "REPLAY_NOT_FOUND"},
                    },
                    status_code=404,
                ),
            ],
            "DELETE": [
                FakeResponse(
                    {
                        "replay_id": replay_id,
                        "status": "deleting",
                        "processing_stage": "deleting",
                        "progress_percent": 0,
                        "normalized_duration_ms": None,
                        "width": None,
                        "height": None,
                        "available_game_time_start_ms": None,
                        "available_game_time_end_ms": None,
                        "warning_codes": [],
                        "error_code": None,
                        "error_retryable": None,
                        "source_delete_after": None,
                        "derived_delete_after": None,
                        "request_id": "f" * 32,
                    }
                ),
            ],
        }
    )

    smoke.run_smoke(
        client=client,
        api_base_url="http://localhost:8000",
        match_id=match_id,
        puuid=puuid,
        platform="NA1",
        video_path=video_path,
        poll_interval_seconds=0,
        poll_timeout_seconds=1,
    )

    output = capsys.readouterr().out
    assert output == "replay=ready artifacts=3 delete=ok\n"
    for sensitive in (
        match_id,
        puuid,
        access_token,
        filename,
        object_key,
        replay_id,
        "http://localhost:8000",
        "/api/v1/replays",
        "owned-authorized",
        "private-smoke",
        "request_id",
    ):
        assert sensitive not in output


def test_smoke_seeds_configured_platform_match_then_waits_for_async_delete(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Compose starts with an empty DB, so smoke must cache the match first.

    DELETE only starts asynchronous retention work; the smoke result is valid
    only after a subsequent status poll reports `deleted`.
    """
    smoke = _load_smoke_module()
    replay_id = str(uuid4())
    video_path = tmp_path / "fixture.mp4"
    video_path.write_bytes(b"fixture")
    platform = "EUW1"
    match_id = "EUW1_123456789"
    puuid = "smoke-player-puuid"
    token = "smoke-access-token"
    client = FakeSmokeClient(
        responses={
            "GET": [
                FakeResponse({"match_id": match_id, "platform": platform}),
                FakeResponse({"replay_id": replay_id, "status": "ready"}),
                FakeResponse({"artifacts": []}),
                FakeResponse(
                    {"error": {"code": "REPLAY_NOT_FOUND"}},
                    status_code=404,
                ),
            ],
            "POST": [
                FakeResponse(
                    {
                        "replay_id": replay_id,
                        "access_token": token,
                        "status": "created",
                        "upload": {
                            "method": "PUT",
                            "url": f"/api/v1/replays/{replay_id}/content",
                            "headers": {},
                        },
                    }
                ),
                FakeResponse({"replay_id": replay_id, "status": "queued"}),
            ],
            "PUT": [FakeResponse({}, status_code=204)],
            "DELETE": [FakeResponse({"replay_id": replay_id, "status": "deleting"})],
        }
    )

    smoke.run_smoke(
        client=client,
        api_base_url="http://localhost:8000",
        match_id=match_id,
        puuid=puuid,
        platform=platform,
        video_path=video_path,
        poll_interval_seconds=0,
        poll_timeout_seconds=1,
    )

    assert client.requests[0][0:2] == (
        "GET",
        f"http://localhost:8000/api/v1/matches/{match_id}?platform={platform}&puuid={puuid}",
    )
    create_request = next(request for request in client.requests if request[0] == "POST")
    assert create_request[3] is not None
    assert create_request[3]["platform"] == platform  # type: ignore[index]
    delete_index = next(
        index for index, request in enumerate(client.requests) if request[0] == "DELETE"
    )
    assert client.requests[delete_index + 1][0] == "GET"
    assert capsys.readouterr().out == "replay=ready artifacts=0 delete=ok\n"


def test_poll_deleted_rejects_other_structured_404_codes() -> None:
    smoke = _load_smoke_module()
    client = FakeSmokeClient(
        responses={
            "GET": [
                FakeResponse(
                    {"error": {"code": "MATCH_NOT_FOUND"}},
                    status_code=404,
                )
            ]
        }
    )

    with pytest.raises(smoke.SmokeFailure) as raised:
        smoke._poll_deleted(
            client,
            api_base_url="http://example.test",
            replay_id=str(uuid4()),
            access_token="smoke-access-token",
            poll_interval_seconds=0,
            poll_timeout_seconds=1,
        )

    assert raised.value.code == "MATCH_NOT_FOUND"


def test_poll_deleted_rejects_non_json_404_as_generic_request_failure() -> None:
    smoke = _load_smoke_module()
    client = FakeSmokeClient(
        responses={
            "GET": [
                FakeResponse(
                    None,
                    status_code=404,
                    json_error=ValueError("invalid JSON"),
                )
            ]
        }
    )

    with pytest.raises(smoke.SmokeFailure) as raised:
        smoke._poll_deleted(
            client,
            api_base_url="http://example.test",
            replay_id=str(uuid4()),
            access_token="smoke-access-token",
            poll_interval_seconds=0,
            poll_timeout_seconds=1,
        )

    assert raised.value.code == "SMOKE_REQUEST_FAILED"


def test_poll_deleted_accepts_readable_deleted_status() -> None:
    smoke = _load_smoke_module()
    client = FakeSmokeClient(responses={"GET": [FakeResponse({"status": "deleted"})]})

    assert smoke._poll_deleted(
        client,
        api_base_url="http://example.test",
        replay_id=str(uuid4()),
        access_token="smoke-access-token",
        poll_interval_seconds=0,
        poll_timeout_seconds=1,
    ) == {"status": "deleted"}


def _linked_evidence_payload(
    *,
    artifact_ids: list[str],
    request_id: str = "a3f4c1d2e5b67890a1b2c3d4e5f60718",
) -> dict[str, object]:
    return {
        "status": "ready",
        "schema_version": 1,
        "facts": [],
        "windows": [
            {
                "window_id": "evidence-window:SENTINEL_WINDOW_ID",
                "coverage": "full",
                "artifacts": [{"artifact_id": artifact_id} for artifact_id in artifact_ids],
            }
        ],
        "timeline_cache_status": "hit",
        "replay_link": {
            "status": "linked",
            "full_count": 1,
            "partial_count": 0,
            "unavailable_count": 0,
        },
        "request_id": request_id,
    }


def test_replay_smoke_calls_linked_evidence_before_delete_when_enabled(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    smoke = _load_smoke_module()
    replay_id = str(uuid4())
    artifact_id = str(uuid4())
    extra_artifact_id = str(uuid4())
    access_token = "smoke-secret-token-value"
    match_id = "NA1_9876543210"
    puuid = "private-smoke-puuid"
    video_path = tmp_path / "owned-authorized-smoke.mp4"
    video_path.write_bytes(b"fake-mp4-bytes")
    client = FakeSmokeClient(
        responses={
            "POST": [
                FakeResponse(
                    {
                        "replay_id": replay_id,
                        "access_token": access_token,
                        "status": "created",
                        "upload": {
                            "method": "PUT",
                            "url": f"/api/v1/replays/{replay_id}/content",
                            "headers": {},
                        },
                    }
                ),
                FakeResponse({"replay_id": replay_id, "status": "queued"}),
                FakeResponse(
                    _linked_evidence_payload(artifact_ids=[artifact_id]),
                ),
            ],
            "PUT": [FakeResponse({}, status_code=204)],
            "GET": [
                FakeResponse({"match_id": match_id, "platform": "NA1"}),
                FakeResponse({"replay_id": replay_id, "status": "ready"}),
                FakeResponse(
                    {
                        "artifacts": [
                            {"artifact_id": artifact_id},
                            {"artifact_id": extra_artifact_id},
                        ]
                    }
                ),
                FakeResponse({"error": {"code": "REPLAY_NOT_FOUND"}}, status_code=404),
            ],
            "DELETE": [FakeResponse({"replay_id": replay_id, "status": "deleting"})],
        }
    )

    smoke.run_smoke(
        client=client,
        api_base_url="http://localhost:8000",
        match_id=match_id,
        puuid=puuid,
        platform="NA1",
        video_path=video_path,
        poll_interval_seconds=0,
        poll_timeout_seconds=1,
        joint_evidence_enabled=True,
    )

    methods = [request[0] for request in client.requests]
    assert methods.index("DELETE") > next(
        index for index, request in enumerate(client.requests) if "/evidence" in request[1]
    )
    evidence_request = next(request for request in client.requests if "/evidence" in request[1])
    assert evidence_request[0] == "POST"
    assert evidence_request[2] == {"Authorization": f"Bearer {access_token}"}
    assert evidence_request[3]["replay_id"] == replay_id  # type: ignore[index]
    assert evidence_request[3]["puuid"] == puuid  # type: ignore[index]
    assert methods[-1] == "GET"

    output = capsys.readouterr().out
    assert "Joint evidence linked smoke passed:" in output
    assert "outcome=linked" in output
    assert "windows=1" in output
    assert "full=1" in output
    assert "partial=0" in output
    assert "unavailable=0" in output
    assert "artifact_refs=1" in output
    assert "elapsed_ms=" in output
    assert "request_id=a3f4c1d2e5b67890a1b2c3d4e5f60718" in output
    assert "replay=ready artifacts=2 delete=ok" in output
    for sensitive in (
        match_id,
        puuid,
        access_token,
        replay_id,
        artifact_id,
        extra_artifact_id,
        "SENTINEL_WINDOW_ID",
        "http://localhost:8000",
        "/api/v1/replays",
        "Bearer",
        "presigned",
    ):
        assert sensitive not in output


def test_replay_smoke_rejects_evidence_artifact_outside_authorized_manifest(
    tmp_path: Path,
) -> None:
    smoke = _load_smoke_module()
    replay_id = str(uuid4())
    manifest_id = str(uuid4())
    leaked_id = str(uuid4())
    video_path = tmp_path / "fixture.mp4"
    video_path.write_bytes(b"fixture")
    client = FakeSmokeClient(
        responses={
            "POST": [
                FakeResponse(
                    {
                        "replay_id": replay_id,
                        "access_token": "smoke-access-token",
                        "status": "created",
                        "upload": {
                            "method": "PUT",
                            "url": f"/api/v1/replays/{replay_id}/content",
                            "headers": {},
                        },
                    }
                ),
                FakeResponse({"replay_id": replay_id, "status": "queued"}),
                FakeResponse(_linked_evidence_payload(artifact_ids=[leaked_id])),
            ],
            "PUT": [FakeResponse({}, status_code=204)],
            "GET": [
                FakeResponse({"match_id": "NA1_1", "platform": "NA1"}),
                FakeResponse({"replay_id": replay_id, "status": "ready"}),
                FakeResponse({"artifacts": [{"artifact_id": manifest_id}]}),
            ],
            "DELETE": [],
        }
    )

    with pytest.raises(smoke.SmokeFailure) as raised:
        smoke.run_smoke(
            client=client,
            api_base_url="http://localhost:8000",
            match_id="NA1_1",
            puuid="smoke-player-puuid",
            video_path=video_path,
            poll_interval_seconds=0,
            poll_timeout_seconds=1,
            joint_evidence_enabled=True,
        )

    assert raised.value.code == "SMOKE_EVIDENCE_ARTIFACT_MISMATCH"
    assert all(request[0] != "DELETE" for request in client.requests)


def test_e2e_compose_enables_joint_evidence_only_for_the_ephemeral_run() -> None:
    script = (REPOSITORY_ROOT / "scripts" / "e2e_replay_compose.sh").read_text()
    compose = (REPOSITORY_ROOT / "docker-compose.yml").read_text()
    makefile = (REPOSITORY_ROOT / "Makefile").read_text()

    assert "export JOINT_EVIDENCE_ENABLED=true" in script
    assert "JOINT_EVIDENCE_ENABLED: ${JOINT_EVIDENCE_ENABLED:-false}" in compose
    assert "smoke-riot:" in makefile
    assert "scripts/smoke_riot.py" in makefile
    assert 'echo "$JOINT_EVIDENCE_ENABLED"' not in script
    assert 'cat "$repo_dir/.env"' not in script
