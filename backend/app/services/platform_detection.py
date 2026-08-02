import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID, uuid4

from app.core.errors import ApiError
from app.core.routing import Platform, Region, display_name_for, ordered_platforms
from app.repositories.platform_detections import (
    DetectionStatus,
    PlatformDetectionRecord,
    PlatformDetectionRepository,
)
from app.schemas.domain import Locale, PlayerView
from app.services.parsing.players import ParsedRiotId, parse_riot_id
from app.services.riot.dto import AccountDto, SummonerDto

# Stable Account-V1 fallback order after the configured primary region.
_REGION_FALLBACK_ORDER = (
    Region.AMERICAS,
    Region.ASIA,
    Region.EUROPE,
    Region.SEA,
)
_PROBE_AVAILABILITY_CODES = frozenset({"RIOT_RATE_LIMITED", "RIOT_UNAVAILABLE"})


@dataclass(frozen=True)
class CandidateView:
    platform: Platform
    display_name: str


@dataclass(frozen=True)
class ResolvedDetection:
    status: Literal["resolved"]
    player: PlayerView


@dataclass(frozen=True)
class ConfirmationRequiredDetection:
    status: Literal["confirmation_required"]
    detection_id: UUID
    expires_at: datetime
    candidates: tuple[CandidateView, ...]


DetectionResult = ResolvedDetection | ConfirmationRequiredDetection


class PlatformDetector(Protocol):
    async def detect(self, *, riot_id: str, locale: Locale) -> DetectionResult: ...

    async def confirm(
        self, *, detection_id: UUID, platform: Platform, locale: Locale
    ) -> DetectionResult: ...


class DetectionGateway(Protocol):
    async def get_account_by_riot_id_in_region(
        self, *, region: Region, game_name: str, tag_line: str
    ) -> AccountDto: ...

    async def get_summoner_by_puuid(self, *, platform: Platform, puuid: str) -> SummonerDto: ...


class DetectionPlayerService(Protocol):
    async def get_by_puuid(self, *, platform: Platform, puuid: str) -> PlayerView: ...


