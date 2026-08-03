# LoL AI Coach Joint Evidence J1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an on-demand, bilingual Joint Evidence J1 flow that retrieves and caches Riot Match-V5 Timeline data, normalizes neutral facts, plans deterministic candidate windows, and optionally links those windows to existing artifacts from an authorized ready Replay.

**Architecture:** Extend the closed-host Riot boundary with one Timeline operation, persist only versioned normalized snapshots in PostgreSQL, and keep normalization, window planning, and replay linkage as separately tested units. A synchronous `JointEvidenceService` composes the existing match cache, the Timeline cache/service, match-compatible Data Dragon hydration, and possession-token-protected Replay data behind one strict match evidence endpoint. The Next.js match page makes the request only after an explicit user action and presents evidence without scoring, causal claims, or coaching conclusions.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy async, PostgreSQL 17/Alembic, httpx2, pytest, Next.js 16, React 19, TypeScript, Zod, Vitest/Testing Library, Docker Compose, FFmpeg, S3-compatible storage, `zh-CN` and `en-US` localization.

## Global Constraints

- The approved source of truth is `docs/superpowers/specs/2026-08-02-lol-ai-coach-joint-evidence-j1-design.md`. Do not redesign or expand J1 while executing this plan.
- Before business-code work, create an isolated `feature/joint-evidence-j1` branch/worktree from the commit containing both the approved J1 design and this plan. Do not start from an older `origin/main`, and do not continue feature code directly on `feature/replay-r1`.
- Cursor owns implementation. Use high reasoning, test-driven development, and one focused commit for each task below. Codex reviews each completed task before the next task begins.
- Keep `JOINT_EVIDENCE_ENABLED=false` in `Settings`, `.env.example`, Compose defaults, and tests throughout implementation. Enabling it is an operational rollout action, not an implementation default.
- Timeline hosts come only from `routes_for(platform).regional_host`. Never construct a hostname from a request field.
- Store normalized Timeline data only. Never store, log, print, snapshot, or commit a real raw Riot response.
- Never expose or log API keys, Riot IDs, PUUIDs, match IDs in metrics, Replay tokens, replay object keys, local paths, hashes, presigned URLs, raw upstream URLs, or individual raw event dictionaries.
- Public evidence IDs and metric labels must not contain a PUUID. Metrics use only the closed label values defined in Task 4 and Task 6.
- J1 is evidence infrastructure: no OpenAI call, score, grade, mistake/strength label, advice, intent, awareness, mechanics, blame, or causal claim.
- J1 must not create clips, extract event-specific frames, add a Replay job kind, or change Replay retention.
- Preserve all existing player, platform-detection, match-detail, Replay R1, deletion-race, FFmpeg, S3-compatible, and Compose behavior.
- All Timeline fixtures are small synthetic payloads under `backend/tests/fixtures`; never copy a real player's payload into the repository.
- Each task report must include changed files, commit hash, exact focused test count, and unverified gates. Stop for Codex review after every task.

## File and Ownership Map

- `backend/app/services/riot/dto.py`: Riot-shaped Timeline DTOs and critical upstream validation only.
- `backend/app/services/riot/gateway.py`: closed regional host selection, encoded Timeline path, and caller-specific 404 code.
- `backend/app/models/timeline.py`: SQLAlchemy row for `match_timelines`.
- `backend/app/repositories/timelines.py`: PostgreSQL cache record conversion, freshness lookup, and convergent upsert.
- `backend/app/services/timelines/domain.py`: versioned normalized Timeline facts and cache-result types.
- `backend/app/services/timelines/normalizer.py`: pure Riot DTO to normalized snapshot boundary.
- `backend/app/services/timelines/service.py`: TTL policy, negative caching, single-flight, and Timeline metrics.
- `backend/app/services/evidence/domain.py`: pure planned-window and replay-link internal contracts.
- `backend/app/services/evidence/windows.py`: deterministic window planning.
- `backend/app/services/evidence/replay.py`: Replay authorization, coverage intersection, time mapping, and safe artifact references.
- `backend/app/services/evidence/service.py`: match validation, public fact projection, static-data hydration, and final composition.
- `backend/app/schemas/evidence.py`: strict request and public response models.
- `backend/app/api/matches.py`: `POST /api/v1/matches/{match_id}/evidence` and conditional Authorization handling.
- `frontend/src/api/schemas.ts` and `frontend/src/api/client.ts`: strict Zod response and typed POST client.
- `frontend/src/components/evidence-section.tsx`: explicit action and evidence UI state machine.
- `frontend/src/replays/storage.ts`: backward-compatible latest Replay status in the local capability record.

---

## Task 1: Add Timeline settings, DTO validation, and the closed-host gateway operation

**Files:**

- Modify: `backend/tests/test_config.py`
- Modify: `backend/tests/fixtures/riot_payloads.py`
- Modify: `backend/tests/test_riot_gateway.py`
- Modify: `backend/tests/test_riot_client.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/services/riot/dto.py`
- Modify: `backend/app/services/riot/gateway.py`
- Modify: `.env.example`
- Modify: `docker-compose.yml`

**Interfaces:**

- Consumes: `Platform`, `routes_for(platform).regional_host`, `RiotHttpClient.get_json(...)`, the existing safe Riot error mapping.
- Produces: `TimelineDto`, `validate_timeline_payload(payload: object) -> TimelineDto`, and `RiotGateway.get_match_timeline(*, platform: Platform, match_id: str) -> TimelineDto`.
- Produces settings: `joint_evidence_enabled`, `timeline_cache_ttl_seconds`, and `timeline_not_found_ttl_seconds`.

- [ ] **Step 1: Add failing configuration tests**

Assert these exact defaults and bounds using `Settings(_env_file=None)`:

```python
assert settings.joint_evidence_enabled is False
assert settings.timeline_cache_ttl_seconds == 2_592_000
assert settings.timeline_not_found_ttl_seconds == 300
```

Assert positive-cache values below `3_600` or above `7_776_000` fail, and negative-cache values below `30` or above `3_600` fail.

- [ ] **Step 2: Run the configuration test and observe the intended failure**

```bash
cd backend
.venv/bin/pytest -q tests/test_config.py
```

Expected: failures because the three J1 settings do not exist.

- [ ] **Step 3: Implement settings and disabled deployment defaults**

Add to `Settings`:

```python
joint_evidence_enabled: bool = False
timeline_cache_ttl_seconds: int = Field(default=2_592_000, ge=3_600, le=7_776_000)
timeline_not_found_ttl_seconds: int = Field(default=300, ge=30, le=3_600)
```

Add the same names and values to `.env.example`. Add only the backend Compose environment entries below; the Replay worker does not fetch Timelines:

```yaml
JOINT_EVIDENCE_ENABLED: ${JOINT_EVIDENCE_ENABLED:-false}
TIMELINE_CACHE_TTL_SECONDS: ${TIMELINE_CACHE_TTL_SECONDS:-2592000}
TIMELINE_NOT_FOUND_TTL_SECONDS: ${TIMELINE_NOT_FOUND_TTL_SECONDS:-300}
```

