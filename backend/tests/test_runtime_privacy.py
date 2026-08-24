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


def test_analysis_runtime_configuration_stays_backend_only_and_dark_by_default() -> None:
    env_example = (REPOSITORY_ROOT / ".env.example").read_text()
    compose = (REPOSITORY_ROOT / "docker-compose.yml").read_text()
    backend_section = compose.split("  backend:\n", 1)[1].split("  replay-worker:\n", 1)[0]
    worker_section = compose.split("  replay-worker:\n", 1)[1].split("  frontend:\n", 1)[0]

    assert "DETERMINISTIC_ANALYSIS_ENABLED=false" in env_example
    assert "ANALYSIS_RETENTION_DAYS=30" in env_example
    assert (
        "DETERMINISTIC_ANALYSIS_ENABLED: ${DETERMINISTIC_ANALYSIS_ENABLED:-false}"
        in backend_section
    )
    assert "ANALYSIS_RETENTION_DAYS: ${ANALYSIS_RETENTION_DAYS:-30}" in backend_section
    assert "DETERMINISTIC_ANALYSIS_ENABLED" not in worker_section
    assert "ANALYSIS_RETENTION_DAYS" not in worker_section
    assert "NEXT_PUBLIC_DETERMINISTIC" not in env_example
    assert "NEXT_PUBLIC_ANALYSIS" not in env_example


def test_readme_documents_joint_evidence_rollout_and_rollback() -> None:
    readme = (REPOSITORY_ROOT / "README.md").read_text()
    assert "0004" in readme
    assert "JOINT_EVIDENCE_ENABLED" in readme
    assert "make smoke-riot" in readme
    assert "make smoke-replay" in readme
    assert "joint_evidence_" in readme
    assert "OpenAI" in readme
    assert "migration" in readme.lower()


def test_readme_documents_deterministic_analysis_boundary_and_rollout() -> None:
    readme = (REPOSITORY_ROOT / "README.md").read_text()
    for required in (
        "0005_deterministic_analyses",
        "DETERMINISTIC_ANALYSIS_ENABLED",
        "ANALYSIS_RETENTION_DAYS",
        "make smoke-analysis",
        "POST /api/v1/analyses",
        "GET /api/v1/analyses/{analysis_id}",
        "UTILITY -> Support",
        "UTILITY -> 辅助",
        "not a Riot score, rank, MMR, or ELO",
        "不是 Riot 评分、段位、MMR 或 ELO",
        "analysis_api_requests_total",
        "analysis_cache_total",
    ):
        assert required in readme
