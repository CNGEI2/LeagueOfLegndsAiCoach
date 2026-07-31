import type { Messages } from "@/i18n/messages";

function fill(template: string, values: Record<string, string>) {
  return template.replace(/\{(\w+)\}/g, (_, key: string) => values[key] ?? "");
}

export function DataState({
  state,
  messages,
  onRetry,
  requestId,
}: {
  state: "loading" | "empty" | "error";
  messages: Messages;
  onRetry?: () => void;
  requestId?: string | null;
}) {
  if (state === "loading") {
    return <p className="data-state" role="status">{messages.loadingMatches}</p>;
  }
  if (state === "empty") {
    return <p className="data-state">{messages.noRecentMatches}</p>;
  }
  return (
    <section className="data-state" role="alert">
      <p>{messages.loadMatchesFailed}</p>
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
