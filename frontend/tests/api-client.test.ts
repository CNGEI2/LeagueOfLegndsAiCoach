import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiClientError,
  confirmPlayerPlatform,
  detectPlayer,
  getMatchDetail,
  prepareMatchEvidence,
  resolvePlayer,
} from "@/api/client";
import {
  confirmationRequiredResponseSchema,
  detectPlayerResponseSchema,
  jointEvidenceResponseSchema,
  platformSchema,
  resolvedDetectionResponseSchema,
} from "@/api/schemas";

function validParticipant(puuid: string, teamId: number, championId: number) {
  return {
    puuid,
    team_id: teamId,
    champion_id: championId,
    role: "MIDDLE",
    won: teamId === 100,
    kills: 7,
    deaths: 3,
    assists: 8,
    cs: 180,
    gold_earned: 12000,
    damage_to_champions: 20000,
    vision_score: 20,
    item_ids: [1055],
    champion: {
      entity_id: championId,
      name: `Champion ${championId}`,
      image_url: `https://cdn.example/champions/${championId}.png`,
    },
    items: [
      {
        entity_id: 1055,
        name: "Doran's Blade",
        image_url: "https://cdn.example/items/1055.png",
      },
    ],
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("API client", () => {
  it("clears a PUUID-shaped request ID from a normalized player response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            player: {
              puuid: "puuid-1",
              game_name: "PlayerName",
              tag_line: "1115",
              platform: "NA1",
              summoner_level: 772,
              profile_icon_id: 29,
              profile_icon: {
                entity_id: 29,
                name: "Profile icon",
                image_url:
                  "https://ddragon.leagueoflegends.com/cdn/16.15.1/img/profileicon/29.png",
              },
              profile_static_data_status: {
                available: true,
                version: "16.15.1",
                code: null,
              },
            },
            request_id: "123e4567-e89b-12d3-a456-426614174000",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    const result = await resolvePlayer({ platform: "NA1", gameName: "PlayerName", tagLine: "1115" });

    expect(result.player.tag_line).toBe("1115");
    expect(result.request_id).toBeNull();
  });

  it("rejects a successful response that violates the runtime schema", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ player: { puuid: 12 } }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(
      resolvePlayer({ platform: "NA1", gameName: "PlayerName", tagLine: "1115" }),
    ).rejects.toMatchObject({ code: "INVALID_API_RESPONSE" });
  });

  it("rejects match detail responses with uncontracted fields", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            match_id: "NA1_1",
            platform: "NA1",
            queue_id: 420,
            started_at: "2026-07-30T12:00:00Z",
            duration_seconds: 1200,
            game_version: "16.15.1",
            selected_puuid: "puuid-1",
            blue_team: Array.from({ length: 5 }, (_, index) =>
              validParticipant(`blue-${index}`, 100, index + 1),
            ),
            red_team: Array.from({ length: 5 }, (_, index) =>
              validParticipant(`red-${index}`, 200, index + 6),
            ),
            static_data_status: { available: true, version: "16.15.1", code: null },
            scope_notice_code: "DATA_ONLY_NO_COACHING",
            request_id: "request-1",
            secretly_invented_coaching_score: 99,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(
      getMatchDetail({ matchId: "NA1_1", puuid: "puuid-1", platform: "NA1", locale: "en-US" }),
    ).rejects.toMatchObject({ code: "INVALID_API_RESPONSE" });
  });

  it("preserves a safe backend code and 32-hex request ID", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "RIOT_RATE_LIMITED",
              message: "Riot API rate limit reached.",
              params: { retry_after_seconds: 12 },
              retryable: true,
              request_id: "a3f4c1d2e5b67890a1b2c3d4e5f60718",
            },
          }),
          {
            status: 429,
            headers: { "X-Request-ID": "a3f4c1d2e5b67890a1b2c3d4e5f60718" },
          },
        ),
      ),
    );

    await expect(resolvePlayer({ platform: "NA1", gameName: "PlayerName", tagLine: "1115" })).rejects.toMatchObject({
      code: "RIOT_RATE_LIMITED",
      requestId: "a3f4c1d2e5b67890a1b2c3d4e5f60718",
    });
  });

  it("drops a PUUID-shaped request ID from a parsed error envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "RIOT_RATE_LIMITED",
              message: "Riot API rate limit reached.",
              params: { retry_after_seconds: 12 },
              retryable: true,
              request_id: "123e4567-e89b-12d3-a456-426614174000",
            },
          }),
          { status: 429, headers: { "X-Request-ID": "123e4567-e89b-12d3-a456-426614174000" } },
        ),
      ),
    );

    await expect(resolvePlayer({ platform: "NA1", gameName: "PlayerName", tagLine: "1115" })).rejects.toMatchObject({
      code: "RIOT_RATE_LIMITED",
      requestId: null,
    });
  });

  it("drops a PUUID-shaped request ID from an invalid response header", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ player: { puuid: 12 } }), {
          status: 200,
          headers: { "X-Request-ID": "123e4567-e89b-12d3-a456-426614174000" },
        }),
      ),
    );

    await expect(resolvePlayer({ platform: "NA1", gameName: "PlayerName", tagLine: "1115" })).rejects.toMatchObject({
      code: "INVALID_API_RESPONSE",
      requestId: null,
    });
  });
});

