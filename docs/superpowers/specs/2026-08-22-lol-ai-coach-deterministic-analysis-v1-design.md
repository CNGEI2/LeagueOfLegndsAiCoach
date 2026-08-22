# LoL AI Coach — Deterministic Analysis V1 Design

**Date:** 2026-08-22

**Status:** Draft — pending written-spec review

**Depends on:** Phase 2 Riot integration, Riot platform detection, Replay R1, Joint Evidence J1

## 1. Goal

Deterministic Analysis V1 turns the existing normalized Match-V5 and Timeline evidence into a versioned, explainable single-match coaching summary. It calculates metrics, a role-aware five-dimension score, a small set of evidence-backed strengths and improvement opportunities, and measurable next-game goals.

This phase creates no OpenAI or other model call. Every number and conclusion is produced by repository-owned deterministic code and cites evidence that already exists in the analysis input.

## 2. Confirmed Product Decisions

- Analysis is a separate subsystem and public API. Joint Evidence J1 remains a neutral evidence endpoint.
- The first release uses only structured Riot Match-V5 and Timeline data.
- Replay can supply timestamp and frame references through the existing J1 evidence UI, but replay media does not affect metrics, scores, findings, or goals.
- The product does not judge positioning, mechanics, awareness, intent, communication, or causality.
- The public and coaching-domain role name is `support`; Riot's upstream `UTILITY` value is mapped at the boundary and is never displayed as the product term.
- Deterministic computation is synchronous. No analysis queue or new worker is introduced.
- Results are locale-neutral and computed once. Chinese and English use stable message codes and parameters to render the same result.
- The feature is controlled by `DETERMINISTIC_ANALYSIS_ENABLED`, which defaults to `false`.
- Enabling deterministic analysis requires `JOINT_EVIDENCE_ENABLED=true` so every eligible conclusion can be inspected against the evidence surface.

## 3. Scope

### 3.1 Included

- A deterministic analysis domain and orchestration service.
- Pure metric, scoring, finding, and goal engines.
- Stable evidence IDs and versioned rules.
- Role-aware weights for Top, Jungle, Mid, Bottom, and Support.
- Synchronous create-or-reuse and get-by-ID APIs.
- PostgreSQL persistence, input hashing, idempotency, concurrency safety, and retention.
- A bilingual match-detail analysis panel.
- Safe partial degradation when some inputs are unavailable.
- Local, PostgreSQL, frontend, and real Riot smoke verification.

### 3.2 Excluded

- OpenAI or any other model provider.
- AI-generated prose, prompt templates, token usage, repair retries, or model evaluation.
- Replay image/video interpretation or computer vision.
- New replay clips or media generation.
- Claims about positioning, mechanics, awareness, intent, communication, or causality.
- Cross-match rank, MMR, ELO, trend, or persistent player skill scoring.
- Global population or rank-tier benchmarks that are not available from the selected match.
- OP.GG or another third-party statistics dependency.

## 4. Architecture

The subsystem lives under `backend/app/services/analyses/` and depends on existing internal Match and Timeline sources rather than consuming the public `/evidence` response.

### 4.1 Components

`MetricEngine`

- Pure function over normalized match/timeline input and the selected player.
- Produces typed metric evidence with stable IDs, units, availability, comparisons, and source references.
- Never assigns coaching language or severity.

`ScoreEngine`

- Converts available metric signals into dimension scores and an optional overall score.
- Applies the versioned role weights and coverage rules in this document.
- Never invents a zero for missing data.

`RuleEngine`

- Consumes only computed metric evidence and score breakdowns.
- Selects at most three findings and at most three measurable goals from a versioned repository-owned ruleset.
- Emits message codes and parameters, not localized prose.

`AnalysisService`

- Loads and validates the Match/Timeline context.
- Coordinates the pure engines.
- Validates evidence-reference closure.
- Computes the canonical input hash and idempotency key.
- Persists or reuses one deterministic result atomically.

`AnalysisRepository`

- Owns PostgreSQL create-or-reuse, get, retention, and concurrency behavior.
- Never stores raw Riot responses.

### 4.2 Existing Boundaries

- `JointEvidenceService` and `POST /api/v1/matches/{match_id}/evidence` remain unchanged and evidence-only.
- Analysis and J1 share Match/Timeline sources and stable fact IDs, but neither public response embeds the other.
- Existing Replay possession-token and artifact authorization remain entirely inside Replay/J1.
- The frontend correlates analysis evidence references with the already-rendered J1 facts/windows. Replay-backed frames remain in the evidence section and do not enter the analysis cache key.

## 5. Domain Contracts

The coaching domain uses the closed role enum:

```text
top | jungle | mid | bottom | support
```

