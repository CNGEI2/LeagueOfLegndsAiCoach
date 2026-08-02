import pytest

from app.core.errors import ApiError
from app.core.routing import Platform
from app.services.parsing.players import normalize_player, parse_riot_id
from app.services.riot.dto import AccountDto, SummonerDto


@pytest.mark.parametrize(
    ("value", "game_name", "tag_line", "game_name_key", "tag_line_key"),
    [
        ("  Player Name#NA1  ", "Player Name", "NA1", "player name", "na1"),
        ("ＦＯＯ#ＴＡＧ", "ＦＯＯ", "ＴＡＧ", "foo", "tag"),
        ("Name#with#tag", "Name#with", "tag", "name#with", "tag"),
        ("名#标", "名", "标", "名", "标"),
        (f"{'a' * 32}#{'b' * 16}", "a" * 32, "b" * 16, "a" * 32, "b" * 16),
    ],
)
def test_parse_riot_id_normalizes_a_single_riot_id_field(
    value: str, game_name: str, tag_line: str, game_name_key: str, tag_line_key: str
) -> None:
    """Parser regressions must not send malformed or non-canonical IDs upstream."""
    parsed = parse_riot_id(value)

    assert parsed.game_name == game_name
    assert parsed.tag_line == tag_line
    assert parsed.game_name_key == game_name_key
    assert parsed.tag_line_key == tag_line_key


@pytest.mark.parametrize(
    "value",
    ["", "NoSeparator", "#tag", "name#", f"{'a' * 33}#tag", f"name#{'a' * 17}"],
)
def test_parse_riot_id_rejects_missing_or_overlong_parts(value: str) -> None:
    """Missing separator/sides and out-of-bounds parts cannot enter detection."""
    with pytest.raises(ApiError) as caught:
        parse_riot_id(value)

    assert caught.value.status_code == 422
    assert caught.value.code == "INVALID_RIOT_ID"


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
