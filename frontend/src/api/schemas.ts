import { z } from "zod";

export const localeSchema = z.enum(["zh-CN", "en-US"]);
export const platformSchema = z.enum(["NA1"]);

export const staticAssetSchema = z
  .object({
    entity_id: z.number().int(),
    name: z.string(),
    image_url: z.string().url(),
  })
  .strict();

export const staticDataStatusSchema = z
  .object({
    available: z.boolean(),
    version: z.string().nullable(),
    code: z.string().nullable(),
  })
  .strict();

export const playerProfileSchema = z
  .object({
    puuid: z.string(),
    game_name: z.string(),
    tag_line: z.string(),
    platform: platformSchema,
    summoner_level: z.number().int(),
    profile_icon_id: z.number().int(),
    profile_icon: staticAssetSchema.nullable(),
    profile_static_data_status: staticDataStatusSchema,
  })
  .strict();

export const participantSnapshotSchema = z
  .object({
    puuid: z.string(),
    team_id: z.number().int(),
    champion_id: z.number().int(),
    role: z.string().nullable(),
    won: z.boolean(),
    kills: z.number().int().nullable(),
    deaths: z.number().int().nullable(),
    assists: z.number().int().nullable(),
    cs: z.number().int().nullable(),
    gold_earned: z.number().int().nullable(),
    damage_to_champions: z.number().int().nullable(),
    vision_score: z.number().int().nullable(),
    item_ids: z.array(z.number().int()),
  })
  .strict();

export const hydratedParticipantSchema = participantSnapshotSchema
  .extend({
    champion: staticAssetSchema.nullable(),
    items: z.array(staticAssetSchema.nullable()),
  })
  .strict()
  .superRefine((participant, context) => {
    if (participant.item_ids.length !== participant.items.length) {
      context.addIssue({
        code: "custom",
        message: "items must align with item_ids",
      });
    }
  });

export const recentMatchItemSchema = z
  .object({
    match_id: z.string(),
    platform: platformSchema,
    queue_id: z.number().int(),
    started_at: z.string().datetime({ offset: true }),
    duration_seconds: z.number().int(),
    game_version: z.string(),
    participant: hydratedParticipantSchema,
    analysis_supported: z.boolean(),
    unsupported_reason_code: z.string().nullable(),
    detail_supported: z.boolean(),
    detail_unavailable_reason_code: z.string().nullable(),
    static_data_status: staticDataStatusSchema,
  })
  .strict();

export const resolvePlayerResponseSchema = z
  .object({
    player: playerProfileSchema,
    request_id: z.string(),
  })
  .strict();

export const recentMatchesResponseSchema = z
  .object({
    player: playerProfileSchema,
    matches: z.array(recentMatchItemSchema),
    request_id: z.string(),
  })
  .strict();

export const matchDetailResponseSchema = z
  .object({
    match_id: z.string(),
    platform: platformSchema,
    queue_id: z.number().int(),
    started_at: z.string().datetime({ offset: true }),
    duration_seconds: z.number().int(),
    game_version: z.string(),
    selected_puuid: z.string(),
    blue_team: z.array(hydratedParticipantSchema).length(5),
    red_team: z.array(hydratedParticipantSchema).length(5),
    static_data_status: staticDataStatusSchema,
    scope_notice_code: z.literal("DATA_ONLY_NO_COACHING"),
    request_id: z.string(),
  })
  .strict();

export const errorResponseSchema = z
  .object({
    error: z
      .object({
        code: z.string(),
        message: z.string(),
        params: z.record(z.string(), z.unknown()),
        retryable: z.boolean(),
        request_id: z.string(),
      })
      .strict(),
  })
  .strict();

export type PlayerProfile = z.infer<typeof playerProfileSchema>;
export type HydratedParticipant = z.infer<typeof hydratedParticipantSchema>;
export type RecentMatchItem = z.infer<typeof recentMatchItemSchema>;
export type RecentMatchesResponse = z.infer<typeof recentMatchesResponseSchema>;
export type MatchDetailResponse = z.infer<typeof matchDetailResponseSchema>;
