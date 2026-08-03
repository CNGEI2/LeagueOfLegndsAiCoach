# LoL AI Coach — Joint Evidence J1 Design

**Status:** Approved design, 2026-08-02
**Implementation owner:** Cursor
**Design and review owner:** Codex

## 1. Goal

Joint Evidence J1 adds an on-demand Riot Match-V5 Timeline evidence path to the existing bilingual match-detail and Replay R1 product. It normalizes recorded match events, creates deterministic candidate time windows, maps those windows into an authorized ready replay when available, and links existing replay frames that fall inside each window.

J1 is evidence infrastructure. It does not score play, label mistakes or strengths, infer causality or intent, generate new video clips, or call OpenAI.

## 2. Existing Foundation

J1 builds on the integrated repository state after:

- Phase 2 Riot account, match, static-data, and bilingual match-detail support;
- automatic Riot platform detection over the closed four-region and sixteen-platform catalog;
- Replay R1 authorized upload, normalization, game-time anchoring, verification-frame extraction, capability-token authorization, retention, and deletion;
- the invariant that player and match identity carries an explicit platform and that player persistence is bounded by `platform + puuid`.

The existing `RiotGateway`, `RiotHttpClient`, match cache, replay service, replay artifact repository, safe error envelope, metrics registry, and `game_to_video_time` mapping are extended or composed rather than replaced.

## 3. Product Guarantees

1. Timeline is fetched only after the user explicitly asks to prepare evidence.
2. The Timeline request uses the regional host from the closed routing catalog. No user value can become a hostname.
3. Timeline facts describe recorded order and state only. Temporal proximity is never presented as causality.
4. Replay linkage is optional. Timeline-only evidence remains usable when no authorized ready replay exists.
5. Replay linkage never bypasses the existing possession token. An invalid token, a mismatched binding, or a deleted replay remains indistinguishable from a missing replay.
6. Public responses and logs never expose replay object keys, local paths, hashes, access tokens, presigned URLs, raw Riot payloads, or raw upstream URLs.
7. Public evidence identifiers never contain a PUUID.
8. The feature is bilingual in `zh-CN` and `en-US` and remains disabled by default until migration, backend, and frontend rollout is complete.

## 4. Scope

### 4.1 Included

- Match-V5 Timeline retrieval by `platform + match_id` through the platform's fixed regional route.
- Strict validation of critical Timeline metadata, participants, frames, participant frames, and supported events.
- Normalized Timeline caching with positive and short negative TTLs.
- In-process single-flight for identical Timeline cache misses.
- Deterministic Timeline facts for the selected player and match context.
- Deterministic candidate evidence windows for selected-player combat involvement, deaths, team elite-monster events, and team building events.
- Mapping each window to the available interval of an authorized ready replay.
- Linking existing replay artifacts whose game time lies inside the covered portion of a window.
- A strict public API and match-detail UI for timeline-only and replay-linked evidence.
- Closed metrics, safe logging, real Riot smoke, and full regression verification.

### 4.2 Excluded

- OpenAI or any other model call.
- Coaching scores, performance grades, mistake or strength labels, training goals, or advice.
- Claims about positioning, mechanics, awareness, communication, intent, or causality.
- OCR, computer vision, audio analysis, or automatic confirmation of the manual `00:00` replay anchor.
- New FFmpeg clips, event-specific frame extraction, or a new media job kind.
- High-rank reference libraries, third-party video downloads, or ingestion of content without ownership or explicit authorization.
- Raw Riot Timeline storage or raw-response fixtures copied from a real player.

## 5. Architecture

The request remains synchronous: one bounded Riot request on a cache miss, followed by deterministic local normalization, planning, and replay linkage. J1 does not add a queue or worker.

```text
Match evidence API
  -> JointEvidenceService
       -> TimelineService
            -> TimelineRepository
            -> RiotGateway.get_match_timeline
            -> TimelineNormalizer
       -> EvidenceWindowPlanner
       -> ReplayEvidenceLinker
            -> ReplayService authorization
            -> ReplayArtifactRepository
  -> strict JointEvidenceResponse
```

The units have independent responsibilities:

