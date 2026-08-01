"use client";

import type { ReplayStatusResponse } from "@/api/schemas";
import type { Messages } from "@/i18n/messages";

function fill(template: string, values: Record<string, string>) {
  return template.replace(/\{(\w+)\}/g, (_, key: string) => values[key] ?? "");
}

export function stageMessage(
  status: ReplayStatusResponse | null,
  uploading: boolean,
  messages: Messages,
): string {
  if (uploading) return messages.replayStageUploading;
  if (!status) return "";
  if (status.status === "queued" || status.status === "uploaded" || status.status === "created") {
    return messages.replayStageQueued;
  }
  if (status.status === "ready") return messages.replayStageReady;
  if (status.status === "failed") return messages.replayStageFailed;
  if (status.status === "expired") return messages.replayStageExpired;
  if (status.status === "deleted" || status.status === "deleting") {
    return messages.replayStageDeleted;
  }
  const stage = status.processing_stage ?? status.status;
  if (stage === "probing") return messages.replayStageProbing;
  if (stage === "transcoding") return messages.replayStageTranscoding;
  if (stage === "extracting") return messages.replayStageExtracting;
  if (stage === "finalizing") return messages.replayStageFinalizing;
  return messages.replayStageQueued;
}

export function ReplayStatusPanel({
  messages,
  status,
  uploading,
  uploadPercent,
  errorMessage,
  onRetry,
  onDelete,
  onCancelUpload,
}: {
  messages: Messages;
  status: ReplayStatusResponse | null;
  uploading: boolean;
  uploadPercent: number | null;
  errorMessage: string | null;
  onRetry?: () => void;
  onDelete?: () => void;
  onCancelUpload?: () => void;
}) {
  const progressValue = uploading
    ? (uploadPercent ?? 0)
    : (status?.progress_percent ?? 0);
  const stage = stageMessage(status, uploading, messages);
  const showProgress = uploading || (status !== null && status.status !== "deleted");
  const showRetry = status?.status === "failed" && status.error_retryable === true && onRetry;
  const showDelete =
    status !== null &&
    status.status !== "deleted" &&
    status.status !== "expired" &&
    !uploading &&
    onDelete;
  const retention =
    status?.derived_delete_after != null
      ? fill(messages.replayRetentionNotice, {
          date: new Date(status.derived_delete_after).toLocaleString(),
        })
      : null;

  return (
    <div className="replay-status-panel">
      {showProgress ? (
        <div
          className="replay-progress"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.max(0, Math.min(100, Math.round(progressValue)))}
          aria-label={stage}
        >
          <div
            className="replay-progress-bar"
            style={{ width: `${Math.max(0, Math.min(100, progressValue))}%` }}
          />
        </div>
      ) : null}

      {stage ? (
        <p className="replay-stage" role="status" aria-live="polite">
          {stage}
        </p>
      ) : null}

      {errorMessage ? (
        <p className="replay-error" role="alert">
          {errorMessage}
        </p>
      ) : null}

      {status?.warning_codes.includes("partial_coverage") ? (
        <p className="replay-partial-coverage" role="status">
          {messages.replayPartialCoverage}
        </p>
      ) : null}

      {retention ? <p className="replay-retention">{retention}</p> : null}

      <div className="replay-status-actions">
        {uploading && onCancelUpload ? (
          <button type="button" onClick={onCancelUpload}>
            {messages.replayCancelUpload}
          </button>
        ) : null}
        {showRetry ? (
          <button type="button" onClick={onRetry}>
            {messages.replayRetry}
          </button>
        ) : null}
        {showDelete ? (
          <button type="button" onClick={onDelete}>
            {messages.replayDelete}
          </button>
        ) : null}
      </div>
    </div>
  );
}