- [ ] **Step 4: Add synthetic Timeline fixtures**

Extend `backend/tests/fixtures/riot_payloads.py` with a compact synthetic payload containing ten unique metadata participants, two monotonic frames, participant frames, one event of each supported kind, and one unknown event. Use obviously synthetic values such as `fixture-puuid-1`; do not use local smoke identifiers.

- [ ] **Step 5: Add failing DTO tests through the gateway boundary**

Cover all of the following in `test_riot_gateway.py`:

- top-level metadata/info required and additive unknown object fields ignored;
- metadata `matchId` required and participant PUUIDs unique;
- metadata participant order defines the internal participant IDs `1..N`;
- `frameInterval` accepts `1_000` and `120_000` and rejects values outside that range;
- frame timestamps are non-negative and monotonically non-decreasing;
- participant-frame map keys are decimal participant IDs known to metadata;
- each participant frame's `participantId` equals its map key;
- participant-frame level/current gold/total gold/minion CS/jungle CS/XP are non-negative;
- a position is accepted only when both integer `x` and `y` are present and non-negative;
- supported event timestamps are non-negative;
- known events reject missing critical fields, while unknown event types validate as ignorable input;
- duplicate assistant IDs and references to unknown participant IDs are rejected.

Use these DTO shapes in `dto.py`:

```python
class TimelinePositionDto(RiotDto):
    x: int = Field(ge=0)
    y: int = Field(ge=0)


class TimelineParticipantFrameDto(RiotDto):
    participant_id: int = Field(alias="participantId", ge=1)
    level: int = Field(ge=0)
    current_gold: int = Field(alias="currentGold", ge=0)
    total_gold: int = Field(alias="totalGold", ge=0)
    minions_killed: int = Field(alias="minionsKilled", ge=0)
    jungle_minions_killed: int = Field(alias="jungleMinionsKilled", ge=0)
    xp: int = Field(ge=0)
    position: TimelinePositionDto | None = None


class TimelineEventDto(RiotDto):
    type: str
    timestamp: int
    # Riot-shaped optional fields are validated by type in a model validator.


class TimelineFrameDto(RiotDto):
    timestamp: int = Field(ge=0)
    participant_frames: dict[int, TimelineParticipantFrameDto] = Field(
        alias="participantFrames"
    )
    events: tuple[TimelineEventDto, ...]


class TimelineInfoDto(RiotDto):
    frame_interval: int = Field(alias="frameInterval", ge=1_000, le=120_000)
    frames: tuple[TimelineFrameDto, ...]


class TimelineDto(RiotDto):
    metadata: MatchMetadataDto
    info: TimelineInfoDto
```

The type-specific validator must require:

- `CHAMPION_KILL`: `killerId`, `victimId`, and an array `assistingParticipantIds` when present;
- `ELITE_MONSTER_KILL`: `killerId`, `killerTeamId`, `monsterType`; subtype and position remain optional;
- `BUILDING_KILL`: `killerId`, `teamId`, `buildingType`; lane/tower subtype and position remain optional;
- `ITEM_PURCHASED`, `ITEM_SOLD`, `ITEM_DESTROYED`: `participantId` and `itemId`;
- `ITEM_UNDO`: `participantId`, `beforeId`, and `afterId`.

Allow Riot's neutral participant ID `0` only for killer fields. It remains ambiguous context and cannot later create a selected-team window.

- [ ] **Step 6: Add failing gateway URL and error tests**

Assert:

```python
timeline = await gateway.get_match_timeline(
    platform=Platform.EUW1,
    match_id="EUW1 path/with spaces",
)
```

calls only `europe.api.riotgames.com` with:

```text
/lol/match/v5/matches/EUW1%20path%2Fwith%20spaces/timeline
```

and `not_found_code="MATCH_TIMELINE_NOT_FOUND"`. Parameterize at least NA1, EUW1, KR, and SG2 to prove the four regional hosts. Extend the existing client tests to prove Timeline 404, 401/403, exhausted 429, final 5xx, connection error, timeout, malformed JSON, and invalid DTO map to the approved safe codes without response-body leakage.

- [ ] **Step 7: Run focused tests and confirm the red phase**

```bash
cd backend
.venv/bin/pytest -q tests/test_config.py tests/test_riot_gateway.py tests/test_riot_client.py
```

Expected: Timeline-specific tests fail before DTO/gateway implementation.

- [ ] **Step 8: Implement the minimal DTO validator and gateway method**

Add `validate_timeline_payload` next to `validate_riot_model`. Convert integer-like participant-frame keys deliberately; reject booleans, negative values, mismatched keys, duplicate participants, non-monotonic frames, and malformed known events by raising the existing `RIOT_INVALID_RESPONSE` error. Do not log the rejected payload.

Implement:

```python
async def get_match_timeline(
    self, *, platform: Platform, match_id: str
) -> TimelineDto:
    host = routes_for(platform).regional_host
    payload = await self._client.get_json(
        host=host,
        path=f"/lol/match/v5/matches/{quote(match_id, safe='')}/timeline",
        params=None,
        not_found_code="MATCH_TIMELINE_NOT_FOUND",
    )
    return validate_timeline_payload(payload)
```

- [ ] **Step 9: Run focused tests, lint/type checks, and commit**

```bash
cd backend
.venv/bin/pytest -q tests/test_config.py tests/test_riot_gateway.py tests/test_riot_client.py
.venv/bin/ruff check app/core/config.py app/services/riot tests/test_config.py tests/test_riot_gateway.py tests/test_riot_client.py
.venv/bin/mypy
cd ..
git diff --check
git add .env.example docker-compose.yml backend/app/core/config.py backend/app/services/riot/dto.py backend/app/services/riot/gateway.py backend/tests/fixtures/riot_payloads.py backend/tests/test_config.py backend/tests/test_riot_gateway.py backend/tests/test_riot_client.py
git commit -m "feat: add Riot timeline gateway"
```

---

## Task 2: Persist positive and negative normalized Timeline cache records

**Files:**

- Create: `backend/alembic/versions/0004_match_timelines.py`
- Create: `backend/app/models/timeline.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/repositories/timelines.py`
- Modify: `backend/app/repositories/__init__.py`
- Modify: `backend/tests/integration/test_migrations.py`
- Create: `backend/tests/integration/test_timeline_repository.py`

**Interfaces:**

- Consumes: `Platform`, SQLAlchemy async session factory, PostgreSQL JSONB and `ON CONFLICT`.
- Produces: `TimelineCacheStatus`, `TimelineCacheRecord`, `TimelineRepository`, and `SqlTimelineRepository`.

- [ ] **Step 1: Write failing migration-preservation tests**

Extend `test_migrations.py` to prove:

1. upgrade from `0003_player_platform_detection` to head preserves representative players, matches, platform detections, replay uploads/jobs/artifacts, and their counts;
2. `match_timelines` has exactly the approved columns and composite primary key `(platform, match_id)`;
3. `expires_at` is indexed;
4. no column name contains `raw`, `payload`, `response`, `url`, `puuid`, or `token`;
5. downgrade to `0003_player_platform_detection` removes only `match_timelines` and its indexes;
6. `0003 -> head -> 0003 -> head` succeeds.

