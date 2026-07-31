# LoL AI Coach Phase 2 Riot Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a real bilingual NA1 flow from Riot ID search through player profile, ten recent matches, and localized match detail without exposing credentials or making coaching claims.

**Architecture:** FastAPI owns Riot routing, upstream request policy, DTO validation, normalization, Data Dragon hydration, PostgreSQL caches, and public response contracts. Next.js calls only the normalized FastAPI API through a small runtime-validated client. Phase 2 preserves replay-binding metadata but does not fetch Timeline, score matches, call OpenAI, or process video.

**Tech Stack:** Python 3.11, FastAPI, Pydantic 2, SQLAlchemy 2 async, asyncpg, Alembic, httpx2, PostgreSQL 17, pytest, Next.js 16, React 19, TypeScript 5, Zod 4, Vitest, Testing Library, Tailwind CSS 4.

## Global Constraints

- Work from an isolated worktree created with `superpowers:using-git-worktrees`; do not implement directly on `main`.
- When Codex dispatches implementation or review workers, use `gpt-5.6-terra` with high reasoning as explicitly requested by the user.
- Use TDD for every behavior change: failing focused test, observed failure, minimal implementation, focused green test, then relevant regression suite.
- The only supported platform is `NA1`; map it to regional host `americas.api.riotgames.com` and platform host `na1.api.riotgames.com`.
- `game_name`, `tag_line`, and `platform` are independent; never default the tag line to `NA1`.
- Accept `game_name` length `1..32` and `tag_line` length `1..16` after trimming; allow Unicode and do not impose an ASCII-only Riot ID pattern.
- Fetch up to ten latest Match-V5 IDs without queue filtering; mark only queue IDs `400` and `420` as analysis-supported.
- Do not call Match Timeline, OpenAI, OP.GG, or any replay/video service.
- Do not calculate metrics, scores, findings, goals, positioning, mechanics, awareness, intent, or causality.
- Riot and Data Dragon DTOs remain private to their service boundaries; public routes return normalized schemas only.
- Do not persist raw Riot or Data Dragon JSON; persist only validated normalized records.
- Map `zh-CN` to Data Dragon `zh_CN` and `en-US` to `en_US`; never silently substitute current static data for an incompatible match patch.
- The Riot API key remains server-only, is never printed, and never appears in source, fixtures, snapshots, frontend bundles, or error messages.
- Existing unified error-envelope, request-ID, and CORS behavior must remain intact for every new route.
- `make verify` excludes PostgreSQL integration tests; `make verify-postgres` requires `TEST_DATABASE_URL` and must fail rather than skip when PostgreSQL is unavailable.
- Docker Compose remains explicitly unverified on this Mac until Docker becomes available.
- Node.js support remains `>=20.9.0`; new frontend dependencies must not raise that floor.
- UI copy, errors, empty states, degraded states, dates, and capability notices must be complete in both `zh-CN` and `en-US`.
- Every task ends with a commit and a fresh reviewer gate before the next task begins.

## File and Responsibility Map

### Backend files to create

- `backend/app/core/routing.py`: closed platform enum and Riot host mapping.
- `backend/app/core/logging.py`: structured safe logging helpers and identifier hashing.
- `backend/app/core/dependencies.py`: application service container and typed route dependencies.
- `backend/app/schemas/domain.py`: locale-neutral normalized player/match domain models.
- `backend/app/schemas/players.py`: player and recent-match public response models.
- `backend/app/schemas/matches.py`: match-detail public response models.
- `backend/app/services/riot/client.py`: authenticated Riot GET policy, timeout, retry, and safe error conversion.
- `backend/app/services/riot/dto.py`: upstream-only Account, Summoner, and Match Pydantic DTOs.
- `backend/app/services/riot/gateway.py`: typed Account-V1, Summoner-V4, and Match-V5 operations.
- `backend/app/services/parsing/players.py`: player DTO normalization.
- `backend/app/services/parsing/matches.py`: match DTO normalization.
- `backend/app/services/static_data/client.py`: unauthenticated Data Dragon downloads and in-process cache.
- `backend/app/services/static_data/resolver.py`: patch-family and locale resolution plus asset hydration.
- `backend/app/services/players.py`: cached player-resolution orchestration.
- `backend/app/services/matches.py`: recent-match/detail orchestration and bounded concurrency.
- `backend/app/services/riot/smoke.py`: tested live-smoke orchestration without secret output.
- `backend/app/models/base.py`: SQLAlchemy declarative base.
- `backend/app/models/player.py`: normalized player cache row.
- `backend/app/models/recent_match_cache.py`: ordered recent-ID cache row.
- `backend/app/models/match.py`: normalized immutable match cache row.
- `backend/app/repositories/players.py`: player cache protocol and PostgreSQL implementation.
- `backend/app/repositories/recent_matches.py`: recent-match cache protocol and PostgreSQL implementation.
- `backend/app/repositories/matches.py`: match cache protocol and PostgreSQL implementation.
- `backend/app/api/players.py`: resolve and recent-match routes.
- `backend/app/api/matches.py`: match-detail route.
- `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`: migration runtime.
- `backend/alembic/versions/0001_phase_2_riot_cache.py`: Phase 2 cache tables.
- `backend/tests/fixtures/riot_payloads.py`: synthetic Account/Summoner/Match/Data Dragon fixtures.
- Focused backend tests named in each task below.

### Frontend files to create

- `frontend/src/api/schemas.ts`: Zod schemas and inferred API types.
- `frontend/src/api/client.ts`: fetch wrapper, request-ID-aware errors, and three public operations.
- `frontend/src/components/data-state.tsx`: shared loading, empty, degraded, error, and retry presentation.
- `frontend/src/components/player-header.tsx`: canonical Riot ID, level, and icon.
- `frontend/src/components/recent-match-card.tsx`: one localized match summary.
- `frontend/src/components/recent-match-list.tsx`: ordered recent-match collection.
- `frontend/src/components/player-page-client.tsx`: player page loading and request lifecycle.
- `frontend/src/components/match-team-table.tsx`: accessible standard five-player team table.
- `frontend/src/components/match-detail-client.tsx`: match-detail request lifecycle.
- `frontend/src/app/[locale]/players/[puuid]/page.tsx`: localized player route.
- `frontend/src/app/[locale]/matches/[matchId]/page.tsx`: localized match route.
- Focused frontend tests named in each task below.

### Existing files to modify

- `backend/pyproject.toml`: runtime HTTP/Alembic dependencies, pytest markers, mypy package coverage.
- `backend/app/core/config.py`: Riot settings, cache TTLs, and safe readiness property.
- `backend/app/core/database.py`: async session factory while retaining ping/close.
- `backend/app/core/errors.py`: Riot-specific safe error factories without weakening the envelope.
- `backend/app/api/health.py`: configuration-aware readiness without external calls.
- `backend/app/main.py`: service-container lifecycle and new routers.
- `backend/tests/conftest.py`: fake settings/database/services and deterministic app fixtures.
- `frontend/package.json` and `frontend/pnpm-lock.yaml`: Zod dependency.
- `frontend/src/components/riot-search-form.tsx`: real async resolution and navigation.
- `frontend/src/i18n/en-US.ts`, `frontend/src/i18n/zh-CN.ts`, `frontend/src/i18n/messages.ts`: complete Phase 2 catalogs.
- `frontend/src/app/globals.css`: player/match/state responsive styles.
- `.env.example`: empty Riot smoke inputs and separate local/container database URLs.
- `docker-compose.yml`: container-internal database URL that does not inherit the host URL.
- `Makefile`, `scripts/verify.sh`, `.github/workflows/ci.yml`: unit/integration/smoke verification.
- `README.md`: Phase 2 setup, boundaries, commands, and current verification evidence.

---

### Task 1: Typed Platform, Configuration, Readiness, and Public Contracts

**Files:**
- Create: `backend/app/core/routing.py`
- Create: `backend/app/schemas/domain.py`
- Create: `backend/app/schemas/players.py`
- Create: `backend/app/schemas/matches.py`
- Create: `backend/tests/test_routing.py`
- Create: `backend/tests/test_phase_2_schemas.py`
- Modify: `backend/app/core/config.py:9-18`
- Modify: `backend/app/api/health.py:1-27`
- Modify: `backend/app/main.py:20-43`
- Modify: `backend/tests/conftest.py:25-49`
- Modify: `backend/tests/test_health.py`

**Interfaces:**
- Produces: `Platform`, `RiotRoutes`, `routes_for(platform: Platform) -> RiotRoutes`.
- Produces: `Locale`, `RiotAccount`, `PlayerProfile`, `PlayerView`, `ParticipantSnapshot`, `MatchSnapshot`, `StaticAsset`, and `StaticDataStatus`.
- Produces: `ResolvePlayerResponse`, `RecentMatchItem`, `RecentMatchesResponse`, and `MatchDetailResponse`.
- Produces settings fields `riot_api_key`, `riot_connect_timeout_seconds`, `riot_read_timeout_seconds`, `riot_total_timeout_seconds`, `riot_retry_max_delay_seconds`, `riot_max_concurrency`, `player_cache_ttl_seconds`, `recent_matches_cache_ttl_seconds`, and `match_retention_days`.
- Produces `Settings.riot_configured -> bool` without revealing the secret.

- [ ] **Step 1: Write failing routing, schema, and readiness tests**

```python
# backend/tests/test_routing.py
import pytest

from app.core.routing import Platform, routes_for


def test_na1_routes_account_and_match_regionally_but_summoner_by_platform() -> None:
    routes = routes_for(Platform.NA1)

    assert routes.regional_host == "americas.api.riotgames.com"
    assert routes.platform_host == "na1.api.riotgames.com"


def test_unknown_platform_is_rejected_before_an_upstream_request() -> None:
    with pytest.raises(ValueError):
        Platform("EUW1")
```

```python
# backend/tests/test_phase_2_schemas.py
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
```

Add to `backend/tests/test_health.py`:

```python
def test_readiness_is_safe_when_riot_key_is_missing(fake_database: FakeDatabase) -> None:
    settings = Settings(
        app_env="test",
        database_url="postgresql+asyncpg://user:pass@db:5432/lol_ai_coach",
        backend_cors_origins="http://localhost:3000",
        riot_api_key="",
    )

    with TestClient(create_app(settings=settings, database=fake_database)) as test_client:
        response = test_client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RIOT_NOT_CONFIGURED"
    assert "RGAPI" not in response.text
    assert fake_database.ping_count == 0
```

- [ ] **Step 2: Run the focused tests and observe the missing modules/behavior**

Run:

```bash
cd backend
.venv/bin/pytest tests/test_routing.py tests/test_phase_2_schemas.py tests/test_health.py -v
```

Expected: collection fails because `app.core.routing` and the Phase 2 schemas do not exist; after those imports exist, the missing-key readiness test fails until readiness checks configuration.

- [ ] **Step 3: Implement the closed routes and exact settings**

```python
# backend/app/core/routing.py
from dataclasses import dataclass
from enum import StrEnum


class Platform(StrEnum):
    NA1 = "NA1"


@dataclass(frozen=True)
class RiotRoutes:
    regional_host: str
    platform_host: str


ROUTES = {
    Platform.NA1: RiotRoutes(
        regional_host="americas.api.riotgames.com",
        platform_host="na1.api.riotgames.com",
    )
}


def routes_for(platform: Platform) -> RiotRoutes:
    return ROUTES[platform]
```

