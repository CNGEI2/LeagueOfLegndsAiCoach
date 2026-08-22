# LoL AI Coach Deterministic Analysis V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dark-by-default, synchronous deterministic coaching analysis that turns the existing Match-V5 and Timeline data into explainable metrics, role-aware scores, evidence-backed findings, and measurable goals without any model call.

**Architecture:** Create an isolated `services/analyses` domain with pure metric, score, and rule engines; orchestrate it through an `AnalysisService`; persist locale-neutral results behind a PostgreSQL idempotency constraint; expose create/read endpoints; and render an on-demand bilingual panel on match detail. Joint Evidence J1 remains neutral and unchanged except for adding focusable fact anchors for analysis evidence navigation.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2 async, PostgreSQL 17, Alembic, pytest, Next.js 16, React 19, TypeScript, Zod, Vitest/Testing Library, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-08-22-lol-ai-coach-deterministic-analysis-v1-design.md`

## Global Constraints

- Work only on `feature/replay-r1`; begin every task with `git status --short --branch` and preserve unrelated user changes.
- Follow red-green-refactor. Do not write production behavior before its focused test fails for the expected reason.
- `POST /api/v1/matches/{match_id}/evidence` remains evidence-only. Do not put scores, findings, goals, or coaching wording into J1.
- Do not add OpenAI/model imports, prompts, generated prose, replay vision, media inspection, or behavioral/intent/causality claims.
- Product role vocabulary is `top | jungle | mid | bottom | support`; map Riot `UTILITY` to `support` only at the analysis boundary. Never render `Utility`.
- Missing data is unavailable, never numeric zero. Win/loss is context only and must not affect scores.
- Locale and Replay data are excluded from the deterministic cache key. Persist stable message codes and typed parameters, never translated prose.
- Every finding and goal must reference evidence IDs present in the same result. Timeline-backed links may reference only fact IDs present in the normalized Timeline snapshot.
- Keep all public schemas strict/frozen on the backend and strict Zod schemas on the frontend.
- No request may log or print full PUUID, Riot ID, match ID, API key, URL, raw response, replay token, or evidence payload. Hash player references before observability use.
- Add no dependency unless the existing standard library/test stack cannot express the requirement. Property-style tests in this plan use deterministic loops, not Hypothesis.
- After every task, run `git diff --check`; commit only that task's coherent change.

## Exact V1 Ruleset

These constants remove implementation discretion and make the versioned behavior reviewable.

```python
METRIC_VERSION = "deterministic-metrics-v1"
SCORE_VERSION = "deterministic-score-v1"
RULES_VERSION = "deterministic-rules-v1"
RESULT_SCHEMA_VERSION = 1

ROLE_WEIGHTS = {
    "top": {"economy": 25, "combat": 25, "survivability": 20, "team_objectives": 15, "vision": 15},
    "mid": {"economy": 25, "combat": 25, "survivability": 20, "team_objectives": 15, "vision": 15},
    "bottom": {"economy": 25, "combat": 25, "survivability": 20, "team_objectives": 15, "vision": 15},
    "jungle": {"economy": 20, "combat": 20, "survivability": 20, "team_objectives": 25, "vision": 15},
    "support": {"economy": 10, "combat": 20, "survivability": 20, "team_objectives": 20, "vision": 30},
}

DIMENSION_SIGNALS = {
    "economy": {"cs_per_min_team": 25, "gold_per_min_team": 25, "cs_per_min_same_role": 25, "gold_per_min_same_role": 25},
    "combat": {"kda_team": 20, "kill_participation_team": 20, "damage_per_min_team": 30, "damage_per_min_same_role": 30},
    "survivability": {"deaths_per_10_team": 50, "deaths_per_10_same_role": 50},
    "team_objectives": {"kill_participation_team": 60, "explicit_objective_events_team": 40},
    "vision": {"vision_per_min_team": 70, "vision_per_min_same_role": 30},
}
```

For team percentile, sort in the beneficial direction, assign ties the average occupied zero-based rank, and calculate `100 * (team_size - 1 - average_rank) / (team_size - 1)`. Return unavailable when fewer than two team values exist. For unique same-role comparison, use the approved formula `clamp(50 + 50 * delta, 0, 100)` where `delta = (selected - opponent) / max(abs(selected), abs(opponent), 1e-9)`; negate `delta` for lower-is-better metrics.

Each dimension score is the weighted mean of available declared signals. `dimension_coverage = available_signal_weight / declared_signal_weight`. Overall raw applied weight for a dimension is `role_weight * dimension_coverage`; overall coverage is the sum of raw applied weights divided by `100`; an overall score exists only when the role is known and coverage is at least `0.60`. The overall score is the weighted mean of dimension scores using raw applied weights. All outputs are rounded to two decimals after calculation and clamped to `0..100`.

Goals use product-owned single-match targets, not claims about rank or global population:

| Role | CS/min | Deaths/10m max | Damage/min | Kill participation | Vision/min |
| --- | ---: | ---: | ---: | ---: | ---: |
| Top | 6.5 | 2.0 | 450 | 0.45 | 0.60 |
| Jungle | 5.5 | 2.0 | 400 | 0.55 | 0.80 |
| Mid | 6.5 | 2.0 | 500 | 0.50 | 0.70 |
| Bottom | 7.0 | 2.0 | 550 | 0.50 | 0.55 |
| Support | unavailable | 2.0 | 250 | 0.60 | 1.20 |

Emit no finding when `overall_score` is unavailable. Otherwise, emit a dimension strength candidate at score `>= 75` and an improvement candidate at score `<= 35`, but only when that dimension's coverage is at least `0.50`. Improvement severity is `high` at `<= 20` and `medium` otherwise; strength severity is `high` at `>= 90` and `medium` otherwise. V1 reserves `low` but emits none. Stable selection sort is severity (`high`, `medium`, `low`), finding kind (`improvement`, then `strength`), dimension priority (`economy=10`, `combat=20`, `survivability=30`, `team_objectives=40`, `vision=50`), then rule ID. Return at most three total findings. Emit goals only for available metrics that miss their role target, order them by normalized gap descending then rule ID, and return at most three. Never emit a Support CS goal.

## Target File Map

New backend files:

- `backend/app/services/analyses/__init__.py`
- `backend/app/services/analyses/domain.py`
- `backend/app/services/analyses/rules_v1.py`
- `backend/app/services/analyses/metrics.py`
- `backend/app/services/analyses/scoring.py`
- `backend/app/services/analyses/rules.py`
- `backend/app/services/analyses/service.py`
- `backend/app/schemas/analyses.py`
- `backend/app/models/analysis.py`
- `backend/app/repositories/analyses.py`
- `backend/app/api/analyses.py`
- `backend/alembic/versions/0005_deterministic_analyses.py`
- focused test files matching each layer and `scripts/smoke_analysis.py`

Modified backend files:

- `backend/app/core/config.py`, `backend/app/core/dependencies.py`, `backend/app/core/errors.py`, `backend/app/core/metrics.py`
- `backend/app/main.py`, `backend/app/models/__init__.py`, `backend/app/repositories/__init__.py`, `backend/tests/conftest.py`
- `.env.example`, `docker-compose.yml`, `Makefile`, `README.md`

New/modified frontend files:

- new `frontend/src/components/analysis-section.tsx`
- new `frontend/tests/analysis-section.test.tsx` and `frontend/tests/analysis-api-client.test.ts`
- modify `frontend/src/api/schemas.ts`, `frontend/src/api/client.ts`, `frontend/src/components/match-detail-client.tsx`, `frontend/src/components/evidence-section.tsx`
- modify `frontend/src/i18n/en-US.ts`, `frontend/src/i18n/zh-CN.ts`, `frontend/tests/i18n.test.ts`, and `frontend/src/app/globals.css`

---

### Task 1: Lock configuration, role mapping, and immutable domain contracts

**Files:**

- Create: `backend/app/services/analyses/__init__.py`
- Create: `backend/app/services/analyses/domain.py`
- Create: `backend/app/services/analyses/rules_v1.py`
- Create: `backend/tests/test_analysis_domain.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/tests/test_config.py`

- [ ] **Step 1: Write failing configuration and role-contract tests**

Add tests that assert:

```python
def test_analysis_defaults_dark() -> None:
    settings = Settings(_env_file=None)
    assert settings.deterministic_analysis_enabled is False
    assert settings.analysis_retention_days == 30