- [ ] **Step 2: Write failing database-shape tests**

Use direct SQL to assert the database rejects:

- an unknown `result_status`;
- `schema_version <= 0`;
- `available` with a null snapshot or hash;
- `not_found` with a non-null snapshot or hash.

Assert valid positive and negative rows succeed.

- [ ] **Step 3: Write failing repository contract tests**

Define the repository-owned record without importing the SQLAlchemy row:

```python
TimelineCacheStatus = Literal["available", "not_found"]


@dataclass(frozen=True)
class TimelineCacheRecord:
    platform: Platform
    match_id: str
    result_status: TimelineCacheStatus
    normalized_snapshot: dict[str, object] | None
    schema_version: int
    snapshot_hash: str | None
    fetched_at: datetime
    expires_at: datetime
    created_at: datetime
    updated_at: datetime


class TimelineRepository(Protocol):
    async def get_fresh(
        self, *, platform: Platform, match_id: str, now: datetime
    ) -> TimelineCacheRecord | None: ...

    async def upsert(self, record: TimelineCacheRecord) -> TimelineCacheRecord: ...
```

Test `expires_at > now` exactly, positive and negative records, stable UTC-aware datetimes, same match ID on two platforms, repeated identical upsert, positive-to-negative and negative-to-positive replacement, and concurrent upsert convergence for one composite key.

- [ ] **Step 4: Run PostgreSQL tests and observe the intended failure**

```bash
export TEST_DATABASE_URL='postgresql+asyncpg://lol_ai_coach:lol_ai_coach@127.0.0.1:5432/lol_ai_coach_test'
cd backend
DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/alembic upgrade 0003_player_platform_detection
.venv/bin/pytest -q tests/integration/test_migrations.py tests/integration/test_timeline_repository.py -m integration
```

Expected: missing `0004`, table, model, and repository failures.

- [ ] **Step 5: Implement revision `0004_match_timelines`**

Create only `match_timelines` with:

```text
platform VARCHAR(8) primary key part
match_id VARCHAR(64) primary key part
result_status VARCHAR(16) not null
normalized_snapshot JSONB null
schema_version INTEGER not null
snapshot_hash VARCHAR(64) null
fetched_at TIMESTAMPTZ not null
expires_at TIMESTAMPTZ not null indexed
created_at TIMESTAMPTZ not null
updated_at TIMESTAMPTZ not null
```

Add named checks for positive schema version, allowed result status, and the two valid result shapes. `down_revision` is exactly `0003_player_platform_detection`. Downgrade drops the J1 index and table only.

- [ ] **Step 6: Implement model and repository conversion**

Use a composite SQLAlchemy primary key. `get_fresh` selects by both identity fields and `expires_at > now`. `upsert` uses PostgreSQL `insert(...).on_conflict_do_update(index_elements=[platform, match_id])`, updates the result fields and timestamps, preserves the original `created_at`, and returns the converged database record.

Do not calculate or trust a hash in the repository; Task 3 supplies a deterministic normalized snapshot and hash. The repository validates returned JSON with the Task 3 model once that model exists; until then keep conversion through the record shape and add the model validation in Task 3 without changing SQL behavior.

- [ ] **Step 7: Run focused PostgreSQL tests and commit**

```bash
cd backend
DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/alembic upgrade head
.venv/bin/pytest -q tests/integration/test_migrations.py tests/integration/test_timeline_repository.py -m integration
.venv/bin/ruff check app/models app/repositories tests/integration/test_migrations.py tests/integration/test_timeline_repository.py alembic/versions/0004_match_timelines.py
.venv/bin/mypy
cd ..
git diff --check
git add backend/alembic/versions/0004_match_timelines.py backend/app/models/timeline.py backend/app/models/__init__.py backend/app/repositories/timelines.py backend/app/repositories/__init__.py backend/tests/integration/test_migrations.py backend/tests/integration/test_timeline_repository.py
git commit -m "feat: persist normalized match timelines"
```

---

## Task 3: Normalize deterministic Timeline facts and stable identifiers

**Files:**

- Create: `backend/app/services/timelines/__init__.py`
- Create: `backend/app/services/timelines/domain.py`
- Create: `backend/app/services/timelines/normalizer.py`
- Modify: `backend/app/repositories/timelines.py`
- Create: `backend/tests/test_timeline_normalizer.py`
- Modify: `backend/tests/fixtures/riot_payloads.py`
- Modify: `backend/tests/integration/test_timeline_repository.py`

**Interfaces:**

- Consumes: validated `TimelineDto`, `Platform`, and synthetic fixtures.
- Produces: `TimelineSnapshot`, discriminated normalized fact types, `TimelineNormalizer.normalize(...)`, canonical JSON, and SHA-256 snapshot hash.

- [ ] **Step 1: Define the failing normalized-domain contract tests**

Use frozen, `extra="forbid"` Pydantic models. Define:

```python
TIMELINE_SCHEMA_VERSION = 1
TimelineFact = (
    ChampionKillFact
    | EliteMonsterKillFact
    | BuildingKillFact
    | ItemEventFact
    | ParticipantStateFact
)


class TimelineSnapshot(DomainModel):
    platform: Platform
    match_id: str
    schema_version: Literal[1]
    frame_interval_ms: int
    participant_puuids: dict[int, str]
    facts: tuple[TimelineFact, ...]
```

Every fact contains `fact_id`, `kind`, `timestamp_ms`, `frame_index`, and its source ordinal. Event facts use `event_index`; participant-state facts use `participant_id`. Position is a strict `{x, y}` model or `None`.

- [ ] **Step 2: Add one red test per supported fact kind**

Assert exact field preservation for:

- `champion_kill`: killer, victim, ordered unique assistants, optional position;
- `elite_monster_kill`: killer, killer team, monster type/subtype, optional position;
- `building_kill`: killer, target team, building/lane/tower values, optional position;
- four separate item kinds: purchased, sold, destroyed, undo; do not create an item-transform fact;
- participant state: level, current/total gold, lane/jungle CS, XP, optional position.

Missing optional values stay `None`; zero remains zero.

- [ ] **Step 3: Add determinism and privacy tests**

Normalize a deep-copied payload twice and assert identical model dumps, canonical JSON bytes, hashes, fact order, and IDs. Assert exact ID forms:

```text
timeline:NA1:NA1_fixture:v1:frame:0:event:0
timeline:NA1:NA1_fixture:v1:frame:0:participant:1
```

Assert no `fact_id` contains any synthetic PUUID. Assert stored JSON contains the internal participant map but no raw event dictionary, raw upstream field aliases, or unknown event content.

- [ ] **Step 4: Add ordering, ignored-event, and failure tests**

Facts are ordered by frame index, then participant-state facts by participant ID, then events by event index. Unknown event types produce no fact and return an ignored count grouped under the single closed value `ignored`; malformed known events must already have failed at the DTO boundary and cannot reach normalization.

Expose normalization metadata without logging event names from upstream:

