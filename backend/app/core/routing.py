from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class Region(StrEnum):
    AMERICAS = "AMERICAS"
    ASIA = "ASIA"
    EUROPE = "EUROPE"
    SEA = "SEA"


class Platform(StrEnum):
    BR1 = "BR1"
    EUN1 = "EUN1"
    EUW1 = "EUW1"
    JP1 = "JP1"
    KR = "KR"
    LA1 = "LA1"
    LA2 = "LA2"
    NA1 = "NA1"
    OC1 = "OC1"
    TR1 = "TR1"
    RU = "RU"
    PH2 = "PH2"
    SG2 = "SG2"
    TH2 = "TH2"
    TW2 = "TW2"
    VN2 = "VN2"


REGIONAL_HOSTS: dict[Region, str] = {
    Region.AMERICAS: "americas.api.riotgames.com",
    Region.ASIA: "asia.api.riotgames.com",
    Region.EUROPE: "europe.api.riotgames.com",
    Region.SEA: "sea.api.riotgames.com",
}


@dataclass(frozen=True)
class RiotRoutes:
    region: Region
    platform_host: str
    display_name_zh: str
    display_name_en: str
    sort_order: int

    @property
    def regional_host(self) -> str:
        return REGIONAL_HOSTS[self.region]


ROUTES: dict[Platform, RiotRoutes] = {
    Platform.BR1: RiotRoutes(
        region=Region.AMERICAS,
        platform_host="br1.api.riotgames.com",
        display_name_zh="巴西服",
        display_name_en="Brazil",
        sort_order=10,
    ),
    Platform.EUN1: RiotRoutes(
        region=Region.EUROPE,
        platform_host="eun1.api.riotgames.com",
        display_name_zh="欧东北服",
        display_name_en="Europe Nordic & East",
        sort_order=20,
    ),
    Platform.EUW1: RiotRoutes(
        region=Region.EUROPE,
        platform_host="euw1.api.riotgames.com",
        display_name_zh="欧西服",
        display_name_en="Europe West",
        sort_order=30,
    ),
    Platform.JP1: RiotRoutes(
        region=Region.ASIA,
        platform_host="jp1.api.riotgames.com",
        display_name_zh="日服",
        display_name_en="Japan",
        sort_order=40,
    ),
    Platform.KR: RiotRoutes(
        region=Region.ASIA,
        platform_host="kr.api.riotgames.com",
        display_name_zh="韩服",
        display_name_en="Korea",
        sort_order=50,
    ),
    Platform.LA1: RiotRoutes(
        region=Region.AMERICAS,
        platform_host="la1.api.riotgames.com",
        display_name_zh="拉丁美洲北服",
        display_name_en="Latin America North",
        sort_order=60,
    ),
    Platform.LA2: RiotRoutes(
        region=Region.AMERICAS,
        platform_host="la2.api.riotgames.com",
        display_name_zh="拉丁美洲南服",
        display_name_en="Latin America South",
        sort_order=70,
    ),
    Platform.NA1: RiotRoutes(
        region=Region.AMERICAS,
        platform_host="na1.api.riotgames.com",
        display_name_zh="北美服",
        display_name_en="North America",
        sort_order=80,
    ),
    Platform.OC1: RiotRoutes(
        region=Region.SEA,
        platform_host="oc1.api.riotgames.com",
        display_name_zh="大洋洲服",
        display_name_en="Oceania",
        sort_order=90,
    ),
    Platform.TR1: RiotRoutes(
        region=Region.EUROPE,
        platform_host="tr1.api.riotgames.com",
        display_name_zh="土耳其服",
        display_name_en="Türkiye",
        sort_order=100,
    ),
    Platform.RU: RiotRoutes(
        region=Region.EUROPE,
        platform_host="ru.api.riotgames.com",
        display_name_zh="俄服",
        display_name_en="Russia",
        sort_order=110,
    ),
    Platform.PH2: RiotRoutes(
        region=Region.SEA,
        platform_host="ph2.api.riotgames.com",
        display_name_zh="菲律宾服",
        display_name_en="Philippines",
        sort_order=120,
    ),
    Platform.SG2: RiotRoutes(
        region=Region.SEA,
        platform_host="sg2.api.riotgames.com",
        display_name_zh="新加坡服",
        display_name_en="Singapore",
        sort_order=130,
    ),
    Platform.TH2: RiotRoutes(
        region=Region.SEA,
        platform_host="th2.api.riotgames.com",
        display_name_zh="泰国服",
        display_name_en="Thailand",
        sort_order=140,
    ),
    Platform.TW2: RiotRoutes(
        region=Region.SEA,
        platform_host="tw2.api.riotgames.com",
        display_name_zh="台服",
        display_name_en="Taiwan",
        sort_order=150,
    ),
    Platform.VN2: RiotRoutes(
        region=Region.SEA,
        platform_host="vn2.api.riotgames.com",
        display_name_zh="越南服",
        display_name_en="Vietnam",
        sort_order=160,
    ),
}


def routes_for(platform: Platform) -> RiotRoutes:
    return ROUTES[platform]


def regional_host_for(region: Region) -> str:
    return REGIONAL_HOSTS[region]


def ordered_platforms() -> tuple[Platform, ...]:
    return tuple(
        platform for platform, _ in sorted(ROUTES.items(), key=lambda item: item[1].sort_order)
    )


def display_name_for(platform: Platform, locale: Literal["zh-CN", "en-US"]) -> str:
    routes = routes_for(platform)
    if locale == "zh-CN":
        return routes.display_name_zh
    return routes.display_name_en
