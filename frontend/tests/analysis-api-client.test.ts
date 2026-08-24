import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiClientError, createAnalysis, getAnalysis } from "@/api/client";
import {
  analysisResponseSchema,
  type AnalysisResponse,
} from "@/api/schemas";

const ANALYSIS_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const SAFE_REQUEST_ID = "a3f4c1d2e5b67890a1b2c3d4e5f60718";
const INPUT_HASH = "a".repeat(64);
const EVIDENCE_ID = "metric:v1:kda";

function clone<T>(value: T): T {
  return structuredClone(value);
}

function completedAnalysis(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    analysis_id: ANALYSIS_ID,
    status: "completed",
    cached: false,
    locale: "en-US",
    role: "support",
    metrics: [
      {
        evidence_id: EVIDENCE_ID,
        metric_key: "kda",
        category: "combat",
        status: "available",
        value: 6.0,
        unit: "ratio",
        beneficial_direction: "higher",
        comparisons: [{ basis: "team_percentile", score: 50.0, opponent_value: null }],
        confidence: "high",
        source_type: "match",
        source_fact_ids: [],
        unavailable_reason: null,
        metric_version: "deterministic-metrics-v1",
      },
    ],
    scores: {
      role: "support",
      dimensions: [
        "economy",
        "combat",
        "survivability",
        "team_objectives",
        "vision",
      ].map((dimension) => ({
        dimension,
        status: "available",
        score: 50.0,
        configured_weight: 20.0,
        applied_weight: 20.0,
        coverage: 1.0,
        evidence_ids: [EVIDENCE_ID],
      })),
      overall_score: 50.0,
      coverage: 1.0,
      score_version: "deterministic-score-v1",
    },
    findings: [
      {
        rule_id: "finding.vision.strength",
        kind: "strength",
        severity: "medium",
        message_code: "analysis.finding.vision.strength",
        params: { score: 80.0 },
        evidence_ids: [EVIDENCE_ID],
        confidence: "medium",
        requires_replay_interpretation: false,
      },
    ],
    goals: [
      {
        rule_id: "goal.support.vision_per_min",
        message_code: "analysis.goal.vision_per_min",
        current_value: 0.8,
        target_value: 1.2,
        unit: "per_minute",
        role: "support",
        evidence_ids: [EVIDENCE_ID],
        rules_version: "deterministic-rules-v1",
      },
    ],
    unavailable_reasons: [],
    input_hash: INPUT_HASH,
    metric_version: "deterministic-metrics-v1",
    score_version: "deterministic-score-v1",
    rules_version: "deterministic-rules-v1",
    schema_version: 1,
    scope_notice_code: "DETERMINISTIC_DATA_COACHING_NO_AI",
    request_id: SAFE_REQUEST_ID,
    ...overrides,
  };
}

function partialAnalysis(): Record<string, unknown> {
  const payload = completedAnalysis({
    status: "partial",
    role: null,
    cached: true,
    locale: "zh-CN",
    findings: [],
    goals: [],
    unavailable_reasons: ["timeline_unavailable", "role_unavailable"],
  });
  const scores = clone(payload.scores as Record<string, unknown>);
  scores.role = null;
  scores.overall_score = null;
  scores.coverage = 0.0;
  scores.dimensions = (
    scores.dimensions as Array<Record<string, unknown>>
  ).map((dimension) => ({
    ...dimension,
    configured_weight: 0,
    applied_weight: 0,
    coverage: 0,
  }));
  payload.scores = scores;
  const metrics = clone(payload.metrics as Array<Record<string, unknown>>);
  metrics[0] = {
    ...metrics[0],
    status: "unavailable",
    value: null,
    unit: null,
    comparisons: [],
    confidence: "low",
    unavailable_reason: "missing_match_value",
  };
  payload.metrics = metrics;
  return payload;
}

afterEach(() => vi.unstubAllGlobals());

