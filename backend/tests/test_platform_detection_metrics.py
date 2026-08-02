from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.errors import ApiError
from app.core.metrics import MetricsRegistry
from app.core.routing import Platform, Region, detection_probe_platforms
from app.repositories.platform_detections import DetectionStatus, PlatformDetectionRecord
from app.schemas.domain import Locale, PlayerView, StaticDataStatus
from app.services.platform_detection import PlatformDetectionService
from app.services.riot.dto import AccountDto, SummonerDto

NOW = datetime(2026, 8, 2, tzinfo=UTC)


class FakeRepository:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], PlatformDetectionRecord] = {}

    async def get_fresh(self, *, game_name_key: str, tag_line_key: str, now: datetime):
        record = self.records.get((game_name_key, tag_line_key))
        return record if record is not None and record.expires_at > now else None

    async def get_for_confirmation(self, *, detection_id, now: datetime):
        for record in self.records.values():
            if (
                record.id == detection_id
                and record.expires_at > now
                and record.confirmation_expires_at is not None
                and record.confirmation_expires_at > now
            ):
                return record
        return None

    async def upsert(self, record: PlatformDetectionRecord) -> PlatformDetectionRecord:
        self.records[(record.game_name_key, record.tag_line_key)] = record
        return record

    async def delete(self, *, detection_id) -> None:
        for key, record in tuple(self.records.items()):
            if record.id == detection_id:
                del self.records[key]


class FakeGateway:
    async def get_account_by_riot_id_in_region(
        self, *, region: Region, game_name: str, tag_line: str
    ):
        return AccountDto(puuid="detected-puuid", gameName="Canonical", tagLine="TAG")

    async def get_summoner_by_puuid(self, *, platform: Platform, puuid: str):
        if platform is Platform.NA1:
            return SummonerDto(puuid=puuid, profileIconId=1, summonerLevel=1, revisionDate=1)
        raise ApiError(status_code=404, code="PLAYER_NOT_FOUND", message="missing", retryable=False)


class FakePlayers:
    async def get_by_puuid(self, *, platform: Platform, puuid: str) -> PlayerView:
        return PlayerView(
            puuid=puuid,
            game_name="Canonical",
            tag_line="TAG",
            platform=platform,
            summoner_level=1,
            profile_icon_id=1,
            profile_icon=None,
            profile_static_data_status=StaticDataStatus(available=False, version=None, code=None),
        )


def test_registry_exposes_platform_detection_metrics_with_closed_labels() -> None:
    registry = MetricsRegistry()
    registry.riot_platform_detection_requests_total.inc(outcome="resolved")
    registry.riot_platform_detection_duration_seconds.observe(0.2, outcome="resolved")
    registry.riot_platform_detection_cache_total.inc(status="hit")
    registry.riot_platform_detection_probes_total.inc(result="found")
    registry.riot_platform_confirmation_total.inc(outcome="success")

    rendered = registry.render_prometheus_text()
    assert "riot_platform_detection_requests_total" in rendered
    assert 'riot_platform_detection_requests_total{outcome="resolved"} 1.0' in rendered
    assert "riot_platform_detection_duration_seconds" in rendered
    assert 'riot_platform_detection_cache_total{status="hit"} 1.0' in rendered
    assert 'riot_platform_detection_probes_total{result="found"} 1.0' in rendered
    assert 'riot_platform_confirmation_total{outcome="success"} 1.0' in rendered
    assert "puuid" not in rendered.lower()
    assert "riot_id" not in rendered.lower()


@pytest.mark.asyncio
async def test_detection_service_records_cache_hit_and_resolved_outcome() -> None:
    registry = MetricsRegistry()
    repository = FakeRepository()
    record = PlatformDetectionRecord(
        id=uuid4(),
        game_name_key="canonical",
        tag_line_key="tag",
        canonical_game_name="Canonical",
        canonical_tag_line="TAG",
        puuid="detected-puuid",
        status=DetectionStatus.RESOLVED,
        candidate_platforms=(Platform.NA1,),
        fetched_at=NOW,
        expires_at=NOW + timedelta(hours=24),
        confirmation_expires_at=None,
    )
    await repository.upsert(record)
    service = PlatformDetectionService(
        repository=repository,
        gateway=FakeGateway(),
        player_service=FakePlayers(),
        detection_ttl_seconds=86400,
        not_found_ttl_seconds=300,
        confirmation_ttl_seconds=900,
        primary_region=Region.AMERICAS,
        max_concurrency=4,
        clock=lambda: NOW,
        metrics=registry,
    )

    await service.detect(riot_id="Canonical#TAG", locale=Locale.EN_US)

    assert registry.riot_platform_detection_cache_total.value(status="hit") == 1
    assert registry.riot_platform_detection_requests_total.value(outcome="resolved") == 1
    assert registry.riot_platform_detection_duration_seconds.count(outcome="resolved") == 1


@pytest.mark.asyncio
async def test_detection_service_records_probe_results_on_miss() -> None:
    registry = MetricsRegistry()
    service = PlatformDetectionService(
        repository=FakeRepository(),
        gateway=FakeGateway(),
        player_service=FakePlayers(),
        detection_ttl_seconds=86400,
        not_found_ttl_seconds=300,
        confirmation_ttl_seconds=900,
        primary_region=Region.AMERICAS,
        max_concurrency=4,
        clock=lambda: NOW,
        metrics=registry,
    )

    await service.detect(riot_id="Canonical#TAG", locale=Locale.EN_US)

    assert registry.riot_platform_detection_cache_total.value(status="miss") == 1
    assert registry.riot_platform_detection_probes_total.value(result="found") == 1
    assert registry.riot_platform_detection_probes_total.value(result="not_found") == (
        len(detection_probe_platforms()) - 1
    )
    assert registry.riot_platform_detection_requests_total.value(outcome="resolved") == 1
