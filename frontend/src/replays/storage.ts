import { z } from "zod";

import { replayStatusSchema, type ReplayStatus } from "@/api/schemas";

const CAPABILITY_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
export const STORAGE_KEY_PREFIX = "lol-ai-coach:replay:";

const replayCapabilitySchema = z
  .object({
    replayId: z.string().min(1),
    accessToken: z.string().min(1),
    matchId: z.string().min(1),
    updatedAt: z.string().datetime({ offset: true }),
    status: replayStatusSchema.nullable().optional(),
  })
  .strict()
  .transform((value) => ({
    replayId: value.replayId,
    accessToken: value.accessToken,
    matchId: value.matchId,
    updatedAt: value.updatedAt,
    status: value.status ?? null,
  }));

export type ReplayCapability = z.infer<typeof replayCapabilitySchema>;

export type ReplayCapabilityInput = {
  replayId: string;
  accessToken: string;
  matchId: string;
  updatedAt: string;
  status?: ReplayStatus | null;
  puuid?: unknown;
  fileName?: unknown;
  uploadUrl?: unknown;
};

function storageKey(replayId: string): string {
  return `${STORAGE_KEY_PREFIX}${replayId}`;
}

export function saveReplayCapability(input: ReplayCapabilityInput): void {
  const capability: ReplayCapability = {
    replayId: input.replayId,
    accessToken: input.accessToken,
    matchId: input.matchId,
    updatedAt: input.updatedAt,
    status: input.status ?? null,
  };
  localStorage.setItem(storageKey(capability.replayId), JSON.stringify(capability));
}

export function loadReplayCapability(replayId: string): ReplayCapability | null {
  const key = storageKey(replayId);
  const raw = localStorage.getItem(key);
  if (raw === null) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    localStorage.removeItem(key);
    return null;
  }

  const result = replayCapabilitySchema.safeParse(parsed);
  if (!result.success) {
    localStorage.removeItem(key);
    return null;
  }

  const updatedAtMs = Date.parse(result.data.updatedAt);
  if (!Number.isFinite(updatedAtMs) || Date.now() - updatedAtMs > CAPABILITY_MAX_AGE_MS) {
    localStorage.removeItem(key);
    return null;
  }

  return result.data;
}

export function removeReplayCapability(replayId: string): void {
  localStorage.removeItem(storageKey(replayId));
}

export function findReplayCapabilityForMatch(
  matchId: string,
  requiredStatus?: ReplayStatus,
): ReplayCapability | null {
  const keys: string[] = [];
  for (let index = 0; index < localStorage.length; index += 1) {
    const key = localStorage.key(index);
    if (key?.startsWith(STORAGE_KEY_PREFIX)) {
      keys.push(key);
    }
  }

  let best: ReplayCapability | null = null;
  for (const key of keys) {
    const capability = loadReplayCapability(key.slice(STORAGE_KEY_PREFIX.length));
    if (!capability || capability.matchId !== matchId) continue;
    if (requiredStatus !== undefined && capability.status !== requiredStatus) continue;
    if (!best || Date.parse(capability.updatedAt) > Date.parse(best.updatedAt)) {
      best = capability;
    }
  }
  return best;
}
