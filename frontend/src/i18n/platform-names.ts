import type { Platform } from "@/api/schemas";
import type { Locale } from "@/i18n/locales";

/** Page-decoration labels only. Detection candidates must use backend display_name. */
export const PLATFORM_NAMES: Record<Locale, Record<Platform, string>> = {
  "en-US": {
    BR1: "Brazil",
    EUN1: "Europe Nordic & East",
    EUW1: "Europe West",
    JP1: "Japan",
    KR: "Korea",
    LA1: "Latin America North",
    LA2: "Latin America South",
    NA1: "North America",
    OC1: "Oceania",
    TR1: "Türkiye",
    RU: "Russia",
    PH2: "Philippines",
    SG2: "Singapore",
    TH2: "Thailand",
    TW2: "Taiwan",
    VN2: "Vietnam",
  },
  "zh-CN": {
    BR1: "巴西服",
    EUN1: "欧东北服",
    EUW1: "欧西服",
    JP1: "日服",
    KR: "韩服",
    LA1: "拉丁美洲北服",
    LA2: "拉丁美洲南服",
    NA1: "北美服",
    OC1: "大洋洲服",
    TR1: "土耳其服",
    RU: "俄服",
    PH2: "菲律宾服",
    SG2: "新加坡服",
    TH2: "泰国服",
    TW2: "台服",
    VN2: "越南服",
  },
};

export function platformDisplayName(locale: Locale, platform: Platform): string {
  return PLATFORM_NAMES[locale][platform];
}
