import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const { getRecentMatchesMock } = vi.hoisted(() => ({ getRecentMatchesMock: vi.fn() }));

vi.mock("@/api/client", () => ({
  getRecentMatches: getRecentMatchesMock,
  ApiClientError: class ApiClientError extends Error {},
}));

import { getRecentMatches } from "@/api/client";
import type { RecentMatchesResponse } from "@/api/schemas";
import { PlayerPageClient } from "@/components/player-page-client";

const participant = {
  puuid: "puuid-1",
  team_id: 100,
  champion_id: 103,
  role: "MIDDLE",
  won: true,
  kills: 8,
  deaths: 2,
  assists: 6,
  cs: 201,
  gold_earned: 14321,
  damage_to_champions: 24567,
  vision_score: 18,
  item_ids: [1055, 0],
  champion: {
    entity_id: 103,
    name: "Ahri",
    image_url: "https://cdn.example/champions/103.png",
  },
  items: [
    { entity_id: 1055, name: "Doran's Blade", image_url: "https://cdn.example/items/1055.png" },
    null,
  ],
};

const recentMatchesFixture: RecentMatchesResponse = {
  player: {
    puuid: "puuid-1",
    game_name: "PlayerName",
    tag_line: "1115",
    platform: "NA1",
    summoner_level: 772,
    profile_icon_id: 29,
    profile_icon: {
      entity_id: 29,
      name: "Profile icon",
      image_url: "https://cdn.example/icons/29.png",
    },
    profile_static_data_status: { available: true, version: "16.15.1", code: null },
  },
  matches: [
    {
      match_id: "NA1_3",
      platform: "NA1",
      queue_id: 420,
      started_at: "2026-07-30T12:00:00Z",
      duration_seconds: 1800,
      game_version: "16.15.1",
      participant,
      analysis_supported: true,
      unsupported_reason_code: null,
      detail_supported: true,
      detail_unavailable_reason_code: null,
      static_data_status: { available: true, version: "16.15.1", code: null },
    },
    {
      match_id: "NA1_2",
      platform: "NA1",
      queue_id: 1700,
      started_at: "2026-07-29T12:00:00Z",
      duration_seconds: 1200,
      game_version: "16.15.1",
      participant: { ...participant, won: false },
      analysis_supported: false,
      unsupported_reason_code: "ANALYSIS_UNSUPPORTED_MODE",
      detail_supported: false,
      detail_unavailable_reason_code: "MATCH_DETAIL_UNSUPPORTED_MODE",
      static_data_status: { available: true, version: "16.15.1", code: null },
    },
    {
      match_id: "NA1_1",
      platform: "NA1",
      queue_id: 400,
      started_at: "2026-07-28T12:00:00Z",
      duration_seconds: 900,
      game_version: "16.15.1",
      participant,
      analysis_supported: true,
      unsupported_reason_code: null,
      detail_supported: true,
      detail_unavailable_reason_code: null,
      static_data_status: { available: true, version: "16.15.1", code: null },
    },
  ],
  request_id: "request-1",
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("PlayerPageClient", () => {
  it("renders the canonical Riot ID and ordered recent matches", async () => {
    vi.mocked(getRecentMatches).mockResolvedValue(recentMatchesFixture);
    render(<PlayerPageClient locale="zh-CN" puuid="puuid-1" platform="NA1" />);

    expect(await screen.findByRole("heading", { name: "PlayerName#1115" })).toBeVisible();
    const cards = screen.getAllByTestId("recent-match-card");
    expect(cards).toHaveLength(3);
    expect(cards[0]).toHaveTextContent("NA1_3");
    expect(screen.getByText("暂不支持复盘")).toBeVisible();
  });

  it("shows a loading state before recent matches resolve", () => {
    vi.mocked(getRecentMatches).mockReturnValue(new Promise(() => undefined));
    render(<PlayerPageClient locale="en-US" puuid="puuid-1" platform="NA1" />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading recent matches…");
  });

  it("shows an empty state when the player has no recent matches", async () => {
    vi.mocked(getRecentMatches).mockResolvedValue({ ...recentMatchesFixture, matches: [] });
    render(<PlayerPageClient locale="en-US" puuid="puuid-1" platform="NA1" />);

    expect(await screen.findByText("No recent matches found.")).toBeVisible();
  });

  it("retries a failed recent-match request", async () => {
    vi.mocked(getRecentMatches)
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce(recentMatchesFixture);
    const user = userEvent.setup();
    render(<PlayerPageClient locale="en-US" puuid="puuid-1" platform="NA1" />);

    await user.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("heading", { name: "PlayerName#1115" })).toBeVisible();
    expect(getRecentMatches).toHaveBeenCalledTimes(2);
  });

  it("warns about degraded static data and uses localized image alternatives", async () => {
    vi.mocked(getRecentMatches).mockResolvedValue({
      ...recentMatchesFixture,
      player: {
        ...recentMatchesFixture.player,
        profile_static_data_status: {
          available: false,
          version: null,
          code: "STATIC_DATA_UNAVAILABLE",
        },
      },
    });
    render(<PlayerPageClient locale="zh-CN" puuid="puuid-1" platform="NA1" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("静态游戏数据暂不可用");
    expect(screen.getByAltText("PlayerName 的头像")).toHaveAttribute(
      "src",
      "https://cdn.example/icons/29.png",
    );
  });

  it("links only standard-detail matches and keeps unsupported matches visible", async () => {
    vi.mocked(getRecentMatches).mockResolvedValue(recentMatchesFixture);
    render(<PlayerPageClient locale="en-US" puuid="puuid-1" platform="NA1" />);

    const cards = await screen.findAllByTestId("recent-match-card");
    expect(cards[0].querySelector("a")).toHaveAttribute(
      "href",
      "/en-US/matches/NA1_3?platform=NA1&puuid=puuid-1",
    );
    expect(cards[1]).toHaveTextContent("Match details are not available for this queue.");
    expect(cards[1].querySelector("a")).toBeNull();
  });
});
