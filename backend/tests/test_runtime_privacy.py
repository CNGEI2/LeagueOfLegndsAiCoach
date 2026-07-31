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
