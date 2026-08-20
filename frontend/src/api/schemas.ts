import { z } from "zod";

export const localeSchema = z.enum(["zh-CN", "en-US"]);
export const platformSchema = z.enum([
  "BR1",
  "EUN1",
  "EUW1",
  "JP1",
  "KR",
  "LA1",
  "LA2",
  "NA1",
  "OC1",
  "TR1",
  "RU",
  "PH2",
  "SG2",
  "TH2",
  "TW2",
  "VN2",
]);
export type Platform = z.infer<typeof platformSchema>;
const requestIdPattern = /^[0-9a-f]{32}$/;
const requestIdSchema = z.string().transform((value) => (requestIdPattern.test(value) ? value : null));

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
    request_id: requestIdSchema,
  })
  .strict();

export const platformCandidateSchema = z
  .object({
    platform: platformSchema,
    display_name: z.string().min(1),
  })
  .strict();

export const resolvedDetectionResponseSchema = z
  .object({
    status: z.literal("resolved"),
    player: playerProfileSchema,
    request_id: requestIdSchema,
  })
  .strict();

export const confirmationRequiredResponseSchema = z
  .object({
    status: z.literal("confirmation_required"),
    detection_id: z.string().uuid(),
    expires_at: z.string().datetime({ offset: true }),
    candidates: z.array(platformCandidateSchema).min(1),
    request_id: requestIdSchema,
  })
  .strict();

export const detectPlayerResponseSchema = z.discriminatedUnion("status", [
  resolvedDetectionResponseSchema,
  confirmationRequiredResponseSchema,
]);

