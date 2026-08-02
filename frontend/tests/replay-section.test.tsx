import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const {
  createReplayMock,
  uploadReplayContentMock,
  completeReplayMock,
  getReplayStatusMock,
  getReplayArtifactsMock,
  getReplayArtifactBlobMock,
  retryReplayMock,
  deleteReplayMock,
} = vi.hoisted(() => ({
  createReplayMock: vi.fn(),
  uploadReplayContentMock: vi.fn(),
  completeReplayMock: vi.fn(),
  getReplayStatusMock: vi.fn(),
  getReplayArtifactsMock: vi.fn(),
  getReplayArtifactBlobMock: vi.fn(),
  retryReplayMock: vi.fn(),
  deleteReplayMock: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  createReplay: createReplayMock,
  uploadReplayContent: uploadReplayContentMock,
  completeReplay: completeReplayMock,
  getReplayStatus: getReplayStatusMock,
  getReplayArtifacts: getReplayArtifactsMock,
  getReplayArtifactBlob: getReplayArtifactBlobMock,
  retryReplay: retryReplayMock,
  deleteReplay: deleteReplayMock,
  ApiClientError: class ApiClientError extends Error {
    constructor(
      readonly code: string,
      readonly params: Record<string, unknown>,
      readonly retryable: boolean,
      readonly requestId: string | null,
    ) {
      super(code);
      this.name = "ApiClientError";
    }
  },
}));

import { ApiClientError } from "@/api/client";
import type { ReplayArtifactsResponse, ReplayStatusResponse } from "@/api/schemas";
import { nextPollBackoffMs, ReplaySection } from "@/components/replay-section";
import { getMessages } from "@/i18n/messages";
import {
  loadReplayCapability,
  removeReplayCapability,
  saveReplayCapability,
} from "@/replays/storage";

const REPLAY_ID = "11111111-2222-4333-8444-555555555555";
const ARTIFACT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";
const ARTIFACT_ID_2 = "bbbbbbbb-bbbb-4ccc-8ddd-eeeeeeeeeeee";
const TOKEN = "possession-token-value";
const MATCH_ID = "NA1_123456789";
const SAFE_REQUEST_ID = "a3f4c1d2e5b67890a1b2c3d4e5f60718";

function installMemoryLocalStorage() {
  const store = new Map<string, string>();
  const memoryStorage = {
    get length() {
      return store.size;
    },
    clear() {
      store.clear();
    },
    getItem(key: string) {
      return store.has(key) ? store.get(key)! : null;
    },
    key(index: number) {
      return [...store.keys()][index] ?? null;
    },
    removeItem(key: string) {
      store.delete(key);
    },
    setItem(key: string, value: string) {
      store.set(key, String(value));
    },
  };
  vi.stubGlobal("localStorage", memoryStorage);
  return memoryStorage;
}

