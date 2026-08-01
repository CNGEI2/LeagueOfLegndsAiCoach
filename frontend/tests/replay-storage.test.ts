import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
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
      "updatedAt",
    ]);
    expect(parsed).not.toHaveProperty("puuid");
    expect(parsed).not.toHaveProperty("fileName");
    expect(parsed).not.toHaveProperty("uploadUrl");
    expect(parsed.accessToken).toBe("secret-token");
  });

  it("loads a valid capability", () => {
    saveReplayCapability({
      replayId: REPLAY_ID,
      accessToken: "secret-token",
      matchId: "NA1_123",
      updatedAt: "2026-08-01T14:00:00.000Z",
    });

    expect(loadReplayCapability(REPLAY_ID)).toEqual({
      replayId: REPLAY_ID,
      accessToken: "secret-token",
      matchId: "NA1_123",
      updatedAt: "2026-08-01T14:00:00.000Z",
    });
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
