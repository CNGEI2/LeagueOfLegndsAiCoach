import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { RiotSearchForm } from "@/components/riot-search-form";
import { getMessages } from "@/i18n/messages";

describe("RiotSearchForm", () => {
  it("renders the English fields and keeps Phase 1 submission local", async () => {
    const user = userEvent.setup();
    render(<RiotSearchForm messages={getMessages("en-US")} />);

    await user.type(screen.getByLabelText("Game Name"), "PlayerName");
    await user.type(screen.getByLabelText("Tag Line"), "NA1");
    expect(screen.getByLabelText("Region")).toHaveValue("NA1");

    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(
      screen.getByText("Riot API search will be added in Phase 2."),
    ).toBeVisible();
  });

  it("renders Simplified Chinese labels", () => {
    render(<RiotSearchForm messages={getMessages("zh-CN")} />);

    expect(screen.getByLabelText("游戏名称")).toBeVisible();
    expect(screen.getByRole("button", { name: "查询" })).toBeVisible();
  });
});
