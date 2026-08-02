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

  it("includes replay R1 bilingual copy without coaching conclusions", () => {
    const en = getMessages("en-US");
    const zh = getMessages("zh-CN");

    expect(en.uploadReplay).toMatch(/upload replay/i);
    expect(zh.uploadReplay).toBe("上传本局录像");
    expect(en.replayNoAiNotice).toMatch(/no AI coaching conclusions/i);
    expect(zh.replayNoAiNotice).toMatch(/尚未.*AI.*结论|没有.*AI.*结论/);
    expect(en.verificationFrame).toBe("Verification frame");
    expect(zh.verificationFrame).toBe("验证帧");
    expect(zh.replayNotFound).toBe("回放不存在或访问已失效");
    expect(en.verificationFrame.toLowerCase()).not.toMatch(/mistake|fight/);
    expect(zh.verificationFrame).not.toMatch(/失误|团战/);
  });

  it("includes platform auto-detection bilingual copy", () => {
    const en = getMessages("en-US");
    const zh = getMessages("zh-CN");

    expect(en.riotId).toBe("Riot ID");
    expect(zh.riotId).toBe("Riot ID");
    expect(en.riotIdExample).toContain("CNGEI#1115");
    expect(zh.riotIdExample).toContain("CNGEI#1115");
    expect(en.tagIsNotServer.toLowerCase()).toMatch(/not the game server/);
    expect(zh.tagIsNotServer).toMatch(/不是服务器/);
    expect(en.detectAccount).toBe("Find account");
    expect(zh.detectAccount).toBe("识别账号");
    expect(en.chooseServer).toBe("Choose your server");
    expect(zh.chooseServer).toBe("选择服务器");
    expect(en.detectionUnavailable.toLowerCase()).toMatch(/temporarily unavailable/);
    expect(zh.confirmationExpired).toMatch(/过期/);
  });
});
