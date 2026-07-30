# LoL AI Coach Phase 2 Riot Integration Design

- Status: Approved in conversation
- Date: 2026-07-30
- Depends on: Phase 1 foundation at `2e6274b`
- Initial platform: North America (`NA1`)
- Product locales: `zh-CN` and `en-US`

## 1. Purpose

Phase 2 turns the tested Phase 1 shell into a real, bilingual Riot-data browser. A user enters a Riot ID and platform, opens a player page, sees up to ten recent matches, and opens a localized match detail page.

This phase is a data-ingestion and presentation phase. It does not judge positioning, mechanics, intent, awareness, or decision quality. It does not fetch Match Timeline, calculate a coaching score, call an AI provider, or process video.

Riot APIs are the source of truth. OP.GG or another third-party statistics site may be used manually during product research, but the application does not scrape, proxy, or depend on those sites.

## 2. Outcomes

Phase 2 must:

1. Resolve a real Riot ID through Account-V1.
2. Treat `game_name`, `tag_line`, and `platform` as independent fields.
3. Support `NA1` as the only platform while allowing any valid Riot ID tag line.
4. Fetch Summoner-V4 profile data by PUUID.
5. Fetch up to ten most recent Match-V5 match IDs and details.
6. Display unsupported queues without offering analysis.
7. Localize champion and item data through a match-compatible Data Dragon version.
8. Normalize upstream data behind stable public and internal contracts.
9. Cache player, recent-match, completed-match, and static-data results without persisting raw upstream responses.
10. Expose safe, localized failure and degraded states without leaking the Riot API key.
11. Preserve the identifiers and timestamps that a later replay-upload phase needs to bind a video to a match.

## 3. Non-Goals

Phase 2 does not include:

- Match Timeline requests or event parsing.
- Metrics, role thresholds, candidate findings, training goals, or scoring.
- OpenAI calls or AI-generated text.
- Replay upload, object storage, transcoding, frame extraction, or video analysis.
- A high-rank reference-video library.
- Accounts, Riot Sign On, trends, subscriptions, or regions beyond NA1.
- OP.GG scraping or another third-party data dependency.
- Storage of raw Riot or Data Dragon JSON.

## 4. Confirmed Decisions

| Decision | Choice |
| --- | --- |
| Delivery shape | Complete visible vertical slice |
| Riot ID | Independent game name and tag line |
| Initial platform | `NA1` only |
| Account and Match route | `americas.api.riotgames.com` |
| Summoner route | `na1.api.riotgames.com` |
| Recent matches | Up to ten latest match IDs, without queue filtering |
| Reviewable queues | `400` Normal Draft and `420` Ranked Solo/Duo |
| Static data | Match-compatible Data Dragon version, `zh_CN` / `en_US` |
| Cache | PostgreSQL for normalized Riot data; in-process cache for Data Dragon |
| Database migrations | Alembic |
| Frontend validation | Typed client plus runtime response schemas |
| State management | Local page/component state; no global state library |
| Replay roadmap | Separate phase immediately after Riot integration |
| Reference-video policy | Owner-uploaded or explicitly authorized material only |
| Rule promotion | AI may propose; a human must approve before use |

## 5. Architecture

```text
Browser
  -> Next.js localized routes and typed API client
  -> FastAPI public API
      -> Riot routing and request policy
          -> Account-V1 (americas)
          -> Summoner-V4 (na1)
          -> Match-V5 (americas)
      -> Riot DTO validation and normalization
      -> Data Dragon version and locale resolution
      -> PostgreSQL repositories and TTL policy
```

The frontend never receives a Riot credential or raw upstream JSON. Public response models contain only fields needed by the Phase 2 pages and stable identifiers needed by later phases.

### 5.1 Backend Modules

Phase 2 adds these focused modules under `backend/app/`:

```text
api/
  players.py          player resolution and recent-match routes
  matches.py          match-detail route
core/
  routing.py          platform and regional route mapping
schemas/
  players.py          public player contracts
  matches.py          public match contracts
services/
  riot/
    client.py         HTTP, authentication, timeout, retry, error mapping
    dto.py            upstream-only validation models
    gateway.py        Account, Summoner, and Match operations
  parsing/
    players.py        Riot player DTOs to internal models
    matches.py        Riot match DTOs to internal models
  static_data/
    client.py         Data Dragon HTTP boundary
    resolver.py       version and locale selection
repositories/
  players.py
  recent_matches.py
  matches.py
models/
  player.py
  recent_match_cache.py
  match.py
```