def test_analysis_requires_joint_evidence() -> None:
    with pytest.raises(ValueError, match="JOINT_EVIDENCE_ENABLED"):
        Settings(
            _env_file=None,
            deterministic_analysis_enabled=True,
            joint_evidence_enabled=False,
        )

@pytest.mark.parametrize(
    ("upstream", "expected"),
    [("TOP", "top"), ("JUNGLE", "jungle"), ("MIDDLE", "mid"),
     ("BOTTOM", "bottom"), ("UTILITY", "support"), (None, None), ("", None)],
)
def test_normalize_analysis_role(upstream: str | None, expected: str | None) -> None:
    assert normalize_analysis_role(upstream) == expected
```

Also construct invalid `MetricEvidence`, `DimensionScore`, `ScoreBreakdown`, `Finding`, `TrainingGoal`, and `DeterministicAnalysisResult` values and assert Pydantic rejects negative values, scores outside `0..100`, available metrics without a value/unit, unavailable metrics with a value, and broken status shapes.

- [ ] **Step 2: Run the tests and confirm the expected import/field failures**

Run: `cd backend && .venv/bin/pytest tests/test_config.py tests/test_analysis_domain.py -v`

Expected: FAIL because analysis configuration and domain modules do not exist.

- [ ] **Step 3: Add the two settings and cross-field validator**

In `Settings`, add:

```python
deterministic_analysis_enabled: bool = False
analysis_retention_days: int = Field(default=30, ge=1, le=365)
```

Rename `validate_replay_settings` to `validate_feature_settings`, retain every replay check unchanged, then reject analysis enabled without J1 using the exact message `DETERMINISTIC_ANALYSIS_ENABLED requires JOINT_EVIDENCE_ENABLED=true`.

- [ ] **Step 4: Implement strict immutable analysis models**

Use `DomainModel` and these public type/signature names in `domain.py`:

```python
AnalysisRole = Literal["top", "jungle", "mid", "bottom", "support"]
DimensionKey = Literal["economy", "combat", "survivability", "team_objectives", "vision"]
MetricStatus = Literal["available", "unavailable"]
UnavailableReason = Literal[
    "missing_match_value", "invalid_duration", "division_by_zero",
    "timeline_unavailable", "role_unavailable", "opponent_unavailable",
    "opponent_ambiguous", "insufficient_team_values",
]

def normalize_analysis_role(upstream: str | None) -> AnalysisRole | None: ...

class MetricComparison(DomainModel):
    basis: Literal["team_percentile", "same_role"]
    score: float = Field(ge=0, le=100)
    opponent_value: float | None = None

class MetricEvidence(DomainModel):
    evidence_id: str
    metric_key: str
    category: DimensionKey
    status: MetricStatus
    value: float | None
    unit: str | None
    beneficial_direction: Literal["higher", "lower"]
    comparisons: tuple[MetricComparison, ...]
    confidence: Literal["high", "medium", "low"]
    source_type: Literal["match", "timeline", "match_and_timeline"]
    source_fact_ids: tuple[str, ...] = ()
    unavailable_reason: UnavailableReason | None = None
    metric_version: str

class DimensionScore(DomainModel):
    dimension: DimensionKey
    status: Literal["available", "unavailable"]
    score: float | None = Field(default=None, ge=0, le=100)
    configured_weight: float = Field(ge=0, le=100)
    applied_weight: float = Field(ge=0, le=100)
    coverage: float = Field(ge=0, le=1)
    evidence_ids: tuple[str, ...]

class ScoreBreakdown(DomainModel):
    role: AnalysisRole | None
    dimensions: tuple[DimensionScore, ...]
    overall_score: float | None = Field(default=None, ge=0, le=100)
    coverage: float = Field(ge=0, le=1)
    score_version: str

class Finding(DomainModel):
    rule_id: str
    kind: Literal["strength", "improvement"]
    severity: Literal["high", "medium", "low"]
    message_code: str
    params: dict[str, str | int | float]
    evidence_ids: tuple[str, ...]
    confidence: Literal["high", "medium", "low"]
    requires_replay_interpretation: bool = False

class TrainingGoal(DomainModel):
    rule_id: str
    message_code: str
    current_value: float
    target_value: float
    unit: str
    role: AnalysisRole
    evidence_ids: tuple[str, ...]
    rules_version: str

class DeterministicAnalysisResult(DomainModel):
    status: Literal["completed", "partial"]
    platform: Platform
    match_id: str
    selected_puuid: str
    role: AnalysisRole | None
    metrics: tuple[MetricEvidence, ...]
    scores: ScoreBreakdown
    findings: tuple[Finding, ...]
    goals: tuple[TrainingGoal, ...]
    unavailable_reasons: tuple[UnavailableReason, ...]
    input_hash: str
    metric_version: str
    score_version: str
    rules_version: str
    schema_version: Literal[1]
```

Add model validators enforcing available/unavailable shape and exactly five unique ordered dimensions. Do not include locale, Replay IDs, artifact IDs, or prose in `DeterministicAnalysisResult`.

- [ ] **Step 5: Encode the exact ruleset constants from this plan**

Put `ROLE_WEIGHTS`, `DIMENSION_SIGNALS`, the goal target table, all four version constants, the `0.60` overall threshold, finding thresholds, maximum counts, severity order, and rule priorities in `rules_v1.py`. Wrap maps in `MappingProxyType` or tuples so request code cannot mutate them.

- [ ] **Step 6: Run focused verification and commit**

Run:

```bash
cd backend && .venv/bin/pytest tests/test_config.py tests/test_analysis_domain.py -v
cd backend && .venv/bin/ruff check app/services/analyses tests/test_analysis_domain.py tests/test_config.py
cd backend && .venv/bin/mypy
git diff --check
git add backend/app/core/config.py backend/app/services/analyses backend/tests/test_config.py backend/tests/test_analysis_domain.py
git commit -m "feat: define deterministic analysis contracts"
```

Expected: focused tests PASS; Ruff and MyPy PASS.

---

### Task 2: Build the pure metric engine

**Files:**

- Create: `backend/app/services/analyses/metrics.py`
- Create: `backend/tests/fixtures/analysis_inputs.py`
- Create: `backend/tests/test_analysis_metrics.py`

- [ ] **Step 1: Add deterministic match/timeline fixtures and failing formula tests**

Create one standard 10-player `MatchSnapshot` fixture with one participant in each upstream role per team and a matching `TimelineSnapshot`. Include tied team values, one unique same-role opponent, selected-player elite-monster/building facts, a team-only objective fact, and stable fact IDs.

Test the public entry point:

```python
engine = MetricEngine()
catalog = engine.compute(match=match, timeline=timeline, selected_puuid="selected")
by_key = {metric.metric_key: metric for metric in catalog}
assert by_key["kda"].value == 6.0
assert by_key["cs_per_min"].unit == "per_minute"
assert by_key["deaths_per_10"].beneficial_direction == "lower"
assert by_key["explicit_objective_events"].source_fact_ids == (
    "timeline:elite_monster:1", "timeline:building:2"
)
```

Add table tests for KDA (`deaths=0` uses `kills+assists`, not division by zero), per-minute metrics, kill participation when team kills are zero, average-rank ties, lower-is-better rank direction, exact same-role formula, ambiguous/no opponent, absent Timeline, negative duration, and missing participant fields. Add a loop over at least 100 deterministic integer pairs asserting every available comparison score stays in `0..100`.

- [ ] **Step 2: Run the focused test and confirm failure**

Run: `cd backend && .venv/bin/pytest tests/test_analysis_metrics.py -v`

Expected: FAIL because `MetricEngine` is absent.

- [ ] **Step 3: Implement one pure entry point and small helpers**

Use this signature:

```python
class MetricEngine:
    def compute(
        self,
        *,
        match: MatchSnapshot,
        timeline: TimelineSnapshot | None,
        selected_puuid: str,
    ) -> tuple[MetricEvidence, ...]: ...