describe("analysisResponseSchema", () => {
  it("parses completed and partial fixtures", () => {
    const completed = analysisResponseSchema.parse(completedAnalysis()) as AnalysisResponse;
    expect(completed.role).toBe("support");
    expect(completed.schema_version).toBe(1);
    expect(completed.scope_notice_code).toBe("DETERMINISTIC_DATA_COACHING_NO_AI");
    expect("selected_puuid" in completed).toBe(false);

    const partial = analysisResponseSchema.parse(partialAnalysis()) as AnalysisResponse;
    expect(partial.status).toBe("partial");
    expect(partial.role).toBeNull();
    expect(partial.scores.overall_score).toBeNull();
    expect(partial.locale).toBe("zh-CN");
  });

  it("rejects UTILITY and other unknown roles", () => {
    expect(analysisResponseSchema.safeParse(completedAnalysis({ role: "UTILITY" })).success).toBe(
      false,
    );
    expect(analysisResponseSchema.safeParse(completedAnalysis({ role: "utility" })).success).toBe(
      false,
    );
    const scores = clone(completedAnalysis().scores as Record<string, unknown>);
    scores.role = "UTILITY";
    expect(analysisResponseSchema.safeParse(completedAnalysis({ scores })).success).toBe(false);
  });

  it("rejects scores above 100", () => {
    const comparison = clone(completedAnalysis());
    (comparison.metrics as Array<Record<string, unknown>>)[0] = {
      ...((comparison.metrics as Array<Record<string, unknown>>)[0] as Record<string, unknown>),
      comparisons: [{ basis: "team_percentile", score: 100.01, opponent_value: null }],
    };
    expect(analysisResponseSchema.safeParse(comparison).success).toBe(false);

    const dimension = clone(completedAnalysis());
    const scores = clone(dimension.scores as Record<string, unknown>);
    const dimensions = clone(scores.dimensions as Array<Record<string, unknown>>);
    dimensions[0] = { ...dimensions[0], score: 100.01 };
    scores.dimensions = dimensions;
    dimension.scores = scores;
    expect(analysisResponseSchema.safeParse(dimension).success).toBe(false);

    expect(
      analysisResponseSchema.safeParse(
        completedAnalysis({
          scores: { ...(completedAnalysis().scores as object), overall_score: 100.01 },
        }),
      ).success,
    ).toBe(false);
  });

  it("rejects broken available and unavailable metric shapes", () => {
    const missingValue = clone(completedAnalysis());
    (missingValue.metrics as Array<Record<string, unknown>>)[0] = {
      ...((missingValue.metrics as Array<Record<string, unknown>>)[0] as Record<string, unknown>),
      value: null,
    };
    expect(analysisResponseSchema.safeParse(missingValue).success).toBe(false);

    const missingUnit = clone(completedAnalysis());
    (missingUnit.metrics as Array<Record<string, unknown>>)[0] = {
      ...((missingUnit.metrics as Array<Record<string, unknown>>)[0] as Record<string, unknown>),
      unit: null,
    };
    expect(analysisResponseSchema.safeParse(missingUnit).success).toBe(false);

    const unavailableWithValue = clone(partialAnalysis());
    (unavailableWithValue.metrics as Array<Record<string, unknown>>)[0] = {
      ...((unavailableWithValue.metrics as Array<Record<string, unknown>>)[0] as Record<
        string,
        unknown
      >),
      value: 1.2,
    };
    expect(analysisResponseSchema.safeParse(unavailableWithValue).success).toBe(false);
  });

  it("rejects duplicate comparison bases", () => {
    const payload = clone(completedAnalysis());
    (payload.metrics as Array<Record<string, unknown>>)[0] = {
      ...((payload.metrics as Array<Record<string, unknown>>)[0] as Record<string, unknown>),
      comparisons: [
        { basis: "team_percentile", score: 50.0, opponent_value: null },
        { basis: "team_percentile", score: 60.0, opponent_value: null },
      ],
    };
    expect(analysisResponseSchema.safeParse(payload).success).toBe(false);
  });

  it("rejects dimension counts other than the canonical five", () => {
    const tooFew = clone(completedAnalysis());
    const fewScores = clone(tooFew.scores as Record<string, unknown>);
    fewScores.dimensions = (fewScores.dimensions as unknown[]).slice(0, 4);
    tooFew.scores = fewScores;
    expect(analysisResponseSchema.safeParse(tooFew).success).toBe(false);

    const shuffled = clone(completedAnalysis());
    const shuffledScores = clone(shuffled.scores as Record<string, unknown>);
    const dims = clone(shuffledScores.dimensions as Array<Record<string, unknown>>);
    [dims[0], dims[1]] = [dims[1], dims[0]];
    shuffledScores.dimensions = dims;
    shuffled.scores = shuffledScores;
    expect(analysisResponseSchema.safeParse(shuffled).success).toBe(false);
  });

  it("rejects overall score when role is absent or coverage is below 0.60", () => {
    const noRole = clone(completedAnalysis({ role: null }));
    const noRoleScores = clone(noRole.scores as Record<string, unknown>);
    noRoleScores.role = null;
    noRole.scores = noRoleScores;
    expect(analysisResponseSchema.safeParse(noRole).success).toBe(false);

    const lowCoverage = clone(completedAnalysis());
    const lowScores = clone(lowCoverage.scores as Record<string, unknown>);
    lowScores.coverage = 0.5999;
    lowCoverage.scores = lowScores;
    expect(analysisResponseSchema.safeParse(lowCoverage).success).toBe(false);
  });

  it("rejects missing evidence references and more than three findings or goals", () => {
    const missing = clone(completedAnalysis());
    missing.findings = [
      {
        rule_id: "finding.vision.strength",
        kind: "strength",
        severity: "medium",
        message_code: "analysis.finding.vision.strength",
        params: { score: 80.0 },
        evidence_ids: ["missing"],
        confidence: "medium",
        requires_replay_interpretation: false,
      },
    ];
    expect(analysisResponseSchema.safeParse(missing).success).toBe(false);

    const missingDimension = clone(completedAnalysis());
    const missingDimensionScores = clone(missingDimension.scores as Record<string, unknown>);
    const missingDimensionItems = clone(
      missingDimensionScores.dimensions as Array<Record<string, unknown>>,
    );
    missingDimensionItems[0].evidence_ids = ["missing"];
    missingDimensionScores.dimensions = missingDimensionItems;
    missingDimension.scores = missingDimensionScores;
    expect(analysisResponseSchema.safeParse(missingDimension).success).toBe(false);

    const finding = (completedAnalysis().findings as unknown[])[0];
    const tooManyFindings = completedAnalysis({ findings: [finding, finding, finding, finding] });
    expect(analysisResponseSchema.safeParse(tooManyFindings).success).toBe(false);

    const goal = (completedAnalysis().goals as unknown[])[0];
    const tooManyGoals = completedAnalysis({ goals: [goal, goal, goal, goal] });
    expect(analysisResponseSchema.safeParse(tooManyGoals).success).toBe(false);
  });

  it("rejects role drift between the result, scores, and goals", () => {
    const scoreDrift = clone(completedAnalysis());
    const scores = clone(scoreDrift.scores as Record<string, unknown>);
    scores.role = "top";
    scoreDrift.scores = scores;
    expect(analysisResponseSchema.safeParse(scoreDrift).success).toBe(false);

    const goalDrift = clone(completedAnalysis());
    const goals = clone(goalDrift.goals as Array<Record<string, unknown>>);
    goals[0].role = "top";
    goalDrift.goals = goals;
    expect(analysisResponseSchema.safeParse(goalDrift).success).toBe(false);
  });

  it("rejects extra fields and wrong scope or version literals", () => {
    expect(
      analysisResponseSchema.safeParse(completedAnalysis({ selected_puuid: "secret" })).success,
    ).toBe(false);
    expect(analysisResponseSchema.safeParse(completedAnalysis({ schema_version: 2 })).success).toBe(
      false,
    );
    expect(
      analysisResponseSchema.safeParse(
        completedAnalysis({ scope_notice_code: "DATA_ONLY_NO_COACHING" }),
      ).success,
    ).toBe(false);
    expect(
      analysisResponseSchema.safeParse(completedAnalysis({ input_hash: "A".repeat(64) })).success,
    ).toBe(false);
    expect(
      analysisResponseSchema.safeParse(
        completedAnalysis({ metric_version: "deterministic-metrics-v2" }),
      ).success,
    ).toBe(false);
  });
});

