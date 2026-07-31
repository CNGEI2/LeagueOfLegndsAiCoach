"use client";

import { useEffect, useState } from "react";

import { getRecentMatches } from "@/api/client";
import type { RecentMatchesResponse } from "@/api/schemas";
import { DataState } from "@/components/data-state";
import { PlayerHeader } from "@/components/player-header";
import { RecentMatchList } from "@/components/recent-match-list";
import type { Locale } from "@/i18n/locales";
import { getMessages } from "@/i18n/messages";

type PageState =
  | { status: "loading" }
  | { status: "error"; requestKey: string }
  | { status: "success"; requestKey: string; response: RecentMatchesResponse };

export function PlayerPageClient({
  locale,
  puuid,
  platform,
}: {
  locale: Locale;
  puuid: string;
  platform: "NA1";
}) {
  const messages = getMessages(locale);
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [retry, setRetry] = useState(0);
  const requestKey = `${locale}:${platform}:${puuid}:${retry}`;

  useEffect(() => {
    const controller = new AbortController();

    void getRecentMatches({ puuid, platform, locale, count: 10 }, controller.signal)
      .then((response) => {
        if (!controller.signal.aborted) setState({ status: "success", requestKey, response });
      })
      .catch(() => {
        if (!controller.signal.aborted) setState({ status: "error", requestKey });
      });

    return () => controller.abort();
  }, [locale, platform, puuid, requestKey]);

  if (state.status === "loading" || state.requestKey !== requestKey) {
    return <main className="player-page"><DataState state="loading" messages={messages} /></main>;
  }
  if (state.status === "error") {
    return (
      <main className="player-page">
        <DataState state="error" messages={messages} onRetry={() => setRetry((value) => value + 1)} />
      </main>
    );
  }

  return (
    <main className="player-page">
      <PlayerHeader player={state.response.player} messages={messages} />
      {state.response.matches.length === 0 ? (
        <DataState state="empty" messages={messages} />
      ) : (
        <RecentMatchList
          locale={locale}
          puuid={puuid}
          matches={state.response.matches}
          messages={messages}
        />
      )}
    </main>
  );
}
