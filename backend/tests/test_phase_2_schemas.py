from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.core.routing import Platform
from app.schemas.domain import (
    Locale,
    PlayerProfile,
    PlayerView,
    StaticAsset,
    StaticDataStatus,
)
from app.schemas.matches import (
    HydratedParticipant,
    MatchDetailResponse,
    RecentMatchesResponse,
    RecentMatchItem,
)
from app.schemas.platform_detection import (
    ConfirmationRequiredResponse,
    ConfirmPlatformRequest,
    DetectPlayerRequest,
    PlatformCandidate,
    ResolvedDetectionResponse,
)
from app.schemas.players import ResolvePlayerResponse

STARTED_AT = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
PLAYER_DUMP = {
    "puuid": "puuid-1",
    "game_name": "PlayerName",
    "tag_line": "1115",
    "platform": "NA1",
    "summoner_level": 772,
    "profile_icon_id": 29,
    "profile_icon": {
        "entity_id": 29,
        "name": "ProfileIcon29",
        "image_url": "https://cdn.example/icons/29.png",
    },
    "profile_static_data_status": {
        "available": True,
        "version": "15.14.1",
        "code": None,
    },
}
PARTICIPANT_DUMP = {
    "puuid": "puuid-1",
    "team_id": 100,
    "champion_id": 103,
    "role": "MIDDLE",
    "won": True,
    "kills": 8,
    "deaths": 2,
    "assists": 6,
    "cs": 201,
    "gold_earned": 14321,
    "damage_to_champions": 24567,
    "vision_score": 18,
    "item_ids": [1055, 0],
    "champion": {
        "entity_id": 103,
        "name": "Ahri",
        "image_url": "https://cdn.example/champions/103.png",
    },
    "items": [
        {
            "entity_id": 1055,
            "name": "Doran's Blade",
            "image_url": "https://cdn.example/items/1055.png",
        },
        None,
    ],
}
STATIC_DATA_DUMP = {"available": True, "version": "15.14.1", "code": None}


def _static_data_status() -> StaticDataStatus:
    return StaticDataStatus(available=True, version="15.14.1", code=None)


def _player_view() -> PlayerView:
    return PlayerView(
        puuid="puuid-1",
        game_name="PlayerName",
        tag_line="1115",
        platform=Platform.NA1,
        summoner_level=772,
        profile_icon_id=29,
        profile_icon=StaticAsset(
            entity_id=29,
            name="ProfileIcon29",
            image_url="https://cdn.example/icons/29.png",
        ),
        profile_static_data_status=_static_data_status(),
    )


def _hydrated_participant() -> HydratedParticipant:
    return HydratedParticipant(
        puuid="puuid-1",
        team_id=100,
        champion_id=103,
        role="MIDDLE",
        won=True,
        kills=8,
        deaths=2,
        assists=6,
        cs=201,
        gold_earned=14321,
        damage_to_champions=24567,
        vision_score=18,
        item_ids=(1055, 0),
        champion=StaticAsset(
            entity_id=103,
            name="Ahri",
            image_url="https://cdn.example/champions/103.png",
        ),
        items=(
            StaticAsset(
                entity_id=1055,
                name="Doran's Blade",
                image_url="https://cdn.example/items/1055.png",
            ),
            None,
        ),
    )


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


def test_player_view_serializes_the_normalized_public_profile() -> None:
    assert _player_view().model_dump(mode="json") == PLAYER_DUMP


def test_domain_models_reject_extra_fields_and_mutation() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PlayerProfile(
            puuid="puuid-1",
            game_name="PlayerName",
            tag_line="1115",
            platform=Platform.NA1,
            summoner_level=772,
            profile_icon_id=29,
            extra_field="not public",
        )

    player = _player_view()
    with pytest.raises(ValidationError, match="Instance is frozen"):
        player.summoner_level = 773


def test_resolve_player_response_serializes_exact_public_fields() -> None:
    response = ResolvePlayerResponse(player=_player_view(), request_id="request-123")

    assert response.model_dump(mode="json") == {
        "player": PLAYER_DUMP,
        "request_id": "request-123",
    }


def test_hydrated_participant_preserves_unknown_items_for_alignment() -> None:
    assert _hydrated_participant().model_dump(mode="json") == PARTICIPANT_DUMP


def test_hydrated_participant_rejects_mismatched_item_asset_lengths() -> None:
    with pytest.raises(ValidationError, match="items must align with item_ids"):
        HydratedParticipant(
            puuid="puuid-1",
            team_id=100,
            champion_id=103,
            role="MIDDLE",
            won=True,
            kills=8,
            deaths=2,
            assists=6,
            cs=201,
            gold_earned=14321,
            damage_to_champions=24567,
            vision_score=18,
            item_ids=(1055, 0),
            champion=None,
            items=(None,),
        )


