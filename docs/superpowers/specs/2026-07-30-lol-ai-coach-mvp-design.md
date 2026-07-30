# LoL AI Coach MVP Technical Design

- Status: Approved in conversation
- Date: 2026-07-30
- Initial market: North America
- Initial audience: 5–20 invited beta testers
- Product languages: Simplified Chinese and US English

## 1. Purpose

LoL AI Coach is a post-game review assistant for League of Legends players. A user enters a Riot ID and platform, selects a recent match, and receives a structured review based on real Riot match data.

The first release is a **data-based review**, not a replay-based coaching system. It can describe performance, relative differences, item purchase order, and the sequence of recorded match events. It cannot reliably determine positioning quality, mechanical execution, player intent, communication, or the true causal reason for an individual decision.

The long-term product will add replay evidence. Replay-aware conclusions must remain separate from data-only conclusions and must cite a video timestamp.

## 2. Product Goals

The MVP must:

1. Resolve a real Riot ID on NA1.
2. Display the player's 10 most recent matches.
3. Display a real match summary and all 10 participants.
4. Analyze Ranked Solo/Duo and Normal Draft matches.
5. Fetch Match Timeline data only when a user requests a review.
6. Produce deterministic metrics, evidence, role-aware scoring, and training goals.
7. Generate a structured Chinese or English explanation using only verified evidence.
8. Tell the user what the data can and cannot establish.
9. Remain usable when Riot Timeline, static data, or the AI provider is temporarily unavailable.
10. Be deployable for a small public beta without exposing API keys.

## 3. Non-Goals

The MVP does not include:

- Live-game assistance, overlays, voice prompts, or game automation.
- Memory inspection, client modification, or anti-cheat workarounds.
- Replay or video upload and analysis.
- A desktop companion.
- User accounts or Riot Sign On.
- Long-term performance trends.
- Mobile applications.
- Social, team, friend, or duo analysis.
- Subscription or payment systems.
- A replacement MMR, ELO, ladder, or persistent skill rating.
- Support for regions other than NA1.
- Simultaneous generation of Chinese and English reviews.

## 4. Confirmed Product Decisions

| Decision | Choice |
| --- | --- |
| Architecture | Next.js frontend + modular FastAPI backend + PostgreSQL |
| Review depth | Match summary plus lightweight Match Timeline evidence |
| Long-term trends | Deferred |
| Release scale | 5–20 invited testers on a public deployment |
| Performance baseline | In-match comparison plus conservative role-specific thresholds |
| Overall score | Deterministic backend score with explainable components |
| Languages | Explicit `zh-CN` / `en-US` switch; generate one language per request |
| Replay evolution | Video upload first, then an optional Windows replay-recording helper |
| Background jobs | Synchronous MVP implementation behind an `AnalysisJob` contract |
| AI role | Select and explain verified findings; never calculate facts or scores |

## 5. System Architecture

The repository is a monorepo with independently testable frontend and backend applications.

```text
Browser
  -> Next.js web application
  -> FastAPI API and orchestration layer
      -> Riot gateway
          -> Account API
          -> Summoner API
          -> Match V5
          -> Match Timeline
          -> Data Dragon
      -> Match normalization
      -> Timeline fact extraction
      -> Deterministic analytics and scoring
      -> Evidence catalog and candidate findings
      -> OpenAI Responses API
      -> Structured-output and evidence-reference validation
      -> PostgreSQL
```

### 5.1 Frontend Responsibilities

The Next.js application owns:

- Locale selection and localized routes/content.
- Riot ID search and input validation.
- Player and recent-match presentation.
- Match detail and review presentation.
- Loading, empty, degraded, error, and retry states.
- Query state and safe client-side response validation.
- Responsive behavior for mobile and desktop.

The frontend never receives Riot or OpenAI credentials and never receives raw upstream JSON.

### 5.2 Backend Responsibilities

FastAPI owns:

