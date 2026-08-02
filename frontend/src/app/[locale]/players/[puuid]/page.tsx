import { notFound } from "next/navigation";

import { platformSchema } from "@/api/schemas";
import { PlayerPageClient } from "@/components/player-page-client";
import { isLocale } from "@/i18n/locales";

export default async function PlayerPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string; puuid: string }>;
  searchParams: Promise<{ platform?: string }>;
}) {
  const [{ locale, puuid }, { platform: rawPlatform }] = await Promise.all([params, searchParams]);
  const parsedPlatform = platformSchema.safeParse(rawPlatform);
  if (!isLocale(locale) || !puuid || !parsedPlatform.success) notFound();

  return <PlayerPageClient locale={locale} puuid={puuid} platform={parsedPlatform.data} />;
}
