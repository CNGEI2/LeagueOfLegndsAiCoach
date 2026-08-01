"use client";

import { useEffect, useState } from "react";

import { ApiClientError, getMatchDetail } from "@/api/client";
import type { MatchDetailResponse } from "@/api/schemas";
import { DataState } from "@/components/data-state";
import { MatchTeamTable } from "@/components/match-team-table";
import { ReplaySection } from "@/components/replay-section";
import type { Locale } from "@/i18n/locales";
import { getMessages } from "@/i18n/messages";

type RequestState<T> =
  | { status: "loading" }
  | { status: "success"; requestKey: string; data: T }
  | { status: "empty"; requestKey: string }
  | {
      status: "error";
      requestKey: string;
      error: {
        code: string;
        params: Record<string, unknown>;
        retryable: boolean;
        requestId: string | null;
      } | null;
    };

export function MatchDetailClient({
  locale,
  matchId,
  puuid,
  platform,
}: {
  locale: Locale;
  matchId: string;
  puuid: string;
  platform: "NA1";
}) {
  const messages = getMessages(locale);
  const [state, setState] = useState<RequestState<MatchDetailResponse>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const requestKey = `${locale}:${platform}:${puuid}:${matchId}:${attempt}`;

  useEffect(() => {
    const controller = new AbortController();
    void getMatchDetail({ matchId, puuid, platform, locale }, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        const selectedFound = data.selected_puuid === puuid && [...data.blue_team, ...data.red_team].some(
          (participant) => participant.puuid === puuid,
        );
        if (!selectedFound) {
          setState({
            status: "error",
            requestKey,
            error: {
              code: "PLAYER_NOT_IN_MATCH",
              params: {},
              retryable: false,
              requestId: data.request_id,
            },
          });
          return;
        }
        setState({ status: "success", requestKey, data });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          status: "error",
          requestKey,
          error:
            error instanceof ApiClientError
              ? {
                  code: error.code,
                  params: error.params,
                  retryable: error.retryable,
                  requestId: error.requestId,
                }
              : null,
        });
      });
    return () => controller.abort();
  }, [locale, matchId, platform, puuid, requestKey]);

  if (state.status === "loading" || state.requestKey !== requestKey) {
    return (
      <main className="match-detail-page">
        <DataState state="loading" messages={messages} loadingMessage={messages.loadingMatchDetail} />
      </main>
    );
  }
  if (state.status === "empty") {
    return (
      <main className="match-detail-page">
        <DataState state="empty" messages={messages} emptyMessage={messages.noMatches} />
      </main>
    );
  }
  if (state.status === "error") {
    return (
      <main className="match-detail-page">
        <DataState
          state="error"
          messages={messages}
          errorCode={state.error?.code}
          errorParams={state.error?.params}
          requestId={state.error?.requestId}
          onRetry={() => setAttempt((value) => value + 1)}
        />
      </main>
    );
  }

  const { data } = state;
  return (
    <main className="match-detail-page">
      <header className="match-detail-header">
        <div>
          <p className="eyebrow">
            {data.platform} · {data.game_version}
          </p>
          <h1>{messages.matchDetails}</h1>
          <p className="utility-data">
            {messages.matchId}: {data.match_id}
          </p>
        </div>
        <p className="match-scope-notice" role="note">
          {messages.dataOnlyScopeNotice}
        </p>
      </header>
      {!data.static_data_status.available ? (
        <p className="static-data-warning" role="alert">
          {messages.staticDataUnavailable}
        </p>
      ) : null}
      <div className="match-teams">
        <MatchTeamTable
          caption={messages.blueTeam}
          participants={data.blue_team}
          selectedPuuid={data.selected_puuid}
          staticDataAvailable={data.static_data_status.available}
          messages={messages}
        />
        <MatchTeamTable
          caption={messages.redTeam}
          participants={data.red_team}
          selectedPuuid={data.selected_puuid}
          staticDataAvailable={data.static_data_status.available}
          messages={messages}
        />
      </div>
      <ReplaySection
        locale={locale}
        matchId={data.match_id}
        puuid={data.selected_puuid}
        platform={data.platform}
        matchDurationSeconds={data.duration_seconds}
      />
    </main>
  );
}