HTTP routes orchestrate services; they do not parse Riot payloads or contain cache SQL. External clients do not return public API schemas.

### 5.2 Frontend Modules

```text
frontend/src/
  api/
    client.ts         base URL, request IDs, safe error decoding
    schemas.ts        runtime schemas and inferred response types
  app/[locale]/
    page.tsx          active Riot ID search
    players/[puuid]/page.tsx
    matches/[matchId]/page.tsx
  components/
    player-header.tsx
    recent-match-list.tsx
    recent-match-card.tsx
    match-team-table.tsx
    data-state.tsx
```

The API client is small and product-specific. Phase 2 does not add Redux, a generic query framework, or generated clients unless implementation evidence shows the manual client is becoming error-prone.

## 6. Riot Identity and Routing

A Riot ID consists of `game_name` and `tag_line`. The tag line is not a region and must not be defaulted to `NA1`. For example, an NA player may have a numeric or otherwise unrelated tag line.

The search form submits:

```json
{
  "game_name": "PlayerName",
  "tag_line": "1115",
  "platform": "NA1"
}
```

The backend maps `NA1` to:

- Regional route `americas` for Account-V1 and Match-V5.
- Platform route `na1` for Summoner-V4.

Routing is a closed, typed map. Adding another platform later requires an explicit map entry and tests; unknown values are rejected before any upstream request.

Input validation trims leading and trailing whitespace, accepts `game_name` values from 1 to 32 Unicode code points and `tag_line` values from 1 to 16 Unicode code points, and leaves Riot to decide whether the bounded identifier exists. These transport-safety caps deliberately avoid an ASCII-only pattern or a stricter local replica of changeable Riot ID rules.

## 7. Data Flow

### 7.1 Player Resolution

1. Validate `platform`, `game_name`, and `tag_line`.
2. Query the player cache using a normalized lookup key.
3. On a miss, call Account-V1 by Riot ID on `americas` to obtain the PUUID.
4. Call Summoner-V4 by PUUID on `na1` for summoner level and profile-icon ID.
5. Normalize and cache the player for 15 minutes.
6. Return a public `PlayerProfile`.

Case normalization is used for cache lookup only. The product displays the canonical game name and tag line returned by Riot.

### 7.2 Recent Matches

1. Validate the PUUID, platform, and `count` (`1..10`, default `10`).
2. Reuse a recent-match-list cache entry younger than two minutes.
3. Otherwise fetch the latest Match-V5 IDs without a queue filter.
4. Reuse cached normalized match details where available.
5. Fetch missing details with a maximum concurrency of four.
6. Preserve Riot's newest-to-oldest order.
7. Mark queue `400` and `420` as reviewable; keep all other returned queues visible and disabled for future analysis.

The route returns fewer than ten matches when Riot returns fewer than ten. It never fabricates or substitutes older matches.

### 7.3 Match Detail

1. Validate `match_id`, `platform`, `puuid`, and `locale`.
2. Reuse a cached normalized match when present.
3. Otherwise fetch Match-V5 detail, validate critical fields, and normalize it.
4. Confirm the selected PUUID is one of the ten participants.
5. Resolve a compatible Data Dragon version from `gameVersion`.
6. Hydrate localized champion and item display data.
7. Return selected-player detail plus both five-player teams.

No Timeline request is made in Phase 2.

## 8. Public API

### 8.1 Resolve Player

```http
GET /api/v1/players/resolve?platform=NA1&game_name=PlayerName&tag_line=1115
```

The response contains:

- `puuid`
- canonical `game_name` and `tag_line`
- `platform`
- `summoner_level`
- `profile_icon_id`
- resolved profile-icon URL and static-data version when available

### 8.2 Recent Matches

```http
GET /api/v1/players/{puuid}/matches?platform=NA1&count=10&locale=zh-CN
```

Each list item contains:

- Match ID, queue ID, start time, duration, and game version.
- Selected participant's champion, role, win/loss, K/D/A, CS, and final items.
- Localized champion and item display data when available.
- `analysis_supported` and a stable reason code when false.
- Static-data availability metadata.