- `RiotGateway` selects the fixed regional host, percent-encodes the match ID, calls `/lol/match/v5/matches/{matchId}/timeline`, and validates the upstream DTO.
- `TimelineService` owns cache policy, single-flight, upstream error propagation, normalization, and repository writes.
- `TimelineNormalizer` is a pure boundary from Riot-specific DTOs to repository-owned facts and snapshots.
- `EvidenceWindowPlanner` is a pure function from normalized facts, selected participant, selected team, and match duration to neutral candidate windows.
- `ReplayEvidenceLinker` authorizes an optional replay, intersects windows with replay coverage, maps game time to video time, and links existing artifacts.
- `JointEvidenceService` validates match support and selected-player membership and composes the response.

## 6. Riot Boundary

### 6.1 Gateway Operation

Add:

```python
async def get_match_timeline(
    self, *, platform: Platform, match_id: str
) -> TimelineDto: ...
```

The operation uses `routes_for(platform).regional_host`. Its path is:

```text
/lol/match/v5/matches/{percent_encoded_match_id}/timeline
```

The existing HTTP policy remains authoritative:

- `401` / `403` -> `RIOT_AUTH_FAILED`, not retryable;
- `404` -> caller-specific `MATCH_TIMELINE_NOT_FOUND`, not retryable;
- `429` -> `RIOT_RATE_LIMITED`, bounded by the existing total request budget;
- final `5xx`, connection error, or timeout -> `RIOT_UNAVAILABLE`, retryable;
- malformed JSON or invalid critical DTO -> `RIOT_INVALID_RESPONSE`, not retryable.

No response text, URL, API key, match identifier, or player identifier is logged.

### 6.2 DTO Validation

Riot-specific DTOs stay under `app/services/riot`. Critical validation covers:

- top-level metadata and info objects;
- metadata match identity;
- participant mapping with unique participant IDs and PUUIDs;
- a frame interval from 1,000 through 120,000 milliseconds;
- monotonically non-decreasing frame timestamps;
- participant-frame keys that reference known participant IDs;
- non-negative supported-event timestamps;
- required fields for each supported event type.

Unknown upstream object fields are ignored at the DTO boundary so additive Riot fields do not break the product. Unknown event types are not normalized; they increment a closed `ignored` metric. A known event type missing a critical field invalidates the complete Timeline and produces no partial cache record.

## 7. Persistence

Alembic revision `0004` creates `match_timelines`.

| Column | Type | Rule |
| --- | --- | --- |
| `platform` | VARCHAR(8) | composite primary key |
| `match_id` | VARCHAR(64) | composite primary key |
| `result_status` | VARCHAR(16) | `available` or `not_found` |
| `normalized_snapshot` | JSONB nullable | required only for `available` |
| `schema_version` | INTEGER | positive, current value `1` |
| `snapshot_hash` | VARCHAR(64) nullable | required only for `available` |
| `fetched_at` | TIMESTAMPTZ | UTC |
| `expires_at` | TIMESTAMPTZ | indexed, UTC |
| `created_at` | TIMESTAMPTZ | UTC |
| `updated_at` | TIMESTAMPTZ | UTC |

Database checks enforce the two valid result shapes:

- `available`: snapshot and hash are non-null;
- `not_found`: snapshot and hash are null.

The repository boundary is `platform + match_id`. Candidate windows are not stored in J1; they are computed deterministically from the cached normalized snapshot and current replay state. Downgrade removes only the J1 table and indexes.

## 8. Cache and Concurrency

- Successful normalized Timelines cache for 30 days (`2592000` seconds).
- Upstream `404` caches as `not_found` for 5 minutes (`300` seconds).
- Authentication, rate-limit, unavailable, invalid-response, and normalization failures are never cached.
- `get_fresh` requires `expires_at > now`.
- Repository upsert uses the composite identity and converges under concurrent PostgreSQL writes.
- `TimelineService` maintains one in-process task per `platform + match_id`; identical concurrent misses await the same task.
- Caller cancellation does not cancel shared upstream work while another caller remains interested.
- The in-flight entry is removed after success, failure, or cancellation.

Settings:

```text
JOINT_EVIDENCE_ENABLED=false
TIMELINE_CACHE_TTL_SECONDS=2592000
TIMELINE_NOT_FOUND_TTL_SECONDS=300
```

`TIMELINE_CACHE_TTL_SECONDS` is bounded from 3,600 through 7,776,000 seconds. `TIMELINE_NOT_FOUND_TTL_SECONDS` is bounded from 30 through 3,600 seconds. The feature flag remains false in defaults, `.env.example`, Compose, and tests.

## 9. Normalized Timeline Contract

The normalized snapshot is independent of Riot field names. It contains:

