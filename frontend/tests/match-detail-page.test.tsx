import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const { getMatchDetailMock, notFoundMock } = vi.hoisted(() => ({
  getMatchDetailMock: vi.fn(),
  notFoundMock: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  getMatchDetail: getMatchDetailMock,
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
  notFound: () => {
    notFoundMock();
    throw new Error("NEXT_NOT_FOUND");
  },
}));

vi.mock("@/components/replay-section", () => ({
  ReplaySection: ({
    matchId,
    puuid,
    platform,
    locale,
    matchDurationSeconds,
  }: {
    matchId: string;
    puuid: string;
    platform: string;
    locale: string;
    matchDurationSeconds: number;
  }) => (
    <section
      data-testid="replay-section"
      data-match-id={matchId}
      data-puuid={puuid}
      data-platform={platform}
      data-locale={locale}
      data-duration={String(matchDurationSeconds)}
    />
  ),
}));

import MatchDetailPage from "@/app/[locale]/matches/[matchId]/page";
import { ApiClientError, getMatchDetail } from "@/api/client";
import type { MatchDetailResponse, Platform } from "@/api/schemas";
import { MatchDetailClient } from "@/components/match-detail-client";

function participant(puuid: string, teamId: number, championId: number) {
  return {
    puuid,
    team_id: teamId,
    champion_id: championId,
    role: "MIDDLE",
    won: teamId === 100,
    kills: 7,
    deaths: 3,
    assists: 8,
    cs: 199,
    gold_earned: 12000,
    damage_to_champions: 18000,
    vision_score: 20,
    item_ids: [1055, 2003],
    champion: {
      entity_id: championId,
      name: championId === 103 ? "Ahri" : `Champion ${championId}`,
      image_url: `https://cdn.example/champions/${championId}.png`,
    },
    items: [
      { entity_id: 1055, name: "Doran's Blade", image_url: "https://cdn.example/items/1055.png" },
      { entity_id: 2003, name: "Health Potion", image_url: "https://cdn.example/items/2003.png" },
    ],
  };
}

const matchDetailFixture: MatchDetailResponse = {
  match_id: "NA1_123456789",
  platform: "NA1",
  queue_id: 420,
  started_at: "2026-07-30T12:00:00Z",
  duration_seconds: 1800,
  game_version: "16.15.1",
  selected_puuid: "selected-puuid",
  blue_team: [
    participant("selected-puuid", 100, 103),
    participant("blue-2", 100, 2),
    participant("blue-3", 100, 3),
    participant("blue-4", 100, 4),
    participant("blue-5", 100, 5),
  ],
  red_team: [
    participant("red-1", 200, 6),
    participant("red-2", 200, 7),
    participant("red-3", 200, 8),
    participant("red-4", 200, 9),
    participant("red-5", 200, 10),
  ],
  static_data_status: { available: true, version: "16.15.1", code: null },
  scope_notice_code: "DATA_ONLY_NO_COACHING",
  request_id: "request-detail-1",
};

