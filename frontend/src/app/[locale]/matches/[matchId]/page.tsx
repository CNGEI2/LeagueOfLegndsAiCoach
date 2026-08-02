import { notFound } from "next/navigation";

import { platformSchema } from "@/api/schemas";
import { MatchDetailClient } from "@/components/match-detail-client";
import { isLocale } from "@/i18n/locales";

export default async function MatchDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string; matchId: string }>;
  searchParams: Promise<{ platform?: string; puuid?: string }>;
}) {
  const [{ locale, matchId }, { platform: rawPlatform, puuid }] = await Promise.all([
    params,
    searchParams,
  ]);
  const parsedPlatform = platformSchema.safeParse(rawPlatform);
  if (!isLocale(locale) || !parsedPlatform.success || !puuid) notFound();
  return (
    <MatchDetailClient
      locale={locale}
      matchId={matchId}
      puuid={puuid}
      platform={parsedPlatform.data}
    />
  );
}
