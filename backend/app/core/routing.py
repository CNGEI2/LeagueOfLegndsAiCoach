from dataclasses import dataclass
from enum import StrEnum


class Platform(StrEnum):
    NA1 = "NA1"


@dataclass(frozen=True)
class RiotRoutes:
    regional_host: str
    platform_host: str


ROUTES: dict[Platform, RiotRoutes] = {
    Platform.NA1: RiotRoutes(
        regional_host="americas.api.riotgames.com",
        platform_host="na1.api.riotgames.com",
    )
}


def routes_for(platform: Platform) -> RiotRoutes:
    return ROUTES[platform]