describe("analysis API client", () => {
  it("POSTs createAnalysis with snake_case body fields", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(completedAnalysis()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await createAnalysis({ platform: "NA1", matchId: "NA1_1", puuid: "p1", locale: "zh-CN" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/analyses",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          platform: "NA1",
          match_id: "NA1_1",
          puuid: "p1",
          locale: "zh-CN",
        }),
      }),
    );
  });

  it("GETs analysis by id and locale", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(completedAnalysis({ cached: true })), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getAnalysis({ analysisId: ANALYSIS_ID, locale: "en-US" });

    expect(fetchMock).toHaveBeenCalledWith(
      `http://localhost:8000/api/v1/analyses/${ANALYSIS_ID}?locale=en-US`,
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("preserves AbortError on cancellation", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new DOMException("The operation was aborted.", "AbortError")),
    );

    await expect(
      createAnalysis({ platform: "NA1", matchId: "NA1_1", puuid: "p1", locale: "zh-CN" }),
    ).rejects.toMatchObject({ name: "AbortError" });
  });

  it("maps safe API errors to ApiClientError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "MATCH_ANALYSIS_UNSUPPORTED_MODE",
              message: "Match analysis is not supported for this game mode.",
              params: {},
              retryable: false,
              request_id: SAFE_REQUEST_ID,
            },
          }),
          { status: 422, headers: { "X-Request-ID": SAFE_REQUEST_ID } },
        ),
      ),
    );

    await expect(
      createAnalysis({ platform: "NA1", matchId: "NA1_1", puuid: "p1", locale: "en-US" }),
    ).rejects.toMatchObject({
      name: "ApiClientError",
      code: "MATCH_ANALYSIS_UNSUPPORTED_MODE",
      retryable: false,
      requestId: SAFE_REQUEST_ID,
    });
  });

  it("rejects malformed success as INVALID_API_RESPONSE", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ analysis_id: ANALYSIS_ID }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(
      getAnalysis({ analysisId: ANALYSIS_ID, locale: "en-US" }),
    ).rejects.toMatchObject({ code: "INVALID_API_RESPONSE" });
    await expect(
      getAnalysis({ analysisId: ANALYSIS_ID, locale: "en-US" }),
    ).rejects.toBeInstanceOf(ApiClientError);
  });

  it("accepts zh-CN and en-US responses for the same analysis id", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          new Response(JSON.stringify(completedAnalysis({ locale: "zh-CN", cached: true })), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        )
        .mockResolvedValueOnce(
          new Response(JSON.stringify(completedAnalysis({ locale: "en-US", cached: true })), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        ),
    );

    const zh = await getAnalysis({ analysisId: ANALYSIS_ID, locale: "zh-CN" });
    const en = await getAnalysis({ analysisId: ANALYSIS_ID, locale: "en-US" });
    expect(zh.analysis_id).toBe(ANALYSIS_ID);
    expect(en.analysis_id).toBe(ANALYSIS_ID);
    expect(zh.locale).toBe("zh-CN");
    expect(en.locale).toBe("en-US");
  });
});
