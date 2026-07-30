import Link from "next/link";

import type { Locale } from "@/i18n/locales";
import type { Messages } from "@/i18n/messages";

export function LanguageSwitcher({
  locale,
  messages,
}: {
  locale: Locale;
  messages: Messages;
}) {
  const target = locale === "zh-CN" ? "en-US" : "zh-CN";
  return (
    <nav aria-label={messages.language}>
      <Link href={`/${target}`} hrefLang={target}>
        {target === "zh-CN" ? "中文" : "English"}
      </Link>
    </nav>
  );
}
