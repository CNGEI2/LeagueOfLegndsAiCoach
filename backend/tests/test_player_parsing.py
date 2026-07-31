import pytest

from app.core.errors import ApiError
from app.core.routing import Platform
from app.services.parsing.players import normalize_player
from app.services.riot.dto import AccountDto, SummonerDto


def test_player_normalization_preserves_canonical_riot_id() -> None:
    """Account identity, rather than user input, is the canonical public Riot ID."""
    profile = normalize_player(
        AccountDto(puuid="p", gameName="Canonical Name", tagLine="1115"),
        SummonerDto(
            id="summoner",
            accountId="account",
            puuid="p",
            profileIconId=29,
            summonerLevel=772,
            revisionDate=1720000000000,
        ),
        Platform.NA1,
    )

    assert profile.game_name == "Canonical Name"
    assert profile.tag_line == "1115"
    assert profile.profile_icon_id == 29


def test_player_normalization_rejects_mismatched_identity_records() -> None:
    """Cross-account Summoner data must never be attached to the Account identity."""
    with pytest.raises(ApiError) as caught:
        normalize_player(
            AccountDto(puuid="account-puuid", gameName="Player", tagLine="1115"),
            SummonerDto(
                id="summoner",
                accountId="account",
                puuid="other-puuid",
                profileIconId=29,
                summonerLevel=772,
                revisionDate=1720000000000,
            ),
            Platform.NA1,
        )

    assert caught.value.code == "RIOT_INVALID_RESPONSE"