export const recentMatchesResponseSchema = z
  .object({
    player: playerProfileSchema,
    matches: z.array(recentMatchItemSchema),
    request_id: requestIdSchema,
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
    request_id: requestIdSchema,
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

export const replayStatusSchema = z.enum([
  "created",
  "uploaded",
  "queued",
  "probing",
  "transcoding",
  "extracting",
  "ready",
  "failed",
  "expired",
  "deleting",
  "deleted",
]);

export const replayArtifactKindSchema = z.enum(["anchor_frame", "verification_frame"]);

export const replayUploadInfoSchema = z
  .object({
    method: z.string(),
    url: z.string(),
    headers: z.record(z.string(), z.string()),
    expires_at: z.string().datetime({ offset: true }),
  })
  .strict();

export const replayRetentionInfoSchema = z
  .object({
    source_hours_after_processing: z.number().int(),
    derived_days_after_ready: z.number().int(),
  })
  .strict();

export const replayCreateResponseSchema = z
  .object({
    replay_id: z.string().uuid(),
    access_token: z.string(),
    status: replayStatusSchema,
    upload: replayUploadInfoSchema,
    retention: replayRetentionInfoSchema,
    request_id: requestIdSchema,
  })
  .strict();

export const replayStatusResponseSchema = z
  .object({
    replay_id: z.string().uuid(),
    status: replayStatusSchema,
    processing_stage: z.string().nullable(),
    progress_percent: z.number().int(),
    normalized_duration_ms: z.number().int().nullable(),
    width: z.number().int().nullable(),
    height: z.number().int().nullable(),
    available_game_time_start_ms: z.number().int().nullable(),
    available_game_time_end_ms: z.number().int().nullable(),
    warning_codes: z.array(z.string()),
    error_code: z.string().nullable(),
    error_retryable: z.boolean().nullable(),
    source_delete_after: z.string().datetime({ offset: true }).nullable(),
    derived_delete_after: z.string().datetime({ offset: true }).nullable(),
    request_id: requestIdSchema,
  })
  .strict();

export const replayArtifactAccessSchema = z
  .object({
    mode: z.enum(["bearer", "presigned"]),
    url: z.string(),
    expires_at: z.string().datetime({ offset: true }),
  })
  .strict();

export const replayArtifactSchema = z
  .object({
    artifact_id: z.string().uuid(),
    replay_id: z.string().uuid(),
    kind: replayArtifactKindSchema,
    game_time_ms: z.number().int(),
    video_time_ms: z.number().int(),
    media_type: z.string(),
    width: z.number().int().nullable(),
    height: z.number().int().nullable(),
    size_bytes: z.number().int(),
    access: replayArtifactAccessSchema,
  })
  .strict();

export const replayArtifactsResponseSchema = z
  .object({
    artifacts: z.array(replayArtifactSchema),
    request_id: requestIdSchema,
  })
  .strict();

export const evidenceRelationshipSchema = z.enum([
  "killer",
  "victim",
  "assistant",
  "actor",
  "team_context",
  "not_involved",
]);

const evidenceFactBaseSchema = {
  fact_id: z.string(),
  timestamp_ms: z.number().int(),
  relationship: evidenceRelationshipSchema,
};

export const championKillFactSchema = z
  .object({
    ...evidenceFactBaseSchema,
    kind: z.literal("champion_kill"),
    killer_id: z.number().int(),
    victim_id: z.number().int(),
    assisting_participant_ids: z.array(z.number().int()),
    position_x: z.number().int().nullable(),
    position_y: z.number().int().nullable(),
  })
  .strict();

export const eliteMonsterKillFactSchema = z
  .object({
    ...evidenceFactBaseSchema,
    kind: z.literal("elite_monster_kill"),
    killer_id: z.number().int(),
    killer_team_id: z.number().int(),
    monster_type: z.string(),
    monster_sub_type: z.string().nullable(),
    position_x: z.number().int().nullable(),
    position_y: z.number().int().nullable(),
  })
  .strict();

export const buildingKillFactSchema = z
  .object({
    ...evidenceFactBaseSchema,
    kind: z.literal("building_kill"),
    killer_id: z.number().int(),
    team_id: z.number().int(),
    building_type: z.string(),
    lane_type: z.string().nullable(),
    tower_type: z.string().nullable(),
    position_x: z.number().int().nullable(),
    position_y: z.number().int().nullable(),
  })
  .strict();

export const itemPurchasedFactSchema = z
  .object({
    ...evidenceFactBaseSchema,
    kind: z.literal("item_purchased"),
    participant_id: z.number().int(),
    item_id: z.number().int(),
    item_name: z.string().nullable(),
    item_image_url: z.string().url().nullable(),
  })
  .strict();

export const itemSoldFactSchema = z
  .object({
    ...evidenceFactBaseSchema,
    kind: z.literal("item_sold"),
    participant_id: z.number().int(),
    item_id: z.number().int(),
    item_name: z.string().nullable(),
    item_image_url: z.string().url().nullable(),
  })
  .strict();

export const itemDestroyedFactSchema = z
  .object({
    ...evidenceFactBaseSchema,
    kind: z.literal("item_destroyed"),
    participant_id: z.number().int(),
    item_id: z.number().int(),
    item_name: z.string().nullable(),
    item_image_url: z.string().url().nullable(),
  })
  .strict();

export const itemUndoFactSchema = z
  .object({
    ...evidenceFactBaseSchema,
    kind: z.literal("item_undo"),
    participant_id: z.number().int(),
    before_id: z.number().int(),
    after_id: z.number().int(),
    before_item_name: z.string().nullable(),
    before_item_image_url: z.string().url().nullable(),
    after_item_name: z.string().nullable(),
    after_item_image_url: z.string().url().nullable(),
  })
  .strict();

export const participantStateFactSchema = z
  .object({
    ...evidenceFactBaseSchema,
    kind: z.literal("participant_state"),
    participant_id: z.number().int(),
    level: z.number().int(),
    current_gold: z.number().int(),
    total_gold: z.number().int(),
    minions_killed: z.number().int(),
    jungle_minions_killed: z.number().int(),
    xp: z.number().int(),
    position_x: z.number().int().nullable(),
    position_y: z.number().int().nullable(),
  })
  .strict();

export const timelineFactSchema = z.discriminatedUnion("kind", [
  championKillFactSchema,
  eliteMonsterKillFactSchema,
  buildingKillFactSchema,
  itemPurchasedFactSchema,
  itemSoldFactSchema,
  itemDestroyedFactSchema,
  itemUndoFactSchema,
  participantStateFactSchema,
]);

export const evidenceCategorySchema = z.enum([
  "combat_context",
  "death_context",
  "objective_context",
  "building_context",
]);

export const evidenceCoverageSchema = z.enum(["full", "partial", "unavailable"]);

export const evidenceArtifactReferenceSchema = z
  .object({
    artifact_id: z.string().uuid(),
    kind: replayArtifactKindSchema,
    game_time_ms: z.number().int(),
    video_time_ms: z.number().int(),
  })
  .strict();

export const evidenceWindowSchema = z
  .object({
    window_id: z.string(),
    start_ms: z.number().int(),
    end_ms: z.number().int(),
    categories: z.array(evidenceCategorySchema),
    trigger_fact_ids: z.array(z.string()),
    coverage: evidenceCoverageSchema,
    covered_game_start_ms: z.number().int().nullable(),
    covered_game_end_ms: z.number().int().nullable(),
    video_start_ms: z.number().int().nullable(),
    video_end_ms: z.number().int().nullable(),
    artifacts: z.array(evidenceArtifactReferenceSchema),
  })
  .strict()
  .refine((window) => window.end_ms >= window.start_ms, {
    message: "end_ms must be >= start_ms",
  })
  .refine(
    (window) => {
      if (window.covered_game_start_ms !== null && window.covered_game_end_ms !== null) {
        return window.covered_game_end_ms >= window.covered_game_start_ms;
      }
      return true;
    },
    { message: "covered_game_end_ms must be >= covered_game_start_ms" },
  );

export const replayLinkSummarySchema = z
  .object({
    status: z.literal("linked"),
    full_count: z.number().int(),
    partial_count: z.number().int(),
    unavailable_count: z.number().int(),
  })
  .strict();

export const jointEvidenceResponseSchema = z
  .object({
    status: z.literal("ready"),
    platform: platformSchema,
    match_id: z.string(),
    locale: localeSchema,
    schema_version: z.literal(1),
    facts: z.array(timelineFactSchema),
    windows: z.array(evidenceWindowSchema),
    timeline_cache_status: z.enum(["hit", "miss"]),
    replay_link: replayLinkSummarySchema.nullable(),
    static_data_status: staticDataStatusSchema,
    truncated: z.boolean(),
    total_window_count: z.number().int(),
    scope_notice_code: z.literal("EVIDENCE_ONLY_NO_COACHING"),
    request_id: requestIdSchema,
  })
  .strict();

export type PlayerProfile = z.infer<typeof playerProfileSchema>;
export type HydratedParticipant = z.infer<typeof hydratedParticipantSchema>;
export type RecentMatchItem = z.infer<typeof recentMatchItemSchema>;
export type RecentMatchesResponse = z.infer<typeof recentMatchesResponseSchema>;
export type MatchDetailResponse = z.infer<typeof matchDetailResponseSchema>;
export type PlatformCandidate = z.infer<typeof platformCandidateSchema>;
export type ResolvedDetectionResponse = z.infer<typeof resolvedDetectionResponseSchema>;
export type ConfirmationRequiredResponse = z.infer<typeof confirmationRequiredResponseSchema>;
export type DetectPlayerResponse = z.infer<typeof detectPlayerResponseSchema>;
export type ReplayStatus = z.infer<typeof replayStatusSchema>;
export type ReplayCreateResponse = z.infer<typeof replayCreateResponseSchema>;
export type ReplayStatusResponse = z.infer<typeof replayStatusResponseSchema>;
export type ReplayArtifactKind = z.infer<typeof replayArtifactKindSchema>;
export type ReplayArtifactAccess = z.infer<typeof replayArtifactAccessSchema>;
export type ReplayArtifact = z.infer<typeof replayArtifactSchema>;
export type ReplayArtifactsResponse = z.infer<typeof replayArtifactsResponseSchema>;
export type EvidenceRelationship = z.infer<typeof evidenceRelationshipSchema>;
export type TimelineFact = z.infer<typeof timelineFactSchema>;
export type EvidenceArtifactReference = z.infer<typeof evidenceArtifactReferenceSchema>;
export type EvidenceWindow = z.infer<typeof evidenceWindowSchema>;
export type ReplayLinkSummary = z.infer<typeof replayLinkSummarySchema>;
export type JointEvidenceResponse = z.infer<typeof jointEvidenceResponseSchema>;