function statusResponse(overrides: Partial<ReplayStatusResponse> = {}): ReplayStatusResponse {
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

function artifactsResponse(
  overrides: Partial<ReplayArtifactsResponse> = {},
): ReplayArtifactsResponse {
  return {
    artifacts: [
      {
        artifact_id: ARTIFACT_ID_2,
        replay_id: REPLAY_ID,
        kind: "verification_frame",
        game_time_ms: 60000,
        video_time_ms: 108231,
        media_type: "image/jpeg",
        width: 1280,
        height: 720,
        size_bytes: 2048,
        access: {
          mode: "bearer",
          url: `/api/v1/replays/${REPLAY_ID}/artifacts/${ARTIFACT_ID_2}/content`,
          expires_at: "2026-08-01T15:05:00+00:00",
        },
      },
      {
        artifact_id: ARTIFACT_ID,
        replay_id: REPLAY_ID,
        kind: "anchor_frame",
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

function renderSection(locale: "en-US" | "zh-CN" = "en-US") {
  return render(
    <ReplaySection
      locale={locale}
      matchId={MATCH_ID}
      puuid="selected-puuid"
      platform="NA1"
      matchDurationSeconds={1800}
    />,
  );
}

async function selectValidFile(user: ReturnType<typeof userEvent.setup>) {
  const file = new File(["video-bytes"], "recording.mp4", { type: "video/mp4" });
  const input = screen.getByLabelText(getMessages("en-US").replayFileLabel);
  await user.upload(input, file);
  return file;
}

async function selectFile(user: ReturnType<typeof userEvent.setup>, file: File) {
  const input = screen.getByLabelText(getMessages("en-US").replayFileLabel);
  await user.upload(input, file);
  return file;
}

beforeEach(() => {
  installMemoryLocalStorage();
  vi.stubGlobal(
    "URL",
    class {
      static createObjectURL = vi.fn(() => "blob:preview-1");
      static revokeObjectURL = vi.fn();
    },
  );
  Object.defineProperty(HTMLMediaElement.prototype, "currentTime", {
    configurable: true,
    get(this: HTMLMediaElement & { _ct?: number }) {
      return this._ct ?? 0;
    },
    set(this: HTMLMediaElement & { _ct?: number }, value: number) {
      this._ct = value;
    },
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("ReplaySection upload gating and anchor", () => {
  it("keeps upload disabled until file, game zero anchor, and rights are set", async () => {
    const user = userEvent.setup();
    const messages = getMessages("en-US");
    renderSection();

    expect(screen.getByText(messages.replayNoAiNotice)).toBeVisible();
    const uploadButton = screen.getByRole("button", { name: messages.replayUpload });
    expect(uploadButton).toBeDisabled();

    await selectValidFile(user);
    expect(screen.getByTestId("replay-video-preview")).toBeInTheDocument();
    expect(uploadButton).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: messages.replayRightsLabel }));
    expect(uploadButton).toBeDisabled();

    const video = screen.getByTestId("replay-video-preview") as HTMLVideoElement;
    video.currentTime = 48.231;
    await user.click(screen.getByRole("button", { name: messages.replaySetGameZero }));
    expect(uploadButton).toBeEnabled();

    createReplayMock.mockResolvedValue({
      replay_id: REPLAY_ID,
      access_token: TOKEN,
      status: "created",
      upload: {
        method: "PUT",
        url: `/api/v1/replays/${REPLAY_ID}/content`,
        headers: {},
        expires_at: "2026-08-01T15:30:00+00:00",
      },
      retention: { source_hours_after_processing: 24, derived_days_after_ready: 7 },
      request_id: SAFE_REQUEST_ID,
    });
    uploadReplayContentMock.mockResolvedValue(undefined);
    completeReplayMock.mockResolvedValue(statusResponse({ status: "queued" }));
    getReplayStatusMock.mockResolvedValue(statusResponse({ status: "queued" }));

    await user.click(uploadButton);

    await waitFor(() => {
      expect(createReplayMock).toHaveBeenCalledWith(
        expect.objectContaining({
          matchId: MATCH_ID,
          puuid: "selected-puuid",
          platform: "NA1",
          gameTimeZeroMs: 48231,
          rightsAttested: true,
          rightsStatementVersion: "2026-08-01",
          originalFilename: "recording.mp4",
          declaredContentType: "video/mp4",
        }),
        expect.any(AbortSignal),
      );
    });
  });
});

describe("ReplaySection upload expiry handling", () => {
  it("shows the expired-upload error and returns to the upload form when the upload target already expired", async () => {
    const user = userEvent.setup();
    const messages = getMessages("en-US");
    renderSection();

    await selectValidFile(user);
    const video = screen.getByTestId("replay-video-preview") as HTMLVideoElement;
    video.currentTime = 12;
    await user.click(screen.getByRole("button", { name: messages.replaySetGameZero }));
    await user.click(screen.getByRole("checkbox", { name: messages.replayRightsLabel }));

    createReplayMock.mockResolvedValue({
      replay_id: REPLAY_ID,
      access_token: TOKEN,
      status: "created",
      upload: {
        method: "PUT",
        url: `/api/v1/replays/${REPLAY_ID}/content`,
        headers: {},
        expires_at: "2020-01-01T00:00:00+00:00",
      },
      retention: { source_hours_after_processing: 24, derived_days_after_ready: 7 },
      request_id: SAFE_REQUEST_ID,
    });
    uploadReplayContentMock.mockRejectedValue(
      new ApiClientError("REPLAY_UPLOAD_EXPIRED", {}, false, null),
    );
    // The recovered capability's own status effect fires once uploading stops;
    // keep it pending so it doesn't interfere with this test's assertions.
    getReplayStatusMock.mockImplementation(() => new Promise(() => {}));

    await user.click(screen.getByRole("button", { name: messages.replayUpload }));

    expect(await screen.findByRole("alert")).toHaveTextContent(messages.replayUploadExpired);
    expect(completeReplayMock).not.toHaveBeenCalled();
    expect(await screen.findByRole("button", { name: messages.replayUpload })).toBeInTheDocument();
  });
});

describe("ReplaySection file type validation", () => {
  it("accepts an .mkv file with a video/x-matroska MIME type", async () => {
    const user = userEvent.setup();
    const messages = getMessages("en-US");
    renderSection();

    await selectFile(
      user,
      new File(["video-bytes"], "recording.mkv", { type: "video/x-matroska" }),
    );

    expect(screen.getByTestId("replay-video-preview")).toBeInTheDocument();
    expect(screen.queryByText(messages.replayFileInvalidType)).not.toBeInTheDocument();
  });

  it("accepts a video file reported with an application/octet-stream MIME type", async () => {
    const user = userEvent.setup();
    const messages = getMessages("en-US");
    renderSection();

    await selectFile(
      user,
      new File(["video-bytes"], "recording.mkv", { type: "application/octet-stream" }),
    );

    expect(screen.getByTestId("replay-video-preview")).toBeInTheDocument();
    expect(screen.queryByText(messages.replayFileInvalidType)).not.toBeInTheDocument();
  });

  it("still rejects unsupported file extensions", async () => {
    // Bypass the input's native accept-attribute filtering so we can exercise the
    // component's own validation, mirroring browsers that still allow "all files".
    const user = userEvent.setup({ applyAccept: false });
    const messages = getMessages("en-US");
    renderSection();

    await selectFile(user, new File(["text-bytes"], "notes.txt", { type: "text/plain" }));

    expect(screen.getByText(messages.replayFileInvalidType)).toBeVisible();
    expect(screen.queryByTestId("replay-video-preview")).not.toBeInTheDocument();
  });
});

describe("ReplaySection upload polling and refresh recovery", () => {
  it("shows create → upload progress → complete → queued → processing → ready", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const messages = getMessages("en-US");
    renderSection();

    createReplayMock.mockResolvedValue({
      replay_id: REPLAY_ID,
      access_token: TOKEN,
      status: "created",
      upload: {
        method: "PUT",
        url: `/api/v1/replays/${REPLAY_ID}/content`,
        headers: {},
        expires_at: "2026-08-01T15:30:00+00:00",
      },
      retention: { source_hours_after_processing: 24, derived_days_after_ready: 7 },
      request_id: SAFE_REQUEST_ID,
    });

    let finishUpload: (() => void) | undefined;
    uploadReplayContentMock.mockImplementation(async (input) => {
      input.onProgress?.(50, 100);
      await new Promise<void>((resolve) => {
        finishUpload = resolve;
      });
      input.onProgress?.(100, 100);
    });
    completeReplayMock.mockResolvedValue(statusResponse({ status: "queued", progress_percent: 5 }));

    let statusCalls = 0;
    getReplayStatusMock.mockImplementation(async () => {
      statusCalls += 1;
      if (statusCalls === 1) {
        return statusResponse({
          status: "transcoding",
          progress_percent: 40,
          processing_stage: "transcoding",
        });
      }
      return statusResponse({
        status: "ready",
        progress_percent: 100,
        processing_stage: null,
        available_game_time_start_ms: 0,
        available_game_time_end_ms: 1_800_000,
        derived_delete_after: "2026-08-08T15:00:00+00:00",
      });
    });
    getReplayArtifactsMock.mockResolvedValue(artifactsResponse());
    getReplayArtifactBlobMock.mockResolvedValue(new Blob(["jpeg"], { type: "image/jpeg" }));

    await selectValidFile(user);
    const video = screen.getByTestId("replay-video-preview") as HTMLVideoElement;
    video.currentTime = 12;
    await user.click(screen.getByRole("button", { name: messages.replaySetGameZero }));
    await user.click(screen.getByRole("checkbox", { name: messages.replayRightsLabel }));
    await user.click(screen.getByRole("button", { name: messages.replayUpload }));

    expect(await screen.findByRole("progressbar")).toHaveAttribute("aria-valuenow", "50");
    expect(screen.getByText(messages.replayStageUploading)).toBeVisible();

    finishUpload?.();
    await waitFor(() => expect(completeReplayMock).toHaveBeenCalled());
    expect(await screen.findByText(messages.replayStageQueued)).toBeVisible();

    await vi.advanceTimersByTimeAsync(2000);
    await waitFor(() => expect(screen.getByText(messages.replayStageTranscoding)).toBeVisible());
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "40");

    await vi.advanceTimersByTimeAsync(2000);
    await waitFor(() => expect(screen.getByText(messages.replayStageReady)).toBeVisible());
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
    expect(getReplayArtifactsMock).toHaveBeenCalled();
    expect(createReplayMock).toHaveBeenCalledTimes(1);
  });

  it("recovers from a saved capability without recreating", async () => {
    const messages = getMessages("en-US");
    saveReplayCapability({
      replayId: REPLAY_ID,
      accessToken: TOKEN,
      matchId: MATCH_ID,
      updatedAt: "2026-08-01T15:00:00.000Z",
    });
    getReplayStatusMock.mockResolvedValue(
      statusResponse({
        status: "ready",
        progress_percent: 100,
        available_game_time_start_ms: 0,
        available_game_time_end_ms: 1_800_000,
      }),
    );
    getReplayArtifactsMock.mockResolvedValue(artifactsResponse());
    getReplayArtifactBlobMock.mockResolvedValue(new Blob(["jpeg"], { type: "image/jpeg" }));

    renderSection();

    expect(await screen.findByText(messages.replayStageReady)).toBeVisible();
    expect(createReplayMock).not.toHaveBeenCalled();
    expect(getReplayStatusMock).toHaveBeenCalledWith(
      { replayId: REPLAY_ID, accessToken: TOKEN },
      expect.any(AbortSignal),
    );
    expect(screen.queryByTestId("replay-video-preview")).not.toBeInTheDocument();
  });

  it("keeps polling through repeated network errors with a capped exponential backoff, then recovers", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const messages = getMessages("en-US");
    saveReplayCapability({
      replayId: REPLAY_ID,
      accessToken: TOKEN,
      matchId: MATCH_ID,
      updatedAt: "2026-08-01T15:00:00.000Z",
    });

    let call = 0;
    getReplayStatusMock.mockImplementation(async () => {
      call += 1;
      if (call === 1) {
        return statusResponse({ status: "transcoding", progress_percent: 10 });
      }
      if (call <= 6) {
        throw new ApiClientError("NETWORK_ERROR", {}, true, null);
      }
      return statusResponse({
        status: "ready",
        progress_percent: 100,
        available_game_time_start_ms: 0,
        available_game_time_end_ms: 1_800_000,
      });
    });
    getReplayArtifactsMock.mockResolvedValue(artifactsResponse());
    getReplayArtifactBlobMock.mockResolvedValue(new Blob(["jpeg"], { type: "image/jpeg" }));

    renderSection();

    // Initial one-shot status load (call 1) resolves with a non-terminal status.
    await waitFor(() => expect(getReplayStatusMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText(messages.replayStageTranscoding)).toBeVisible());

    // First poll attempt fires at the normal active interval (2s) and fails.
    await vi.advanceTimersByTimeAsync(2000);
    await waitFor(() => expect(getReplayStatusMock).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("alert")).toHaveTextContent(messages.replayNetworkError);
    // Polling did not stop: the last known status stays visible instead of the
    // error message replacing the whole panel.
    expect(screen.getByText(messages.replayStageTranscoding)).toBeVisible();

    // Backoff schedule: 2s, 4s, 8s, 16s, then capped at 30s. Each step uses the
    // exact nominal delay (matching this suite's existing fake-timer pattern)
    // rather than a razor's-edge boundary check, since waitFor's internal fake
    // timer flushing can add a small amount of drift between assertions.
    const expectedDelays = [2000, 4000, 8000, 16000, 30000];
    for (const [index, delayMs] of expectedDelays.entries()) {
      const expectedCallCount = index + 3;
      await vi.advanceTimersByTimeAsync(delayMs);
      await waitFor(() => expect(getReplayStatusMock).toHaveBeenCalledTimes(expectedCallCount));
    }

    await waitFor(() => expect(screen.getByText(messages.replayStageReady)).toBeVisible());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("recovers from a network error while the tab is hidden", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const messages = getMessages("en-US");
    saveReplayCapability({
      replayId: REPLAY_ID,
      accessToken: TOKEN,
      matchId: MATCH_ID,
      updatedAt: "2026-08-01T15:00:00.000Z",
    });
    Object.defineProperty(document, "hidden", { configurable: true, value: true });

    let call = 0;
    getReplayStatusMock.mockImplementation(async () => {
      call += 1;
      if (call === 1) {
        return statusResponse({ status: "transcoding", progress_percent: 10 });
      }
      if (call === 2) {
        throw new ApiClientError("NETWORK_ERROR", {}, true, null);
      }
      return statusResponse({ status: "transcoding", progress_percent: 20 });
    });

    try {
      renderSection();
      await waitFor(() => expect(getReplayStatusMock).toHaveBeenCalledTimes(1));

      // Hidden-tab polling interval (10s) before the first failure.
      await vi.advanceTimersByTimeAsync(10000);
      await waitFor(() => expect(getReplayStatusMock).toHaveBeenCalledTimes(2));
      expect(await screen.findByRole("alert")).toHaveTextContent(messages.replayNetworkError);

      // Retries continue (using the hidden-tab base delay under the hood; the
      // exact schedule is covered by the nextPollBackoffMs unit tests below).
      await vi.advanceTimersByTimeAsync(10000);
      await waitFor(() => expect(getReplayStatusMock).toHaveBeenCalledTimes(3));
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    } finally {
      Object.defineProperty(document, "hidden", { configurable: true, value: false });
    }
  });
});

describe("nextPollBackoffMs", () => {
  it("doubles from a 2s base and caps at 30s while the tab is visible", () => {
    let backoff = 0;
    for (const expected of [2000, 4000, 8000, 16000, 30000, 30000]) {
      backoff = nextPollBackoffMs(backoff, false);
      expect(backoff).toBe(expected);
    }
  });

  it("uses a 10s base while hidden and still caps at 30s", () => {
    let backoff = 0;
    for (const expected of [10000, 20000, 30000, 30000]) {
      backoff = nextPollBackoffMs(backoff, true);
      expect(backoff).toBe(expected);
    }
  });

  it("resets to the base delay after a successful poll (backoff of 0)", () => {
    expect(nextPollBackoffMs(0, false)).toBe(2000);
    expect(nextPollBackoffMs(0, true)).toBe(10000);
  });
});

describe("ReplaySection status, delete, and token errors", () => {
  it("shows partial coverage warning when ready coverage is incomplete", async () => {
    const messages = getMessages("en-US");
    saveReplayCapability({
      replayId: REPLAY_ID,
      accessToken: TOKEN,
      matchId: MATCH_ID,
      updatedAt: "2026-08-01T15:00:00.000Z",
    });
    getReplayStatusMock.mockResolvedValue(
      statusResponse({
        status: "ready",
        progress_percent: 100,
        warning_codes: ["partial_coverage"],
        available_game_time_start_ms: 0,
        available_game_time_end_ms: 900_000,
      }),
    );
    getReplayArtifactsMock.mockResolvedValue(artifactsResponse());
    getReplayArtifactBlobMock.mockResolvedValue(new Blob(["jpeg"], { type: "image/jpeg" }));

    renderSection();
    expect(await screen.findByText(messages.replayPartialCoverage)).toBeVisible();
  });

  it("shows retry only for retryable failures", async () => {
    const messages = getMessages("en-US");
    saveReplayCapability({
      replayId: REPLAY_ID,
      accessToken: TOKEN,
      matchId: MATCH_ID,
      updatedAt: "2026-08-01T15:00:00.000Z",
    });
    getReplayStatusMock.mockResolvedValue(
      statusResponse({
        status: "failed",
        progress_percent: 40,
        error_code: "REPLAY_STORAGE_UNAVAILABLE",
        error_retryable: true,
      }),
    );

    renderSection();
    expect(await screen.findByRole("button", { name: messages.replayRetry })).toBeVisible();

    cleanup();
    getReplayStatusMock.mockResolvedValue(
      statusResponse({
        status: "failed",
        progress_percent: 40,
        error_code: "REPLAY_MEDIA_UNSUPPORTED",
        error_retryable: false,
      }),
    );
    renderSection();
    expect(await screen.findByText(messages.replayStageFailed)).toBeVisible();
    expect(screen.queryByRole("button", { name: messages.replayRetry })).not.toBeInTheDocument();
  });

  it("clears capability when the replay is expired", async () => {
    saveReplayCapability({
      replayId: REPLAY_ID,
      accessToken: TOKEN,
      matchId: MATCH_ID,
      updatedAt: "2026-08-01T15:00:00.000Z",
    });
    getReplayStatusMock.mockResolvedValue(statusResponse({ status: "expired", progress_percent: 0 }));

    renderSection();
    await waitFor(() => {
      expect(loadReplayCapability(REPLAY_ID)).toBeNull();
    });
  });

  it("confirms delete then clears capability", async () => {
    const user = userEvent.setup();
    const messages = getMessages("en-US");
    saveReplayCapability({
      replayId: REPLAY_ID,
      accessToken: TOKEN,
      matchId: MATCH_ID,
      updatedAt: "2026-08-01T15:00:00.000Z",
    });
    getReplayStatusMock.mockResolvedValue(
      statusResponse({
        status: "ready",
        progress_percent: 100,
        available_game_time_start_ms: 0,
        available_game_time_end_ms: 1_800_000,
      }),
    );
    getReplayArtifactsMock.mockResolvedValue(artifactsResponse());
    getReplayArtifactBlobMock.mockResolvedValue(new Blob(["jpeg"], { type: "image/jpeg" }));
    deleteReplayMock.mockResolvedValue(statusResponse({ status: "deleted" }));
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    renderSection();
    expect(await screen.findByText(messages.replayStageReady)).toBeVisible();
    await user.click(screen.getByRole("button", { name: messages.replayDelete }));
    expect(confirmSpy).toHaveBeenCalled();
    await waitFor(() => {
      expect(deleteReplayMock).toHaveBeenCalledWith(
        { replayId: REPLAY_ID, accessToken: TOKEN },
        expect.any(AbortSignal),
      );
      expect(loadReplayCapability(REPLAY_ID)).toBeNull();
    });
    confirmSpy.mockRestore();
  });

  it("shows localized not-found copy for a wrong token and clears capability", async () => {
    const zh = getMessages("zh-CN");
    saveReplayCapability({
      replayId: REPLAY_ID,
      accessToken: "bad-token",
      matchId: MATCH_ID,
      updatedAt: "2026-08-01T15:00:00.000Z",
    });
    getReplayStatusMock.mockRejectedValue(
      new ApiClientError("REPLAY_NOT_FOUND", {}, false, SAFE_REQUEST_ID),
    );

    renderSection("zh-CN");
    expect(await screen.findByRole("alert")).toHaveTextContent(zh.replayNotFound);
    await waitFor(() => {
      expect(loadReplayCapability(REPLAY_ID)).toBeNull();
    });
  });
});

describe("ReplaySection accessibility and bilingual copy", () => {
  it("exposes checkbox, live region, alerts, progress, alts, and no-AI notice", async () => {
    const user = userEvent.setup();
    const en = getMessages("en-US");
    const zh = getMessages("zh-CN");

    expect(Object.keys(en).sort()).toEqual(Object.keys(zh).sort());
    for (const key of [
      "uploadReplay",
      "replayNoAiNotice",
      "replayRightsLabel",
      "replaySetGameZero",
      "replayUpload",
      "replayStageUploading",
      "replayStageQueued",
      "replayStageReady",
      "replayPartialCoverage",
      "replayNotFound",
      "verificationFrame",
      "verificationFrameAlt",
      "anchorFrame",
      "anchorFrameAlt",
    ] as const) {
      expect(en[key].length).toBeGreaterThan(0);
      expect(zh[key].length).toBeGreaterThan(0);
    }
    expect(zh.verificationFrame).toBe("验证帧");
    expect(en.verificationFrame).toBe("Verification frame");
    expect(zh.replayNotFound).toBe("回放不存在或访问已失效");

    renderSection("en-US");
    expect(screen.getByText(en.replayNoAiNotice)).toBeVisible();

    const checkbox = screen.getByRole("checkbox", { name: en.replayRightsLabel });
    expect(checkbox).not.toBeChecked();
    await user.click(screen.getByText(en.replayRightsLabel));
    expect(checkbox).toBeChecked();

    saveReplayCapability({
      replayId: REPLAY_ID,
      accessToken: TOKEN,
      matchId: MATCH_ID,
      updatedAt: "2026-08-01T15:00:00.000Z",
    });
    getReplayStatusMock.mockResolvedValue(
      statusResponse({
        status: "probing",
        progress_percent: 12,
        processing_stage: "probing",
      }),
    );
    cleanup();
    renderSection("en-US");

    const live = await screen.findByRole("status");
    expect(live).toHaveAttribute("aria-live", "polite");
    expect(live).toHaveTextContent(en.replayStageProbing);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "12");

    getReplayStatusMock.mockResolvedValue(
      statusResponse({
        status: "ready",
        progress_percent: 100,
        available_game_time_start_ms: 0,
        available_game_time_end_ms: 1_800_000,
      }),
    );
    getReplayArtifactsMock.mockResolvedValue(artifactsResponse());
    getReplayArtifactBlobMock.mockResolvedValue(new Blob(["jpeg"], { type: "image/jpeg" }));
    cleanup();
    renderSection("en-US");

    const gallery = await screen.findByTestId("replay-artifact-gallery");
    const images = await within(gallery).findAllByRole("img");
    expect(images[0]).toHaveAttribute(
      "alt",
      en.anchorFrameAlt.replace("{time}", "00:00"),
    );
    expect(images[1]).toHaveAttribute(
      "alt",
      en.verificationFrameAlt.replace("{time}", "01:00"),
    );
    expect(within(gallery).getByText(en.verificationFrame)).toBeVisible();
    expect(within(gallery).queryByText(/mistake|fight|失误|团战/i)).not.toBeInTheDocument();
    expect(screen.getByText(en.replayNoAiNotice)).toBeVisible();

    getReplayStatusMock.mockRejectedValue(
      new ApiClientError("REPLAY_STORAGE_UNAVAILABLE", {}, true, SAFE_REQUEST_ID),
    );
    removeReplayCapability(REPLAY_ID);
    saveReplayCapability({
      replayId: REPLAY_ID,
      accessToken: TOKEN,
      matchId: MATCH_ID,
      updatedAt: "2026-08-01T15:00:00.000Z",
    });
    cleanup();
    renderSection("zh-CN");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(zh.replayStorageUnavailable);
  });
});