```

Private helpers must isolate `_safe_ratio`, `_team_percentile`, `_same_role_score`, `_find_unique_role_opponent`, `_selected_timeline_participant_id`, and `_explicit_objective_facts`. Compute base metrics in this stable order: `kda`, `cs_per_min`, `gold_per_min`, `damage_per_min`, `kill_participation`, `deaths_per_10`, `vision_per_min`, `explicit_objective_events`. Give evidence IDs `metric:v1:<metric_key>`. Comparisons live inside the corresponding base evidence; the score engine names individual signal use without duplicating metrics.

Team rank inputs include only selected player's teammates with a valid source value. Same-role comparison requires exactly one opponent whose normalized analysis role equals the selected role. Explicit objective credit includes only `EliteMonsterKillFact` or `BuildingKillFact` whose `killer_id` equals the selected Timeline participant ID; a team-only event never becomes personal credit.

- [ ] **Step 4: Prove neutral outcomes and typed unavailability**

Clone the fixture with only `won` toggled and assert the full metric catalog is identical. Assert absent Timeline returns `explicit_objective_events.status == "unavailable"`, `unavailable_reason == "timeline_unavailable"`, and no fabricated value.

- [ ] **Step 5: Run focused verification and commit**

```bash
cd backend && .venv/bin/pytest tests/test_analysis_metrics.py -v
cd backend && .venv/bin/ruff check app/services/analyses/metrics.py tests/fixtures/analysis_inputs.py tests/test_analysis_metrics.py
cd backend && .venv/bin/mypy
git diff --check
git add backend/app/services/analyses/metrics.py backend/tests/fixtures/analysis_inputs.py backend/tests/test_analysis_metrics.py
git commit -m "feat: compute deterministic match metrics"
```

Expected: all metric tests PASS and no score/finding code exists in the engine.

---

### Task 3: Implement role-aware score calculation and coverage

**Files:**

- Create: `backend/app/services/analyses/scoring.py`
- Create: `backend/tests/test_analysis_scoring.py`

- [ ] **Step 1: Write failing scoring tests at every boundary**

Tests must cover all five role-weight rows, exact `0.60` coverage acceptance, `0.5999` rejection, dimension signal renormalization, unknown role, clamping, stable dimension order, and win/loss neutrality. Use helpers that build `MetricEvidence` with controlled team/same-role comparison scores.

Representative assertion:

```python
scores = ScoreEngine().compute(role="support", metrics=metrics)
assert [item.dimension for item in scores.dimensions] == [
    "economy", "combat", "survivability", "team_objectives", "vision"
]
assert scores.coverage == 0.60
assert scores.overall_score is not None
assert sum(item.applied_weight for item in scores.dimensions) == pytest.approx(100.0)
```

- [ ] **Step 2: Confirm red state**

Run: `cd backend && .venv/bin/pytest tests/test_analysis_scoring.py -v`

Expected: FAIL because `ScoreEngine` is absent.

- [ ] **Step 3: Implement scoring with explicit signal extraction**

Use:

```python
class ScoreEngine:
    def compute(
        self,
        *,
        role: AnalysisRole | None,
        metrics: tuple[MetricEvidence, ...],
    ) -> ScoreBreakdown: ...
```

Create an internal `_signal_score(signal_key, metric_by_key)` mapping for every key in `DIMENSION_SIGNALS`. Every base metric carries zero, one, or two uniquely based comparisons in `MetricEvidence.comparisons`. Team signals select `basis == "team_percentile"`; same-role signals select `basis == "same_role"`. Do not infer a score from the raw metric value.

Calculate dimension coverage from declared signal weights, then calculate the overall coverage and applied normalized weights exactly as stated in this plan. When coverage is below threshold, return `overall_score=None` and set all applied weights to `0`; still return available dimension scores and configured weights.

- [ ] **Step 4: Run property-style bounds loop and focused verification**

```bash
cd backend && .venv/bin/pytest tests/test_analysis_scoring.py -v
cd backend && .venv/bin/ruff check app/services/analyses/scoring.py tests/test_analysis_scoring.py
cd backend && .venv/bin/mypy
git diff --check
git add backend/app/services/analyses/domain.py backend/app/services/analyses/scoring.py backend/tests/test_analysis_domain.py backend/tests/test_analysis_metrics.py backend/tests/test_analysis_scoring.py
git commit -m "feat: score deterministic analysis by role"
```

Expected: all score outputs in the deterministic test matrix are bounded, and unknown role/below-threshold cases have no overall score.

---

### Task 4: Generate bounded findings and measurable goals

**Files:**

- Create: `backend/app/services/analyses/rules.py`
- Create: `backend/tests/test_analysis_rules.py`

- [ ] **Step 1: Write failing rule-engine tests**

Cover strength and improvement thresholds, dimension coverage suppression, overall coverage suppression, severity/priority/rule-ID ordering, combined cap of three findings, goal cap of three, every role target, lower-is-better death goals, Support CS suppression, missing evidence suppression, and reference closure.

Test the interface:

```python
findings, goals = RuleEngine().evaluate(role="support", metrics=metrics, scores=scores)
assert len(findings) <= 3
assert len(goals) <= 3
assert all(ref in {m.evidence_id for m in metrics} for item in (*findings, *goals) for ref in item.evidence_ids)
assert all(goal.rule_id != "goal.support.cs_per_min" for goal in goals)
```

- [ ] **Step 2: Confirm red state**

Run: `cd backend && .venv/bin/pytest tests/test_analysis_rules.py -v`

Expected: FAIL because `RuleEngine` is absent.

- [ ] **Step 3: Implement stable structured rules**

Use:

```python
class RuleEngine:
    def evaluate(
        self,
        *,
        role: AnalysisRole | None,
        metrics: tuple[MetricEvidence, ...],
        scores: ScoreBreakdown,
    ) -> tuple[tuple[Finding, ...], tuple[TrainingGoal, ...]]: ...
