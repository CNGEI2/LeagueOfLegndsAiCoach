"use client";

import { type FormEvent, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiClientError, confirmPlayerPlatform, detectPlayer } from "@/api/client";
import type { Platform, PlatformCandidate } from "@/api/schemas";
import type { Locale } from "@/i18n/locales";
import type { Messages } from "@/i18n/messages";

type SearchState =
  | { status: "idle" }
  | { status: "detecting" }
  | {
      status: "confirmation_required";
      detectionId: string;
      expiresAt: string;
      candidates: PlatformCandidate[];
      confirming: Platform | null;
    }
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
    if (typeof retryAfter !== "number" || !Number.isFinite(retryAfter) || retryAfter < 0) {
      return messages.rateLimitedWithoutDelay;
    }
    return fill(messages.rateLimited, { seconds: retryAfter });
  }
  if (error.code === "RIOT_PLATFORM_DETECTION_UNAVAILABLE") {
    return messages.detectionUnavailable;
  }
  if (error.code === "PLATFORM_CONFIRMATION_EXPIRED") {
    return messages.confirmationExpired;
  }
  if (error.code === "INVALID_PLATFORM_SELECTION") {
    return messages.invalidPlatformSelection;
  }
  return messages.searchFailed;
}

function navigateToPlayer(
  router: ReturnType<typeof useRouter>,
  locale: Locale,
  puuid: string,
  platform: Platform,
) {
  router.push(`/${locale}/players/${encodeURIComponent(puuid)}?platform=${platform}`);
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
  const [riotId, setRiotId] = useState("");
  const requestGeneration = useRef(0);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = riotId.trim();
    const generation = ++requestGeneration.current;
    setState({ status: "detecting" });

    try {
      const result = await detectPlayer({ riotId: trimmed, locale });
      if (generation !== requestGeneration.current) return;
      if (result.status === "resolved") {
        navigateToPlayer(router, locale, result.player.puuid, result.player.platform);
        return;
      }
      setState({
        status: "confirmation_required",
        detectionId: result.detection_id,
        expiresAt: result.expires_at,
        candidates: result.candidates,
        confirming: null,
      });
    } catch (error) {
      if (generation !== requestGeneration.current) return;
      setState({
        status: "error",
        error: error instanceof ApiClientError ? error : null,
      });
    }
  }

  async function handleConfirm(platform: Platform) {
    if (state.status !== "confirmation_required") return;
    const generation = ++requestGeneration.current;
    const { detectionId } = state;
    setState({ ...state, confirming: platform });

    try {
      const result = await confirmPlayerPlatform({ detectionId, platform, locale });
      if (generation !== requestGeneration.current) return;
      if (result.status === "resolved") {
        navigateToPlayer(router, locale, result.player.puuid, result.player.platform);
        return;
      }
      setState({
        status: "confirmation_required",
        detectionId: result.detection_id,
        expiresAt: result.expires_at,
        candidates: result.candidates,
        confirming: null,
      });
    } catch (error) {
      if (generation !== requestGeneration.current) return;
      const clientError = error instanceof ApiClientError ? error : null;
      if (clientError?.code === "PLATFORM_CONFIRMATION_EXPIRED") {
        setState({ status: "error", error: clientError });
        return;
      }
      setState({ status: "error", error: clientError });
    }
  }

  const busy =
    state.status === "detecting" ||
    (state.status === "confirmation_required" && state.confirming !== null);

  return (
    <div className="search-panel">
      {state.status === "confirmation_required" ? (
        <div className="server-confirmation">
          <h2>{messages.chooseServer}</h2>
          <p>{messages.chooseServerHelp}</p>
          <div className="server-candidates">
            {state.candidates.map((candidate) => (
              <button
                key={candidate.platform}
                type="button"
                disabled={busy}
                onClick={() => void handleConfirm(candidate.platform)}
              >
                {state.confirming === candidate.platform
                  ? messages.confirmingServer
                  : candidate.display_name}
              </button>
            ))}
          </div>
          {state.confirming !== null ? (
            <p role="status">{messages.confirmingServerStatus}</p>
          ) : null}
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="search-card search-card-single">
          <label>
            <span>{messages.riotId}</span>
            <input
              name="riotId"
              autoComplete="off"
              required
              maxLength={49}
              value={riotId}
              onChange={(event) => setRiotId(event.target.value)}
              disabled={busy}
            />
          </label>
          <button type="submit" disabled={busy}>
            {state.status === "detecting" ? messages.detecting : messages.detectAccount}
          </button>
          <p className="example">{messages.riotIdExample}</p>
          <p className="tag-help">{messages.tagIsNotServer}</p>
          {state.status === "detecting" ? (
            <p role="status">{messages.detectingStatus}</p>
          ) : null}
        </form>
      )}
      {state.status === "error" ? (
        <div className="search-error" role="alert">
          <p>{errorMessage(state.error, messages)}</p>
          {state.error?.code === "PLATFORM_CONFIRMATION_EXPIRED" ? (
            <p>{messages.detectAgain}</p>
          ) : null}
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
    </div>
  );
}
