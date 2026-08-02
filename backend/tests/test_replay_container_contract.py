"""Static contracts for Replay R1 Docker image and Compose wiring."""

from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REPLAY_MOUNT = "/var/lib/lol-ai-coach/replays"
FRONTEND_FORBIDDEN_ENV = (
    "REPLAY_TOKEN_SECRET",
    "REPLAY_S3_ACCESS_KEY_ID",
    "REPLAY_S3_SECRET_ACCESS_KEY",
    "RIOT_API_KEY",
    "OPENAI_API_KEY",
)


def _service_block(compose: str, name: str) -> str:
    marker = f"  {name}:\n"
    start = compose.index(marker)
    next_service = re.search(r"\n  \S", compose[start + len(marker) :])
    if next_service is None:
        return compose[start:]
    return compose[start : start + len(marker) + next_service.start()]


def test_backend_image_installs_ffmpeg_and_cleans_apt_metadata() -> None:
    """Replay processing requires ffmpeg inside the backend image used by the worker."""
    dockerfile = (REPOSITORY_ROOT / "backend" / "Dockerfile").read_text()

    assert "apt-get update" in dockerfile
    assert "apt-get install -y --no-install-recommends ffmpeg" in dockerfile
    assert "rm -rf /var/lib/apt/lists/*" in dockerfile


def test_compose_defines_independent_replay_worker_with_shared_replay_volume() -> None:
    """API and worker must share private replay storage and use a real dependency healthcheck."""
    compose = (REPOSITORY_ROOT / "docker-compose.yml").read_text()
    assert "  replay-worker:\n" in compose
    assert "replay_data:" in compose

    backend = _service_block(compose, "backend")
    worker = _service_block(compose, "replay-worker")
    frontend = _service_block(compose, "frontend")

    assert f"replay_data:{REPLAY_MOUNT}" in backend
    assert f"replay_data:{REPLAY_MOUNT}" in worker
    assert 'command: ["python", "-m", "app.workers.replay"]' in worker
    assert '["CMD", "python", "-m", "app.workers.replay", "--check"]' in worker
    assert "REPLAY_ENABLED: ${REPLAY_ENABLED:-false}" in backend
    assert "REPLAY_ENABLED: ${REPLAY_ENABLED:-false}" in worker
    assert "REPLAY_LOCAL_ROOT" in backend
    assert REPLAY_MOUNT in backend
    assert "build: ./backend" in worker or "build:\n      context: ./backend" in worker

    for forbidden in FRONTEND_FORBIDDEN_ENV:
        assert forbidden not in frontend


def test_backend_image_runs_as_a_non_root_user() -> None:
    """The API and worker containers must never run their process as root."""
    dockerfile = (REPOSITORY_ROOT / "backend" / "Dockerfile").read_text()

    assert "useradd" in dockerfile
    assert re.search(r"^USER\s+(?!root\b)\S+", dockerfile, re.MULTILINE) is not None
    # Ownership of the replay volume mountpoint must be seeded pre-mount so a
    # non-root, read-only-root-filesystem worker can still write to it.
    assert "chown" in dockerfile
    assert REPLAY_MOUNT in dockerfile


def test_worker_hardened_with_read_only_root_and_writable_scratch() -> None:
    """The worker's root filesystem is read-only; scratch space comes from tmpfs."""
    compose = (REPOSITORY_ROOT / "docker-compose.yml").read_text()
    worker = _service_block(compose, "replay-worker")

    assert re.search(r"user:\s*[\"']?\d+:\d+[\"']?", worker) is not None
    assert re.search(r"read_only:\s*true", worker) is not None
    assert re.search(r"tmpfs:", worker) is not None
    assert re.search(r"/tmp:size=\d+[A-Za-z]", worker) is not None
    # The replay data volume must remain writable despite the read-only root.
    assert f"replay_data:{REPLAY_MOUNT}" in worker


def test_worker_has_a_stop_grace_period_for_draining_in_flight_jobs() -> None:
    """SIGTERM must not be escalated to SIGKILL before an in-flight job can finish.

    The worker itself already drains gracefully: `_consumer_loop` stops
    claiming new jobs once `stop_event` is set but does not cancel the job
    currently being processed (see `test_stop_event_stops_claiming_new_jobs`
    in `test_replay_worker.py`). This only verifies Docker is configured to
    give that in-flight job real wall-clock time before force-killing it.
    """
    compose = (REPOSITORY_ROOT / "docker-compose.yml").read_text()
    worker = _service_block(compose, "replay-worker")

    match = re.search(r"stop_grace_period:\s*(\d+)([a-z]*)", worker)
    assert match is not None
    value, unit = match.groups()
    seconds = int(value) * (60 if unit == "m" else 1)
    assert seconds >= 60


def test_env_example_keeps_replay_secrets_and_smoke_identity_empty() -> None:
    """Committed examples must never ship a replay token secret or smoke identity."""
    env_example = (REPOSITORY_ROOT / ".env.example").read_text().splitlines()
    values = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in env_example
        if "=" in line and not line.lstrip().startswith("#")
    }

    assert values.get("REPLAY_TOKEN_SECRET") == ""
    assert values.get("REPLAY_SMOKE_MATCH_ID") == ""
    assert values.get("REPLAY_SMOKE_PUUID") == ""
    assert values.get("REPLAY_ENABLED") == "false"
    assert values.get("REPLAY_S3_ACCESS_KEY_ID") == ""
    assert values.get("REPLAY_S3_SECRET_ACCESS_KEY") == ""
