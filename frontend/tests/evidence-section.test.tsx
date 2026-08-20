import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const {
  prepareMatchEvidenceMock,
  getReplayArtifactsMock,
  findReplayCapabilityForMatchMock,
  removeReplayCapabilityMock,
} = vi.hoisted(() => ({
  prepareMatchEvidenceMock: vi.fn(),
  getReplayArtifactsMock: vi.fn(),
  findReplayCapabilityForMatchMock: vi.fn(),
  removeReplayCapabilityMock: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  prepareMatchEvidence: prepareMatchEvidenceMock,
  getReplayArtifacts: getReplayArtifactsMock,
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

vi.mock("@/replays/storage", () => ({
  findReplayCapabilityForMatch: findReplayCapabilityForMatchMock,
  removeReplayCapability: removeReplayCapabilityMock,
}));

import { ApiClientError } from "@/api/client";
import { EvidenceSection } from "@/components/evidence-section";
import { getMessages } from "@/i18n/messages";

const MATCH_ID = "NA1_123456789";
const REPLAY_ID = "11111111-2222-4333-8444-555555555555";
const ARTIFACT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";
const MISSING_ARTIFACT_ID = "bbbbbbbb-bbbb-4ccc-8ddd-eeeeeeeeeeee";
const EXTRA_ARTIFACT_ID = "cccccccc-bbbb-4ccc-8ddd-eeeeeeeeeeee";
const TOKEN = "possession-token-value";
const SAFE_REQUEST_ID = "a3f4c1d2e5b67890a1b2c3d4e5f60718";
const PUUID = "selected-puuid";

function timelineOnlyReady(overrides: Record<string, unknown> = {}) {
  return {
    status: "ready",
    platform: "NA1",
    match_id: MATCH_ID,
    locale: "en-US",
    schema_version: 1,
    facts: [
      {
        fact_id: "timeline:NA1:NA1_123456789:v1:frame:1:event:0",
        kind: "champion_kill",
        timestamp_ms: 60_000,
        relationship: "killer",
        killer_id: 1,
        victim_id: 6,
        assisting_participant_ids: [],
        position_x: 100,
        position_y: 200,
      },
    ],
    windows: [
      {
        window_id: "evidence-window:NA1:NA1_123456789:v1:0",
        start_ms: 48_000,
        end_ms: 68_000,
        categories: ["combat_context"],
        trigger_fact_ids: ["timeline:NA1:NA1_123456789:v1:frame:1:event:0"],
        coverage: "unavailable",
        covered_game_start_ms: null,
        covered_game_end_ms: null,
        video_start_ms: null,
        video_end_ms: null,
        artifacts: [],
      },
    ],
    timeline_cache_status: "miss",
    replay_link: null,
    static_data_status: { available: true, version: "16.15.1", code: null },
    truncated: false,
    total_window_count: 1,
    scope_notice_code: "EVIDENCE_ONLY_NO_COACHING",
    request_id: SAFE_REQUEST_ID,
    ...overrides,
  };
}

function linkedReady() {
  return timelineOnlyReady({
    windows: [
      {
        window_id: "evidence-window:NA1:NA1_123456789:v1:0",
        start_ms: 48_000,
        end_ms: 68_000,
        categories: ["combat_context"],
        trigger_fact_ids: ["timeline:NA1:NA1_123456789:v1:frame:1:event:0"],
        coverage: "full",
        covered_game_start_ms: 48_000,
        covered_game_end_ms: 68_000,
        video_start_ms: 49_000,
        video_end_ms: 69_000,
        artifacts: [
          {
            artifact_id: ARTIFACT_ID,
            kind: "verification_frame",
            game_time_ms: 60_000,
            video_time_ms: 61_000,
          },
          {
            artifact_id: MISSING_ARTIFACT_ID,
            kind: "verification_frame",
            game_time_ms: 61_000,
            video_time_ms: 62_000,
          },
        ],
      },
    ],
    replay_link: {
      status: "linked",
      full_count: 1,
      partial_count: 0,
      unavailable_count: 0,
    },
  });
}

function artifactsManifest() {
  return {
    artifacts: [
      {
        artifact_id: ARTIFACT_ID,
        replay_id: REPLAY_ID,
        kind: "verification_frame",
        game_time_ms: 60_000,
        video_time_ms: 61_000,
        media_type: "image/jpeg",
        width: 1280,
        height: 720,
        size_bytes: 2048,
        access: {
          mode: "presigned",
          url: "https://cdn.example/artifacts/matched.jpg",
          expires_at: "2026-08-01T15:05:00+00:00",
        },
      },
      {
        artifact_id: EXTRA_ARTIFACT_ID,
        replay_id: REPLAY_ID,
        kind: "anchor_frame",
        game_time_ms: 0,
        video_time_ms: 0,
        media_type: "image/jpeg",
        width: 1280,
        height: 720,
        size_bytes: 1024,
        access: {
          mode: "presigned",
          url: "https://cdn.example/artifacts/extra.jpg",
          expires_at: "2026-08-01T15:05:00+00:00",
        },
      },
    ],
    request_id: SAFE_REQUEST_ID,
  };
}

function renderSection(
  props: Partial<{
    matchId: string;
    puuid: string;
    platform: "NA1" | "EUW1" | "KR";
    locale: "en-US" | "zh-CN";
  }> = {},
) {
  return render(
    <EvidenceSection
      matchId={props.matchId ?? MATCH_ID}
      puuid={props.puuid ?? PUUID}
      platform={props.platform ?? "NA1"}
      locale={props.locale ?? "en-US"}
    />,
  );
}

beforeEach(() => {
  findReplayCapabilityForMatchMock.mockReturnValue(null);
  removeReplayCapabilityMock.mockReset();
  prepareMatchEvidenceMock.mockReset();
  getReplayArtifactsMock.mockReset();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("EvidenceSection", () => {
  it("renders the idle prepare button and does not prepare on mount", () => {
    const messages = getMessages("en-US");
    renderSection();

    const button = screen.getByRole("button", { name: messages.prepareEvidence });
    expect(button).toBeVisible();
    expect(button).toHaveAttribute("type", "button");
    expect(prepareMatchEvidenceMock).not.toHaveBeenCalled();
  });

  it("enters a polite loading status and sends exactly one prepare call on click", async () => {
    const user = userEvent.setup();
    const messages = getMessages("en-US");
    prepareMatchEvidenceMock.mockImplementation(() => new Promise(() => undefined));
    renderSection();

    await user.click(screen.getByRole("button", { name: messages.prepareEvidence }));

    const status = await screen.findByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveTextContent(messages.preparingEvidence);
    expect(prepareMatchEvidenceMock).toHaveBeenCalledTimes(1);
    expect(prepareMatchEvidenceMock).toHaveBeenCalledWith(
      expect.objectContaining({
        matchId: MATCH_ID,
        puuid: PUUID,
        platform: "NA1",
        locale: "en-US",
      }),
      expect.any(AbortSignal),
    );
  });

  it("aborts in-flight work and resets to idle when matchId changes", async () => {
    const user = userEvent.setup();
    const messages = getMessages("en-US");
    let firstSignal: AbortSignal | undefined;
    prepareMatchEvidenceMock.mockImplementation((_input, signal?: AbortSignal) => {
      firstSignal = signal;
      return new Promise(() => undefined);
    });

    const view = renderSection({ matchId: "NA1_old" });
    await user.click(screen.getByRole("button", { name: messages.prepareEvidence }));
    await waitFor(() => expect(prepareMatchEvidenceMock).toHaveBeenCalledTimes(1));

    view.rerender(
      <EvidenceSection matchId="NA1_new" puuid={PUUID} platform="NA1" locale="en-US" />,
    );

    await waitFor(() => expect(firstSignal?.aborted).toBe(true));
    expect(screen.getByRole("button", { name: messages.prepareEvidence })).toBeVisible();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it.each([
    { locale: "zh-CN" as const },
    { platform: "EUW1" as const },
    { puuid: "other-puuid" },
  ])("aborts in-flight work and resets to idle when %s changes", async (nextProps) => {
    const user = userEvent.setup();
    const messages = getMessages("en-US");
    let firstSignal: AbortSignal | undefined;
    prepareMatchEvidenceMock.mockImplementation((_input, signal?: AbortSignal) => {
      firstSignal = signal;
      return new Promise(() => undefined);
    });

    const view = renderSection();
    await user.click(screen.getByRole("button", { name: messages.prepareEvidence }));
    await waitFor(() => expect(prepareMatchEvidenceMock).toHaveBeenCalledTimes(1));

    view.rerender(
      <EvidenceSection
        matchId={MATCH_ID}
        puuid={nextProps.puuid ?? PUUID}
        platform={nextProps.platform ?? "NA1"}
        locale={nextProps.locale ?? "en-US"}
      />,
    );

    await waitFor(() => expect(firstSignal?.aborted).toBe(true));
    expect(
      screen.getByRole("button", {
        name: getMessages(nextProps.locale ?? "en-US").prepareEvidence,
      }),
    ).toBeVisible();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("renders Timeline-only ready facts, windows, and the evidence-only notice", async () => {
    const user = userEvent.setup();
    const messages = getMessages("en-US");
    prepareMatchEvidenceMock.mockResolvedValue(timelineOnlyReady());
    renderSection();

    await user.click(screen.getByRole("button", { name: messages.prepareEvidence }));

    expect(await screen.findByText(messages.evidenceOnlyScopeNotice)).toBeVisible();
    expect(screen.getByText(messages.factKindChampionKill)).toBeVisible();
    expect(screen.getByText(messages.categoryCombatContext)).toBeVisible();
    expect(screen.getByText(messages.evidenceTimelineOnly)).toBeVisible();
    expect(screen.getByText(messages.coverageUnavailable)).toBeVisible();
    expect(getReplayArtifactsMock).not.toHaveBeenCalled();
  });

  it("includes ready capability replay credentials, joins artifacts, and never invents missing src", async () => {
    const user = userEvent.setup();
    const messages = getMessages("en-US");
    findReplayCapabilityForMatchMock.mockReturnValue({
      replayId: REPLAY_ID,
      accessToken: TOKEN,
      matchId: MATCH_ID,
      updatedAt: "2026-08-01T15:00:00.000Z",
      status: "ready",
    });
    prepareMatchEvidenceMock.mockResolvedValue(linkedReady());
    getReplayArtifactsMock.mockResolvedValue(artifactsManifest());
    renderSection();

    await user.click(screen.getByRole("button", { name: messages.prepareEvidence }));

    await waitFor(() => {
      expect(prepareMatchEvidenceMock).toHaveBeenCalledWith(
        expect.objectContaining({
          matchId: MATCH_ID,
          replay: { replayId: REPLAY_ID, accessToken: TOKEN },
        }),
        expect.any(AbortSignal),
      );
    });
    expect(findReplayCapabilityForMatchMock).toHaveBeenCalledWith(MATCH_ID, "ready");
    expect(getReplayArtifactsMock).toHaveBeenCalledWith(
      { replayId: REPLAY_ID, accessToken: TOKEN },
      expect.any(AbortSignal),
    );

    expect(await screen.findByText(messages.evidenceLinkedFrames)).toBeVisible();
    expect(screen.getByText(messages.coverageFull)).toBeVisible();

    const gallery = await screen.findByTestId("replay-artifact-gallery");
    const images = within(gallery).getAllByRole("img");
    expect(images).toHaveLength(1);
    expect(images[0]).toHaveAttribute("src", "https://cdn.example/artifacts/matched.jpg");
    expect(screen.queryByAltText(messages.anchorFrameAlt.replace("{time}", "00:00"))).not.toBeInTheDocument();
    for (const img of document.querySelectorAll("img")) {
      const src = img.getAttribute("src") ?? "";
      expect(src).not.toContain(MISSING_ARTIFACT_ID);
      expect(src).not.toContain(`/artifacts/${MISSING_ARTIFACT_ID}/`);
      expect(src).not.toContain("https://cdn.example/artifacts/extra.jpg");
    }
  });

  it("shows partial and unavailable coverage labels", async () => {
    const user = userEvent.setup();
    const messages = getMessages("en-US");
    prepareMatchEvidenceMock.mockResolvedValue(
      timelineOnlyReady({
        windows: [
          {
            window_id: "evidence-window:partial",
            start_ms: 100_000,
            end_ms: 120_000,
            categories: ["death_context"],
            trigger_fact_ids: ["fact-partial"],
            coverage: "partial",
            covered_game_start_ms: 100_000,
            covered_game_end_ms: 110_000,
            video_start_ms: 101_000,
            video_end_ms: 111_000,
            artifacts: [],
          },
          {
            window_id: "evidence-window:unavailable",
            start_ms: 200_000,
            end_ms: 220_000,
            categories: ["building_context"],
            trigger_fact_ids: ["fact-unavailable"],
            coverage: "unavailable",
            covered_game_start_ms: null,
            covered_game_end_ms: null,
            video_start_ms: null,
            video_end_ms: null,
            artifacts: [],
          },
        ],
        total_window_count: 2,
      }),
    );
    renderSection();

    await user.click(screen.getByRole("button", { name: messages.prepareEvidence }));

    expect(await screen.findByText(messages.coveragePartial)).toBeVisible();
    expect(screen.getByText(messages.coverageUnavailable)).toBeVisible();
  });

  it("shows the empty evidence state when facts and windows are empty", async () => {
    const user = userEvent.setup();
    const messages = getMessages("en-US");
    prepareMatchEvidenceMock.mockResolvedValue(
      timelineOnlyReady({ facts: [], windows: [], total_window_count: 0 }),
    );
    renderSection();

    await user.click(screen.getByRole("button", { name: messages.prepareEvidence }));

    expect(await screen.findByText(messages.evidenceEmpty)).toBeVisible();
  });

  it("shows a retryable alert with a retry button", async () => {
    const user = userEvent.setup();
    const messages = getMessages("en-US");
    prepareMatchEvidenceMock
      .mockRejectedValueOnce(
        new ApiClientError("RIOT_RATE_LIMITED", { retry_after_seconds: 5 }, true, SAFE_REQUEST_ID),
      )
      .mockResolvedValueOnce(timelineOnlyReady());
    renderSection();

    await user.click(screen.getByRole("button", { name: messages.prepareEvidence }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(messages.riotRateLimited.replace("{seconds}", "5"));
    await user.click(screen.getByRole("button", { name: messages.retry }));
    expect(await screen.findByText(messages.evidenceOnlyScopeNotice)).toBeVisible();
    expect(prepareMatchEvidenceMock).toHaveBeenCalledTimes(2);
  });

  it("does not offer retry for a non-retryable error", async () => {
    const user = userEvent.setup();
    const messages = getMessages("en-US");
    prepareMatchEvidenceMock.mockRejectedValue(
      new ApiClientError("MATCH_EVIDENCE_UNSUPPORTED_MODE", {}, false, SAFE_REQUEST_ID),
    );
    renderSection();

    await user.click(screen.getByRole("button", { name: messages.prepareEvidence }));

    expect(await screen.findByRole("alert")).toHaveTextContent(messages.matchEvidenceUnsupportedMode);
    expect(screen.queryByRole("button", { name: messages.retry })).not.toBeInTheDocument();
  });

  it("removes a stale capability and auto-retries Timeline-only once on REPLAY_NOT_FOUND", async () => {
    const user = userEvent.setup();
    const messages = getMessages("en-US");
    findReplayCapabilityForMatchMock.mockReturnValue({
      replayId: REPLAY_ID,
      accessToken: TOKEN,
      matchId: MATCH_ID,
      updatedAt: "2026-08-01T15:00:00.000Z",
      status: "ready",
    });
    prepareMatchEvidenceMock
      .mockRejectedValueOnce(new ApiClientError("REPLAY_NOT_FOUND", {}, false, SAFE_REQUEST_ID))
      .mockResolvedValueOnce(timelineOnlyReady());
    renderSection();

    await user.click(screen.getByRole("button", { name: messages.prepareEvidence }));

    await waitFor(() => expect(removeReplayCapabilityMock).toHaveBeenCalledWith(REPLAY_ID));
    await waitFor(() => expect(prepareMatchEvidenceMock).toHaveBeenCalledTimes(2));
    expect(prepareMatchEvidenceMock.mock.calls[0]?.[0]).toEqual(
      expect.objectContaining({
        replay: { replayId: REPLAY_ID, accessToken: TOKEN },
      }),
    );
    expect(prepareMatchEvidenceMock.mock.calls[1]?.[0]).toEqual(
      expect.objectContaining({
        matchId: MATCH_ID,
        puuid: PUUID,
        platform: "NA1",
        locale: "en-US",
      }),
    );
    expect(prepareMatchEvidenceMock.mock.calls[1]?.[0]).not.toHaveProperty("replay");
    expect(await screen.findByText(messages.evidenceTimelineOnly)).toBeVisible();
  });

  it("keeps the capability and stays retryable on REPLAY_EVIDENCE_NOT_READY without fabricating coverage", async () => {
    const user = userEvent.setup();
    const messages = getMessages("en-US");
    findReplayCapabilityForMatchMock.mockReturnValue({
      replayId: REPLAY_ID,
      accessToken: TOKEN,
      matchId: MATCH_ID,
      updatedAt: "2026-08-01T15:00:00.000Z",
      status: "ready",
    });
    prepareMatchEvidenceMock.mockRejectedValue(
      new ApiClientError("REPLAY_EVIDENCE_NOT_READY", {}, true, SAFE_REQUEST_ID),
    );
    renderSection();

    await user.click(screen.getByRole("button", { name: messages.prepareEvidence }));

    expect(await screen.findByRole("alert")).toHaveTextContent(messages.replayEvidenceNotReady);
    expect(screen.getByRole("button", { name: messages.retry })).toBeVisible();
    expect(removeReplayCapabilityMock).not.toHaveBeenCalled();
    expect(screen.queryByText(messages.coverageFull)).not.toBeInTheDocument();
    expect(screen.queryByText(messages.coveragePartial)).not.toBeInTheDocument();
    expect(screen.queryByText(messages.evidenceLinkedFrames)).not.toBeInTheDocument();
    expect(getReplayArtifactsMock).not.toHaveBeenCalled();
  });

  it("keeps the prepare trigger keyboard accessible as type=button", () => {
    const messages = getMessages("en-US");
    renderSection();
    expect(screen.getByRole("button", { name: messages.prepareEvidence })).toHaveAttribute(
      "type",
      "button",
    );
  });

  it("drops a stale capability and retries Timeline-only when the artifact manifest is REPLAY_NOT_FOUND", async () => {
    const user = userEvent.setup();
    const messages = getMessages("en-US");
    findReplayCapabilityForMatchMock.mockReturnValue({
      replayId: REPLAY_ID,
      accessToken: TOKEN,
      matchId: MATCH_ID,
      updatedAt: "2026-08-01T15:00:00.000Z",
      status: "ready",
    });
    prepareMatchEvidenceMock
      .mockResolvedValueOnce(linkedReady())
      .mockResolvedValueOnce(timelineOnlyReady());
    getReplayArtifactsMock.mockRejectedValue(
      new ApiClientError("REPLAY_NOT_FOUND", {}, false, SAFE_REQUEST_ID),
    );
    renderSection();

    await user.click(screen.getByRole("button", { name: messages.prepareEvidence }));

    await waitFor(() => expect(removeReplayCapabilityMock).toHaveBeenCalledWith(REPLAY_ID));
    await waitFor(() => expect(prepareMatchEvidenceMock).toHaveBeenCalledTimes(2));
    expect(prepareMatchEvidenceMock.mock.calls[1]?.[0]).toEqual(
      expect.objectContaining({
        matchId: MATCH_ID,
        puuid: PUUID,
        platform: "NA1",
        locale: "en-US",
      }),
    );
    expect(prepareMatchEvidenceMock.mock.calls[1]?.[0]).not.toHaveProperty("replay");
    expect(getReplayArtifactsMock).toHaveBeenCalledTimes(1);
    expect(await screen.findByText(messages.evidenceTimelineOnly)).toBeVisible();
    expect(screen.queryByText(messages.coverageFull)).not.toBeInTheDocument();
    expect(screen.queryByText(messages.evidenceLinkedFrames)).not.toBeInTheDocument();
    expect(screen.queryByTestId("replay-artifact-gallery")).not.toBeInTheDocument();
  });

  it("aborts a deferred manifest refresh on unmount", async () => {
    const user = userEvent.setup();
    const messages = getMessages("en-US");
    findReplayCapabilityForMatchMock.mockReturnValue({
      replayId: REPLAY_ID,
      accessToken: TOKEN,
      matchId: MATCH_ID,
      updatedAt: "2026-08-01T15:00:00.000Z",
      status: "ready",
    });
    prepareMatchEvidenceMock.mockResolvedValue(linkedReady());
    let refreshSignal: AbortSignal | undefined;
    getReplayArtifactsMock
      .mockResolvedValueOnce(artifactsManifest())
      .mockImplementationOnce((_input, signal?: AbortSignal) => {
        refreshSignal = signal;
        return new Promise(() => undefined);
      });

    const view = renderSection();
    await user.click(screen.getByRole("button", { name: messages.prepareEvidence }));
    const image = await screen.findByRole("img");
    image.dispatchEvent(new Event("error"));

    await waitFor(() => expect(getReplayArtifactsMock).toHaveBeenCalledTimes(2));
    view.unmount();
    await waitFor(() => expect(refreshSignal?.aborted).toBe(true));
  });

  it("ignores a stale deferred refresh after the same request key is prepared again", async () => {
    const user = userEvent.setup();
    const messages = getMessages("en-US");
    findReplayCapabilityForMatchMock.mockReturnValue({
      replayId: REPLAY_ID,
      accessToken: TOKEN,
      matchId: MATCH_ID,
      updatedAt: "2026-08-01T15:00:00.000Z",
      status: "ready",
    });
    const secondArtifactId = "dddddddd-bbbb-4ccc-8ddd-eeeeeeeeeeee";
    prepareMatchEvidenceMock
      .mockResolvedValueOnce(linkedReady())
      .mockResolvedValueOnce(
        timelineOnlyReady({
          windows: [
            {
              window_id: "evidence-window:second",
              start_ms: 48_000,
              end_ms: 68_000,
              categories: ["combat_context"],
              trigger_fact_ids: ["timeline:NA1:NA1_123456789:v1:frame:1:event:0"],
              coverage: "full",
              covered_game_start_ms: 48_000,
              covered_game_end_ms: 68_000,
              video_start_ms: 49_000,
              video_end_ms: 69_000,
              artifacts: [
                {
                  artifact_id: secondArtifactId,
                  kind: "verification_frame",
                  game_time_ms: 60_000,
                  video_time_ms: 61_000,
                },
              ],
            },
          ],
          replay_link: {
            status: "linked",
            full_count: 1,
            partial_count: 0,
            unavailable_count: 0,
          },
        }),
      );

    let resolveStaleRefresh: ((value: ReturnType<typeof artifactsManifest>) => void) | undefined;
    getReplayArtifactsMock
      .mockResolvedValueOnce(artifactsManifest())
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveStaleRefresh = resolve;
          }),
      )
      .mockResolvedValueOnce({
        artifacts: [
          {
            artifact_id: secondArtifactId,
            replay_id: REPLAY_ID,
            kind: "verification_frame",
            game_time_ms: 60_000,
            video_time_ms: 61_000,
            media_type: "image/jpeg",
            width: 1280,
            height: 720,
            size_bytes: 2048,
            access: {
              mode: "presigned",
              url: "https://cdn.example/artifacts/second.jpg",
              expires_at: "2026-08-01T15:05:00+00:00",
            },
          },
        ],
        request_id: SAFE_REQUEST_ID,
      });

    const view = renderSection();
    await user.click(screen.getByRole("button", { name: messages.prepareEvidence }));
    const firstImage = await screen.findByRole("img");
    expect(firstImage).toHaveAttribute("src", "https://cdn.example/artifacts/matched.jpg");
    firstImage.dispatchEvent(new Event("error"));
    await waitFor(() => expect(resolveStaleRefresh).toBeDefined());

    view.rerender(<EvidenceSection matchId="NA1_other" puuid={PUUID} platform="NA1" locale="en-US" />);
    view.rerender(
      <EvidenceSection matchId={MATCH_ID} puuid={PUUID} platform="NA1" locale="en-US" />,
    );
    await user.click(screen.getByRole("button", { name: messages.prepareEvidence }));
    expect(await screen.findByRole("img")).toHaveAttribute(
      "src",
      "https://cdn.example/artifacts/second.jpg",
    );

    resolveStaleRefresh?.(artifactsManifest());
    await waitFor(() =>
      expect(screen.getByRole("img")).toHaveAttribute("src", "https://cdn.example/artifacts/second.jpg"),
    );
    expect(document.querySelector('img[src="https://cdn.example/artifacts/matched.jpg"]')).toBeNull();
  });

  it("renders each linked artifact inside its own window card", async () => {
    const user = userEvent.setup();
    const messages = getMessages("en-US");
    const secondArtifactId = "dddddddd-bbbb-4ccc-8ddd-eeeeeeeeeeee";
    findReplayCapabilityForMatchMock.mockReturnValue({
      replayId: REPLAY_ID,
      accessToken: TOKEN,
      matchId: MATCH_ID,
      updatedAt: "2026-08-01T15:00:00.000Z",
      status: "ready",
    });
    prepareMatchEvidenceMock.mockResolvedValue(
      timelineOnlyReady({
        windows: [
          {
            window_id: "evidence-window:one",
            start_ms: 48_000,
            end_ms: 68_000,
            categories: ["combat_context"],
            trigger_fact_ids: ["fact-one"],
            coverage: "full",
            covered_game_start_ms: 48_000,
            covered_game_end_ms: 68_000,
            video_start_ms: 49_000,
            video_end_ms: 69_000,
            artifacts: [
              {
                artifact_id: ARTIFACT_ID,
                kind: "verification_frame",
                game_time_ms: 60_000,
                video_time_ms: 61_000,
              },
            ],
          },
          {
            window_id: "evidence-window:two",
            start_ms: 80_000,
            end_ms: 100_000,
            categories: ["objective_context"],
            trigger_fact_ids: ["fact-two"],
            coverage: "full",
            covered_game_start_ms: 80_000,
            covered_game_end_ms: 100_000,
            video_start_ms: 81_000,
            video_end_ms: 101_000,
            artifacts: [
              {
                artifact_id: secondArtifactId,
                kind: "verification_frame",
                game_time_ms: 90_000,
                video_time_ms: 91_000,
              },
              {
                artifact_id: MISSING_ARTIFACT_ID,
                kind: "verification_frame",
                game_time_ms: 91_000,
                video_time_ms: 92_000,
              },
            ],
          },
        ],
        total_window_count: 2,
        replay_link: { status: "linked", full_count: 2, partial_count: 0, unavailable_count: 0 },
      }),
    );
    getReplayArtifactsMock.mockResolvedValue({
      artifacts: [
        ...artifactsManifest().artifacts,
        {
          artifact_id: secondArtifactId,
          replay_id: REPLAY_ID,
          kind: "verification_frame",
          game_time_ms: 90_000,
          video_time_ms: 91_000,
          media_type: "image/jpeg",
          width: 1280,
          height: 720,
          size_bytes: 2048,
          access: {
            mode: "presigned",
            url: "https://cdn.example/artifacts/second.jpg",
            expires_at: "2026-08-01T15:05:00+00:00",
          },
        },
      ],
      request_id: SAFE_REQUEST_ID,
    });
    renderSection();

    await user.click(screen.getByRole("button", { name: messages.prepareEvidence }));

    const firstCard = await screen.findByTestId("evidence-window:one");
    const secondCard = screen.getByTestId("evidence-window:two");
    const firstGallery = within(firstCard).getByTestId("replay-artifact-gallery");
    const secondGallery = within(secondCard).getByTestId("replay-artifact-gallery");
    expect(within(firstGallery).getAllByRole("img")).toHaveLength(1);
    expect(within(firstGallery).getByRole("img")).toHaveAttribute(
      "src",
      "https://cdn.example/artifacts/matched.jpg",
    );
    expect(within(secondGallery).getAllByRole("img")).toHaveLength(1);
    expect(within(secondGallery).getByRole("img")).toHaveAttribute(
      "src",
      "https://cdn.example/artifacts/second.jpg",
    );
    expect(within(firstCard).queryByRole("img", { name: /01:30/ })).not.toBeInTheDocument();
    expect(within(secondCard).queryByRole("img", { name: /01:00/ })).not.toBeInTheDocument();
    expect(document.querySelector('img[src="https://cdn.example/artifacts/extra.jpg"]')).toBeNull();
    for (const img of document.querySelectorAll("img")) {
      expect(img.getAttribute("src") ?? "").not.toContain(MISSING_ARTIFACT_ID);
    }
  });

  it("shows truncation metadata only when the response is truncated", async () => {
    const user = userEvent.setup();
    const messages = getMessages("en-US");
    prepareMatchEvidenceMock.mockResolvedValueOnce(
      timelineOnlyReady({ truncated: true, total_window_count: 65 }),
    );
    renderSection();
    await user.click(screen.getByRole("button", { name: messages.prepareEvidence }));
    expect(
      await screen.findByText(messages.evidenceTruncatedNotice.replace("{shown}", "1").replace("{total}", "65")),
    ).toBeVisible();

    cleanup();
    prepareMatchEvidenceMock.mockResolvedValueOnce(timelineOnlyReady({ truncated: false, total_window_count: 1 }));
    renderSection();
    await user.click(screen.getByRole("button", { name: messages.prepareEvidence }));
    expect(await screen.findByText(messages.evidenceTimelineOnly)).toBeVisible();
    expect(screen.queryByText(/65/)).not.toBeInTheDocument();
  });

  it("maps NOT_FOUND and VALIDATION_ERROR to dedicated copy instead of invalid response", async () => {
    const user = userEvent.setup();
    const messages = getMessages("en-US");
    prepareMatchEvidenceMock.mockRejectedValueOnce(
      new ApiClientError("NOT_FOUND", {}, false, SAFE_REQUEST_ID),
    );
    renderSection();
    await user.click(screen.getByRole("button", { name: messages.prepareEvidence }));
    const notFoundAlert = await screen.findByRole("alert");
    expect(notFoundAlert).toHaveTextContent(messages.evidenceNotFound);
    expect(notFoundAlert).not.toHaveTextContent(messages.invalidApiResponse);

    cleanup();
    prepareMatchEvidenceMock.mockRejectedValueOnce(
      new ApiClientError("VALIDATION_ERROR", {}, false, SAFE_REQUEST_ID),
    );
    renderSection();
    await user.click(screen.getByRole("button", { name: messages.prepareEvidence }));
    const validationAlert = await screen.findByRole("alert");
    expect(validationAlert).toHaveTextContent(messages.evidenceValidationError);
    expect(validationAlert).not.toHaveTextContent(messages.invalidApiResponse);
  });
});