const degradedMatchDetailFixture: MatchDetailResponse = {
  ...matchDetailFixture,
  static_data_status: { available: false, version: null, code: "STATIC_DATA_UNAVAILABLE" },
  blue_team: [
    {
      ...matchDetailFixture.blue_team[0],
      champion: null,
      items: [null, null],
    },
    ...matchDetailFixture.blue_team.slice(1),
  ],
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("MatchDetailClient", () => {
  it("renders two five-player teams and identifies the selected player", async () => {
    vi.mocked(getMatchDetail).mockResolvedValue(matchDetailFixture);
    render(<MatchDetailClient locale="en-US" matchId="NA1_123456789" puuid="selected-puuid" platform="NA1" />);

    expect(await screen.findByRole("heading", { name: /match details/i })).toBeVisible();
    expect(screen.getAllByRole("row")).toHaveLength(12);
    expect(screen.getByText("Selected player").closest("tr")).toHaveAttribute("data-selected", "true");
    expect(screen.getByText(/recorded match data only/i)).toBeVisible();
    expect(screen.queryByRole("button", { name: /generate review/i })).not.toBeInTheDocument();
    expect(screen.getByAltText("Champion: Ahri")).toHaveAttribute("src", "https://cdn.example/champions/103.png");
    expect(screen.getAllByAltText("Item: Doran's Blade")).not.toHaveLength(0);

    const replay = screen.getByTestId("replay-section");
    expect(replay).toHaveAttribute("data-match-id", "NA1_123456789");
    expect(replay).toHaveAttribute("data-puuid", "selected-puuid");
    expect(replay).toHaveAttribute("data-platform", "NA1");
    expect(replay).toHaveAttribute("data-locale", "en-US");
    expect(replay).toHaveAttribute("data-duration", "1800");
  });

  it("keeps internal participant IDs private and uses stable team-local labels", async () => {
    vi.mocked(getMatchDetail).mockResolvedValue(matchDetailFixture);
    const { container } = render(
      <MatchDetailClient locale="en-US" matchId="NA1_123456789" puuid="selected-puuid" platform="NA1" />,
    );

    expect(await screen.findByRole("heading", { name: /match details/i })).toBeVisible();
    for (const internalId of [
      "blue-2",
      "blue-3",
      "blue-4",
      "blue-5",
      "red-1",
      "red-2",
      "red-3",
      "red-4",
      "red-5",
    ]) {
      expect(container).not.toHaveTextContent(internalId);
    }
    expect(screen.getAllByText(/^Player [1-5]$/)).toHaveLength(9);
    expect(screen.getAllByText("Player 1")).toHaveLength(1);
    for (const number of [2, 3, 4, 5]) {
      expect(screen.getAllByText(`Player ${number}`)).toHaveLength(2);
    }
    expect(screen.getByText("Selected player").closest("tr")).toHaveAttribute("aria-current", "true");
  });

  it("localizes neutral participant labels in Chinese", async () => {
    vi.mocked(getMatchDetail).mockResolvedValue(matchDetailFixture);
    render(<MatchDetailClient locale="zh-CN" matchId="NA1_123456789" puuid="selected-puuid" platform="NA1" />);

    expect(await screen.findByRole("heading", { name: "对局详情" })).toBeVisible();
    expect(screen.getAllByText(/^玩家 [1-5]$/)).toHaveLength(9);
    expect(screen.getByText("已选择玩家").closest("tr")).toHaveAttribute("aria-current", "true");
  });

  it("keeps numeric data visible when static data is unavailable", async () => {
    vi.mocked(getMatchDetail).mockResolvedValue(degradedMatchDetailFixture);
    render(<MatchDetailClient locale="zh-CN" matchId="NA1_123456789" puuid="selected-puuid" platform="NA1" />);

    expect(await screen.findByText(/静态游戏数据暂不可用/)).toBeVisible();
    expect(screen.getAllByText("7 / 3 / 8")).not.toHaveLength(0);
    expect(screen.getByText("英雄 #103")).toBeVisible();
    expect(screen.getAllByText("装备 #1055")).not.toHaveLength(0);
    expect(screen.queryByAltText("Champion 2 英雄")).not.toBeInTheDocument();
  });

  it("shows localized loading and an actionable retry with safe request support", async () => {
    vi.mocked(getMatchDetail)
      .mockRejectedValueOnce(new ApiClientError("RIOT_RATE_LIMITED", { retry_after_seconds: 8 }, true, "request-429"))
      .mockResolvedValueOnce(matchDetailFixture);
    const user = userEvent.setup();
    render(<MatchDetailClient locale="zh-CN" matchId="NA1_123456789" puuid="selected-puuid" platform="NA1" />);

    expect(screen.getByRole("status")).toHaveTextContent("正在加载对局详情…");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Riot 服务繁忙，请在 8 秒后重试。");
    await user.click(screen.getByText("支持详情"));
    expect(screen.getByText("请求 ID：request-429")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByRole("heading", { name: "对局详情" })).toBeVisible();
    expect(getMatchDetail).toHaveBeenCalledTimes(2);
  });

  it("reports when the requested player is absent from the match", async () => {
    vi.mocked(getMatchDetail).mockResolvedValue({ ...matchDetailFixture, selected_puuid: "different-puuid" });
    render(<MatchDetailClient locale="en-US" matchId="NA1_123456789" puuid="selected-puuid" platform="NA1" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("This player is not in the match data.");
    expect(screen.queryByTestId("replay-section")).not.toBeInTheDocument();
  });

  it("does not show support details for a sanitized request ID on local player validation", async () => {
    vi.mocked(getMatchDetail).mockResolvedValue({
      ...matchDetailFixture,
      selected_puuid: "different-puuid",
      request_id: null,
    });
    render(<MatchDetailClient locale="en-US" matchId="NA1_123456789" puuid="selected-puuid" platform="NA1" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("This player is not in the match data.");
    expect(screen.queryByText("Support details")).not.toBeInTheDocument();
  });

  it("aborts a stale request before it can replace the newer match", async () => {
    let firstSignal: AbortSignal | undefined;
    vi.mocked(getMatchDetail)
      .mockImplementationOnce((_input, signal) => {
        firstSignal = signal;
        return new Promise(() => undefined);
      })
      .mockResolvedValueOnce({ ...matchDetailFixture, match_id: "NA1_new" });
    const view = render(<MatchDetailClient locale="en-US" matchId="NA1_old" puuid="selected-puuid" platform="NA1" />);
    view.rerender(<MatchDetailClient locale="en-US" matchId="NA1_new" puuid="selected-puuid" platform="NA1" />);

    await waitFor(() => expect(firstSignal?.aborted).toBe(true));
    expect(await screen.findByText(/NA1_new/)).toBeVisible();
  });
});

function detailFixtureFor(platform: Platform): MatchDetailResponse {
  return {
    ...matchDetailFixture,
    match_id: `${platform}_123456789`,
    platform,
  };
}

describe("MatchDetailClient platform propagation", () => {
  it.each(["EUW1", "KR"] as const)(
    "preserves %s for match-detail requests, display, and replay props",
    async (platform) => {
      const fixture = detailFixtureFor(platform);
      vi.mocked(getMatchDetail).mockResolvedValue(fixture);
      render(
        <MatchDetailClient
          locale="en-US"
          matchId={`${platform}_123456789`}
          puuid="selected-puuid"
          platform={platform}
        />,
      );

      expect(
        await screen.findByText(platform === "EUW1" ? /Europe West/ : /^Korea/),
      ).toBeVisible();
      expect(getMatchDetail).toHaveBeenCalledWith(
        expect.objectContaining({
          matchId: `${platform}_123456789`,
          platform,
          puuid: "selected-puuid",
        }),
        expect.any(AbortSignal),
      );
      expect(screen.getByTestId("replay-section")).toHaveAttribute("data-platform", platform);
      expect(screen.queryByText("NA1")).not.toBeInTheDocument();
    },
  );
});

describe("MatchDetailPage unknown platform rejection", () => {
  it("rejects an unknown platform query without falling back to NA1", async () => {
    await expect(
      MatchDetailPage({
        params: Promise.resolve({ locale: "en-US", matchId: "EUW1_1" }),
        searchParams: Promise.resolve({ platform: "XYZ1", puuid: "selected-puuid" }),
      }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
    expect(notFoundMock).toHaveBeenCalled();
    expect(getMatchDetail).not.toHaveBeenCalled();
  });
});
