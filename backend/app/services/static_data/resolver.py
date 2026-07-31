from dataclasses import dataclass
from typing import Protocol

from app.schemas.domain import (
    Locale,
    MatchSnapshot,
    ParticipantSnapshot,
    PlayerProfile,
    PlayerView,
    StaticAsset,
    StaticDataStatus,
)
from app.schemas.matches import HydratedParticipant
from app.services.static_data.client import CatalogAsset, StaticCatalog, StaticDataUnavailable

_STATIC_DATA_UNAVAILABLE = "STATIC_DATA_UNAVAILABLE"


class StaticDataSource(Protocol):
    async def get_versions(self) -> tuple[str, ...]: ...

    async def get_catalog(self, version: str, locale: str) -> StaticCatalog: ...


@dataclass(frozen=True)
class HydratedMatch:
    snapshot: MatchSnapshot
    participants: tuple[HydratedParticipant, ...]
    static_data_status: StaticDataStatus


class StaticDataResolver:
    def __init__(self, client: StaticDataSource) -> None:
        self._client = client

    async def hydrate_player(self, profile: PlayerProfile) -> PlayerView:
        try:
            version = _newest_version(await self._client.get_versions())
            if version is None:
                return _unhydrated_player(profile)
        except (StaticDataUnavailable, TimeoutError):
            return _unhydrated_player(profile)
        return PlayerView(
            **profile.model_dump(),
            profile_icon=StaticAsset(
                entity_id=profile.profile_icon_id,
                name=f"Profile icon {profile.profile_icon_id}",
                image_url=(
                    f"https://ddragon.leagueoflegends.com/cdn/{version}/img/profileicon/"
                    f"{profile.profile_icon_id}.png"
                ),
            ),
            profile_static_data_status=StaticDataStatus(available=True, version=version, code=None),
        )

    async def hydrate_match(self, snapshot: MatchSnapshot, locale: Locale) -> HydratedMatch:
        try:
            version = compatible_version(snapshot.game_version, await self._client.get_versions())
            if version is None:
                return _unhydrated_match(snapshot)
            catalog = await self._client.get_catalog(version, locale_code(locale))
        except (StaticDataUnavailable, TimeoutError):
            return _unhydrated_match(snapshot)

        participants = tuple(
            _hydrate_participant(participant, catalog, version)
            for participant in snapshot.participants
        )
        complete = all(
            participant.champion is not None and all(item is not None for item in participant.items)
            for participant in participants
        )
        return HydratedMatch(
            snapshot=snapshot,
            participants=participants,
            static_data_status=StaticDataStatus(
                available=complete,
                version=version,
                code=None if complete else _STATIC_DATA_UNAVAILABLE,
            ),
        )


def compatible_version(game_version: str, versions: tuple[str, ...]) -> str | None:
    """Return the newest Data Dragon build with the match's numeric major/minor pair."""
    match_parts = _numeric_version_parts(game_version)
    if match_parts is None:
        return None
    candidates = [
        (version_parts, version)
        for version in versions
        if (version_parts := _numeric_version_parts(version)) is not None
        and version_parts[:2] == match_parts[:2]
    ]
    return max(candidates, default=((), None))[1]


def locale_code(locale: Locale) -> str:
    return {Locale.ZH_CN: "zh_CN", Locale.EN_US: "en_US"}[locale]


def champion_image_url(version: str, image_name: str) -> str:
    return f"https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/{image_name}"


def item_image_url(version: str, image_name: str) -> str:
    return f"https://ddragon.leagueoflegends.com/cdn/{version}/img/item/{image_name}"


def _numeric_version_parts(value: str) -> tuple[int, ...] | None:
    parts = value.split(".")
    if len(parts) < 2 or any(not part.isdecimal() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _newest_version(versions: tuple[str, ...]) -> str | None:
    candidates = [
        (version_parts, version)
        for version in versions
        if (version_parts := _numeric_version_parts(version)) is not None
    ]
    return max(candidates, default=((), None))[1]


def _hydrate_participant(
    participant: ParticipantSnapshot,
    catalog: StaticCatalog,
    version: str,
) -> HydratedParticipant:
    champion = _champion_asset(catalog.champion(participant.champion_id), version)
    items = tuple(_item_asset(catalog.item(item_id), version) for item_id in participant.item_ids)
    return HydratedParticipant(
        **participant.model_dump(),
        champion=champion,
        items=items,
    )


def _champion_asset(asset: CatalogAsset | None, version: str) -> StaticAsset | None:
    if asset is None:
        return None
    return StaticAsset(
        entity_id=asset.entity_id,
        name=asset.name,
        image_url=champion_image_url(version, asset.image_name),
    )


def _item_asset(asset: CatalogAsset | None, version: str) -> StaticAsset | None:
    if asset is None:
        return None
    return StaticAsset(
        entity_id=asset.entity_id,
        name=asset.name,
        image_url=item_image_url(version, asset.image_name),
    )


def _unhydrated_player(profile: PlayerProfile) -> PlayerView:
    return PlayerView(
        **profile.model_dump(),
        profile_icon=None,
        profile_static_data_status=_unavailable_status(),
    )


def _unhydrated_match(snapshot: MatchSnapshot) -> HydratedMatch:
    return HydratedMatch(
        snapshot=snapshot,
        participants=tuple(
            HydratedParticipant(
                **participant.model_dump(),
                champion=None,
                items=(None,) * len(participant.item_ids),
            )
            for participant in snapshot.participants
        ),
        static_data_status=_unavailable_status(),
    )


def _unavailable_status() -> StaticDataStatus:
    return StaticDataStatus(available=False, version=None, code=_STATIC_DATA_UNAVAILABLE)
