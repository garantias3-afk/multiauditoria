import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

describe("configuración Tauri v2", () => {
  it("mantiene drag/drop HTML5 y CSP limitada a loopback", async () => {
    const configPath = fileURLToPath(new URL("../src-tauri/tauri.conf.json", import.meta.url));
    const config = JSON.parse(await readFile(configPath, "utf8")) as {
      app: {
        windows: Array<{ dragDropEnabled?: boolean }>;
        security: { csp: string };
      };
    };

    expect(config.app.windows[0]?.dragDropEnabled).toBe(false);
    const connectSources = config.app.security.csp
      .split(";")
      .find((directive) => directive.trim().startsWith("connect-src"))
      ?.trim()
      .split(/\s+/)
      .slice(1);
    expect(connectSources).toEqual([
      "'self'",
      "http://127.0.0.1:*",
      "http://localhost:*",
      "http://[::1]:*",
      "https://127.0.0.1:*",
      "https://localhost:*",
      "https://[::1]:*",
    ]);
  });
});
