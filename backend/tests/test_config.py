from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import ROOT_ENV_FILE, Settings
from app.core.routing import Region


def test_settings_have_safe_local_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env == "development"
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.cors_origins == ["http://localhost:3000"]


def test_replay_settings_are_disabled_by_default() -> None:
    settings = Settings(_env_file=None)
    assert settings.replay_enabled is False
    assert settings.replay_max_bytes == 4 * 1024**3
    assert settings.replay_min_duration_seconds == 600
    assert settings.replay_max_duration_seconds == 5400


def test_settings_resolve_the_env_file_from_the_repository_root() -> None:
    assert Path(__file__).resolve().parents[2] / ".env" == ROOT_ENV_FILE
    assert Settings.model_config["env_file"] == ROOT_ENV_FILE


def test_settings_parse_comma_separated_cors_origins() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql+asyncpg://user:pass@db:5432/lol_ai_coach",
        backend_cors_origins="http://localhost:3000,https://coach.example.com",
    )

    assert settings.cors_origins == [
        "http://localhost:3000",
        "https://coach.example.com",
    ]


def test_replay_enabled_requires_token_secret_of_at_least_32_bytes() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, replay_enabled=True, replay_token_secret="")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, replay_enabled=True, replay_token_secret="short")
    settings = Settings(
        _env_file=None,
        replay_enabled=True,
        replay_token_secret="x" * 32,
    )
    assert settings.replay_enabled is True


def test_production_replay_requires_gateway_rate_limits() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="production",
            replay_enabled=True,
            replay_token_secret="x" * 32,
            replay_gateway_rate_limits_enforced=False,
        )
    settings = Settings(
        _env_file=None,
        app_env="production",
        replay_enabled=True,
        replay_token_secret="x" * 32,
        replay_gateway_rate_limits_enforced=True,
    )
    assert settings.replay_gateway_rate_limits_enforced is True


def test_replay_gateway_rate_limit_defaults_match_the_documented_limits() -> None:
    settings = Settings(_env_file=None)

    assert settings.replay_gateway_rate_limits_enforced is False
    assert settings.replay_gateway_create_limit_per_hour == 5
    assert settings.replay_gateway_upload_concurrency_limit == 2
    assert settings.replay_gateway_request_limit_per_minute == 60
    assert settings.replay_trusted_proxy_networks == ()


def test_replay_trusted_proxy_cidrs_parses_comma_separated_networks() -> None:
    settings = Settings(_env_file=None, replay_trusted_proxy_cidrs="10.0.0.0/8, 172.16.0.0/12")

    networks = settings.replay_trusted_proxy_networks
    assert len(networks) == 2
    assert str(networks[0]) == "10.0.0.0/8"
    assert str(networks[1]) == "172.16.0.0/12"


def test_unknown_replay_storage_backend_is_rejected_by_pydantic() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, replay_storage_backend="gcs")  # type: ignore[arg-type]


def test_build_replay_storage_fail_closed_when_disabled() -> None:
    from app.services.replays.storage.factory import build_replay_storage

    with pytest.raises(ValueError, match="disabled"):
        build_replay_storage(Settings(_env_file=None, replay_enabled=False))


def test_platform_detection_settings_have_safe_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.riot_platform_detection_enabled is False
    assert settings.riot_platform_detection_ttl_seconds == 86400
    assert settings.riot_platform_detection_not_found_ttl_seconds == 300
    assert settings.riot_platform_confirmation_ttl_seconds == 900
    assert settings.riot_account_primary_region is Region.AMERICAS
    assert isinstance(settings.riot_account_primary_region, Region)
    assert settings.riot_max_concurrency == 4


def test_platform_detection_ttl_bounds_are_enforced() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, riot_platform_detection_ttl_seconds=59)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, riot_platform_detection_ttl_seconds=604_801)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, riot_platform_detection_not_found_ttl_seconds=29)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, riot_platform_detection_not_found_ttl_seconds=3601)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, riot_platform_confirmation_ttl_seconds=59)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, riot_platform_confirmation_ttl_seconds=3601)

    settings = Settings(
        _env_file=None,
        riot_platform_detection_ttl_seconds=60,
        riot_platform_detection_not_found_ttl_seconds=30,
        riot_platform_confirmation_ttl_seconds=60,
    )
    assert settings.riot_platform_detection_ttl_seconds == 60
    assert settings.riot_platform_detection_not_found_ttl_seconds == 30
    assert settings.riot_platform_confirmation_ttl_seconds == 60


def test_riot_account_primary_region_must_be_a_known_region() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, riot_account_primary_region="ATLANTIS")
    settings = Settings(_env_file=None, riot_account_primary_region="EUROPE")
    assert settings.riot_account_primary_region is Region.EUROPE
    assert isinstance(settings.riot_account_primary_region, Region)
    settings = Settings(_env_file=None, riot_account_primary_region=Region.ASIA)
    assert settings.riot_account_primary_region is Region.ASIA


def test_riot_max_concurrency_is_bounded_as_shared_probe_limit() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, riot_max_concurrency=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, riot_max_concurrency=17)
    settings = Settings(_env_file=None, riot_max_concurrency=1)
    assert settings.riot_max_concurrency == 1
    settings = Settings(_env_file=None, riot_max_concurrency=16)
    assert settings.riot_max_concurrency == 16
