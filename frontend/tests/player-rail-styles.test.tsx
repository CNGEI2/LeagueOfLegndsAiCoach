import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { cleanup, render, screen } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import type { PlayerProfile, RecentMatchItem } from "@/api/schemas";
import { PlayerHeader } from "@/components/player-header";
import { RecentMatchList } from "@/components/recent-match-list";
import { getMessages } from "@/i18n/messages";

const player: PlayerProfile = {
  puuid: "selected-puuid",
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
};

const match: RecentMatchItem = {
  match_id: "NA1_3",
  platform: "NA1",
  queue_id: 420,
  started_at: "2026-07-30T12:00:00Z",
  duration_seconds: 1800,
  game_version: "16.15.1",
  participant: {
    puuid: "selected-puuid",
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
    item_ids: [1055],
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
    ],
  },
  analysis_supported: true,
  unsupported_reason_code: null,
  detail_supported: true,
  detail_unavailable_reason_code: null,
  static_data_status: { available: true, version: "16.15.1", code: null },
};

const styleElement = document.createElement("style");

beforeAll(() => {
  const stylesheetPath = resolve(process.cwd(), "src/app/globals.css");
  styleElement.textContent = readFileSync(stylesheetPath, "utf8").replace(
    '@import "tailwindcss";',
    "",
  );
  document.head.append(styleElement);
});

afterEach(cleanup);
afterAll(() => styleElement.remove());

describe("player evidence presentation", () => {
  it("constrains the profile image inside a restrained player header", () => {
    render(<PlayerHeader player={player} messages={getMessages("en-US")} />);

    const imageStyle = getComputedStyle(screen.getByAltText("Profile icon for PlayerName"));
    expect(imageStyle.width).toBe("88px");
    expect(imageStyle.height).toBe("88px");
    expect(imageStyle.objectFit).toBe("cover");
  });

  it("renders recent matches as a chronological evidence rail with bounded assets", () => {
    render(
      <RecentMatchList
        locale="en-US"
        puuid="selected-puuid"
        matches={[match]}
        messages={getMessages("en-US")}
      />,
    );

    const rail = screen.getByRole("list", { name: "" });
    expect(getComputedStyle(rail).listStyle).toBe("none");
    expect(getComputedStyle(screen.getByTestId("recent-match-card")).display).toBe("grid");
    expect(
      getComputedStyle(screen.getByTestId("recent-match-card").querySelector(".match-slip-marker")!),
    ).toHaveProperty("position", "absolute");
    expect(getComputedStyle(screen.getByAltText("Champion: Ahri")).width).toBe("56px");
    expect(getComputedStyle(screen.getByAltText("Item: Doran's Blade")).width).toBe("28px");
  });

  it("defines a narrow-screen single-column slip without hiding evidence", () => {
    const stylesheet = styleElement.sheet;
    expect(stylesheet).not.toBeNull();
    const mobileRule = Array.from(stylesheet!.cssRules).find(
      (rule): rule is CSSMediaRule =>
        "conditionText" in rule && rule.conditionText === "(max-width: 720px)",
    );
    const mobileSlip = Array.from(mobileRule?.cssRules ?? []).find(
      (rule): rule is CSSStyleRule => "selectorText" in rule && rule.selectorText === ".match-slip",
    );

    expect(mobileSlip?.style.getPropertyValue("grid-template-columns")).toBe("1fr");
  });
});