- Input validation and platform-to-regional routing.
- Rate limiting and request correlation.
- Riot API timeouts, retries, and error normalization.
- Raw response parsing into internal Pydantic models.
- Metrics, time-context facts, rankings, composition analysis, and scoring.
- AI prompt construction and structured-output validation.
- Idempotency, caching, persistence, retention, and safe logging.

### 5.3 Module Boundaries

```text
backend/app/
  api/             HTTP routes and error envelopes
  core/            configuration, logging, security, localization enums
  schemas/         public and internal Pydantic contracts
  services/
    riot/          upstream clients and routing
    static_data/   Data Dragon version and locale resolution
    parsing/       raw-to-internal conversion
    timeline/      recorded-event fact extraction
    analytics/     pure metric and ranking functions
    scoring/       versioned role-specific scoring
    evidence/      evidence catalog and candidate findings
    ai/            provider boundary and prompt/output validation
  repositories/    database access
  models/          SQLAlchemy persistence models
```

External service clients are behind interfaces so unit tests can replace them with deterministic fakes.

## 6. Riot Data Flow

### 6.1 Player Resolution

1. Accept `game_name`, `tag_line`, and `platform=NA1`.
2. Map NA1 to the `americas` regional route where required.
3. Resolve PUUID through Account API.
4. Resolve profile icon and summoner level through Summoner API.
5. Store the normalized player reference and cache timestamp.

### 6.2 Recent Matches

1. Fetch the 10 latest Match IDs without restricting the queue.
2. Fetch or reuse cached Match Detail for those IDs.
3. Mark `queueId=400` and `queueId=420` as reviewable.
4. Display other modes but disable AI review with a localized explanation.

This preserves the meaning of “10 most recent matches” instead of silently replacing recent unsupported matches with older supported matches.

### 6.3 On-Demand Timeline

Match Timeline is fetched only after the user requests a review. It is used for:

- Item purchase, sale, undo, and transformation order.
- Champion kill/death timestamps.
- Elite monster, tower, and inhibitor event ordering.
- Participant-frame gold, level, and creep-score snapshots.
- Strictly temporal statements such as “a death occurred 42 seconds before the second dragon was taken.”

Timeline evidence must not turn event order into unsupported causality. The system may say two events occurred in sequence; it may not claim that one caused the other without replay evidence.

### 6.4 Static Data

The match `gameVersion` determines the Data Dragon patch family. The static-data service selects the latest available Data Dragon build compatible with that patch and locale:

- `zh-CN` -> Data Dragon `zh_CN`
- `en-US` -> Data Dragon `en_US`

Static data provides localized champion/item names, images, build trees, costs, and published attributes. Repository-owned coaching rules provide explicitly reviewed capability tags and training thresholds.

If a compatible static version or a required coaching tag is unavailable, the dependent conclusion becomes `unknown`. A current-version value must not be substituted for an older match without an explicit compatibility rule.

## 7. Internal Contracts

The principal internal Pydantic models are:

- `PlayerProfile`
- `MatchSummary`
- `MatchDetail`
- `ParticipantSnapshot`
- `TimelineFact`
- `MetricEvidence`
- `CandidateFinding`
- `ScoreBreakdown`
- `AnalyticsEvidence`
- `CoachAnalysis`
- `AnalysisJobStatus`

All internal models are independent of Riot field names. Riot-specific DTOs remain inside the Riot/parsing boundary.

### 7.1 Evidence Contract

Every claimable fact has a stable ID and provenance:

```json
{
  "evidence_id": "metric:deaths_per_10m:player",
  "source_type": "match_data",
  "category": "survivability",
  "value": 2.42,
  "unit": "deaths_per_10_minutes",
  "comparison": {
    "team_rank": 1,
    "lane_opponent_value": 1.21
  },
  "confidence": "high",
  "timestamp_ms": null,
  "source_version": "match-v5"
}
```

Allowed source types in the shared contract are:

- `match_data`
- `timeline`
- `static_data`
- `coach_rule`
- `replay_video` (reserved for a later project)

The MVP does not create video storage, video tables, or unused replay-processing modules. It only ensures evidence and AI result schemas can later accept timestamped replay evidence without breaking existing consumers.

