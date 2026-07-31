"""Run the Phase 2 local Riot smoke flow without exposing configured values."""

from __future__ import annotations

import sys

import httpx2
from app.core.config import Settings
from app.services.riot.smoke import SmokeFailure, require_smoke_configuration, run_smoke


def main() -> int:
    settings = Settings()
    try:
        require_smoke_configuration(
            game_name=settings.riot_smoke_game_name,
            tag_line=settings.riot_smoke_tag_line,
            platform=settings.riot_smoke_platform,
            riot_configured=settings.riot_configured,
        )
        with httpx2.Client(timeout=10.0) as client:
            run_smoke(
                client=client,
                api_base_url=settings.smoke_api_base_url,
                game_name=settings.riot_smoke_game_name,
                tag_line=settings.riot_smoke_tag_line,
                platform=settings.riot_smoke_platform,
            )
    except SmokeFailure as error:
        print(error)
        return 1
    except Exception:  # noqa: BLE001 - the CLI boundary must redact unexpected failures.
        print(SmokeFailure("SMOKE_REQUEST_FAILED"))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
