# Riot Platform Auto-Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a player enter only `game name#tag`, automatically determine every Riot League platform where the account exists, navigate directly when the result is unique, and ask the player to confirm only when multiple real candidates exist.

**Architecture:** Add a closed, typed Riot routing catalog; a PostgreSQL-backed platform-detection cache; and a `PlatformDetectionService` between the localized player-search API and the existing `PlayerService`. Account-V1 obtains the PUUID from one of four regional routes, then bounded Summoner-V4 probes determine platform candidates. The service fails closed on partial upstream failure, merges identical in-process requests, and returns a discriminated `resolved` or `confirmation_required` response. Existing player, match, and replay flows continue to carry an explicit platform.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy async, PostgreSQL/Alembic, httpx2, pytest, Next.js 16, React 19, TypeScript, Zod, Vitest/Testing Library, bilingual `zh-CN` and `en-US` messages.

## Global Constraints

- Implement only after the Replay R1 real-smoke closure plan is complete and green.
- The approved source of truth is `docs/superpowers/specs/2026-08-01-riot-platform-auto-detection-design.md`.
- The browser accepts one Riot ID field. Never add a free-text platform field or expose API hostnames.
- Keep `GET /api/v1/players/resolve` for one complete compatibility release; the new home page must not call it.
- Platform and regional hosts come only from the closed routing catalog. Never derive a hostname from user input.
- Preserve the data boundary `platform + puuid` for players, matches, replays, URLs, and cache keys.
- Fail closed: one unknown platform probe means the result is temporarily unavailable, not unique and not missing.
- Log no raw Riot ID, PUUID, API key, or upstream payload. Metrics may use outcome labels but no player identifiers.
- Preserve all Replay R1 behavior and tests.
- Use test-driven development and one focused commit per task.

---

## Task 1: Expand the closed Riot routing catalog and settings

**Files:**

- Modify: `backend/tests/test_routing.py`
- Modify: `backend/app/core/routing.py`
- Modify: `backend/tests/test_config.py`
- Modify: `backend/app/core/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Write failing routing-catalog tests**

Replace the old test that rejects EUW1 with table-driven assertions covering exactly these values:

```python
EXPECTED_REGIONS = {"AMERICAS", "ASIA", "EUROPE", "SEA"}
EXPECTED_PLATFORMS = {
    "BR1", "EUN1", "EUW1", "JP1", "KR", "LA1", "LA2", "NA1",
    "OC1", "TR1", "RU", "PH2", "SG2", "TH2", "TW2", "VN2",
}
```

Assert every platform has:

- a lowercase `*.api.riotgames.com` platform host;
- one valid `Region`;
- a regional host from the four-entry catalog;
- non-empty Chinese and English display names;
- a unique stable sort order.

Assert unknown values still fail enum parsing and no API accepts a raw hostname.

- [ ] **Step 2: Verify the routing tests fail**

```bash
cd backend
.venv/bin/pytest -q tests/test_routing.py
```

Expected: failures because the current catalog contains only NA1.

- [ ] **Step 3: Implement typed regions and all 16 platforms**

Use these public types in `app/core/routing.py`:

```python
class Region(StrEnum):
    AMERICAS = "AMERICAS"
    ASIA = "ASIA"
    EUROPE = "EUROPE"
    SEA = "SEA"


class Platform(StrEnum):
    BR1 = "BR1"
    EUN1 = "EUN1"
    EUW1 = "EUW1"
    JP1 = "JP1"
    KR = "KR"
    LA1 = "LA1"
    LA2 = "LA2"
    NA1 = "NA1"
    OC1 = "OC1"
    TR1 = "TR1"
    RU = "RU"
    PH2 = "PH2"
    SG2 = "SG2"
    TH2 = "TH2"
    TW2 = "TW2"
    VN2 = "VN2"
