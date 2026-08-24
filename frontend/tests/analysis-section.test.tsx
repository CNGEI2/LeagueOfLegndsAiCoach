import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const { createAnalysisMock } = vi.hoisted(() => ({ createAnalysisMock: vi.fn() }));

vi.mock("@/api/client", () => ({
  createAnalysis: createAnalysisMock,
  ApiClientError: class ApiClientError extends Error {
    constructor(
      readonly code: string,
      readonly params: Record<string, unknown>,
      readonly retryable: boolean,
      readonly requestId: string | null,
    ) {
      super(code);
      this.name = "ApiClientError";
    }
  },
}));

import { ApiClientError } from "@/api/client";
import type { AnalysisResponse } from "@/api/schemas";
import { AnalysisSection } from "@/components/analysis-section";

const FACT_ID = "timeline:NA1:NA1_123456789:v1:frame:1:event:0";
const INPUT_HASH = "a".repeat(64);

function response(overrides: Partial<AnalysisResponse> = {}): AnalysisResponse {
  const evidenceIds = {
    economy: "metric:v1:cs_per_min",
    combat: "metric:v1:kda",
    survivability: "metric:v1:deaths_per_10",
    team_objectives: "metric:v1:explicit_objective_events",
    vision: "metric:v1:vision_per_min",
  } as const;
  const dimensions = [
    ["economy", 64],
    ["combat", 82],
    ["survivability", 58],
    ["team_objectives", 76],
    ["vision", 91],
  ] as const;
  return {
    analysis_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    status: "completed",
    cached: false,
    locale: "en-US",
    role: "support",
    metrics: [
      {
        evidence_id: evidenceIds.combat,
        metric_key: "kda",
        category: "combat",
        status: "available",
        value: 6,
        unit: "ratio",
        beneficial_direction: "higher",
        comparisons: [{ basis: "team_percentile", score: 75, opponent_value: null }],
        confidence: "high",
        source_type: "match",
        source_fact_ids: [],
        unavailable_reason: null,
        metric_version: "deterministic-metrics-v1",
      },
      {
        evidence_id: evidenceIds.team_objectives,
        metric_key: "explicit_objective_events",
        category: "team_objectives",
        status: "available",
        value: 2,
        unit: "count",
        beneficial_direction: "higher",
        comparisons: [{ basis: "team_percentile", score: 75, opponent_value: null }],
        confidence: "high",
        source_type: "timeline",
        source_fact_ids: [FACT_ID],
        unavailable_reason: null,
        metric_version: "deterministic-metrics-v1",
      },
      {
        evidence_id: evidenceIds.vision,
        metric_key: "vision_per_min",
        category: "vision",
        status: "available",
        value: 0.8,
        unit: "per_minute",
        beneficial_direction: "higher",
        comparisons: [{ basis: "same_role", score: 80, opponent_value: 0.6 }],
        confidence: "high",
        source_type: "match",
        source_fact_ids: [],
        unavailable_reason: null,
        metric_version: "deterministic-metrics-v1",
      },
    ],
    scores: {
      role: "support",
      dimensions: dimensions.map(([dimension, score]) => ({
        dimension,
        status: "available" as const,
        score,
        configured_weight: 20,
        applied_weight: 20,
        coverage: 1,
        evidence_ids: [evidenceIds[dimension]],
      })),
      overall_score: 78.5,
      coverage: 1,
      score_version: "deterministic-score-v1",
    },
    findings: [
      {
        rule_id: "finding.vision.strength",
        kind: "strength",
        severity: "medium",
        message_code: "analysis.finding.vision.strength",
        params: { score: 91, coverage: 1 },
        evidence_ids: [evidenceIds.vision],
        confidence: "medium",
        requires_replay_interpretation: false,
      },
      {
        rule_id: "finding.team_objectives.strength",
        kind: "strength",
        severity: "medium",
        message_code: "analysis.finding.team_objectives.strength",
        params: { score: 76, coverage: 1 },
        evidence_ids: [evidenceIds.team_objectives],
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
        evidence_ids: [evidenceIds.vision],
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
    request_id: "a3f4c1d2e5b67890a1b2c3d4e5f60718",
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function renderSection(
  props: Partial<{
    locale: "en-US" | "zh-CN";
    matchId: string;
    puuid: string;
    platform: "NA1" | "EUW1";
    onEvidenceFactRequest: (factId: string) => void;
  }> = {},
) {
  return render(
    <AnalysisSection
      locale={props.locale ?? "en-US"}
      matchId={props.matchId ?? "NA1_123456789"}
      puuid={props.puuid ?? "selected-puuid"}
      platform={props.platform ?? "NA1"}
      onEvidenceFactRequest={props.onEvidenceFactRequest ?? vi.fn()}
    />,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AnalysisSection", () => {
  it("stays idle until requested, announces loading, and renders the completed report", async () => {
    const pending = deferred<AnalysisResponse>();
    createAnalysisMock.mockReturnValue(pending.promise);
    const user = userEvent.setup();
    const { container } = renderSection();

    expect(createAnalysisMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Generate data review" }));
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
    expect(screen.getByRole("status")).toHaveTextContent("Generating data review");

    pending.resolve(response());
    expect(await screen.findByText("78.5")).toBeVisible();
    expect(screen.getByTestId("analysis-role")).toHaveTextContent("Support");
    expect(screen.getAllByTestId("analysis-dimension")).toHaveLength(5);
    expect(screen.getByText("Vision score per minute")).toBeVisible();
    expect(screen.getByText("Objective events")).toBeVisible();
    expect(screen.getByText(/deterministic match data/i)).toBeVisible();
    expect(screen.getByText(/not a Riot score, rank, MMR, or ELO/i)).toBeVisible();
    expect(container).not.toHaveTextContent(/Utility|win caused|loss caused/i);
  });

  it("renders cached partial data and never turns unavailable into zero", async () => {
    const partial = response({ status: "partial", cached: true });
    partial.scores.dimensions[4] = {
      ...partial.scores.dimensions[4],
      status: "unavailable",
      score: null,
      applied_weight: 0,
      coverage: 0,
    };
    createAnalysisMock.mockResolvedValue(partial);
    const user = userEvent.setup();
    renderSection();

    await user.click(screen.getByRole("button", { name: "Generate data review" }));
    expect(await screen.findByText("Cached result")).toBeVisible();
    expect(screen.getByText("Partial data")).toBeVisible();
    const vision = screen.getByTestId("analysis-dimension-vision");
    expect(vision).toHaveTextContent("Unavailable");
    expect(vision).not.toHaveTextContent(/\b0(?:\.0)?\b/);
  });

  it("labels a missing role and overall score as unavailable", async () => {
    const missing = response({ role: null, findings: [], goals: [] });
    missing.scores = {
      ...missing.scores,
      role: null,
      overall_score: null,
      coverage: 0.4,
    };
    createAnalysisMock.mockResolvedValue(missing);
    const user = userEvent.setup();
    renderSection();

    await user.click(screen.getByRole("button", { name: "Generate data review" }));
    expect(await screen.findByText("Overall score unavailable")).toBeVisible();
    expect(screen.getByTestId("analysis-role")).toHaveTextContent("Role unavailable");
    expect(screen.queryByTestId("analysis-overall-score")).not.toBeInTheDocument();
  });

  it("retries a retryable safe error and does not expose raw backend values", async () => {
    createAnalysisMock
      .mockRejectedValueOnce(
        new ApiClientError(
          "RIOT_RATE_LIMITED",
          { retry_after_seconds: 5, secret: "do-not-render" },
          true,
          null,
        ),
      )
      .mockResolvedValueOnce(response());
    const user = userEvent.setup();
    renderSection();

    await user.click(screen.getByRole("button", { name: "Generate data review" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Try again in 5 seconds");
    expect(alert).not.toHaveTextContent("do-not-render");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("78.5")).toBeVisible();
    expect(createAnalysisMock).toHaveBeenCalledTimes(2);
  });

  it("does not offer retry for an unsupported match", async () => {
    createAnalysisMock.mockRejectedValue(
      new ApiClientError("MATCH_ANALYSIS_UNSUPPORTED_MODE", {}, false, null),
    );
    const user = userEvent.setup();
    renderSection();

    await user.click(screen.getByRole("button", { name: "Generate data review" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Data review is not supported for this match mode.",
    );
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("aborts on locale change and suppresses the stale response", async () => {
    const first = deferred<AnalysisResponse>();
    let firstSignal: AbortSignal | undefined;
    createAnalysisMock
      .mockImplementationOnce((_input: unknown, signal?: AbortSignal) => {
        firstSignal = signal;
        return first.promise;
      })
      .mockResolvedValueOnce(response({ locale: "zh-CN", role: "support" }));
    const user = userEvent.setup();
    const view = renderSection();

    await user.click(screen.getByRole("button", { name: "Generate data review" }));
    view.rerender(
      <AnalysisSection
        locale="zh-CN"
        matchId="NA1_123456789"
        puuid="selected-puuid"
        platform="NA1"
        onEvidenceFactRequest={vi.fn()}
      />,
    );
    await waitFor(() => expect(firstSignal?.aborted).toBe(true));
    await user.click(screen.getByRole("button", { name: "生成数据复盘" }));
    expect(await screen.findByTestId("analysis-role")).toHaveTextContent("辅助");
    first.resolve(response({ role: "top" }));
    await waitFor(() => expect(screen.queryByText("Top")).not.toBeInTheDocument());
  });

  it("falls back safely for unknown finding and goal message codes", async () => {
    const unknown = response();
    unknown.findings[0] = {
      ...unknown.findings[0],
      message_code: "analysis.finding.future.raw_code",
      params: { secret: "raw-param" },
    };
    unknown.goals[0] = {
      ...unknown.goals[0],
      message_code: "analysis.goal.future.raw_code",
    };
    createAnalysisMock.mockResolvedValue(unknown);
    const user = userEvent.setup();
    const { container } = renderSection();

    await user.click(screen.getByRole("button", { name: "Generate data review" }));
    expect(await screen.findAllByText("Structured detail unavailable")).toHaveLength(2);
    expect(container).not.toHaveTextContent("future.raw_code");
    expect(container).not.toHaveTextContent("raw-param");
  });

  it("navigates only Timeline-backed supporting metrics and caps rendered cards", async () => {
    const onEvidenceFactRequest = vi.fn();
    const capped = response();
    capped.findings = [
      ...capped.findings,
      { ...capped.findings[0], rule_id: "finding.vision.strength.3" },
      { ...capped.findings[0], rule_id: "finding.vision.strength.4" },
    ];
    capped.goals = [
      ...capped.goals,
      { ...capped.goals[0], rule_id: "goal.support.vision_per_min.2" },
      { ...capped.goals[0], rule_id: "goal.support.vision_per_min.3" },
      { ...capped.goals[0], rule_id: "goal.support.vision_per_min.4" },
    ];
    createAnalysisMock.mockResolvedValue(capped);
    const user = userEvent.setup();
    renderSection({ onEvidenceFactRequest });

    await user.click(screen.getByRole("button", { name: "Generate data review" }));
    const report = await screen.findByTestId("analysis-report");
    expect(within(report).getAllByTestId("analysis-finding")).toHaveLength(3);
    expect(within(report).getAllByTestId("analysis-goal")).toHaveLength(3);
    const evidenceButtons = within(report).getAllByRole("button", {
      name: "Open timeline evidence",
    });
    expect(evidenceButtons).toHaveLength(1);
    await user.click(evidenceButtons[0]);
    expect(onEvidenceFactRequest).toHaveBeenCalledWith(FACT_ID);
  });
});