```

Finding codes are `analysis.finding.<dimension>.strength` and `analysis.finding.<dimension>.improvement`. Goal codes are `analysis.goal.<metric_key>`. Params contain only typed `score`, `coverage`, `current`, `target`, and `unit` values needed by both catalogs. Evidence references are the dimension's evidence IDs for findings and the exact metric evidence ID for goals. `requires_replay_interpretation` remains `False` in all V1 outputs.

Normalized goal gap is `(target-current)/max(abs(target), 1e-9)` for higher-is-better and `(current-target)/max(abs(target), 1e-9)` for deaths. Do not emit a goal when the target is already met.

- [ ] **Step 4: Verify and commit**

```bash
cd backend && .venv/bin/pytest tests/test_analysis_rules.py -v
cd backend && .venv/bin/ruff check app/services/analyses/rules.py tests/test_analysis_rules.py
cd backend && .venv/bin/mypy
git diff --check
git add backend/app/services/analyses/rules.py backend/tests/test_analysis_rules.py
git commit -m "feat: derive deterministic coaching rules"
```

Expected: deterministic ordering/caps and evidence-closure tests PASS.

---

### Task 5: Add PostgreSQL models, migration, and atomic repository

**Files:**

- Create: `backend/app/models/analysis.py`
- Create: `backend/app/repositories/analyses.py`
- Create: `backend/alembic/versions/0005_deterministic_analyses.py`
- Create: `backend/tests/test_analysis_models.py`
- Create: `backend/tests/test_analysis_repository_contract.py`
- Create: `backend/tests/integration/test_analysis_repository.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/repositories/__init__.py`
- Modify: `backend/tests/integration/test_migrations.py`

- [ ] **Step 1: Write failing row and repository contract tests**

Define the repository contract first:

```python
@dataclass(frozen=True)
class StoredAnalysis:
    analysis_id: UUID
    idempotency_key: str
    result: DeterministicAnalysisResult
    created_at: datetime
    expires_at: datetime

class AnalysisRepository(Protocol):
    async def get(self, *, analysis_id: UUID, now: datetime) -> StoredAnalysis | None: ...
    async def create_or_reuse(
        self,
        *,
        idempotency_key: str,
        result: DeterministicAnalysisResult,
        now: datetime,
        expires_at: datetime,
    ) -> tuple[StoredAnalysis, bool]: ...
    async def delete_expired(self, *, now: datetime) -> int: ...
```

The returned bool is `created`; API `cached` is its inverse. Unit contract tests validate timezone awareness, 64-character lowercase SHA-256 keys, result/input hash equality, and invalid persistence shapes.

- [ ] **Step 2: Write failing PostgreSQL behavior tests**

Add integration tests that run against `postgres_database`/`postgres_session_factory` and assert:

- first insert returns `created=True`, second identical insert returns the same UUID and `created=False`;
- 10 concurrent identical inserts produce exactly one `analysis_jobs` row and one `analysis_evidence` row;
- a read round-trips through `DeterministicAnalysisResult.model_validate`;
- an expired row is invisible to `get` and removed by `delete_expired`;
- deleting `analysis_jobs` cascades to `analysis_evidence`;
- the migration chain now ends at `0005_deterministic_analyses`.

- [ ] **Step 3: Confirm red state**

Run:

```bash
cd backend && .venv/bin/pytest tests/test_analysis_models.py tests/test_analysis_repository_contract.py -v
test -n "$TEST_DATABASE_URL" && cd backend && DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/alembic upgrade head && .venv/bin/pytest tests/integration/test_analysis_repository.py tests/integration/test_migrations.py -m integration -v
```

Expected: FAIL because the rows, migration, and repository do not exist.

- [ ] **Step 4: Create the forward-only migration**

`0005_deterministic_analyses.py` must create:

```text
analysis_jobs:
  id UUID PK
  platform VARCHAR(8) NOT NULL
  match_id VARCHAR(64) NOT NULL
  selected_puuid VARCHAR(128) NOT NULL
  idempotency_key VARCHAR(64) UNIQUE NOT NULL
  input_hash VARCHAR(64) NOT NULL
  status VARCHAR(16) CHECK IN ('completed','partial') NOT NULL
  metric_version VARCHAR(64) NOT NULL
  score_version VARCHAR(64) NOT NULL
  rules_version VARCHAR(64) NOT NULL
  created_at TIMESTAMPTZ NOT NULL
  updated_at TIMESTAMPTZ NOT NULL
  completed_at TIMESTAMPTZ NOT NULL
  expires_at TIMESTAMPTZ NOT NULL

analysis_evidence:
  analysis_id UUID PK/FK analysis_jobs(id) ON DELETE CASCADE
  evidence_catalog JSONB NOT NULL
  deterministic_result JSONB NOT NULL
  input_hash VARCHAR(64) NOT NULL
  schema_version INTEGER CHECK > 0 NOT NULL
  created_at TIMESTAMPTZ NOT NULL
```

Add indexes on `(platform, match_id, selected_puuid)`, `expires_at`, and the unique idempotency key. `downgrade()` may drop only these two new tables/indexes; rollout uses feature-flag rollback, not schema downgrade.

- [ ] **Step 5: Implement atomic `INSERT .. ON CONFLICT DO NOTHING` reuse**

In one transaction, attempt the job insert with a generated UUID. If inserted, insert evidence and return it. If the unique key loses, read the winning joined row in the same transaction and validate its hashes/versions/result. Never overwrite an existing result. Treat a mismatched or malformed winning row as an internal persistence error; do not return it.

Store `evidence_catalog` as `[metric.model_dump(mode="json") ...]` and `deterministic_result` as the complete locale-neutral result. Do not store raw Riot DTOs or Replay state.

- [ ] **Step 6: Run focused/PostgreSQL verification and commit**

```bash
cd backend && .venv/bin/pytest tests/test_analysis_models.py tests/test_analysis_repository_contract.py -v
test -n "$TEST_DATABASE_URL" && cd backend && DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/alembic upgrade head && .venv/bin/pytest tests/integration/test_analysis_repository.py tests/integration/test_migrations.py -m integration -v
cd backend && .venv/bin/ruff check app/models/analysis.py app/repositories/analyses.py alembic/versions/0005_deterministic_analyses.py tests/test_analysis_models.py tests/test_analysis_repository_contract.py tests/integration/test_analysis_repository.py
cd backend && .venv/bin/mypy
git diff --check
git add backend/app/models backend/app/repositories backend/alembic/versions/0005_deterministic_analyses.py backend/tests/test_analysis_models.py backend/tests/test_analysis_repository_contract.py backend/tests/integration/test_analysis_repository.py backend/tests/integration/test_migrations.py
git commit -m "feat: persist deterministic analyses"
```

Expected: migration and real-concurrency tests PASS.

---

### Task 6: Orchestrate Match/Timeline inputs, hashing, degradation, and reuse

**Files:**

- Create: `backend/app/services/analyses/service.py`
- Create: `backend/tests/test_analysis_service.py`
- Modify: `backend/app/core/errors.py`

- [ ] **Step 1: Write fakes and failing service tests**

Use the existing `MatchResolver.get_evidence_context` behavior as the supported-queue/player-membership gate. Map its `MATCH_EVIDENCE_UNSUPPORTED_MODE` error to the analysis-specific `422 MATCH_ANALYSIS_UNSUPPORTED_MODE` from the approved API contract; preserve `PLAYER_NOT_IN_MATCH` unchanged. Define:

```python
class AnalysisResolver(Protocol):
    async def create_or_reuse(
        self, *, platform: Platform, match_id: str, puuid: str
    ) -> tuple[UUID, DeterministicAnalysisResult, bool]: ...
    async def get(self, *, analysis_id: UUID) -> DeterministicAnalysisResult: ...

