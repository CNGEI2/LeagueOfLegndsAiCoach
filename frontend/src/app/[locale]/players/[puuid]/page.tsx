import { notFound } from "next/navigation";

import { PlayerPageClient } from "@/components/player-page-client";
import { isLocale } from "@/i18n/locales";

export default async function PlayerPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string; puuid: string }>;
  searchParams: Promise<{ platform?: string }>;
}) {
  const [{ locale, puuid }, { platform }] = await Promise.all([params, searchParams]);
  if (!isLocale(locale) || !puuid || platform !== "NA1") notFound();

  return <PlayerPageClient locale={locale} puuid={puuid} platform="NA1" />;
}
