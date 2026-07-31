import { notFound } from "next/navigation";

import { MatchDetailClient } from "@/components/match-detail-client";
import { isLocale } from "@/i18n/locales";

export default async function MatchDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string; matchId: string }>;
  searchParams: Promise<{ platform?: string; puuid?: string }>;
}) {
  const [{ locale, matchId }, { platform, puuid }] = await Promise.all([params, searchParams]);
  if (!isLocale(locale) || platform !== "NA1" || !puuid) notFound();
  return <MatchDetailClient locale={locale} matchId={matchId} puuid={puuid} platform="NA1" />;
}