class DisabledAnalysisService:
    async def create_or_reuse(...): raise not_found()
    async def get(...): raise not_found()
```

Service tests must assert completed flow, Timeline-not-found partial flow, safe Timeline upstream partial flow, malformed Timeline hard failure, unsupported-mode error mapping, exact idempotent reuse, different input/version creates a new key, locale is impossible to pass into computation, Replay is absent, static-data resolution is absent, result reference closure is checked before persistence, expired cleanup is requested, and failed computation never calls `create_or_reuse`.

- [ ] **Step 2: Confirm red state**

Run: `cd backend && .venv/bin/pytest tests/test_analysis_service.py -v`

Expected: FAIL because the service does not exist.

- [ ] **Step 3: Implement the service with injectable pure collaborators**

Constructor and methods:

```python
class AnalysisService:
    def __init__(
        self,
        *,
        match_service: MatchEvidenceContext,
        timeline_service: TimelineEvidenceSource,
        repository: AnalysisRepository,
        metric_engine: MetricEngine,
        score_engine: ScoreEngine,
        rule_engine: RuleEngine,
        retention_days: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None: ...

    async def create_or_reuse(
        self, *, platform: Platform, match_id: str, puuid: str
    ) -> tuple[UUID, DeterministicAnalysisResult, bool]: ...

    async def get(self, *, analysis_id: UUID) -> DeterministicAnalysisResult: ...
```

Catch only these Timeline `ApiError.code` values for Match-only partial degradation: `MATCH_TIMELINE_NOT_FOUND`, `RIOT_AUTH_FAILED`, `RIOT_RATE_LIMITED`, and `RIOT_UNAVAILABLE`. Propagate `RIOT_INVALID_RESPONSE`, roster mismatches, validation failures, cancellations, and unknown exceptions. Record the caught code as a typed result-level unavailable reason by mapping it to `timeline_unavailable`; do not store free-form upstream messages.

- [ ] **Step 4: Canonicalize and hash exactly once**

Implement helpers:

```python
def canonical_analysis_input(
    *, match: MatchSnapshot, timeline: TimelineSnapshot | None, selected_puuid: str
) -> bytes: ...

def analysis_idempotency_key(
    *, platform: Platform, match_id: str, selected_puuid: str,
    input_hash: str, metric_version: str, score_version: str, rules_version: str,
) -> str: ...

def validate_reference_closure(result: DeterministicAnalysisResult) -> None: ...
```

Serialize JSON with `sort_keys=True`, `separators=(",", ":")`, UTF-8, and Pydantic `mode="json"`. The input includes the entire normalized Match snapshot because team rankings depend on all participants; includes the entire normalized Timeline snapshot or explicit `null`; includes selected PUUID; excludes locale and Replay. Hash with SHA-256 lowercase hex. The idempotency material uses platform, match ID, selected PUUID, input hash, and all three versions in a fixed JSON object.

Reference validation requires every finding/goal evidence ID to exist exactly once in `result.metrics`, every metric source fact ID to exist in the supplied Timeline when Timeline is present, no fact IDs when Timeline is absent, five unique dimensions, and bounded scores. Raise an internal domain exception before repository access on failure.

- [ ] **Step 5: Return completed/partial deterministically**

Set `partial` when Timeline is unavailable or any of the seven Match metrics (`kda`, `cs_per_min`, `gold_per_min`, `damage_per_min`, `kill_participation`, `deaths_per_10`, `vision_per_min`) is unavailable; otherwise `completed`. Below-coverage or unknown-role results are `partial` and must not contain an overall score or judgmental findings. Deduplicate result unavailable reasons and order them by the `UnavailableReason` declaration. Call `delete_expired(now=now)` only after a successful create/reuse response so cleanup cannot destroy the request result.

- [ ] **Step 6: Verify and commit**

```bash
cd backend && .venv/bin/pytest tests/test_analysis_service.py -v
cd backend && .venv/bin/ruff check app/services/analyses/service.py app/core/errors.py tests/test_analysis_service.py
cd backend && .venv/bin/mypy
git diff --check
git add backend/app/services/analyses/service.py backend/app/core/errors.py backend/tests/test_analysis_service.py
git commit -m "feat: orchestrate deterministic analysis"
```

Expected: completed/partial/hash/reuse/failure-path tests PASS.

---

### Task 7: Expose dark-by-default APIs and closed-label observability

**Files:**

- Create: `backend/app/schemas/analyses.py`
- Create: `backend/app/api/analyses.py`
- Create: `backend/tests/test_analysis_schemas.py`
- Create: `backend/tests/test_analysis_api.py`
- Create: `backend/tests/test_analysis_observability.py`
- Modify: `backend/app/core/dependencies.py`
- Modify: `backend/app/core/metrics.py`
- Modify: `backend/app/core/errors.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/conftest.py`
- Modify: any focused tests that construct `AppServices` directly

- [ ] **Step 1: Write failing strict schema tests**

Create request/response models with these public shapes:

```python
class AnalysisCreateRequest(DomainModel):
    platform: Platform
    match_id: str = Field(min_length=1, max_length=64)
    puuid: str = Field(min_length=1, max_length=128)
    locale: Locale = Locale.EN_US

class AnalysisResponse(DomainModel):
    analysis_id: UUID
    status: Literal["completed", "partial"]
    cached: bool
    locale: Locale
    role: AnalysisRole | None
    metrics: tuple[MetricEvidence, ...]
    scores: ScoreBreakdown
    findings: tuple[Finding, ...]
    goals: tuple[TrainingGoal, ...]
    unavailable_reasons: tuple[UnavailableReason, ...]
    input_hash: str
    metric_version: str
    score_version: str
    rules_version: str
    schema_version: Literal[1]
    scope_notice_code: Literal["DETERMINISTIC_DATA_COACHING_NO_AI"]
    request_id: str
```

Assert extra fields, unsupported locales/roles/statuses, malformed UUID/hash, invalid evidence references, and more than three findings/goals are rejected. The schema projector must not include `selected_puuid` in the response.

- [ ] **Step 2: Write failing API behavior tests**

Add `FakeAnalysisService` to `backend/tests/conftest.py` and make `AppServices.analysis_service` default to `DisabledAnalysisService`, after the existing `joint_evidence_service` default, so old focused service constructors stay valid.

Test:

- flag-disabled `POST /api/v1/analyses` and `GET /api/v1/analyses/{uuid}` return the safe `404 NOT_FOUND` envelope;
- POST validates the body, calls the service without locale, and returns 200 with the requested locale;
- create returns `cached=False` for a new row and `cached=True` for reuse;
- GET accepts only supported `locale` and returns 200 with `cached=True`;
- unknown/expired IDs return safe 404;
- unsupported queue, absent player, and upstream errors preserve allowlisted error codes;
- response body never contains selected PUUID, raw Timeline payload, Replay token, or free-form error body.

- [ ] **Step 3: Write failing metric-registry tests**

Require these closed-label series in `MetricsRegistry.render_prometheus()`:

```text
analysis_api_requests_total{outcome,error_code}
analysis_duration_seconds{stage}
analysis_cache_total{status}
analysis_results_total{status}
analysis_coverage_total{bucket}
analysis_unavailable_signals_total{reason}
analysis_finding_count
analysis_goal_count
analysis_idempotency_total{result}
```

Allow only fixed label sets declared on the service: API outcomes `ready|error`; cache `hit|miss`; status `completed|partial`; coverage buckets `lt_60|60_79|80_99|100`; stages `compute|persist|total`; idempotency `created|reused`; and the domain unavailable reasons. Tests must reject arbitrary labels and prove rendered output contains no match ID or PUUID.

- [ ] **Step 4: Confirm red state**

```bash
cd backend && .venv/bin/pytest tests/test_analysis_schemas.py tests/test_analysis_api.py tests/test_analysis_observability.py -v
```

Expected: FAIL because schema/router/service wiring/metrics do not exist.

- [ ] **Step 5: Implement router and projection**

Create a router with prefix `/api/v1/analyses`, tag `analyses`, and `bind_safe_request_context` dependency:

```python
@router.post("", response_model=AnalysisResponse)
async def create_analysis(request: Request, body: AnalysisCreateRequest, services: ...) -> AnalysisResponse: ...

@router.get("/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(
    request: Request, analysis_id: UUID, services: ..., locale: Locale = Locale.EN_US
) -> AnalysisResponse: ...
```

Keep a single `_response(...)` projector. POST passes only platform/match ID/PUUID to the service. GET passes only UUID. Locale is echoed by the projector. Register the router unconditionally in `main.py`; the disabled service owns dark 404 behavior.

- [ ] **Step 6: Wire enabled/disabled service construction**

In `build_services`, construct `TimelineService` once when J1 is enabled and reuse the same instance for J1 and Analysis. When analysis is enabled, construct `SqlAnalysisRepository`, all three pure engines, and `AnalysisService`; otherwise use `DisabledAnalysisService`. Do not create a second Riot client, gateway, Timeline normalizer, or cache.

Update every `AppServices(...)` construction only where needed; the default disabled analysis service should keep unrelated tests concise.

- [ ] **Step 7: Record safe metrics and errors**

Measure compute, persistence, and total service stages with the injected monotonic clock. Add analysis-route recognition alongside the existing J1 recognition in `core/errors.py`, so safe `ApiError` responses increment analysis API error counters. Hash PUUID for optional safe logs with SHA-256 and truncate to 12 hex characters; never use the full value as a metric label.

- [ ] **Step 8: Verify and commit**

```bash
cd backend && .venv/bin/pytest tests/test_analysis_schemas.py tests/test_analysis_api.py tests/test_analysis_observability.py tests/test_app_factory.py tests/test_errors.py -v
cd backend && .venv/bin/ruff check app/api/analyses.py app/schemas/analyses.py app/core/dependencies.py app/core/metrics.py app/core/errors.py app/main.py tests/test_analysis_schemas.py tests/test_analysis_api.py tests/test_analysis_observability.py
cd backend && .venv/bin/mypy
git diff --check
git add backend/app/api/analyses.py backend/app/schemas/analyses.py backend/app/core/dependencies.py backend/app/core/metrics.py backend/app/core/errors.py backend/app/main.py backend/tests
git commit -m "feat: expose deterministic analysis api"
```

Expected: dark-route, enabled-route, response privacy, and closed-label metrics tests PASS.

---

### Task 8: Add strict frontend analysis schemas and API client

**Files:**

- Modify: `frontend/src/api/schemas.ts`
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/tests/analysis-api-client.test.ts`

- [ ] **Step 1: Write failing strict Zod-schema tests**

Add fixtures for completed and partial responses. Assert the completed fixture parses; reject unknown role `UTILITY`, any score above 100, an available metric without value/unit, an unavailable metric with a value, duplicate comparison basis, more/fewer than five dimensions, a finding/goal referencing an absent evidence ID, more than three findings/goals, extra fields, and wrong scope/version literals.

- [ ] **Step 2: Write failing API-client request tests**

Test exact calls:

```typescript
await createAnalysis({ platform: "NA1", matchId: "NA1_1", puuid: "p1", locale: "zh-CN" });
expect(fetch).toHaveBeenCalledWith(
  "http://localhost:8000/api/v1/analyses",
  expect.objectContaining({
    method: "POST",
    body: JSON.stringify({ platform: "NA1", match_id: "NA1_1", puuid: "p1", locale: "zh-CN" }),
  }),
);

await getAnalysis({ analysisId, locale: "en-US" });
expect(fetch).toHaveBeenCalledWith(
  `http://localhost:8000/api/v1/analyses/${analysisId}?locale=en-US`,
  expect.objectContaining({ method: "GET" }),
);
```

Also assert cancellation preserves `AbortError`, safe API errors become `ApiClientError`, malformed success becomes `INVALID_API_RESPONSE`, and `zh-CN`/`en-US` responses with the same analysis ID are both accepted.

- [ ] **Step 3: Confirm red state**

Run: `cd frontend && pnpm test -- analysis-api-client.test.ts`

Expected: FAIL because schemas and client methods are missing.

- [ ] **Step 4: Implement strict schemas and refinements**

Export `analysisRoleSchema`, `analysisMetricSchema`, `dimensionScoreSchema`, `scoreBreakdownSchema`, `analysisFindingSchema`, `analysisGoalSchema`, `analysisResponseSchema`, and inferred `AnalysisResponse`. Use `.strict()` at every object level and `.superRefine()` to enforce:

- available/unavailable value shape;
- one comparison per basis;
- five unique dimensions in canonical order;
- overall score absent when role absent or coverage below `0.60`;
- evidence-reference closure;
- max-three caps;
- 64-character lowercase hex `input_hash` and fixed version/scope literals.

- [ ] **Step 5: Add the two typed client calls**

```typescript
export type CreateAnalysisInput = {
  platform: Platform; matchId: string; puuid: string; locale: Locale;
};
export async function createAnalysis(input: CreateAnalysisInput, signal?: AbortSignal) { ... }