```

Retain `routes_for(platform)` compatibility. Extend `RiotRoutes` with `region`, `display_name_zh`, `display_name_en`, and `sort_order`; provide `regional_host` through the fixed `REGIONAL_HOSTS` mapping. Use the official route grouping from the approved design and Riot routing documentation. Add:

```python
def regional_host_for(region: Region) -> str: ...
def ordered_platforms() -> tuple[Platform, ...]: ...
def display_name_for(platform: Platform, locale: Locale) -> str: ...
```

To avoid importing the schema layer into core routing, define `display_name_for(platform, locale)` with `locale: Literal["zh-CN", "en-US"]`; API/service callers pass `Locale.value`.

Use this exact platform catalog and stable order:

| Order | Platform | Region | Platform host | Chinese | English |
| ---: | --- | --- | --- | --- | --- |
| 10 | BR1 | AMERICAS | `br1.api.riotgames.com` | 巴西服 | Brazil |
| 20 | EUN1 | EUROPE | `eun1.api.riotgames.com` | 欧东北服 | Europe Nordic & East |
| 30 | EUW1 | EUROPE | `euw1.api.riotgames.com` | 欧西服 | Europe West |
| 40 | JP1 | ASIA | `jp1.api.riotgames.com` | 日服 | Japan |
| 50 | KR | ASIA | `kr.api.riotgames.com` | 韩服 | Korea |
| 60 | LA1 | AMERICAS | `la1.api.riotgames.com` | 拉丁美洲北服 | Latin America North |
| 70 | LA2 | AMERICAS | `la2.api.riotgames.com` | 拉丁美洲南服 | Latin America South |
| 80 | NA1 | AMERICAS | `na1.api.riotgames.com` | 北美服 | North America |
| 90 | OC1 | SEA | `oc1.api.riotgames.com` | 大洋洲服 | Oceania |
| 100 | TR1 | EUROPE | `tr1.api.riotgames.com` | 土耳其服 | Türkiye |
| 110 | RU | EUROPE | `ru.api.riotgames.com` | 俄服 | Russia |
| 120 | PH2 | SEA | `ph2.api.riotgames.com` | 菲律宾服 | Philippines |
| 130 | SG2 | SEA | `sg2.api.riotgames.com` | 新加坡服 | Singapore |
| 140 | TH2 | SEA | `th2.api.riotgames.com` | 泰国服 | Thailand |
| 150 | TW2 | SEA | `tw2.api.riotgames.com` | 台服 | Taiwan |
| 160 | VN2 | SEA | `vn2.api.riotgames.com` | 越南服 | Vietnam |

- [ ] **Step 4: Add failing configuration tests**

Cover defaults and bounds for:

```text
RIOT_PLATFORM_DETECTION_ENABLED=false
RIOT_PLATFORM_DETECTION_TTL_SECONDS=86400
RIOT_PLATFORM_DETECTION_NOT_FOUND_TTL_SECONDS=300
RIOT_PLATFORM_CONFIRMATION_TTL_SECONDS=900
RIOT_ACCOUNT_PRIMARY_REGION=AMERICAS
```

Assert invalid region values fail settings validation. Assert TTLs must be positive and bounded to:

- detection TTL: 60 through 604800 seconds;
- not-found TTL: 30 through 3600 seconds;
- confirmation TTL: 60 through 3600 seconds.

The existing `riot_max_concurrency` remains the shared probe limit and must be at least 1 and at most 16.

- [ ] **Step 5: Implement and document settings**

Add typed fields to `Settings`, validate the numeric bounds, and add the same names and safe defaults to `.env.example`. The feature remains disabled until migrations and both clients are deployed.

- [ ] **Step 6: Run focused tests and commit**

```bash
cd backend
.venv/bin/pytest -q tests/test_routing.py tests/test_config.py
cd ..
git add backend/app/core/routing.py backend/app/core/config.py backend/tests/test_routing.py backend/tests/test_config.py .env.example
git commit -m "feat: add Riot platform routing catalog"
```

---

## Task 2: Migrate player identity and add detection persistence

**Files:**

- Create: `backend/alembic/versions/0003_player_platform_detection.py`
- Create: `backend/app/models/platform_detection.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/models/player.py`
- Create: `backend/app/repositories/platform_detections.py`
- Modify: `backend/app/repositories/__init__.py`
- Modify: `backend/app/repositories/players.py`
- Modify: `backend/tests/integration/test_migrations.py`
- Modify: `backend/tests/integration/test_repositories.py`
- Create: `backend/tests/integration/test_platform_detection_repository.py`

- [ ] **Step 1: Write failing migration and player-repository tests**

Add PostgreSQL tests proving:

1. upgrade from revision `0002` preserves every existing player row;
2. `players.puuid` is no longer globally unique;
3. `(platform, puuid)` is unique;
4. the same PUUID can be inserted for NA1 and EUW1;
5. upserting NA1 updates only the NA1 row;
6. downgrade restores the former constraint only when the data permits it;
7. upgrade to head and downgrade/upgrade round trip succeed on the normal fixture.

Update `test_player_repository_enforces_unique_puuid` to assert composite uniqueness instead of the obsolete global rule.

- [ ] **Step 2: Write failing detection-repository tests**

Define repository behavior with UTC-aware datetimes:

```python
class PlatformDetectionRepository(Protocol):
    async def get_fresh(
        self, *, game_name_key: str, tag_line_key: str, now: datetime
    ) -> PlatformDetectionRecord | None: ...

    async def get_for_confirmation(
        self, *, detection_id: UUID, now: datetime
    ) -> PlatformDetectionRecord | None: ...

    async def upsert(self, record: PlatformDetectionRecord) -> PlatformDetectionRecord: ...

    async def delete(self, *, detection_id: UUID) -> None: ...
