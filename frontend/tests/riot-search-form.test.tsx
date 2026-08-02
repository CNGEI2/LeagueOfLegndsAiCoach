import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const { pushMock, detectPlayerMock, confirmPlayerPlatformMock } = vi.hoisted(() => ({
  pushMock: vi.fn(),
  detectPlayerMock: vi.fn(),
  confirmPlayerPlatformMock: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  detectPlayer: detectPlayerMock,
  confirmPlayerPlatform: confirmPlayerPlatformMock,
  ApiClientError: class ApiClientError extends Error {
    constructor(
      readonly code: string,
      readonly params: Record<string, unknown>,
      readonly retryable: boolean,
      readonly requestId: string | null,
    ) {
      super(code);
    }
  },
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

import { ApiClientError, confirmPlayerPlatform, detectPlayer } from "@/api/client";
import { RiotSearchForm } from "@/components/riot-search-form";
import { getMessages } from "@/i18n/messages";

const resolvedPlayer = {
  puuid: "puuid-1",
  game_name: "CNGEI",
  tag_line: "1115",
  platform: "NA1" as const,
  summoner_level: 772,
  profile_icon_id: 29,
  profile_icon: {
    entity_id: 29,
    name: "Profile icon",
    image_url: "https://ddragon.leagueoflegends.com/cdn/16.15.1/img/profileicon/29.png",
  },
  profile_static_data_status: { available: true, version: "16.15.1", code: null },
};

const successfulDetection = {
  status: "resolved" as const,
  player: resolvedPlayer,
  request_id: "a3f4c1d2e5b67890a1b2c3d4e5f60718",
};

const confirmationRequired = {
  status: "confirmation_required" as const,
  detection_id: "12345678-1234-5678-1234-567812345678",
  expires_at: "2026-08-02T12:15:00Z",
  candidates: [
    { platform: "EUW1" as const, display_name: "Europe West" },
    { platform: "NA1" as const, display_name: "North America" },
  ],
  request_id: "a3f4c1d2e5b67890a1b2c3d4e5f60718",
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("RiotSearchForm", () => {
  it("uses a single riotId field without platform or separate game/tag inputs", () => {
    render(<RiotSearchForm locale="en-US" messages={getMessages("en-US")} />);

    expect(screen.getByLabelText("Riot ID")).toHaveAttribute("name", "riotId");
    expect(screen.queryByLabelText("Game Name")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Tag Line")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Region")).not.toBeInTheDocument();
    expect(screen.getByText("Example: CNGEI#1115")).toBeVisible();
    expect(
      screen.getByText("The tag after # is part of your Riot ID, not the game server."),
    ).toBeVisible();
  });

  it("submits detectPlayer with the current locale and navigates on resolved", async () => {
    vi.mocked(detectPlayer).mockResolvedValue(successfulDetection);
    const user = userEvent.setup();
    render(<RiotSearchForm locale="en-US" messages={getMessages("en-US")} />);

    await user.type(screen.getByLabelText("Riot ID"), "CNGEI#1115");
    await user.click(screen.getByRole("button", { name: "Find account" }));

    expect(detectPlayer).toHaveBeenCalledWith({ riotId: "CNGEI#1115", locale: "en-US" });
    expect(pushMock).toHaveBeenCalledWith("/en-US/players/puuid-1?platform=NA1");
  });

  it("disables repeat submit and announces progress while detecting", async () => {
    let finish: (value: typeof successfulDetection) => void = () => undefined;
    vi.mocked(detectPlayer).mockImplementation(
      () => new Promise((resolve) => (finish = resolve)),
    );
    const user = userEvent.setup();
    render(<RiotSearchForm locale="en-US" messages={getMessages("en-US")} />);

    await user.type(screen.getByLabelText("Riot ID"), "CNGEI#1115");
    await user.click(screen.getByRole("button", { name: "Find account" }));

    expect(screen.getByRole("button", { name: "Detecting…" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Detecting your Riot account and servers…",
    );
    finish(successfulDetection);
  });

  it("renders only API candidate display names and confirms the selected platform", async () => {
    vi.mocked(detectPlayer).mockResolvedValue(confirmationRequired);
    vi.mocked(confirmPlayerPlatform).mockResolvedValue({
      status: "resolved",
      player: { ...resolvedPlayer, platform: "EUW1" },
      request_id: "a3f4c1d2e5b67890a1b2c3d4e5f60718",
    });
    const user = userEvent.setup();
    render(<RiotSearchForm locale="en-US" messages={getMessages("en-US")} />);

    await user.type(screen.getByLabelText("Riot ID"), "CNGEI#1115");
    await user.click(screen.getByRole("button", { name: "Find account" }));

    expect(await screen.findByRole("heading", { name: "Choose your server" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Europe West" })).toBeVisible();
    expect(screen.getByRole("button", { name: "North America" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "KR" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Europe West" }));

    expect(confirmPlayerPlatform).toHaveBeenCalledWith({
      detectionId: confirmationRequired.detection_id,
      platform: "EUW1",
      locale: "en-US",
    });
    expect(pushMock).toHaveBeenCalledWith("/en-US/players/puuid-1?platform=EUW1");
  });

  it("shows distinct messages for not found, invalid id, rate limit, unavailable, and expiry", async () => {
    const user = userEvent.setup();
    const cases: Array<[string, string, Record<string, unknown>]> = [
      ["PLAYER_NOT_FOUND", "We couldn't find that Riot ID.", {}],
      ["INVALID_RIOT_ID", "Check the Riot ID format and try again.", {}],
      ["RIOT_RATE_LIMITED", "Riot is busy. Try again in 12 seconds.", { retry_after_seconds: 12 }],
      [
        "RIOT_PLATFORM_DETECTION_UNAVAILABLE",
        "Server detection is temporarily unavailable. Try again.",
        {},
      ],
    ];

    for (const [code, message, params] of cases) {
      cleanup();
      vi.mocked(detectPlayer).mockRejectedValue(new ApiClientError(code, params, true, "req-1"));
      render(<RiotSearchForm locale="en-US" messages={getMessages("en-US")} />);
      await user.type(screen.getByLabelText("Riot ID"), "CNGEI#1115");
      await user.click(screen.getByRole("button", { name: "Find account" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(message);
    }

    cleanup();
    vi.mocked(detectPlayer).mockResolvedValue(confirmationRequired);
    vi.mocked(confirmPlayerPlatform).mockRejectedValue(
      new ApiClientError("PLATFORM_CONFIRMATION_EXPIRED", {}, false, "req-2"),
    );
    render(<RiotSearchForm locale="en-US" messages={getMessages("en-US")} />);
    await user.type(screen.getByLabelText("Riot ID"), "CNGEI#1115");
    await user.click(screen.getByRole("button", { name: "Find account" }));
    await user.click(await screen.findByRole("button", { name: "Europe West" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Server confirmation expired. Detect your account again.",
    );
    expect(screen.getByLabelText("Riot ID")).toBeVisible();
    expect(screen.getByRole("button", { name: "Find account" })).toBeVisible();
  });

  it("keeps the request ID under support details", async () => {
    vi.mocked(detectPlayer).mockRejectedValue(
      new ApiClientError("PLAYER_NOT_FOUND", {}, false, "request-404"),
    );
    const user = userEvent.setup();
    render(<RiotSearchForm locale="en-US" messages={getMessages("en-US")} />);

    await user.type(screen.getByLabelText("Riot ID"), "CNGEI#1115");
    await user.click(screen.getByRole("button", { name: "Find account" }));
    await user.click(screen.getByText("Support details"));

    expect(screen.getByText("Request ID: request-404")).toBeVisible();
  });

  it("renders Simplified Chinese detection copy and candidates", async () => {
    vi.mocked(detectPlayer).mockResolvedValue({
      ...confirmationRequired,
      candidates: [
        { platform: "EUW1", display_name: "欧西服" },
        { platform: "NA1", display_name: "北美服" },
      ],
    });
    const user = userEvent.setup();
    render(<RiotSearchForm locale="zh-CN" messages={getMessages("zh-CN")} />);

    expect(screen.getByLabelText("Riot ID")).toBeVisible();
    expect(screen.getByRole("button", { name: "识别账号" })).toBeVisible();
    await user.type(screen.getByLabelText("Riot ID"), "CNGEI#1115");
    await user.click(screen.getByRole("button", { name: "识别账号" }));

    expect(await screen.findByRole("heading", { name: "选择服务器" })).toBeVisible();
    expect(screen.getByRole("button", { name: "欧西服" })).toBeVisible();
    expect(screen.getByRole("button", { name: "北美服" })).toBeVisible();
  });
});
