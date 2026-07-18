import { describe, expect, it, vi } from "vitest";

import {
  CoreApi,
  CoreApiError,
  StreamDisconnectedError,
} from "../src/core/api";
import type { CoreEvent } from "../src/core/types";

function jsonResponse(value: unknown, init: ResponseInit = {}): Response {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  return new Response(JSON.stringify(value), {
    ...init,
    headers,
  });
}

function sseResponse(events: CoreEvent[]): Response {
  const body = events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream; charset=utf-8" },
  });
}

describe("CoreApi HITL", () => {
  it("envía un rechazo mediante el único POST contractual y con approved false exacto", async () => {
    const requestSpy = vi.fn<typeof fetch>(async () => jsonResponse({ ok: true }));
    const api = new CoreApi({
      baseUrl: "http://127.0.0.1:8850/",
      token: "test-token",
      fetchImpl: requestSpy,
    });

    await api.confirm("session / uno", "confirm-9", false);

    expect(requestSpy).toHaveBeenCalledTimes(1);
    const [url, maybeInit] = requestSpy.mock.calls[0];
    expect(String(url)).toBe("http://127.0.0.1:8850/session/session%20%2F%20uno/confirm");
    expect(maybeInit).toBeDefined();
    const init = maybeInit as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.body).toBe('{"confirm_id":"confirm-9","approved":false}');
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer test-token");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("Cache-Control")).toBe("no-store");
  });

  it("no auto-aprueba ni llama /confirm al recibir confirm_request", async () => {
    const streamed: CoreEvent[] = [
      {
        type: "confirm_request",
        tool: "write_file",
        args: { path: "/tmp/a" },
        confirm_id: "confirm-manual",
      },
      { type: "error", message: "La prueba cierra sin decisión humana" },
    ];
    const requestSpy = vi.fn<typeof fetch>(async () => sseResponse(streamed));
    const api = new CoreApi({
      baseUrl: "http://localhost:8850",
      token: "test-token",
      fetchImpl: requestSpy,
    });
    const received: CoreEvent[] = [];

    await api.streamMessage(
      "session-1",
      { text: "acción sensible", attachments: [] },
      (event) => {
        received.push(event);
      },
    );

    expect(received).toEqual(streamed);
    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(String(requestSpy.mock.calls[0][0])).toMatch(/\/session\/session-1\/message$/);
    expect(requestSpy.mock.calls.some(([url]) => String(url).endsWith("/confirm"))).toBe(false);
  });

  it("no considera resuelta la decisión si el Core no responde ok true", async () => {
    const requestSpy = vi.fn<typeof fetch>(async () => jsonResponse({ ok: false }));
    const api = new CoreApi({
      baseUrl: "http://127.0.0.1:8850",
      token: "test-token",
      fetchImpl: requestSpy,
    });

    await expect(api.confirm("session-1", "confirm-1", false)).rejects.toThrow(
      /no confirmó la decisión humana/,
    );
  });
});

describe("CoreApi streaming terminal y desconexión", () => {
  function apiReturning(response: Response): CoreApi {
    const fetchImpl = vi.fn<typeof fetch>(async () => response);
    return new CoreApi({
      baseUrl: "http://127.0.0.1:8850",
      token: "test-token",
      fetchImpl,
    });
  }

  const message = { text: "stream", attachments: [] };

  it("distingue EOF sin eventos como desconexión con contador cero", async () => {
    const api = apiReturning(
      new Response("", { headers: { "Content-Type": "text/event-stream" } }),
    );

    try {
      await api.streamMessage("session-1", message, vi.fn());
      expect.unreachable("EOF sin terminal debía rechazar");
    } catch (error) {
      expect(error).toBeInstanceOf(StreamDisconnectedError);
      expect(error).toMatchObject({ eventsReceived: 0 });
    }
  });

  it("preserva eventos parciales y reporta cuántos recibió cuando falta terminal", async () => {
    const api = apiReturning(sseResponse([{ type: "token", text: "parcial" }]));
    const received: CoreEvent[] = [];

    try {
      await api.streamMessage("session-1", message, (event) => {
        received.push(event);
      });
      expect.unreachable("EOF parcial sin terminal debía rechazar");
    } catch (error) {
      expect(error).toBeInstanceOf(StreamDisconnectedError);
      expect(error).toMatchObject({ eventsReceived: 1 });
    }
    expect(received).toEqual([{ type: "token", text: "parcial" }]);
  });

  it("rechaza un evento posterior al terminal dentro del mismo chunk", async () => {
    const api = apiReturning(
      sseResponse([
        { type: "final", text: "terminó" },
        { type: "token", text: "evento ilegal" },
      ]),
    );
    const received: CoreEvent[] = [];

    await expect(
      api.streamMessage("session-1", message, (event) => {
        received.push(event);
      }),
    ).rejects.toThrow(/después de un evento terminal/);
    expect(received).toEqual([{ type: "final", text: "terminó" }]);
  });

  it("rechaza respuestas que no declaran text/event-stream", async () => {
    const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({ cancel });
    const api = apiReturning(
      new Response(body, { headers: { "Content-Type": "application/json" } }),
    );

    await expect(api.streamMessage("session-1", message, vi.fn())).rejects.toMatchObject({
      name: "CoreApiError",
      message: expect.stringMatching(/text\/event-stream/),
    } satisfies Partial<CoreApiError>);
    expect(cancel).toHaveBeenCalledTimes(1);
  });

  it("cancela el reader después de recibir un terminal aunque el transporte quede abierto", async () => {
    const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode('data: {"type":"final","text":"listo"}\n\n'),
        );
      },
      cancel,
    });
    const api = apiReturning(
      new Response(body, { headers: { "Content-Type": "text/event-stream" } }),
    );
    const received: CoreEvent[] = [];

    await api.streamMessage("session-1", message, (event) => {
      received.push(event);
    });

    expect(received).toEqual([{ type: "final", text: "listo" }]);
    expect(cancel).toHaveBeenCalledTimes(1);
  });
});

describe("CoreApi identidad de sesión", () => {
  it("rechaza un snapshot cuyo session_id no coincide con el solicitado", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () =>
      jsonResponse({ session_id: "session-equivocada", turns: [] }),
    );
    const api = new CoreApi({
      baseUrl: "http://127.0.0.1:8850",
      token: "test-token",
      fetchImpl,
    });

    await expect(api.getSession("session-esperada")).rejects.toThrow(/sesión distinta/);
  });
});
