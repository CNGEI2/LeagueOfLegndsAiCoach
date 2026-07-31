import type { Messages } from "@/i18n/messages";

function fill(template: string, values: Record<string, string>) {
  return template.replace(/\{(\w+)\}/g, (_, key: string) => values[key] ?? "");
}

function messageForError(
  code: string | undefined,
  params: Record<string, unknown> | undefined,
  messages: Messages,
) {
  if (code === "PLAYER_NOT_FOUND") return messages.playerNotFound;
  if (code === "MATCH_NOT_FOUND") return messages.matchNotFound;
  if (code === "PLAYER_NOT_IN_MATCH") return messages.playerNotInMatch;
  if (code === "RIOT_NOT_CONFIGURED") return messages.riotNotConfigured;
  if (code === "RIOT_AUTH_FAILED") return messages.riotAuthFailed;
  if (code === "RIOT_UNAVAILABLE" || code === "NETWORK_ERROR") return messages.riotUnavailable;
  if (code === "RIOT_REQUEST_INVALID" || code === "VALIDATION_ERROR") return messages.riotRequestInvalid;
  if (code === "INVALID_API_RESPONSE") return messages.invalidApiResponse;
  if (code === "MATCH_DETAIL_UNSUPPORTED_MODE") return messages.matchDetailUnsupportedMode;
  if (code === "MATCH_DETAIL_UNAVAILABLE") return messages.detailUnavailable;
  if (code === "RIOT_RATE_LIMITED") {
    const seconds = params?.retry_after_seconds;
    if (typeof seconds === "number" && Number.isFinite(seconds) && seconds >= 0) {
      return fill(messages.riotRateLimited, { seconds: String(seconds) });
    }
    return messages.rateLimitedWithoutDelay;
  }
  return messages.loadMatchesFailed;
}

export function DataState({
  state,
  messages,
  onRetry,
  requestId,
  loadingMessage,
  emptyMessage,
  errorCode,
  errorParams,
}: {
  state: "loading" | "empty" | "error";
  messages: Messages;
  onRetry?: () => void;
  requestId?: string | null;
  loadingMessage?: string;
  emptyMessage?: string;
  errorCode?: string;
  errorParams?: Record<string, unknown>;
}) {
  if (state === "loading") {
    return <p className="data-state" role="status">{loadingMessage ?? messages.loadingMatches}</p>;
  }
  if (state === "empty") {
    return <p className="data-state">{emptyMessage ?? messages.noRecentMatches}</p>;
  }
  return (
    <section className="data-state" role="alert">
      <p>{messageForError(errorCode, errorParams, messages)}</p>
      {requestId ? (
        <details>
          <summary>{messages.supportDetails}</summary>
          <p className="utility-data">{fill(messages.requestId, { requestId })}</p>
        </details>
      ) : null}
      {onRetry ? <button type="button" onClick={onRetry}>{messages.retry}</button> : null}
    </section>
  );
}
