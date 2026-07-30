export const locales = ["zh-CN", "en-US"] as const;
export type Locale = (typeof locales)[number];
export const DEFAULT_LOCALE: Locale = "en-US";

export function isLocale(value: string): value is Locale {
  return locales.includes(value as Locale);
}

function localeForLanguage(language: string): Locale | undefined {
  if (language === "zh" || language === "zh-cn") return "zh-CN";
  if (language === "en" || language === "en-us") return "en-US";
  return undefined;
}

function isSpecificLocale(language: string): boolean {
  return language === "zh-cn" || language === "en-us";
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
    });

  const disabledLocales = new Set(
    preferences.flatMap(({ language, q }) =>
      q === 0 && isSpecificLocale(language) ? [localeForLanguage(language)] : [],
    ),
  );

  const candidates = preferences
    .filter(({ q }) => q > 0)
    .map(({ language, q, index }) => ({ locale: localeForLanguage(language), q, index }))
    .filter(
      (candidate): candidate is { locale: Locale; q: number; index: number } =>
        candidate.locale !== undefined && !disabledLocales.has(candidate.locale),
    )
    .sort((left, right) => right.q - left.q || left.index - right.index);

  for (const { locale } of candidates) {
    return locale;
  }

  return DEFAULT_LOCALE;
}
