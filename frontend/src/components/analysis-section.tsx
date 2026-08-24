"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiClientError, createAnalysis } from "@/api/client";
import type {
  AnalysisFinding,
  AnalysisGoal,
  AnalysisMetric,
  AnalysisResponse,
  AnalysisRole,
  DimensionScore,
  Platform,
} from "@/api/schemas";
import type { Locale } from "@/i18n/locales";
import { getMessages, type Messages } from "@/i18n/messages";

type AnalysisState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; analysis: AnalysisResponse }
  | {
      status: "error";
      code: string;
      params: Record<string, unknown>;
      retryable: boolean;
    };

function fill(template: string, values: Record<string, string>): string {
  return template.replace(/\{(\w+)\}/g, (_, key: string) => values[key] ?? "");
}

function formatNumber(locale: Locale, value: number): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value);
}

function formatPercent(locale: Locale, value: number): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(value * 100);
}

function dimensionLabel(dimension: DimensionScore["dimension"], messages: Messages): string {
  switch (dimension) {
    case "economy":
      return messages.analysisDimensionEconomy;
    case "combat":
      return messages.analysisDimensionCombat;
    case "survivability":
      return messages.analysisDimensionSurvivability;
    case "team_objectives":
      return messages.analysisDimensionTeamObjectives;
    case "vision":
      return messages.analysisDimensionVision;
  }
}

function roleLabel(role: AnalysisRole, messages: Messages): string {
  switch (role) {
    case "top":
      return messages.analysisRoleTop;
    case "jungle":
      return messages.analysisRoleJungle;
    case "mid":
      return messages.analysisRoleMid;
    case "bottom":
      return messages.analysisRoleBottom;
    case "support":
      return messages.analysisRoleSupport;
  }
}

function metricLabel(metricKey: string, messages: Messages): string {
  switch (metricKey) {
    case "kda":
      return messages.analysisMetricKda;
    case "cs_per_min":
      return messages.analysisMetricCsPerMinute;
    case "gold_per_min":
      return messages.analysisMetricGoldPerMinute;
    case "damage_per_min":
      return messages.analysisMetricDamagePerMinute;
    case "kill_participation":
      return messages.analysisMetricKillParticipation;
    case "deaths_per_10":
      return messages.analysisMetricDeathsPer10;
    case "vision_per_min":
      return messages.analysisMetricVisionPerMinute;
    case "explicit_objective_events":
      return messages.analysisMetricObjectiveEvents;
    default:
      return messages.analysisMessageUnavailable;
  }
}

function metricValue(metric: AnalysisMetric, locale: Locale, messages: Messages): string {
  if (metric.status === "unavailable" || metric.value === null) {
    return messages.analysisUnavailable;
  }
  if (metric.metric_key === "kill_participation") {
    return `${formatPercent(locale, metric.value)}%`;
  }
  return formatNumber(locale, metric.value);
}

function safeFindingValues(
  finding: AnalysisFinding,
  locale: Locale,
): { score: string; coverage: string } | null {
  const score = finding.params.score;
  const coverage = finding.params.coverage;
  if (
    typeof score !== "number" ||
    !Number.isFinite(score) ||
    score < 0 ||
    score > 100 ||
    typeof coverage !== "number" ||
    !Number.isFinite(coverage) ||
    coverage < 0 ||
    coverage > 1
  ) {
    return null;
  }
  return { score: formatNumber(locale, score), coverage: formatPercent(locale, coverage) };
}

