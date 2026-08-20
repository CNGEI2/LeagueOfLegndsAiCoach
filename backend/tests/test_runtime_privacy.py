from __future__ import annotations

import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_every_tracked_uvicorn_launch_disables_raw_access_logs() -> None:
    """Removing no-access-log from any tracked launcher would expose request identifiers."""
    tracked_files = subprocess.check_output(
        ["git", "ls-files"], cwd=REPOSITORY_ROOT, text=True
    ).splitlines()
    tracked_launch_files = ("Makefile", "backend/Dockerfile")
    assert all(path in tracked_files for path in tracked_launch_files)
    uvicorn_launches = [
        (path, line)
        for path in tracked_launch_files
        for line in (REPOSITORY_ROOT / path).read_text().splitlines()
        if "uvicorn" in line
    ]

    assert {path for path, _ in uvicorn_launches} == set(tracked_launch_files)
    assert all("--no-access-log" in launch for _, launch in uvicorn_launches)


def test_compose_declares_joint_evidence_disabled_by_default() -> None:
    compose = (REPOSITORY_ROOT / "docker-compose.yml").read_text()
    assert "JOINT_EVIDENCE_ENABLED: ${JOINT_EVIDENCE_ENABLED:-false}" in compose


def test_readme_documents_joint_evidence_rollout_and_rollback() -> None:
    readme = (REPOSITORY_ROOT / "README.md").read_text()
    assert "0004" in readme
    assert "JOINT_EVIDENCE_ENABLED" in readme
    assert "make smoke-riot" in readme
    assert "make smoke-replay" in readme
    assert "joint_evidence_" in readme
    assert "OpenAI" in readme
    assert "migration" in readme.lower()
