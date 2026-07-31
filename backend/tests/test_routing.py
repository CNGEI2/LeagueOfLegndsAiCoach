import pytest

from app.core.routing import Platform, routes_for


def test_na1_routes_account_and_match_regionally_but_summoner_by_platform() -> None:
    routes = routes_for(Platform.NA1)

    assert routes.regional_host == "americas.api.riotgames.com"
    assert routes.platform_host == "na1.api.riotgames.com"


def test_unknown_platform_is_rejected_before_an_upstream_request() -> None:
    with pytest.raises(ValueError):
        Platform("EUW1")