- platform, match ID, schema version, and frame interval;
- an internal participant-ID-to-PUUID mapping;
- ordered participant snapshots;
- ordered normalized event facts;
- a deterministic snapshot hash.

### 9.1 Stable Fact IDs

Fact IDs contain platform, match ID, schema version, and normalized source ordinals, but never a PUUID:

```text
timeline:{platform}:{match_id}:v1:frame:{frame_index}:event:{event_index}
timeline:{platform}:{match_id}:v1:frame:{frame_index}:participant:{participant_id}
```

Completed-match input and deterministic normalization make the IDs stable for a given schema version.

### 9.2 Supported Event Facts

J1 normalizes:

- champion kill events, including killer, victim, and assistants;
- elite monster kills, including team, monster type, subtype when present, and position when valid;
- building kills, including team, building type, lane/tower subtype when present, and position when valid;
- `ITEM_PURCHASED`, `ITEM_SOLD`, `ITEM_DESTROYED`, and `ITEM_UNDO` facts. J1 does not invent a synthetic transformation event when Riot does not provide one;
- participant-frame level, current gold, total gold, minion CS, jungle CS, XP, and valid position.

Public facts describe the selected player's relationship as `killer`, `victim`, `assistant`, `actor`, `team_context`, or `not_involved`. They do not expose the selected PUUID.

Missing optional values remain typed unavailable. Zero is not replaced by an invented value. Static item or champion names are hydrated only from a match-compatible Data Dragon version; when unavailable, numeric IDs remain visible with an existing degraded-data status.

## 10. Evidence Window Planning

Only the following facts create candidate video windows:

| Trigger | Window | Neutral category |
| --- | --- | --- |
| selected player is killer or assistant | 12 seconds before, 8 seconds after | `combat_context` |
| selected player is victim | 15 seconds before, 10 seconds after | `death_context` |
| an explicit killer/team mapping proves the selected player's team took an elite monster | 20 seconds before, 10 seconds after | `objective_context` |
| an explicit killer-participant mapping proves the selected player's team destroyed a building | 20 seconds before, 10 seconds after | `building_context` |

Item facts and periodic participant snapshots remain Timeline facts but do not create video windows in J1.

The selected participant's team comes from the validated match roster. Objective and building facts remain visible as neutral match context when their actor is ambiguous, but ambiguous ownership never creates a selected-team video window.

Planning rules:

1. Clamp each raw interval to `[0, match_duration_ms]`.
2. Sort by start time, end time, neutral category order, and trigger fact ID.
3. Merge overlapping intervals. A merged window retains every trigger fact ID and every neutral category in stable order.
4. Do not merge intervals separated by a positive gap.
5. Return at most 64 windows in chronological order.
6. If more than 64 remain, keep the first 64 and return `truncated=true` plus the total pre-truncation count.
7. Generate a stable window ID from platform, match ID, schema version, and final chronological ordinal. It contains no PUUID.

The planner never assigns quality, severity, blame, advice, or causal language.

## 11. Replay Linkage

Replay linkage is requested only when the body contains a `replay_id`.

The existing bearer capability token must authorize the replay. The replay must:

- exist and authorize successfully;
- be `READY`;
- match the requested platform, match ID, and selected PUUID;
- have a valid normalized-video coverage interval.

An invalid token, deleted replay, missing replay, or binding mismatch returns the existing uniform `REPLAY_NOT_FOUND`. An authorized replay that is not ready returns `409 REPLAY_EVIDENCE_NOT_READY`.

For each window:

- `full`: the complete window lies inside replay game-time coverage;
- `partial`: the intersection with replay coverage is non-empty but incomplete;
- `unavailable`: no authorized replay was requested or the window has no overlap.

For full and partial windows, map the covered game-time interval through the existing `game_to_video_time` function. Link only existing artifacts whose `game_time_ms` lies inside the covered interval. The response includes artifact ID, kind, game time, and video time, but no storage key or access URL. Actual media access continues through the existing token-protected artifact API.

No new frame or clip is generated when a window lacks an existing artifact.

## 12. Public API

Add:

```http
POST /api/v1/matches/{match_id}/evidence
```

The strict request body contains:

```json
{
  "platform": "NA1",
  "puuid": "selected player identity",
  "locale": "zh-CN",
  "replay_id": null
}
```

Unknown fields are rejected. If `replay_id` is absent, an Authorization header is rejected rather than silently ignored. If `replay_id` is present, a valid bearer replay token is required.

