import { afterEach, describe, expect, it, vi } from "vitest";

import {
  completeReplay,
  createReplay,
  deleteReplay,
  getReplayArtifactBlob,
  getReplayArtifacts,
  getReplayStatus,
  retryReplay,
  uploadReplayContent,
} from "@/api/client";
import {
  replayArtifactsResponseSchema,
  replayCreateResponseSchema,
  replayStatusResponseSchema,
  type ReplayArtifactsResponse,
  type ReplayCreateResponse,
  type ReplayStatusResponse,
} from "@/api/schemas";

const REPLAY_ID = "11111111-2222-4333-8444-555555555555";
const ARTIFACT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";
const TOKEN = "possession-token-value";
const SAFE_REQUEST_ID = "a3f4c1d2e5b67890a1b2c3d4e5f60718";

function futureIso(msFromNow = 30 * 60 * 1000): string {
  return new Date(Date.now() + msFromNow).toISOString();
}

function validCreateResponse(overrides: Record<string, unknown> = {}) {
  return {
    replay_id: REPLAY_ID,
    access_token: TOKEN,
    status: "created",
    upload: {
      method: "PUT",
      url: `/api/v1/replays/${REPLAY_ID}/content`,
      headers: {},
      expires_at: futureIso(),
    },
    retention: {
      source_hours_after_processing: 24,
      derived_days_after_ready: 7,
    },
    request_id: SAFE_REQUEST_ID,
    ...overrides,
  };
}

function validStatusResponse(overrides: Record<string, unknown> = {}) {
  return {
    replay_id: REPLAY_ID,
    status: "queued",
    processing_stage: null,
    progress_percent: 0,
    normalized_duration_ms: null,
    width: null,
    height: null,
    available_game_time_start_ms: null,
    available_game_time_end_ms: null,
    warning_codes: [],
    error_code: null,
    error_retryable: null,
    source_delete_after: null,
    derived_delete_after: null,
    request_id: SAFE_REQUEST_ID,
    ...overrides,
  };
}

