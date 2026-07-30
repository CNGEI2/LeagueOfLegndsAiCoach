export const locales = ["zh-CN", "en-US"] as const;
export type Locale = (typeof locales)[number];
export const DEFAULT_LOCALE: Locale = "en-US";

export function isLocale(value: string): value is Locale {
  return locales.includes(value as Locale);
}

export function resolveLocale(acceptLanguage: string | null): Locale {
  if (!acceptLanguage) return DEFAULT_LOCALE;

  const preferences = acceptLanguage
    .split(",")
    .map((value, index) => {
      const [language, ...parameters] = value.trim().toLowerCase().split(";");
      const quality = parameters.find((parameter) => parameter.trim().startsWith("q="));
      const parsedQuality = quality ? Number(quality.trim().slice(2)) : 1;
      const q =
        Number.isFinite(parsedQuality) && parsedQuality >= 0 && parsedQuality <= 1
          ? parsedQuality
          : 0;
      return { language, q, index };
    })
    .filter(({ q }) => q > 0)
    .sort((left, right) => right.q - left.q || left.index - right.index);

  for (const { language } of preferences) {
    if (language === "zh" || language === "zh-cn") return "zh-CN";
    if (language === "en" || language === "en-us") return "en-US";
  }

  return DEFAULT_LOCALE;
}
