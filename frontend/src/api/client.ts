import type { z } from "zod";

import {
  errorResponseSchema,
  matchDetailResponseSchema,
  recentMatchesResponseSchema,
  resolvePlayerResponseSchema,
} from "@/api/schemas";
import type { Locale } from "@/i18n/locales";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const requestIdPattern = /^[0-9a-f]{32}$/;

function safeRequestId(value: string | null): string | null {
  return value !== null && requestIdPattern.test(value) ? value : null;
}

export class ApiClientError extends Error {
  constructor(
    readonly code: string,
    readonly params: Record<string, unknown>,
    readonly retryable: boolean,
    readonly requestId: string | null,
  ) {
    super(code);
    this.name = "ApiClientError";
  }
}

async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiClientError("NETWORK_ERROR", {}, true, null);
  }

  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const parsed = errorResponseSchema.safeParse(body);
    if (!parsed.success) {
      throw new ApiClientError(
        "INVALID_API_RESPONSE",
        {},
        true,
        safeRequestId(response.headers.get("X-Request-ID")),
      );
    }
    throw new ApiClientError(
      parsed.data.error.code,
      parsed.data.error.params,
      parsed.data.error.retryable,
      safeRequestId(parsed.data.error.request_id),
    );
  }

  const parsed = schema.safeParse(body);
  if (!parsed.success) {
    throw new ApiClientError(
      "INVALID_API_RESPONSE",
      {},
      true,
      safeRequestId(response.headers.get("X-Request-ID")),
    );
  }
  return parsed.data;
}

export type ResolvePlayerInput = {
  platform: "NA1";
  gameName: string;
  tagLine: string;
};

export async function resolvePlayer(input: ResolvePlayerInput, signal?: AbortSignal) {
  const query = new URLSearchParams({
    platform: input.platform,
    game_name: input.gameName,
    tag_line: input.tagLine,
  });
  return request(`/api/v1/players/resolve?${query}`, resolvePlayerResponseSchema, signal);
}

export type RecentMatchesInput = {
  puuid: string;
  platform: "NA1";
  locale: Locale;
  count: number;
};

export async function getRecentMatches(input: RecentMatchesInput, signal?: AbortSignal) {
  const query = new URLSearchParams({
    platform: input.platform,
    locale: input.locale,
    count: String(input.count),
  });
  return request(
    `/api/v1/players/${encodeURIComponent(input.puuid)}/matches?${query}`,
    recentMatchesResponseSchema,
    signal,
  );
}

export type MatchDetailInput = {
  matchId: string;
  puuid: string;
  platform: "NA1";
  locale: Locale;
};

export async function getMatchDetail(input: MatchDetailInput, signal?: AbortSignal) {
  const query = new URLSearchParams({
    platform: input.platform,
    puuid: input.puuid,
    locale: input.locale,
  });
  return request(
    `/api/v1/matches/${encodeURIComponent(input.matchId)}?${query}`,
    matchDetailResponseSchema,
    signal,
  );
}