const validPlayer = {
  puuid: "puuid-1",
  game_name: "PlayerName",
  tag_line: "1115",
  platform: "NA1" as const,
  summoner_level: 772,
  profile_icon_id: 29,
  profile_icon: {
    entity_id: 29,
    name: "Profile icon",
    image_url: "https://ddragon.leagueoflegends.com/cdn/16.15.1/img/profileicon/29.png",
  },
  profile_static_data_status: {
    available: true,
    version: "16.15.1",
    code: null,
  },
};

describe("platform detection schemas", () => {
  it("accepts the closed 16-value platform enum and rejects unknown values", () => {
    expect(platformSchema.options).toHaveLength(16);
    expect(platformSchema.safeParse("NA1").success).toBe(true);
    expect(platformSchema.safeParse("XYZ1").success).toBe(false);
  });

  it("rejects confirmation responses with missing candidates or naive expiry", () => {
    expect(
      confirmationRequiredResponseSchema.safeParse({
        status: "confirmation_required",
        detection_id: "12345678-1234-5678-1234-567812345678",
        expires_at: "2026-08-02T12:15:00",
        candidates: [{ platform: "NA1", display_name: "North America" }],
        request_id: "a3f4c1d2e5b67890a1b2c3d4e5f60718",
      }).success,
    ).toBe(false);
    expect(
      confirmationRequiredResponseSchema.safeParse({
        status: "confirmation_required",
        detection_id: "12345678-1234-5678-1234-567812345678",
        expires_at: "2026-08-02T12:15:00Z",
        candidates: [],
        request_id: "a3f4c1d2e5b67890a1b2c3d4e5f60718",
      }).success,
    ).toBe(false);
  });

  it("rejects detection responses with extra fields", () => {
    expect(
      resolvedDetectionResponseSchema.safeParse({
        status: "resolved",
        player: validPlayer,
        request_id: "a3f4c1d2e5b67890a1b2c3d4e5f60718",
        extra: true,
      }).success,
    ).toBe(false);
    expect(
      detectPlayerResponseSchema.safeParse({
        status: "confirmation_required",
        detection_id: "12345678-1234-5678-1234-567812345678",
        expires_at: "2026-08-02T12:15:00Z",
        candidates: [{ platform: "NA1", display_name: "North America", extra: true }],
        request_id: "a3f4c1d2e5b67890a1b2c3d4e5f60718",
      }).success,
    ).toBe(false);
  });
});

