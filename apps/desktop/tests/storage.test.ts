import { afterEach, describe, expect, it, vi } from "vitest";

import {
  clearRecentSessionIds,
  loadCoreUrl,
  loadRecentSessionIds,
  saveCoreUrl,
  saveRecentSessionId,
} from "../src/utils/storage";

function memoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => Array.from(values.keys())[index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, String(value)),
  };
}

describe("utilidades de persistencia local", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("conserva URL e IDs y permite invalidar el historial al cambiar credenciales", () => {
    const localStorage = memoryStorage();
    vi.stubGlobal("window", { localStorage });
    const url = "http://127.0.0.1:8850";

    saveCoreUrl(url);
    saveRecentSessionId(url, "session-1");

    expect(loadCoreUrl()).toBe(url);
    expect(loadRecentSessionIds(url)).toEqual(["session-1"]);
    expect(Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index)).sort()).toEqual(
      ["robot.core_url", `robot.session_ids:${url}`].sort(),
    );

    expect(clearRecentSessionIds(url)).toBe(true);
    expect(loadRecentSessionIds(url)).toEqual([]);
    expect(localStorage.getItem("robot.core_token")).toBeNull();
  });

  it("no afirma que quitó IDs si el almacenamiento rechaza removeItem", () => {
    const localStorage = memoryStorage();
    localStorage.removeItem = () => {
      throw new Error("storage denied");
    };
    vi.stubGlobal("window", { localStorage });

    expect(clearRecentSessionIds("http://127.0.0.1:8850")).toBe(false);
  });
});
