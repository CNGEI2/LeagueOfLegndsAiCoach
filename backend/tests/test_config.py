from pathlib import Path

from app.core.config import ROOT_ENV_FILE, Settings


def test_settings_have_safe_local_defaults() -> None:
    settings = Settings()

    assert settings.app_env == "development"
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.cors_origins == ["http://localhost:3000"]


def test_settings_resolve_the_env_file_from_the_repository_root() -> None:
    assert Path(__file__).resolve().parents[2] / ".env" == ROOT_ENV_FILE
    assert Settings.model_config["env_file"] == ROOT_ENV_FILE


def test_settings_parse_comma_separated_cors_origins() -> None:
    settings = Settings(
        app_env="test",
        database_url="postgresql+asyncpg://user:pass@db:5432/lol_ai_coach",
        backend_cors_origins="http://localhost:3000,https://coach.example.com",
    )

    assert settings.cors_origins == [
        "http://localhost:3000",
        "https://coach.example.com",
    ]
