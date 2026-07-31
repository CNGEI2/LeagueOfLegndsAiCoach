import httpx2
import pytest

from app.core.routing import Platform
from app.schemas.domain import Locale, PlayerProfile
from app.services.parsing.matches import normalize_match
from app.services.riot.dto import MatchDto
from app.services.static_data.client import StaticDataClient
from app.services.static_data.resolver import StaticDataResolver, compatible_version, locale_code
from tests.fixtures.riot_payloads import MATCH_PAYLOAD


class FakeStaticDataClient:
    def __init__(self, *, versions: tuple[str, ...]) -> None:
        self._versions = versions

    async def get_versions(self) -> tuple[str, ...]:
        return self._versions

    async def get_catalog(self, version: str, locale: str):  # type: ignore[no-untyped-def]
        from app.services.static_data.client import StaticCatalog

        return StaticCatalog.from_payloads(
            {"data": {"Ahri": {"key": "103", "name": "阿狸", "image": {"full": "Ahri.png"}}}},
            {
                "data": {
                    "1055": {
                        "name": "多兰之刃",
                        "image": {"full": "1055.png"},
                    },
                    "6672": {
                        "name": "岚切",
                        "image": {"full": "6672.png"},
                    },
                    "3006": {
                        "name": "狂战士胫甲",
                        "image": {"full": "3006.png"},
                    },
                }
            },
        )


class TimingOutStaticDataClient:
    async def get_versions(self) -> tuple[str, ...]:
        raise TimeoutError


def _profile() -> PlayerProfile:
    return PlayerProfile(
        puuid="player-puuid",
        game_name="Player",
        tag_line="1115",
        platform=Platform.NA1,
        summoner_level=772,
        profile_icon_id=29,
    )


def test_compatible_version_selects_newest_build_in_match_patch_family() -> None:
    """A historical match must use the newest available build from its own patch family."""
    versions = ("16.16.1", "16.15.2", "16.15.1", "16.14.1")

    assert compatible_version("16.15.602.1234", versions) == "16.15.2"


def test_incompatible_patch_does_not_use_current_static_data() -> None:
    """Current display data is wrong for a match from another patch family."""
    assert compatible_version("15.24.1.1", ("16.16.1", "16.15.2")) is None


@pytest.mark.parametrize(
    ("game_version", "versions"),
    [("not-a-version", ("16.15.2",)), ("16.15.1", ("bad", "16.x.2"))],
)
def test_invalid_versions_are_not_guessed(game_version: str, versions: tuple[str, ...]) -> None:
    """Malformed upstream version text must not select an arbitrary catalog."""
    assert compatible_version(game_version, versions) is None


def test_product_locale_maps_to_data_dragon_locale() -> None:
    """Product locales are deliberately mapped rather than passed through."""
    assert locale_code(Locale.ZH_CN) == "zh_CN"
    assert locale_code(Locale.EN_US) == "en_US"


@pytest.mark.asyncio
async def test_player_hydration_uses_newest_advertised_version_for_icon() -> None:
    """Profile icons are current assets and therefore use the current valid release."""
    player = await StaticDataResolver(
        FakeStaticDataClient(versions=("16.15.2", "16.16.1"))
    ).hydrate_player(_profile())

    assert player.profile_icon_id == 29
    assert player.profile_icon is not None
    assert player.profile_icon.image_url == (
        "https://ddragon.leagueoflegends.com/cdn/16.16.1/img/profileicon/29.png"
    )
    assert player.profile_static_data_status.model_dump() == {
        "available": True,
        "version": "16.16.1",
        "code": None,
    }


@pytest.mark.asyncio
async def test_player_hydration_preserves_numeric_icon_when_versions_are_unavailable() -> None:
    """Static-data failure must not erase a successfully normalized profile value."""
    player = await StaticDataResolver(TimingOutStaticDataClient()).hydrate_player(_profile())

    assert player.profile_icon_id == 29
    assert player.profile_icon is None
    assert player.profile_static_data_status.model_dump() == {
        "available": False,
        "version": None,
        "code": "STATIC_DATA_UNAVAILABLE",
    }


@pytest.mark.asyncio
async def test_match_hydration_degrades_without_erasing_numeric_snapshot_data() -> None:
    """A timeout leaves every normalized match statistic available for display."""
    snapshot = normalize_match(MatchDto.model_validate(MATCH_PAYLOAD), Platform.NA1)

    hydrated = await StaticDataResolver(TimingOutStaticDataClient()).hydrate_match(
        snapshot, Locale.ZH_CN
    )

    assert hydrated.snapshot is snapshot
    assert hydrated.participants[0].cs == 214
    assert hydrated.participants[0].gold_earned == 12001
    assert hydrated.participants[0].champion is None
    assert hydrated.participants[0].items == (None, None, None)
    assert hydrated.static_data_status.model_dump() == {
        "available": False,
        "version": None,
        "code": "STATIC_DATA_UNAVAILABLE",
    }


@pytest.mark.asyncio
async def test_match_hydration_localizes_assets_and_keeps_unknown_item_alignment() -> None:
    """Missing item catalog entries remain explicit None values in their original slots."""
    snapshot = normalize_match(MatchDto.model_validate(MATCH_PAYLOAD), Platform.NA1)
    first = snapshot.participants[0].model_copy(update={"item_ids": (1055, 999999)})
    snapshot = snapshot.model_copy(update={"participants": (first,) + snapshot.participants[1:]})

    hydrated = await StaticDataResolver(
        FakeStaticDataClient(versions=("16.15.2", "16.16.1"))
    ).hydrate_match(snapshot, Locale.ZH_CN)

    assert hydrated.snapshot is snapshot
    assert hydrated.participants[0].champion is not None
    assert hydrated.participants[0].champion.name == "阿狸"
    assert hydrated.participants[0].items[0] is not None
    assert hydrated.participants[0].items[0].name == "多兰之刃"
    assert hydrated.participants[0].items[1] is None
    assert hydrated.static_data_status.model_dump() == {
        "available": False,
        "version": "16.15.2",
        "code": "STATIC_DATA_UNAVAILABLE",
    }


@pytest.mark.asyncio
async def test_client_uses_unauthenticated_data_dragon_urls_and_caches_catalogs() -> None:
    """Catalog requests are localized, token-free, and reused per version and locale."""
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.url.path.endswith("champion.json"):
            return httpx2.Response(
                200,
                json={
                    "data": {
                        "Ahri": {
                            "key": "103",
                            "name": "Ahri",
                            "image": {"full": "Ahri.png"},
                        }
                    }
                },
            )
        return httpx2.Response(
            200,
            json={"data": {"1055": {"name": "Doran's Blade", "image": {"full": "1055.png"}}}},
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as raw_client:
        client = StaticDataClient(raw_client)
        first = await client.get_catalog("16.15.2", "zh_CN")
        second = await client.get_catalog("16.15.2", "zh_CN")

    assert first is second
    assert first.champion(103) is not None
    assert [str(request.url) for request in requests] == [
        "https://ddragon.leagueoflegends.com/cdn/16.15.2/data/zh_CN/champion.json",
        "https://ddragon.leagueoflegends.com/cdn/16.15.2/data/zh_CN/item.json",
    ]
    assert all("X-Riot-Token" not in request.headers for request in requests)
