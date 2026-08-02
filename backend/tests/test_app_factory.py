from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.core.dependencies import AppServices
from app.main import create_app
from app.services.replays.storage.local import LocalReplayStorage
from app.services.replays.storage.s3 import S3ReplayStorage
from tests.conftest import FakeDatabase, FakeMatchService, FakePlayerService, FakeReplayService


def _services() -> AppServices:
    return AppServices(
        player_service=FakePlayerService(),
        match_service=FakeMatchService(),
        replay_service=FakeReplayService(),
        closers=(),
    )


def test_create_app_builds_local_storage_by_default_when_replay_enabled(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql+asyncpg://user:pass@db:5432/lol_ai_coach",
        riot_api_key="RGAPI-test",
        replay_enabled=True,
        replay_token_secret="x" * 32,
        replay_storage_backend="local",
        replay_local_root=tmp_path,
    )

    application = create_app(settings=settings, database=FakeDatabase(), services=_services())

    assert application.state.replay_storage is not None
    assert isinstance(application.state.replay_storage, LocalReplayStorage)


def test_create_app_builds_s3_storage_via_factory_when_backend_is_s3(tmp_path: Path) -> None:
    """Regression test: create_app previously only ever constructed
    LocalReplayStorage directly and left app.state.replay_storage as None
    for any other backend, silently breaking every replay route (they all
    404 with REPLAY_NOT_FOUND when storage is None) whenever
    REPLAY_STORAGE_BACKEND=s3 in production."""
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql+asyncpg://user:pass@db:5432/lol_ai_coach",
        riot_api_key="RGAPI-test",
        replay_enabled=True,
        replay_token_secret="x" * 32,
        replay_storage_backend="s3",
        replay_s3_endpoint_url="https://s3.example.invalid",
        replay_s3_region="us-east-1",
        replay_s3_bucket="replays-bucket",
        replay_s3_access_key_id="fake-access-key",
        replay_s3_secret_access_key="fake-secret-key",
        replay_s3_prefix="replays",
    )

    application = create_app(settings=settings, database=FakeDatabase(), services=_services())

    assert application.state.replay_storage is not None
    assert isinstance(application.state.replay_storage, S3ReplayStorage)


def test_create_app_leaves_storage_none_when_replay_disabled() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql+asyncpg://user:pass@db:5432/lol_ai_coach",
        riot_api_key="RGAPI-test",
        replay_enabled=False,
    )

    application = create_app(settings=settings, database=FakeDatabase(), services=_services())

    assert application.state.replay_storage is None


def test_create_app_prefers_explicitly_injected_storage_over_the_factory(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql+asyncpg://user:pass@db:5432/lol_ai_coach",
        riot_api_key="RGAPI-test",
        replay_enabled=True,
        replay_token_secret="x" * 32,
        replay_storage_backend="s3",
        replay_s3_endpoint_url="https://s3.example.invalid",
        replay_s3_region="us-east-1",
        replay_s3_bucket="replays-bucket",
        replay_s3_access_key_id="fake-access-key",
        replay_s3_secret_access_key="fake-secret-key",
        replay_s3_prefix="replays",
    )
    injected = LocalReplayStorage(tmp_path)

    application = create_app(
        settings=settings,
        database=FakeDatabase(),
        services=_services(),
        replay_storage=injected,
    )

    assert application.state.replay_storage is injected