describe("platform detection client", () => {
  it("posts detectPlayer with riot_id and locale", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "resolved",
          player: validPlayer,
          request_id: "a3f4c1d2e5b67890a1b2c3d4e5f60718",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await detectPlayer({ riotId: "PlayerName#1115", locale: "zh-CN" });

    expect(result.status).toBe("resolved");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/players/detect",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ riot_id: "PlayerName#1115", locale: "zh-CN" }),
      }),
    );
  });

  it("posts confirmPlayerPlatform with encoded detection id", async () => {
    const detectionId = "12345678-1234-5678-1234-567812345678";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "resolved",
          player: { ...validPlayer, platform: "EUW1" },
          request_id: "a3f4c1d2e5b67890a1b2c3d4e5f60718",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await confirmPlayerPlatform({
      detectionId,
      platform: "EUW1",
      locale: "en-US",
    });

    expect(result.status).toBe("resolved");
    expect(fetchMock).toHaveBeenCalledWith(
      `http://localhost:8000/api/v1/players/detect/${encodeURIComponent(detectionId)}/confirm`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ platform: "EUW1", locale: "en-US" }),
      }),
    );
  });
});

const SAFE_EVIDENCE_REQUEST_ID = "a3f4c1d2e5b67890a1b2c3d4e5f60718";
const EVIDENCE_ARTIFACT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";
const EVIDENCE_REPLAY_ID = "11111111-2222-4333-8444-555555555555";

const FACT_KINDS = [
  "champion_kill",
  "elite_monster_kill",
  "building_kill",
  "item_purchased",
  "item_sold",
  "item_destroyed",
  "item_undo",
  "participant_state",
] as const;

function factForKind(kind: (typeof FACT_KINDS)[number]) {
  const base = {
    fact_id: `timeline:NA1:NA1_1:v1:frame:1:event:${kind}`,
    timestamp_ms: 60_000,
    relationship: "killer" as const,
  };
  switch (kind) {
    case "champion_kill":
      return {
        ...base,
        kind,
        killer_id: 1,
        victim_id: 6,
        assisting_participant_ids: [2],
        position_x: 100,
        position_y: 200,
      };
    case "elite_monster_kill":
      return {
        ...base,
        kind,
        killer_id: 1,
        killer_team_id: 100,
        monster_type: "DRAGON",
        monster_sub_type: "FIRE_DRAGON",
        position_x: 100,
        position_y: 200,
      };
    case "building_kill":
      return {
        ...base,
        kind,
        killer_id: 1,
        team_id: 100,
        building_type: "TOWER_BUILDING",
        lane_type: "MID_LANE",
        tower_type: "OUTER_TURRET",
        position_x: 100,
        position_y: 200,
      };
    case "item_purchased":
    case "item_sold":
    case "item_destroyed":
      return {
        ...base,
        kind,
        relationship: "actor" as const,
        participant_id: 1,
        item_id: 1055,
        item_name: "Doran's Blade",
        item_image_url: "https://cdn.example/items/1055.png",
      };
    case "item_undo":
      return {
        ...base,
        kind,
        relationship: "actor" as const,
        participant_id: 1,
        before_id: 1055,
        after_id: 0,
        before_item_name: "Doran's Blade",
        before_item_image_url: "https://cdn.example/items/1055.png",
        after_item_name: null,
        after_item_image_url: null,
      };
    case "participant_state":
      return {
        ...base,
        kind,
        relationship: "actor" as const,
        participant_id: 1,
        level: 7,
        current_gold: 500,
        total_gold: 4000,
        minions_killed: 80,
        jungle_minions_killed: 4,
        xp: 3200,
        position_x: 100,
        position_y: 200,
      };
  }
}

