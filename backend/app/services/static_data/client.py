from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import httpx2

_BASE_URL = "https://ddragon.leagueoflegends.com"


class StaticDataUnavailable(Exception):
    """Raised when Data Dragon cannot provide a valid static catalog."""


@dataclass(frozen=True)
class CatalogAsset:
    entity_id: int
    name: str
    image_name: str


@dataclass(frozen=True)
class StaticCatalog:
    _champions: Mapping[int, CatalogAsset]
    _items: Mapping[int, CatalogAsset]

    @classmethod
    def from_payloads(cls, champions_payload: object, items_payload: object) -> "StaticCatalog":
        champions_data = _catalog_data(champions_payload)
        items_data = _catalog_data(items_payload)
        champions: dict[int, CatalogAsset] = {}
        items: dict[int, CatalogAsset] = {}
        for entry in champions_data.values():
            asset = _champion_asset(entry)
            if asset is not None:
                champions[asset.entity_id] = asset
        for item_id, entry in items_data.items():
            asset = _item_asset(item_id, entry)
            if asset is not None:
                items[asset.entity_id] = asset
        return cls(MappingProxyType(champions), MappingProxyType(items))

    def champion(self, champion_id: int) -> CatalogAsset | None:
        return self._champions.get(champion_id)

    def item(self, item_id: int) -> CatalogAsset | None:
        return self._items.get(item_id)


class StaticDataClient:
    """Small, unauthenticated Data Dragon boundary with catalog-only process caching."""

    def __init__(self, client: httpx2.AsyncClient) -> None:
        self._client = client
        self._catalogs: dict[tuple[str, str], StaticCatalog] = {}

    async def get_versions(self) -> tuple[str, ...]:
        payload = await self._get_json(f"{_BASE_URL}/api/versions.json")
        if not isinstance(payload, list) or not all(isinstance(value, str) for value in payload):
            raise StaticDataUnavailable
        return tuple(payload)

    async def get_catalog(self, version: str, locale: str) -> StaticCatalog:
        key = (version, locale)
        cached = self._catalogs.get(key)
        if cached is not None:
            return cached
        base_url = f"{_BASE_URL}/cdn/{version}/data/{locale}"
        champions_payload = await self._get_json(f"{base_url}/champion.json")
        items_payload = await self._get_json(f"{base_url}/item.json")
        try:
            catalog = StaticCatalog.from_payloads(champions_payload, items_payload)
        except ValueError:
            raise StaticDataUnavailable from None
        self._catalogs[key] = catalog
        return catalog

    async def _get_json(self, url: str) -> object:
        try:
            response = await self._client.get(url)
            response.raise_for_status()
            return response.json()
        except (httpx2.HTTPError, ValueError):
            raise StaticDataUnavailable from None


def _catalog_data(payload: object) -> Mapping[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("catalog payload must be an object")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("catalog data must be an object")
    return data


def _champion_asset(entry: object) -> CatalogAsset | None:
    if not isinstance(entry, dict):
        return None
    key = entry.get("key")
    if not isinstance(key, str) or not key.isdecimal():
        return None
    return _catalog_asset(int(key), entry)


def _item_asset(item_id: str, entry: object) -> CatalogAsset | None:
    if not item_id.isdecimal() or not isinstance(entry, dict):
        return None
    return _catalog_asset(int(item_id), entry)


def _catalog_asset(entity_id: int, entry: Mapping[str, Any]) -> CatalogAsset | None:
    name = entry.get("name")
    image = entry.get("image")
    if not isinstance(name, str) or not isinstance(image, dict):
        return None
    image_name = image.get("full")
    if not isinstance(image_name, str):
        return None
    return CatalogAsset(entity_id=entity_id, name=name, image_name=image_name)
