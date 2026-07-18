// @vitest-environment jsdom

import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { startMockCore, type MockCoreHandle } from "../mocks/server";
import App from "../src/App";

function buttonNamed(name: string): HTMLButtonElement | null {
  return (
    Array.from(document.querySelectorAll<HTMLButtonElement>("button")).find(
      (button) => button.textContent?.trim() === name,
    ) ?? null
  );
}

async function setFieldValue(element: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const prototype =
    element instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
  if (!setter) throw new Error("El entorno DOM no expone el setter nativo de value");

  await act(async () => {
    setter.call(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

async function click(element: HTMLElement) {
  await act(async () => {
    element.click();
    await Promise.resolve();
  });
}

async function waitForDom(
  condition: () => boolean,
  description: string,
  timeoutMs = 5_000,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!condition()) {
    if (Date.now() >= deadline) {
      throw new Error(`Timeout esperando: ${description}\nDOM actual: ${document.body.textContent}`);
    }
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
  }
}

function memoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() {
      return values.size;
    },
    clear() {
      values.clear();
    },
    getItem(key) {
      return values.get(key) ?? null;
    },
    key(index) {
      return Array.from(values.keys())[index] ?? null;
    },
    removeItem(key) {
      values.delete(key);
    },
    setItem(key, value) {
      values.set(key, String(value));
    },
  };
}

describe("App HITL contra Mock Core", () => {
  let mock: MockCoreHandle | undefined;
  let root: Root | undefined;
  let container: HTMLDivElement;

  beforeAll(async () => {
    (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean })
      .IS_REACT_ACT_ENVIRONMENT = true;
    vi.stubGlobal(
      "requestAnimationFrame",
      (callback: FrameRequestCallback) =>
        window.setTimeout(() => callback(performance.now()), 0),
    );
    vi.stubGlobal("cancelAnimationFrame", (handle: number) => window.clearTimeout(handle));
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: memoryStorage(),
    });
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn((query: string): MediaQueryList => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(() => true),
      })),
    });
    mock = await startMockCore({ port: 0, eventDelayMs: 0, token: "app-hitl-token" });
  });

  beforeEach(async () => {
    window.localStorage.clear();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () => {
      root!.render(createElement(App));
    });
  });

  afterEach(async () => {
    await act(async () => {
      root?.unmount();
    });
    root = undefined;
    container?.remove();
  });

  afterAll(async () => {
    await mock?.close();
    vi.unstubAllGlobals();
  });

  it("un clic real en Rechazar envía false, libera la pausa y termina sin ejecutar la tool", async () => {
    const auditStart = mock!.auditLog.length;
    const urlInput = container.querySelector<HTMLInputElement>("#core-url");
    const tokenInput = container.querySelector<HTMLInputElement>("#core-token");
    expect(urlInput).not.toBeNull();
    expect(tokenInput).not.toBeNull();

    await setFieldValue(urlInput!, mock!.baseUrl);
    await setFieldValue(tokenInput!, mock!.token);
    const save = buttonNamed("Guardar");
    expect(save).not.toBeNull();
    expect(save!.disabled).toBe(false);
    await click(save!);
    await waitForDom(
      () => container.querySelector(".settings-dialog") === null,
      "cierre de Ajustes",
    );

    const composer = container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Mensaje"]');
    expect(composer).not.toBeNull();
    await setFieldValue(composer!, "Intentá escribir, pero voy a rechazar el permiso");
    const send = buttonNamed("Enviar");
    expect(send).not.toBeNull();
    expect(send!.disabled).toBe(false);
    await click(send!);

    await waitForDom(() => buttonNamed("Rechazar") !== null, "diálogo HITL");
    expect(mock!.auditLog.slice(auditStart)).toEqual([]);
    expect(container.textContent).toContain("Stream en pausa");

    await click(buttonNamed("Rechazar")!);
    const finalText = "Acción rechazada por el usuario. No ejecuté la herramienta.";
    await waitForDom(
      () => container.textContent?.includes(finalText) === true && buttonNamed("Rechazar") === null,
      "final rechazado y cierre del diálogo HITL",
    );

    const audit = mock!.auditLog.slice(auditStart);
    expect(audit).toHaveLength(1);
    expect(audit[0]).toMatchObject({ kind: "confirmation", approved: false });
    expect(audit.some((entry) => entry.kind === "tool_execution")).toBe(false);
    expect(container.querySelectorAll(".activity-item")).toHaveLength(0);
    expect(container.textContent).toContain(finalText);
  });

  it("Detener preserva el error terminal que llegó antes del ACK", async () => {
    const auditStart = mock!.auditLog.length;
    const urlInput = container.querySelector<HTMLInputElement>("#core-url")!;
    const tokenInput = container.querySelector<HTMLInputElement>("#core-token")!;
    await setFieldValue(urlInput, mock!.baseUrl);
    await setFieldValue(tokenInput, mock!.token);
    await click(buttonNamed("Guardar")!);
    await waitForDom(() => container.querySelector(".settings-dialog") === null, "cierre de Ajustes");

    const composer = container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Mensaje"]')!;
    await setFieldValue(composer, "Interrumpí este turno antes de ejecutar la herramienta");
    await click(buttonNamed("Enviar")!);
    await waitForDom(() => buttonNamed("Detener turno") !== null, "HITL antes de interrumpir");
    await click(buttonNamed("Detener turno")!);

    await waitForDom(
      () => container.querySelector(".global-error")?.textContent?.includes("Turno interrumpido") === true,
      "error terminal visible",
    );
    expect(container.textContent).toContain("Con error");
    expect(container.textContent).toContain(
      "El Core confirmó la solicitud de interrupción y también informó un error terminal.",
    );
    const audit = mock!.auditLog.slice(auditStart);
    expect(audit).toContainEqual(
      expect.objectContaining({ kind: "interrupt", hadActiveTurn: true }),
    );
    expect(audit.some((entry) => entry.kind === "tool_execution")).toBe(false);
  });

  it("invalida un test de conexión exitoso al editar sus credenciales", async () => {
    const urlInput = container.querySelector<HTMLInputElement>("#core-url")!;
    const tokenInput = container.querySelector<HTMLInputElement>("#core-token")!;
    await setFieldValue(urlInput, mock!.baseUrl);
    await setFieldValue(tokenInput, mock!.token);
    await click(buttonNamed("Probar conexión")!);
    await waitForDom(
      () => container.textContent?.includes("Conexión correcta: healthz respondió ok:true.") === true,
      "test de conexión exitoso",
    );

    await setFieldValue(tokenInput, `${mock!.token}-editado`);
    expect(container.textContent).not.toContain("Conexión correcta: healthz respondió ok:true.");
  });

  it("no persiste el token centinela bajo ninguna clave ni valor local", async () => {
    const sentinel = "SECRET_TOKEN_SENTINEL_7f31";
    await setFieldValue(container.querySelector<HTMLInputElement>("#core-url")!, mock!.baseUrl);
    await setFieldValue(container.querySelector<HTMLInputElement>("#core-token")!, sentinel);
    await click(buttonNamed("Guardar")!);
    await waitForDom(() => container.querySelector(".settings-dialog") === null, "cierre de Ajustes");

    const entries = Array.from({ length: window.localStorage.length }, (_unused, index) => {
      const key = window.localStorage.key(index)!;
      return [key, window.localStorage.getItem(key)] as const;
    });
    expect(entries.map(([key]) => key)).toEqual(["robot.core_url"]);
    expect(JSON.stringify(entries)).not.toContain(sentinel);
  });

  it("procesa eventos retenidos si el ACK de aprobación llega después del final SSE", async () => {
    const nativeFetch = globalThis.fetch;
    const delayedFetch: typeof fetch = async (input, init) => {
      const response = await nativeFetch(input, init);
      if (String(input).endsWith("/confirm")) {
        await new Promise((resolve) => setTimeout(resolve, 40));
      }
      return response;
    };
    vi.stubGlobal("fetch", delayedFetch);
    try {
      await setFieldValue(container.querySelector<HTMLInputElement>("#core-url")!, mock!.baseUrl);
      await setFieldValue(container.querySelector<HTMLInputElement>("#core-token")!, mock!.token);
      await click(buttonNamed("Guardar")!);
      await waitForDom(() => container.querySelector(".settings-dialog") === null, "cierre de Ajustes");
      await setFieldValue(
        container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Mensaje"]')!,
        "Aprobación con ACK demorado",
      );
      await click(buttonNamed("Enviar")!);
      await waitForDom(() => buttonNamed("Aprobar") !== null, "diálogo HITL");
      await click(buttonNamed("Aprobar")!);

      await waitForDom(
        () =>
          container.textContent?.includes(
            "La simulación completó la investigación y ejecutó la herramienta después de tu aprobación.",
          ) === true,
        "final retenido hasta el ACK",
      );
      expect(container.querySelector(".global-error")).toBeNull();
      expect(buttonNamed("Aprobar")).toBeNull();
    } finally {
      vi.stubGlobal("fetch", nativeFetch);
    }
  });

  it("corta fail-closed y no ofrece reintentar si se pierde el ACK de /confirm", async () => {
    const nativeFetch = globalThis.fetch;
    const lostAckFetch: typeof fetch = async (input, init) => {
      const response = await nativeFetch(input, init);
      if (String(input).endsWith("/confirm")) {
        await response.arrayBuffer();
        await new Promise((resolve) => setTimeout(resolve, 40));
        throw new TypeError("ACK simulado perdido");
      }
      return response;
    };
    vi.stubGlobal("fetch", lostAckFetch);
    try {
      await setFieldValue(container.querySelector<HTMLInputElement>("#core-url")!, mock!.baseUrl);
      await setFieldValue(container.querySelector<HTMLInputElement>("#core-token")!, mock!.token);
      await click(buttonNamed("Guardar")!);
      await waitForDom(() => container.querySelector(".settings-dialog") === null, "cierre de Ajustes");
      await setFieldValue(
        container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Mensaje"]')!,
        "Aprobación cuyo ACK se perderá",
      );
      await click(buttonNamed("Enviar")!);
      await waitForDom(() => buttonNamed("Aprobar") !== null, "diálogo HITL");
      await click(buttonNamed("Aprobar")!);

      await waitForDom(
        () => container.querySelector(".global-error")?.textContent?.includes("Se canceló el stream") === true,
        "estado incierto fail-closed",
      );
      expect(buttonNamed("Aprobar")).toBeNull();
      expect(buttonNamed("Rechazar")).toBeNull();
    } finally {
      vi.stubGlobal("fetch", nativeFetch);
    }
  });

  it("no reabre HITL si falla Detener mientras una aprobación queda incierta", async () => {
    const nativeFetch = globalThis.fetch;
    const uncertainFetch: typeof fetch = async (input, init) => {
      const url = String(input);
      if (url.endsWith("/confirm")) {
        await nativeFetch(input, init);
        return await new Promise<Response>((_resolve, reject) => {
          const signal = init?.signal;
          const rejectAbort = () => reject(new DOMException("Aborted", "AbortError"));
          if (signal?.aborted) rejectAbort();
          else signal?.addEventListener("abort", rejectAbort, { once: true });
        });
      }
      if (url.endsWith("/interrupt")) {
        return new Response(JSON.stringify({ ok: false }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return nativeFetch(input, init);
    };
    vi.stubGlobal("fetch", uncertainFetch);
    try {
      await setFieldValue(container.querySelector<HTMLInputElement>("#core-url")!, mock!.baseUrl);
      await setFieldValue(container.querySelector<HTMLInputElement>("#core-token")!, mock!.token);
      await click(buttonNamed("Guardar")!);
      await waitForDom(() => container.querySelector(".settings-dialog") === null, "cierre de Ajustes");
      await setFieldValue(
        container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Mensaje"]')!,
        "Aprobación incierta durante Detener",
      );
      await click(buttonNamed("Enviar")!);
      await waitForDom(() => buttonNamed("Aprobar") !== null, "diálogo HITL");
      await click(buttonNamed("Aprobar")!);
      await waitForDom(
        () => container.textContent?.includes("Enviando tu decisión al Core") === true,
        "aprobación en vuelo",
      );
      await click(buttonNamed("Detener turno")!);

      await waitForDom(
        () => container.querySelector(".global-error")?.textContent?.includes("Se canceló el stream") === true,
        "interrupción fallida fail-closed",
      );
      expect(buttonNamed("Aprobar")).toBeNull();
      expect(buttonNamed("Rechazar")).toBeNull();
    } finally {
      vi.stubGlobal("fetch", nativeFetch);
    }
  });

  it("preserva tool y final ya recibidos si Detener gana mientras el ACK sigue pendiente", async () => {
    const nativeFetch = globalThis.fetch;
    const auditStart = mock!.auditLog.length;
    const heldAckFetch: typeof fetch = async (input, init) => {
      if (String(input).endsWith("/confirm")) {
        const response = await nativeFetch(input, init);
        await response.arrayBuffer();
        return await new Promise<Response>((_resolve, reject) => {
          const signal = init?.signal;
          const rejectAbort = () => reject(new DOMException("Aborted", "AbortError"));
          if (signal?.aborted) rejectAbort();
          else signal?.addEventListener("abort", rejectAbort, { once: true });
        });
      }
      return nativeFetch(input, init);
    };
    vi.stubGlobal("fetch", heldAckFetch);
    try {
      await setFieldValue(container.querySelector<HTMLInputElement>("#core-url")!, mock!.baseUrl);
      await setFieldValue(container.querySelector<HTMLInputElement>("#core-token")!, mock!.token);
      await click(buttonNamed("Guardar")!);
      await waitForDom(() => container.querySelector(".settings-dialog") === null, "cierre de Ajustes");
      await setFieldValue(
        container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Mensaje"]')!,
        "Conservá el resultado aunque Detener llegue tarde",
      );
      await click(buttonNamed("Enviar")!);
      await waitForDom(() => buttonNamed("Aprobar") !== null, "diálogo HITL");
      await click(buttonNamed("Aprobar")!);
      await waitForDom(
        () =>
          mock!.auditLog
            .slice(auditStart)
            .some((entry) => entry.kind === "tool_execution"),
        "ejecución aceptada por el Core",
      );
      await click(buttonNamed("Detener turno")!);

      const finalText =
        "La simulación completó la investigación y ejecutó la herramienta después de tu aprobación.";
      await waitForDom(
        () => container.textContent?.includes(finalText) === true,
        "final retenido preservado",
      );
      expect(container.textContent).not.toContain("Interrumpido");
      expect(container.querySelectorAll(".activity-item--complete")).toHaveLength(1);
    } finally {
      vi.stubGlobal("fetch", nativeFetch);
    }
  });

  it("ante EOF reconcilia health→GET y nunca reenvía POST /message", async () => {
    const nativeFetch = globalThis.fetch;
    const calls: Array<{ url: string; method: string }> = [];
    const disconnectingFetch: typeof fetch = async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      calls.push({ url, method });
      if (url.endsWith("/message")) {
        return new Response('data: {"type":"token","text":"parcial"}\n\n', {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        });
      }
      return nativeFetch(input, init);
    };
    vi.stubGlobal("fetch", disconnectingFetch);
    try {
      await setFieldValue(container.querySelector<HTMLInputElement>("#core-url")!, mock!.baseUrl);
      await setFieldValue(container.querySelector<HTMLInputElement>("#core-token")!, mock!.token);
      await click(buttonNamed("Guardar")!);
      await waitForDom(() => container.querySelector(".settings-dialog") === null, "cierre de Ajustes");
      await setFieldValue(
        container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Mensaje"]')!,
        "Forzá un EOF recuperable",
      );
      await click(buttonNamed("Enviar")!);

      await waitForDom(
        () => container.textContent?.includes("snapshot todavía no contiene el turno completo") === true,
        "reconciliación sin replay",
      );
      expect(calls.filter(({ url }) => url.endsWith("/message"))).toHaveLength(1);
      expect(calls.some(({ url }) => url.endsWith("/healthz"))).toBe(true);
      expect(
        calls.some(
          ({ url, method }) =>
            method === "GET" && /\/session\/session_[^/]+$/.test(new URL(url).pathname),
        ),
      ).toBe(true);
    } finally {
      vi.stubGlobal("fetch", nativeFetch);
    }
  });
});
