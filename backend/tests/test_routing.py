import pytest

from app.core.routing import (
    Platform,
    Region,
    display_name_for,
    ordered_platforms,
    regional_host_for,
    routes_for,
)

EXPECTED_REGIONS = {"AMERICAS", "ASIA", "EUROPE", "SEA"}
EXPECTED_PLATFORM_CODES = {
    "BR1",
    "EUN1",
    "EUW1",
    "JP1",
    "KR",
    "LA1",
    "LA2",
    "NA1",
    "OC1",
    "TR1",
    "RU",
    "PH2",
    "SG2",
    "TH2",
    "TW2",
    "VN2",
}

CATALOG = {
    "BR1": (10, "AMERICAS", "br1.api.riotgames.com", "巴西服", "Brazil"),
    "EUN1": (20, "EUROPE", "eun1.api.riotgames.com", "欧东北服", "Europe Nordic & East"),
    "EUW1": (30, "EUROPE", "euw1.api.riotgames.com", "欧西服", "Europe West"),
    "JP1": (40, "ASIA", "jp1.api.riotgames.com", "日服", "Japan"),
    "KR": (50, "ASIA", "kr.api.riotgames.com", "韩服", "Korea"),
    "LA1": (60, "AMERICAS", "la1.api.riotgames.com", "拉丁美洲北服", "Latin America North"),
    "LA2": (70, "AMERICAS", "la2.api.riotgames.com", "拉丁美洲南服", "Latin America South"),
    "NA1": (80, "AMERICAS", "na1.api.riotgames.com", "北美服", "North America"),
    "OC1": (90, "SEA", "oc1.api.riotgames.com", "大洋洲服", "Oceania"),
    "TR1": (100, "EUROPE", "tr1.api.riotgames.com", "土耳其服", "Türkiye"),
    "RU": (110, "EUROPE", "ru.api.riotgames.com", "俄服", "Russia"),
    "PH2": (120, "SEA", "ph2.api.riotgames.com", "菲律宾服", "Philippines"),
    "SG2": (130, "SEA", "sg2.api.riotgames.com", "新加坡服", "Singapore"),
    "TH2": (140, "SEA", "th2.api.riotgames.com", "泰国服", "Thailand"),
    "TW2": (150, "SEA", "tw2.api.riotgames.com", "台服", "Taiwan"),
    "VN2": (160, "SEA", "vn2.api.riotgames.com", "越南服", "Vietnam"),
}

REGIONAL_HOSTS = {
    "AMERICAS": "americas.api.riotgames.com",
    "ASIA": "asia.api.riotgames.com",
    "EUROPE": "europe.api.riotgames.com",
    "SEA": "sea.api.riotgames.com",
}


def test_region_and_platform_enums_match_the_closed_catalog() -> None:
    assert {region.value for region in Region} == EXPECTED_REGIONS
    assert {platform.value for platform in Platform} == EXPECTED_PLATFORM_CODES


def test_na1_routes_account_and_match_regionally_but_summoner_by_platform() -> None:
    routes = routes_for(Platform.NA1)

    assert routes.regional_host == "americas.api.riotgames.com"
    assert routes.platform_host == "na1.api.riotgames.com"
    assert routes.region == Region.AMERICAS


@pytest.mark.parametrize("platform_code", sorted(EXPECTED_PLATFORM_CODES))
def test_every_platform_has_typed_routes_and_display_names(platform_code: str) -> None:
    platform = Platform(platform_code)
    sort_order, region_code, platform_host, name_zh, name_en = CATALOG[platform_code]
    routes = routes_for(platform)

    assert platform_host == platform_host.lower()
    assert platform_host.endswith(".api.riotgames.com")
    assert routes.platform_host == platform_host
    assert routes.region == Region(region_code)
    assert routes.region.value in EXPECTED_REGIONS
    assert routes.regional_host == REGIONAL_HOSTS[region_code]
    assert routes.display_name_zh == name_zh
    assert routes.display_name_en == name_en
    assert routes.display_name_zh.strip()
    assert routes.display_name_en.strip()
    assert routes.sort_order == sort_order


def test_sort_orders_are_unique_and_stable() -> None:
    platforms = ordered_platforms()
    assert tuple(platform.value for platform in platforms) == tuple(
        code for code, _ in sorted(CATALOG.items(), key=lambda item: item[1][0])
    )
    sort_orders = [routes_for(platform).sort_order for platform in platforms]
    assert sort_orders == sorted(sort_orders)
    assert len(set(sort_orders)) == len(sort_orders)


def test_regional_host_for_returns_closed_catalog_hosts() -> None:
    for region_code, host in REGIONAL_HOSTS.items():
        assert regional_host_for(Region(region_code)) == host


def test_display_name_for_supports_zh_and_en_locales() -> None:
    assert display_name_for(Platform.NA1, "zh-CN") == "北美服"
    assert display_name_for(Platform.NA1, "en-US") == "North America"
    assert display_name_for(Platform.EUW1, "zh-CN") == "欧西服"
    assert display_name_for(Platform.EUW1, "en-US") == "Europe West"


def test_unknown_platform_and_region_are_rejected_before_an_upstream_request() -> None:
    with pytest.raises(ValueError):
        Platform("bad")
    with pytest.raises(ValueError):
        Region("ATLANTIS")


def test_routes_api_does_not_accept_raw_hostnames() -> None:
    with pytest.raises((ValueError, TypeError, KeyError)):
        routes_for("na1.api.riotgames.com")  # type: ignore[arg-type]
    with pytest.raises((ValueError, TypeError, KeyError)):
        regional_host_for("americas.api.riotgames.com")  # type: ignore[arg-type]