Add these fields to `Settings` using `SecretStr`:

```python
from pydantic import SecretStr

riot_api_key: SecretStr = SecretStr("")
riot_connect_timeout_seconds: float = 2.0
riot_read_timeout_seconds: float = 5.0
riot_total_timeout_seconds: float = 10.0
riot_retry_max_delay_seconds: float = 2.0
riot_max_concurrency: int = 4
player_cache_ttl_seconds: int = 900
recent_matches_cache_ttl_seconds: int = 120
match_retention_days: int = 30

@property
def riot_configured(self) -> bool:
    return bool(self.riot_api_key.get_secret_value())
```

Store `resolved_settings` on `application.state.settings`. In `/health/ready`, return `ApiError(status_code=503, code="RIOT_NOT_CONFIGURED", message="Riot API is not configured.", retryable=False)` before pinging the database when `riot_configured` is false. Do not call Riot from readiness.

- [ ] **Step 4: Implement the normalized and public Pydantic contracts**

Use frozen Pydantic models. The minimum required fields are:

```python
# backend/app/schemas/domain.py
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.core.routing import Platform


class Locale(StrEnum):
    ZH_CN = "zh-CN"
    EN_US = "en-US"


class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RiotAccount(DomainModel):
    puuid: str
    game_name: str
    tag_line: str


class PlayerProfile(RiotAccount):
    platform: Platform
    summoner_level: int
    profile_icon_id: int


class StaticAsset(DomainModel):
    entity_id: int
    name: str
    image_url: str


class StaticDataStatus(DomainModel):
    available: bool
    version: str | None
    code: str | None


class PlayerView(PlayerProfile):
    profile_icon: StaticAsset | None
    profile_static_data_status: StaticDataStatus


class ParticipantSnapshot(DomainModel):
    puuid: str
    team_id: int
    champion_id: int
    role: str | None
    won: bool
    kills: int | None
    deaths: int | None
    assists: int | None
    cs: int | None
    gold_earned: int | None
    damage_to_champions: int | None
    vision_score: int | None
    item_ids: tuple[int, ...]


class MatchSnapshot(DomainModel):
    match_id: str
    platform: Platform
    queue_id: int
    game_version: str
    started_at: datetime
    duration_seconds: int
    participants: tuple[ParticipantSnapshot, ...]
```

Define service/public schemas as follows:

- `ResolvePlayerResponse.player` and `RecentMatchesData.player` use `PlayerView`, which preserves the numeric `profile_icon_id` and adds a backend-resolved `profile_icon` URL plus `profile_static_data_status`. The SQL player cache continues to store only `PlayerProfile`.
- `RecentMatchesData(player: PlayerView, matches: tuple[RecentMatchItem, ...])` is returned by the service; `RecentMatchesResponse` contains the same two fields plus `request_id: str`.
- `MatchDetailData` contains match metadata, `selected_puuid`, two standard five-player team lists, `static_data_status`, and `scope_notice_code="DATA_ONLY_NO_COACHING"`; `MatchDetailResponse` contains the same fields plus `request_id: str`.
- `RecentMatchItem` includes `detail_supported: bool` and `detail_unavailable_reason_code: str | None`. Set `detail_supported=true` only when the normalized match is a standard 10-participant two-team match; an unsupported mode remains visible in the list without a broken detail link.

Use these exact public field sets (implement shared fields through inheritance only when the serialized JSON remains identical):

```python
class HydratedParticipant(ParticipantSnapshot):
    champion: StaticAsset | None
    items: tuple[StaticAsset | None, ...]


class ResolvePlayerResponse(DomainModel):
    player: PlayerView
    request_id: str


class RecentMatchItem(DomainModel):
    match_id: str
    platform: Platform
    queue_id: int
    started_at: datetime
    duration_seconds: int
    game_version: str
    participant: HydratedParticipant
    analysis_supported: bool
    unsupported_reason_code: str | None
    detail_supported: bool
    detail_unavailable_reason_code: str | None
    static_data_status: StaticDataStatus


class RecentMatchesData(DomainModel):
    player: PlayerView
    matches: tuple[RecentMatchItem, ...]


class RecentMatchesResponse(RecentMatchesData):
    request_id: str


class MatchDetailData(DomainModel):
    match_id: str
    platform: Platform
    queue_id: int
    started_at: datetime
    duration_seconds: int
    game_version: str
    selected_puuid: str
    blue_team: tuple[HydratedParticipant, ...]
    red_team: tuple[HydratedParticipant, ...]
    static_data_status: StaticDataStatus
    scope_notice_code: Literal["DATA_ONLY_NO_COACHING"] = "DATA_ONLY_NO_COACHING"


class MatchDetailResponse(MatchDetailData):
    request_id: str
```

Maintain the invariant `len(items) == len(item_ids)`, including `None` assets for unknown catalog entries. The service constructors validate exactly five blue and five red participants before creating `MatchDetailData`.

In the standard `backend/tests/conftest.py` settings fixture, set `riot_api_key="RGAPI-test"` so pre-existing readiness tests remain green. The dedicated missing-key test must construct its own settings with an empty key.

- [ ] **Step 5: Run focused and full backend tests**

Run:

```bash
cd backend
.venv/bin/pytest tests/test_routing.py tests/test_phase_2_schemas.py tests/test_health.py -v
.venv/bin/pytest -v
.venv/bin/ruff check .
.venv/bin/mypy
```

Expected: all tests pass, Ruff reports no errors, and mypy reports no issues.

- [ ] **Step 6: Commit Task 1**

```bash
git add backend/app/core/routing.py backend/app/core/config.py backend/app/api/health.py backend/app/main.py backend/app/schemas backend/tests
git commit -m "feat: define phase two Riot contracts"
```

---

### Task 2: Riot HTTP Client, DTOs, and Gateway

**Files:**
- Create: `backend/app/core/logging.py`
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/riot/__init__.py`
- Create: `backend/app/services/riot/client.py`
- Create: `backend/app/services/riot/dto.py`
- Create: `backend/app/services/riot/gateway.py`
- Create: `backend/tests/test_riot_client.py`
- Create: `backend/tests/test_riot_gateway.py`
- Create: `backend/tests/test_safe_logging.py`
- Create: `backend/tests/fixtures/__init__.py`
- Create: `backend/tests/fixtures/riot_payloads.py`
- Modify: `backend/pyproject.toml:9-25`
- Modify: `backend/app/core/errors.py`

**Interfaces:**
- Consumes: `Platform`, `RiotRoutes`, `routes_for`, and Phase 2 settings from Task 1.
- Produces: `RiotHttpClient.get_json(host: str, path: str, params: dict[str, str | int] | None, not_found_code: str) -> object`.
- Produces: `RiotGateway.get_account_by_riot_id`, `get_summoner_by_puuid`, `get_match_ids`, and `get_match`.
- Produces DTOs `AccountDto`, `SummonerDto`, `MatchDto`, and nested participant DTOs.
- Produces `SafeRequestContext`, `bind_safe_request_context`, `hashed_player_reference`, and `log_safe_operation`; no operational log may contain a full PUUID, Riot ID, request URL, response body, or token.
- Uses `httpx2.AsyncClient`; move `httpx2>=2.9,<3.0` from dev-only to runtime dependencies.

- [ ] **Step 1: Write failing Riot HTTP-policy tests**

```python
# backend/tests/test_riot_client.py
import httpx2
import pytest

from app.core.errors import ApiError
from app.services.riot.client import RiotHttpClient


@pytest.mark.asyncio
async def test_riot_client_sends_server_only_token() -> None:
    seen_header = ""

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal seen_header
        seen_header = request.headers["X-Riot-Token"]
        return httpx2.Response(200, json={"puuid": "p"})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport_client:
        client = RiotHttpClient(api_key="RGAPI-fake", client=transport_client)
        body = await client.get_json(
            host="americas.api.riotgames.com",
            path="/riot/account/v1/accounts/by-riot-id/Player/1115",
            params=None,
            not_found_code="PLAYER_NOT_FOUND",
        )

    assert body == {"puuid": "p"}
    assert seen_header == "RGAPI-fake"


@pytest.mark.asyncio
async def test_riot_client_maps_rate_limit_without_unbounded_sleep() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(429, headers={"Retry-After": "30"}, json={})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport_client:
        client = RiotHttpClient(
            api_key="RGAPI-fake",
            client=transport_client,
            retry_max_delay_seconds=2.0,
        )
        with pytest.raises(ApiError) as caught:
            await client.get_json(
                host="americas.api.riotgames.com",
                path="/test",
                params=None,
                not_found_code="PLAYER_NOT_FOUND",
            )

    assert caught.value.code == "RIOT_RATE_LIMITED"
    assert caught.value.params == {"retry_after_seconds": 30}
    assert caught.value.retryable is True
```

Add separate tests for `401`, `403`, contextual `404`, one retry after `500`, timeout exhaustion, malformed JSON, and a response body containing a fake secret that must not appear in the resulting error message.

Add `backend/tests/test_safe_logging.py`:

```python
import json
import logging

from app.core.logging import log_safe_operation


def test_structured_log_hashes_player_reference_and_omits_secret(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="lol_ai_coach.test"):
        log_safe_operation(
            logging.getLogger("lol_ai_coach.test"),
            event="riot_request",
            request_id="request-1",
            route="/api/v1/players/{puuid}/matches",
            safe_status="success",
            upstream="riot-match-v5",
            latency_ms=12,
            retry_count=1,
            cache_status="miss",
            player_reference="full-puuid-secret",
        )

    payload = json.loads(caplog.messages[-1])
    assert payload["request_id"] == "request-1"
    assert payload["route"] == "/api/v1/players/{puuid}/matches"
    assert payload["player_reference_hash"]
    assert "full-puuid-secret" not in caplog.text
    assert "RGAPI" not in caplog.text
