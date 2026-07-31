import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DataState } from "@/components/data-state";
import { getMessages } from "@/i18n/messages";

afterEach(cleanup);

describe("DataState", () => {
  it("uses the requested loading copy instead of always calling it a match list", () => {
    render(<DataState state="loading" loadingMessage={getMessages("en-US").loadingMatchDetail} messages={getMessages("en-US")} />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading match details…");
  });

  it("interpolates a finite rate-limit retry delay and omits unknown delay values", () => {
    const { rerender } = render(
      <DataState
        state="error"
        errorCode="RIOT_RATE_LIMITED"
        errorParams={{ retry_after_seconds: 4 }}
        messages={getMessages("zh-CN")}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("4 秒");

    rerender(
      <DataState
        state="error"
        errorCode="RIOT_RATE_LIMITED"
        errorParams={{ retry_after_seconds: "not-a-number" }}
        messages={getMessages("zh-CN")}
      />,
    );
    expect(screen.getByRole("alert")).not.toHaveTextContent("a few");
    expect(screen.getByRole("alert")).toHaveTextContent("Riot 服务繁忙，请稍后重试。");
  });
});
