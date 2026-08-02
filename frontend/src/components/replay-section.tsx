"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiClientError,
  completeReplay,
  createReplay,
  deleteReplay,
  getReplayArtifacts,
  getReplayStatus,
  retryReplay,
  uploadReplayContent,
} from "@/api/client";
import type { Platform, ReplayArtifact, ReplayStatusResponse } from "@/api/schemas";
import { ReplayArtifactGallery } from "@/components/replay-artifact-gallery";
import { ReplayStatusPanel } from "@/components/replay-status-panel";
import { ReplayUploadForm, type ReplayUploadSubmit } from "@/components/replay-upload-form";
import type { Locale } from "@/i18n/locales";
import { getMessages, type Messages } from "@/i18n/messages";
import {
  loadReplayCapability,
  removeReplayCapability,
  saveReplayCapability,
  type ReplayCapability,
} from "@/replays/storage";

const RIGHTS_STATEMENT_VERSION = "2026-08-01";
const STORAGE_KEY_PREFIX = "lol-ai-coach:replay:";
const ACTIVE_POLL_MS = 2000;
const HIDDEN_POLL_MS = 10000;
const BACKOFF_BASE_MS = 2000;
const BACKOFF_MAX_MS = 30000;

const TERMINAL_STATUSES = new Set(["ready", "failed", "deleted", "expired"]);

// Exported for direct unit testing of the retry schedule without relying on
// fragile fake-timer boundary assertions.
export function nextPollBackoffMs(previousBackoffMs: number, hidden: boolean): number {
  const base = hidden ? HIDDEN_POLL_MS : BACKOFF_BASE_MS;
  return previousBackoffMs === 0 ? base : Math.min(previousBackoffMs * 2, BACKOFF_MAX_MS);
}

function findCapabilityForMatch(matchId: string): ReplayCapability | null {
  let best: ReplayCapability | null = null;
  for (let index = 0; index < localStorage.length; index += 1) {
    const key = localStorage.key(index);
    if (!key?.startsWith(STORAGE_KEY_PREFIX)) continue;
    const replayId = key.slice(STORAGE_KEY_PREFIX.length);
    const capability = loadReplayCapability(replayId);
    if (!capability || capability.matchId !== matchId) continue;
    if (!best || Date.parse(capability.updatedAt) > Date.parse(best.updatedAt)) {
      best = capability;
    }
  }
  return best;
}

function messageForReplayError(code: string | undefined, messages: Messages): string {
  switch (code) {
    case "REPLAY_NOT_FOUND":
      return messages.replayNotFound;
    case "REPLAY_DISABLED":
      return messages.replayDisabled;
    case "REPLAY_MATCH_NOT_FOUND":
      return messages.replayMatchNotFound;
    case "REPLAY_PLAYER_NOT_IN_MATCH":
      return messages.replayPlayerNotInMatch;
    case "REPLAY_RIGHTS_ATTESTATION_REQUIRED":
      return messages.replayRightsRequired;
    case "REPLAY_UPLOAD_INVALID":
      return messages.replayUploadInvalid;
    case "REPLAY_UPLOAD_EXPIRED":
      return messages.replayUploadExpired;
    case "REPLAY_TOO_LARGE":
      return messages.replayTooLarge;
    case "REPLAY_DURATION_UNSUPPORTED":
      return messages.replayDurationUnsupported;
    case "REPLAY_MEDIA_UNSUPPORTED":
      return messages.replayMediaUnsupported;
    case "REPLAY_PROCESSING_FAILED":
      return messages.replayProcessingFailed;
    case "REPLAY_STORAGE_UNAVAILABLE":
      return messages.replayStorageUnavailable;
    case "REPLAY_FFMPEG_UNAVAILABLE":
      return messages.replayFfmpegUnavailable;
    case "REPLAY_RETRY_NOT_ALLOWED":
      return messages.replayRetryNotAllowed;
    case "INVALID_API_RESPONSE":
      return messages.invalidApiResponse;
    case "NETWORK_ERROR":
      return messages.replayNetworkError;
    default:
      return messages.replayProcessingFailed;
  }
}

function errorMessageFromStatus(status: ReplayStatusResponse, messages: Messages): string | null {
  if (status.status !== "failed" || !status.error_code) return null;
  return messageForReplayError(status.error_code, messages);
}