def test_recent_matches_response_serializes_exact_public_fields() -> None:
    response = RecentMatchesResponse(
        player=_player_view(),
        matches=(
            RecentMatchItem(
                match_id="NA1_123",
                platform=Platform.NA1,
                queue_id=420,
                started_at=STARTED_AT,
                duration_seconds=1800,
                game_version="15.14.1",
                participant=_hydrated_participant(),
                analysis_supported=True,
                unsupported_reason_code=None,
                detail_supported=True,
                detail_unavailable_reason_code=None,
                static_data_status=_static_data_status(),
            ),
        ),
        request_id="request-123",
    )

    assert response.model_dump(mode="json") == {
        "player": PLAYER_DUMP,
        "matches": [
            {
                "match_id": "NA1_123",
                "platform": "NA1",
                "queue_id": 420,
                "started_at": "2026-07-30T12:00:00Z",
                "duration_seconds": 1800,
                "game_version": "15.14.1",
                "participant": PARTICIPANT_DUMP,
                "analysis_supported": True,
                "unsupported_reason_code": None,
                "detail_supported": True,
                "detail_unavailable_reason_code": None,
                "static_data_status": STATIC_DATA_DUMP,
            }
        ],
        "request_id": "request-123",
    }


def test_match_detail_response_serializes_exact_public_fields() -> None:
    response = MatchDetailResponse(
        match_id="NA1_123",
        platform=Platform.NA1,
        queue_id=420,
        started_at=STARTED_AT,
        duration_seconds=1800,
        game_version="15.14.1",
        selected_puuid="puuid-1",
        blue_team=(_hydrated_participant(),) * 5,
        red_team=(_hydrated_participant(),) * 5,
        static_data_status=_static_data_status(),
        request_id="request-123",
    )

    assert response.model_dump(mode="json") == {
        "match_id": "NA1_123",
        "platform": "NA1",
        "queue_id": 420,
        "started_at": "2026-07-30T12:00:00Z",
        "duration_seconds": 1800,
        "game_version": "15.14.1",
        "selected_puuid": "puuid-1",
        "blue_team": [PARTICIPANT_DUMP] * 5,
        "red_team": [PARTICIPANT_DUMP] * 5,
        "static_data_status": STATIC_DATA_DUMP,
        "scope_notice_code": "DATA_ONLY_NO_COACHING",
        "request_id": "request-123",
    }


def test_detect_player_request_rejects_extra_fields_and_invalid_locale() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DetectPlayerRequest(riot_id="Player#TAG", locale=Locale.EN_US, extra="nope")
    with pytest.raises(ValidationError):
        DetectPlayerRequest.model_validate({"riot_id": "Player#TAG", "locale": "fr-FR"})


def test_confirm_platform_request_rejects_unknown_platform() -> None:
    with pytest.raises(ValidationError):
        ConfirmPlatformRequest.model_validate({"platform": "XYZ1", "locale": "en-US"})


def test_resolved_detection_response_serializes_exact_public_fields() -> None:
    response = ResolvedDetectionResponse(
        status="resolved",
        player=_player_view(),
        request_id="request-123",
    )
    assert response.model_dump(mode="json") == {
        "status": "resolved",
        "player": PLAYER_DUMP,
        "request_id": "request-123",
    }


def test_confirmation_required_response_rejects_naive_expiry_and_empty_candidates() -> None:
    detection_id = UUID("12345678-1234-5678-1234-567812345678")
    with pytest.raises(ValidationError):
        ConfirmationRequiredResponse(
            status="confirmation_required",
            detection_id=detection_id,
            expires_at=datetime(2026, 8, 2, 12, 15),
            candidates=(PlatformCandidate(platform=Platform.NA1, display_name="North America"),),
            request_id="request-123",
        )
    with pytest.raises(ValidationError):
        ConfirmationRequiredResponse(
            status="confirmation_required",
            detection_id=detection_id,
            expires_at=datetime(2026, 8, 2, 12, 15, tzinfo=UTC),
            candidates=(),
            request_id="request-123",
        )


def test_confirmation_required_response_serializes_exact_public_fields() -> None:
    detection_id = UUID("12345678-1234-5678-1234-567812345678")
    response = ConfirmationRequiredResponse(
        status="confirmation_required",
        detection_id=detection_id,
        expires_at=datetime(2026, 8, 2, 12, 15, tzinfo=UTC),
        candidates=(
            PlatformCandidate(platform=Platform.EUW1, display_name="Europe West"),
            PlatformCandidate(platform=Platform.NA1, display_name="North America"),
        ),
        request_id="request-123",
    )
    assert response.model_dump(mode="json") == {
        "status": "confirmation_required",
        "detection_id": "12345678-1234-5678-1234-567812345678",
        "expires_at": "2026-08-02T12:15:00Z",
        "candidates": [
            {"platform": "EUW1", "display_name": "Europe West"},
            {"platform": "NA1", "display_name": "North America"},
        ],
        "request_id": "request-123",
    }


def test_detection_status_variants_reject_wrong_fields() -> None:
    with pytest.raises(ValidationError):
        ResolvedDetectionResponse.model_validate(
            {
                "status": "resolved",
                "detection_id": "12345678-1234-5678-1234-567812345678",
                "request_id": "request-123",
            }
        )
    with pytest.raises(ValidationError):
        ConfirmationRequiredResponse.model_validate(
            {
                "status": "confirmation_required",
                "player": PLAYER_DUMP,
                "request_id": "request-123",
            }
        )
