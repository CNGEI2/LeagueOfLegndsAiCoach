import { enUS } from "./en-US";
import { zhCN } from "./zh-CN";
import type { Locale } from "./locales";

export type Messages = { [Key in keyof typeof enUS]: string };

export function getMessages(locale: Locale): Messages {
  return locale === "zh-CN" ? zhCN : enUS;
}