export function ReplaySection({
  matchId,
  puuid,
  platform,
  locale,
  matchDurationSeconds,
}: {
  matchId: string;
  puuid: string;
  platform: Platform;
  locale: Locale;
  matchDurationSeconds: number;
}) {
  const messages = getMessages(locale);
  void matchDurationSeconds;
  const [activeMatchId, setActiveMatchId] = useState(matchId);
  const [capability, setCapability] = useState<ReplayCapability | null>(() =>
    findCapabilityForMatch(matchId),
  );
  const [status, setStatus] = useState<ReplayStatusResponse | null>(null);
  const [artifacts, setArtifacts] = useState<ReplayArtifact[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadPercent, setUploadPercent] = useState<number | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [showUploadForm, setShowUploadForm] = useState(
    () => findCapabilityForMatch(matchId) === null,
  );
  const uploadAbortRef = useRef<AbortController | null>(null);

  if (activeMatchId !== matchId) {
    const nextCapability = findCapabilityForMatch(matchId);
    setActiveMatchId(matchId);
    setCapability(nextCapability);
    setStatus(null);
    setArtifacts([]);
    setUploading(false);
    setUploadPercent(null);
    setErrorMessage(null);
    setShowUploadForm(nextCapability === null);
  }

  const clearCapabilityState = useCallback((replayId: string | null) => {
    if (replayId) removeReplayCapability(replayId);
    setCapability(null);
    setStatus(null);
    setArtifacts([]);
    setShowUploadForm(true);
  }, []);

  const applyStatus = useCallback(
    (next: ReplayStatusResponse, accessToken: string, replayId: string) => {
      setStatus(next);
      if (next.status === "expired" || next.status === "deleted") {
        clearCapabilityState(replayId);
        return;
      }
      setErrorMessage(errorMessageFromStatus(next, messages));
      saveReplayCapability({
        replayId,
        accessToken,
        matchId,
        updatedAt: new Date().toISOString(),
      });
    },
    [clearCapabilityState, matchId, messages],
  );

  const loadArtifacts = useCallback(
    async (replayId: string, accessToken: string, signal: AbortSignal) => {
      try {
        const response = await getReplayArtifacts({ replayId, accessToken }, signal);
        if (signal.aborted) return;
        setArtifacts(response.artifacts);
      } catch (error) {
        if (signal.aborted) return;
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (error instanceof ApiClientError && error.code === "REPLAY_NOT_FOUND") {
          setErrorMessage(messages.replayNotFound);
          clearCapabilityState(replayId);
          return;
        }
        setErrorMessage(
          messageForReplayError(
            error instanceof ApiClientError ? error.code : undefined,
            messages,
          ),
        );
      }
    },
    [clearCapabilityState, messages],
  );

  // Load status for a locally known capability when none is in memory yet
  useEffect(() => {
    if (!capability || uploading || status !== null) return;

    const controller = new AbortController();
    const { replayId, accessToken } = capability;

    void getReplayStatus({ replayId, accessToken }, controller.signal)
      .then((next) => {
        if (controller.signal.aborted) return;
        applyStatus(next, accessToken, replayId);
        if (next.status === "ready") {
          void loadArtifacts(replayId, accessToken, controller.signal);
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (error instanceof ApiClientError && error.code === "REPLAY_NOT_FOUND") {
          setErrorMessage(messages.replayNotFound);
          clearCapabilityState(replayId);
          return;
        }
        setErrorMessage(
          messageForReplayError(
            error instanceof ApiClientError ? error.code : undefined,
            messages,
          ),
        );
      });

    return () => controller.abort();
  }, [applyStatus, capability, clearCapabilityState, loadArtifacts, messages, status, uploading]);

  // Poll while active
  useEffect(() => {
    if (!capability || uploading) return;
    if (!status || TERMINAL_STATUSES.has(status.status)) return;

    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | null = null;
    let backoffMs = 0;

    const poll = async () => {
      try {
        const next = await getReplayStatus(
          { replayId: capability.replayId, accessToken: capability.accessToken },
          controller.signal,
        );
        if (controller.signal.aborted) return;
        backoffMs = 0;
        applyStatus(next, capability.accessToken, capability.replayId);
        if (next.status === "ready") {
          void loadArtifacts(capability.replayId, capability.accessToken, controller.signal);
          return;
        }
        if (!TERMINAL_STATUSES.has(next.status)) {
          const delay = document.hidden ? HIDDEN_POLL_MS : ACTIVE_POLL_MS;
          timer = setTimeout(() => {
            void poll();
          }, delay);
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (error instanceof ApiClientError && error.code === "REPLAY_NOT_FOUND") {
          setErrorMessage(messages.replayNotFound);
          clearCapabilityState(capability.replayId);
          return;
        }
        setErrorMessage(
          messageForReplayError(
            error instanceof ApiClientError ? error.code : undefined,
            messages,
          ),
        );
        // Network errors are transient: keep polling with a capped exponential
        // backoff instead of giving up. Other error codes (e.g. not-found,
        // storage unavailable) stop polling as before.
        if (error instanceof ApiClientError && error.code === "NETWORK_ERROR") {
          backoffMs = nextPollBackoffMs(backoffMs, document.hidden);
          timer = setTimeout(() => {
            void poll();
          }, backoffMs);
        }
      }
    };

    const onVisibility = () => {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      if (!controller.signal.aborted && status && !TERMINAL_STATUSES.has(status.status)) {
        void poll();
      }
    };

    const delay = document.hidden ? HIDDEN_POLL_MS : ACTIVE_POLL_MS;
    timer = setTimeout(() => {
      void poll();
    }, delay);
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      controller.abort();
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [
    applyStatus,
    capability,
    clearCapabilityState,
    loadArtifacts,
    messages,
    status,
    uploading,
  ]);

  async function handleUpload({ file, gameTimeZeroMs }: ReplayUploadSubmit) {
    const controller = new AbortController();
    uploadAbortRef.current?.abort();
    uploadAbortRef.current = controller;
    setUploading(true);
    setUploadPercent(0);
    setErrorMessage(null);
    setShowUploadForm(false);

    try {
      const created = await createReplay(
        {
          matchId,
          platform,
          puuid,
          originalFilename: file.name,
          declaredSizeBytes: file.size,
          declaredContentType: file.type || "application/octet-stream",
          gameTimeZeroMs,
          rightsAttested: true,
          rightsStatementVersion: RIGHTS_STATEMENT_VERSION,
        },
        controller.signal,
      );
      if (controller.signal.aborted) return;

      const nextCapability: ReplayCapability = {
        replayId: created.replay_id,
        accessToken: created.access_token,
        matchId,
        updatedAt: new Date().toISOString(),
      };
      saveReplayCapability(nextCapability);
      setCapability(nextCapability);

      await uploadReplayContent({
        upload: created.upload,
        accessToken: created.access_token,
        body: file,
        signal: controller.signal,
        onProgress: (loaded, total) => {
          if (total > 0) {
            setUploadPercent(Math.round((loaded / total) * 100));
          }
        },
      });
      if (controller.signal.aborted) return;

      const completed = await completeReplay(
        { replayId: created.replay_id, accessToken: created.access_token },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setUploading(false);
      setUploadPercent(null);
      applyStatus(completed, created.access_token, created.replay_id);
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error instanceof DOMException && error.name === "AbortError") return;
      setUploading(false);
      setUploadPercent(null);
      setShowUploadForm(true);
      setErrorMessage(
        messageForReplayError(error instanceof ApiClientError ? error.code : undefined, messages),
      );
    }
  }

  async function handleRetry() {
    if (!capability) return;
    const controller = new AbortController();
    setErrorMessage(null);
    try {
      const next = await retryReplay(
        { replayId: capability.replayId, accessToken: capability.accessToken },
        controller.signal,
      );
      applyStatus(next, capability.accessToken, capability.replayId);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setErrorMessage(
        messageForReplayError(error instanceof ApiClientError ? error.code : undefined, messages),
      );
    }
  }

  async function handleDelete() {
    if (!capability) return;
    if (!window.confirm(messages.replayDeleteConfirm)) return;
    const controller = new AbortController();
    try {
      await deleteReplay(
        { replayId: capability.replayId, accessToken: capability.accessToken },
        controller.signal,
      );
      clearCapabilityState(capability.replayId);
      setErrorMessage(null);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      if (error instanceof ApiClientError && error.code === "REPLAY_NOT_FOUND") {
        setErrorMessage(messages.replayNotFound);
        clearCapabilityState(capability.replayId);
        return;
      }
      setErrorMessage(
        messageForReplayError(error instanceof ApiClientError ? error.code : undefined, messages),
      );
    }
  }

  function handleCancelUpload() {
    uploadAbortRef.current?.abort();
    uploadAbortRef.current = null;
    setUploading(false);
    setUploadPercent(null);
    if (capability) {
      clearCapabilityState(capability.replayId);
    } else {
      setShowUploadForm(true);
    }
  }

  const refreshArtifacts = useCallback(() => {
    if (!capability) return;
    const controller = new AbortController();
    void loadArtifacts(capability.replayId, capability.accessToken, controller.signal);
  }, [capability, loadArtifacts]);

  const tracking = capability !== null || uploading || status !== null;

  return (
    <section className="replay-section" aria-labelledby="replay-section-title">
      <header className="replay-section-header">
        <h2 id="replay-section-title">{messages.uploadReplay}</h2>
        <p className="replay-no-ai-notice" role="note">
          {messages.replayNoAiNotice}
        </p>
        <p className="replay-token-notice">{messages.replayTokenStorageNotice}</p>
      </header>

      {showUploadForm && !uploading && (!status || status.status === "deleted" || status.status === "expired") ? (
        <ReplayUploadForm messages={messages} disabled={uploading} onSubmit={handleUpload} />
      ) : null}

      {tracking ? (
        <ReplayStatusPanel
          messages={messages}
          status={status}
          uploading={uploading}
          uploadPercent={uploadPercent}
          errorMessage={errorMessage}
          onRetry={status?.error_retryable ? handleRetry : undefined}
          onDelete={capability ? handleDelete : undefined}
          onCancelUpload={uploading ? handleCancelUpload : undefined}
        />
      ) : errorMessage ? (
        <p className="replay-error" role="alert">
          {errorMessage}
        </p>
      ) : null}

      {status?.status === "ready" && capability && artifacts.length > 0 ? (
        <ReplayArtifactGallery
          artifacts={artifacts}
          accessToken={capability.accessToken}
          messages={messages}
          onRefreshManifest={refreshArtifacts}
        />
      ) : null}
    </section>
  );
}
