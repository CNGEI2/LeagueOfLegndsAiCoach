import Link from "next/link";

import type { RecentMatchItem } from "@/api/schemas";
import type { Locale } from "@/i18n/locales";
import type { Messages } from "@/i18n/messages";

function fill(template: string, values: Record<string, string | number>) {
  return template.replace(/\{(\w+)\}/g, (_, key: string) => String(values[key] ?? ""));
}

function detailUnavailableMessage(match: RecentMatchItem, messages: Messages) {
  if (match.detail_unavailable_reason_code === "MATCH_DETAIL_UNSUPPORTED_MODE") {
    return messages.detailUnavailable;
  }
  return messages.detailUnavailable;
}

export function RecentMatchCard({
  locale,
  puuid,
  match,
  messages,
}: {
  locale: Locale;
  puuid: string;
  match: RecentMatchItem;
  messages: Messages;
}) {
  const matchDate = new Date(match.started_at);
  const outcome = match.participant.won ? messages.win : messages.loss;
  const link = `/${locale}/matches/${encodeURIComponent(match.match_id)}?platform=${match.platform}&puuid=${encodeURIComponent(puuid)}`;

  return (
    <article className="match-slip" data-testid="recent-match-card">
      <div className="match-slip-marker" aria-hidden="true" />
      <div className="match-slip-main">
        <p className={`match-outcome ${match.participant.won ? "match-win" : "match-loss"}`}>
          {outcome}
        </p>
        <p className="utility-data">{fill(messages.queue, { queueId: match.queue_id })}</p>
        <time className="utility-data" dateTime={match.started_at}>
          {new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(matchDate)}
        </time>
      </div>
      <div className="match-slip-meta">
        <p className="utility-data">{messages.matchId}: {match.match_id}</p>
        {match.detail_supported ? (
          <Link href={link}>{messages.matchDetails}</Link>
        ) : (
          <p className="match-unavailable">{detailUnavailableMessage(match, messages)}</p>
        )}
        {!match.analysis_supported ? (
          <p className="match-future-notice">{messages.futureReviewUnavailable}</p>
        ) : null}
      </div>
    </article>
  );
}