### 8.3 Match Detail

```http
GET /api/v1/matches/{match_id}?platform=NA1&puuid={puuid}&locale=en-US
```

The response contains:

- Match metadata and data-sufficiency status.
- The selected participant's full Phase 2 summary.
- Blue and red teams with five normalized participants each.
- Localized champion/item display data or explicit unavailable values.
- A visible capability notice stating that no coaching judgment has been produced.

## 9. Internal Contracts

Phase 2 introduces internal models independent of Riot field names:

- `PlatformRoute`
- `RiotAccount`
- `PlayerProfile`
- `RecentMatchReference`
- `MatchSummary`
- `MatchDetail`
- `ParticipantSnapshot`
- `StaticAsset`
- `StaticDataStatus`

Riot DTOs are private to `services/riot`. They accept unknown extra upstream fields but require critical identity, match, team, and participant fields. Non-critical missing statistics become typed unavailable values; missing critical structure becomes `RIOT_INVALID_RESPONSE`.

Public responses never include a full upstream response or arbitrary pass-through dictionaries.

## 10. Persistence and Caching

Alembic manages PostgreSQL migrations.

### 10.1 `players`

- Internal UUID.
- Unique PUUID.
- Canonical game name and tag line.
- Platform.
- Summoner level and profile-icon ID.
- Fetched and updated timestamps.

### 10.2 `recent_match_caches`

- Player and platform key.
- Ordered Match ID array.
- Fetched timestamp and expiry timestamp.

### 10.3 `matches`

- Match ID primary key.
- Platform, queue ID, game version, start time, and duration.
- Normalized match snapshot as validated JSONB.
- Normalized schema version and content hash.
- Fetched timestamp.

Completed match data is treated as immutable and retained for 30 days. The schema version allows controlled re-normalization later. A separate `player_match_stats` table remains deferred until Phase 3 needs metric queries.

Data Dragon JSON is cached in process by version and locale. A process restart may fetch it again; Redis and persistent static-data storage are not required for the invited beta.

Raw Riot and Data Dragon responses are transient and discarded after successful validation and normalization.

## 11. Data Dragon

The resolver reads Riot's Data Dragon versions list and matches the major/minor patch family from Match-V5 `gameVersion`. When multiple builds exist for a patch family, it selects the newest compatible build.

Locale mapping is explicit:

- `zh-CN` -> `zh_CN`
- `en-US` -> `en_US`

The backend returns localized names and complete asset URLs. The frontend does not construct versioned URLs or guess versions.

If no compatible version, champion, or item exists:

- The match and numeric statistics still render.
- The missing display field is typed as unavailable.
- The UI shows a localized static-data warning.
- A current-version value is not silently substituted.

## 12. Riot Request Policy

The Riot API key exists only in backend configuration and is sent through the documented authentication header over HTTPS.

Every upstream operation defines:

- Connection and response timeouts.
- A maximum total request duration.
- Bounded retries for idempotent GET requests only.
- Safe status and error translation.
- Request-correlation logging without secret or full-PUUID logging.

Policy by error class:

- `400`: internal request-contract failure; do not retry.
- `401` / `403`: `RIOT_AUTH_FAILED`; do not retry.
- Player `404`: `PLAYER_NOT_FOUND`; do not retry.
- Match `404`: `MATCH_NOT_FOUND`; do not retry.
- `429`: parse a bounded `Retry-After`; retry only when the delay fits the synchronous request budget, otherwise return `RIOT_RATE_LIMITED` with a safe retry value.
- `5xx`, connection error, or timeout: one bounded retry with jitter, then `RIOT_UNAVAILABLE`.
- Malformed critical response: `RIOT_INVALID_RESPONSE`; do not retry automatically.

Readiness checks database connectivity and the presence of required Riot configuration, but never calls Riot or consumes rate limits.

## 13. Error and Degradation Contract

All routes keep the existing error envelope:

```json
{
  "error": {
    "code": "RIOT_RATE_LIMITED",
    "message": "Riot API rate limit reached.",
    "params": {"retry_after_seconds": 12},
    "retryable": true,
    "request_id": "request-correlation-id"
  }
}
```

Phase 2 adds stable codes for:

- `INVALID_RIOT_ID`
- `PLAYER_NOT_FOUND`
- `MATCH_NOT_FOUND`
- `PLAYER_NOT_IN_MATCH`
- `RIOT_NOT_CONFIGURED`
- `RIOT_AUTH_FAILED`
- `RIOT_RATE_LIMITED`
- `RIOT_UNAVAILABLE`
- `RIOT_INVALID_RESPONSE`

`STATIC_DATA_UNAVAILABLE` is a stable code inside successful response sufficiency metadata, not a top-level failed-request envelope.

The frontend translates codes and parameters. Safe English messages remain fallbacks and never contain upstream bodies, exception strings, credentials, or full request URLs containing player identifiers.

A Data Dragon failure is degraded success rather than a failed match response. A Riot identity or match failure cannot be replaced by stale data unless the response explicitly reports the stale cache timestamp.

## 14. Frontend Experience

### 14.1 Search

The Phase 1 form becomes functional. The game name, tag line, and platform remain separate controls. Placeholder text does not imply that the tag line equals the platform.

Successful resolution navigates to:

```text
/{locale}/players/{puuid}?platform=NA1
```

### 14.2 Player Page

The player page shows:

- Canonical Riot ID, level, and profile icon.
- Up to ten recent matches.
- Champion, result, role, K/D/A, CS, duration, time, and final items.
- A clear reviewable or unsupported-queue state.

### 14.3 Match Detail Page

The detail page route is:

```text
/{locale}/matches/{match_id}?platform=NA1&puuid={puuid}
```

It shows match metadata, the selected participant, and both complete teams. The selected player is visually and semantically identified. It also displays a scope notice: the page shows recorded data and has not evaluated gameplay behavior.

### 14.4 States and Accessibility

Both locales cover loading, empty, not-found, authentication, rate-limit, unavailable, malformed-response, static-data-degraded, and retry states.

The pages use semantic headings, labelled controls, keyboard-visible focus, meaningful image alternatives, non-color-only result indicators, and readable mobile layouts. Loading skeletons do not replace accessible status text.

Switching locale fetches locale-dependent static display data without forcing a new Riot match fetch when normalized cached data is available.

## 15. Security, Privacy, and Observability

- `.env` remains ignored; only `.env.example` documents an empty key.
- No Riot key or authorization header appears in frontend bundles, logs, errors, fixtures, or snapshots.
- Logs contain request ID, route, safe status, upstream service, latency, retry count, cache status, and a hashed or truncated player reference.
- Full PUUIDs may appear in API routes where required by the approved contract, but operational logs redact them.
- CORS keeps an explicit allowlist.
- Inputs and `count` are bounded before upstream requests.
- The application does not expose raw Riot responses as a data-broker endpoint.
- Riot's required third-party disclaimer remains visible in both locales.

## 16. Testing Strategy

### 16.1 Backend Unit and Contract Tests

Tests use deterministic fakes for all Riot and Data Dragon calls. They cover:

- Independent tag line and platform values.
- NA1 platform/regional routing.
- Request headers, encoding, timeout, and bounded concurrency.
- Success responses and `400`, `401`, `403`, `404`, `429`, `5xx`, timeout, and malformed payloads.
- `Retry-After` bounds and retry exhaustion.
- Critical versus optional missing fields.
- Newest-to-oldest recent-match ordering and counts below ten.
- Queue `400` / `420` support flags.
- Data Dragon patch-family and locale selection.
- Static-data degraded success.
- Cache hit, expiry, and immutable-match reuse.
- Error-envelope, request-ID, CORS, and secret-redaction behavior.

Fixtures contain synthetic values and fake keys, not copied user responses or committed real identifiers.

### 16.2 PostgreSQL Integration Tests

Repository and migration tests use PostgreSQL, not SQLite. CI provisions a PostgreSQL service and runs migrations, uniqueness, JSONB, expiry, and reuse tests.

`make verify` remains the canonical non-Docker unit/frontend quality gate and excludes tests marked `integration`. `make verify-postgres` requires `TEST_DATABASE_URL`, fails rather than skips when that value or PostgreSQL is unavailable, and runs migrations plus every test marked `integration`. CI runs both commands, with PostgreSQL supplied as a service.

Because the current Mac has no Docker CLI, local `make verify` does not prove PostgreSQL integration. The verification output and README must state that distinction. Phase 2 is not accepted until `make verify-postgres` has passed in a real PostgreSQL environment such as CI.

