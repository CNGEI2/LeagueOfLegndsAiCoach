import type { z } from "zod";

import {
  errorResponseSchema,
  matchDetailResponseSchema,
  recentMatchesResponseSchema,
  replayArtifactsResponseSchema,
  replayCreateResponseSchema,
  replayStatusResponseSchema,
  type ReplayArtifactAccess,
  type ReplayArtifactKind,
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

type RequestOptions = {
  method?: string;
  body?: unknown;
  token?: string;
  signal?: AbortSignal;
};

async function request<T>(path: string, schema: z.ZodType<T>, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, token, signal } = options;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (token !== undefined) {
    headers.Authorization = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiClientError("NETWORK_ERROR", {}, true, null);
  }

  const responseBody: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const parsed = errorResponseSchema.safeParse(responseBody);
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

  const parsed = schema.safeParse(responseBody);
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
  return request(`/api/v1/players/resolve?${query}`, resolvePlayerResponseSchema, { signal });
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
    { signal },
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
  return request(`/api/v1/matches/${encodeURIComponent(input.matchId)}?${query}`, matchDetailResponseSchema, {
    signal,
  });
}

export type CreateReplayInput = {
  matchId: string;
  platform: "NA1";
  puuid: string;
  originalFilename: string;
  declaredSizeBytes: number;
  declaredContentType: string;
  gameTimeZeroMs: number;
  rightsAttested: boolean;
  rightsStatementVersion: string;
};

export async function createReplay(input: CreateReplayInput, signal?: AbortSignal) {
  return request("/api/v1/replays", replayCreateResponseSchema, {
    method: "POST",
    body: {
      match_id: input.matchId,
      platform: input.platform,
      puuid: input.puuid,
      original_filename: input.originalFilename,
      declared_size_bytes: input.declaredSizeBytes,
      declared_content_type: input.declaredContentType,
      game_time_zero_ms: input.gameTimeZeroMs,
      rights_attested: input.rightsAttested,
      rights_statement_version: input.rightsStatementVersion,
    },
    signal,
  });
}

export type ReplayAuthInput = {
  replayId: string;
  accessToken: string;
};

export async function completeReplay(input: ReplayAuthInput, signal?: AbortSignal) {
  return request(
    `/api/v1/replays/${encodeURIComponent(input.replayId)}/complete`,
    replayStatusResponseSchema,
    { method: "POST", token: input.accessToken, signal },
  );
}

export async function getReplayStatus(input: ReplayAuthInput, signal?: AbortSignal) {
  return request(`/api/v1/replays/${encodeURIComponent(input.replayId)}`, replayStatusResponseSchema, {
    token: input.accessToken,
    signal,
  });
}

export async function getReplayArtifacts(input: ReplayAuthInput, signal?: AbortSignal) {
  return request(
    `/api/v1/replays/${encodeURIComponent(input.replayId)}/artifacts`,
    replayArtifactsResponseSchema,
    { token: input.accessToken, signal },
  );
}

export async function retryReplay(input: ReplayAuthInput, signal?: AbortSignal) {
  return request(
    `/api/v1/replays/${encodeURIComponent(input.replayId)}/retry`,
    replayStatusResponseSchema,
    { method: "POST", token: input.accessToken, signal },
  );
}

export async function deleteReplay(input: ReplayAuthInput, signal?: AbortSignal) {
  return request(`/api/v1/replays/${encodeURIComponent(input.replayId)}`, replayStatusResponseSchema, {
    method: "DELETE",
    token: input.accessToken,
    signal,
  });
}

export type UploadReplayContentInput = {
  upload: {
    method: string;
    url: string;
    headers: Record<string, string>;
    expires_at: string;
  };
  accessToken: string;
  body: Blob;
  onProgress?: (loaded: number, total: number) => void;
  signal?: AbortSignal;
};

function abortError(): DOMException {
  return new DOMException("The operation was aborted.", "AbortError");
}

const UPLOAD_EXPIRY_SKEW_MS = 5000;

export async function uploadReplayContent(input: UploadReplayContentInput): Promise<void> {
  const url = new URL(input.upload.url, apiBaseUrl).toString();
  const relative = input.upload.url.startsWith("/");

  if (relative) {
    const expiresAtMs = Date.parse(input.upload.expires_at);
    if (Number.isFinite(expiresAtMs) && expiresAtMs - Date.now() <= UPLOAD_EXPIRY_SKEW_MS) {
      throw new ApiClientError("REPLAY_UPLOAD_EXPIRED", {}, false, null);
    }
  }

  await new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    let settled = false;

    const settle = (action: () => void) => {
      if (settled) return;
      settled = true;
      input.signal?.removeEventListener("abort", onAbort);
      action();
    };

    const onAbort = () => {
      xhr.abort();
      settle(() => reject(abortError()));
    };

    xhr.open(input.upload.method, url);

    if (relative) {
      xhr.setRequestHeader("Authorization", `Bearer ${input.accessToken}`);
    }
    for (const [header, value] of Object.entries(input.upload.headers)) {
      xhr.setRequestHeader(header, value);
    }

    xhr.upload.onprogress = (event) => {
      input.onProgress?.(event.loaded, event.total);
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        settle(() => resolve());
        return;
      }
      settle(() => reject(new ApiClientError("INVALID_API_RESPONSE", {}, true, null)));
    };
    xhr.onerror = () => {
      settle(() => reject(new ApiClientError("NETWORK_ERROR", {}, true, null)));
    };
    xhr.onabort = () => {
      settle(() => reject(abortError()));
    };
    xhr.ontimeout = () => {
      settle(() => reject(new ApiClientError("NETWORK_ERROR", {}, true, null)));
    };

    if (input.signal?.aborted) {
      onAbort();
      return;
    }
    input.signal?.addEventListener("abort", onAbort);
    xhr.send(input.body);
  });
}

export type GetReplayArtifactBlobInput = {
  access: ReplayArtifactAccess;
  accessToken: string;
  kind: ReplayArtifactKind;
  signal?: AbortSignal;
};

export async function getReplayArtifactBlob(input: GetReplayArtifactBlobInput): Promise<Blob> {
  const url = input.access.url.startsWith("/")
    ? `${apiBaseUrl}${input.access.url}`
    : input.access.url;
  const headers: Record<string, string> = {};
  if (input.access.mode === "bearer") {
    headers.Authorization = `Bearer ${input.accessToken}`;
  }

  let response: Response;
  try {
    response = await fetch(url, { headers, signal: input.signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiClientError("NETWORK_ERROR", {}, true, null);
  }

  if (!response.ok) {
    throw new ApiClientError(
      "INVALID_API_RESPONSE",
      {},
      true,
      safeRequestId(response.headers.get("X-Request-ID")),
    );
  }

  const contentType = response.headers.get("Content-Type")?.split(";")[0]?.trim() ?? "";
  const isFrame = input.kind === "anchor_frame" || input.kind === "verification_frame";
  if (isFrame && contentType !== "image/jpeg") {
    throw new ApiClientError(
      "INVALID_API_RESPONSE",
      {},
      true,
      safeRequestId(response.headers.get("X-Request-ID")),
    );
  }

  return response.blob();
}
