import { notFound } from "next/navigation";

import { LanguageSwitcher } from "@/components/language-switcher";
import { RiotSearchForm } from "@/components/riot-search-form";
import { getMessages } from "@/i18n/messages";
import { isLocale } from "@/i18n/locales";

export default async function HomePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const messages = getMessages(locale);

  return (
    <main>
      <header>
        <span className="brand">{messages.productName}</span>
        <LanguageSwitcher locale={locale} messages={messages} />
      </header>
      <section className="hero">
        <p className="eyebrow">POST-GAME REVIEW</p>
        <h1>{messages.headline}</h1>
        <p>{messages.description}</p>
        <RiotSearchForm messages={messages} />
      </section>
      <footer>{messages.disclaimer}</footer>
    </main>
  );
}