```python
@dataclass(frozen=True)
class TimelineNormalizationResult:
    snapshot: TimelineSnapshot
    snapshot_hash: str
    supported_event_counts: dict[SupportedEventKind, int]
    ignored_event_count: int
```

- [ ] **Step 5: Run the normalizer tests and observe the red phase**

```bash
cd backend
.venv/bin/pytest -q tests/test_timeline_normalizer.py
```

- [ ] **Step 6: Implement canonical normalization**

Build participant IDs from the one-based order of `metadata.participants`. Use source frame/event ordinals, never content-derived or PUUID-derived IDs. Serialize with:

```python
json.dumps(
    snapshot.model_dump(mode="json"),
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
```

Hash those bytes with SHA-256. Never include the raw DTO or raw event in the result.

- [ ] **Step 7: Make repository reads validate the normalized schema**

When an `available` cache row is read, validate `normalized_snapshot` as `TimelineSnapshot`, require its `schema_version == TIMELINE_SCHEMA_VERSION`, require row identity to equal snapshot identity, and require a recomputed canonical hash to equal `snapshot_hash`. Treat any mismatch as `RIOT_INVALID_RESPONSE` without returning partial data. `not_found` rows have no snapshot validation.

- [ ] **Step 8: Run unit and repository tests and commit**

```bash
cd backend
.venv/bin/pytest -q tests/test_timeline_normalizer.py
.venv/bin/pytest -q tests/integration/test_timeline_repository.py -m integration
.venv/bin/ruff check app/services/timelines app/repositories/timelines.py tests/test_timeline_normalizer.py tests/integration/test_timeline_repository.py
.venv/bin/mypy
cd ..
git diff --check
git add backend/app/services/timelines backend/app/repositories/timelines.py backend/tests/test_timeline_normalizer.py backend/tests/fixtures/riot_payloads.py backend/tests/integration/test_timeline_repository.py
git commit -m "feat: normalize Riot timeline facts"
```

---

## Task 4: Implement Timeline cache policy, single-flight, failure handling, and metrics

**Files:**

- Create: `backend/app/services/timelines/service.py`
- Modify: `backend/app/services/timelines/__init__.py`
- Modify: `backend/app/core/metrics.py`
- Create: `backend/tests/test_timeline_service.py`
- Create: `backend/tests/test_timeline_metrics.py`
- Modify: `backend/tests/test_container_contract.py`

**Interfaces:**

- Consumes: `TimelineRepository`, `RiotGateway.get_match_timeline`, `TimelineNormalizer`, TTL settings, and `MetricsRegistry`.
- Produces: `TimelineResolver`, `TimelineService.get_timeline(...) -> TimelineLoadResult`, cache/single-flight behavior, and closed J1 metrics.

- [ ] **Step 1: Write failing positive and negative cache tests**

Define:

```python
TimelineCacheResult = Literal["hit", "miss"]


@dataclass(frozen=True)
class TimelineLoadResult:
    snapshot: TimelineSnapshot
    cache_status: TimelineCacheResult


class TimelineResolver(Protocol):
    async def get_timeline(
        self, *, platform: Platform, match_id: str
    ) -> TimelineLoadResult: ...
```

Test fresh positive hit, positive expiry/refetch, fresh negative hit, negative expiry/refetch, positive TTL `2_592_000`, negative TTL `300`, and the exact `expires_at > now` boundary.

- [ ] **Step 2: Write failing error caching tests**

An upstream `MATCH_TIMELINE_NOT_FOUND` writes one `not_found` record and re-raises the same public error. `RIOT_AUTH_FAILED`, `RIOT_RATE_LIMITED`, `RIOT_UNAVAILABLE`, `RIOT_INVALID_RESPONSE`, normalizer failure, and repository-write failure write no negative record and preserve the approved safe error. Do not turn a database error into a false Timeline 404.

- [ ] **Step 3: Write failing single-flight tests**

Use `asyncio.Event` barriers to prove:

- identical `(platform, match_id)` misses make one gateway request;
- different matches and the same match ID on different platforms do not share tasks;
- cancelling one waiter does not cancel the shared task or the remaining waiter;
- the in-flight entry is removed after success, upstream failure, normalizer failure, and shared-task cancellation;
- a later request after cleanup can retry.

- [ ] **Step 4: Write failing closed-metric tests**

Add registry members and rendering for:

```text
joint_evidence_timeline_requests_total{outcome}
joint_evidence_timeline_cache_total{status}
joint_evidence_timeline_fetch_duration_seconds{outcome}
joint_evidence_timeline_events_total{event_type,result}
joint_evidence_singleflight_total{result}
```

Allowed values are fixed in code:

- request `outcome`: `available`, `not_found`, `auth_failed`, `rate_limited`, `invalid_response`, `unavailable`, `internal_error`;
- cache `status`: `hit`, `miss`, `not_found`;
- fetch `outcome`: `available`, `not_found`, `auth_failed`, `rate_limited`, `invalid_response`, `unavailable`;
- event `event_type`: `champion_kill`, `elite_monster_kill`, `building_kill`, `item_purchased`, `item_sold`, `item_destroyed`, `item_undo`, `participant_state`, or `unknown`; `result`: `supported` or `ignored`;
- single-flight `result`: `leader`, `waiter`, `shared_success`, `shared_failure`.

Assert labels never equal or contain supplied platform, match, PUUID, Replay ID, hostname, URL, or upstream free text.

- [ ] **Step 5: Run service/metric tests and observe the red phase**

```bash
cd backend
.venv/bin/pytest -q tests/test_timeline_service.py tests/test_timeline_metrics.py tests/test_container_contract.py
```

- [ ] **Step 6: Implement shielded single-flight and TTL policy**

Use one `dict[tuple[Platform, str], asyncio.Task[TimelineLoadResult]]`. Check the repository before joining; the shared task checks once more before fetching so two process-local leaders racing a PostgreSQL writer converge. Await with `asyncio.shield(task)`. A done callback removes the entry only if the stored task is the completed task.

Use the injected UTC clock for all cache timestamps. On a cache miss, call the gateway once, normalize once, and upsert `available`. On Timeline 404 only, upsert `not_found`; re-raise `MATCH_TIMELINE_NOT_FOUND` for both cached and fresh negative results.

- [ ] **Step 7: Implement metrics without unsafe log context**

Record duration with an injected monotonic clock. Add the new counters/histogram to `render_prometheus_text`. Do not add platform, match, participant, event subtype, monster name, or error message labels. Update the container-contract test so the backend image imports the new Timeline package and still contains no model SDK dependency.

- [ ] **Step 8: Run focused tests, type checks, and commit**

```bash
cd backend
.venv/bin/pytest -q tests/test_timeline_service.py tests/test_timeline_metrics.py tests/test_container_contract.py
.venv/bin/ruff check app/services/timelines app/core/metrics.py tests/test_timeline_service.py tests/test_timeline_metrics.py tests/test_container_contract.py
.venv/bin/mypy
cd ..
git diff --check
git add backend/app/services/timelines backend/app/core/metrics.py backend/tests/test_timeline_service.py backend/tests/test_timeline_metrics.py backend/tests/test_container_contract.py
git commit -m "feat: cache Riot timeline evidence"
```

