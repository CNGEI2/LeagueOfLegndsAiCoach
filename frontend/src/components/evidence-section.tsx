"use client";

import { useEffect, useRef, useState } from "react";

import {
  ApiClientError,
  getReplayArtifacts,
  prepareMatchEvidence,
} from "@/api/client";
import type {
  JointEvidenceResponse,
  Platform,
  ReplayArtifact,
  TimelineFact,
} from "@/api/schemas";
import { formatGameTime, ReplayArtifactGallery } from "@/components/replay-artifact-gallery";
import type { Locale } from "@/i18n/locales";
import { getMessages, type Messages } from "@/i18n/messages";
import {
  findReplayCapabilityForMatch,
  removeReplayCapability,
  type ReplayCapability,
} from "@/replays/storage";

function fill(template: string, values: Record<string, string>) {
  return template.replace(/\{(\w+)\}/g, (_, key: string) => values[key] ?? "");
}

function factKindLabel(kind: TimelineFact["kind"], messages: Messages): string {
  switch (kind) {
    case "champion_kill":
      return messages.factKindChampionKill;
    case "elite_monster_kill":
      return messages.factKindEliteMonsterKill;
    case "building_kill":
      return messages.factKindBuildingKill;
    case "item_purchased":
      return messages.factKindItemPurchased;
    case "item_sold":
      return messages.factKindItemSold;
    case "item_destroyed":
      return messages.factKindItemDestroyed;
    case "item_undo":
      return messages.factKindItemUndo;
    case "participant_state":
      return messages.factKindParticipantState;
  }
}

function relationshipLabel(
  relationship: TimelineFact["relationship"],
  messages: Messages,
): string {
  switch (relationship) {
    case "killer":
      return messages.relationshipKiller;
    case "victim":
      return messages.relationshipVictim;
    case "assistant":
      return messages.relationshipAssistant;
    case "actor":
      return messages.relationshipActor;
    case "team_context":
      return messages.relationshipTeamContext;
    case "not_involved":
      return messages.relationshipNotInvolved;
  }
}

function categoryLabel(
  category: JointEvidenceResponse["windows"][number]["categories"][number],
  messages: Messages,
): string {
  switch (category) {
    case "combat_context":
      return messages.categoryCombatContext;
    case "death_context":
      return messages.categoryDeathContext;
    case "objective_context":
      return messages.categoryObjectiveContext;
    case "building_context":
      return messages.categoryBuildingContext;
  }
}

function coverageLabel(
  coverage: JointEvidenceResponse["windows"][number]["coverage"],
  messages: Messages,
): string {
  switch (coverage) {
    case "full":
      return messages.coverageFull;
    case "partial":
      return messages.coveragePartial;
    case "unavailable":
      return messages.coverageUnavailable;
  }
}

function messageForEvidenceError(
  code: string | undefined,
  params: Record<string, unknown> | undefined,
  messages: Messages,
): string {
  switch (code) {
    case "MATCH_EVIDENCE_UNSUPPORTED_MODE":
      return messages.matchEvidenceUnsupportedMode;
    case "MATCH_TIMELINE_NOT_FOUND":
      return messages.matchTimelineNotFound;
    case "REPLAY_EVIDENCE_NOT_READY":
      return messages.replayEvidenceNotReady;
    case "REPLAY_NOT_FOUND":
      return messages.replayNotFound;
    case "MATCH_NOT_FOUND":
      return messages.matchNotFound;
    case "PLAYER_NOT_IN_MATCH":
      return messages.playerNotInMatch;
    case "RIOT_AUTH_FAILED":
      return messages.riotAuthFailed;
    case "RIOT_RATE_LIMITED": {
      const seconds = params?.retry_after_seconds;
      if (typeof seconds === "number" && Number.isFinite(seconds) && seconds >= 0) {
        return fill(messages.riotRateLimited, { seconds: String(seconds) });
      }
      return messages.rateLimitedWithoutDelay;
    }
    case "RIOT_UNAVAILABLE":
      return messages.riotUnavailable;
    case "RIOT_INVALID_RESPONSE":
    case "RIOT_REQUEST_INVALID":
      return messages.riotRequestInvalid;
    case "INVALID_API_RESPONSE":
      return messages.invalidApiResponse;
    case "NETWORK_ERROR":
      return messages.riotUnavailable;
    default:
      return messages.invalidApiResponse;
  }
}

