from functools import cached_property
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "postgresql+asyncpg://lol_ai_coach:lol_ai_coach@localhost:5432/lol_ai_coach"
    backend_cors_origins: str = "http://localhost:3000"

    model_config = SettingsConfigDict(env_file=ROOT_ENV_FILE, extra="ignore")

    @cached_property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]