## 8. Metrics and Composition

Pure functions calculate:

- KDA
- CS per minute
- Gold per minute
- Champion damage per minute
- Damage taken per minute
- Kill participation
- Deaths per 10 minutes
- Vision score per minute
- Wards placed/destroyed per minute
- Control wards purchased
- Team rankings for damage, gold, CS, vision, kill participation, and deaths
- Lane-opponent differences when role matching is unambiguous

Division by zero and missing values return a typed unavailable result rather than a fabricated zero.

Team physical, magic, and true-damage composition uses actual participant damage-to-champions fields from the match. Static champion tags are a fallback context field, not a replacement for recorded damage.

Tank, healing, shielding, burst, and sustained-damage classifications require a versioned coaching-rule entry. Missing entries return `unknown`.

## 9. Deterministic Performance Score

The score is a single-match coaching summary, not a persistent skill rating. Win/loss is not directly scored.

Default role weights are:

| Role | Economy/tempo | Combat | Survivability | Team/objectives | Vision |
| --- | ---: | ---: | ---: | ---: | ---: |
| Top/Mid/Bottom | 25 | 25 | 20 | 15 | 15 |
| Jungle | 20 | 20 | 20 | 25 | 15 |
| Utility | 10 | 20 | 20 | 20 | 30 |

Each scoring signal produces:

- A normalized 0–100 signal score.
- One or more evidence IDs.
- A confidence level.
- A rule or comparison source.

Signals use in-match team rank, an unambiguous lane opponent comparison, or a conservative role-specific threshold. Missing dimensions are excluded and the remaining weights are normalized. The response includes `score_version`, dimension scores, available weight coverage, confidence, and evidence IDs.

The UI labels it “LoL AI Coach match score” / “LoL AI Coach 本局评分” and states that it is not an official Riot score. The product never aggregates it into a replacement ladder, MMR, or ELO.

## 10. Candidate Findings and Training Goals

The rule engine, not the AI model, creates candidate findings and numeric training goals.

A candidate finding includes:

- Type: strength, mistake, itemization, vision, or objective context.
- Severity.
- Evidence IDs.
- Allowed advice topics.
- Confidence.
- A flag indicating whether replay evidence would be required for a stronger conclusion.

Training goals must be measurable and conservative. Examples include a death ceiling, a CS/min target, or a control-ward purchase target. A threshold is used only when the ruleset defines it for that role and the supporting data is available.

## 11. AI Coach Boundary

The default provider uses the OpenAI Responses API with Structured Outputs. The default model is `gpt-5.6-terra`, selected as a quality/cost starting point, and is configurable through `OPENAI_MODEL`. The model and request parameters must be evaluated on representative match fixtures before beta release.

The request uses:

- `store: false`
- A privacy-preserving stable `safety_identifier`
- Configurable reasoning effort, initially `low`
- A strict JSON Schema derived from the Pydantic response model
- The selected locale
- Only the evidence catalog, deterministic score, candidate findings, and rule-generated goals

The AI may:

- Select and order the most useful candidate findings.
- Write a concise overall summary.
- Explain the practical impact of selected findings.
- Phrase approved advice in Chinese or English.

The AI may not:

- Calculate or change metrics, scores, severity, or numeric goals.
- Create an evidence sentence containing uncatalogued numbers.
- Cite an evidence ID absent from the input.
- Claim to have seen positioning, mechanics, or intent.
- Generate a replay-level conclusion without replay evidence.

AI output stores evidence IDs instead of free-form evidence text. The backend hydrates localized evidence text from deterministic templates before returning the final API response.

Output validation verifies:

1. JSON Schema validity.
2. Every evidence ID exists in the input catalog.
3. Selected findings were present in the candidate list.
4. Numeric goals are unchanged.
5. The output language matches the requested locale.

A validation failure triggers one repair attempt. A second failure records a safe error. Base match data, deterministic metrics, and scoring remain available when AI generation fails.

## 12. Localization

Supported locales are the closed enum `zh-CN` and `en-US`.

