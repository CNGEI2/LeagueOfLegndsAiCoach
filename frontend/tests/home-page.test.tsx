import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import HomePage from "@/app/[locale]/page";

describe("HomePage", () => {
  it("renders the localized Simplified Chinese post-game review eyebrow", async () => {
    render(
      await HomePage({ params: Promise.resolve({ locale: "zh-CN" }) }),
    );

    expect(screen.getByText("赛后复盘")).toBeVisible();
    expect(screen.queryByText("POST-GAME REVIEW")).not.toBeInTheDocument();
  });
});