Riot boundary mapping is:

```text
TOP -> top
JUNGLE -> jungle
MIDDLE -> mid
BOTTOM -> bottom
UTILITY -> support
anything else -> unavailable
```

Principal immutable models are:

- `MetricEvidence`
- `MetricComparison`
- `DimensionScore`
- `ScoreBreakdown`
- `CandidateFinding`
- `TrainingGoal`
- `DeterministicAnalysisResult`
- `AnalysisJobStatus`

Every `MetricEvidence` contains:

- `evidence_id`
- `category`
- `value` and `unit`, or a typed unavailable reason
- `comparison` when a valid team or same-role comparison exists
- `confidence`
- `source_type`
- stable source fact IDs when Timeline facts contribute
- metric version

Every finding and goal contains only evidence IDs from the same result. The service rejects a result when any reference is absent.

## 6. Metric Catalog

V1 computes the following when inputs are available:

- KDA
- CS per minute
- Gold per minute
- Champion damage per minute
- Kill participation
- Deaths per ten minutes
- Vision score per minute
- Team ranks for damage, gold, CS, vision, kill participation, and deaths
- Same-role opponent differences when exactly one valid opponent exists
- Explicit selected-player objective events recorded by Timeline

Division by zero, negative duration, missing participant values, ambiguous role matching, and absent Timeline data produce typed unavailable results. They never produce fabricated zeros.

The five dimensions use these signals:

| Dimension | V1 signals |
| --- | --- |
| Economy/tempo | CS/min, gold/min, valid same-role differences |
| Combat | KDA, kill participation, champion damage/min, team damage rank |
| Survivability | Deaths/10m, relative team death rank, valid same-role death difference |
| Team/objectives | Kill participation and explicit selected-player objective events; team-only objective outcomes are context, not personal credit |
| Vision | Vision score/min and team vision rank |

Win/loss is context only and never directly changes a score.

## 7. Signal Normalization

Every signal is converted to `0–100` by one declared rule in the versioned ruleset:

1. **Team percentile.** Rank available team values in the beneficial direction. Ties receive the average occupied rank. For five distinct values, the scores are `100`, `75`, `50`, `25`, and `0` from best to worst.
2. **Unique same-role comparison.** When exactly one opponent has the same normalized role, calculate `delta = (selected - opponent) / max(abs(selected), abs(opponent), 1e-9)` and map it to `clamp(50 + 50 * delta, 0, 100)` for higher-is-better metrics. Invert the sign for lower-is-better metrics. No opponent is guessed.
3. **Role threshold.** Use only a repository-owned, reviewed threshold table for the matching role and metric. Missing thresholds make the signal unavailable.

Each dimension combines its available signal scores using weights declared in the ruleset. V1 may use equal weights inside a dimension only where the ruleset explicitly says so. Score behavior is therefore versioned and reviewable rather than hidden in presentation code.

## 8. Role Weights and Coverage

| Role | Economy/tempo | Combat | Survivability | Team/objectives | Vision |
| --- | ---: | ---: | ---: | ---: | ---: |
| Top | 25 | 25 | 20 | 15 | 15 |
| Mid | 25 | 25 | 20 | 15 | 15 |
| Bottom | 25 | 25 | 20 | 15 | 15 |
| Jungle | 20 | 20 | 20 | 25 | 15 |
| Support | 10 | 20 | 20 | 20 | 30 |

- Missing signals are excluded from their dimension.
- A missing dimension contributes no applied weight.
- Available role weights are renormalized only when they cover at least `60%` of configured weight.
- Below `60%`, `overall_score` is unavailable and judgmental findings are suppressed; metrics and coverage remain visible.
- An unavailable role prevents an overall score because no role weights may be guessed.
- Every available dimension and overall score is clamped to `0–100`.
- The response includes configured weight, applied normalized weight, available coverage, evidence IDs, and score version.
- The UI states that this is a single-match LoL AI Coach score, not a Riot score, rank, MMR, or ELO.

## 9. Findings and Training Goals

The ruleset emits finding types `strength` and `improvement`. It does not use a free-form model label.

Each finding contains:

- stable rule ID
- type and severity
- message code and typed parameters
- evidence IDs
- confidence
- whether stronger replay-backed interpretation would require a later, separately approved feature

Selection is stable: severity, ruleset priority, and rule ID provide deterministic ordering. Strengths and improvements together are capped at three.

Each goal contains:

- stable rule ID
- message code
- current value
- target value
- unit
- role
- evidence IDs
- rules version

A goal is emitted only when the exact metric/role target exists in the reviewed V1 ruleset and its supporting data is available. Goals are capped at three. V1 goals may cover deaths/10m, CS/min, damage/min, kill participation, and vision score/min when their rules exist. No unsupported control-ward goal is generated from absent data.