export type GetAnalysisInput = { analysisId: string; locale: Locale };
export async function getAnalysis(input: GetAnalysisInput, signal?: AbortSignal) { ... }
```

Use the existing private `request()` helper; do not add a parallel fetch/error implementation.

- [ ] **Step 6: Verify and commit**

```bash
cd frontend && pnpm test -- analysis-api-client.test.ts api-client.test.ts
cd frontend && pnpm lint
cd frontend && pnpm typecheck
git diff --check
git add frontend/src/api/schemas.ts frontend/src/api/client.ts frontend/tests/analysis-api-client.test.ts
git commit -m "feat: add deterministic analysis client"
```

Expected: strict schema and exact request tests PASS.

---

### Task 9: Render the bilingual analysis panel and accessible evidence navigation

**Files:**

- Create: `frontend/src/components/analysis-section.tsx`
- Create: `frontend/tests/analysis-section.test.tsx`
- Modify: `frontend/src/components/match-detail-client.tsx`
- Modify: `frontend/src/components/evidence-section.tsx`
- Modify: `frontend/tests/evidence-section.test.tsx`
- Modify: `frontend/tests/match-detail-page.test.tsx`
- Modify: `frontend/src/i18n/en-US.ts`
- Modify: `frontend/src/i18n/zh-CN.ts`
- Modify: `frontend/tests/i18n.test.ts`
- Modify: `frontend/src/app/globals.css`

- [ ] **Step 1: Write failing panel state and content tests**

Test idle generate, loading `aria-live`, completed, cached, partial, missing overall, retryable/non-retryable error, abort on identity/locale change, and stale response suppression. Assert:

- overall score and five dimensions render numerically plus text, never color alone;
- unavailable dimensions say unavailable and do not render `0`;
- at most three findings/goals render;
- deterministic/no-AI and non-Riot-score notices are visible;
- roles display `Support`/`辅助`, never `Utility`;
- win/loss is not mentioned as a score cause;
- unknown backend message codes fall back safely rather than rendering raw codes/params.

- [ ] **Step 2: Write failing cross-section focus tests**

Add `id={`evidence-fact-${fact.fact_id}`}` and `tabIndex={-1}` to J1 fact list items. Define:

```typescript
export type EvidenceFocusRequest = { factId: string; nonce: number };
```

Test two paths:

1. J1 is already ready: clicking a Timeline-backed analysis evidence button scrolls the fact into view and moves focus to it.
2. J1 is idle: the request starts `prepareMatchEvidence` once; after the fact renders, focus moves to the exact fact. If the fact is absent, focus the Evidence section heading and announce `analysisEvidenceUnavailable`; never select a near timestamp or arbitrary window.

- [ ] **Step 3: Confirm red state**

Run:

```bash
cd frontend && pnpm test -- analysis-section.test.tsx evidence-section.test.tsx match-detail-page.test.tsx i18n.test.ts
```

Expected: FAIL because the panel, messages, and focus protocol are absent.

- [ ] **Step 4: Implement the on-demand panel**

`AnalysisSection` props:

```typescript
export function AnalysisSection({
  locale, matchId, puuid, platform, onEvidenceFactRequest,
}: {
  locale: Locale;
  matchId: string;
  puuid: string;
  platform: Platform;
  onEvidenceFactRequest: (factId: string) => void;
}) { ... }
```

Use an `idle | loading | ready | error` discriminated state, one `AbortController`, and a monotonically increasing request key. Call only `createAnalysis`; it already handles create-or-reuse. Render finding/goal prose by exhaustive message-code switch and safe parameter formatting. Render supporting metric labels/values inside the panel; render J1 navigation buttons only for `source_fact_ids`, not for Match-only evidence.

- [ ] **Step 5: Coordinate evidence focus in the match page**

`MatchDetailClient` owns `EvidenceFocusRequest | null`. Increment `nonce` for repeat clicks, pass the callback to `AnalysisSection`, and pass the request to `EvidenceSection`. Place Analysis after team tables and before Replay/J1 so the coaching result does not visually redefine the neutral evidence section.

Refactor `EvidenceSection.runPrepare` to a stable `useCallback`. On a new focus request, prepare if idle/error, then after ready render use `CSS.escape(factId)` or an equivalent safe DOM lookup, call `scrollIntoView({ block: "center" })`, and `.focus()`. Cancel pending focus on identity change/unmount. Do not automatically open or access Replay artifacts.

- [ ] **Step 6: Add complete bilingual copy**

Add catalog keys for panel title/actions/statuses, five dimensions, five roles, available/partial/unavailable/coverage labels, cached label, structured finding and goal codes, units, deterministic scope notice, non-Riot-score disclaimer, all safe API errors, and evidence-unavailable fallback. English `support` is `Support`; Chinese is `辅助`.

Extend `i18n.test.ts` with a deterministic-analysis required-key list and assertions that both catalogs have identical keys, no `Utility`, no claim that the score is Riot/MMR/ELO/rank, and no positioning/mechanics/awareness/intent/causality phrasing.

- [ ] **Step 7: Add accessible responsive styling**

Reuse the existing visual language but give the analysis panel a distinct section boundary. Use visible text/icons for strength, improvement, partial, and unavailable states; preserve keyboard focus rings; keep score grids readable at 320px and desktop widths; respect reduced motion. Do not add a chart library.

- [ ] **Step 8: Verify and commit**

```bash
cd frontend && pnpm test -- analysis-section.test.tsx evidence-section.test.tsx match-detail-page.test.tsx i18n.test.ts
cd frontend && pnpm lint
cd frontend && pnpm typecheck
cd frontend && pnpm build
git diff --check
git add frontend/src frontend/tests
git commit -m "feat: render deterministic coaching analysis"
```

Expected: all panel states, bilingual terminology, focus behavior, lint, typecheck, and production build PASS.

---

### Task 10: Add runtime configuration, safe real smoke, and rollout documentation

**Files:**

- Create: `scripts/smoke_analysis.py`
- Create: `backend/tests/test_analysis_smoke_script.py`
- Modify: `backend/tests/test_runtime_privacy.py`
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Modify: `Makefile`
- Modify: `README.md`

- [ ] **Step 1: Write failing smoke contract/privacy tests**

The smoke must reuse ignored `RIOT_SMOKE_GAME_NAME`, `RIOT_SMOKE_TAG_LINE`, and `RIOT_SMOKE_PLATFORM`; do not add another real identity to configuration. Fake HTTP responses and assert the flow:

1. resolve the configured account;
2. list recent matches and choose the newest item where both `analysis_supported` and `detail_supported` are true;
3. POST analysis in `zh-CN`;
4. POST identical analysis in `en-US`;
5. GET the returned analysis in both locales;
6. assert one analysis ID/input hash/versions across all four responses, first create may be miss or hit, second must be `cached=true`, and numeric/result payloads are locale-neutral;
7. assert each finding/goal reference closes over the returned metrics and every score is bounded.

Capture stdout/stderr and assert they contain none of the configured Riot ID parts, PUUID, match ID, API key, full URL, response body, or evidence content. Unexpected exceptions must collapse to `ANALYSIS_SMOKE_REQUEST_FAILED`.

- [ ] **Step 2: Confirm red state**

Run: `cd backend && .venv/bin/pytest tests/test_analysis_smoke_script.py tests/test_runtime_privacy.py -v`

Expected: FAIL because the analysis smoke is absent.

- [ ] **Step 3: Implement safe smoke output**

The only success line is:

```text
analysis=completed|partial metrics=<n> dimensions=5 findings=<0..3> goals=<0..3> coverage=<bucket> repeat=ok locales=2 request_id=<safe-or-none> versions=ok
```

The coverage value is one of `lt_60|60_79|80_99|100`, not a raw payload. Use the same 32-hex request-ID allowlist as other smoke scripts. `SmokeFailure.__str__` prints only an allowlisted uppercase code. Never interpolate the URL or caught exception.

- [ ] **Step 4: Add Make/Compose/environment settings**

Add `smoke-analysis` to `.PHONY` and:

```make
smoke-analysis:
	PYTHONPATH=backend backend/.venv/bin/python scripts/smoke_analysis.py
