import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const { pushMock, resolvePlayerMock } = vi.hoisted(() => ({
  pushMock: vi.fn(),
  resolvePlayerMock: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  resolvePlayer: resolvePlayerMock,
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

import { ApiClientError, resolvePlayer } from "@/api/client";
import { RiotSearchForm } from "@/components/riot-search-form";
import { getMessages } from "@/i18n/messages";

const successfulResolution = {
  player: {
    puuid: "puuid-1",
    game_name: "PlayerName",
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
  },
  request_id: "request-1",
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("RiotSearchForm", () => {
  it("resolves an independent tag line and navigates to the localized player page", async () => {
    vi.mocked(resolvePlayer).mockResolvedValue(successfulResolution);
    const user = userEvent.setup();
    render(<RiotSearchForm locale="en-US" messages={getMessages("en-US")} />);

    await user.type(screen.getByLabelText("Game Name"), "PlayerName");
    await user.type(screen.getByLabelText("Tag Line"), "1115");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(resolvePlayer).toHaveBeenCalledWith({
      platform: "NA1",
      gameName: "PlayerName",
      tagLine: "1115",
    });
    expect(pushMock).toHaveBeenCalledWith("/en-US/players/puuid-1?platform=NA1");
  });

  it("trims Unicode Riot ID fields before resolving", async () => {
    vi.mocked(resolvePlayer).mockResolvedValue(successfulResolution);
    const user = userEvent.setup();
    render(<RiotSearchForm locale="en-US" messages={getMessages("en-US")} />);

    await user.type(screen.getByLabelText("Game Name"), "  玩家名  ");
    await user.type(screen.getByLabelText("Tag Line"), "  标签  ");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(resolvePlayer).toHaveBeenCalledWith({
      platform: "NA1",
      gameName: "玩家名",
      tagLine: "标签",
    });
  });

  it("disables the submit button and announces loading while resolving", async () => {
    let finishResolution: (value: typeof successfulResolution) => void = () => undefined;
    vi.mocked(resolvePlayer).mockImplementation(
      () => new Promise((resolve) => (finishResolution = resolve)),
    );
    const user = userEvent.setup();
    render(<RiotSearchForm locale="en-US" messages={getMessages("en-US")} />);

    await user.type(screen.getByLabelText("Game Name"), "PlayerName");
    await user.type(screen.getByLabelText("Tag Line"), "1115");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(screen.getByRole("button", { name: "Searching…" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Searching for Riot ID…");
    finishResolution(successfulResolution);
  });

  it("shows localized safe player-not-found copy and the request ID", async () => {
    vi.mocked(resolvePlayer).mockRejectedValue(
      new ApiClientError("PLAYER_NOT_FOUND", {}, false, "request-404"),
    );
    const user = userEvent.setup();
    render(<RiotSearchForm locale="en-US" messages={getMessages("en-US")} />);

    await user.type(screen.getByLabelText("Game Name"), "PlayerName");
    await user.type(screen.getByLabelText("Tag Line"), "1115");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("We couldn't find that Riot ID.");
    await user.click(screen.getByText("Support details"));
    expect(screen.getByText("Request ID: request-404")).toBeVisible();
  });

  it("shows a retry delay for a rate limit response", async () => {
    vi.mocked(resolvePlayer).mockRejectedValue(
      new ApiClientError("RIOT_RATE_LIMITED", { retry_after_seconds: 12 }, true, null),
    );
    const user = userEvent.setup();
    render(<RiotSearchForm locale="en-US" messages={getMessages("en-US")} />);

    await user.type(screen.getByLabelText("Game Name"), "PlayerName");
    await user.type(screen.getByLabelText("Tag Line"), "1115");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 12 seconds.");
  });

  it("accepts a tag line with up to sixteen characters", () => {
    render(<RiotSearchForm locale="en-US" messages={getMessages("en-US")} />);

    expect(screen.getByLabelText("Tag Line")).toHaveAttribute("maxLength", "16");
    expect(screen.getByText("Example: PlayerName # 1115")).toBeVisible();
  });

  it("accepts a game name with up to thirty-two characters", () => {
    render(<RiotSearchForm locale="en-US" messages={getMessages("en-US")} />);

    expect(screen.getByLabelText("Game Name")).toHaveAttribute("maxLength", "32");
  });

  it("renders Simplified Chinese labels", () => {
    render(<RiotSearchForm locale="zh-CN" messages={getMessages("zh-CN")} />);

    expect(screen.getByLabelText("游戏名称")).toBeVisible();
    expect(screen.getByRole("button", { name: "查询" })).toBeVisible();
  });
});