```

- [ ] **Step 2: Run client tests and observe failure**

Run:

```bash
cd backend
.venv/bin/pytest tests/test_riot_client.py tests/test_safe_logging.py -v
```

Expected: collection fails because `app.services.riot.client` does not exist.

- [ ] **Step 3: Add runtime dependency and implement bounded Riot GET behavior**

Move `httpx2>=2.9,<3.0` into `[project].dependencies`. Build URLs only from approved hosts and quoted path segments. The response mapping must be:

```python
STATUS_MAPPING = {
    400: (502, "RIOT_REQUEST_INVALID", False),
    401: (503, "RIOT_AUTH_FAILED", False),
    403: (503, "RIOT_AUTH_FAILED", False),
    429: (429, "RIOT_RATE_LIMITED", True),
}
```

For `404`, use the caller-provided code and HTTP 404. For final `5xx`, connection, or timeout failure, raise HTTP 503 `RIOT_UNAVAILABLE` with `retryable=True`. For invalid JSON, raise HTTP 502 `RIOT_INVALID_RESPONSE` with `retryable=False`. A `400` indicates an internal Riot request-contract error, is never retried, and returns only the stable safe code `RIOT_REQUEST_INVALID`. Safe messages are fixed constants; never include response text or the request URL.

The constructor must accept an injected `httpx2.AsyncClient`, injected async sleep callable, injected bounded-jitter callable, monotonic clock, and logger so tests do not use real time. Wrap the complete attempt/retry sequence in `asyncio.timeout(riot_total_timeout_seconds)`. Only idempotent GETs retry, at most once. Retry a `429` only when the parsed non-negative `Retry-After` value is at most `retry_max_delay_seconds`; use injected jitter bounded by the same maximum for retryable `5xx`/connection failures. Add a test proving total-budget exhaustion becomes `RIOT_UNAVAILABLE` without a second unbounded wait.

`backend/app/core/logging.py` serializes a fixed allowlist to one compact JSON object. `hashed_player_reference` is the first 16 hexadecimal characters of SHA-256 over the provided reference; the raw value is never added. A request-scoped `ContextVar[SafeRequestContext | None]` holds only `request_id` and the FastAPI route template. A yield dependency binds/resets it after routing; add that dependency to the new API routers. `RiotHttpClient` logs upstream, safe status, monotonic latency, and retry count. Tasks 5–6 log cache hit/miss/refresh with a hashed player reference. Tests must prove arbitrary upstream payloads and the injected fake key cannot enter any log record.

- [ ] **Step 4: Write failing gateway path and DTO tests**

```python
# backend/tests/test_riot_gateway.py
import httpx2
import pytest

from app.core.routing import Platform
from app.services.riot.client import RiotHttpClient
from app.services.riot.gateway import RiotGateway


