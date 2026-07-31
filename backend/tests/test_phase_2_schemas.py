import pytest

from app.core.routing import Platform
from app.schemas.domain import Locale, PlayerProfile


def test_player_profile_keeps_tag_line_separate_from_platform() -> None:
    profile = PlayerProfile(
        puuid="puuid-1",
        game_name="PlayerName",
        tag_line="1115",
        platform=Platform.NA1,
        summoner_level=772,
        profile_icon_id=29,
    )

    assert profile.tag_line == "1115"
    assert profile.platform is Platform.NA1


def test_locale_is_closed() -> None:
    with pytest.raises(ValueError):
        Locale("fr-FR")
