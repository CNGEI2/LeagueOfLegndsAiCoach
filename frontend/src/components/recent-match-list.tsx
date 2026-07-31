import type { RecentMatchItem } from "@/api/schemas";
import type { Locale } from "@/i18n/locales";
import type { Messages } from "@/i18n/messages";

import { RecentMatchCard } from "./recent-match-card";

export function RecentMatchList({
  locale,
  puuid,
  matches,
  messages,
}: {
  locale: Locale;
  puuid: string;
  matches: RecentMatchItem[];
  messages: Messages;
}) {
  return (
    <section className="recent-match-section" aria-labelledby="recent-matches-heading">
      <h2 id="recent-matches-heading">{messages.recentMatches}</h2>
      <ol className="match-rail">
        {matches.map((match) => (
          <li key={match.match_id}>
            <RecentMatchCard locale={locale} puuid={puuid} match={match} messages={messages} />
          </li>
        ))}
      </ol>
    </section>
  );
}