The endpoint first validates the cached or freshly loaded match detail:

- match exists for the requested platform;
- selected PUUID is in the match exactly once;
- the match is marked `analysis_supported` by the existing queue/mode rules.

The strict response contains:

- `status="ready"`;
- platform, match ID, locale, schema version, and request ID;
- ordered public Timeline facts;
- ordered evidence windows;
- Timeline cache status;
- optional replay-link summary;
- `truncated` and total-window count;
- `scope_notice_code="EVIDENCE_ONLY_NO_COACHING"`.

It never returns the selected PUUID as a duplicate response field.

### 12.1 Public Errors

| Condition | HTTP | Code | Retryable |
| --- | ---: | --- | --- |
| feature disabled | 404 | `NOT_FOUND` | false |
| match missing | 404 | `MATCH_NOT_FOUND` | false |
| selected player missing | 404 | `PLAYER_NOT_IN_MATCH` | false |
| unsupported queue/mode | 422 | `MATCH_EVIDENCE_UNSUPPORTED_MODE` | false |
| Timeline missing | 404 | `MATCH_TIMELINE_NOT_FOUND` | false |
| replay invalid/mismatched/deleted | 404 | `REPLAY_NOT_FOUND` | false |
| authorized replay not ready | 409 | `REPLAY_EVIDENCE_NOT_READY` | true |
| Riot authentication | 503 | `RIOT_AUTH_FAILED` | false |
| Riot rate limit | 429 | `RIOT_RATE_LIMITED` | true |
| invalid Riot response | 502 | `RIOT_INVALID_RESPONSE` | false |
| Riot unavailable | 503 | `RIOT_UNAVAILABLE` | true |

All errors use the existing safe envelope and request ID.

## 13. Frontend

The localized match-detail page adds a section below the existing match data and Replay controls:

```text
准备时间线证据 / Prepare timeline evidence
```

The request is not made on page load. The user activates the button explicitly.

Frontend states are:

- idle;
- loading;
- ready with Timeline facts and candidate windows;
- ready without replay linkage;
- ready with partial replay coverage;
- empty supported facts/windows;
- retryable error;
- non-retryable unavailable state.

When a locally stored Replay capability for the same match exists and its latest known state is ready, the client includes its replay ID and token. Otherwise it requests Timeline-only evidence. A replay authorization failure clears the stale local capability using the existing behavior and allows a Timeline-only retry.

Window cards show:

- neutral localized categories;
- formatted game-time start and end;
- triggering recorded events;
- full, partial, or unavailable replay coverage;
- authorized linked frames when present.

The UI never uses words equivalent to mistake, good play, bad play, score, awareness, mechanics, or causality. It always displays a localized notice that synchronized evidence is available but no AI coaching conclusion has been generated.

Loading uses a polite live region, failures use an alert, the trigger is keyboard accessible, and linked images retain meaningful localized alt text with game time.

## 14. Metrics and Logging

Closed-label metrics include:

- Timeline request outcome and cache result (`hit`, `miss`, `not_found`);
- Riot Timeline fetch outcome and duration;
- normalized supported event type and ignored-event count;
- candidate-window count and truncation count;
- replay coverage result (`full`, `partial`, `unavailable`);
- public API outcome and stable error code;
- single-flight waiter and shared-fetch counts.

No metric label contains a Riot ID, PUUID, match ID, replay ID, token, hostname, URL, or free-form upstream value.

Structured logs use route templates and existing hashed safe references where correlation is necessary. Raw Timeline payloads and individual event dictionaries are never logged.

## 15. Testing Strategy

### 15.1 Unit and Contract Tests

- closed regional host and percent-encoded Timeline path;
- 404, authentication, rate-limit, unavailable, malformed JSON, and invalid DTO mapping;
- critical DTO validation, monotonic frames, participant uniqueness, and additive unknown fields;
- every supported normalized fact, missing optional values, ignored unknown events, stable ordering, and stable fact IDs;
- match-compatible static-data hydration and degraded numeric fallback;
- window clamping, overlap merging, category aggregation, deterministic IDs, 64-window cap, and truncation metadata;
- no window generation from item or periodic snapshot facts;
- full, partial, and unavailable replay coverage;
- linked artifacts only inside the covered interval;
- strict request/response schemas and every public error;
- disabled feature returns 404 and the default remains false;
- safe logs and closed metric labels.

