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

function numericValue(value: number | null, messages: Messages) {
  return value === null ? messages.unavailable : String(value);
}

function kdaValue(match: RecentMatchItem, messages: Messages) {
  const { assists, deaths, kills } = match.participant;
  if (kills === null || deaths === null || assists === null) return messages.unavailable;
  return `${kills} / ${deaths} / ${assists}`;
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
        <p className="utility-data">{messages.kda}: {kdaValue(match, messages)}</p>
        <p className="utility-data">{messages.cs}: {numericValue(match.participant.cs, messages)}</p>
      </div>
      <div className="match-game-assets">
        {match.participant.champion ? (
          <>
            {/* The backend supplies a localized public static-data URL; no fixed Next image host is safe here. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={match.participant.champion.image_url}
              alt={fill(messages.championAlt, { name: match.participant.champion.name })}
            />
          </>
        ) : (
          <p className="utility-data">{messages.champion} #{match.participant.champion_id}</p>
        )}
        <ul aria-label={messages.item} className="match-item-assets">
          {match.participant.item_ids.map((itemId, index) => {
            const item = match.participant.items[index];
            return (
              <li key={`${itemId}-${index}`}>
                {item ? (
                  <>
                    {/* The backend supplies a localized public static-data URL; no fixed Next image host is safe here. */}
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={item.image_url} alt={fill(messages.itemAlt, { name: item.name })} />
                  </>
                ) : (
                  <span className="utility-data">{messages.item} #{itemId}</span>
                )}
              </li>
            );
          })}
        </ul>
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
