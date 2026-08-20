import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  findReplayCapabilityForMatch,
  loadReplayCapability,
  removeReplayCapability,
  saveReplayCapability,
} from "@/replays/storage";

const REPLAY_ID = "11111111-2222-4333-8444-555555555555";
const STORAGE_KEY = `lol-ai-coach:replay:${REPLAY_ID}`;

function installMemoryLocalStorage() {
  const store = new Map<string, string>();
  const memoryStorage = {
    get length() {
      return store.size;
    },
    clear() {
      store.clear();
    },
    getItem(key: string) {
      return store.has(key) ? store.get(key)! : null;
    },
    key(index: number) {
      return [...store.keys()][index] ?? null;
    },
    removeItem(key: string) {
      store.delete(key);
    },
    setItem(key: string, value: string) {
      store.set(key, String(value));
    },
  };
  vi.stubGlobal("localStorage", memoryStorage);
  return memoryStorage;
}

let memoryStorage: ReturnType<typeof installMemoryLocalStorage>;

beforeEach(() => {
  memoryStorage = installMemoryLocalStorage();
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-08-01T15:00:00.000Z"));
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("replay capability storage", () => {
  it("persists only the capability whitelist", () => {
    saveReplayCapability({
      replayId: REPLAY_ID,
      accessToken: "secret-token",
      matchId: "NA1_123",
      updatedAt: "2026-08-01T15:00:00.000Z",
      status: "ready",
      puuid: "should-not-persist",
      fileName: "recording.mp4",
      uploadUrl: "https://s3.example/upload",
    });

    const raw = memoryStorage.getItem(STORAGE_KEY);
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw!) as Record<string, unknown>;
    expect(Object.keys(parsed).sort()).toEqual([
      "accessToken",
      "matchId",
      "replayId",
      "status",
      "updatedAt",
    ]);
    expect(parsed).not.toHaveProperty("puuid");
    expect(parsed).not.toHaveProperty("fileName");
    expect(parsed).not.toHaveProperty("uploadUrl");
    expect(parsed.accessToken).toBe("secret-token");
    expect(parsed.status).toBe("ready");
  });

  it("loads a valid capability", () => {
    saveReplayCapability({
      replayId: REPLAY_ID,
      accessToken: "secret-token",
      matchId: "NA1_123",
      updatedAt: "2026-08-01T14:00:00.000Z",
      status: "ready",
    });

    expect(loadReplayCapability(REPLAY_ID)).toEqual({
      replayId: REPLAY_ID,
      accessToken: "secret-token",
      matchId: "NA1_123",
      updatedAt: "2026-08-01T14:00:00.000Z",
      status: "ready",
    });
  });

  it("loads a legacy capability without status as status null while keeping the token", () => {
    memoryStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        replayId: REPLAY_ID,
        accessToken: "legacy-token",
        matchId: "NA1_123",
        updatedAt: "2026-08-01T14:00:00.000Z",
      }),
    );

    expect(loadReplayCapability(REPLAY_ID)).toEqual({
      replayId: REPLAY_ID,
      accessToken: "legacy-token",
      matchId: "NA1_123",
      updatedAt: "2026-08-01T14:00:00.000Z",
      status: null,
    });
  });

  it("persists ready status when saving with status", () => {
    saveReplayCapability({
      replayId: REPLAY_ID,
      accessToken: "secret-token",
      matchId: "NA1_123",
      updatedAt: "2026-08-01T15:00:00.000Z",
      status: "ready",
    });

    expect(loadReplayCapability(REPLAY_ID)?.status).toBe("ready");
  });

  it("findReplayCapabilityForMatch returns the newest capability by updatedAt", () => {
    const olderId = "aaaaaaaa-bbbb-4ccc-8ddd-111111111111";
    const newerId = "aaaaaaaa-bbbb-4ccc-8ddd-222222222222";
    saveReplayCapability({
      replayId: olderId,
      accessToken: "older-token",
      matchId: "NA1_123",
      updatedAt: "2026-08-01T14:00:00.000Z",
      status: "ready",
    });
    saveReplayCapability({
      replayId: newerId,
      accessToken: "newer-token",
      matchId: "NA1_123",
      updatedAt: "2026-08-01T15:00:00.000Z",
      status: "queued",
    });
    saveReplayCapability({
      replayId: REPLAY_ID,
      accessToken: "other-match-token",
      matchId: "NA1_999",
      updatedAt: "2026-08-01T16:00:00.000Z",
      status: "ready",
    });

    expect(findReplayCapabilityForMatch("NA1_123")).toEqual({
      replayId: newerId,
      accessToken: "newer-token",
      matchId: "NA1_123",
      updatedAt: "2026-08-01T15:00:00.000Z",
      status: "queued",
    });
  });

  it("findReplayCapabilityForMatch with ready skips null and non-ready statuses", () => {
    const legacyId = "aaaaaaaa-bbbb-4ccc-8ddd-333333333333";
    const queuedId = "aaaaaaaa-bbbb-4ccc-8ddd-444444444444";
    const olderReadyId = "aaaaaaaa-bbbb-4ccc-8ddd-555555555555";
    const newestReadyId = "aaaaaaaa-bbbb-4ccc-8ddd-666666666666";

    memoryStorage.setItem(
      `lol-ai-coach:replay:${legacyId}`,
      JSON.stringify({
        replayId: legacyId,
        accessToken: "legacy-token",
        matchId: "NA1_123",
        updatedAt: "2026-08-01T16:00:00.000Z",
      }),
    );
    saveReplayCapability({
      replayId: queuedId,
      accessToken: "queued-token",
      matchId: "NA1_123",
      updatedAt: "2026-08-01T15:30:00.000Z",
      status: "queued",
    });
    saveReplayCapability({
      replayId: olderReadyId,
      accessToken: "older-ready-token",
      matchId: "NA1_123",
      updatedAt: "2026-08-01T14:00:00.000Z",
      status: "ready",
    });
    saveReplayCapability({
      replayId: newestReadyId,
      accessToken: "newest-ready-token",
      matchId: "NA1_123",
      updatedAt: "2026-08-01T15:00:00.000Z",
      status: "ready",
    });

    expect(findReplayCapabilityForMatch("NA1_123", "ready")).toEqual({
      replayId: newestReadyId,
      accessToken: "newest-ready-token",
      matchId: "NA1_123",
      updatedAt: "2026-08-01T15:00:00.000Z",
      status: "ready",
    });
  });

  it("snapshots storage keys so a corrupt earlier item cannot hide a later ready capability", () => {
    const corruptId = "aaaaaaaa-bbbb-4ccc-8ddd-aaaaaaaac001";
    const expiredId = "aaaaaaaa-bbbb-4ccc-8ddd-aaaaaaaac002";
    const readyId = "aaaaaaaa-bbbb-4ccc-8ddd-aaaaaaaac003";

    memoryStorage.setItem(`lol-ai-coach:replay:${corruptId}`, "{not-json");
    memoryStorage.setItem(
      `lol-ai-coach:replay:${expiredId}`,
      JSON.stringify({
        replayId: expiredId,
        accessToken: "expired-token",
        matchId: "NA1_123",
        updatedAt: "2026-07-20T15:00:00.000Z",
        status: "ready",
      }),
    );
    saveReplayCapability({
      replayId: readyId,
      accessToken: "surviving-ready-token",
      matchId: "NA1_123",
      updatedAt: "2026-08-01T15:00:00.000Z",
      status: "ready",
    });

    expect([...Array(memoryStorage.length)].map((_, index) => memoryStorage.key(index))).toEqual([
      `lol-ai-coach:replay:${corruptId}`,
      `lol-ai-coach:replay:${expiredId}`,
      `lol-ai-coach:replay:${readyId}`,
    ]);

    expect(findReplayCapabilityForMatch("NA1_123", "ready")).toEqual({
      replayId: readyId,
      accessToken: "surviving-ready-token",
      matchId: "NA1_123",
      updatedAt: "2026-08-01T15:00:00.000Z",
      status: "ready",
    });
    expect(memoryStorage.getItem(`lol-ai-coach:replay:${corruptId}`)).toBeNull();
    expect(memoryStorage.getItem(`lol-ai-coach:replay:${expiredId}`)).toBeNull();
    expect(memoryStorage.getItem(`lol-ai-coach:replay:${readyId}`)).not.toBeNull();
  });

  it("returns null and removes corrupt JSON", () => {
    memoryStorage.setItem(STORAGE_KEY, "{not-json");
    expect(loadReplayCapability(REPLAY_ID)).toBeNull();
    expect(memoryStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("returns null and removes schema-invalid JSON", () => {
    memoryStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        replayId: REPLAY_ID,
        accessToken: "secret-token",
        matchId: "NA1_123",
        updatedAt: "2026-08-01T14:00:00.000Z",
        puuid: "leaked",
      }),
    );

    expect(loadReplayCapability(REPLAY_ID)).toBeNull();
    expect(memoryStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("returns null and removes expired capabilities", () => {
    memoryStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        replayId: REPLAY_ID,
        accessToken: "secret-token",
        matchId: "NA1_123",
        updatedAt: "2026-07-20T15:00:00.000Z",
      }),
    );

    expect(loadReplayCapability(REPLAY_ID)).toBeNull();
    expect(memoryStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("removes a capability by replay id", () => {
    saveReplayCapability({
      replayId: REPLAY_ID,
      accessToken: "secret-token",
      matchId: "NA1_123",
      updatedAt: "2026-08-01T15:00:00.000Z",
    });
    removeReplayCapability(REPLAY_ID);
    expect(memoryStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});