function validEvidenceResponse(overrides: Record<string, unknown> = {}) {
  return {
    status: "ready",
    platform: "NA1",
    match_id: "NA1_123456789",
    locale: "en-US",
    schema_version: 1,
    facts: [factForKind("champion_kill")],
    windows: [
      {
        window_id: "evidence-window:NA1:NA1_123456789:v1:0",
        start_ms: 48_000,
        end_ms: 68_000,
        categories: ["combat_context"],
        trigger_fact_ids: ["timeline:NA1:NA1_1:v1:frame:1:event:champion_kill"],
        coverage: "full",
        covered_game_start_ms: 48_000,
        covered_game_end_ms: 68_000,
        video_start_ms: 49_000,
        video_end_ms: 69_000,
        artifacts: [
          {
            artifact_id: EVIDENCE_ARTIFACT_ID,
            kind: "verification_frame",
            game_time_ms: 60_000,
            video_time_ms: 61_000,
          },
        ],
      },
    ],
    timeline_cache_status: "miss",
    replay_link: {
      status: "linked",
      full_count: 1,
      partial_count: 0,
      unavailable_count: 0,
    },
    static_data_status: { available: true, version: "16.15.1", code: null },
    truncated: false,
    total_window_count: 1,
    scope_notice_code: "EVIDENCE_ONLY_NO_COACHING",
    request_id: SAFE_EVIDENCE_REQUEST_ID,
    ...overrides,
  };
}

function evidenceWindow(overrides: Record<string, unknown> = {}) {
  return {
    ...(validEvidenceResponse().windows as Record<string, unknown>[])[0],
    ...overrides,
  };
}