## 10. Public API

### 10.1 Create or Reuse

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

The endpoint returns `200` synchronously for both a new result and a cache hit.

The response includes:

- `analysis_id`
- `status` (`completed` or `partial`)
- `cached`
- `locale`
- metric, score, finding, and goal payloads
- data coverage and typed unavailable reasons
- input, metric, score, and rules versions
- `scope_notice_code=DETERMINISTIC_DATA_COACHING_NO_AI`
- safe request ID

The core stored result is locale-neutral. `locale` controls frontend message-catalog selection and does not create a second deterministic computation.

### 10.2 Read

```http
GET /api/v1/analyses/{analysis_id}?locale=zh-CN
```

The read endpoint returns the same locale-neutral result with the requested supported locale. Unknown or expired IDs return the existing safe error envelope.

## 11. Data Flow

1. Reject the route as not found while `DETERMINISTIC_ANALYSIS_ENABLED=false`.
2. Validate platform, match ID, PUUID, locale, supported queue, and selected-player membership.
3. Load the normalized match from the existing cache/service.
4. Attempt to load normalized Timeline data.
5. Normalize the selected role, including `UTILITY -> support`.
6. Build the metric evidence catalog.
7. Compute dimension and optional overall scores.
8. Generate findings and goals from the V1 ruleset.
9. Validate score bounds, typed availability, goal immutability, and evidence-reference closure.
10. Canonicalize the selected Match/Timeline inputs and compute `input_hash`.
11. Compute the idempotency key from platform, match ID, PUUID, input hash, metric version, score version, and rules version. Locale and Replay are excluded.
12. Atomically insert or reuse the persisted result.
13. Return the result and a safe cache indicator.

## 12. Persistence and Concurrency

Migration V1 adds only deterministic-analysis storage. It does not add `ai_analyses`.

`analysis_jobs`

- UUID primary key
- platform, match ID, selected PUUID
- unique SHA-256 idempotency key
- canonical input hash
- status (`completed` or `partial`)
- metric, score, and rules versions
- created, updated, completed, and expiry timestamps

`analysis_evidence`

- analysis ID primary/foreign key with cascade delete
- evidence catalog JSONB
- deterministic result JSONB
- canonical input hash
- schema version
- created timestamp

A PostgreSQL unique constraint owns concurrency correctness. An optional in-process singleflight may reduce duplicate work but is not the correctness boundary. A conflict reads and returns the winning completed/partial row. Failed requests do not create a cache row and return only the safe API error envelope.

Completed and partial deterministic analyses default to 30-day retention. Cleanup deletes metadata and evidence atomically. Raw Riot responses are never stored.

## 13. Partial Degradation and Errors

- Missing Timeline or a safe Riot Timeline failure yields a Match-only `partial` result when Match metrics remain valid.
- Timeline-derived metrics, findings, and goals become unavailable; existing Match metrics remain usable.
- Static-data failure suppresses item/champion classification findings and does not substitute current-version data.
- Less than `60%` score coverage suppresses the overall score and judgmental findings.
- Unknown role suppresses the overall role-weighted score.
- Malformed normalized input, invalid numeric domains, or broken evidence references fail safely rather than returning partial false claims.
- Unsupported queues use `422 MATCH_ANALYSIS_UNSUPPORTED_MODE`.
- Disabled analysis remains dark with `404 NOT_FOUND`, matching other feature-flag boundaries.
- Upstream and persistence failures use the existing error envelope and stable allowlisted codes.

The base match page and neutral J1 evidence remain usable when deterministic analysis fails.

## 14. Frontend

The supported match detail page gains an on-demand “Data coaching analysis” / “数据教练分析” panel.

The panel renders:

- generate/retry action
- loading and cache-hit state
- overall score when available
- all five dimensions with availability and coverage
- up to three findings
- up to three next-game goals
- evidence links into the existing J1 section
- a visible deterministic/no-AI scope notice
- a visible non-Riot-score disclaimer

Product roles are localized as Top/上路, Jungle/打野, Mid/中路, Bottom/下路, and Support/辅助. `Utility` is never user-facing.

Keyboard and screen-reader users can move from a finding or goal to the corresponding evidence target. Color is never the sole score, availability, strength, or improvement signal.

## 15. Configuration and Rollout

Configuration adds:

```dotenv
DETERMINISTIC_ANALYSIS_ENABLED=false
ANALYSIS_RETENTION_DAYS=30
```

Startup validation rejects `DETERMINISTIC_ANALYSIS_ENABLED=true` when `JOINT_EVIDENCE_ENABLED=false`.