### 16.3 Frontend Tests

Frontend tests cover:

- Valid search navigation and Unicode Riot IDs.
- Tag lines that differ from the platform.
- Player header and recent-match cards.
- Supported and unsupported queues.
- Ten-player match rendering and selected-player identification.
- Localized champion/item content.
- All loading, degraded, error, and retry states.
- Runtime rejection of invalid backend responses.
- Locale switching and cache behavior.
- Core mobile and accessibility behavior.

### 16.4 Live Riot Smoke Test

A separate `make smoke-riot` command uses `RIOT_API_KEY` plus `RIOT_SMOKE_GAME_NAME`, `RIOT_SMOKE_TAG_LINE`, and `RIOT_SMOKE_PLATFORM` from the ignored root `.env`. It requires a real NA Riot ID at runtime. The identifier and key are never committed or printed by the command.

The smoke flow resolves the player, returns recent matches, opens one detail, switches locale, and repeats a request to confirm cache reuse. Automated CI never uses a development key.

## 17. Phase 2 Acceptance Criteria

Phase 2 is complete when:

1. A real NA Riot ID with a tag line unrelated to `NA1` resolves successfully.
2. The player page shows up to ten real recent matches in Riot order.
3. Supported and unsupported queues are displayed correctly.
4. A match detail shows exactly ten participants for a standard ten-player match.
5. Champion and item names/assets match the selected locale and a compatible match patch.
6. Static-data failure preserves the numeric match view with a visible warning.
7. Second identical requests demonstrate the specified cache behavior.
8. Riot credential, limit, not-found, timeout, unavailable, and malformed-response paths are safe and localized.
9. No key, raw upstream response, or real fixture identifier is committed or logged.
10. Unit, frontend, lint, format, type, and production-build checks pass.
11. PostgreSQL migration and repository integration tests pass in a PostgreSQL environment.
12. The page makes no coaching, positioning, mechanics, awareness, or intent claim.

## 18. Replay-Ready Boundary and Revised Roadmap

Replay analysis is an independent subsystem and receives its own design and implementation plan after Phase 2. Phase 2 stores only the binding metadata the replay system will need: Match ID, PUUID, platform, queue, game version, start time, and duration.

The revised order is:

1. Phase 2: Riot identity, matches, localized static data, and replay-binding metadata.
2. Replay Phase R1: authorized upload, temporary object storage, validation, transcoding, match synchronization, timestamped frame/clip evidence, and deletion policy.
3. Joint Evidence Phase: Timeline plus video evidence, metrics, candidate findings, and deterministic score.
4. AI Review Phase: structured explanation grounded in approved data and replay evidence.
5. Reference Library Phase: authorized, annotated high-rank examples for evaluation and retrieval.

Reference-video rules are:

- The system accepts only uploader-owned or explicitly authorized material.
- Public URLs may be stored as research references with human-authored notes, but their media is not copied into the product without permission.
- Purchased viewing access does not by itself authorize ingestion, AI processing, training, redistribution, or commercial use.
- Current general OpenAI API models accept image rather than direct video input, so R1 will design timestamped frame/clip extraction unless provider capabilities change and are re-verified.
- AI may observe clips and propose candidate coaching rules.
- A candidate rule records role, champion context, match phase, preconditions, observed action, trade-offs, counterexamples, patch, source clip, timestamp, sample count, and confidence.
- A human must approve and version a rule before it may influence a user review.
- A small authorized evaluation/reference set precedes any decision to train a custom model.

## 19. Authoritative References

- Riot League of Legends APIs, Riot ID transition, routing, Data Dragon, and game policy: <https://developer.riotgames.com/docs/lol>
- Riot API key types and rate limiting: <https://developer.riotgames.com/docs/portal>
- Riot general policies: <https://developer.riotgames.com/policies/general>
- Riot Terms of Service and Legal Jibber Jabber: <https://www.riotgames.com/en/terms-of-service-update-2024> and <https://www.riotgames.com/en/legal>
- OpenAI model input capabilities: <https://developers.openai.com/api/docs/models>
- Chinese Copyright Law licensing scope: <https://www.npc.gov.cn/c2/c30834/202011/t20201119_308796.html>
