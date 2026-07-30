import { describe, expect, it } from "vitest";

import { getMessages } from "@/i18n/messages";
import { resolveLocale } from "@/i18n/locales";

describe("locale resolution", () => {
  it("honors an English preference ahead of Chinese", () => {
    expect(resolveLocale("en-US,en;q=0.9,zh-CN;q=0.8")).toBe("en-US");
  });

  it("selects Simplified Chinese when it is preferred", () => {
    expect(resolveLocale("zh-CN,zh;q=0.9,en;q=0.8")).toBe("zh-CN");
  });

  it("falls back to English for unsupported languages", () => {
    expect(resolveLocale("fr-FR,fr;q=0.9")).toBe("en-US");
  });

  it("does not select a locale disabled with q=0", () => {
    expect(resolveLocale("zh-CN;q=0,en-US;q=0.8")).toBe("en-US");
  });

  it("does not let a Chinese parent preference re-enable disabled zh-CN", () => {
    expect(resolveLocale("zh-CN;q=0,zh;q=1,en-US;q=0.5")).toBe("en-US");
  });

  it("does not let an English parent preference re-enable disabled en-US", () => {
    expect(resolveLocale("en-US;q=0,en;q=1,zh-CN;q=0.5")).toBe("zh-CN");
  });

  it("ignores an out-of-range quality value", () => {
    expect(resolveLocale("zh-CN;q=1.2,en-US;q=0.8")).toBe("en-US");
  });
});

describe("message catalogs", () => {
  it("contain exactly the same required keys", () => {
    expect(Object.keys(getMessages("zh-CN")).sort()).toEqual(
      Object.keys(getMessages("en-US")).sort(),
    );
  });
});