### 15.2 PostgreSQL Tests

- `0003 -> 0004` upgrade preserves existing players, matches, detections, and replays;
- normal head downgrade/upgrade round trip;
- success and not-found database check constraints;
- positive and negative expiry behavior;
- composite identity across platforms;
- concurrent upsert convergence;
- no raw upstream table or payload column;
- replay delete and artifact cleanup remain unaffected.

### 15.3 Service Concurrency and Authorization Tests

- identical misses share one upstream Timeline request;
- different matches do not share work;
- caller cancellation does not cancel shared work;
- in-flight cleanup after success and failure;
- partial upstream failure is not cached;
- invalid, mismatched, non-ready, and deleted replays;
- replay deletion racing evidence composition returns no unauthorized artifact reference.

### 15.4 Frontend Tests

- no eager request on page load;
- explicit prepare action and stale-request cancellation;
- Timeline-only, linked, partial, empty, retryable, and non-retryable states;
- stale replay capability fallback;
- strict runtime response validation;
- bilingual key completeness;
- accessibility roles, live regions, alerts, keyboard action, and image alt text;
- no coaching, score, or causal wording.

### 15.5 Real Verification

The final gate includes:

- complete backend and frontend verification;
- PostgreSQL migration and repository suites;
- Replay PostgreSQL, FFmpeg, and real S3-compatible regression gates;
- production frontend build;
- Compose Replay lifecycle with zero storage residue and both locales returning 200;
- a real Riot Timeline smoke using only an authorized local identity.

The Timeline smoke prints only safe fields: public outcome, fact count, window count, cache consistency, elapsed time, and request ID. It never prints the Riot ID, PUUID, match ID, replay token, URL, raw event, or raw response.

## 16. Rollout and Rollback

1. Apply migration `0004`.
2. Deploy the backend with `JOINT_EVIDENCE_ENABLED=false`.
3. Deploy the compatible frontend.
4. Configure Timeline TTLs.
5. Enable the feature in the target environment.
6. Run Timeline-only and authorized replay-linked smoke checks.
7. Monitor Timeline, window, replay coverage, Riot error, and cleanup metrics.

Rollback sets `JOINT_EVIDENCE_ENABLED=false`. Migration `0004` remains in place during operational rollback. Existing match, platform detection, Replay upload, and artifact APIs remain compatible.

## 17. Delivery Slices

Cursor implements J1 by test-driven, focused commits in this order:

1. Timeline settings, DTOs, routing operation, and gateway tests.
2. Migration, model, repository, TTL behavior, and PostgreSQL concurrency.
3. Pure Timeline normalization and stable fact contracts.
4. Timeline service cache, single-flight, metrics, and failure policy.
5. Pure evidence-window planning and replay coverage linkage.
6. Joint evidence service, authorization, strict schemas, and API route.
7. Typed frontend client and bilingual evidence UI.
8. Real smoke, Compose regression, privacy audit, documentation, and final review.

Each slice reports changed files, commit hash, exact test counts, and unverified gates. Feature defaults remain off throughout implementation.

## 18. Definition of Done

- A supported match can prepare normalized Timeline evidence on demand.
- Cache and single-flight prevent unnecessary repeated Riot requests.
- Public facts and windows are deterministic, ordered, versioned, and free of PUUID-bearing evidence IDs.
- Unknown events cannot create unsupported claims; malformed known events cannot create partial truth.
- Timeline-only evidence works without a replay.
- An authorized ready replay maps windows to honest full or partial coverage and existing frames only.
- Invalid or deleted replay capabilities never expose replay existence or artifacts.
- The bilingual UI clearly distinguishes recorded evidence from coaching conclusions.
- No AI call, score, judgment, new clip, unauthorized media ingestion, or raw Riot storage exists.
- All unit, PostgreSQL, Replay, frontend, FFmpeg, S3-compatible, Compose, and safe real Riot smoke gates pass with exact reported evidence.

## 19. Authoritative References

- Riot Developer Portal, League routing and API guidance: <https://developer.riotgames.com/docs/lol>
- Riot Developer Portal, Match-V5 API reference: <https://developer.riotgames.com/apis#match-v5/GET_getTimeline>
- Existing product design: `docs/superpowers/specs/2026-07-30-lol-ai-coach-mvp-design.md`
- Existing Replay design: `docs/superpowers/specs/2026-08-01-lol-ai-coach-replay-r1-design.md`
