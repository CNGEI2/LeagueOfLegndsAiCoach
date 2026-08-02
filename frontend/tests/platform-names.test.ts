import { describe, expect, it } from "vitest";

import { platformSchema, type Platform } from "@/api/schemas";
import { PLATFORM_NAMES, platformDisplayName } from "@/i18n/platform-names";

const PLATFORMS = platformSchema.options;

describe("platform display names", () => {
  it("covers exactly the 16 closed Platform values in both locales", () => {
    expect(PLATFORMS).toHaveLength(16);
    expect(Object.keys(PLATFORM_NAMES["en-US"]).sort()).toEqual([...PLATFORMS].sort());
    expect(Object.keys(PLATFORM_NAMES["zh-CN"]).sort()).toEqual([...PLATFORMS].sort());
  });

  it("uses the Task 1 catalog names for EUW1 and KR", () => {
    expect(platformDisplayName("en-US", "EUW1")).toBe("Europe West");
    expect(platformDisplayName("zh-CN", "EUW1")).toBe("欧西服");
    expect(platformDisplayName("en-US", "KR")).toBe("Korea");
    expect(platformDisplayName("zh-CN", "KR")).toBe("韩服");
  });

  it("never invents a missing platform entry", () => {
    for (const locale of ["en-US", "zh-CN"] as const) {
      for (const platform of PLATFORMS as Platform[]) {
        expect(PLATFORM_NAMES[locale][platform].length).toBeGreaterThan(0);
      }
    }
  });
});