type EvidenceState =
  | { status: "idle" }
  | { status: "loading" }
  | {
      status: "ready";
      evidence: JointEvidenceResponse;
      linkedArtifacts: ReplayArtifact[];
      accessToken: string | null;
      replayId: string | null;
    }
  | {
      status: "error";
      code: string;
      params: Record<string, unknown>;
      retryable: boolean;
    };

export function EvidenceSection({
  matchId,
  puuid,
  platform,
  locale,
}: {
  matchId: string;
  puuid: string;
  platform: Platform;
  locale: Locale;
}) {
  const messages = getMessages(locale);
  const [state, setState] = useState<EvidenceState>({ status: "idle" });
  const abortRef = useRef<AbortController | null>(null);
  const propsKey = `${matchId}:${platform}:${puuid}:${locale}`;

  useEffect(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    // Reset to idle when the match/locale/platform/puuid identity changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional prop-driven reset
    setState({ status: "idle" });
  }, [propsKey]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  async function prepareWithOptionalReplay(
    capability: ReplayCapability | null,
    signal: AbortSignal,
    allowStaleReplayRetry: boolean,
  ): Promise<JointEvidenceResponse> {
    const input = {
      matchId,
      puuid,
      platform,
      locale,
      ...(capability
        ? { replay: { replayId: capability.replayId, accessToken: capability.accessToken } }
        : {}),
    };

    try {
      return await prepareMatchEvidence(input, signal);
    } catch (error) {
      if (
        allowStaleReplayRetry &&
        capability &&
        error instanceof ApiClientError &&
        error.code === "REPLAY_NOT_FOUND"
      ) {
        removeReplayCapability(capability.replayId);
        return prepareMatchEvidence(
          {
            matchId,
            puuid,
            platform,
            locale,
          },
          signal,
        );
      }
      throw error;
    }
  }

  async function runPrepare() {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ status: "loading" });

    const capability = findReplayCapabilityForMatch(matchId, "ready");

    try {
      const evidence = await prepareWithOptionalReplay(capability, controller.signal, true);
      if (controller.signal.aborted) return;

      let linkedArtifacts: ReplayArtifact[] = [];
      let accessToken: string | null = null;
      let replayId: string | null = null;

      if (evidence.replay_link && capability) {
        accessToken = capability.accessToken;
        replayId = capability.replayId;
        const manifest = await getReplayArtifacts(
          { replayId: capability.replayId, accessToken: capability.accessToken },
          controller.signal,
        );
        if (controller.signal.aborted) return;
        const referencedIds = new Set(
          evidence.windows.flatMap((window) =>
            window.artifacts.map((artifact) => artifact.artifact_id),
          ),
        );
        linkedArtifacts = manifest.artifacts.filter((artifact) =>
          referencedIds.has(artifact.artifact_id),
        );
      }

      setState({
        status: "ready",
        evidence,
        linkedArtifacts,
        accessToken,
        replayId,
      });
    } catch (error) {
      if (controller.signal.aborted) return;
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
      setState({
        status: "error",
        code: "NETWORK_ERROR",
        params: {},
        retryable: true,
      });
    }
  }

  function refreshLinkedArtifacts() {
    if (state.status !== "ready" || !state.accessToken || !state.replayId) return;
    const { accessToken, replayId, evidence } = state;
    const controller = new AbortController();
    void getReplayArtifacts({ replayId, accessToken }, controller.signal)
      .then((manifest) => {
        if (controller.signal.aborted) return;
        const referencedIds = new Set(
          evidence.windows.flatMap((window) =>
            window.artifacts.map((artifact) => artifact.artifact_id),
          ),
        );
        setState((previous) => {
          if (previous.status !== "ready") return previous;
          return {
            ...previous,
            linkedArtifacts: manifest.artifacts.filter((artifact) =>
              referencedIds.has(artifact.artifact_id),
            ),
          };
        });
      })
      .catch(() => undefined);
  }

  return (
    <section className="evidence-section" aria-labelledby="evidence-section-title">
      <header className="evidence-section-header">
        <h2 id="evidence-section-title">{messages.prepareEvidence}</h2>
      </header>

      {state.status === "idle" ? (
        <button type="button" className="evidence-prepare-button" onClick={() => void runPrepare()}>
          {messages.prepareEvidence}
        </button>
      ) : null}

      {state.status === "loading" ? (
        <p className="evidence-status" role="status" aria-live="polite">
          {messages.preparingEvidence}
        </p>
      ) : null}

      {state.status === "error" ? (
        <div className="evidence-alert" role="alert">
          <p>{messageForEvidenceError(state.code, state.params, messages)}</p>
          {state.retryable ? (
            <button type="button" onClick={() => void runPrepare()}>
              {messages.retry}
            </button>
          ) : null}
        </div>
      ) : null}

      {state.status === "ready" ? (
        <EvidenceReadyView
          evidence={state.evidence}
          linkedArtifacts={state.linkedArtifacts}
          accessToken={state.accessToken}
          messages={messages}
          onRefreshManifest={refreshLinkedArtifacts}
        />
      ) : null}
    </section>
  );
}