function findingMessage(
  finding: AnalysisFinding,
  locale: Locale,
  messages: Messages,
): string {
  const values = safeFindingValues(finding, locale);
  if (!values) return messages.analysisMessageUnavailable;
  let template: string;
  switch (finding.message_code) {
    case "analysis.finding.economy.strength":
      template = messages.analysisFindingEconomyStrength;
      break;
    case "analysis.finding.economy.improvement":
      template = messages.analysisFindingEconomyImprovement;
      break;
    case "analysis.finding.combat.strength":
      template = messages.analysisFindingCombatStrength;
      break;
    case "analysis.finding.combat.improvement":
      template = messages.analysisFindingCombatImprovement;
      break;
    case "analysis.finding.survivability.strength":
      template = messages.analysisFindingSurvivabilityStrength;
      break;
    case "analysis.finding.survivability.improvement":
      template = messages.analysisFindingSurvivabilityImprovement;
      break;
    case "analysis.finding.team_objectives.strength":
      template = messages.analysisFindingTeamObjectivesStrength;
      break;
    case "analysis.finding.team_objectives.improvement":
      template = messages.analysisFindingTeamObjectivesImprovement;
      break;
    case "analysis.finding.vision.strength":
      template = messages.analysisFindingVisionStrength;
      break;
    case "analysis.finding.vision.improvement":
      template = messages.analysisFindingVisionImprovement;
      break;
    default:
      return messages.analysisMessageUnavailable;
  }
  return fill(template, values);
}

function goalValue(goal: AnalysisGoal, value: number, locale: Locale): string {
  if (goal.message_code === "analysis.goal.kill_participation") {
    return `${formatPercent(locale, value)}%`;
  }
  return formatNumber(locale, value);
}

function goalMessage(goal: AnalysisGoal, locale: Locale, messages: Messages): string {
  if (!Number.isFinite(goal.current_value) || !Number.isFinite(goal.target_value)) {
    return messages.analysisMessageUnavailable;
  }
  let template: string;
  switch (goal.message_code) {
    case "analysis.goal.cs_per_min":
      template = messages.analysisGoalCsPerMinute;
      break;
    case "analysis.goal.deaths_per_10":
      template = messages.analysisGoalDeathsPer10;
      break;
    case "analysis.goal.damage_per_min":
      template = messages.analysisGoalDamagePerMinute;
      break;
    case "analysis.goal.kill_participation":
      template = messages.analysisGoalKillParticipation;
      break;
    case "analysis.goal.vision_per_min":
      template = messages.analysisGoalVisionPerMinute;
      break;
    default:
      return messages.analysisMessageUnavailable;
  }
  return fill(template, {
    current: goalValue(goal, goal.current_value, locale),
    target: goalValue(goal, goal.target_value, locale),
  });
}

function errorMessage(
  code: string,
  params: Record<string, unknown>,
  messages: Messages,
): string {
  switch (code) {
    case "MATCH_ANALYSIS_UNSUPPORTED_MODE":
      return messages.analysisErrorUnsupported;
    case "MATCH_NOT_FOUND":
    case "NOT_FOUND":
      return messages.analysisErrorNotFound;
    case "PLAYER_NOT_IN_MATCH":
      return messages.analysisErrorPlayerNotInMatch;
    case "VALIDATION_ERROR":
      return messages.analysisErrorValidation;
    case "RIOT_AUTH_FAILED":
      return messages.analysisErrorAuth;
    case "RIOT_RATE_LIMITED": {
      const seconds = params.retry_after_seconds;
      if (typeof seconds === "number" && Number.isFinite(seconds) && seconds >= 0) {
        return fill(messages.analysisErrorRateLimited, { seconds: String(Math.ceil(seconds)) });
      }
      return messages.analysisErrorRateLimitedNoDelay;
    }
    case "RIOT_UNAVAILABLE":
    case "NETWORK_ERROR":
      return messages.analysisErrorUnavailable;
    case "RIOT_INVALID_RESPONSE":
    case "RIOT_REQUEST_INVALID":
    case "INVALID_API_RESPONSE":
      return messages.analysisErrorInvalidResponse;
    default:
      return messages.analysisErrorGeneric;
  }
}

function dimensionAvailability(dimension: DimensionScore, messages: Messages): string {
  if (dimension.status === "unavailable") return messages.analysisUnavailable;
  if (dimension.coverage < 1) return messages.analysisPartiallyAvailable;
  return messages.analysisAvailable;
}

function timelineFactIds(
  evidenceIds: string[],
  metrics: AnalysisMetric[],
): string[] {
  const referencedEvidence = new Set(evidenceIds);
  return [
    ...new Set(
      metrics
        .filter((metric) => referencedEvidence.has(metric.evidence_id))
        .flatMap((metric) => metric.source_fact_ids),
    ),
  ];
}