@pytest.mark.asyncio
async def test_gateway_uses_independent_tag_line_and_regional_account_route() -> None:
    seen_url = ""

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal seen_url
        seen_url = str(request.url)
        return httpx2.Response(
            200,
            json={"puuid": "puuid-1", "gameName": "Player Name", "tagLine": "1115"},
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as raw_client:
        gateway = RiotGateway(RiotHttpClient(api_key="RGAPI-fake", client=raw_client))
        account = await gateway.get_account_by_riot_id(
            platform=Platform.NA1,
            game_name="Player Name",
            tag_line="1115",
        )

    assert account.tag_line == "1115"
    assert seen_url.startswith("https://americas.api.riotgames.com/")
    assert "Player%20Name/1115" in seen_url
```

Add tests proving Summoner-V4 uses `na1`, Match-V5 uses `americas`, recent-match query sends `start=0&count=10`, and a Match DTO rejects a missing critical `metadata.matchId`.

- [ ] **Step 5: Implement exact gateway operations and DTO validation**

```python
# backend/app/services/riot/gateway.py
from urllib.parse import quote

from app.core.routing import Platform, routes_for
from app.services.riot.client import RiotHttpClient
from app.services.riot.dto import AccountDto, MatchDto, SummonerDto


class RiotGateway:
    def __init__(self, client: RiotHttpClient) -> None:
        self._client = client

    async def get_account_by_riot_id(
        self, *, platform: Platform, game_name: str, tag_line: str
    ) -> AccountDto:
        host = routes_for(platform).regional_host
        path = (
            "/riot/account/v1/accounts/by-riot-id/"
            f"{quote(game_name, safe='')}/{quote(tag_line, safe='')}"
        )
        payload = await self._client.get_json(
            host=host, path=path, params=None, not_found_code="PLAYER_NOT_FOUND"
        )
        return validate_riot_model(AccountDto, payload)

    async def get_summoner_by_puuid(
        self, *, platform: Platform, puuid: str
    ) -> SummonerDto:
        host = routes_for(platform).platform_host
        payload = await self._client.get_json(
            host=host,
            path=f"/lol/summoner/v4/summoners/by-puuid/{quote(puuid, safe='')}",
            params=None,
            not_found_code="PLAYER_NOT_FOUND",
        )
        return validate_riot_model(SummonerDto, payload)

    async def get_match_ids(
        self, *, platform: Platform, puuid: str, count: int
    ) -> tuple[str, ...]:
        host = routes_for(platform).regional_host
        payload = await self._client.get_json(
            host=host,
            path=f"/lol/match/v5/matches/by-puuid/{quote(puuid, safe='')}/ids",
            params={"start": 0, "count": count},
            not_found_code="PLAYER_NOT_FOUND",
        )
        return validate_match_ids(payload, max_count=count)

    async def get_match(self, *, platform: Platform, match_id: str) -> MatchDto:
        host = routes_for(platform).regional_host
        payload = await self._client.get_json(
            host=host,
            path=f"/lol/match/v5/matches/{quote(match_id, safe='')}",
            params=None,
            not_found_code="MATCH_NOT_FOUND",
        )
        return validate_riot_model(MatchDto, payload)
```

DTOs use explicit aliases such as `gameName`, `tagLine`, `profileIconId`, `summonerLevel`, `matchId`, `gameCreation`, `gameDuration`, `gameVersion`, `queueId`, `teamId`, `championId`, `teamPosition`, `goldEarned`, `totalDamageDealtToChampions`, `visionScore`, `totalMinionsKilled`, and `neutralMinionsKilled`. Set `extra="ignore"`. Critical identity, match, team, champion, and win/loss fields are required. Non-critical role/statistic fields default to `None`, item slots default to `None`, and normalization preserves typed unavailable values rather than rejecting the whole match.

All gateway validation goes through one helper using `TypeAdapter`/`BaseModel.model_validate` inside `try/except ValidationError`; convert any failure to `ApiError(status_code=502, code="RIOT_INVALID_RESPONSE", message="Riot returned an invalid response.", retryable=False)` with `raise ... from None`. Validate Match-ID responses as a strict list of strings and reject more entries than requested; never coerce arbitrary objects with `str(value)`.

- [ ] **Step 6: Run focused and regression tests**

Run:

```bash
cd backend
.venv/bin/pytest tests/test_riot_client.py tests/test_riot_gateway.py tests/test_safe_logging.py -v
.venv/bin/pytest -v
.venv/bin/ruff check .
.venv/bin/mypy
```

Expected: all tests and checks pass without network access or warning output.

- [ ] **Step 7: Commit Task 2**

```bash
git add backend/pyproject.toml backend/app/core/errors.py backend/app/core/logging.py backend/app/services backend/tests/test_riot_client.py backend/tests/test_riot_gateway.py backend/tests/test_safe_logging.py backend/tests/fixtures
git commit -m "feat: add safe Riot API gateway"
```

---

### Task 3: Pure Normalization and Localized Data Dragon Hydration

**Files:**
- Create: `backend/app/services/parsing/__init__.py`
- Create: `backend/app/services/parsing/players.py`
- Create: `backend/app/services/parsing/matches.py`
- Create: `backend/app/services/static_data/__init__.py`
- Create: `backend/app/services/static_data/client.py`
- Create: `backend/app/services/static_data/resolver.py`
- Create: `backend/tests/test_player_parsing.py`
- Create: `backend/tests/test_match_parsing.py`
- Create: `backend/tests/test_static_data.py`
- Modify: `backend/tests/fixtures/riot_payloads.py`

**Interfaces:**
- Consumes: Task 1 domain models and Task 2 DTOs.
- Produces: `normalize_player(account: AccountDto, summoner: SummonerDto, platform: Platform) -> PlayerProfile`.
- Produces: `normalize_match(dto: MatchDto, platform: Platform) -> MatchSnapshot`.
- Produces: `StaticDataResolver.hydrate_player(profile: PlayerProfile) -> PlayerView` using the newest advertised Data Dragon version for the current profile icon.
- Produces: `StaticDataResolver.hydrate_match(snapshot: MatchSnapshot, locale: Locale) -> HydratedMatch`.
- Produces: patch helper `compatible_version(game_version: str, versions: tuple[str, ...]) -> str | None`.
- Reuses the exact `HydratedParticipant` schema from Task 1 and defines internal immutable `HydratedMatch(snapshot, participants, static_data_status)` for resolver-to-service transfer; Riot DTOs remain private and are never serialized directly.

- [ ] **Step 1: Write failing pure normalization tests**

```python
# backend/tests/test_match_parsing.py
from app.core.routing import Platform
from app.services.parsing.matches import normalize_match
from app.services.riot.dto import MatchDto
from tests.fixtures.riot_payloads import MATCH_PAYLOAD


def test_match_normalization_combines_lane_and_jungle_cs_and_keeps_ten_players() -> None:
    snapshot = normalize_match(MatchDto.model_validate(MATCH_PAYLOAD), Platform.NA1)

    assert snapshot.match_id == "NA1_123456789"
    assert len(snapshot.participants) == 10
    assert snapshot.participants[0].cs == 214
    assert snapshot.participants[0].item_ids == (1055, 6672, 3006)
    assert snapshot.game_version == "16.15.602.1234"
```

```python
# backend/tests/test_player_parsing.py
from app.core.routing import Platform
from app.services.parsing.players import normalize_player
from app.services.riot.dto import AccountDto, SummonerDto


def test_player_normalization_preserves_canonical_riot_id() -> None:
    profile = normalize_player(
        AccountDto(puuid="p", gameName="Canonical Name", tagLine="1115"),
        SummonerDto(puuid="p", profileIconId=29, summonerLevel=772),
        Platform.NA1,
    )

    assert profile.game_name == "Canonical Name"
    assert profile.tag_line == "1115"
```

- [ ] **Step 2: Run normalization tests and observe failure**

Run:

```bash
cd backend
.venv/bin/pytest tests/test_player_parsing.py tests/test_match_parsing.py -v
```

Expected: collection fails because the parsing modules do not exist.

- [ ] **Step 3: Implement minimal pure parsers**

`normalize_player` must reject mismatched Account/Summoner PUUIDs with `RIOT_INVALID_RESPONSE`. `normalize_match` must:

```python
def normalize_item_ids(participant: ParticipantDto) -> tuple[int, ...]:
    values = (
        participant.item0,
        participant.item1,
        participant.item2,
        participant.item3,
        participant.item4,
        participant.item5,
        participant.item6,
    )
    return tuple(value for value in values if value is not None and value > 0)


def normalized_role(team_position: str) -> str | None:
    allowed = {"TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"}
    return team_position if team_position in allowed else None
```

Convert `gameCreation` milliseconds to an aware UTC `datetime`. Compute `cs` only when both lane- and neutral-minion fields are present; otherwise set it to `None`. Reject a match with zero participants, duplicate PUUIDs, or a metadata Match ID different from the requested DTO's identity. Do not reject a valid non-10-player Riot mode during normalization: recent-match discovery must still display it. Add the pure predicate `supports_standard_detail(snapshot) -> bool`, true only when the snapshot has exactly ten participants, team IDs are exactly `100` and `200`, and each team contains five players. Task 6 uses that predicate to expose or suppress the standard 5v5 detail link.

- [ ] **Step 4: Write failing Data Dragon compatibility and degradation tests**

```python
# backend/tests/test_static_data.py
from app.schemas.domain import Locale
from app.services.static_data.resolver import compatible_version, locale_code


def test_compatible_version_selects_newest_build_in_match_patch_family() -> None:
    versions = ("16.16.1", "16.15.2", "16.15.1", "16.14.1")

    assert compatible_version("16.15.602.1234", versions) == "16.15.2"


def test_incompatible_patch_does_not_use_current_static_data() -> None:
    assert compatible_version("15.24.1.1", ("16.16.1", "16.15.2")) is None


def test_product_locale_maps_to_data_dragon_locale() -> None:
    assert locale_code(Locale.ZH_CN) == "zh_CN"
    assert locale_code(Locale.EN_US) == "en_US"
```

Add an async test whose fake Data Dragon client raises a timeout and assert the resolver returns `StaticDataStatus(available=False, version=None, code="STATIC_DATA_UNAVAILABLE")` while retaining all normalized numeric match data. Add player-hydration tests proving a current profile icon receives a complete backend URL and that a versions-list failure preserves `profile_icon_id` while returning `profile_icon=None` with degraded status.

- [ ] **Step 5: Run Data Dragon tests and observe failure**

Run:

```bash
cd backend
.venv/bin/pytest tests/test_static_data.py -v
```

Expected: collection fails because the static-data modules do not exist.

- [ ] **Step 6: Implement versioned, locale-aware static data**

`compatible_version` parses only numeric major/minor components, filters versions with the same pair, and returns the highest semantic version in that family. Invalid versions return `None` rather than guessing.

`StaticDataClient` fetches:

```text
https://ddragon.leagueoflegends.com/api/versions.json
https://ddragon.leagueoflegends.com/cdn/{version}/data/{locale}/champion.json
https://ddragon.leagueoflegends.com/cdn/{version}/data/{locale}/item.json
```

For current player profiles, `hydrate_player` obtains the newest valid version from `versions.json` and constructs `https://ddragon.leagueoflegends.com/cdn/{version}/img/profileicon/{profile_icon_id}.png`. It returns the numeric ID even when versions cannot be loaded; then `profile_icon=None` and `profile_static_data_status.code="STATIC_DATA_UNAVAILABLE"`. Match hydration still requires a compatible match patch and never uses this newest-version rule.

It accepts an injected `httpx2.AsyncClient`, uses no Riot token, and caches parsed catalogs by `(version, locale)` for the process lifetime. Asset URLs are:

```python
def champion_image_url(version: str, image_name: str) -> str:
    return f"https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/{image_name}"


def item_image_url(version: str, image_name: str) -> str:
    return f"https://ddragon.leagueoflegends.com/cdn/{version}/img/item/{image_name}"
```

Hydration never mutates the cached `MatchSnapshot`. Missing champion/item entries yield `None` assets and degraded status; they do not substitute another version.

- [ ] **Step 7: Run focused and full backend verification**

Run:

```bash
cd backend
.venv/bin/pytest tests/test_player_parsing.py tests/test_match_parsing.py tests/test_static_data.py -v
.venv/bin/pytest -v
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy
```

Expected: all tests and checks pass without live Riot or Data Dragon traffic.

- [ ] **Step 8: Commit Task 3**

```bash
git add backend/app/services/parsing backend/app/services/static_data backend/tests/test_player_parsing.py backend/tests/test_match_parsing.py backend/tests/test_static_data.py backend/tests/fixtures/riot_payloads.py
git commit -m "feat: normalize Riot and static data"
```

---

### Task 4: Alembic, PostgreSQL Cache Models, Repositories, and Integration Gate

**Files:**
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/models/base.py`
- Create: `backend/app/models/player.py`
- Create: `backend/app/models/recent_match_cache.py`
- Create: `backend/app/models/match.py`
- Create: `backend/app/repositories/__init__.py`
- Create: `backend/app/repositories/players.py`
- Create: `backend/app/repositories/recent_matches.py`
- Create: `backend/app/repositories/matches.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/0001_phase_2_riot_cache.py`
- Create: `backend/tests/integration/__init__.py`
- Create: `backend/tests/integration/conftest.py`
- Create: `backend/tests/integration/test_migrations.py`
- Create: `backend/tests/integration/test_repositories.py`
- Modify: `backend/app/core/database.py:1-22`
- Modify: `backend/pyproject.toml`
- Modify: `.env.example`
- Modify: `docker-compose.yml:17-21`
- Modify: `Makefile`
- Modify: `scripts/verify.sh`
- Modify: `.github/workflows/ci.yml:8-25`

**Interfaces:**
- Consumes: `PlayerProfile`, `MatchSnapshot`, and `Platform` from Tasks 1–3.
- Produces: `Database.session_factory: async_sessionmaker[AsyncSession]` while preserving `ping()` and `close()`.
- Produces protocols and implementations `PlayerRepository`, `RecentMatchRepository`, and `MatchRepository`.
- Produces `make verify-postgres` and pytest marker `integration`.
- Produces host `DATABASE_URL` and container-only `COMPOSE_DATABASE_URL` conventions.

- [ ] **Step 1: Write failing PostgreSQL repository integration tests with a safety guard**

```python
# backend/tests/integration/conftest.py
import os
from collections.abc import AsyncIterator
from pathlib import Path
import asyncio

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@pytest.fixture(scope="session")
def test_database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL", "")
    if not value:
        pytest.fail("TEST_DATABASE_URL is required for integration tests")
    database_name = make_url(value).database or ""
    if not database_name.endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must target a database ending in _test")
    return value


@pytest_asyncio.fixture
async def integration_engine(test_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(test_database_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def migrated_database(test_database_url: str) -> AsyncIterator[None]:
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", test_database_url)
    await asyncio.to_thread(command.downgrade, config, "base")
    await asyncio.to_thread(command.upgrade, config, "head")
    yield


@pytest_asyncio.fixture
async def session_factory(
    migrated_database: None,
    integration_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async with integration_engine.begin() as connection:
        await connection.execute(
            text("TRUNCATE TABLE matches, recent_match_caches, players CASCADE")
        )
    yield async_sessionmaker(
        integration_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
```

```python
# backend/tests/integration/test_repositories.py
from datetime import UTC, datetime, timedelta

import pytest

from app.core.routing import Platform
from app.repositories.players import SqlPlayerRepository
from app.schemas.domain import PlayerProfile


pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_player_repository_respects_fresh_after(session_factory) -> None:
    repository = SqlPlayerRepository(session_factory)
    profile = PlayerProfile(
        puuid="integration-puuid",
        game_name="PlayerName",
        tag_line="1115",
        platform=Platform.NA1,
        summoner_level=50,
        profile_icon_id=29,
    )
    fetched_at = datetime.now(UTC)
    await repository.upsert(profile, fetched_at=fetched_at)

    fresh = await repository.get_by_riot_id(
        platform=Platform.NA1,
        game_name_key="playername",
        tag_line_key="1115",
        fresh_after=fetched_at - timedelta(seconds=1),
    )
    expired = await repository.get_by_riot_id(
        platform=Platform.NA1,
        game_name_key="playername",
        tag_line_key="1115",
        fresh_after=fetched_at + timedelta(seconds=1),
    )

    assert fresh == profile
    assert expired is None
```

Add integration tests for ordered recent IDs, match JSONB round trip, match upsert idempotency, same-schema content-conflict rejection without overwriting the original, a stale match being excluded by `fresh_after`, expired-match deletion, unique PUUID, and migration upgrade from an empty test schema. `test_migrations.py` must leave the schema at `head` in `finally`, even if an assertion fails.

- [ ] **Step 2: Run the integration test command and observe failure**

Run with a dedicated PostgreSQL test URL:

```bash
cd backend
TEST_DATABASE_URL=postgresql+asyncpg://lol_ai_coach:lol_ai_coach@localhost:5432/lol_ai_coach_test .venv/bin/pytest -m integration -v
```

Expected: collection fails because the models, repositories, and migration environment do not exist. If PostgreSQL is unavailable, record that environmental blocker; do not substitute SQLite or mark the test successful.

- [ ] **Step 3: Add Alembic and database-session support**

Add `alembic>=1.16,<2.0` to runtime dependencies and these pytest settings:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
  "integration: requires TEST_DATABASE_URL pointing to a dedicated PostgreSQL test database",
]
```

Extend `Database`:

```python
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class Database:
    def __init__(self, database_url: str) -> None:
        self._engine = create_async_engine(database_url, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
```

The Alembic environment reads `DATABASE_URL` from `Settings` but replaces `+asyncpg` only when Alembic's synchronous configuration requires it; prefer Alembic's async migration template so the application and migrations use the same URL.

- [ ] **Step 4: Implement exact SQLAlchemy cache rows and migration**

Use `Mapped` and `mapped_column`. Required table shapes are:

```python
# backend/app/models/player.py
class PlayerRow(Base):
    __tablename__ = "players"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    puuid: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    platform: Mapped[str] = mapped_column(String(8), index=True)
    game_name: Mapped[str] = mapped_column(String(128))
    tag_line: Mapped[str] = mapped_column(String(64))
    game_name_key: Mapped[str] = mapped_column(String(128), index=True)
    tag_line_key: Mapped[str] = mapped_column(String(64), index=True)
    summoner_level: Mapped[int]
    profile_icon_id: Mapped[int]
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

`RecentMatchCacheRow` uses composite primary key `(platform, puuid)`, PostgreSQL `ARRAY(String(32))` for ordered Match IDs, `fetched_at`, and `expires_at`. `MatchRow` uses Match ID primary key, platform, queue ID, game version, started time, duration, JSONB normalized snapshot, schema version `1`, normalized SHA-256 hash, and fetched time.

The migration creates only these three tables and their declared indexes. It must not create Phase 3 analytics, AI, or replay tables.

- [ ] **Step 5: Implement repository protocols and SQL repositories**

Protocols must expose these exact async methods:

```python
class PlayerRepository(Protocol):
    async def get_by_riot_id(
        self,
        *,
        platform: Platform,
        game_name_key: str,
        tag_line_key: str,
        fresh_after: datetime,
    ) -> PlayerProfile | None:
        raise NotImplementedError

    async def get_by_puuid(
        self, *, platform: Platform, puuid: str, fresh_after: datetime
    ) -> PlayerProfile | None:
        raise NotImplementedError

    async def upsert(self, profile: PlayerProfile, *, fetched_at: datetime) -> None:
        raise NotImplementedError


class RecentMatchRepository(Protocol):
    async def get(
        self, *, platform: Platform, puuid: str, now: datetime
    ) -> tuple[str, ...] | None:
        raise NotImplementedError

    async def put(
        self,
        *,
        platform: Platform,
        puuid: str,
        match_ids: tuple[str, ...],
        fetched_at: datetime,
        expires_at: datetime,
    ) -> None:
        raise NotImplementedError


class MatchRepository(Protocol):
    async def get(
        self,
        *,
        platform: Platform,
        match_id: str,
        fresh_after: datetime,
    ) -> MatchSnapshot | None:
        raise NotImplementedError

    async def put(self, snapshot: MatchSnapshot, *, fetched_at: datetime) -> None:
        raise NotImplementedError

    async def delete_expired(self, *, before: datetime) -> int:
        raise NotImplementedError
```

Use PostgreSQL `INSERT ... ON CONFLICT DO UPDATE`. Serialize `MatchSnapshot` with `model_dump(mode="json")`; validate it again with `MatchSnapshot.model_validate` on reads. Compute the hash from canonical JSON with sorted keys and compact separators. A conflict with the same Match ID, schema version, and content hash updates only `fetched_at`; the normalized snapshot remains immutable. A same-schema conflict with a different hash raises a safe internal `MatchCacheConflict` and leaves the stored row unchanged. A future higher schema version may use an explicit re-normalization migration, not this Phase 2 write path. `get` must filter `fetched_at >= fresh_after`; `delete_expired` removes rows older than the configured retention boundary and returns the affected-row count. Task 6 performs this bounded cleanup opportunistically after successful cache writes, making the 30-day retention rule executable without adding a scheduler.

- [ ] **Step 6: Separate host and container database URLs**

Change `.env.example` to:

```dotenv
DATABASE_URL=postgresql+asyncpg://lol_ai_coach:lol_ai_coach@localhost:5432/lol_ai_coach
COMPOSE_DATABASE_URL=postgresql+asyncpg://lol_ai_coach:lol_ai_coach@db:5432/lol_ai_coach
TEST_DATABASE_URL=postgresql+asyncpg://lol_ai_coach:lol_ai_coach@localhost:5432/lol_ai_coach_test
```

Change Compose backend configuration to `DATABASE_URL: ${COMPOSE_DATABASE_URL:-postgresql+asyncpg://lol_ai_coach:lol_ai_coach@db:5432/lol_ai_coach}`. Do not pass host `DATABASE_URL` into the container.

- [ ] **Step 7: Add explicit local and CI verification gates**

Change backend test invocations in `scripts/verify.sh` and `Makefile` to:

```bash
.venv/bin/pytest -m "not integration" -v
```

Add:

```make
verify-postgres:
	test -n "$$TEST_DATABASE_URL"
	cd backend; .venv/bin/alembic upgrade head
	cd backend; .venv/bin/pytest -m integration -v
```

In the backend CI job, add a PostgreSQL 17 service with database `lol_ai_coach_test`, a `pg_isready` health check, and `TEST_DATABASE_URL=postgresql+asyncpg://lol_ai_coach:lol_ai_coach@localhost:5432/lol_ai_coach_test`. Run `make verify-postgres` after the non-integration backend tests.

- [ ] **Step 8: Run available checks and the real PostgreSQL gate where available**

Run:

```bash
make verify
make verify-postgres
git diff --check
```

Expected: `make verify` passes everywhere. `make verify-postgres` passes only with the dedicated PostgreSQL test database; if the current Mac still lacks PostgreSQL/Docker, keep the task open until CI or another PostgreSQL environment records a passing run.

- [ ] **Step 9: Commit Task 4**

```bash
git add backend/app/core/database.py backend/app/models backend/app/repositories backend/alembic.ini backend/alembic backend/tests/integration backend/pyproject.toml .env.example docker-compose.yml Makefile scripts/verify.sh .github/workflows/ci.yml
git commit -m "feat: add PostgreSQL Riot data caches"
```

---

### Task 5: Cached Player Resolution Service and API

**Files:**
- Create: `backend/app/core/dependencies.py`
- Create: `backend/app/services/players.py`
- Create: `backend/app/api/players.py`
- Create: `backend/tests/test_player_service.py`
- Create: `backend/tests/test_player_api.py`
- Modify: `backend/app/services/riot/gateway.py`
- Modify: `backend/tests/test_riot_gateway.py`
- Modify: `backend/app/main.py:16-47`
- Modify: `backend/tests/conftest.py`
- Modify: `docker-compose.yml`

**Interfaces:**
- Consumes: `RiotGateway`, `normalize_player`, `StaticDataResolver`, `PlayerRepository`, `Settings`, and `ResolvePlayerResponse`.
- Produces: `PlayerService.resolve(platform, game_name, tag_line) -> PlayerView`.
- Produces: `PlayerService.get_by_puuid(platform, puuid) -> PlayerView` for Task 6.
- Produces: `GET /api/v1/players/resolve`.
- Produces: Task 5 `AppServices` containing `player_service` and deterministic async close behavior; Task 6 extends the same container with `match_service`.
- Adds `RiotGateway.get_account_by_puuid(platform, puuid) -> AccountDto` for cache-independent direct player URLs.

- [ ] **Step 1: Extend the gateway with a failing by-PUUID account test**

```python
@pytest.mark.asyncio
async def test_gateway_gets_account_by_puuid_on_regional_route() -> None:
    seen_url = ""

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal seen_url
        seen_url = str(request.url)
        return httpx2.Response(
            200,
            json={"puuid": "puuid-1", "gameName": "PlayerName", "tagLine": "1115"},
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as raw_client:
        gateway = RiotGateway(RiotHttpClient(api_key="RGAPI-fake", client=raw_client))
        account = await gateway.get_account_by_puuid(platform=Platform.NA1, puuid="puuid-1")

    assert account.game_name == "PlayerName"
    assert seen_url.startswith("https://americas.api.riotgames.com/")
    assert seen_url.endswith("/riot/account/v1/accounts/by-puuid/puuid-1")
```

Run the test and expect `AttributeError` before adding the method with safe URL quoting and `PLAYER_NOT_FOUND` mapping.

- [ ] **Step 2: Write failing player-service cache tests**

```python
# backend/tests/test_player_service.py
from datetime import UTC, datetime

import pytest

from app.core.routing import Platform
from app.schemas.domain import PlayerProfile
from app.services.players import PlayerService


@pytest.mark.asyncio
async def test_resolve_returns_fresh_cache_without_riot_call(
    fake_player_repository, fake_riot_gateway, fake_static_resolver
) -> None:
    cached = PlayerProfile(
        puuid="cached-puuid",
        game_name="Canonical",
        tag_line="1115",
        platform=Platform.NA1,
        summoner_level=50,
        profile_icon_id=29,
    )
    fake_player_repository.cached_profile = cached
    service = PlayerService(
        repository=fake_player_repository,
        gateway=fake_riot_gateway,
        static_resolver=fake_static_resolver,
        cache_ttl_seconds=900,
        clock=lambda: datetime(2026, 7, 30, tzinfo=UTC),
    )

    result = await service.resolve(
        platform=Platform.NA1, game_name="Canonical", tag_line="1115"
    )

    assert result.puuid == cached.puuid
    assert result.profile_icon is not None
    assert fake_riot_gateway.calls == []
```

Add tests for cache miss Account+Summoner calls, canonical Riot ID persistence, independent numeric tag line, `get_by_puuid` cache miss through Account-by-PUUID, upstream failures not being cached, and structured hit/miss logs containing only the hashed player reference.

- [ ] **Step 3: Run focused tests and observe failure**

Run:

```bash
cd backend
.venv/bin/pytest tests/test_riot_gateway.py tests/test_player_service.py -v
```

Expected: the by-PUUID gateway and player service tests fail because the interfaces are missing.

- [ ] **Step 4: Implement the player service with deterministic keys and clock**

```python
from datetime import UTC, datetime, timedelta
from unicodedata import normalize


def lookup_key(value: str) -> str:
    return normalize("NFKC", value.strip()).casefold()


class PlayerService:
    def __init__(
        self,
        *,
        repository,
        gateway,
        static_resolver,
        cache_ttl_seconds: int,
        clock=None,
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._static_resolver = static_resolver
        self._cache_ttl_seconds = cache_ttl_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    async def resolve(
        self, *, platform: Platform, game_name: str, tag_line: str
    ) -> PlayerProfile:
        now = self._clock()
        cached = await self._repository.get_by_riot_id(
            platform=platform,
            game_name_key=lookup_key(game_name),
            tag_line_key=lookup_key(tag_line),
            fresh_after=now - timedelta(seconds=self._cache_ttl_seconds),
        )
        if cached is not None:
            return await self._static_resolver.hydrate_player(cached)
        account = await self._gateway.get_account_by_riot_id(
            platform=platform, game_name=game_name.strip(), tag_line=tag_line.strip()
        )
        summoner = await self._gateway.get_summoner_by_puuid(
            platform=platform, puuid=account.puuid
        )
        profile = normalize_player(account, summoner, platform)
        await self._repository.upsert(profile, fetched_at=now)
        return await self._static_resolver.hydrate_player(profile)
```

`get_by_puuid` follows the same cache-first rule and refreshes through `get_account_by_puuid` plus Summoner-V4. Both methods always return `PlayerView`; a Data Dragon failure degrades only `profile_icon` and never turns successful Riot identity resolution into an error.

- [ ] **Step 5: Write failing API validation and response tests**

```python
# backend/tests/test_player_api.py
def test_resolve_player_accepts_tag_line_unrelated_to_platform(player_client) -> None:
    response = player_client.get(
        "/api/v1/players/resolve",
        params={"platform": "NA1", "game_name": "PlayerName", "tag_line": "1115"},
    )

    assert response.status_code == 200
    assert response.json()["player"]["tag_line"] == "1115"
    assert response.json()["player"]["platform"] == "NA1"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_resolve_player_rejects_overlong_input_before_service_call(player_client) -> None:
    response = player_client.get(
        "/api/v1/players/resolve",
        params={"platform": "NA1", "game_name": "x" * 33, "tag_line": "1115"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_RIOT_ID"
```

Add Unicode, whitespace trimming, empty values, unsupported platform, safe Riot error passthrough, CORS, and request-ID tests.

- [ ] **Step 6: Implement AppServices, route dependency, lifecycle, and player route**

At the end of Task 5, `AppServices` owns `player_service` plus a tuple of async closers. `build_services(settings, database)` creates the Riot client/gateway, Data Dragon client/resolver, SQL player repository, and `PlayerService`, then stores only the service-facing interface and closers in the container. Task 6 reuses the resolver and adds recent-match/match repositories plus `match_service` without changing the player route. Tests inject a fake `AppServices` into `create_app(settings, database, services)`.

The route signature is:

```python
@router.get("/api/v1/players/resolve", response_model=ResolvePlayerResponse)
async def resolve_player(
    request: Request,
    platform: Platform,
    game_name: str,
    tag_line: str,
    services: Annotated[AppServices, Depends(get_services)],
) -> ResolvePlayerResponse:
    normalized_game_name, normalized_tag_line = validate_riot_id(game_name, tag_line)
    profile = await services.player_service.resolve(
        platform=platform,
        game_name=normalized_game_name,
        tag_line=normalized_tag_line,
    )
    return ResolvePlayerResponse(player=profile, request_id=request.state.request_id)
```

`validate_riot_id` trims both fields, counts Unicode code points with Python `len`, and raises HTTP 422 `INVALID_RIOT_ID` unless the trimmed lengths are respectively `1..32` and `1..16`. Missing query parameters may still use the global `VALIDATION_ERROR`; present but invalid Riot ID values use the more specific stable code. The test fixture asserts the player service was not called.

Register the router in `create_app`. Add `RIOT_API_KEY: ${RIOT_API_KEY:-}` to the Compose backend environment; never add it to the frontend build arguments or environment. Add the Task 2 yield dependency to bind `request.state.request_id` and `request.scope["route"].path` into `SafeRequestContext` for the duration of every Phase 2 API operation, then reset the `ContextVar` in `finally`. In lifespan shutdown, close `AppServices` first and the database second, the reverse of construction order; tests assert each closes exactly once. Existing health fixtures inject fake services so health tests never create real network clients.

- [ ] **Step 7: Run focused and backend regression checks**

Run:

```bash
cd backend
.venv/bin/pytest tests/test_riot_gateway.py tests/test_player_service.py tests/test_player_api.py -v
.venv/bin/pytest -m "not integration" -v
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy
```

Expected: all checks pass without network or PostgreSQL access.

- [ ] **Step 8: Commit Task 5**

```bash
git add backend/app/core/dependencies.py backend/app/services/riot/gateway.py backend/app/services/players.py backend/app/api/players.py backend/app/main.py backend/tests docker-compose.yml
git commit -m "feat: resolve Riot players through cached API"
```

---

### Task 6: Recent Matches, Match Detail, Bounded Fetching, and Static Hydration APIs

**Files:**
- Create: `backend/app/services/matches.py`
- Create: `backend/app/api/matches.py`
- Create: `backend/tests/test_match_service.py`
- Create: `backend/tests/test_match_api.py`
- Modify: `backend/app/api/players.py`
- Modify: `backend/app/core/dependencies.py`
- Modify: `backend/app/schemas/players.py`
- Modify: `backend/app/schemas/matches.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/conftest.py`

**Interfaces:**
- Consumes: player service, Riot gateway, normalizer, static resolver, and three repositories.
- Produces: `MatchService.list_recent(platform, puuid, count, locale) -> RecentMatchesData`.
- Produces: `MatchService.get_detail(platform, match_id, puuid, locale) -> MatchDetailData`.
- Produces: `GET /api/v1/players/{puuid}/matches` and `GET /api/v1/matches/{match_id}`.
- Guarantees at most four simultaneous missing-detail Riot requests and preserves input Match ID order.

- [ ] **Step 1: Write failing recent-match orchestration tests**

```python
# backend/tests/test_match_service.py
import pytest

from app.core.routing import Platform
from app.schemas.domain import Locale
from app.services.matches import MatchService


@pytest.mark.asyncio
async def test_recent_matches_preserve_riot_order_and_mark_supported_queues(
    match_service_dependencies,
) -> None:
    deps = match_service_dependencies
    deps.riot_gateway.match_ids = ("NA1_3", "NA1_2", "NA1_1")
    deps.riot_gateway.matches = {
        "NA1_3": deps.match_dto("NA1_3", queue_id=420),
        "NA1_2": deps.match_dto("NA1_2", queue_id=450),
        "NA1_1": deps.match_dto("NA1_1", queue_id=400),
    }
    service = MatchService(
        player_service=deps.player_service,
        gateway=deps.riot_gateway,
        recent_repository=deps.recent_repository,
        match_repository=deps.match_repository,
        static_resolver=deps.static_resolver,
        recent_cache_ttl_seconds=120,
        match_retention_days=30,
        max_concurrency=4,
        clock=deps.clock,
    )

    result = await service.list_recent(
        platform=Platform.NA1,
        puuid="selected-puuid",
        count=10,
        locale=Locale.EN_US,
    )

    assert [item.match_id for item in result.matches] == ["NA1_3", "NA1_2", "NA1_1"]
    assert [item.analysis_supported for item in result.matches] == [True, False, True]
    assert result.matches[1].unsupported_reason_code == "UNSUPPORTED_QUEUE"
```

Add tests for fewer than ten IDs, two-minute recent-ID cache hit, completed-match cache reuse inside the 30-day retention boundary, stale-match refetch plus expired-row cleanup, at-most-four concurrent gateway calls measured by a fake counter, participant-not-found failure, a non-10-player mode remaining visible with `detail_supported=false`, structured cache logs with no full PUUID, and degraded static data preserving numeric fields.

- [ ] **Step 2: Write failing match-detail service tests**

```python
@pytest.mark.asyncio
async def test_match_detail_returns_two_teams_and_replay_binding_metadata(
    match_service_dependencies,
) -> None:
    deps = match_service_dependencies
    service = MatchService(
        player_service=deps.player_service,
        gateway=deps.riot_gateway,
        recent_repository=deps.recent_repository,
        match_repository=deps.match_repository,
        static_resolver=deps.static_resolver,
        recent_cache_ttl_seconds=120,
        match_retention_days=30,
        max_concurrency=4,
        clock=deps.clock,
    )

    result = await service.get_detail(
        platform=Platform.NA1,
        match_id="NA1_123456789",
        puuid="selected-puuid",
        locale=Locale.ZH_CN,
    )

    assert len(result.blue_team) == 5
    assert len(result.red_team) == 5
    assert result.selected_puuid == "selected-puuid"
    assert result.game_version == "16.15.602.1234"
    assert result.scope_notice_code == "DATA_ONLY_NO_COACHING"
```

- [ ] **Step 3: Run service tests and observe failure**

Run:

```bash
cd backend
.venv/bin/pytest tests/test_match_service.py -v
```

Expected: collection fails because `MatchService` does not exist.

- [ ] **Step 4: Implement cached loading and bounded concurrency**

Use `asyncio.Semaphore` and `asyncio.gather`, whose result order matches input order:

```python
async def _load_missing_match(self, platform: Platform, match_id: str) -> MatchSnapshot:
    now = self._clock()
    retention_boundary = now - timedelta(days=self._match_retention_days)
    cached = await self._match_repository.get(
        platform=platform,
        match_id=match_id,
        fresh_after=retention_boundary,
    )
    if cached is not None:
        return cached
    async with self._semaphore:
        dto = await self._gateway.get_match(platform=platform, match_id=match_id)
    snapshot = normalize_match(dto, platform)
    await self._match_repository.put(snapshot, fetched_at=now)
    await self._match_repository.delete_expired(before=retention_boundary)
    return snapshot


async def _load_matches(
    self, platform: Platform, match_ids: tuple[str, ...]
) -> tuple[MatchSnapshot, ...]:
    loaded = await asyncio.gather(
        *(self._load_missing_match(platform, match_id) for match_id in match_ids)
    )
    return tuple(loaded)
```

`list_recent` first obtains a fresh profile via `PlayerService.get_by_puuid`, then recent IDs from cache or Match-V5. Store an empty returned tuple with the normal two-minute expiry so repeated empty histories do not hammer Riot. Hydrate each match for the requested locale through the static resolver.

`get_detail` loads one match, raises HTTP 404 `PLAYER_NOT_IN_MATCH` when the PUUID is absent, and raises HTTP 422 `MATCH_DETAIL_UNSUPPORTED_MODE` when `supports_standard_detail` is false. Otherwise it separates team IDs `100` and `200` into two five-player teams. This is independent of `analysis_supported`: for example, a normal 5v5 ARAM may have details while still being marked unsupported for future coaching.

- [ ] **Step 5: Write failing API contract and safe-error tests**

```python
# backend/tests/test_match_api.py
def test_recent_match_api_returns_player_and_ordered_matches(match_client) -> None:
    response = match_client.get(
        "/api/v1/players/selected-puuid/matches",
        params={"platform": "NA1", "count": 10, "locale": "en-US"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["player"]["puuid"] == "selected-puuid"
    assert len(body["matches"]) == 3
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_match_api_rejects_player_not_in_match_with_unified_envelope(match_client) -> None:
    response = match_client.get(
        "/api/v1/matches/NA1_123456789",
        params={"platform": "NA1", "puuid": "absent", "locale": "zh-CN"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PLAYER_NOT_IN_MATCH"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
```

Add query bound tests for `count=0`, `count=11`, invalid locale, invalid platform, match not found, unsupported nonstandard detail, Riot rate limit, static degraded success, CORS, and no upstream body leakage.

- [ ] **Step 6: Add routes and response hydration**

Route signatures are:

```python
@router.get("/api/v1/players/{puuid}/matches", response_model=RecentMatchesResponse)
async def recent_matches(
    request: Request,
    puuid: Annotated[str, Path(min_length=1, max_length=128)],
    services: Annotated[AppServices, Depends(get_services)],
    platform: Platform,
    count: Annotated[int, Query(ge=1, le=10)] = 10,
    locale: Locale = Locale.EN_US,
) -> RecentMatchesResponse:
    data = await services.match_service.list_recent(
        platform=platform, puuid=puuid, count=count, locale=locale
    )
    return RecentMatchesResponse(**data.model_dump(), request_id=request.state.request_id)
```

```python
@router.get("/api/v1/matches/{match_id}", response_model=MatchDetailResponse)
async def match_detail(
    request: Request,
    match_id: Annotated[str, Path(min_length=1, max_length=64)],
    services: Annotated[AppServices, Depends(get_services)],
    platform: Platform,
    puuid: Annotated[str, Query(min_length=1, max_length=128)],
    locale: Locale = Locale.EN_US,
) -> MatchDetailResponse:
    data = await services.match_service.get_detail(
        platform=platform, match_id=match_id, puuid=puuid, locale=locale
    )
    return MatchDetailResponse(**data.model_dump(), request_id=request.state.request_id)
```

Extend `AppServices` with `match_service`. `build_services` passes `Settings.recent_matches_cache_ttl_seconds`, `Settings.match_retention_days`, and `Settings.riot_max_concurrency` into the exact constructor shown in the service tests.

- [ ] **Step 7: Run backend verification**

Run:

```bash
cd backend
.venv/bin/pytest tests/test_match_service.py tests/test_match_api.py -v
.venv/bin/pytest -m "not integration" -v
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy
```

Expected: all tests and checks pass; fake concurrency never exceeds four.

- [ ] **Step 8: Commit Task 6**

```bash
git add backend/app/services/matches.py backend/app/api backend/app/core/dependencies.py backend/app/schemas backend/app/main.py backend/tests
git commit -m "feat: expose cached Riot match APIs"
```

---

### Task 7: Runtime-Validated Frontend Client, Active Search, and Player Page

**Files:**
- Create: `frontend/src/api/schemas.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/components/data-state.tsx`
- Create: `frontend/src/components/player-header.tsx`
- Create: `frontend/src/components/recent-match-card.tsx`
- Create: `frontend/src/components/recent-match-list.tsx`
- Create: `frontend/src/components/player-page-client.tsx`
- Create: `frontend/src/app/[locale]/players/[puuid]/page.tsx`
- Create: `frontend/tests/api-client.test.ts`
- Create: `frontend/tests/player-page.test.tsx`
- Modify: `frontend/package.json`
- Modify: `frontend/pnpm-lock.yaml`
- Modify: `frontend/src/components/riot-search-form.tsx:1-36`
- Modify: `frontend/src/app/[locale]/page.tsx`
- Modify: `frontend/src/i18n/en-US.ts`
- Modify: `frontend/src/i18n/zh-CN.ts`
- Modify: `frontend/tests/riot-search-form.test.tsx`

**Interfaces:**
- Consumes: Task 5 and 6 public JSON contracts.
- Produces Zod schemas and inferred types `PlayerProfile`, `RecentMatchItem`, `RecentMatchesResponse`, and `MatchDetailResponse`.
- Produces `resolvePlayer`, `getRecentMatches`, and `getMatchDetail` in `src/api/client.ts`.
- Produces a functional `RiotSearchForm({locale, messages})` and localized player route.
- Error UI consumes only stable backend error codes and safe parameters.

- [ ] **Step 1: Add Zod without raising the Node floor**

Run:

```bash
cd frontend
pnpm add zod@4
pnpm install --frozen-lockfile
```

Inspect `pnpm-lock.yaml` engine metadata and confirm Zod plus all direct frontend dependencies still allow Node `20.9.0`. Do not change the `engines.node` value.

- [ ] **Step 2: Write failing API-client validation tests**

```typescript
// frontend/tests/api-client.test.ts
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiClientError, resolvePlayer } from "@/api/client";

afterEach(() => vi.unstubAllGlobals());

describe("API client", () => {
  it("accepts a normalized player response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            player: {
              puuid: "puuid-1",
              game_name: "PlayerName",
              tag_line: "1115",
              platform: "NA1",
              summoner_level: 772,
              profile_icon_id: 29,
              profile_icon: {
                entity_id: 29,
                name: "Profile icon",
                image_url:
                  "https://ddragon.leagueoflegends.com/cdn/16.15.1/img/profileicon/29.png",
              },
              profile_static_data_status: {
                available: true,
                version: "16.15.1",
                code: null,
              },
            },
            request_id: "request-1",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    const result = await resolvePlayer({
      platform: "NA1",
      gameName: "PlayerName",
      tagLine: "1115",
    });

    expect(result.player.tag_line).toBe("1115");
  });

  it("rejects a successful response that violates the runtime schema", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ player: { puuid: 12 } }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(
      resolvePlayer({ platform: "NA1", gameName: "PlayerName", tagLine: "1115" }),
    ).rejects.toMatchObject({ code: "INVALID_API_RESPONSE" });
  });

  it("preserves a safe backend code and request ID", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "RIOT_RATE_LIMITED",
              message: "Riot API rate limit reached.",
              params: { retry_after_seconds: 12 },
              retryable: true,
              request_id: "request-2",
            },
          }),
          { status: 429, headers: { "X-Request-ID": "request-2" } },
        ),
      ),
    );

    await expect(
      resolvePlayer({ platform: "NA1", gameName: "PlayerName", tagLine: "1115" }),
    ).rejects.toBeInstanceOf(ApiClientError);
  });
});
```

- [ ] **Step 3: Run the client tests and observe failure**

Run:

```bash
cd frontend
pnpm test -- tests/api-client.test.ts
```

Expected: test collection fails because `@/api/client` does not exist.

- [ ] **Step 4: Implement the exact runtime schemas and safe fetch wrapper**

`schemas.ts` defines closed locale/platform enums, shared static status/asset schemas, player, recent match, hydrated participant, team, match detail, and error envelope schemas. Required top-level schemas must use `.strict()` so accidental upstream pass-through fields fail tests.

The request core is:

```typescript
// frontend/src/api/client.ts
import type { z } from "zod";

import {
  errorResponseSchema,
  matchDetailResponseSchema,
  recentMatchesResponseSchema,
  resolvePlayerResponseSchema,
} from "@/api/schemas";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiClientError extends Error {
  constructor(
    readonly code: string,
    readonly params: Record<string, unknown>,
    readonly retryable: boolean,
    readonly requestId: string | null,
  ) {
    super(code);
  }
}

async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    headers: { Accept: "application/json" },
    signal,
  });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const parsed = errorResponseSchema.safeParse(body);
    if (!parsed.success) {
      throw new ApiClientError(
        "INVALID_API_RESPONSE",
        {},
        true,
        response.headers.get("X-Request-ID"),
      );
    }
    throw new ApiClientError(
      parsed.data.error.code,
      parsed.data.error.params,
      parsed.data.error.retryable,
      parsed.data.error.request_id,
    );
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success) {
    throw new ApiClientError(
      "INVALID_API_RESPONSE",
      {},
      true,
      response.headers.get("X-Request-ID"),
    );
  }
  return parsed.data;
}
```

Build all query strings with `URLSearchParams`. Export exact operations:

```typescript
export type ResolvePlayerInput = {
  platform: "NA1";
  gameName: string;
  tagLine: string;
};

export async function resolvePlayer(
  input: ResolvePlayerInput,
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({
    platform: input.platform,
    game_name: input.gameName,
    tag_line: input.tagLine,
  });
  return request(
    `/api/v1/players/resolve?${query}`,
    resolvePlayerResponseSchema,
    signal,
  );
}
```

Implement `getRecentMatches(input, signal?: AbortSignal)` and `getMatchDetail(input, signal?: AbortSignal)` in the same style, where inputs respectively contain `{puuid, platform, locale, count}` and `{matchId, puuid, platform, locale}`. Every page effect passes its `AbortController.signal`; the search form may omit the optional signal.

- [ ] **Step 5: Write failing functional-search tests**

Replace the Phase 1 local-submit expectation with:

```typescript
vi.mock("@/api/client", () => ({
  resolvePlayer: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

it("resolves an independent tag line and navigates to the localized player page", async () => {
  vi.mocked(resolvePlayer).mockResolvedValue({
    player: {
      puuid: "puuid-1",
      game_name: "PlayerName",
      tag_line: "1115",
      platform: "NA1",
      summoner_level: 772,
      profile_icon_id: 29,
      profile_icon: {
        entity_id: 29,
        name: "Profile icon",
        image_url:
          "https://ddragon.leagueoflegends.com/cdn/16.15.1/img/profileicon/29.png",
      },
      profile_static_data_status: {
        available: true,
        version: "16.15.1",
        code: null,
      },
    },
    request_id: "request-1",
  });
  const user = userEvent.setup();
  render(<RiotSearchForm locale="en-US" messages={getMessages("en-US")} />);

  await user.type(screen.getByLabelText("Game Name"), "PlayerName");
  await user.type(screen.getByLabelText("Tag Line"), "1115");
  await user.click(screen.getByRole("button", { name: "Search" }));

  expect(resolvePlayer).toHaveBeenCalledWith({
    platform: "NA1",
    gameName: "PlayerName",
    tagLine: "1115",
  });
  expect(pushMock).toHaveBeenCalledWith("/en-US/players/puuid-1?platform=NA1");
});
```

Add tests for Unicode input, trimming, disabled submit/loading copy, player not found, rate-limit retry text, and a tag line up to 16 characters. Update examples so neither locale suggests `#NA1` is required.

- [ ] **Step 6: Implement the active search form**

Use `FormData`, trim both values, set a discriminated state (`idle | loading | error`), call `resolvePlayer`, and navigate with `encodeURIComponent(puuid)`. Do not place game name/tag line in the destination URL. Render localized error text by stable code and include the safe request ID in a collapsible support detail, not the upstream fallback message as primary copy.

- [ ] **Step 7: Write failing player-page tests**

```typescript
// frontend/tests/player-page.test.tsx
it("renders the canonical Riot ID and ordered recent matches", async () => {
  vi.mocked(getRecentMatches).mockResolvedValue(recentMatchesFixture);
  render(<PlayerPageClient locale="zh-CN" puuid="puuid-1" platform="NA1" />);

  expect(await screen.findByRole("heading", { name: "PlayerName#1115" })).toBeVisible();
  const cards = screen.getAllByTestId("recent-match-card");
  expect(cards).toHaveLength(3);
  expect(cards[0]).toHaveTextContent("NA1_3");
  expect(screen.getByText("暂不支持复盘")).toBeVisible();
});
```

Add loading, empty, retry, static-data warning, localized asset, and match-link tests. Prove that a standard-detail card has a link and a nonstandard card with `detail_supported=false` remains visible but has no link.

- [ ] **Step 8: Implement player components and route**

The route validates `locale` with existing `isLocale`, reads `puuid` and `platform`, and renders `PlayerPageClient`. The client fetches once per `(puuid, platform, locale)` and cancels stale updates with an `AbortController` passed through the API client.

Each card with `detail_supported=true` links to:

```text
/{locale}/matches/{encoded_match_id}?platform=NA1&puuid={encoded_puuid}
```

When `detail_supported=false`, render a localized `detail_unavailable_reason_code` instead of an anchor. Use `<time dateTime>` for match time, text plus color for win/loss, real image alternatives, and a visible unsupported queue reason.

- [ ] **Step 9: Run frontend verification**

Run:

```bash
cd frontend
pnpm test
pnpm lint
pnpm typecheck
pnpm build
```

Expected: all frontend tests and production build pass with no Phase 1 temporary notice.

- [ ] **Step 10: Commit Task 7**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/src/api frontend/src/components frontend/src/app frontend/src/i18n frontend/tests
git commit -m "feat: add real Riot player search flow"
```

---

### Task 8: Match Detail Page, Complete States, Accessibility, and Responsive Layout

**Files:**
- Create: `frontend/src/components/match-team-table.tsx`
- Create: `frontend/src/components/match-detail-client.tsx`
- Create: `frontend/src/app/[locale]/matches/[matchId]/page.tsx`
- Create: `frontend/tests/match-detail-page.test.tsx`
- Create: `frontend/tests/data-state.test.tsx`
- Modify: `frontend/src/components/data-state.tsx`
- Modify: `frontend/src/api/schemas.ts`
- Modify: `frontend/src/i18n/en-US.ts`
- Modify: `frontend/src/i18n/zh-CN.ts`
- Modify: `frontend/src/app/globals.css`

**Interfaces:**
- Consumes: `getMatchDetail`, `MatchDetailResponse`, existing locale catalogs, and Task 7 state components.
- Produces: localized match detail with two teams, selected-player identification, data sufficiency, and an explicit data-only capability notice.
- Produces no active analysis/review action and no coaching copy.

- [ ] **Step 1: Write failing match-detail rendering tests**

```typescript
// frontend/tests/match-detail-page.test.tsx
it("renders two five-player teams and identifies the selected player", async () => {
  vi.mocked(getMatchDetail).mockResolvedValue(matchDetailFixture);
  render(
    <MatchDetailClient
      locale="en-US"
      matchId="NA1_123456789"
      puuid="selected-puuid"
      platform="NA1"
    />,
  );

  expect(await screen.findByRole("heading", { name: /match details/i })).toBeVisible();
  expect(screen.getAllByRole("row")).toHaveLength(12);
  expect(screen.getByText("Selected player").closest("tr")).toHaveAttribute(
    "data-selected",
    "true",
  );
  expect(screen.getByText(/recorded match data only/i)).toBeVisible();
  expect(screen.queryByRole("button", { name: /generate review/i })).not.toBeInTheDocument();
});

it("keeps numeric data visible when static data is unavailable", async () => {
  vi.mocked(getMatchDetail).mockResolvedValue(degradedMatchDetailFixture);
  render(
    <MatchDetailClient
      locale="zh-CN"
      matchId="NA1_123456789"
      puuid="selected-puuid"
      platform="NA1"
    />,
  );

  expect(await screen.findByText("静态资料暂时不可用")).toBeVisible();
  expect(screen.getByText("7 / 3 / 8")).toBeVisible();
});
```

The expected row count includes two header rows plus ten participant rows. Add tests for loading, API error, retry, missing selected player, localized item/champion names, meaningful image alt text, and request-ID support detail.

- [ ] **Step 2: Run focused tests and observe failure**

Run:

```bash
cd frontend
pnpm test -- tests/match-detail-page.test.tsx tests/data-state.test.tsx
```

Expected: tests fail because the match-detail route and components do not exist.

- [ ] **Step 3: Implement the match-detail request lifecycle**

`MatchDetailClient` uses the same explicit request-state union as the player page:

```typescript
type RequestState<T> =
  | { status: "loading" }
  | { status: "success"; data: T }
  | { status: "empty" }
  | { status: "error"; error: ApiClientError };
```

It calls `getMatchDetail` for `(matchId, puuid, platform, locale)`, cancels stale requests, and passes retry as an explicit incrementing attempt key. It never infers coaching quality from numeric fields.

- [ ] **Step 4: Implement accessible team tables and capability notice**

Render one `<table>` per team with `<caption>`, column headers, and five body rows. Columns are player identity, champion, role, K/D/A, CS, gold, champion damage, vision, and items. Use `aria-current="true"` and visible localized text on the selected player's row; do not rely on color alone.

When `static_data_status.available` is false, render IDs or localized unknown labels and keep numeric columns. Always render localized `DATA_ONLY_NO_COACHING` copy explaining that positioning, mechanics, awareness, intent, and causality have not been evaluated.

- [ ] **Step 5: Complete bilingual state and error catalogs**

Both catalogs must define matching keys for:

```text
loadingPlayer, loadingMatches, loadingMatchDetail, noMatches,
playerNotFound, matchNotFound, playerNotInMatch, riotNotConfigured,
riotAuthFailed, riotRateLimited, riotUnavailable, riotRequestInvalid, invalidApiResponse,
staticDataUnavailable, retry, requestId, selectedPlayer,
blueTeam, redTeam, matchDetails, unsupportedQueue,
dataOnlyScopeNotice, unknownChampion, unknownItem
unknownStatistic, matchDetailUnsupportedMode, detailUnavailable
```

Rate-limit copy interpolates `retry_after_seconds` only when it is a finite non-negative number. Unknown codes use a localized generic message and the request ID.

- [ ] **Step 6: Add responsive, intentional styles**

Extend `globals.css` with existing color tokens and typography. At narrow widths, team tables use a labelled horizontal scroll region rather than hiding columns. Keep touch targets at least 44 CSS pixels, maintain visible keyboard focus, and ensure selected/win/loss states include text or icons with accessible names.

- [ ] **Step 7: Run all frontend and repository-wide non-Docker checks**

Run:

```bash
cd frontend
pnpm test
pnpm lint
pnpm typecheck
pnpm build
cd ..
make verify
git diff --check
```

Expected: all tests and checks pass; both localized static routes compile.

- [ ] **Step 8: Commit Task 8**

```bash
git add frontend/src/components frontend/src/app frontend/src/api/schemas.ts frontend/src/i18n frontend/src/app/globals.css frontend/tests
git commit -m "feat: add bilingual Riot match detail"
```

---

### Task 9: Live Riot Smoke Flow, Documentation, Final CI Evidence, and Phase 2 Acceptance

**Files:**
- Create: `backend/app/services/riot/smoke.py`
- Create: `scripts/smoke_riot.py`
- Create: `backend/tests/test_smoke_script.py`
- Modify: `backend/app/core/config.py`
- Modify: `.env.example`
- Modify: `Makefile`
- Modify: `README.md`
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/verify.sh`

**Interfaces:**
- Consumes: all Phase 2 APIs and commands.
- Produces: `make smoke-riot`, which calls a running local backend without printing the Riot ID or API key.
- Produces: final bilingual setup/boundary documentation and recorded verification limits.
- Does not automate a development key in CI.

- [ ] **Step 1: Write failing smoke-script safety tests**

```python
# backend/tests/test_smoke_script.py
from app.services.riot.smoke import run_smoke


def test_smoke_reports_counts_without_printing_identifier_or_key(fake_smoke_client, capsys) -> None:
    run_smoke(
        client=fake_smoke_client,
        api_base_url="http://localhost:8000",
        game_name="Secret Player",
        tag_line="1115",
        platform="NA1",
    )

    output = capsys.readouterr().out
    assert "Phase 2 Riot smoke passed" in output
    assert "matches=3" in output
    assert "Secret Player" not in output
    assert "1115" not in output
    assert "RGAPI" not in output
```

Add tests for missing smoke variables, no recent matches, failed player resolution, failed match detail, both locales, and repeat-request execution.

- [ ] **Step 2: Run the smoke tests and observe failure**

Run:

```bash
cd backend
.venv/bin/pytest tests/test_smoke_script.py -v
```

Expected: import fails because `app.services.riot.smoke` does not exist.

- [ ] **Step 3: Implement a local-API smoke script**

Add settings with safe defaults:

```python
riot_smoke_game_name: str = ""
riot_smoke_tag_line: str = ""
riot_smoke_platform: str = "NA1"
smoke_api_base_url: str = "http://localhost:8000"
```

Put the tested orchestration in `backend/app/services/riot/smoke.py`; keep `scripts/smoke_riot.py` as a thin CLI adapter that loads settings, creates `httpx2.Client`, calls `run_smoke`, and converts safe failures to a non-zero exit. The orchestration calls the already-running backend:

```python
def run_smoke(*, client, api_base_url: str, game_name: str, tag_line: str, platform: str) -> None:
    resolved = client.get(
        f"{api_base_url}/api/v1/players/resolve",
        params={"platform": platform, "game_name": game_name, "tag_line": tag_line},
    )
    resolved.raise_for_status()
    puuid = resolved.json()["player"]["puuid"]
    recent = client.get(
        f"{api_base_url}/api/v1/players/{puuid}/matches",
        params={"platform": platform, "count": 10, "locale": "en-US"},
    )
    recent.raise_for_status()
    matches = recent.json()["matches"]
    if not matches:
        raise RuntimeError("The smoke account has no recent matches")
    detail_match = next(
        (match for match in matches if match["detail_supported"]),
        None,
    )
    if detail_match is None:
        raise RuntimeError("The smoke account has no standard detail-supported match")
    match_id = detail_match["match_id"]
    for locale in ("en-US", "zh-CN"):
        detail = client.get(
            f"{api_base_url}/api/v1/matches/{match_id}",
            params={"platform": platform, "puuid": puuid, "locale": locale},
        )
        detail.raise_for_status()
    repeat = client.get(
        f"{api_base_url}/api/v1/players/{puuid}/matches",
        params={"platform": platform, "count": 10, "locale": "en-US"},
    )
    repeat.raise_for_status()
    print(f"Phase 2 Riot smoke passed: matches={len(matches)} locales=2 repeat=ok")
```

The CLI loads ignored root `.env` through `Settings`, refuses empty smoke identity fields or an unconfigured Riot key, and never prints exception request bodies. On failure it prints only the stable backend code and request ID, then exits non-zero.

- [ ] **Step 4: Add the smoke command and empty variables**

Append only empty/default-safe values to `.env.example`:

```dotenv
RIOT_SMOKE_GAME_NAME=
RIOT_SMOKE_TAG_LINE=
RIOT_SMOKE_PLATFORM=NA1
SMOKE_API_BASE_URL=http://localhost:8000
```

Add:

```make
smoke-riot:
	PYTHONPATH=backend backend/.venv/bin/python scripts/smoke_riot.py
```

Do not copy the user's real Riot ID or key into tracked files.

- [ ] **Step 5: Update the bilingual README with exact Phase 2 truth**

Document:

- Functional Riot ID search, player page, recent matches, and detail page.
- Independent tag line and platform with a generic numeric-tag example.
- Local `DATABASE_URL` versus `COMPOSE_DATABASE_URL`.
- Alembic migration command.
- `make verify`, `make verify-postgres`, and `make smoke-riot` prerequisites and meanings.
- Development-key 24-hour expiry and server-only handling.
- PostgreSQL/Docker verification evidence, distinguishing passed, failed, and unavailable.
- Data Dragon locale/version behavior and degraded state.
- Exact Phase 2 boundary: no Timeline, scoring, AI, behavioral judgment, OP.GG dependency, or replay processing.
- Next phase: authorized replay upload and timestamped frame evidence; public/purchased video is not ingested without permission; AI-proposed rules require human approval.

- [ ] **Step 6: Run all automated acceptance gates**

Run:

```bash
make verify
make verify-postgres
git diff --check
git status --short
```

Expected: non-Docker and PostgreSQL gates exit zero; whitespace check is clean; status lists only Task 9 files before commit. If PostgreSQL remains unavailable locally, obtain a green CI PostgreSQL job before declaring Phase 2 complete.

- [ ] **Step 7: Run the live Riot smoke without exposing inputs**

With the backend and PostgreSQL running and ignored `.env` populated, run:

```bash
make smoke-riot
```

Expected output contains only a generic pass line such as `Phase 2 Riot smoke passed: matches=10 locales=2 repeat=ok`. It must not contain the Riot ID, PUUID, match ID, API key, raw response, or full URL.

- [ ] **Step 8: Perform browser acceptance in both locales**

Use the real browser against the running frontend and verify:

1. A real NA Riot ID whose tag line differs from `NA1` resolves.
2. Up to ten matches appear in newest-to-oldest order.
3. Supported and unsupported queues are visibly distinct.
4. A standard match shows ten participants and the selected player.
5. `zh-CN` and `en-US` show localized champion/item names.
6. A forced static-data failure preserves numeric data and shows a warning.
7. A forced Riot error shows localized safe copy and a request ID.
8. No page claims to have evaluated positioning, mechanics, awareness, intent, or causality.

Record screenshots or concise evidence notes without capturing the Riot key.

- [ ] **Step 9: Run the secret and boundary audit**

Run:

```bash
git grep -n "RGAPI-"
git grep -n -E "OP\.GG|timeline|generate review|生成复盘" -- backend frontend
git status --short --branch
```

Expected: no real key match. OP.GG/Timeline/review text appears only in explicit boundary or unsupported-state copy, never as an integration or active action. The worktree contains no raw upstream fixture dumps or real player identifier.

- [ ] **Step 10: Commit Task 9**

```bash
git add backend/app/services/riot/smoke.py scripts/smoke_riot.py backend/tests/test_smoke_script.py backend/app/core/config.py .env.example Makefile README.md .github/workflows/ci.yml scripts/verify.sh
git commit -m "docs: complete phase two Riot acceptance"
```

## Final Phase 2 Review Gate

Before integration, generate a full-branch review package and dispatch a fresh high-reasoning reviewer. The reviewer must compare the branch against `docs/superpowers/specs/2026-07-30-lol-ai-coach-phase-2-riot-integration-design.md` and this plan, inspect every task report, and run safe independent checks.

Critical/Important findings must be fixed and receive a scoped re-review. Final evidence must include:

- Exact backend and frontend test counts.
- Ruff, format, mypy, ESLint, TypeScript, and Next production-build results.
- Alembic and PostgreSQL repository integration results.
- Live Riot smoke result without identifiers or secrets.
- Browser acceptance in both locales.
- Docker Compose status stated as passed, failed, or unverified.
- `git diff --check` and clean worktree status.
- Confirmation that no Timeline, AI, scoring, OP.GG, replay, raw Riot response, or unauthorized video feature entered Phase 2.
