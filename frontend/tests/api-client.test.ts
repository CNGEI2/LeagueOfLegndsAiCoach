import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiClientError, resolvePlayer } from "@/api/client";

afterEach(() => vi.unstubAllGlobals());

describe("API client", () => {
  it("accepts a normalized player response", async () => {
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
            request_id: "request-1",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    const result = await resolvePlayer({
      platform: "NA1",
      gameName: "PlayerName",
      tagLine: "1115",
    });

    expect(result.player.tag_line).toBe("1115");
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

  it("preserves a safe backend code and request ID", async () => {
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
              request_id: "request-2",
            },
          }),
          { status: 429, headers: { "X-Request-ID": "request-2" } },
        ),
      ),
    );

    await expect(
      resolvePlayer({ platform: "NA1", gameName: "PlayerName", tagLine: "1115" }),
    ).rejects.toBeInstanceOf(ApiClientError);
  });
});