- The first visit uses browser-language negotiation.
- An explicit language switch always wins.
- The selection is stored without requiring an account.
- UI text, dates, errors, empty states, disclaimers, and deterministic evidence templates use locale message catalogs.
- Backend error codes are stable and language-neutral; the frontend translates them with parameter substitution.
- AI prompt templates are locale-specific but share one output schema.
- Evidence and scores are locale-neutral and computed once.
- AI analyses are cached separately by locale.

The analysis idempotency key is:

```text
match_id
+ puuid
+ locale
+ evidence_version
+ score_version
+ prompt_version
+ model_config_version
```

Automated tests fail when required translation keys are missing or when a Chinese result is returned for an English analysis key, and vice versa.

## 13. Public API

### 13.1 Resolve Player

```http
GET /api/v1/players/resolve?platform=NA1&game_name=PlayerName&tag_line=NA1
```

### 13.2 Recent Matches

```http
GET /api/v1/players/{puuid}/matches?platform=NA1&count=10
```

### 13.3 Match Detail

```http
GET /api/v1/matches/{match_id}?platform=NA1&puuid={puuid}&locale=zh-CN
```

### 13.4 Create or Reuse Analysis

```http
POST /api/v1/analyses
Content-Type: application/json

{
  "platform": "NA1",
  "match_id": "NA1_123456789",
  "puuid": "...",
  "locale": "zh-CN"
}
```

The synchronous MVP returns `200 completed` for a completed or cached analysis. The route may return `202 processing` after the implementation moves to a worker.

### 13.5 Analysis Status

```http
GET /api/v1/analyses/{analysis_id}
```

### 13.6 Health

```http
GET /health/live
GET /health/ready
```

Liveness checks the process. Readiness checks required configuration and database connectivity without making billable Riot or OpenAI calls.

## 14. Persistence

### 14.1 Tables

`players`

- Internal ID, PUUID, game name, tag line, platform, profile icon, level, timestamps.

`matches`

- Match ID, platform, queue, game version, start time, duration, normalized snapshot JSON, normalized hash, fetched timestamp.

`player_match_stats`

- Match/player keys, champion, role, result, core statistics, final items, calculated metrics JSON.

`analysis_jobs`

- Analysis ID, idempotency key, status, attempts, safe error code, all version keys, timestamps.

`analysis_evidence`

- Analysis ID, evidence JSON, input hash, evidence version, rules version.

`ai_analyses`

- Analysis ID, locale, provider, model, prompt version, output JSON, usage JSON, provider response ID when safe to retain, timestamps.

### 14.2 Retention

- Raw Riot responses are transient and are not stored after normalization.
- Normalized match snapshots, evidence, and AI analyses default to a 30-day retention period.
- Operational logs default to 14 days.
- Retention values are environment configuration.
- Logs never contain API keys and use hashed or truncated PUUID values.

## 15. Error Handling and Degradation

All API errors use:

```json
{
  "error": {
    "code": "RIOT_RATE_LIMITED",
    "message": "Safe English fallback message",
    "params": {},
    "retryable": true,
    "request_id": "request-correlation-id"
  }
}
```

Frontend localization primarily uses `code` and `params`. `message` is a safe fallback and never contains an upstream exception or secret.

Required mappings include:

- Invalid input.
- Player not found.
- Match not found.
- Player absent from match.
- Riot credentials rejected.
- Riot rate limited, including a safe retry-after value when available.
- Riot unavailable or timed out.
- Static-data version unavailable.
- Timeline unavailable.
- OpenAI unavailable, timed out, refused, or returned invalid structured output.
- Duplicate analysis already processing.

Degradation rules:

- Missing Timeline -> summary-only data review with explicit insufficiency.
- Missing compatible static data -> omit dependent item/champion conclusions.
- AI failure -> show match detail, deterministic evidence, score, and retry control.
- Partial participant fields -> preserve valid fields and list unavailable calculations.

## 16. Caching and Idempotency

