import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  notFound: vi.fn(),
  useRouter: () => ({ push: vi.fn() }),
}));

import HomePage from "@/app/[locale]/page";

afterEach(() => cleanup());

describe("HomePage", () => {
  it("renders the localized Simplified Chinese post-game review eyebrow", async () => {
    render(
      await HomePage({ params: Promise.resolve({ locale: "zh-CN" }) }),
    );

    expect(screen.getByText("赛后复盘")).toBeVisible();
    expect(screen.queryByText("POST-GAME REVIEW")).not.toBeInTheDocument();
  });

  it("renders automatic detection search without a platform selector", async () => {
    render(await HomePage({ params: Promise.resolve({ locale: "en-US" }) }));

    expect(screen.getByLabelText("Riot ID")).toBeVisible();
    expect(screen.queryByLabelText("Region")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Find account" })).toBeVisible();
  });
});