```

Add to `.env.example`:

```dotenv
DETERMINISTIC_ANALYSIS_ENABLED=false
ANALYSIS_RETENTION_DAYS=30
```

Pass both values into only the backend Compose service. The replay worker does not perform analysis and must not receive them. No secret or `NEXT_PUBLIC_*` analysis flag is added.

- [ ] **Step 5: Document bilingual boundary and rollout**

Update both README languages with:

- deterministic V1 capabilities and explicit no-model/no-replay-vision boundary;
- `UTILITY -> Support/辅助` boundary wording;
- migration `0005`, dark deployment, J1 prerequisite, enable, smoke twice, monitoring, and flag-only rollback order;
- `make smoke-analysis` requirements and safe-output contract;
- the two environment variables and two analysis routes;
- exact statement that this is a single-match LoL AI Coach score, not Riot score/rank/MMR/ELO;
- no claim that live/browser/CI acceptance passed until Task 11 records it.

- [ ] **Step 6: Verify and commit**

```bash
cd backend && .venv/bin/pytest tests/test_analysis_smoke_script.py tests/test_runtime_privacy.py -v
cd backend && .venv/bin/ruff check ../scripts/smoke_analysis.py tests/test_analysis_smoke_script.py tests/test_runtime_privacy.py
git diff --check
git add scripts/smoke_analysis.py backend/tests/test_analysis_smoke_script.py backend/tests/test_runtime_privacy.py .env.example docker-compose.yml Makefile README.md
git commit -m "docs: add deterministic analysis rollout"
```

Expected: smoke contract/privacy tests PASS, and tracked files contain no live identifiers or credentials.

---

### Task 11: Run focused regression, real PostgreSQL concurrency, and browser QA

**Files:**

- Modify only files required by defects found during verification.
- Record no generated screenshots, database dumps, `.env`, media, or smoke payloads in Git.

- [ ] **Step 1: Run all deterministic-analysis focused tests together**

```bash
cd backend && .venv/bin/pytest tests/test_analysis_*.py -m "not integration" -v
cd frontend && pnpm test -- analysis-api-client.test.ts analysis-section.test.tsx evidence-section.test.tsx match-detail-page.test.tsx i18n.test.ts
```

Expected: PASS with no test-order dependency.

- [ ] **Step 2: Run the entire standard gate**

Run: `make verify`

Expected: all backend non-integration tests, all frontend tests, Ruff check/format, ESLint, MyPy, TypeScript, `git diff --check`, and production Next.js build PASS.

- [ ] **Step 3: Run real PostgreSQL gates**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://lol_ai_coach:lol_ai_coach@localhost:5432/lol_ai_coach_test make verify-postgres
TEST_DATABASE_URL=postgresql+asyncpg://lol_ai_coach:lol_ai_coach@localhost:5432/lol_ai_coach_test make verify-replay-postgres
```