- Player resolution and profile data use a short TTL.
- Immutable completed match details and timelines use a long TTL keyed by Match ID and normalized hash.
- Data Dragon JSON is cached in memory by version and locale; container restarts may fetch it again.
- Analysis uniqueness is enforced by a database unique constraint on the full idempotency key.
- The first request owns generation; concurrent requests observe the same `analysis_jobs` row.
- Failed analyses may be retried under bounded attempt rules without creating unlimited billable calls.

Redis is not required for the small beta. The repository/API boundary allows a later Redis and worker implementation without changing frontend contracts.

## 17. Security and Compliance

- `RIOT_API_KEY` and `OPENAI_API_KEY` exist only in backend environment variables.
- `.env.example` documents names without values.
- CORS uses an explicit deployment allowlist.
- Search and analysis endpoints have separate configurable limits; analysis is more restrictive.
- Input length, platform enum, Match ID shape, locale, and request body size are validated.
- External requests use HTTPS, explicit timeouts, bounded retry, and safe error conversion.
- Logs redact authorization headers, secrets, and full PUUID values.
- The service does not access live-game information, game memory, or hidden players.
- The match score is not presented as Riot ranking, MMR, or ELO.

The product displays Riot's required third-party disclaimer in both supported languages, with English containing the official substance that the product is not endorsed by Riot Games and does not reflect Riot's views, and that Riot properties belong to Riot Games.

Riot registration and production-key requirements must be rechecked before expanding beyond the invited beta.

## 18. Frontend Information Architecture

### 18.1 Home

- Product statement.
- Game Name, Tag Line, and platform fields.
- Search action.
- Locale switch.
- Example format.
- Loading, validation, error, and retry states.
- Riot disclaimer.

### 18.2 Player Page

- Profile icon, Riot ID, level.
- Ten recent matches.
- Champion, result, KDA, CS, duration, time, role, and final core items.
- Clear disabled state for unsupported queues.

### 18.3 Match Detail

- Result and scope notice.
- Player metrics and deterministic score breakdown.
- Items and purchase order.
- Both teams.
- Data sufficiency status.
- Generate/retry review action.
- AI summary, strengths, mistakes, itemization, vision, and three goals.
- Visible evidence links for every conclusion.

The page prioritizes the most important problem and next-game goals. It uses a restrained dark game aesthetic without copying Riot's client or using Riot branding as the product logo.

## 19. Observability

Structured logs include:

- Request ID.
- Route and safe status code.
- Upstream service and latency.
- Cache hit/miss.
- Analysis version keys.
- AI model, latency, token usage, and validation outcome.
- Hashed player reference.

Operational counters include Riot errors by class, AI failures, schema failures, evidence-reference failures, cache hit rate, analysis latency, and approximate AI cost.

No user-facing health endpoint makes external billable calls.

## 20. Testing Strategy

### 20.1 Backend Units

- All metric formulas and division-by-zero behavior.
- Missing and malformed participant fields.
- Team and lane-opponent rankings, including ties.
- Timeline item-order reconstruction and event-window boundaries.
- Damage composition and unknown static classifications.
- Role weights, missing-dimension normalization, confidence, and score version.
- Candidate finding and training-goal rules.

### 20.2 External Contract Tests

All Riot and OpenAI tests use mocks or fakes. Tests cover 401, 403, 404, 429, 500, timeout, malformed payloads, missing fields, refusal, invalid JSON, invalid evidence IDs, and retry exhaustion.

### 20.3 Persistence and Integration

- Alembic migrations.
- Idempotency uniqueness under concurrent requests.
- Cache reuse.
- Retention selection.
- Analysis recovery after failure.
- PostgreSQL is authoritative for integration tests; SQLite may be used only for fast isolated tests that do not rely on PostgreSQL behavior.

### 20.4 Frontend

- Search form and validation.
- Locale negotiation and explicit switching.
- Missing translation detection.
- Chinese/English analysis cache isolation.
- Loading, empty, degraded, error, and retry states.
- Player, match, score, and review rendering.
- Mobile layout.

### 20.5 End-to-End