describe("joint evidence schemas and prepareMatchEvidence", () => {
  it.each(FACT_KINDS)("accepts fact kind %s", (kind) => {
    const parsed = jointEvidenceResponseSchema.safeParse(
      validEvidenceResponse({ facts: [factForKind(kind)] }),
    );
    expect(parsed.success).toBe(true);
  });

  it("rejects an unknown fact kind", () => {
    expect(
      jointEvidenceResponseSchema.safeParse(
        validEvidenceResponse({
          facts: [{ ...factForKind("champion_kill"), kind: "skill_shot_miss" }],
        }),
      ).success,
    ).toBe(false);
  });

  it("rejects an unknown relationship", () => {
    expect(
      jointEvidenceResponseSchema.safeParse(
        validEvidenceResponse({
          facts: [{ ...factForKind("champion_kill"), relationship: "blamed" }],
        }),
      ).success,
    ).toBe(false);
  });

  it("rejects an unknown category", () => {
    const base = validEvidenceResponse();
    const window = { ...(base.windows as Record<string, unknown>[])[0], categories: ["mistake"] };
    expect(jointEvidenceResponseSchema.safeParse(validEvidenceResponse({ windows: [window] })).success).toBe(
      false,
    );
  });

  it.each([
    "coaching",
    "score",
    "puuid",
    "selected_puuid",
    "object_key",
    "access_token",
    "url",
    "path",
  ] as const)("rejects forbidden extra field %s on the response", (field) => {
    expect(jointEvidenceResponseSchema.safeParse(validEvidenceResponse({ [field]: "leak" })).success).toBe(
      false,
    );
  });

  it.each([
    "coaching",
    "score",
    "puuid",
    "selected_puuid",
    "object_key",
    "access_token",
    "url",
    "path",
  ] as const)("rejects forbidden extra field %s on a window", (field) => {
    const base = validEvidenceResponse();
    const window = { ...(base.windows as Record<string, unknown>[])[0], [field]: "leak" };
    expect(jointEvidenceResponseSchema.safeParse(validEvidenceResponse({ windows: [window] })).success).toBe(
      false,
    );
  });

  it.each([
    "coaching",
    "score",
    "puuid",
    "selected_puuid",
    "object_key",
    "access_token",
    "url",
    "path",
  ] as const)("rejects forbidden extra field %s on an artifact reference", (field) => {
    const base = validEvidenceResponse();
    const window = { ...(base.windows as Record<string, unknown>[])[0] };
    const artifact = { ...(window.artifacts as Record<string, unknown>[])[0], [field]: "leak" };
    expect(
      jointEvidenceResponseSchema.safeParse(
        validEvidenceResponse({ windows: [{ ...window, artifacts: [artifact] }] }),
      ).success,
    ).toBe(false);
  });

  it.each([
    "coaching",
    "score",
    "puuid",
    "selected_puuid",
    "object_key",
    "access_token",
    "url",
    "path",
  ] as const)("rejects forbidden extra field %s on a fact", (field) => {
    expect(
      jointEvidenceResponseSchema.safeParse(
        validEvidenceResponse({
          facts: [{ ...factForKind("champion_kill"), [field]: "leak" }],
        }),
      ).success,
    ).toBe(false);
  });

  it("rejects end_ms earlier than start_ms", () => {
    const window = evidenceWindow({ start_ms: 80_000, end_ms: 60_000 });
    expect(jointEvidenceResponseSchema.safeParse(validEvidenceResponse({ windows: [window] })).success).toBe(
      false,
    );
  });

  it.each(["timestamp_ms", "start_ms", "end_ms", "total_window_count"] as const)(
    "rejects a negative time or count field %s",
    (field) => {
      if (field === "timestamp_ms") {
        expect(
          jointEvidenceResponseSchema.safeParse(
            validEvidenceResponse({ facts: [{ ...factForKind("champion_kill"), timestamp_ms: -1 }] }),
          ).success,
        ).toBe(false);
        return;
      }
      if (field === "total_window_count") {
        expect(jointEvidenceResponseSchema.safeParse(validEvidenceResponse({ total_window_count: -1 })).success).toBe(
          false,
        );
        return;
      }
      expect(
        jointEvidenceResponseSchema.safeParse(validEvidenceResponse({ windows: [evidenceWindow({ [field]: -1 })] }))
          .success,
      ).toBe(false);
    },
  );

  it("rejects unpaired coverage interval fields", () => {
    expect(
      jointEvidenceResponseSchema.safeParse(
        validEvidenceResponse({
          windows: [evidenceWindow({ covered_game_end_ms: null })],
        }),
      ).success,
    ).toBe(false);
    expect(
      jointEvidenceResponseSchema.safeParse(
        validEvidenceResponse({
          windows: [evidenceWindow({ video_start_ms: null })],
        }),
      ).success,
    ).toBe(false);
  });

  it("requires legal covered and video intervals for full and partial coverage", () => {
    expect(
      jointEvidenceResponseSchema.safeParse(
        validEvidenceResponse({
          windows: [
            evidenceWindow({
              coverage: "full",
              covered_game_start_ms: null,
              covered_game_end_ms: null,
              video_start_ms: null,
              video_end_ms: null,
              artifacts: [],
            }),
          ],
        }),
      ).success,
    ).toBe(false);
    expect(
      jointEvidenceResponseSchema.safeParse(
        validEvidenceResponse({
          windows: [
            evidenceWindow({
              coverage: "partial",
              covered_game_start_ms: 50_000,
              covered_game_end_ms: 60_000,
              video_start_ms: null,
              video_end_ms: null,
              artifacts: [],
            }),
          ],
          replay_link: { status: "linked", full_count: 0, partial_count: 1, unavailable_count: 0 },
        }),
      ).success,
    ).toBe(false);
  });

  it("requires unavailable coverage to have null intervals and no artifacts", () => {
    expect(
      jointEvidenceResponseSchema.safeParse(
        validEvidenceResponse({
          windows: [
            evidenceWindow({
              coverage: "unavailable",
              covered_game_start_ms: 48_000,
              covered_game_end_ms: 68_000,
              video_start_ms: 49_000,
              video_end_ms: 69_000,
            }),
          ],
          replay_link: { status: "linked", full_count: 0, partial_count: 0, unavailable_count: 1 },
        }),
      ).success,
    ).toBe(false);
    expect(
      jointEvidenceResponseSchema.safeParse(
        validEvidenceResponse({
          windows: [evidenceWindow({ coverage: "unavailable", artifacts: evidenceWindow().artifacts })],
          replay_link: { status: "linked", full_count: 0, partial_count: 0, unavailable_count: 1 },
        }),
      ).success,
    ).toBe(false);
  });

  it("rejects a covered interval outside the evidence window", () => {
    expect(
      jointEvidenceResponseSchema.safeParse(
        validEvidenceResponse({
          windows: [
            evidenceWindow({
              start_ms: 48_000,
              end_ms: 68_000,
              covered_game_start_ms: 40_000,
              covered_game_end_ms: 68_000,
            }),
          ],
        }),
      ).success,
    ).toBe(false);
  });

  it("rejects an inverted video interval", () => {
    expect(
      jointEvidenceResponseSchema.safeParse(
        validEvidenceResponse({
          windows: [evidenceWindow({ video_start_ms: 80_000, video_end_ms: 49_000 })],
        }),
      ).success,
    ).toBe(false);
  });

  it("rejects an artifact whose times fall outside the authorized coverage interval", () => {
    const window = evidenceWindow();
    const artifact = { ...(window.artifacts as Record<string, unknown>[])[0], game_time_ms: 90_000 };
    expect(
      jointEvidenceResponseSchema.safeParse(
        validEvidenceResponse({ windows: [{ ...window, artifacts: [artifact] }] }),
      ).success,
    ).toBe(false);
  });

  it("rejects full or partial coverage and artifacts when replay_link is null", () => {
    expect(jointEvidenceResponseSchema.safeParse(validEvidenceResponse({ replay_link: null })).success).toBe(
      false,
    );
    expect(
      jointEvidenceResponseSchema.safeParse(
        validEvidenceResponse({
          replay_link: null,
          windows: [
            evidenceWindow({
              coverage: "unavailable",
              covered_game_start_ms: null,
              covered_game_end_ms: null,
              video_start_ms: null,
              video_end_ms: null,
              artifacts: evidenceWindow().artifacts,
            }),
          ],
        }),
      ).success,
    ).toBe(false);
  });

  it("requires linked summary counts to match window coverage", () => {
    expect(
      jointEvidenceResponseSchema.safeParse(
        validEvidenceResponse({
          replay_link: { status: "linked", full_count: 0, partial_count: 1, unavailable_count: 0 },
        }),
      ).success,
    ).toBe(false);
  });

  it("requires truncated and total_window_count to agree with returned windows", () => {
    expect(
      jointEvidenceResponseSchema.safeParse(validEvidenceResponse({ truncated: false, total_window_count: 2 }))
        .success,
    ).toBe(false);
    expect(
      jointEvidenceResponseSchema.safeParse(validEvidenceResponse({ truncated: true, total_window_count: 1 }))
        .success,
    ).toBe(false);
    expect(
      jointEvidenceResponseSchema.safeParse(validEvidenceResponse({ truncated: true, total_window_count: 65 }))
        .success,
    ).toBe(true);
  });

  it("accepts timeline-only evidence with unavailable windows and no artifacts", () => {
    expect(
      jointEvidenceResponseSchema.safeParse(
        validEvidenceResponse({
          replay_link: null,
          windows: [
            evidenceWindow({
              coverage: "unavailable",
              covered_game_start_ms: null,
              covered_game_end_ms: null,
              video_start_ms: null,
              video_end_ms: null,
              artifacts: [],
            }),
          ],
        }),
      ).success,
    ).toBe(true);
  });

  it("rejects schema_version values other than 1", () => {
    expect(jointEvidenceResponseSchema.safeParse(validEvidenceResponse({ schema_version: 2 })).success).toBe(
      false,
    );
    expect(jointEvidenceResponseSchema.safeParse(validEvidenceResponse({ schema_version: "1" })).success).toBe(
      false,
    );
  });

  it("requires scope_notice_code EVIDENCE_ONLY_NO_COACHING", () => {
    expect(
      jointEvidenceResponseSchema.safeParse(
        validEvidenceResponse({ scope_notice_code: "DATA_ONLY_NO_COACHING" }),
      ).success,
    ).toBe(false);
    const withoutNotice = { ...validEvidenceResponse() };
    delete (withoutNotice as { scope_notice_code?: string }).scope_notice_code;
    expect(jointEvidenceResponseSchema.safeParse(withoutNotice).success).toBe(false);
  });

  it("posts Timeline-only prepareMatchEvidence with encoded path and replay_id null", async () => {
    const matchId = "NA1_abc/def+1";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(validEvidenceResponse({ match_id: matchId })), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await prepareMatchEvidence({
      matchId,
      platform: "NA1",
      puuid: "selected-puuid",
      locale: "zh-CN",
    });

    expect(result.status).toBe("ready");
    expect(fetchMock).toHaveBeenCalledWith(
      `http://localhost:8000/api/v1/matches/${encodeURIComponent(matchId)}/evidence`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          platform: "NA1",
          puuid: "selected-puuid",
          locale: "zh-CN",
          replay_id: null,
        }),
      }),
    );
    const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });

  it("sends linked replay_id and Authorization bearer token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify(
          validEvidenceResponse({
            replay_link: {
              status: "linked",
              full_count: 1,
              partial_count: 0,
              unavailable_count: 0,
            },
          }),
        ),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await prepareMatchEvidence({
      matchId: "NA1_123456789",
      platform: "NA1",
      puuid: "selected-puuid",
      locale: "en-US",
      replay: { replayId: EVIDENCE_REPLAY_ID, accessToken: "possession-token" },
    });

    expect(fetchMock).toHaveBeenCalledWith(
      `http://localhost:8000/api/v1/matches/${encodeURIComponent("NA1_123456789")}/evidence`,
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Authorization: "Bearer possession-token" }),
        body: JSON.stringify({
          platform: "NA1",
          puuid: "selected-puuid",
          locale: "en-US",
          replay_id: EVIDENCE_REPLAY_ID,
        }),
      }),
    );
  });

  it("forwards AbortSignal to fetch", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(validEvidenceResponse()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await prepareMatchEvidence(
      {
        matchId: "NA1_123456789",
        platform: "NA1",
        puuid: "selected-puuid",
        locale: "en-US",
      },
      controller.signal,
    );

    expect(fetchMock).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ signal: controller.signal }),
    );
  });

  it("parses an error envelope into ApiClientError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "REPLAY_EVIDENCE_NOT_READY",
              message: "Replay is not ready for evidence.",
              params: {},
              retryable: true,
              request_id: SAFE_EVIDENCE_REQUEST_ID,
            },
          }),
          { status: 409, headers: { "X-Request-ID": SAFE_EVIDENCE_REQUEST_ID } },
        ),
      ),
    );

    try {
      await prepareMatchEvidence({
        matchId: "NA1_123456789",
        platform: "NA1",
        puuid: "selected-puuid",
        locale: "en-US",
        replay: { replayId: EVIDENCE_REPLAY_ID, accessToken: "possession-token" },
      });
      expect.fail("expected prepareMatchEvidence to reject");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiClientError);
      expect(error).toMatchObject({
        code: "REPLAY_EVIDENCE_NOT_READY",
        retryable: true,
        requestId: SAFE_EVIDENCE_REQUEST_ID,
      });
    }
  });

  it("rejects an invalid success body as INVALID_API_RESPONSE", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: "ready", coaching_score: 99 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(
      prepareMatchEvidence({
        matchId: "NA1_123456789",
        platform: "NA1",
        puuid: "selected-puuid",
        locale: "en-US",
      }),
    ).rejects.toMatchObject({ code: "INVALID_API_RESPONSE" });
  });
});