function EvidenceActions({
  context,
  factIds,
  messages,
  onEvidenceFactRequest,
}: {
  context: string;
  factIds: string[];
  messages: Messages;
  onEvidenceFactRequest: (factId: string) => void;
}) {
  if (factIds.length === 0) return null;
  return (
    <div className="analysis-evidence-actions">
      {factIds.map((factId, index) => {
        const ordinal = factIds.length > 1 ? ` (${index + 1}/${factIds.length})` : "";
        return (
          <button
            key={factId}
            type="button"
            aria-label={`${messages.analysisEvidence}: ${context}${ordinal}`}
            onClick={() => onEvidenceFactRequest(factId)}
          >
            {messages.analysisEvidence}
          </button>
        );
      })}
    </div>
  );
}

export function AnalysisSection({
  locale,
  matchId,
  puuid,
  platform,
  onEvidenceFactRequest,
}: {
  locale: Locale;
  matchId: string;
  puuid: string;
  platform: Platform;
  onEvidenceFactRequest: (factId: string) => void;
}) {
  const messages = getMessages(locale);
  const [state, setState] = useState<AnalysisState>({ status: "idle" });
  const abortRef = useRef<AbortController | null>(null);
  const requestKeyRef = useRef(0);
  const identityKey = `${locale}:${platform}:${puuid}:${matchId}`;

  const runAnalysis = useCallback(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const requestKey = requestKeyRef.current + 1;
    requestKeyRef.current = requestKey;
    setState({ status: "loading" });
    void createAnalysis({ locale, matchId, puuid, platform }, controller.signal)
      .then((analysis) => {
        if (controller.signal.aborted || requestKey !== requestKeyRef.current) return;
        setState({ status: "ready", analysis });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || requestKey !== requestKeyRef.current) return;
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (error instanceof ApiClientError) {
          setState({
            status: "error",
            code: error.code,
            params: error.params,
            retryable: error.retryable,
          });
          return;
        }
        setState({ status: "error", code: "NETWORK_ERROR", params: {}, retryable: true });
      });
  }, [locale, matchId, platform, puuid]);

  useEffect(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    requestKeyRef.current += 1;
    // Reset the on-demand report when its match identity or language changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional prop-driven reset
    setState({ status: "idle" });
  }, [identityKey]);

  useEffect(
    () => () => {
      abortRef.current?.abort();
      requestKeyRef.current += 1;
    },
    [],
  );

  return (
    <section className="analysis-section" aria-labelledby="analysis-section-title">
      <header className="analysis-section-header">
        <div>
          <p className="analysis-eyebrow">{messages.analysisEyebrow}</p>
          <h2 id="analysis-section-title">{messages.analysisTitle}</h2>
        </div>
        {state.status === "ready" ? (
          <div className="analysis-statuses" aria-label={messages.analysisTitle}>
            <span>{state.analysis.status === "partial" ? messages.analysisPartial : messages.analysisCompleted}</span>
            {state.analysis.cached ? <span>{messages.analysisCached}</span> : null}
          </div>
        ) : null}
      </header>

      {state.status === "idle" ? (
        <button type="button" className="analysis-generate" onClick={runAnalysis}>
          {messages.analysisGenerate}
        </button>
      ) : null}

      {state.status === "loading" ? (
        <p className="analysis-loading" role="status" aria-live="polite">
          {messages.analysisGenerating}
        </p>
      ) : null}

      {state.status === "error" ? (
        <div className="analysis-alert" role="alert">
          <p>{errorMessage(state.code, state.params, messages)}</p>
          {state.retryable ? (
            <button type="button" onClick={runAnalysis}>
              {messages.retry}
            </button>
          ) : null}
        </div>
      ) : null}

      {state.status === "ready" ? (
        <AnalysisReport
          analysis={state.analysis}
          locale={locale}
          messages={messages}
          onEvidenceFactRequest={onEvidenceFactRequest}
        />
      ) : null}
    </section>
  );
}