---

## Task 5: Plan neutral evidence windows and link authorized Replay coverage

**Files:**

- Create: `backend/app/services/evidence/__init__.py`
- Create: `backend/app/services/evidence/domain.py`
- Create: `backend/app/services/evidence/windows.py`
- Create: `backend/app/services/evidence/replay.py`
- Modify: `backend/app/services/replays/service.py`
- Create: `backend/tests/test_evidence_windows.py`
- Create: `backend/tests/test_replay_evidence_linker.py`
- Modify: `backend/tests/test_replay_service.py`

**Interfaces:**

- Consumes: normalized Timeline facts, selected participant/team, match duration, `ReplayServiceProtocol.authorize`, `ReplayArtifactRepository.list_for_replay`, and `game_to_video_time`.
- Produces: `EvidenceWindowPlanner.plan(...)`, `ReplayEvidenceLinker.link(...)`, safe linked-window records, and `REPLAY_EVIDENCE_NOT_READY`.

- [ ] **Step 1: Write failing raw-window tests**

Define neutral categories in this stable order:

```python
EvidenceCategory = Literal[
    "combat_context",
    "death_context",
    "objective_context",
    "building_context",
]
```

Assert exact intervals:

- selected killer or assistant: `timestamp - 12_000` through `timestamp + 8_000`;
- selected victim: `timestamp - 15_000` through `timestamp + 10_000`;
- selected-team elite monster with explicit actor/team mapping: `-20_000/+10_000`;
- selected-team building destruction with explicit killer mapping: `-20_000/+10_000`.

Item facts, participant-state facts, unrelated combat events, and ambiguous killer ID `0` create no window.

- [ ] **Step 2: Write failing clamp, merge, ordering, and cap tests**

Assert clamping to `[0, match_duration_ms]`; stable sorting by start, end, category order, trigger fact ID; merging overlapping intervals only; no merge across a one-millisecond positive gap; stable deduplicated category and trigger lists; chronological IDs:

```text
evidence-window:NA1:NA1_fixture:v1:0
```

Generate 65 disjoint windows and assert 64 returned, `truncated=True`, and `total_window_count=65`.

- [ ] **Step 3: Define replay-link domain contracts**

```python
ReplayCoverageStatus = Literal["full", "partial", "unavailable"]


@dataclass(frozen=True)
class EvidenceArtifactReference:
    artifact_id: UUID
    kind: ReplayArtifactKind
    game_time_ms: int
    video_time_ms: int


@dataclass(frozen=True)
class LinkedEvidenceWindow:
    window: PlannedEvidenceWindow
    coverage: ReplayCoverageStatus
    covered_game_start_ms: int | None
    covered_game_end_ms: int | None
    video_start_ms: int | None
    video_end_ms: int | None
    artifacts: tuple[EvidenceArtifactReference, ...]
```

These internal/public-safe records contain no object key, URL, hash, token, PUUID, or local path.

- [ ] **Step 4: Write failing full, partial, and unavailable coverage tests**

Without a replay request, every window is `unavailable`. For a ready replay, intersect each window with `available_game_time_start_ms..available_game_time_end_ms`; map non-empty intersections with `game_to_video_time`. Exact boundary equality counts as covered. Empty intersection is unavailable. Select only artifacts whose `game_time_ms` is inside the inclusive covered interval and sort by game time, video time, kind, artifact ID.

- [ ] **Step 5: Write failing authorization and binding tests**

Test invalid/missing token, missing/deleted replay, platform mismatch, match mismatch, and selected-PUUID mismatch all produce the existing uniform 404 `REPLAY_NOT_FOUND`. An authorized replay in any state other than `READY` produces 409 `REPLAY_EVIDENCE_NOT_READY`, `retryable=True`. Missing or invalid normalized coverage is `REPLAY_NOT_FOUND`, not fabricated coverage.

- [ ] **Step 6: Write the deletion-race test before implementation**

Use a fake Replay service that becomes deleted after the first authorization but before the final authorization. Assert the linker returns `REPLAY_NOT_FOUND` and no `EvidenceArtifactReference` escapes. Require the linker to authorize and validate the exact binding once before listing artifacts and once after the list is assembled; discard the assembled result when the second check fails or the row version/status/binding changes.

- [ ] **Step 7: Run window/linker tests and observe the red phase**

```bash
cd backend
.venv/bin/pytest -q tests/test_evidence_windows.py tests/test_replay_evidence_linker.py tests/test_replay_service.py
```

- [ ] **Step 8: Implement the planner and linker**

Keep the planner pure and free of repositories. The linker calls the existing Replay authorization boundary; it does not parse tokens itself. Add only the shared `replay_evidence_not_ready()` error factory to `service.py` or `core/errors.py`, preserving the existing `ReplayServiceProtocol` method signatures. Do not call `list_artifacts`, because it produces access URLs; inject `ReplayArtifactRepository` and read safe row metadata directly.

- [ ] **Step 9: Run focused tests and commit**

```bash
cd backend
.venv/bin/pytest -q tests/test_evidence_windows.py tests/test_replay_evidence_linker.py tests/test_replay_service.py
.venv/bin/ruff check app/services/evidence app/services/replays/service.py tests/test_evidence_windows.py tests/test_replay_evidence_linker.py tests/test_replay_service.py
.venv/bin/mypy
cd ..
git diff --check
git add backend/app/services/evidence backend/app/services/replays/service.py backend/tests/test_evidence_windows.py backend/tests/test_replay_evidence_linker.py backend/tests/test_replay_service.py
git commit -m "feat: link evidence windows to replays"
```

---

## Task 6: Compose Joint Evidence, strict schemas, authorization, API, and dependency wiring

**Files:**

- Create: `backend/app/schemas/evidence.py`
- Modify: `backend/app/schemas/__init__.py`
- Create: `backend/app/services/evidence/service.py`
- Modify: `backend/app/services/matches.py`
- Modify: `backend/app/services/static_data/resolver.py`
- Modify: `backend/app/services/replays/security.py`
- Modify: `backend/app/api/replays.py`
- Modify: `backend/app/api/matches.py`
- Modify: `backend/app/core/dependencies.py`
- Modify: `backend/app/core/metrics.py`
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/test_match_service.py`
- Modify: `backend/tests/test_static_data.py`
- Modify: `backend/tests/test_replay_security.py`
- Modify: `backend/tests/test_replay_api.py`
- Create: `backend/tests/test_joint_evidence_service.py`
- Create: `backend/tests/test_evidence_api.py`
- Create: `backend/tests/test_evidence_metrics.py`
- Modify: `backend/tests/test_app_factory.py`

**Interfaces:**

- Consumes: existing match cache/loading, `TimelineResolver`, `EvidenceWindowPlanner`, `ReplayEvidenceLinker`, `StaticDataResolver`, and the existing error envelope/request ID.
- Produces: strict `JointEvidenceRequest`, `JointEvidenceResponse`, `JointEvidenceResolver`, enabled/disabled service implementations, and `POST /api/v1/matches/{match_id}/evidence`.

- [ ] **Step 1: Add a match evidence-context method with failing tests**

Extend `MatchResolver` and `MatchService`:

```python
async def get_evidence_context(
    self, *, platform: Platform, match_id: str, puuid: str
) -> MatchSnapshot: ...
```

Reuse `_load_missing_match`. Require the selected PUUID exactly once, not merely at least once. Require `queue_id` in the existing `_ANALYSIS_QUEUES`; otherwise raise 422 `MATCH_EVIDENCE_UNSUPPORTED_MODE`. Preserve `MATCH_NOT_FOUND` and `PLAYER_NOT_IN_MATCH`. Add tests for zero, one, and duplicate selected participant plus queue 400/420 success and queue 450 rejection.

- [ ] **Step 2: Define strict request and response schemas**

Use `DomainModel`/`extra="forbid"`. The request is:

```python
class JointEvidenceRequest(DomainModel):
    platform: Platform
    puuid: str = Field(min_length=1, max_length=128)
    locale: Locale = Locale.EN_US
    replay_id: UUID | None = None
