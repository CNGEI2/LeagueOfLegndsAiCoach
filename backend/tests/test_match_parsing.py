import copy

import pytest

from app.core.errors import ApiError
from app.core.routing import Platform
from app.services.parsing.matches import normalize_match, supports_standard_detail
from app.services.riot.dto import MatchDto
from tests.fixtures.riot_payloads import MATCH_PAYLOAD


def test_match_normalization_combines_lane_and_jungle_cs_and_keeps_ten_players() -> None:
    """The normalized view must retain the complete 5v5 roster and exact numeric totals."""
    snapshot = normalize_match(MatchDto.model_validate(MATCH_PAYLOAD), Platform.NA1)

    assert snapshot.match_id == "NA1_123456789"
    assert len(snapshot.participants) == 10
    assert snapshot.participants[0].cs == 214
    assert snapshot.participants[0].item_ids == (1055, 6672, 3006)
    assert snapshot.game_version == "16.15.602.1234"
    assert supports_standard_detail(snapshot) is True


def test_match_normalization_rejects_metadata_for_another_platform_identity() -> None:
    """A metadata ID from another platform cannot satisfy this platform's requested match."""
    payload = copy.deepcopy(MATCH_PAYLOAD)
    metadata = payload["metadata"]
    assert isinstance(metadata, dict)
    metadata["matchId"] = "KR_123456789"

    with pytest.raises(ApiError) as caught:
        normalize_match(MatchDto.model_validate(payload), Platform.NA1)

    assert caught.value.code == "RIOT_INVALID_RESPONSE"


def test_nonstandard_match_is_normalized_but_not_eligible_for_standard_detail() -> None:
    """Recent-match discovery keeps valid special modes without exposing a broken 5v5 detail."""
    payload = copy.deepcopy(MATCH_PAYLOAD)
    info = payload["info"]
    metadata = payload["metadata"]
    assert isinstance(info, dict)
    assert isinstance(metadata, dict)
    players = info["participants"]
    assert isinstance(players, list)
    info["participants"] = players[:3]
    metadata["participants"] = ["puuid-1", "puuid-2", "puuid-3"]

    snapshot = normalize_match(MatchDto.model_validate(payload), Platform.NA1)

    assert len(snapshot.participants) == 3
    assert supports_standard_detail(snapshot) is False


def test_optional_stat_gaps_and_unknown_role_remain_typed_unavailable() -> None:
    """Incomplete non-critical game stats do not invalidate the entire match snapshot."""
    payload = copy.deepcopy(MATCH_PAYLOAD)
    info = payload["info"]
    assert isinstance(info, dict)
    players = info["participants"]
    assert isinstance(players, list)
    first = players[0]
    assert isinstance(first, dict)
    first.pop("neutralMinionsKilled")
    first["teamPosition"] = "INVALID_ROLE"

    snapshot = normalize_match(MatchDto.model_validate(payload), Platform.NA1)

    assert snapshot.participants[0].cs is None
    assert snapshot.participants[0].role is None


def test_duplicate_participant_identity_is_rejected() -> None:
    """A duplicate PUUID would attach two incompatible stat lines to one player."""
    payload = copy.deepcopy(MATCH_PAYLOAD)
    info = payload["info"]
    assert isinstance(info, dict)
    players = info["participants"]
    assert isinstance(players, list)
    duplicate = players[1]
    assert isinstance(duplicate, dict)
    duplicate["puuid"] = "puuid-1"

    with pytest.raises(ApiError) as caught:
        normalize_match(MatchDto.model_validate(payload), Platform.NA1)

    assert caught.value.code == "RIOT_INVALID_RESPONSE"