A fully mocked browser flow covers:

1. Search Riot ID.
2. Select a supported match.
3. Load match detail.
4. Request analysis.
5. Show deterministic score and evidence-backed review.
6. Switch locale and generate/reuse the correctly isolated localized result.

### 20.6 AI Evaluation

A representative evaluation set covers all five roles, wins and losses, short and long matches, low-kill teams, missing Timeline, static-data mismatch, and conflicting candidate findings.

It checks:

- Schema validity.
- Evidence coverage.
- No unsupported numerical claims.
- No positioning/mechanics claims without replay evidence.
- Correct locale.
- Appropriate prioritization and actionable wording.
- Latency and token cost.

## 21. Deployment

Recommended beta deployment:

- Frontend: Vercel.
- Backend: Render or Railway.
- Database: Neon or Supabase PostgreSQL.
- Local development: Docker Compose.

The MVP does not require Redis, Celery, a separate worker, object storage, or video processing. These are introduced only when measured demand requires them.

## 22. Replay Evolution

Replay analysis is a separate future project, not a hidden MVP task.

### Phase R1: User-Uploaded Video

1. Accept an authenticated or possession-bound upload.
2. Validate file type and size.
3. Store temporarily in object storage.
4. Transcode to a controlled format.
5. Use Match Timeline to select relevant time windows.
6. Extract frames or short visual segments.
7. Produce timestamped replay evidence.
8. Merge replay and data evidence in the unified evidence contract.
9. Link each replay-backed conclusion to a timestamp.
10. Delete source video according to a short, explicit retention policy.

### Phase R2: Desktop Replay Helper

After R1 proves useful, a Windows helper may use Riot's local Replay API to assist replay playback and recording. It must not operate during a live game, read process memory, modify the client, or rely on anti-cheat workarounds. Unsupported local-client dependencies and Riot registration requirements must be re-evaluated before implementation.

## 23. Delivery Phases

### Phase 1: Foundation

Monorepo, Next.js, FastAPI, configuration, health checks, Docker Compose, linting, typing, tests, and README.

### Phase 2: Riot Integration

Player resolution, recent matches, detail parsing, localized Data Dragon assets, cache, and safe error states.

### Phase 3: Evidence and Score

Timeline fetch/parsing, pure analytics, composition, versioned coaching rules, evidence catalog, candidate findings, goals, and deterministic score.

### Phase 4: AI Review

Responses API, Structured Outputs, evidence-reference validation, locale prompts, repair retry, caching, and cost records.

### Phase 5: Beta Hardening

Responsive UI, accessibility, rate limits, logging, deployment, retention, end-to-end tests, AI evaluation, and invited-user validation.

### Future: Replay Analysis

R1 video upload followed by R2 desktop replay helper, each with its own design and implementation plan.

## 24. MVP Acceptance Criteria

The MVP is accepted when:

- A real NA1 Riot ID resolves successfully.
- Ten real recent matches display without exposing an API key.
- Supported matches display all required player and team data.
- Timeline-backed item order and event context are correct for tested fixtures.
- Every calculation handles zero and missing data safely.
- Every score dimension cites deterministic evidence.
- Every AI conclusion cites existing evidence and respects the data-only scope.
- Chinese and English UI/reviews are isolated and correct.
- Repeated identical requests do not produce duplicate AI calls.
- Riot and AI failures produce understandable localized states.
- Backend tests, frontend tests, lint, formatting, and type checks pass.
- Docker Compose starts the system locally.
- The deployed beta completes the full user flow on desktop and mobile.
- At least five real players can test it, and feedback is collected without representing statistical review as replay analysis.

## 25. Authoritative References

- Riot Games developer policy, routing, Riot ID transition, APIs, Replay API, and Data Dragon: <https://developer.riotgames.com/docs/lol>
- OpenAI current model guidance: <https://developers.openai.com/api/docs/guides/latest-model>
- OpenAI GPT-5.6 Terra model capabilities: <https://developers.openai.com/api/docs/models/gpt-5.6-terra>

