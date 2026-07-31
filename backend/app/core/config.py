from functools import cached_property
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "postgresql+asyncpg://lol_ai_coach:lol_ai_coach@localhost:5432/lol_ai_coach"
    backend_cors_origins: str = "http://localhost:3000"
    riot_api_key: SecretStr = SecretStr("")
    riot_connect_timeout_seconds: float = 2.0
    riot_read_timeout_seconds: float = 5.0
    riot_total_timeout_seconds: float = 10.0
    riot_retry_max_delay_seconds: float = 2.0
    riot_max_concurrency: int = 4
    player_cache_ttl_seconds: int = 900
    recent_matches_cache_ttl_seconds: int = 120
    match_retention_days: int = 30
    riot_smoke_game_name: str = ""
    riot_smoke_tag_line: str = ""
    riot_smoke_platform: str = "NA1"
    smoke_api_base_url: str = "http://localhost:8000"

    model_config = SettingsConfigDict(env_file=ROOT_ENV_FILE, extra="ignore")

    @cached_property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]

    @property
    def riot_configured(self) -> bool:
        return bool(self.riot_api_key.get_secret_value())