Rollout order:

1. Apply the forward-only migration.
2. Deploy with deterministic analysis disabled.
3. Run unit, frontend, PostgreSQL, and existing Riot/J1/Replay gates.
4. Enable J1 and confirm its metrics/cache health.
5. Enable deterministic analysis for local/invited-beta traffic.
6. Run real `smoke-analysis` twice against the same supported match.
7. Confirm the second request reuses the same analysis and that bilingual rendering does not recompute.
8. Roll back by disabling only `DETERMINISTIC_ANALYSIS_ENABLED`; do not downgrade the migration.

## 16. Observability and Privacy

Closed-label metrics cover:

- API outcomes and safe error codes
- computation and persistence latency
- cache hit/miss
- result status (`completed` or `partial`)
- score coverage buckets
- unavailable signal reasons
- finding and goal counts
- idempotency conflicts and singleflight reuse

Logs contain request ID, safe route/status, versions, cache status, latency, and a hashed player reference. They never contain Riot/OpenAI keys, authorization headers, raw Riot responses, replay tokens, full PUUID values, or free-form upstream error bodies.

## 17. Testing Strategy

### 17.1 Unit and Property Tests

- Every metric formula, unit, and division-by-zero case.
- Missing, negative, malformed, and partial participant fields.
- Team ranking, beneficial direction, and average-rank tie handling.
- Unique and ambiguous same-role opponent matching.
- `UTILITY -> support` and unknown-role behavior.
- Dimension weighting, `60%` coverage boundary, renormalization, and score clamping.
- Win/loss neutrality.
- Stable finding/goal selection, caps, ordering, and rule versioning.
- Property checks that all available scores remain within `0–100`.
- Property checks that every finding/goal reference exists in the evidence catalog.

### 17.2 API and Service Tests

- Flag-disabled darkness.
- Supported and unsupported queues.
- Selected player absent from match.
- Completed, partial, cached, and safe failure responses.
- Match-only degradation when Timeline is unavailable.
- Locale validation and locale-neutral reuse.
- Concurrent identical requests return one persisted analysis.
- Input or rules version changes produce a new analysis.
- No OpenAI client or provider call exists in the path.

### 17.3 PostgreSQL Tests

- Forward migration and model constraints.
- Unique idempotency behavior under real concurrency.
- Evidence/result round-trip validation.
- Cascade delete and retention cleanup.

### 17.4 Frontend Tests

- Generate, loading, retry, cached, partial, and unavailable states.
- Overall and five-dimension score rendering.
- Findings, goals, evidence navigation, and keyboard focus.
- Chinese/English catalog completeness and deterministic reuse.
- Top/Jungle/Mid/Bottom/Support and 上路/打野/中路/下路/辅助 terminology.
- Scope/disclaimer visibility and no unsupported coaching wording.

### 17.5 Full and Real Verification

- Existing `make verify` gate.
- Existing PostgreSQL, Replay PostgreSQL, and Replay FFmpeg gates.
- Existing real Riot/J1 smoke.
- Existing isolated Replay Compose lifecycle and zero-residue gate.
- New real `make smoke-analysis`, executed twice, with safe output only.
- `git diff --check`, secret scan, production frontend build, and GitHub Actions.

The real smoke prints only status, metric/dimension/finding/goal counts, coverage, cache consistency, elapsed time, versions, and a safe request ID. It never prints Riot ID, PUUID, match ID, API key, full URL, raw response, or evidence payload.

## 18. Definition of Done

- The feature is dark by default and requires J1 when enabled.
- A supported real match produces deterministic metrics and an explainable role-aware result.
- Missing inputs degrade explicitly and never become fabricated zeros.
- Total score appears only with a known role and at least `60%` available weight.
- Every score, finding, and goal cites valid deterministic evidence.
- Findings and goals stay within the structured-data scope.
- Support/辅助 is the only product term for the support role.
- Repeated identical requests reuse one persisted result, including across locales.
- Replay evidence can be navigated without influencing the analysis result.
- The base match and J1 experiences survive analysis failures.
- All focused, full, PostgreSQL, FFmpeg, Compose, live-smoke, build, and CI gates pass.
- No OpenAI call, AI prose, video interpretation, unauthorized media use, or unsupported behavioral/causal claim enters V1.

## 19. Authoritative References

- `docs/superpowers/specs/2026-07-30-lol-ai-coach-mvp-design.md`
- `docs/superpowers/specs/2026-08-02-lol-ai-coach-joint-evidence-j1-design.md`
- `docs/superpowers/specs/2026-08-01-lol-ai-coach-replay-r1-design.md`
- Riot Match-V5 and Timeline contracts already normalized by the repository.
