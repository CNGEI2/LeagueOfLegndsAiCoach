export const locales = ["zh-CN", "en-US"] as const;
export type Locale = (typeof locales)[number];

export function isLocale(value: string): value is Locale {
  return locales.includes(value as Locale);
}

export function resolveLocale(acceptLanguage: string | null): Locale {
  if (!acceptLanguage) return "en-US";
  const normalized = acceptLanguage.toLowerCase();
  return normalized.includes("zh-cn") || normalized.startsWith("zh")
    ? "zh-CN"
    : "en-US";
}
