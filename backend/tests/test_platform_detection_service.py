import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.errors import ApiError
from app.core.routing import Platform, Region, detection_probe_platforms
from app.repositories.platform_detections import DetectionStatus, PlatformDetectionRecord
from app.schemas.domain import Locale, PlayerView, StaticDataStatus
from app.services.platform_detection import (
    ConfirmationRequiredDetection,
    PlatformDetectionService,
    ResolvedDetection,
)
from app.services.riot.dto import AccountDto, SummonerDto

NOW = datetime(2026, 8, 2, tzinfo=UTC)


def error(code: str, *, status_code: int = 503, retryable: bool = False) -> ApiError:
    return ApiError(status_code=status_code, code=code, message=code, retryable=retryable)


class FakeRepository:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], PlatformDetectionRecord] = {}
        self.upserts: list[PlatformDetectionRecord] = []
        self.deleted: list[object] = []

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
        prior = self.records.get((record.game_name_key, record.tag_line_key))
        stored = PlatformDetectionRecord(
            id=prior.id if prior else record.id,
            game_name_key=record.game_name_key,
            tag_line_key=record.tag_line_key,
            canonical_game_name=record.canonical_game_name,
            canonical_tag_line=record.canonical_tag_line,
            puuid=record.puuid,
            status=record.status,
            candidate_platforms=record.candidate_platforms,
            fetched_at=record.fetched_at,
            expires_at=record.expires_at,
            confirmation_expires_at=record.confirmation_expires_at,
        )
        self.records[(stored.game_name_key, stored.tag_line_key)] = stored
        self.upserts.append(stored)
        return stored

    async def delete(self, *, detection_id) -> None:
        self.deleted.append(detection_id)
        for key, record in tuple(self.records.items()):
            if record.id == detection_id:
                del self.records[key]


class FakeGateway:
    def __init__(self) -> None:
        self.account = AccountDto(puuid="detected-puuid", gameName="Canonical", tagLine="TAG")
        self.account_calls: list[Region] = []
        self.probe_calls: list[Platform] = []
        self.account_failures: dict[Region, ApiError] = {}
        self.found: set[Platform] = {Platform.NA1}
        self.probe_failures: dict[Platform, ApiError] = {}
        self.probe_puuid_overrides: dict[Platform, str] = {}
        self.current_probes = 0
        self.max_probes = 0
        self.wait_for_probe: asyncio.Event | None = None
        self.wait_for_account: asyncio.Event | None = None

    async def get_account_by_riot_id_in_region(
        self, *, region: Region, game_name: str, tag_line: str
    ):
        self.account_calls.append(region)
        if self.wait_for_account is not None:
            await self.wait_for_account.wait()
        if failure := self.account_failures.get(region):
            raise failure
        return self.account

    async def get_summoner_by_puuid(self, *, platform: Platform, puuid: str):
        self.probe_calls.append(platform)
        self.current_probes += 1
        self.max_probes = max(self.max_probes, self.current_probes)
        try:
            if self.wait_for_probe is not None:
                await self.wait_for_probe.wait()
            if failure := self.probe_failures.get(platform):
                raise failure
            if platform not in self.found:
                raise error("PLAYER_NOT_FOUND", status_code=404)
            return SummonerDto(
                puuid=self.probe_puuid_overrides.get(platform, puuid),
                profileIconId=1,
                summonerLevel=1,
                revisionDate=1,
            )
        finally:
            self.current_probes -= 1


class FakePlayers:
    def __init__(self) -> None:
        self.calls: list[tuple[Platform, str]] = []

    async def get_by_puuid(self, *, platform: Platform, puuid: str) -> PlayerView:
        self.calls.append((platform, puuid))
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


def record(**overrides: object) -> PlatformDetectionRecord:
    values: dict[str, object] = {
        "id": uuid4(),
        "game_name_key": "canonical",
        "tag_line_key": "tag",
        "canonical_game_name": "Canonical",
        "canonical_tag_line": "TAG",
        "puuid": "detected-puuid",
        "status": DetectionStatus.RESOLVED,
        "candidate_platforms": (Platform.NA1,),
        "fetched_at": NOW,
        "expires_at": NOW + timedelta(hours=24),
        "confirmation_expires_at": None,
    }
    values.update(overrides)
    return PlatformDetectionRecord(**values)  # type: ignore[arg-type]


