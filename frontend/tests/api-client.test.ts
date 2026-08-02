import { afterEach, describe, expect, it, vi } from "vitest";

import {
  confirmPlayerPlatform,
  detectPlayer,
  getMatchDetail,
  resolvePlayer,
} from "@/api/client";
import {
  confirmationRequiredResponseSchema,
  detectPlayerResponseSchema,
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