```

Test resolved, ambiguous, and not-found records; expiry; confirmation expiry; candidate ordering; repeated upsert; concurrent upsert convergence; and delete.

- [ ] **Step 3: Verify integration tests fail before the migration**

```bash
export TEST_DATABASE_URL='postgresql+asyncpg://lol_ai_coach:lol_ai_coach@127.0.0.1:5432/lol_ai_coach_test'
make verify-postgres
```

Expected: missing revision/table and old unique-constraint failures.

- [ ] **Step 4: Add the detection model and migration**

Create `player_platform_detections` with the approved columns:

```text
id UUID primary key
game_name_key VARCHAR(128) not null
tag_line_key VARCHAR(64) not null
canonical_game_name VARCHAR(128) null
canonical_tag_line VARCHAR(64) null
puuid VARCHAR(128) null
result_status VARCHAR(16) not null
candidate_platforms JSONB not null
fetched_at TIMESTAMPTZ not null
expires_at TIMESTAMPTZ not null
confirmation_expires_at TIMESTAMPTZ null
created_at TIMESTAMPTZ not null
updated_at TIMESTAMPTZ not null
```

Add a unique constraint on `(game_name_key, tag_line_key)`, an expiry index, and database check constraints for the three result shapes. Candidate values also receive application-level enum validation because a portable SQL check cannot cleanly validate every JSON array member.

In the same migration:

- drop the existing unique constraint/index on `players.puuid` by its real reflected name;
- create a normal PUUID index if one does not remain;
- add `UNIQUE (platform, puuid)`;
- keep the existing platform index.

Use explicit Alembic operations with deterministic constraint names; do not rely on model `create_all`.

- [ ] **Step 5: Implement repository records and SQL operations**

Use immutable domain records:

```python
class DetectionStatus(StrEnum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class PlatformDetectionRecord:
    id: UUID
    game_name_key: str
    tag_line_key: str
    canonical_game_name: str | None
    canonical_tag_line: str | None
    puuid: str | None
    status: DetectionStatus
    candidate_platforms: tuple[Platform, ...]
    fetched_at: datetime
    expires_at: datetime
    confirmation_expires_at: datetime | None
```

Validate record shape at the domain boundary. Sort candidates by routing-catalog order before persistence. `get_fresh` requires `expires_at > now`; `get_for_confirmation` requires both cache and confirmation deadlines to be current.

Change player upsert to `index_elements=[PlayerRow.platform, PlayerRow.puuid]`.

- [ ] **Step 6: Run PostgreSQL tests and commit**

```bash
make verify-postgres
git add backend/alembic/versions/0003_player_platform_detection.py backend/app/models backend/app/repositories backend/tests/integration
git commit -m "feat: persist Riot platform detections"
```

---

## Task 3: Add region-aware Riot gateway operations

**Files:**

- Modify: `backend/app/services/riot/client.py`
- Modify: `backend/app/services/riot/gateway.py`
- Modify: `backend/tests/test_riot_client.py`
- Modify: `backend/tests/test_riot_gateway.py`

- [ ] **Step 1: Write failing allowlist and gateway tests**

Cover all platform and regional hosts. Assert a host absent from the catalog is rejected before any network request.

Add gateway tests for:

```python
async def get_account_by_riot_id_in_region(
    self, *, region: Region, game_name: str, tag_line: str
) -> AccountDto: ...
```

Verify correct percent-encoding, regional host choice, DTO validation, 404 mapping to `PLAYER_NOT_FOUND`, and propagation of authentication/rate-limit/unavailable errors.

- [ ] **Step 2: Verify focused tests fail**

```bash
cd backend
.venv/bin/pytest -q tests/test_riot_client.py tests/test_riot_gateway.py
```

- [ ] **Step 3: Expand the HTTP host allowlist safely**

Compute `_APPROVED_HOSTS` only from `REGIONAL_HOSTS` and the platform catalog. Do not add wildcard matching or accept a caller-provided URL.

- [ ] **Step 4: Implement the regional account method**

Use `regional_host_for(region)`. Keep `get_account_by_riot_id(platform=...)` as a compatibility wrapper that calls the new method using `routes_for(platform).region`. Existing `PlayerService` behavior must remain unchanged.

When probing Summoner-V4, reuse the existing `get_summoner_by_puuid(platform=...)`; the detector handles concurrency and classification.

- [ ] **Step 5: Run focused tests and commit**

```bash
cd backend
.venv/bin/pytest -q tests/test_riot_client.py tests/test_riot_gateway.py tests/test_player_service.py tests/test_match_service.py
cd ..
git add backend/app/services/riot backend/tests/test_riot_client.py backend/tests/test_riot_gateway.py
git commit -m "feat: support Riot regional account lookup"
```

---

## Task 4: Implement Riot ID parsing and platform detection service

**Files:**

- Create: `backend/app/services/platform_detection.py`
- Create: `backend/tests/test_platform_detection_service.py`
- Modify: `backend/app/services/parsing/players.py`
- Modify: `backend/tests/test_player_parsing.py`

- [ ] **Step 1: Add parser tests for the single-field Riot ID**

Add a pure parser:

```python
@dataclass(frozen=True)
class ParsedRiotId:
    game_name: str
    tag_line: str
    game_name_key: str
    tag_line_key: str


def parse_riot_id(value: str) -> ParsedRiotId: ...
```

Test trimming, Unicode, NFKC/casefold lookup keys, use of the final `#`, maximum lengths, empty sides, no separator, and overlength values. Invalid input raises `ApiError` code `INVALID_RIOT_ID` without calling a gateway.

- [ ] **Step 2: Define detector protocol and result types in tests**

Use service-layer result objects rather than API response models:

```python
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
```

Expose:

```python
class PlatformDetector(Protocol):
    async def detect(self, *, riot_id: str, locale: Locale) -> DetectionResult: ...
    async def confirm(
        self, *, detection_id: UUID, platform: Platform, locale: Locale
    ) -> ResolvedDetection: ...
```

- [ ] **Step 3: Write service tests for cache and classification**

Using fakes and an injected UTC clock, test:

1. valid resolved cache calls no Riot API and resolves the cached platform;
2. ambiguous cache returns localized ordered candidates and refreshes only the 15-minute confirmation window when needed;
3. not-found cache raises `PLAYER_NOT_FOUND`;
4. expired cache performs detection;
5. primary Account region succeeds and stops the regional sequence;
6. primary 404 falls through in fixed region order;
7. all four regional 404s cache not-found for 5 minutes;
8. any regional non-404 failure is propagated and not cached as missing;
9. zero successful platform probes caches not-found;
10. one candidate caches 24 hours and returns resolved;
11. multiple candidates cache 24 hours and return confirmation required;
12. invalid Summoner DTO or PUUID mismatch produces `RIOT_INVALID_RESPONSE`;
13. any exhausted 429/timeout/5xx produces `RIOT_PLATFORM_DETECTION_UNAVAILABLE` and writes no positive/negative result;
14. probe concurrency never exceeds `riot_max_concurrency`;
15. two concurrent calls for the same normalized Riot ID share one Account/probe task;
16. different Riot IDs do not share a task;
17. inflight entries are removed after success and exception.

- [ ] **Step 4: Write confirmation tests**

Test missing/expired detection (`PLATFORM_CONFIRMATION_EXPIRED`), chosen value not in candidates (`INVALID_PLATFORM_SELECTION`), successful candidate resolution, no mutation of the shared candidate list, and a chosen platform that has disappeared.

For the disappeared-platform case, delete the detection record and retry full detection exactly once. If the second attempt still cannot resolve the chosen platform, return the new detection result or the appropriate temporary/not-found error; never loop.

Confirmation must first re-probe the selected platform through `get_summoner_by_puuid`; only after that succeeds may it call `player_service.get_by_puuid`. This prevents an unexpired player-profile cache from hiding a platform that no longer resolves upstream.

- [ ] **Step 5: Verify service tests fail before implementation**

```bash
cd backend
.venv/bin/pytest -q tests/test_player_parsing.py tests/test_platform_detection_service.py
```

- [ ] **Step 6: Implement cache-first, fail-closed detection**

Use the configured primary region followed by the remaining `Region` values in one stable order. Catch only `ApiError(code="PLAYER_NOT_FOUND")` as a negative probe. Authentication, rate limit, invalid response, and unavailable errors must abort classification. Map exhausted platform-probe availability errors to `RIOT_PLATFORM_DETECTION_UNAVAILABLE` while preserving retryability and safe retry metadata.

After a unique candidate has been established, call `player_service.get_by_puuid(platform=candidate, puuid=account.puuid)` and return that `PlayerView`. Use the same call for a fresh resolved cache record. Do not call the compatibility `resolve(game_name, tag_line, platform)` path, because detection already established the canonical PUUID.

Use one shared semaphore per detector instance:

```python
self._probe_semaphore = asyncio.Semaphore(max_concurrency)
```

Probe all platforms with created tasks, cancel and await outstanding tasks on a fatal result, and never leave orphan tasks.

- [ ] **Step 7: Implement in-process single-flight**

Key inflight work by `(game_name_key, tag_line_key)`. Guard the dictionary with an `asyncio.Lock`; create one task for the uncached detection; await it through `asyncio.shield`; and remove it in the task's `finally` path only when the stored task identity still matches. A caller cancellation must not cancel work shared by other callers.

The shared task produces/persists a locale-neutral record. Each caller localizes candidate names after awaiting the shared record, so simultaneous Chinese and English requests share upstream work without sharing display strings.

- [ ] **Step 8: Run focused tests and commit**

```bash
cd backend
.venv/bin/pytest -q tests/test_player_parsing.py tests/test_platform_detection_service.py
cd ..
git add backend/app/services/platform_detection.py backend/app/services/parsing/players.py backend/tests/test_platform_detection_service.py backend/tests/test_player_parsing.py
git commit -m "feat: detect Riot account platform candidates"
```

---

## Task 5: Expose detection APIs, errors, metrics, and dependency wiring

**Files:**

- Create: `backend/app/schemas/platform_detection.py`
- Modify: `backend/app/schemas/__init__.py`
- Modify: `backend/app/api/players.py`
- Modify: `backend/app/core/dependencies.py`
- Modify: `backend/app/core/errors.py`
- Modify: `backend/app/core/metrics.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_phase_2_schemas.py`
- Modify: `backend/tests/test_player_api.py`
- Create: `backend/tests/test_platform_detection_metrics.py`
- Modify: `backend/tests/test_app_factory.py`

- [ ] **Step 1: Write failing strict-schema tests**

Add strict Pydantic models:

```python
class DetectPlayerRequest(DomainModel):
    riot_id: str
    locale: Locale


class ConfirmPlatformRequest(DomainModel):
    platform: Platform
    locale: Locale


class PlatformCandidate(DomainModel):
    platform: Platform
    display_name: str


class ResolvedDetectionResponse(DomainModel):
    status: Literal["resolved"]
    player: PlayerView
    request_id: str


class ConfirmationRequiredResponse(DomainModel):
    status: Literal["confirmation_required"]
    detection_id: UUID
    expires_at: datetime
    candidates: tuple[PlatformCandidate, ...]
    request_id: str
```

Define `DetectPlayerResponse` as the discriminated union. Reject extra fields, invalid locale/platform, naive expiry timestamps, empty candidates, and the wrong fields for each status.

- [ ] **Step 2: Write API tests before routes**

Test:

- `POST /api/v1/players/detect` request/response mapping for resolved and confirmation-required;
- `POST /api/v1/players/detect/{uuid}/confirm` mapping;
- malformed Riot ID error contract;
- disabled feature returns 404 `NOT_FOUND` so it is not accidentally exposed before rollout;
- temporary detection failure is retryable;
- confirmation expiry and invalid selection codes;
- request ID is included in success and error bodies;
- the compatibility GET route still works for all typed platforms;
- raw Riot IDs and PUUIDs are absent from captured logs.

- [ ] **Step 3: Implement dependency wiring once**

Add `platform_detection_service: PlatformDetector` to `AppServices`. In `build_services`, construct one `SqlPlatformDetectionRepository`, pass the existing `RiotGateway` and `PlayerService`, and inject all TTL/concurrency/primary-region settings plus the shared metrics registry.

Do not create a detector or semaphore per HTTP request. Add `DisabledPlatformDetectionService`, whose `detect` and `confirm` methods raise the standard 404 `NOT_FOUND` error, and wire it when `riot_platform_detection_enabled` is false. Always register the two routes so application shape is stable across configurations. Preserve service close behavior.

- [ ] **Step 4: Add the two POST routes**

Use request bodies, not query strings:

```python
@router.post("/detect", response_model=DetectPlayerResponse)
async def detect_player(...): ...

@router.post(
    "/detect/{detection_id}/confirm",
    response_model=ResolvedDetectionResponse,
)
async def confirm_player_platform(...): ...
```

Place static `/detect` routes before the dynamic `/{puuid}/matches` route and use UUID path validation. Map service result objects explicitly and add `request.state.request_id` only at the API boundary.

- [ ] **Step 5: Add exact error factories**

Provide stable errors:

- `INVALID_RIOT_ID`: 422, not retryable;
- `PLAYER_NOT_FOUND`: 404, not retryable;
- `RIOT_PLATFORM_DETECTION_UNAVAILABLE`: 503, retryable;
- `PLATFORM_CONFIRMATION_EXPIRED`: 409, not retryable;
- `INVALID_PLATFORM_SELECTION`: 422, not retryable.

Reuse existing `RIOT_NOT_CONFIGURED`, `RIOT_AUTH_FAILED`, `RIOT_RATE_LIMITED`, `RIOT_UNAVAILABLE`, and `RIOT_INVALID_RESPONSE` mappings rather than inventing duplicates.

- [ ] **Step 6: Add bounded-cardinality metrics**

Extend `MetricsRegistry` and Prometheus rendering with:

```text
riot_platform_detection_requests_total{outcome}
riot_platform_detection_duration_seconds{outcome}
riot_platform_detection_cache_total{status}
riot_platform_detection_probes_total{result}
riot_platform_confirmation_total{outcome}
```

Allowed label values must be fixed enums such as `resolved`, `confirmation_required`, `not_found`, `unavailable`, `hit`, `miss`, `expired`, `success`, and `not_found`. Never label by Riot ID, platform combinations, PUUID, request ID, or error message.

- [ ] **Step 7: Run API, metrics, and app-factory tests**

```bash
cd backend
.venv/bin/pytest -q tests/test_phase_2_schemas.py tests/test_player_api.py tests/test_platform_detection_metrics.py tests/test_app_factory.py tests/test_errors.py
```

- [ ] **Step 8: Commit the API boundary**

```bash
cd ..
git add backend/app/api/players.py backend/app/schemas backend/app/core/dependencies.py backend/app/core/errors.py backend/app/core/metrics.py backend/app/main.py backend/tests
git commit -m "feat: expose Riot platform detection API"
```

---

## Task 6: Generalize frontend platform schemas and add detection client calls

**Files:**

- Modify: `frontend/src/api/schemas.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/tests/api-client.test.ts`
- Modify: `frontend/tests/replay-api-client.test.ts`

- [ ] **Step 1: Add failing schema/client tests**

Expand `platformSchema` to the exact 16-value backend enum and export:

```typescript
export type Platform = z.infer<typeof platformSchema>;
```

Add strict schemas for the two discriminated detection responses and test rejection of unknown platforms, missing candidate fields, invalid expiry timestamps, and extra fields.

Test exact HTTP requests:

```typescript
detectPlayer({ riotId, locale })
// POST /api/v1/players/detect
// JSON { riot_id: riotId, locale }

confirmPlayerPlatform({ detectionId, platform, locale })
// POST /api/v1/players/detect/{encoded UUID}/confirm
// JSON { platform, locale }
```

- [ ] **Step 2: Verify tests fail**

```bash
cd frontend
pnpm test -- api-client.test.ts replay-api-client.test.ts
```

- [ ] **Step 3: Implement schemas and typed client functions**

Use `z.discriminatedUnion("status", [...])`. Export `DetectPlayerResponse`, `ResolvedDetectionResponse`, and `PlatformCandidate` types.

Replace every public input type containing `platform: "NA1"` with `platform: Platform`, including player, match, and replay client calls. Keep `resolvePlayer` exported for compatibility tests, but do not call it from the home search form.

Reuse the current `ApiClientError` parsing so backend codes, retryability, params, and request ID remain available to the UI.

- [ ] **Step 4: Run client tests and typecheck**

```bash
pnpm test -- api-client.test.ts replay-api-client.test.ts
pnpm typecheck
```

- [ ] **Step 5: Commit the frontend contract**

```bash
cd ..
git add frontend/src/api frontend/tests/api-client.test.ts frontend/tests/replay-api-client.test.ts
git commit -m "feat: add platform detection web client"
```

---

## Task 7: Replace the search form with bilingual auto-detection UX

**Files:**

- Modify: `frontend/tests/riot-search-form.test.tsx`
- Modify: `frontend/tests/home-page.test.tsx`
- Modify: `frontend/tests/i18n.test.ts`
- Modify: `frontend/src/components/riot-search-form.tsx`
- Modify: `frontend/src/i18n/messages.ts`
- Modify: `frontend/src/i18n/zh-CN.ts`
- Modify: `frontend/src/i18n/en-US.ts`
- Modify: `frontend/src/app/[locale]/page.tsx`
- Modify: `frontend/src/app/globals.css`

- [ ] **Step 1: Write interaction tests for the approved state machine**

The tests must cover:

1. one input named `riotId`, no platform select, no separate game/tag inputs;
2. example `CNGEI#1115` and text explaining the tag is not the server;
3. submit calls `detectPlayer` with the current locale;
4. detecting state disables repeat submit and announces progress;
5. resolved result navigates to `/{locale}/players/{encodedPuuid}?platform={platform}`;
6. confirmation-required renders only server names returned by the API;
7. a candidate button calls `confirmPlayerPlatform` with the detection ID and platform;
8. successful confirmation navigates with the selected platform;
9. `PLAYER_NOT_FOUND`, `INVALID_RIOT_ID`, rate limit, detection unavailable, and confirmation expired have distinct messages/actions;
10. confirmation expiry resets to the Riot ID form and invites a new detection;
11. request ID remains available under support details;
12. the same behavior works with Chinese and English messages.

- [ ] **Step 2: Verify UI tests fail**

```bash
cd frontend
pnpm test -- riot-search-form.test.tsx home-page.test.tsx i18n.test.ts
```

- [ ] **Step 3: Implement the explicit UI state union**

Use:

```typescript
type SearchState =
  | { status: "idle" }
  | { status: "detecting" }
  | {
      status: "confirmation_required";
      detectionId: string;
      expiresAt: string;
      candidates: PlatformCandidate[];
      confirming: Platform | null;
    }
  | { status: "error"; error: ApiClientError | null };
```

Do not maintain hidden platform defaults. Candidate labels are rendered from `candidate.display_name`, exactly as returned by the backend. Candidate values are never editable.

Guard stale async results if the user submits a new Riot ID while an older request is finishing. The simplest acceptable implementation is an incrementing request generation stored in a ref.

- [ ] **Step 4: Add complete bilingual copy**

Add message keys for:

- Riot ID field and example;
- tag-is-not-server explanation;
- detecting account/server;
- server confirmation heading and help text;
- confirming selection;
- player not found;
- invalid Riot ID;
- temporarily unavailable and retry;
- confirmation expired and detect again;
- generic failure and support details.

Both locale modules must satisfy the shared `Messages` type and the i18n parity test. Remove old labels from the rendered form; message keys may remain only when another page still uses them.

- [ ] **Step 5: Style candidate selection accessibly**

Use real `<button type="button">` elements, visible focus states, `aria-live`/`role="status"` for progress, and `role="alert"` for errors. Preserve the established visual design; do not introduce a second design system or modal.

- [ ] **Step 6: Run UI tests, lint, and typecheck**

```bash
pnpm test -- riot-search-form.test.tsx home-page.test.tsx i18n.test.ts
pnpm lint
pnpm typecheck
```

- [ ] **Step 7: Commit the bilingual search experience**

```bash
cd ..
git add frontend/src/components/riot-search-form.tsx frontend/src/i18n frontend/src/app/\[locale\]/page.tsx frontend/src/app/globals.css frontend/tests
git commit -m "feat: add bilingual automatic server detection UI"
```

---

## Task 8: Carry all supported platforms through player, match, and replay pages

**Files:**

- Modify: `frontend/src/app/[locale]/players/[puuid]/page.tsx`
- Modify: `frontend/src/app/[locale]/matches/[matchId]/page.tsx`
- Modify: `frontend/src/components/player-page-client.tsx`
- Modify: `frontend/src/components/match-detail-client.tsx`
- Modify: `frontend/src/components/replay-section.tsx`
- Modify: `frontend/src/components/player-header.tsx`
- Create: `frontend/src/i18n/platform-names.ts`
- Modify: `frontend/tests/player-page.test.tsx`
- Modify: `frontend/tests/match-detail-page.test.tsx`
- Modify: `frontend/tests/replay-section.test.tsx`
- Create: `frontend/tests/platform-names.test.ts`

- [ ] **Step 1: Add non-NA route propagation tests**

Use at least EUW1 and KR fixtures. Assert:

- the player page accepts a platform parsed by `platformSchema`;
- recent-match requests preserve that platform;
- match links preserve platform and selected PUUID;
- match detail requests preserve platform;
- replay creation preserves platform;
- an unknown platform query is rejected with the existing safe error/not-found behavior;
- no component silently substitutes NA1.

- [ ] **Step 2: Verify the tests fail on NA1 literals**

```bash
cd frontend
pnpm test -- player-page.test.tsx match-detail-page.test.tsx replay-section.test.tsx platform-names.test.ts
```

- [ ] **Step 3: Replace literal platform prop types**

Import and use `Platform` from `@/api/schemas`. Parse page query parameters with `platformSchema.safeParse` and pass the parsed value unchanged. Build URLs with `encodeURIComponent(platform)` and never infer platform from the match ID string.

For the player header, add `platform-names.ts` with an explicit `Record<Locale, Record<Platform, string>>` for page decoration. Use the exact names from Task 1 and test that it contains exactly the 16 `Platform` values in both locales. Detection candidate labels must still come from the backend and must not use this map.

- [ ] **Step 4: Run page regression tests and typecheck**

```bash
pnpm test -- player-page.test.tsx match-detail-page.test.tsx replay-section.test.tsx platform-names.test.ts
pnpm typecheck
```

- [ ] **Step 5: Commit platform propagation**

```bash
cd ..
git add frontend/src/app frontend/src/components frontend/tests
git commit -m "fix: preserve detected platform across player flows"
```

---

## Task 9: Full verification, real smoke, and staged rollout

**Files:**

- Modify: `scripts/smoke_riot.py`
- Modify: `backend/app/services/riot/smoke.py`
- Modify: `README.md`
- Verify: `docker-compose.yml`
- Verify: `.env.example`

- [ ] **Step 1: Add a detection smoke mode without exposing identifiers**

Extend the existing Riot smoke path to optionally call `POST /api/v1/players/detect` with `RIOT_SMOKE_GAME_NAME`, `RIOT_SMOKE_TAG_LINE`, and a locale, but no platform. Do not print the Riot ID or returned PUUID. Print only safe fields: HTTP outcome, result status, candidate count, cache hit/miss when exposed safely, request ID, and elapsed time.

Run the request twice and assert the second result is semantically identical. Metrics/repository tests are the authoritative cache-call-count proof; the real smoke confirms the public behavior.

- [ ] **Step 2: Add a real ambiguous-case hook without making it required**

If `RIOT_SMOKE_AMBIGUOUS_RIOT_ID` is configured locally, assert `confirmation_required`, select only a returned candidate, and call confirm. If not configured, report this optional case as skipped while keeping the unique-account smoke mandatory.

- [ ] **Step 3: Document feature flags and rollout order**

Update `README.md` with:

1. migrate database to head;
2. deploy backend with `RIOT_PLATFORM_DETECTION_ENABLED=false`;
3. deploy the compatible frontend;
4. set the primary region and TTLs;
5. enable detection;
6. monitor error, rate-limit, cache, and confirmation metrics;
7. disable the flag to roll back while the old resolve route remains available.

Document that production API keys require normal rotation and must never be pasted into source files.

- [ ] **Step 4: Run the complete backend verification**

```bash
make test
make lint
make typecheck
```

Then with the dedicated PostgreSQL URL:

```bash
make verify-postgres
make verify-replay-postgres
```

Run real media/storage checks:

```bash
make verify-replay-ffmpeg
```

With the configured real MinIO endpoint, run the exact integration file and confirm both storage tests pass:

```bash
test -n "$REPLAY_S3_TEST_ENDPOINT"
cd backend
.venv/bin/pytest -m replay_s3 tests/integration/test_replay_s3_streaming.py -v
cd ..
```

- [ ] **Step 5: Run the complete frontend verification**

```bash
cd frontend
pnpm test
pnpm lint
pnpm typecheck
pnpm build
cd ..
```

- [ ] **Step 6: Run real Riot and Replay smoke checks**

With secrets loaded only from the ignored local `.env`:

```bash
make smoke-riot
make e2e-replay-compose
```

Required results:

- unique Riot ID resolves without sending a platform;
- second detection returns the same public result;
- no raw identifier appears in logs;
- replay create/upload/process/delete still passes with zero storage residue;
- `/zh-CN` and `/en-US` both return 200.

- [ ] **Step 7: Inspect migration and repository behavior under concurrency**

Confirm the PostgreSQL suite includes concurrent detection upsert and the same PUUID stored on two platforms. Confirm there is no remaining single-column unique constraint on `players.puuid` after upgrading to head.

- [ ] **Step 8: Commit smoke/docs changes**

```bash
git add scripts/smoke_riot.py backend/app/services/riot/smoke.py README.md
git commit -m "test: verify automatic Riot platform detection"
```

- [ ] **Step 9: Produce the implementation handoff**

Report:

- commit list by task;
- backend, PostgreSQL, frontend, FFmpeg, MinIO, and Compose pass counts;
- real unique-account detection result without the Riot ID or PUUID;
- whether the optional ambiguous smoke ran;
- migration head revision;
- feature-flag state;
- any production-only validation still outstanding.

---

## Definition of Done

- Home search contains one Riot ID field and no server input.
- The backend supports exactly four regional routes and sixteen platform routes from a typed allowlist.
- A unique candidate resolves automatically; multiple candidates require selection from server-provided choices only.
- Partial Riot failures never produce a false unique or not-found result.
- Positive/ambiguous results cache for 24 hours, not-found for 5 minutes, and confirmation for 15 minutes.
- Identical in-process requests share one upstream detection task with a maximum of four concurrent platform probes by default.
- Player persistence uses `UNIQUE(platform, puuid)` and preserves existing data.
- Chinese and English user flows, errors, progress, and confirmation are fully tested.
- Player, match, replay, and URL flows preserve every supported platform without NA1 fallback.
- The compatibility resolve endpoint still works for one release cycle.
- Full backend, PostgreSQL, frontend, FFmpeg, MinIO, Riot smoke, and Replay Compose verification passes with no secret leakage.