function validArtifactsResponse(overrides: Record<string, unknown> = {}) {
  return {
    artifacts: [
      {
        artifact_id: ARTIFACT_ID,
        replay_id: REPLAY_ID,
        kind: "verification_frame",
        game_time_ms: 0,
        video_time_ms: 48231,
        media_type: "image/jpeg",
        width: 1280,
        height: 720,
        size_bytes: 2048,
        access: {
          mode: "bearer",
          url: `/api/v1/replays/${REPLAY_ID}/artifacts/${ARTIFACT_ID}/content`,
          expires_at: "2026-08-01T15:05:00+00:00",
        },
      },
    ],
    request_id: SAFE_REQUEST_ID,
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("replay schemas", () => {
  it("accepts contracted create/status/artifact responses and sanitizes request_id", () => {
    expect(replayCreateResponseSchema.parse(validCreateResponse()).request_id).toBe(SAFE_REQUEST_ID);
    expect(replayStatusResponseSchema.parse(validStatusResponse()).request_id).toBe(SAFE_REQUEST_ID);
    expect(replayArtifactsResponseSchema.parse(validArtifactsResponse()).request_id).toBe(
      SAFE_REQUEST_ID,
    );

    const unsafe = replayCreateResponseSchema.parse(
      validCreateResponse({ request_id: "123e4567-e89b-12d3-a456-426614174000" }),
    );
    expect(unsafe.request_id).toBeNull();
  });

  it("rejects create/status/artifact responses with uncontracted fields", () => {
    expect(() =>
      replayCreateResponseSchema.parse(validCreateResponse({ selected_puuid: "puuid-1" })),
    ).toThrow();
    expect(() =>
      replayStatusResponseSchema.parse(validStatusResponse({ token_digest: "digest" })),
    ).toThrow();
    expect(() =>
      replayArtifactsResponseSchema.parse(
        validArtifactsResponse({
          artifacts: [
            {
              ...validArtifactsResponse().artifacts[0],
              object_key: "derived/x",
            },
          ],
        }),
      ),
    ).toThrow();
    expect(() =>
      replayCreateResponseSchema.parse(validCreateResponse({ original_filename: "recording.mp4" })),
    ).toThrow();
  });

  it("keeps sensitive fields out of public response types", () => {
    type Forbidden =
      | "selected_puuid"
      | "token_digest"
      | "object_key"
      | "original_filename";

    type CreateKeys = keyof ReplayCreateResponse;
    type StatusKeys = keyof ReplayStatusResponse;
    type ArtifactKeys = keyof ReplayArtifactsResponse["artifacts"][number];

    type CreateLeak = Extract<CreateKeys, Forbidden>;
    type StatusLeak = Extract<StatusKeys, Forbidden>;
    type ArtifactLeak = Extract<ArtifactKeys, Forbidden>;

    const createOk: CreateLeak extends never ? true : false = true;
    const statusOk: StatusLeak extends never ? true : false = true;
    const artifactOk: ArtifactLeak extends never ? true : false = true;

    expect(createOk).toBe(true);
    expect(statusOk).toBe(true);
    expect(artifactOk).toBe(true);

    const access = validArtifactsResponse().artifacts[0].access;
    expect(access).toEqual(
      expect.objectContaining({
        mode: expect.stringMatching(/^(bearer|presigned)$/),
        url: expect.any(String),
        expires_at: expect.any(String),
      }),
    );
  });
});

describe("replay API client", () => {
  it("creates a replay with a JSON body and no authorization header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(validCreateResponse()), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await createReplay({
      matchId: "NA1_1234567890",
      platform: "NA1",
      puuid: "selected-player-puuid",
      originalFilename: "recording.mp4",
      declaredSizeBytes: 1_000_000,
      declaredContentType: "video/mp4",
      gameTimeZeroMs: 48231,
      rightsAttested: true,
      rightsStatementVersion: "2026-08-01",
    });

    expect(result.replay_id).toBe(REPLAY_ID);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/replays"),
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Accept: "application/json" }),
        body: JSON.stringify({
          match_id: "NA1_1234567890",
          platform: "NA1",
          puuid: "selected-player-puuid",
          original_filename: "recording.mp4",
          declared_size_bytes: 1_000_000,
          declared_content_type: "video/mp4",
          game_time_zero_ms: 48231,
          rights_attested: true,
          rights_statement_version: "2026-08-01",
        }),
      }),
    );
    const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });

  it("sends the possession token only as an Authorization bearer header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(validStatusResponse()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await completeReplay({ replayId: REPLAY_ID, accessToken: TOKEN });

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(`/api/v1/replays/${REPLAY_ID}/complete`),
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Authorization: `Bearer ${TOKEN}` }),
      }),
    );
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).not.toContain(TOKEN);
    expect((init.headers as Record<string, string>).Authorization).toBe(`Bearer ${TOKEN}`);
  });

  it("reads status, artifacts, retry, and delete with bearer auth", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(validStatusResponse()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(validArtifactsResponse()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(validStatusResponse({ status: "queued" })), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(validStatusResponse({ status: "deleting" })), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await getReplayStatus({ replayId: REPLAY_ID, accessToken: TOKEN });
    await getReplayArtifacts({ replayId: REPLAY_ID, accessToken: TOKEN });
    await retryReplay({ replayId: REPLAY_ID, accessToken: TOKEN });
    await deleteReplay({ replayId: REPLAY_ID, accessToken: TOKEN });

    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: "GET",
      headers: expect.objectContaining({ Authorization: `Bearer ${TOKEN}` }),
    });
    expect(fetchMock.mock.calls[1][0]).toContain(`/api/v1/replays/${REPLAY_ID}/artifacts`);
    expect(fetchMock.mock.calls[2][1]).toMatchObject({ method: "POST" });
    expect(fetchMock.mock.calls[3][1]).toMatchObject({ method: "DELETE" });
  });

  it("reports XHR upload progress and aborts with AbortError", async () => {
    const progress = vi.fn();
    const setRequestHeader = vi.fn();
    let loadHandler: (() => void) | null = null;
    let uploadProgressHandler: ((event: { loaded: number; total: number }) => void) | null = null;

    class ProgressXHR {
      upload = {
        set onprogress(handler: ((event: { loaded: number; total: number }) => void) | null) {
          uploadProgressHandler = handler;
        },
      };
      status = 204;
      open = vi.fn();
      send = vi.fn(() => {
        uploadProgressHandler?.({ loaded: 50, total: 100 });
        loadHandler?.();
      });
      abort = vi.fn();
      setRequestHeader = setRequestHeader;
      set onload(handler: (() => void) | null) {
        loadHandler = handler;
      }
      set onabort(_handler: (() => void) | null) {}
      set onerror(_handler: (() => void) | null) {}
      set ontimeout(_handler: (() => void) | null) {}
    }

    vi.stubGlobal(
      "XMLHttpRequest",
      vi.fn(() => new ProgressXHR()) as unknown as typeof XMLHttpRequest,
    );

    await uploadReplayContent({
      upload: {
        method: "PUT",
        url: `/api/v1/replays/${REPLAY_ID}/content`,
        headers: { "Content-Type": "video/mp4" },
        expires_at: futureIso(),
      },
      accessToken: TOKEN,
      body: new Blob(["abc"]),
      onProgress: progress,
    });

    expect(progress).toHaveBeenCalledWith(50, 100);
    expect(setRequestHeader).toHaveBeenCalledWith("Authorization", `Bearer ${TOKEN}`);
    expect(setRequestHeader).toHaveBeenCalledWith("Content-Type", "video/mp4");

    let abortHandler: (() => void) | null = null;
    const abort = vi.fn(() => {
      abortHandler?.();
    });

    class WaitingXHR {
      upload = { onprogress: null };
      status = 0;
      open = vi.fn();
      send = vi.fn();
      abort = abort;
      setRequestHeader = vi.fn();
      set onload(_handler: (() => void) | null) {}
      set onabort(handler: (() => void) | null) {
        abortHandler = handler;
      }
      set onerror(_handler: (() => void) | null) {}
      set ontimeout(_handler: (() => void) | null) {}
    }

    vi.stubGlobal(
      "XMLHttpRequest",
      vi.fn(() => new WaitingXHR()) as unknown as typeof XMLHttpRequest,
    );

    const controller = new AbortController();
    const waiting = uploadReplayContent({
      upload: {
        method: "PUT",
        url: `/api/v1/replays/${REPLAY_ID}/content`,
        headers: {},
        expires_at: futureIso(),
      },
      accessToken: TOKEN,
      body: new Blob(["abc"]),
      signal: controller.signal,
    });
    controller.abort();
    await expect(waiting).rejects.toMatchObject({ name: "AbortError" });
    expect(abort).toHaveBeenCalled();
  });

  it("uses returned headers only for absolute S3 upload URLs", async () => {
    const setRequestHeader = vi.fn();
    let loadHandler: (() => void) | null = null;

    class FakeXHR {
      upload = { onprogress: null as ((event: { loaded: number; total: number }) => void) | null };
      status = 200;
      open = vi.fn();
      send = vi.fn(() => loadHandler?.());
      abort = vi.fn();
      setRequestHeader = setRequestHeader;
      set onload(handler: (() => void) | null) {
        loadHandler = handler;
      }
      set onabort(_handler: (() => void) | null) {}
      set onerror(_handler: (() => void) | null) {}
      set ontimeout(_handler: (() => void) | null) {}
    }

    vi.stubGlobal(
      "XMLHttpRequest",
      vi.fn(() => new FakeXHR()) as unknown as typeof XMLHttpRequest,
    );

    await uploadReplayContent({
      upload: {
        method: "PUT",
        url: "https://s3.example/bucket/object?X-Amz-Signature=abc",
        headers: { "Content-Type": "video/mp4", "x-amz-acl": "private" },
        expires_at: futureIso(),
      },
      accessToken: TOKEN,
      body: new Blob(["abc"]),
    });

    expect(setRequestHeader).toHaveBeenCalledWith("Content-Type", "video/mp4");
    expect(setRequestHeader).toHaveBeenCalledWith("x-amz-acl", "private");
    expect(setRequestHeader).not.toHaveBeenCalledWith("Authorization", expect.anything());
  });

  it("rejects a local upload without sending bytes when expires_at has already passed", async () => {
    const xhrCtor = vi.fn();
    vi.stubGlobal("XMLHttpRequest", xhrCtor as unknown as typeof XMLHttpRequest);

    await expect(
      uploadReplayContent({
        upload: {
          method: "PUT",
          url: `/api/v1/replays/${REPLAY_ID}/content`,
          headers: {},
          expires_at: new Date(Date.now() - 60_000).toISOString(),
        },
        accessToken: TOKEN,
        body: new Blob(["abc"]),
      }),
    ).rejects.toMatchObject({ code: "REPLAY_UPLOAD_EXPIRED" });

    expect(xhrCtor).not.toHaveBeenCalled();
  });

  it("rejects a local upload within the clock-skew window before expiry, without sending bytes", async () => {
    const xhrCtor = vi.fn();
    vi.stubGlobal("XMLHttpRequest", xhrCtor as unknown as typeof XMLHttpRequest);

    await expect(
      uploadReplayContent({
        upload: {
          method: "PUT",
          url: `/api/v1/replays/${REPLAY_ID}/content`,
          headers: {},
          expires_at: new Date(Date.now() + 1_000).toISOString(),
        },
        accessToken: TOKEN,
        body: new Blob(["abc"]),
      }),
    ).rejects.toMatchObject({ code: "REPLAY_UPLOAD_EXPIRED" });

    expect(xhrCtor).not.toHaveBeenCalled();
  });

  it("still starts a local upload once comfortably before expiry", async () => {
    let loadHandler: (() => void) | null = null;
    class OkXHR {
      upload = { onprogress: null };
      status = 204;
      open = vi.fn();
      send = vi.fn(() => loadHandler?.());
      abort = vi.fn();
      setRequestHeader = vi.fn();
      set onload(handler: (() => void) | null) {
        loadHandler = handler;
      }
      set onabort(_handler: (() => void) | null) {}
      set onerror(_handler: (() => void) | null) {}
      set ontimeout(_handler: (() => void) | null) {}
    }
    vi.stubGlobal("XMLHttpRequest", vi.fn(() => new OkXHR()) as unknown as typeof XMLHttpRequest);

    await expect(
      uploadReplayContent({
        upload: {
          method: "PUT",
          url: `/api/v1/replays/${REPLAY_ID}/content`,
          headers: {},
          expires_at: futureIso(),
        },
        accessToken: TOKEN,
        body: new Blob(["abc"]),
      }),
    ).resolves.toBeUndefined();
  });

  it("does not require a fresh expiry for absolute (presigned) upload URLs", async () => {
    let loadHandler: (() => void) | null = null;
    class OkXHR {
      upload = { onprogress: null };
      status = 200;
      open = vi.fn();
      send = vi.fn(() => loadHandler?.());
      abort = vi.fn();
      setRequestHeader = vi.fn();
      set onload(handler: (() => void) | null) {
        loadHandler = handler;
      }
      set onabort(_handler: (() => void) | null) {}
      set onerror(_handler: (() => void) | null) {}
      set ontimeout(_handler: (() => void) | null) {}
    }
    vi.stubGlobal("XMLHttpRequest", vi.fn(() => new OkXHR()) as unknown as typeof XMLHttpRequest);

    await expect(
      uploadReplayContent({
        upload: {
          method: "PUT",
          url: "https://s3.example/bucket/object?X-Amz-Signature=abc",
          headers: {},
          expires_at: new Date(Date.now() - 60_000).toISOString(),
        },
        accessToken: TOKEN,
        body: new Blob(["abc"]),
      }),
    ).resolves.toBeUndefined();
  });

  it("fetches bearer artifact blobs and rejects non-jpeg frames", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(new Uint8Array([1, 2, 3]), {
          status: 200,
          headers: { "Content-Type": "image/jpeg" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(new Uint8Array([1, 2, 3]), {
          status: 200,
          headers: { "Content-Type": "image/png" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const blob = await getReplayArtifactBlob({
      access: {
        mode: "bearer",
        url: `/api/v1/replays/${REPLAY_ID}/artifacts/${ARTIFACT_ID}/content`,
        expires_at: "2026-08-01T15:05:00+00:00",
      },
      accessToken: TOKEN,
      kind: "verification_frame",
    });
    expect(blob.type).toBe("image/jpeg");
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(`/api/v1/replays/${REPLAY_ID}/artifacts/${ARTIFACT_ID}/content`),
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: `Bearer ${TOKEN}` }),
      }),
    );

    await expect(
      getReplayArtifactBlob({
        access: {
          mode: "bearer",
          url: `/api/v1/replays/${REPLAY_ID}/artifacts/${ARTIFACT_ID}/content`,
          expires_at: "2026-08-01T15:05:00+00:00",
        },
        accessToken: TOKEN,
        kind: "anchor_frame",
      }),
    ).rejects.toMatchObject({ code: "INVALID_API_RESPONSE" });
  });

  it("maps replay API errors through errorResponseSchema without leaking the token", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "REPLAY_NOT_FOUND",
              message: "The requested replay was not found.",
              params: {},
              retryable: false,
              request_id: SAFE_REQUEST_ID,
            },
          }),
          { status: 404, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(getReplayStatus({ replayId: REPLAY_ID, accessToken: TOKEN })).rejects.toMatchObject(
      {
        code: "REPLAY_NOT_FOUND",
        requestId: SAFE_REQUEST_ID,
      },
    );

    try {
      await getReplayStatus({ replayId: REPLAY_ID, accessToken: TOKEN });
    } catch (error) {
      expect(String(error)).not.toContain(TOKEN);
      expect(JSON.stringify(error)).not.toContain(TOKEN);
    }
  });
});