Expected: Alembic reaches `0005`; full integration, analysis concurrency, Timeline, platform-detection, Match, and Replay repository tests PASS.

- [ ] **Step 4: Run real FFmpeg regression**

Run: `make verify-replay-ffmpeg`

Expected: real FFmpeg/ffprobe integration PASS; analysis introduced no media behavior.

- [ ] **Step 5: Start the feature-enabled local stack**

Set only in ignored `.env`:

```dotenv
JOINT_EVIDENCE_ENABLED=true
DETERMINISTIC_ANALYSIS_ENABLED=true
```

Apply Alembic head, then run backend/frontend using the repository targets. If Riot rejects the configured development key, open `/Users/pf/lol-ai-coach/.env` directly for the user to refresh it; do not display or copy the key.

- [ ] **Step 6: Run real Riot/J1 and deterministic smokes**

```bash
make smoke-riot
make smoke-analysis
make smoke-analysis
```

Expected: Riot match/locales/repeat pass; J1 facts/windows/cache pass; both analysis runs show `repeat=ok`, `locales=2`, bounded counts, stable versions, and the same persisted analysis reused. Output contains no real identifiers.

- [ ] **Step 7: Run browser visual/accessibility QA in both locales**

At desktop and 320px width, verify `/zh-CN/matches/...` and `/en-US/matches/...`:

- generate/loading/completed-or-partial/cached states are visually distinct;
- five dimensions, findings, goals, coverage, deterministic notice, and non-Riot-score disclaimer are readable;
- Support/辅助 terminology is correct and `Utility` absent;
- keyboard-only generation and evidence navigation work;
- J1 prepares on demand and focuses the exact referenced fact;
- absent evidence has the localized fallback;
- Replay section remains separately authorized and analysis never opens media automatically;
- no horizontal overflow, clipped focus ring, or color-only meaning.

Use temporary screenshots only for visual inspection and do not commit them.

- [ ] **Step 8: Run isolated Replay Compose zero-residue regression**

Use the already established anonymous Docker config so Docker Desktop credential state is untouched:

```bash
DOCKER_CONFIG=/private/tmp/lol-ai-coach-docker-anon \
DOCKER_HOST=unix:///Users/pf/.docker/run/docker.sock \
COMPOSE_PROJECT_NAME=lol-ai-coach-analysis-e2e \
make e2e-replay-compose
```

Expected: both locale routes 200, authorized Replay/J1 lifecycle PASS, delete PASS, and `replay_data` contains zero files. Always clean the isolated project containers/volumes after the result; do not stop the user's default project.

- [ ] **Step 9: Repair only evidence-backed failures and rerun their containing gate**

For every failure, invoke systematic debugging, add/adjust a regression test first, implement the smallest correction, rerun the focused test, then rerun the full gate that exposed it. Commit coherent repairs as `fix: <specific deterministic analysis defect>`; never weaken strict schemas, privacy assertions, or scope limits merely to make a test green.

---

### Task 12: Final review, push, and remote verification

**Files:**

- Modify only evidence-backed repair files and, after all gates pass, the README observed-acceptance paragraph.

- [ ] **Step 1: Perform a specification coverage review**

Check every design section against implementation and tests. Explicitly verify: separate API/J1 neutrality, structured Riot-only computation, no Replay influence, role mapping, all metric formulas, exact weights/coverage, caps/order/reference closure, locale-neutral persistence, concurrency, 30-day retention, partial degradation, dark flag/J1 prerequisite, bilingual UI/accessibility, observability/privacy, and no OpenAI path.

Search:

```bash
rg -n "OpenAI|openai|prompt|UTILITY|Utility|positioning|mechanics|awareness|intent|causality" backend/app/services/analyses backend/app/api/analyses.py backend/app/schemas/analyses.py frontend/src/components/analysis-section.tsx frontend/src/i18n
rg -n "TODO|TBD|FIXME|pass$|NotImplemented" backend/app/services/analyses backend/app/api/analyses.py backend/app/schemas/analyses.py backend/app/models/analysis.py backend/app/repositories/analyses.py frontend/src/components/analysis-section.tsx scripts/smoke_analysis.py
```

Expected: only explicit scope/disclaimer copy or upstream-boundary role tests match the first search; the placeholder search returns no implementation placeholder.

- [ ] **Step 2: Run final evidence-before-completion gates**

Rerun `make verify`, both PostgreSQL targets, Replay FFmpeg, real Riot/J1 smoke, real analysis smoke twice, browser QA, isolated Compose zero-residue, and `git diff --check`. Do not reuse earlier output after a repair.

- [ ] **Step 3: Update observed acceptance truthfully**

Only after the corresponding live evidence exists, update the English and Chinese README observed-acceptance paragraphs with the exact locally verified boundaries. Separate automated/local PostgreSQL/FFmpeg/Compose/live Riot/browser results from GitHub CI. Do not call the feature AI-generated coaching; name it deterministic data coaching.

- [ ] **Step 4: Request code review and fix all substantiated findings**

Review the entire branch diff from the pre-feature commit through HEAD. Prioritize correctness/privacy/concurrency/schema findings. For each accepted finding, add a regression test, fix it, rerun the containing full gate, and commit. Document rejected findings with concrete code/test evidence.

- [ ] **Step 5: Confirm clean branch and push**

```bash
git status --short --branch
git log --oneline --decorate -15
git diff origin/feature/replay-r1...HEAD --check
git push origin feature/replay-r1
```

Expected: only intended commits, no tracked `.env`/media/generated payloads, push succeeds.

- [ ] **Step 6: Verify GitHub Actions remotely**

Watch the workflow created by the push until completion. Require backend and frontend jobs to succeed. If CI fails, inspect the concrete log, reproduce locally where possible, fix with a regression test, rerun all affected local gates, push again, and watch the replacement run.

- [ ] **Step 7: Report the exact completion boundary**

Report commit SHA, GitHub Actions run URL/result, local gates, live smoke results, browser/Compose results, and any genuinely manual/unverified boundary. The V1 completion claim is permitted only when all required gates above pass; otherwise report implemented vs verified separately.
