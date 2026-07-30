from app.core.config import Settings


def test_settings_have_safe_local_defaults() -> None:
    settings = Settings()

    assert settings.app_env == "development"
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.cors_origins == ["http://localhost:3000"]


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
