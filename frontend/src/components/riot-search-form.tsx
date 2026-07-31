"use client";

import { type FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiClientError, resolvePlayer } from "@/api/client";
import type { Locale } from "@/i18n/locales";
import type { Messages } from "@/i18n/messages";

type SearchState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; error: ApiClientError | null };

function fill(template: string, values: Record<string, string | number>) {
  return template.replace(/\{(\w+)\}/g, (_, key: string) => String(values[key] ?? ""));
}

function errorMessage(error: ApiClientError | null, messages: Messages) {
  if (!error) return messages.searchFailed;
  if (error.code === "PLAYER_NOT_FOUND") return messages.playerNotFound;
  if (error.code === "INVALID_RIOT_ID" || error.code === "VALIDATION_ERROR") {
    return messages.invalidRiotId;
  }
  if (error.code === "RIOT_RATE_LIMITED") {
    const retryAfter = error.params.retry_after_seconds;
    const seconds = typeof retryAfter === "number" ? retryAfter : "a few";
    return fill(messages.rateLimited, { seconds });
  }
  return messages.searchFailed;
}

export function RiotSearchForm({
  locale,
  messages,
}: {
  locale: Locale;
  messages: Messages;
}) {
  const router = useRouter();
  const [state, setState] = useState<SearchState>({ status: "idle" });

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const gameName = String(formData.get("gameName") ?? "").trim();
    const tagLine = String(formData.get("tagLine") ?? "").trim();
    const platform = String(formData.get("platform") ?? "NA1") as "NA1";
    setState({ status: "loading" });

    try {
      const result = await resolvePlayer({ platform, gameName, tagLine });
      router.push(`/${locale}/players/${encodeURIComponent(result.player.puuid)}?platform=NA1`);
    } catch (error) {
      setState({
        status: "error",
        error: error instanceof ApiClientError ? error : null,
      });
    }
  }

  return (
    <form onSubmit={handleSubmit} className="search-card">
      <label>
        <span>{messages.gameName}</span>
        <input name="gameName" autoComplete="off" required maxLength={32} />
      </label>
      <label>
        <span>{messages.tagLine}</span>
        <input name="tagLine" autoComplete="off" required maxLength={16} />
      </label>
      <label>
        <span>{messages.region}</span>
        <select name="platform" defaultValue="NA1">
          <option value="NA1">{messages.northAmerica}</option>
        </select>
      </label>
      <button type="submit" disabled={state.status === "loading"}>
        {state.status === "loading" ? messages.searching : messages.search}
      </button>
      <p className="example">{messages.example}</p>
      {state.status === "loading" ? <p role="status">{messages.searchingStatus}</p> : null}
      {state.status === "error" ? (
        <div className="search-error" role="alert">
          <p>{errorMessage(state.error, messages)}</p>
          {state.error?.requestId ? (
            <details>
              <summary>{messages.supportDetails}</summary>
              <p className="utility-data">
                {fill(messages.requestId, { requestId: state.error.requestId })}
              </p>
            </details>
          ) : null}
        </div>
      ) : null}
    </form>
  );
}
