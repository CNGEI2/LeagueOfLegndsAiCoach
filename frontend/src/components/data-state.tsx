import type { Messages } from "@/i18n/messages";

export function DataState({
  state,
  messages,
  onRetry,
}: {
  state: "loading" | "empty" | "error";
  messages: Messages;
  onRetry?: () => void;
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
      {onRetry ? <button type="button" onClick={onRetry}>{messages.retry}</button> : null}
    </section>
  );
}
