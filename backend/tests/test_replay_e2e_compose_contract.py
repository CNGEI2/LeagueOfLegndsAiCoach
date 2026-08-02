"""Contracts for the Replay R1 Docker Compose end-to-end flow script.

Docker CLI availability varies by environment, so this suite checks the
script and Makefile wiring exist and document the full flow, rather than
requiring a live `docker compose` run.
"""

from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
E2E_SCRIPT = REPOSITORY_ROOT / "scripts" / "e2e_replay_compose.sh"

_REQUIRED_STEP_MARKERS = (
    "zh-CN",
    "en-US",
    "upload",
    "refresh",
    "frames",
    "delete",
    "cleanup",
)


def test_e2e_compose_script_exists_and_is_executable() -> None:
    assert E2E_SCRIPT.is_file()
    assert E2E_SCRIPT.stat().st_mode & 0o111, "script must be executable"


def test_e2e_compose_script_documents_the_full_replay_flow() -> None:
    contents = E2E_SCRIPT.read_text(encoding="utf-8").lower()
    for marker in _REQUIRED_STEP_MARKERS:
        assert marker.lower() in contents, f"missing required step marker: {marker!r}"


def test_e2e_compose_script_drives_docker_compose_and_smoke_replay() -> None:
    contents = E2E_SCRIPT.read_text(encoding="utf-8")
    assert "docker compose" in contents
    assert "smoke_replay.py" in contents or "smoke-replay" in contents


def test_e2e_compose_smoke_requires_platform_and_zero_remaining_replay_objects() -> None:
    """A DELETE acknowledgement is insufficient until async cleanup is done."""
    contents = E2E_SCRIPT.read_text(encoding="utf-8")

    assert "REPLAY_SMOKE_PLATFORM" in contents
    assert "read_smoke_env_value" in contents
    assert "/.env" in contents
    assert "remaining_objects" in contents
    assert '[[ "$remaining_objects" != "0" ]]' in contents
    assert "FAILED: replay_data volume still contains" in contents


def test_e2e_compose_script_notes_when_docker_is_unavailable() -> None:
    contents = E2E_SCRIPT.read_text(encoding="utf-8").lower()
    assert "docker" in contents
    assert "not executed" in contents or "skip" in contents or "unavailable" in contents


def test_makefile_defines_e2e_replay_compose_target_that_runs_the_script() -> None:
    makefile = (REPOSITORY_ROOT / "Makefile").read_text()
    assert "e2e-replay-compose:" in makefile
    assert "e2e_replay_compose.sh" in makefile