```

The response contains no selected-PUUID field. Define a discriminated `PublicTimelineFact` union for champion kill, elite monster, building, four item event kinds, and participant state. Every variant has `fact_id`, `kind`, `timestamp_ms`, and `relationship` from the closed set `killer/victim/assistant/actor/team_context/not_involved`. Use typed optional details, not `dict[str, object]`.

Define `EvidenceWindowResponse` with window ID, game start/end, ordered categories, trigger fact IDs, coverage, optional covered/video interval, and safe artifact references. Define:

```python
class JointEvidenceData(DomainModel):
    status: Literal["ready"] = "ready"
    platform: Platform
    match_id: str
    locale: Locale
    schema_version: Literal[1]
    facts: tuple[PublicTimelineFact, ...]
    windows: tuple[EvidenceWindowResponse, ...]
    timeline_cache_status: Literal["hit", "miss"]
    replay_link: ReplayLinkSummary | None
    static_data_status: StaticDataStatus
    truncated: bool
    total_window_count: int
    scope_notice_code: Literal["EVIDENCE_ONLY_NO_COACHING"] = (
        "EVIDENCE_ONLY_NO_COACHING"
    )


class JointEvidenceResponse(JointEvidenceData):
    request_id: str
```

`ReplayLinkSummary` contains only `status="linked"` and full/partial/unavailable counts. It does not repeat a replay ID or token.

- [ ] **Step 3: Add failing match-compatible static hydration tests**

Extend `StaticDataResolver` with:

```python
async def hydrate_evidence_items(
    self, *, game_version: str, item_ids: tuple[int, ...], locale: Locale
) -> EvidenceItemCatalog: ...
```

Use `compatible_version` and the existing locale mapping/catalog cache. Return localized names and image URLs for known item IDs. When versions/catalog/items are unavailable, return numeric IDs with `name=None`, `image_url=None`, and the existing degraded `StaticDataStatus`. Hydration failure must not fail evidence preparation.

- [ ] **Step 4: Add failing service-composition tests**

Define:

```python
class JointEvidenceResolver(Protocol):
    async def prepare(
        self,
        *,
        match_id: str,
        request: JointEvidenceRequest,
        replay_token: str | None,
    ) -> JointEvidenceData: ...
