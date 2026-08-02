import ipaddress
from functools import cached_property
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.routing import Region

IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

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
    riot_max_concurrency: int = Field(default=4, ge=1, le=16)
    riot_platform_detection_enabled: bool = False
    riot_platform_detection_ttl_seconds: int = Field(default=86400, ge=60, le=604800)
    riot_platform_detection_not_found_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    riot_platform_confirmation_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    riot_account_primary_region: str = "AMERICAS"
    player_cache_ttl_seconds: int = 900
    recent_matches_cache_ttl_seconds: int = 120
    match_retention_days: int = 30
    riot_smoke_game_name: str = ""
    riot_smoke_tag_line: str = ""
    riot_smoke_platform: str = "NA1"
    smoke_api_base_url: str = "http://localhost:8000"
    replay_enabled: bool = False
    replay_storage_backend: Literal["local", "s3"] = "local"
    replay_local_root: Path = ROOT_ENV_FILE.parent / "var" / "replays"
    replay_token_secret: SecretStr = SecretStr("")
    replay_max_bytes: int = 4 * 1024**3
    replay_min_duration_seconds: int = 600
    replay_max_duration_seconds: int = 5400
    replay_upload_expiry_seconds: int = 1800
    replay_source_retention_hours: int = 24
    replay_derived_retention_days: int = 7
    replay_worker_concurrency: int = 1
    replay_ffmpeg_path: str = "ffmpeg"
    replay_ffprobe_path: str = "ffprobe"
    replay_process_timeout_seconds: int = 7200
    replay_s3_endpoint_url: str = ""
    replay_s3_region: str = ""
    replay_s3_bucket: str = ""
    replay_s3_access_key_id: SecretStr = SecretStr("")
    replay_s3_secret_access_key: SecretStr = SecretStr("")
    replay_s3_prefix: str = "replays"
    replay_gateway_rate_limits_enforced: bool = False
    replay_gateway_create_limit_per_hour: int = 5
    replay_gateway_upload_concurrency_limit: int = 2
    replay_gateway_request_limit_per_minute: int = 60
    replay_trusted_proxy_cidrs: str = ""
    internal_metrics_token: SecretStr = SecretStr("")

    model_config = SettingsConfigDict(env_file=ROOT_ENV_FILE, extra="ignore")

    @cached_property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]

    @cached_property
    def replay_trusted_proxy_networks(self) -> tuple[IpNetwork, ...]:
        networks: list[IpNetwork] = []
        for entry in self.replay_trusted_proxy_cidrs.split(","):
            candidate = entry.strip()
            if not candidate:
                continue
            networks.append(ipaddress.ip_network(candidate, strict=False))
        return tuple(networks)

    @property
    def riot_configured(self) -> bool:
        return bool(self.riot_api_key.get_secret_value())

    @field_validator("riot_account_primary_region")
    @classmethod
    def validate_riot_account_primary_region(cls, value: str) -> str:
        try:
            return Region(value).value
        except ValueError as exc:
            raise ValueError(
                "RIOT_ACCOUNT_PRIMARY_REGION must be one of "
                f"{', '.join(region.value for region in Region)}"
            ) from exc

    @model_validator(mode="after")
    def validate_replay_settings(self) -> Self:
        if not self.replay_enabled:
            return self

        secret = self.replay_token_secret.get_secret_value()
        if len(secret.encode("utf-8")) < 32:
            raise ValueError(
                "REPLAY_TOKEN_SECRET must contain at least 32 bytes when replay is enabled"
            )
        if self.app_env == "production" and not self.replay_gateway_rate_limits_enforced:
            raise ValueError(
                "REPLAY_GATEWAY_RATE_LIMITS_ENFORCED must be true in production "
                "when replay is enabled"
            )
        return self