function EvidenceReadyView({
  evidence,
  linkedArtifacts,
  accessToken,
  messages,
  onRefreshManifest,
}: {
  evidence: JointEvidenceResponse;
  linkedArtifacts: ReplayArtifact[];
  accessToken: string | null;
  messages: Messages;
  onRefreshManifest: () => void;
}) {
  const isEmpty = evidence.facts.length === 0 && evidence.windows.length === 0;
  const linked = evidence.replay_link !== null;

  return (
    <div className="evidence-ready">
      <p className="evidence-scope-notice" role="note">
        {messages.evidenceOnlyScopeNotice}
      </p>
      <p className="evidence-link-notice">
        {linked ? messages.evidenceLinkedFrames : messages.evidenceTimelineOnly}
      </p>

      {isEmpty ? <p className="evidence-empty">{messages.evidenceEmpty}</p> : null}

      {!isEmpty && evidence.facts.length > 0 ? (
        <ul className="evidence-fact-list">
          {evidence.facts.map((fact) => (
            <li key={fact.fact_id} className="evidence-fact">
              <span className="evidence-fact-kind">{factKindLabel(fact.kind, messages)}</span>
              <span className="evidence-fact-relationship">
                {relationshipLabel(fact.relationship, messages)}
              </span>
              <span className="evidence-fact-time">{formatGameTime(fact.timestamp_ms)}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {!isEmpty && evidence.windows.length > 0 ? (
        <ul className="evidence-window-list">
          {evidence.windows.map((window) => (
            <li key={window.window_id} className="evidence-window">
              <div className="evidence-window-meta">
                <p className="evidence-window-interval">
                  {fill(messages.evidenceGameInterval, {
                    start: formatGameTime(window.start_ms),
                    end: formatGameTime(window.end_ms),
                  })}
                </p>
                <p className="evidence-window-coverage">{coverageLabel(window.coverage, messages)}</p>
                <p className="evidence-window-triggers">
                  {fill(messages.evidenceTriggerCount, {
                    count: String(window.trigger_fact_ids.length),
                  })}
                </p>
              </div>
              <ul className="evidence-window-categories">
                {window.categories.map((category) => (
                  <li key={`${window.window_id}:${category}`}>
                    {categoryLabel(category, messages)}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      ) : null}

      {linked && accessToken && linkedArtifacts.length > 0 ? (
        <ReplayArtifactGallery
          artifacts={linkedArtifacts}
          accessToken={accessToken}
          messages={messages}
          onRefreshManifest={onRefreshManifest}
        />
      ) : null}
    </div>
  );
}