```

Test call order and outputs for Timeline-only, ready Replay full/partial linkage, empty supported facts/windows, cache hit/miss propagation, static-data degradation, stable relationship projection, truncation metadata, and all public errors. Assert a selected PUUID appears only in the request/internal collaborator calls, never in `model_dump_json()` or IDs.

- [ ] **Step 5: Add conditional bearer parsing tests**

Extract a pure bounded bearer parser in `services/replays/security.py` and keep `api/replays.py::require_replay_token` as a compatibility wrapper. For the evidence endpoint:

- no `replay_id` and no Authorization header is valid;
- no `replay_id` with any Authorization header is 422 `VALIDATION_ERROR`;
- `replay_id` with missing, malformed, empty, or over-512-byte bearer token is uniform 404 `REPLAY_NOT_FOUND`;
- `replay_id` with a valid bearer token passes only the token to the service.

Never include the submitted token in an assertion failure message, log, metric, or response.

- [ ] **Step 6: Add failing endpoint contract tests**

Cover strict unknown-field rejection, path length, all 16 platforms, both locales, request ID agreement, disabled 404 `NOT_FOUND`, every error/status pair in the approved design, and a successful strict body. Assert output excludes selected PUUID, object key, hash, path, token, and access URL fields.

- [ ] **Step 7: Add failing service/API metric tests**

Add:

```text
joint_evidence_windows_total{result}
joint_evidence_window_truncations_total{result}
joint_evidence_replay_coverage_total{coverage}
joint_evidence_api_requests_total{outcome,error_code}
```

Allowed window `result` is `planned`; truncation `result` is `truncated/not_truncated`; coverage is `full/partial/unavailable`; API `outcome` is `ready/error` and `error_code` is from a fixed approved set plus `none`. No identifiers or free-form labels.

- [ ] **Step 8: Run the service/API tests and observe the red phase**

```bash
cd backend
.venv/bin/pytest -q tests/test_match_service.py tests/test_static_data.py tests/test_replay_security.py tests/test_replay_api.py tests/test_joint_evidence_service.py tests/test_evidence_api.py tests/test_evidence_metrics.py tests/test_app_factory.py
```

- [ ] **Step 9: Implement composition and dependency wiring**

Create the enabled service only when `joint_evidence_enabled` is true. Construct `MatchService` once, then inject it into both `AppServices.match_service` and `JointEvidenceService`. Inject `SqlTimelineRepository`, `TimelineService`, planner, linker, static resolver, and the shared metrics registry. When disabled, use `DisabledJointEvidenceService` that always raises 404 `NOT_FOUND`.

Add `joint_evidence_service` to `AppServices` with a backward-compatible disabled default so unrelated tests do not all require fake implementations. The route calls only `services.joint_evidence_service`.

- [ ] **Step 10: Run focused tests, backend verification, and commit**

```bash
cd backend
.venv/bin/pytest -q tests/test_match_service.py tests/test_static_data.py tests/test_replay_security.py tests/test_replay_api.py tests/test_joint_evidence_service.py tests/test_evidence_api.py tests/test_evidence_metrics.py tests/test_app_factory.py
.venv/bin/ruff check app tests/test_match_service.py tests/test_static_data.py tests/test_replay_security.py tests/test_replay_api.py tests/test_joint_evidence_service.py tests/test_evidence_api.py tests/test_evidence_metrics.py tests/test_app_factory.py
.venv/bin/mypy
cd ..
git diff --check
git add backend/app/schemas backend/app/services/evidence/service.py backend/app/services/matches.py backend/app/services/static_data/resolver.py backend/app/services/replays/security.py backend/app/api/replays.py backend/app/api/matches.py backend/app/core/dependencies.py backend/app/core/metrics.py backend/tests/conftest.py backend/tests/test_match_service.py backend/tests/test_static_data.py backend/tests/test_replay_security.py backend/tests/test_replay_api.py backend/tests/test_joint_evidence_service.py backend/tests/test_evidence_api.py backend/tests/test_evidence_metrics.py backend/tests/test_app_factory.py
git commit -m "feat: expose joint match evidence API"
```

---

## Task 7: Add the typed bilingual on-demand evidence UI

**Files:**

- Modify: `frontend/src/api/schemas.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/replays/storage.ts`
- Modify: `frontend/src/components/replay-section.tsx`
- Create: `frontend/src/components/evidence-section.tsx`
- Modify: `frontend/src/components/replay-artifact-gallery.tsx`
- Modify: `frontend/src/components/match-detail-client.tsx`
- Modify: `frontend/src/i18n/messages.ts`
- Modify: `frontend/src/i18n/zh-CN.ts`
- Modify: `frontend/src/i18n/en-US.ts`
- Modify: `frontend/src/app/globals.css`
- Modify: `frontend/tests/api-client.test.ts`
- Modify: `frontend/tests/replay-storage.test.ts`
- Modify: `frontend/tests/replay-section.test.tsx`
- Create: `frontend/tests/evidence-section.test.tsx`
- Modify: `frontend/tests/match-detail-page.test.tsx`
- Modify: `frontend/tests/i18n.test.ts`

**Interfaces:**

- Consumes: strict backend evidence response, existing Replay capability/token, Replay artifact manifest/blob clients, current match context, and bilingual message contract.
- Produces: `prepareMatchEvidence(...)`, backward-compatible stored Replay status, and `EvidenceSection` with explicit user activation.

- [ ] **Step 1: Add failing strict Zod schema tests**

Mirror every backend discriminated fact variant, window coverage shape, safe artifact reference, replay summary, static-data status, and `EVIDENCE_ONLY_NO_COACHING`. Use `.strict()` at every object level. Reject extra coaching/score fields, unknown fact kinds/categories/relationships, invalid intervals, PUUID-shaped duplicate response fields, and artifact access/object-key fields.

- [ ] **Step 2: Add failing API client tests**

Define:

```typescript
export type PrepareMatchEvidenceInput = {
  matchId: string;
  platform: Platform;
  puuid: string;
  locale: Locale;
  replay?: { replayId: string; accessToken: string };
};
```

`prepareMatchEvidence` posts to the encoded match path, sends `replay_id: null` without Authorization for Timeline-only, and sends both replay ID and bearer token for linked evidence. Assert AbortSignal forwarding and strict success/error parsing.

- [ ] **Step 3: Add failing backward-compatible capability-status tests**

Move `findCapabilityForMatch` from `replay-section.tsx` into `replays/storage.ts` and export:

```typescript
findReplayCapabilityForMatch(
  matchId: string,
  requiredStatus?: ReplayStatus,
): ReplayCapability | null
```

Add `status: ReplayStatus | null` to the stored capability. Loading a valid legacy record without `status` yields `status: null` rather than deleting the token. Every create/poll/status transition updates the stored status and timestamp. Evidence lookup requests only the newest capability for the same match whose status is `ready`.

- [ ] **Step 4: Write failing UI state tests before the component**

Cover:

- page load renders the idle button and makes no evidence request;
- click enters a polite live region and sends exactly one request;
- subsequent match/locale/platform/PUUID prop changes abort stale work and reset to idle;
- ready Timeline-only, ready linked, partial coverage, unavailable coverage, empty facts/windows, retryable error, and non-retryable error;
- an eligible ready capability includes replay ID/token;
- `REPLAY_NOT_FOUND` removes the stale capability and automatically retries once Timeline-only without Authorization;
- `REPLAY_EVIDENCE_NOT_READY` leaves the capability, shows a retryable state, and does not fabricate linkage;
- linked artifact IDs are joined only to the separately authorized `getReplayArtifacts` manifest;
- a missing artifact manifest entry renders no image and never invents an access URL;
- trigger is keyboard accessible, loading uses `role="status"`/`aria-live="polite"`, failures use `role="alert"`, and images have localized game-time alt text.

- [ ] **Step 5: Run the frontend tests and observe the red phase**

```bash
cd frontend
pnpm test -- api-client.test.ts replay-storage.test.ts replay-section.test.tsx evidence-section.test.tsx match-detail-page.test.tsx i18n.test.ts
```

- [ ] **Step 6: Implement the evidence client and state machine**

Create `EvidenceSection` with `idle/loading/ready/error` state and a request key. Resolve a ready local capability only when the user clicks. For linked responses, fetch the existing authorized artifact manifest, filter by the safe artifact IDs in each window, and reuse `ReplayArtifactGallery`; never use a Timeline response as a media URL.

If a linked request gets `REPLAY_NOT_FOUND`, remove that exact capability and retry Timeline-only at most once. Other errors follow their backend `retryable` flag. Abort work on unmount/request-key change.

- [ ] **Step 7: Add neutral bilingual messages and render cards**

Add complete `zh-CN` and `en-US` keys for the prepare button, loading, empty, evidence-only notice, fact kinds, relationships, four neutral categories, game interval, trigger count, full/partial/unavailable coverage, Timeline-only state, linked frames, retry, and each J1 error.

Do not use Chinese or English words equivalent to mistake, good/bad play, score, blame, awareness, mechanics, intent, caused by, or therefore. Cards show recorded facts, time range, triggers, coverage, and available authorized frames only.

- [ ] **Step 8: Mount below Replay and style within the existing visual system**

Render `EvidenceSection` after `ReplaySection` in `match-detail-client.tsx`. Preserve current platform/PUUID propagation. Add responsive styles using the existing page tokens/classes; do not add a UI library or a new global design system.

- [ ] **Step 9: Run frontend verification and commit**

```bash
cd frontend
pnpm test -- api-client.test.ts replay-storage.test.ts replay-section.test.tsx evidence-section.test.tsx match-detail-page.test.tsx i18n.test.ts
pnpm lint
pnpm typecheck
pnpm build
cd ..
git diff --check
git add frontend/src/api frontend/src/replays/storage.ts frontend/src/components/replay-section.tsx frontend/src/components/evidence-section.tsx frontend/src/components/replay-artifact-gallery.tsx frontend/src/components/match-detail-client.tsx frontend/src/i18n frontend/src/app/globals.css frontend/tests/api-client.test.ts frontend/tests/replay-storage.test.ts frontend/tests/replay-section.test.tsx frontend/tests/evidence-section.test.tsx frontend/tests/match-detail-page.test.tsx frontend/tests/i18n.test.ts
git commit -m "feat: add bilingual joint evidence UI"
```

---

## Task 8: Close privacy, real smoke, Compose, documentation, and full regression gates

**Files:**

- Modify: `backend/app/services/riot/smoke.py`
- Modify: `scripts/smoke_riot.py`
- Modify: `scripts/smoke_replay.py`
- Modify: `scripts/e2e_replay_compose.sh`
- Modify: `Makefile`
- Modify: `docker-compose.yml`
- Modify: `backend/tests/test_smoke_script.py`
- Modify: `backend/tests/test_replay_smoke_script.py`
- Modify: `backend/tests/test_runtime_privacy.py`
- Modify: `backend/tests/test_safe_logging.py`
- Modify: `backend/tests/test_replay_runtime_privacy.py`
- Create: `backend/tests/test_joint_evidence_privacy.py`
- Modify: `README.md`

**Interfaces:**

- Consumes: completed J1 public API, existing local smoke identities, Replay lifecycle, Compose stack, and internal metrics endpoint.
- Produces: safe Timeline-only and Replay-linked smoke proofs, rollout instructions, privacy regression checks, and exact final verification evidence.

- [ ] **Step 1: Write failing Timeline smoke tests**

Extend `run_smoke` to keep the already resolved PUUID and a match whose `detail_supported` and `analysis_supported` fields are both true in memory, then call the evidence endpoint twice when `JOINT_EVIDENCE_ENABLED=true`. Assert semantic equality of status/schema/fact IDs/window IDs and that the second request is a cache hit. Print only:

```text
Joint evidence smoke passed: outcome=ready facts=<count> windows=<count> cache=consistent elapsed_ms=<n> request_id=<safe-id>
```

Never print the Riot ID, PUUID, platform, match ID, fact/window IDs, raw events, URL, headers, or response body. When the flag is false, print only a safe disabled skip line.

- [ ] **Step 2: Write failing authorized Replay-linked smoke tests**

In `scripts/smoke_replay.py`, after Replay reaches ready and before delete, call the evidence endpoint only when the feature flag is enabled. Pass the in-memory replay ID/token but print only linked outcome, window count, coverage counts, artifact-reference count, elapsed time, and safe request ID. Assert returned artifact references are a subset of the separately authorized Replay artifact manifest. Continue through delete and zero-residue checks.

- [ ] **Step 3: Add privacy and safe-logging regression tests**

Seed sentinel API key, PUUID, match ID, Replay ID, token, object key, presigned URL, and raw event values. Exercise success and every J1 failure path, capture logs, metrics text, response JSON, and CLI output, and assert each sentinel is absent from every surface where the specification forbids it. Assert normalized cache JSON is the only Timeline persistence and contains no raw-event container.

- [ ] **Step 4: Run focused smoke/privacy tests and observe the red phase**

```bash
cd backend
.venv/bin/pytest -q tests/test_smoke_script.py tests/test_replay_smoke_script.py tests/test_runtime_privacy.py tests/test_safe_logging.py tests/test_replay_runtime_privacy.py tests/test_joint_evidence_privacy.py
```

- [ ] **Step 5: Implement safe smoke extensions and Compose enablement**

Add a `smoke-joint-evidence` Make target only if it improves separation; otherwise keep `make smoke-riot` authoritative. For `e2e-replay-compose`, explicitly export `JOINT_EVIDENCE_ENABLED=true` for this ephemeral verification run while keeping Compose's declared default false. Update the script's documented lifecycle to include linked evidence before deletion.

- [ ] **Step 6: Document local use, rollout, rollback, and cost boundary**

Update README with:

1. migration `0004` before enabling;
2. backend deploy with flag false, then compatible frontend, then TTLs, then flag true;
3. Timeline-only and authorized Replay-linked smoke commands;
4. metrics to monitor and their closed labels;
5. rollback by setting only `JOINT_EVIDENCE_ENABLED=false`, leaving migration in place;
6. J1 makes no OpenAI call and does not create new media, so local external service cost remains approximately zero beyond existing Riot/local compute usage;
7. only user-owned or explicitly authorized recordings may enter Replay.

- [ ] **Step 7: Run complete unit, lint, type, and build verification**

```bash
make verify
```

Record exact backend passed/skipped/deselected counts, exact frontend passed/file counts, MyPy file count, and build result from this run.

- [ ] **Step 8: Run complete PostgreSQL verification**

```bash
export TEST_DATABASE_URL='postgresql+asyncpg://lol_ai_coach:lol_ai_coach@127.0.0.1:5432/lol_ai_coach_test'
make verify-postgres
make verify-replay-postgres
```

Record exact counts. Confirm Alembic head is `0004_match_timelines` and the work database contains no raw Timeline table/column.

- [ ] **Step 9: Run media, storage, real Riot, and Compose gates**

```bash
make verify-replay-ffmpeg
# Run the existing real S3-compatible streaming gate with the configured local MinIO values.
make smoke-riot
make e2e-replay-compose
```

Do not echo environment values. Confirm the real Timeline request repeats consistently, the linked flow uses only authorized Replay artifacts, both locales return 200, `artifacts=21` remains the Replay baseline unless intentionally changed by existing extraction behavior, delete succeeds, and the Compose replay volume has zero files.

- [ ] **Step 10: Perform the final specification and privacy audit**

Search tracked code and rendered UI text for prohibited concepts and unsafe fields:

```bash
rg -n -i "openai|mistake|good play|bad play|score|awareness|mechanics|intent|caused by|therefore" backend/app frontend/src
rg -n "raw_payload|raw_response|presigned_url|object_key|access_token|selected_puuid" backend/app/schemas/evidence.py backend/app/services/evidence frontend/src/components/evidence-section.tsx frontend/src/api/schemas.ts
git diff --check
git status --short
```

Review every hit in context. Existing Replay internals may legitimately contain `object_key`/`access_token`; J1 public schemas, evidence logs, evidence metrics, and evidence UI may not. Confirm no real fixture or secret is tracked.

- [ ] **Step 11: Commit final smoke/docs changes**

```bash
git add backend/app/services/riot/smoke.py scripts/smoke_riot.py scripts/smoke_replay.py scripts/e2e_replay_compose.sh Makefile docker-compose.yml backend/tests/test_smoke_script.py backend/tests/test_replay_smoke_script.py backend/tests/test_runtime_privacy.py backend/tests/test_safe_logging.py backend/tests/test_replay_runtime_privacy.py backend/tests/test_joint_evidence_privacy.py README.md
git commit -m "test: verify joint evidence lifecycle"
```

- [ ] **Step 12: Request independent code review before integration**

Provide the reviewer with the approved design, this plan, the eight commit hashes, exact verification counts, real-smoke safe summaries, and any unverified production-only gates. The review must explicitly cover DTO fail-closed behavior, cache corruption handling, single-flight cancellation, Replay deletion race, strict frontend schemas, feature flag defaults, and prohibited coaching language. Fix Critical/Important findings in separate commits and rerun the affected gates plus `make verify` before merging.

## Cursor Task Report Template

After every task, send exactly this information to the user/Codex reviewer:

```text
Task <n> complete
Changed files: <tracked file list>
Commit: <hash> <message>
Focused verification: <command and exact passed/skipped/deselected counts>
Lint/type/build: <exact result for gates run>
Feature flag default: false
Unverified: <explicit remaining gates; never imply they ran>
Safety: no secrets/identifiers/raw Riot responses printed or committed
```

Do not begin the next task until the current commit is reviewed or the user explicitly asks Cursor to continue.
