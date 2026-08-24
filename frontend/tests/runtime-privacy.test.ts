import { describe, expect, it } from "vitest";

import nextConfig from "../next.config";

describe("frontend runtime privacy", () => {
  it("disables incoming development request logs that can expose route identifiers", () => {
    expect(nextConfig.logging).toMatchObject({ incomingRequests: false });
  });
});
