import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]


def _service_block(compose: str, name: str) -> str:
    marker = f"  {name}:\n"
    start = compose.index(marker)
    next_service = re.search(r"\n  \S", compose[start + len(marker) :])
    if next_service is None:
        return compose[start:]
    return compose[start : start + len(marker) + next_service.start()]


def test_compose_migrates_a_healthy_database_before_starting_the_backend() -> None:
    """Removing migration gating would let readiness succeed without cache tables."""
    dockerfile = (REPOSITORY_ROOT / "backend" / "Dockerfile").read_text()
    compose = (REPOSITORY_ROOT / "docker-compose.yml").read_text()
    assert "  migrate:\n" in compose
    migrate = _service_block(compose, "migrate")
    backend = _service_block(compose, "backend")

    assert "COPY alembic.ini ./" in dockerfile
    assert "COPY alembic ./alembic" in dockerfile
    assert 'command: ["alembic", "upgrade", "head"]' in migrate
    assert "db:\n        condition: service_healthy" in migrate
    assert "migrate:\n        condition: service_completed_successfully" in backend
    assert "--no-access-log" in dockerfile
