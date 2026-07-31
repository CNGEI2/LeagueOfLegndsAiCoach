import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { RecentMatchItem } from "@/api/schemas";
import { RecentMatchCard } from "@/components/recent-match-card";
import { getMessages } from "@/i18n/messages";

const baseMatch: RecentMatchItem = {
  match_id: "NA1_3",
  platform: "NA1",
  queue_id: 420,
  started_at: "2026-07-30T12:00:00Z",
  duration_seconds: 1800,
  game_version: "16.15.1",
  participant: {
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
      {
        entity_id: 1055,
        name: "Doran's Blade",
        image_url: "https://cdn.example/items/1055.png",
      },
      null,
    ],
  },
  analysis_supported: true,
  unsupported_reason_code: null,
  detail_supported: true,
  detail_unavailable_reason_code: null,
  static_data_status: { available: true, version: "16.15.1", code: null },
};

afterEach(cleanup);

describe("RecentMatchCard", () => {
  it("renders localized champion and item assets with gameplay statistics", () => {
    render(
      <RecentMatchCard
        locale="en-US"
        puuid="puuid-1"
        match={baseMatch}
        messages={getMessages("en-US")}
      />,
    );

    expect(screen.getByAltText("Champion: Ahri")).toHaveAttribute(
      "src",
      "https://cdn.example/champions/103.png",
    );
    expect(screen.getByAltText("Item: Doran's Blade")).toHaveAttribute(
      "src",
      "https://cdn.example/items/1055.png",
    );
    expect(screen.getByText("Item #0")).toBeVisible();
    expect(screen.getByText("K/D/A: 8 / 2 / 6")).toBeVisible();
    expect(screen.getByText("CS: 201")).toBeVisible();
  });

  it("marks the match-detail navigation as a dedicated 44px touch action", () => {
    render(
      <RecentMatchCard
        locale="en-US"
        puuid="puuid-1"
        match={baseMatch}
        messages={getMessages("en-US")}
      />,
    );

    expect(screen.getByRole("link", { name: "View match details" })).toHaveClass(
      "match-detail-link",
    );
  });

  it("keeps numeric fallbacks and typed unavailable statistics visible without static assets", () => {
    render(
      <RecentMatchCard
        locale="zh-CN"
        puuid="puuid-1"
        match={{
          ...baseMatch,
          participant: {
            ...baseMatch.participant,
            champion: null,
            items: [null, null],
            kills: null,
            deaths: null,
            assists: null,
            cs: null,
          },
        }}
        messages={getMessages("zh-CN")}
      />,
    );

    expect(screen.getByText("英雄 #103")).toBeVisible();
    expect(screen.getByText("装备 #1055")).toBeVisible();
    expect(screen.getByText("装备 #0")).toBeVisible();
    expect(screen.getByText("K/D/A: 暂无数据")).toBeVisible();
    expect(screen.getByText("补刀: 暂无数据")).toBeVisible();
  });
});