def service(
    repository: FakeRepository, gateway: FakeGateway, players: FakePlayers, **overrides: object
):
    values: dict[str, object] = {
        "repository": repository,
        "gateway": gateway,
        "player_service": players,
        "detection_ttl_seconds": 86400,
        "not_found_ttl_seconds": 300,
        "confirmation_ttl_seconds": 900,
        "primary_region": Region.AMERICAS,
        "max_concurrency": 2,
        "clock": lambda: NOW,
    }
    values.update(overrides)
    return PlatformDetectionService(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_detection_uses_fresh_resolved_cache_without_riot_call() -> None:
    repository, gateway, players = FakeRepository(), FakeGateway(), FakePlayers()
    await repository.upsert(record())

    result = await service(repository, gateway, players).detect(
        riot_id="Canonical#TAG", locale=Locale.EN_US
    )

    assert isinstance(result, ResolvedDetection)
    assert gateway.account_calls == []
    assert gateway.probe_calls == []
    assert players.calls == [(Platform.NA1, "detected-puuid")]


@pytest.mark.asyncio
async def test_detection_returns_localized_ordered_ambiguous_cache_and_refreshes_confirmation() -> (
    None
):
    repository, gateway, players = FakeRepository(), FakeGateway(), FakePlayers()
    cached = record(
        status=DetectionStatus.AMBIGUOUS,
        candidate_platforms=(Platform.VN2, Platform.NA1),
        confirmation_expires_at=NOW,
    )
    await repository.upsert(cached)

    result = await service(repository, gateway, players).detect(
        riot_id="Canonical#TAG", locale=Locale.ZH_CN
    )

    assert isinstance(result, ConfirmationRequiredDetection)
    assert [candidate.platform for candidate in result.candidates] == [Platform.NA1, Platform.VN2]
    assert [candidate.display_name for candidate in result.candidates] == ["北美服", "越南服"]
    assert repository.upserts[-1].expires_at == cached.expires_at
    assert repository.upserts[-1].confirmation_expires_at == NOW + timedelta(minutes=15)
    assert gateway.account_calls == []


@pytest.mark.asyncio
async def test_detection_raises_cached_not_found_without_riot_call() -> None:
    repository, gateway, players = FakeRepository(), FakeGateway(), FakePlayers()
    await repository.upsert(
        record(
            game_name_key="missing",
            tag_line_key="tag",
            canonical_game_name=None,
            canonical_tag_line=None,
            puuid=None,
            status=DetectionStatus.NOT_FOUND,
            candidate_platforms=(),
            expires_at=NOW + timedelta(minutes=5),
        )
    )

    with pytest.raises(ApiError) as caught:
        await service(repository, gateway, players).detect(
            riot_id="Missing#TAG", locale=Locale.EN_US
        )

    assert caught.value.code == "PLAYER_NOT_FOUND"
    assert gateway.account_calls == []
    assert gateway.probe_calls == []


@pytest.mark.asyncio
async def test_expired_cache_performs_fresh_detection() -> None:
    repository, gateway, players = FakeRepository(), FakeGateway(), FakePlayers()
    await repository.upsert(record(expires_at=NOW))

    result = await service(repository, gateway, players).detect(
        riot_id="Canonical#TAG", locale=Locale.EN_US
    )

    assert isinstance(result, ResolvedDetection)
    assert gateway.account_calls == [Region.AMERICAS]
    assert len(gateway.probe_calls) == len(detection_probe_platforms())


@pytest.mark.asyncio
async def test_primary_account_region_success_stops_regional_sequence() -> None:
    repository, gateway, players = FakeRepository(), FakeGateway(), FakePlayers()

    await service(repository, gateway, players).detect(riot_id="Player#TAG", locale=Locale.EN_US)

    assert gateway.account_calls == [Region.AMERICAS]


@pytest.mark.asyncio
async def test_primary_account_404_falls_through_fixed_region_order() -> None:
    repository, gateway, players = FakeRepository(), FakeGateway(), FakePlayers()
    gateway.account_failures[Region.AMERICAS] = error("PLAYER_NOT_FOUND", status_code=404)

    await service(repository, gateway, players).detect(riot_id="Player#TAG", locale=Locale.EN_US)

    assert gateway.account_calls == [Region.AMERICAS, Region.ASIA]


@pytest.mark.asyncio
async def test_detection_caches_not_found_only_after_every_region_returns_404() -> None:
    repository, gateway, players = FakeRepository(), FakeGateway(), FakePlayers()
    gateway.account_failures = {
        region: error("PLAYER_NOT_FOUND", status_code=404) for region in Region
    }

    with pytest.raises(ApiError) as caught:
        await service(repository, gateway, players).detect(
            riot_id="Missing#TAG", locale=Locale.EN_US
        )

    assert caught.value.code == "PLAYER_NOT_FOUND"
    assert gateway.account_calls == [
        Region.AMERICAS,
        Region.ASIA,
        Region.EUROPE,
        Region.SEA,
    ]
    assert repository.upserts[-1].status is DetectionStatus.NOT_FOUND
    assert repository.upserts[-1].expires_at == NOW + timedelta(minutes=5)


@pytest.mark.asyncio
async def test_detection_aborts_without_cache_when_a_region_is_unavailable() -> None:
    repository, gateway, players = FakeRepository(), FakeGateway(), FakePlayers()
    gateway.account_failures[Region.AMERICAS] = error("RIOT_UNAVAILABLE", retryable=True)

    with pytest.raises(ApiError) as caught:
        await service(repository, gateway, players).detect(
            riot_id="Player#TAG", locale=Locale.EN_US
        )

    assert caught.value.code == "RIOT_UNAVAILABLE"
    assert repository.upserts == []
    assert gateway.probe_calls == []


@pytest.mark.asyncio
async def test_zero_platform_probes_cache_not_found() -> None:
    repository, gateway, players = FakeRepository(), FakeGateway(), FakePlayers()
    gateway.found = set()

    with pytest.raises(ApiError) as caught:
        await service(repository, gateway, players).detect(
            riot_id="Player#TAG", locale=Locale.EN_US
        )

    assert caught.value.code == "PLAYER_NOT_FOUND"
    assert repository.upserts[-1].status is DetectionStatus.NOT_FOUND
    assert repository.upserts[-1].expires_at == NOW + timedelta(minutes=5)


@pytest.mark.asyncio
async def test_single_platform_candidate_resolves_and_caches_for_24_hours() -> None:
    repository, gateway, players = FakeRepository(), FakeGateway(), FakePlayers()
    gateway.found = {Platform.KR}

    result = await service(repository, gateway, players).detect(
        riot_id="Player#TAG", locale=Locale.EN_US
    )

    assert isinstance(result, ResolvedDetection)
    assert repository.upserts[-1].status is DetectionStatus.RESOLVED
    assert repository.upserts[-1].candidate_platforms == (Platform.KR,)
    assert repository.upserts[-1].expires_at == NOW + timedelta(hours=24)
    assert players.calls == [(Platform.KR, "detected-puuid")]


@pytest.mark.asyncio
async def test_detection_classifies_multiple_platforms_and_uses_shared_probe_limit() -> None:
    repository, gateway, players = FakeRepository(), FakeGateway(), FakePlayers()
    gateway.found = {Platform.NA1, Platform.EUW1}

    result = await service(repository, gateway, players).detect(
        riot_id="Player#TAG", locale=Locale.EN_US
    )

    assert isinstance(result, ConfirmationRequiredDetection)
    assert [candidate.platform for candidate in result.candidates] == [Platform.EUW1, Platform.NA1]
    assert repository.upserts[-1].status is DetectionStatus.AMBIGUOUS
    assert repository.upserts[-1].expires_at == NOW + timedelta(hours=24)
    assert gateway.max_probes <= 2
    assert players.calls == []


@pytest.mark.asyncio
async def test_invalid_summoner_puuid_mismatch_is_not_cached() -> None:
    repository, gateway, players = FakeRepository(), FakeGateway(), FakePlayers()
    gateway.probe_puuid_overrides[Platform.NA1] = "other-puuid"

    with pytest.raises(ApiError) as caught:
        await service(repository, gateway, players).detect(
            riot_id="Player#TAG", locale=Locale.EN_US
        )

    assert caught.value.code == "RIOT_INVALID_RESPONSE"
    assert repository.upserts == []


@pytest.mark.asyncio
async def test_detection_fails_closed_when_any_platform_is_rate_limited() -> None:
    repository, gateway, players = FakeRepository(), FakeGateway(), FakePlayers()
    gateway.probe_failures[Platform.EUW1] = error(
        "RIOT_RATE_LIMITED", status_code=429, retryable=True
    )

    with pytest.raises(ApiError) as caught:
        await service(repository, gateway, players).detect(
            riot_id="Player#TAG", locale=Locale.EN_US
        )

    assert caught.value.code == "RIOT_PLATFORM_DETECTION_UNAVAILABLE"
    assert caught.value.retryable is True
    assert repository.upserts == []


@pytest.mark.asyncio
async def test_detection_fails_closed_when_any_platform_is_unavailable() -> None:
    repository, gateway, players = FakeRepository(), FakeGateway(), FakePlayers()
    gateway.probe_failures[Platform.EUW1] = error("RIOT_UNAVAILABLE", retryable=True)

    with pytest.raises(ApiError) as caught:
        await service(repository, gateway, players).detect(
            riot_id="Player#TAG", locale=Locale.EN_US
        )

    assert caught.value.code == "RIOT_PLATFORM_DETECTION_UNAVAILABLE"
    assert caught.value.retryable is True
    assert repository.upserts == []


@pytest.mark.asyncio
async def test_auth_failure_during_probe_is_preserved_and_not_mapped() -> None:
    repository, gateway, players = FakeRepository(), FakeGateway(), FakePlayers()
    gateway.probe_failures[Platform.NA1] = error("RIOT_AUTH_FAILED", status_code=503)

    with pytest.raises(ApiError) as caught:
        await service(repository, gateway, players).detect(
            riot_id="Player#TAG", locale=Locale.EN_US
        )

    assert caught.value.code == "RIOT_AUTH_FAILED"
    assert repository.upserts == []


@pytest.mark.asyncio
async def test_detection_single_flight_shares_upstream_work_and_cleans_up() -> None:
    repository, gateway, players = FakeRepository(), FakeGateway(), FakePlayers()
    gateway.wait_for_probe = asyncio.Event()
    detector = service(repository, gateway, players)
    first = asyncio.create_task(detector.detect(riot_id="Player#TAG", locale=Locale.EN_US))
    second = asyncio.create_task(detector.detect(riot_id="player#tag", locale=Locale.ZH_CN))
    for _ in range(50):
        if gateway.probe_calls:
            break
        await asyncio.sleep(0)
    gateway.wait_for_probe.set()
    first_result, second_result = await asyncio.gather(first, second)

    assert isinstance(first_result, ResolvedDetection)
    assert isinstance(second_result, ResolvedDetection)
    assert gateway.account_calls == [Region.AMERICAS]
    assert len(gateway.probe_calls) == len(detection_probe_platforms())
    assert detector._inflight == {}


@pytest.mark.asyncio
async def test_different_riot_ids_do_not_share_inflight_detection() -> None:
    repository, gateway, players = FakeRepository(), FakeGateway(), FakePlayers()
    gateway.wait_for_account = asyncio.Event()
    detector = service(repository, gateway, players)
    first = asyncio.create_task(detector.detect(riot_id="One#TAG", locale=Locale.EN_US))
    second = asyncio.create_task(detector.detect(riot_id="Two#TAG", locale=Locale.EN_US))
    for _ in range(50):
        if len(gateway.account_calls) >= 2:
            break
        await asyncio.sleep(0)
    assert len(gateway.account_calls) >= 2
    gateway.wait_for_account.set()
    await asyncio.gather(first, second)
    assert detector._inflight == {}


@pytest.mark.asyncio
async def test_caller_cancellation_does_not_cancel_shared_detection_task() -> None:
    repository, gateway, players = FakeRepository(), FakeGateway(), FakePlayers()
    gateway.wait_for_probe = asyncio.Event()
    detector = service(repository, gateway, players)
    first = asyncio.create_task(detector.detect(riot_id="Player#TAG", locale=Locale.EN_US))
    second = asyncio.create_task(detector.detect(riot_id="player#tag", locale=Locale.ZH_CN))
    for _ in range(50):
        if gateway.probe_calls:
            break
        await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    gateway.wait_for_probe.set()
    second_result = await second
    assert isinstance(second_result, ResolvedDetection)
    assert detector._inflight == {}


@pytest.mark.asyncio
async def test_inflight_is_cleared_after_exception() -> None:
    repository, gateway, players = FakeRepository(), FakeGateway(), FakePlayers()
    gateway.account_failures[Region.AMERICAS] = error("RIOT_UNAVAILABLE", retryable=True)
    detector = service(repository, gateway, players)

    with pytest.raises(ApiError):
        await detector.detect(riot_id="Other#TAG", locale=Locale.EN_US)

    assert detector._inflight == {}


@pytest.mark.asyncio
async def test_confirmation_reprobes_selected_platform_before_hydrating_player() -> None:
    repository, gateway, players = FakeRepository(), FakeGateway(), FakePlayers()
    cached = await repository.upsert(
        record(
            status=DetectionStatus.AMBIGUOUS,
            candidate_platforms=(Platform.NA1, Platform.EUW1),
            confirmation_expires_at=NOW + timedelta(minutes=15),
        )
    )
    original_candidates = cached.candidate_platforms

    result = await service(repository, gateway, players).confirm(
        detection_id=cached.id, platform=Platform.NA1, locale=Locale.EN_US
    )

    assert isinstance(result, ResolvedDetection)
    assert gateway.probe_calls == [Platform.NA1]
    assert players.calls == [(Platform.NA1, "detected-puuid")]
    assert repository.records[(cached.game_name_key, cached.tag_line_key)].candidate_platforms == (
        original_candidates
    )


@pytest.mark.asyncio
async def test_confirmation_rejects_expired_or_non_candidate_selection() -> None:
    repository, gateway, players = FakeRepository(), FakeGateway(), FakePlayers()
    detector = service(repository, gateway, players)
    with pytest.raises(ApiError) as expired:
        await detector.confirm(detection_id=uuid4(), platform=Platform.NA1, locale=Locale.EN_US)
    assert expired.value.code == "PLATFORM_CONFIRMATION_EXPIRED"

    cached = await repository.upsert(
        record(
            status=DetectionStatus.AMBIGUOUS,
            candidate_platforms=(Platform.NA1, Platform.EUW1),
            confirmation_expires_at=NOW + timedelta(minutes=15),
        )
    )
    with pytest.raises(ApiError) as invalid:
        await detector.confirm(detection_id=cached.id, platform=Platform.KR, locale=Locale.EN_US)
    assert invalid.value.code == "INVALID_PLATFORM_SELECTION"


@pytest.mark.asyncio
async def test_confirmation_disappeared_platform_deletes_cache_and_redetects_once() -> None:
    repository, gateway, players = FakeRepository(), FakeGateway(), FakePlayers()
    cached = await repository.upsert(
        record(
            status=DetectionStatus.AMBIGUOUS,
            candidate_platforms=(Platform.NA1, Platform.EUW1),
            confirmation_expires_at=NOW + timedelta(minutes=15),
        )
    )
    gateway.probe_failures[Platform.NA1] = error("PLAYER_NOT_FOUND", status_code=404)
    gateway.found = {Platform.EUW1}

    result = await service(repository, gateway, players).confirm(
        detection_id=cached.id, platform=Platform.NA1, locale=Locale.EN_US
    )

    assert cached.id in repository.deleted
    assert isinstance(result, ResolvedDetection)
    assert result.player.platform is Platform.EUW1
    assert gateway.account_calls == [Region.AMERICAS]
    assert players.calls == [(Platform.EUW1, "detected-puuid")]