class PlatformDetectionService:
    def __init__(
        self,
        *,
        repository: PlatformDetectionRepository,
        gateway: DetectionGateway,
        player_service: DetectionPlayerService,
        detection_ttl_seconds: int,
        not_found_ttl_seconds: int,
        confirmation_ttl_seconds: int,
        primary_region: Region,
        max_concurrency: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._player_service = player_service
        self._detection_ttl_seconds = detection_ttl_seconds
        self._not_found_ttl_seconds = not_found_ttl_seconds
        self._confirmation_ttl_seconds = confirmation_ttl_seconds
        self._primary_region = primary_region
        self._probe_semaphore = asyncio.Semaphore(max_concurrency)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._inflight: dict[tuple[str, str], asyncio.Task[PlatformDetectionRecord]] = {}
        self._inflight_lock = asyncio.Lock()

    async def detect(self, *, riot_id: str, locale: Locale) -> DetectionResult:
        parsed = parse_riot_id(riot_id)
        now = self._clock()
        record = await self._repository.get_fresh(
            game_name_key=parsed.game_name_key,
            tag_line_key=parsed.tag_line_key,
            now=now,
        )
        if record is None:
            record = await self._detect_single_flight(parsed)
        elif (
            record.status is DetectionStatus.AMBIGUOUS
            and record.confirmation_expires_at is not None
            and record.confirmation_expires_at <= now
        ):
            confirmation_expires_at = now + timedelta(seconds=self._confirmation_ttl_seconds)
            record = await self._repository.upsert(
                replace(record, confirmation_expires_at=confirmation_expires_at)
            )
        return await self._result_for(record, locale)

    async def confirm(
        self, *, detection_id: UUID, platform: Platform, locale: Locale
    ) -> DetectionResult:
        record = await self._repository.get_for_confirmation(
            detection_id=detection_id,
            now=self._clock(),
        )
        if record is None:
            raise _confirmation_expired()
        if platform not in record.candidate_platforms:
            raise _invalid_platform_selection()
        if record.puuid is None:
            raise _invalid_response()
        try:
            summoner = await self._gateway.get_summoner_by_puuid(
                platform=platform, puuid=record.puuid
            )
        except ApiError as exc:
            if exc.code != "PLAYER_NOT_FOUND":
                raise
            await self._repository.delete(detection_id=detection_id)
            if record.canonical_game_name is None or record.canonical_tag_line is None:
                raise _invalid_response() from None
            return await self.detect(
                riot_id=f"{record.canonical_game_name}#{record.canonical_tag_line}", locale=locale
            )
        if summoner.puuid != record.puuid:
            raise _invalid_response()
        player = await self._player_service.get_by_puuid(platform=platform, puuid=record.puuid)
        return ResolvedDetection(status="resolved", player=player)

    async def _detect_single_flight(self, parsed: ParsedRiotId) -> PlatformDetectionRecord:
        key = (parsed.game_name_key, parsed.tag_line_key)
        async with self._inflight_lock:
            task = self._inflight.get(key)
            if task is None:
                task = asyncio.create_task(self._detect_and_remove(parsed, key))
                self._inflight[key] = task
        return await asyncio.shield(task)

    async def _detect_and_remove(
        self, parsed: ParsedRiotId, key: tuple[str, str]
    ) -> PlatformDetectionRecord:
        try:
            return await self._detect_uncached(parsed)
        finally:
            async with self._inflight_lock:
                if self._inflight.get(key) is asyncio.current_task():
                    self._inflight.pop(key, None)

    async def _detect_uncached(self, parsed: ParsedRiotId) -> PlatformDetectionRecord:
        account = await self._find_account(parsed)
        if account is None:
            record = await self._repository.upsert(
                PlatformDetectionRecord(
                    id=uuid4(),
                    game_name_key=parsed.game_name_key,
                    tag_line_key=parsed.tag_line_key,
                    canonical_game_name=None,
                    canonical_tag_line=None,
                    puuid=None,
                    status=DetectionStatus.NOT_FOUND,
                    candidate_platforms=(),
                    fetched_at=self._clock(),
                    expires_at=self._clock() + timedelta(seconds=self._not_found_ttl_seconds),
                    confirmation_expires_at=None,
                )
            )
            return record
        try:
            candidates = await self._probe_platforms(account.puuid)
        except ApiError as exc:
            if exc.code in _PROBE_AVAILABILITY_CODES:
                raise _platform_unavailable(exc) from None
            raise
        now = self._clock()
        if not candidates:
            return await self._repository.upsert(
                PlatformDetectionRecord(
                    id=uuid4(),
                    game_name_key=parsed.game_name_key,
                    tag_line_key=parsed.tag_line_key,
                    canonical_game_name=None,
                    canonical_tag_line=None,
                    puuid=None,
                    status=DetectionStatus.NOT_FOUND,
                    candidate_platforms=(),
                    fetched_at=now,
                    expires_at=now + timedelta(seconds=self._not_found_ttl_seconds),
                    confirmation_expires_at=None,
                )
            )
        ordered_candidates = tuple(
            platform for platform in ordered_platforms() if platform in set(candidates)
        )
        status = (
            DetectionStatus.RESOLVED if len(ordered_candidates) == 1 else DetectionStatus.AMBIGUOUS
        )
        return await self._repository.upsert(
            PlatformDetectionRecord(
                id=uuid4(),
                game_name_key=parsed.game_name_key,
                tag_line_key=parsed.tag_line_key,
                canonical_game_name=account.game_name,
                canonical_tag_line=account.tag_line,
                puuid=account.puuid,
                status=status,
                candidate_platforms=ordered_candidates,
                fetched_at=now,
                expires_at=now + timedelta(seconds=self._detection_ttl_seconds),
                confirmation_expires_at=(
                    now + timedelta(seconds=self._confirmation_ttl_seconds)
                    if status is DetectionStatus.AMBIGUOUS
                    else None
                ),
            )
        )

    async def _find_account(self, parsed: ParsedRiotId) -> AccountDto | None:
        for region in self._region_order():
            try:
                return await self._gateway.get_account_by_riot_id_in_region(
                    region=region,
                    game_name=parsed.game_name,
                    tag_line=parsed.tag_line,
                )
            except ApiError as exc:
                if exc.code != "PLAYER_NOT_FOUND":
                    raise
        return None

    async def _probe_platforms(self, puuid: str) -> tuple[Platform, ...]:
        tasks = [
            asyncio.create_task(self._probe_platform(platform, puuid))
            for platform in ordered_platforms()
        ]
        try:
            probed = await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        return tuple(platform for platform in probed if platform is not None)

    async def _probe_platform(self, platform: Platform, puuid: str) -> Platform | None:
        async with self._probe_semaphore:
            try:
                summoner = await self._gateway.get_summoner_by_puuid(platform=platform, puuid=puuid)
            except ApiError as exc:
                if exc.code == "PLAYER_NOT_FOUND":
                    return None
                raise
        if summoner.puuid != puuid:
            raise _invalid_response()
        return platform

    def _region_order(self) -> tuple[Region, ...]:
        return (self._primary_region,) + tuple(
            region for region in _REGION_FALLBACK_ORDER if region is not self._primary_region
        )

    async def _result_for(self, record: PlatformDetectionRecord, locale: Locale) -> DetectionResult:
        if record.status is DetectionStatus.NOT_FOUND:
            raise _player_not_found()
        if record.status is DetectionStatus.RESOLVED:
            if record.puuid is None or len(record.candidate_platforms) != 1:
                raise _invalid_response()
            player = await self._player_service.get_by_puuid(
                platform=record.candidate_platforms[0], puuid=record.puuid
            )
            return ResolvedDetection(status="resolved", player=player)
        if record.status is DetectionStatus.AMBIGUOUS:
            if record.confirmation_expires_at is None:
                raise _invalid_response()
            candidates = tuple(
                CandidateView(
                    platform=platform,
                    display_name=display_name_for(platform, locale.value),
                )
                for platform in ordered_platforms()
                if platform in record.candidate_platforms
            )
            return ConfirmationRequiredDetection(
                status="confirmation_required",
                detection_id=record.id,
                expires_at=record.confirmation_expires_at,
                candidates=candidates,
            )
        raise _invalid_response()


def _player_not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code="PLAYER_NOT_FOUND",
        message="The player was not found.",
        retryable=False,
    )


def _platform_unavailable(source: ApiError) -> ApiError:
    return ApiError(
        status_code=503,
        code="RIOT_PLATFORM_DETECTION_UNAVAILABLE",
        message="Riot platform detection is temporarily unavailable.",
        params=source.params,
        retryable=True,
        headers=source.headers,
    )


def _confirmation_expired() -> ApiError:
    return ApiError(
        status_code=409,
        code="PLATFORM_CONFIRMATION_EXPIRED",
        message="Platform confirmation has expired.",
        retryable=False,
    )


def _invalid_platform_selection() -> ApiError:
    return ApiError(
        status_code=422,
        code="INVALID_PLATFORM_SELECTION",
        message="The selected platform is not a candidate.",
        retryable=False,
    )


def _invalid_response() -> ApiError:
    return ApiError(
        status_code=502,
        code="RIOT_INVALID_RESPONSE",
        message="Riot returned an invalid response.",
        retryable=False,
    )