function AnalysisReport({
  analysis,
  locale,
  messages,
  onEvidenceFactRequest,
}: {
  analysis: AnalysisResponse;
  locale: Locale;
  messages: Messages;
  onEvidenceFactRequest: (factId: string) => void;
}) {
  return (
    <div className="analysis-report" data-testid="analysis-report">
      <div className="analysis-scoreboard">
        <div className="analysis-overall">
          <span>{messages.analysisOverall}</span>
          {analysis.scores.overall_score === null ? (
            <strong>{messages.analysisOverallUnavailable}</strong>
          ) : (
            <strong data-testid="analysis-overall-score">
              {formatNumber(locale, analysis.scores.overall_score)}
            </strong>
          )}
          <small>
            {fill(messages.analysisCoverage, {
              coverage: formatPercent(locale, analysis.scores.coverage),
            })}
          </small>
        </div>
        <div className="analysis-role" data-testid="analysis-role">
          {analysis.role === null
            ? messages.analysisRoleUnavailable
            : fill(messages.analysisRole, { role: roleLabel(analysis.role, messages) })}
        </div>
      </div>

      <ul className="analysis-dimension-grid" aria-label={messages.analysisOverall}>
        {analysis.scores.dimensions.map((dimension) => (
          <li
            key={dimension.dimension}
            className={`analysis-dimension analysis-dimension-${dimension.status}`}
            data-testid={`analysis-dimension-${dimension.dimension}`}
          >
            <span>{dimensionLabel(dimension.dimension, messages)}</span>
            {dimension.score === null ? (
              <strong data-testid="analysis-dimension">{messages.analysisUnavailable}</strong>
            ) : (
              <strong data-testid="analysis-dimension">
                {formatNumber(locale, dimension.score)} / 100
              </strong>
            )}
            <small>{dimensionAvailability(dimension, messages)}</small>
          </li>
        ))}
      </ul>

      <div className="analysis-detail-grid">
        <section aria-labelledby="analysis-findings-title">
          <h3 id="analysis-findings-title">{messages.analysisFindings}</h3>
          {analysis.findings.length === 0 ? (
            <p className="analysis-empty">{messages.analysisNoFindings}</p>
          ) : (
            <ul className="analysis-card-list">
              {analysis.findings.slice(0, 3).map((finding) => {
                const message = findingMessage(finding, locale, messages);
                return (
                  <li
                    key={finding.rule_id}
                    className={`analysis-card analysis-card-${finding.kind}`}
                    data-testid="analysis-finding"
                  >
                    <p>{message}</p>
                    <EvidenceActions
                      context={message}
                      factIds={timelineFactIds(finding.evidence_ids, analysis.metrics)}
                      messages={messages}
                      onEvidenceFactRequest={onEvidenceFactRequest}
                    />
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section aria-labelledby="analysis-goals-title">
          <h3 id="analysis-goals-title">{messages.analysisGoals}</h3>
          {analysis.goals.length === 0 ? (
            <p className="analysis-empty">{messages.analysisNoGoals}</p>
          ) : (
            <ul className="analysis-card-list">
              {analysis.goals.slice(0, 3).map((goal) => {
                const message = goalMessage(goal, locale, messages);
                return (
                  <li
                    key={goal.rule_id}
                    className="analysis-card analysis-card-goal"
                    data-testid="analysis-goal"
                  >
                    <p>{message}</p>
                    <EvidenceActions
                      context={message}
                      factIds={timelineFactIds(goal.evidence_ids, analysis.metrics)}
                      messages={messages}
                      onEvidenceFactRequest={onEvidenceFactRequest}
                    />
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>

      <section className="analysis-metrics" aria-labelledby="analysis-metrics-title">
        <h3 id="analysis-metrics-title">{messages.analysisMetrics}</h3>
        <ul>
          {analysis.metrics.map((metric) => (
            <li key={metric.evidence_id}>
              <span>{metricLabel(metric.metric_key, messages)}</span>
              <strong>{metricValue(metric, locale, messages)}</strong>
            </li>
          ))}
        </ul>
      </section>

      <div className="analysis-boundaries">
        <p role="note">{messages.analysisDeterministicNotice}</p>
        <p role="note">{messages.analysisNotRiotScore}</p>
      </div>
    </div>
  );
}
