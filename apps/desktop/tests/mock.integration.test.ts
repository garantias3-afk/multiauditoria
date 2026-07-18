import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { startMockCore, type MockCoreHandle } from "../mocks/server";
import { CoreApi } from "../src/core/api";
import type { CoreEvent } from "../src/core/types";
import {
  chatReducer,
  initialChatState,
  type ChatState,
  type ChatTurn,
} from "../src/state/chatReducer";

function assistantTurn(id: string): ChatTurn {
  return {
    id,
    role: "assistant",
    content: "",
    status: "streaming",
    attachments: [],
    brainNotices: [],
  };
}

function startChat(sessionId: string, assistantId: string): ChatState {
  const ready = chatReducer(initialChatState, { type: "SESSION_READY", sessionId });
  return chatReducer(ready, {
    type: "STREAM_STARTED",
    assistantTurn: assistantTurn(assistantId),
  });
}

describe("CoreApi contra Mock Core por HTTP/SSE real", () => {
  let mock: MockCoreHandle | undefined;
  let api: CoreApi;

  beforeAll(async () => {
    mock = await startMockCore({ port: 0, eventDelayMs: 0, token: "integration-token" });
    api = new CoreApi({ baseUrl: mock.baseUrl, token: mock.token });
  });

  afterAll(async () => {
    await mock?.close();
  });

  it("completa un turno con research, confirmación aprobada y tool posterior al permiso", async () => {
    const auditStart = mock!.auditLog.length;
    const { session_id: sessionId } = await api.createSession();
    const received: CoreEvent[] = [];
    let state = startChat(sessionId, "assistant-approved");
    let sequence = 0;

    await api.streamMessage(
      sessionId,
      {
        text: "Investigá y escribí el resultado simulado",
        attachments: [],
        tier_hint: "PAID_CHEAP",
        wants_cheap: false,
      },
      async (event) => {
        received.push(event);
        sequence += 1;
        state = chatReducer(state, {
          type: "CORE_EVENT",
          event,
          receivedAt: sequence * 100,
          eventId: `approved-${sequence}`,
        });

        if (event.type === "confirm_request") {
          expect(received.some((item) => item.type === "tool_start")).toBe(false);
          expect(received.some((item) => item.type === "tool_end")).toBe(false);
          expect(state.phase).toBe("paused");

          state = chatReducer(state, { type: "CONFIRM_SUBMIT_STARTED" });
          await api.confirm(sessionId, event.confirm_id, true);
          state = chatReducer(state, {
            type: "CONFIRM_RESOLVED",
            confirmId: event.confirm_id,
          });
        }
      },
    );

    expect(received.map((event) => event.type)).toEqual([
      "token",
      "brain_switch",
      "research_progress",
      "token",
      "research_progress",
      "confirm_request",
      "tool_start",
      "tool_end",
      "final",
    ]);
    expect(state.phase).toBe("idle");
    expect(state.pendingConfirmation).toBeNull();
    expect(state.research).toMatchObject({ iteration: 2, of: 2, cost_usd: 0.0042 });
    expect(state.activities).toHaveLength(1);
    expect(state.activities[0]).toMatchObject({
      tool: "filesystem.write_file",
      status: "complete",
      resultSummary: { ok: true },
    });
    expect(state.turns[0]).toMatchObject({
      status: "complete",
      content:
        "La simulación completó la investigación y ejecutó la herramienta después de tu aprobación.",
    });

    const audit = mock!.auditLog.slice(auditStart);
    expect(audit).toEqual([
      expect.objectContaining({ kind: "confirmation", approved: true }),
      {
        kind: "tool_execution",
        tool: "filesystem.write_file",
        sessionId,
      },
    ]);

    const persisted = await api.getSession(sessionId);
    expect(persisted.turns).toEqual([
      expect.objectContaining({
        role: "user",
        text: "Investigá y escribí el resultado simulado",
        tier_hint: "PAID_CHEAP",
        wants_cheap: false,
      }),
      expect.objectContaining({ role: "assistant", text: state.turns[0].content }),
    ]);
  });

  it("reanuda tras rechazo, finaliza y no emite ningún evento de ejecución", async () => {
    const auditStart = mock!.auditLog.length;
    const { session_id: sessionId } = await api.createSession();
    const received: CoreEvent[] = [];
    let state = startChat(sessionId, "assistant-rejected");
    let sequence = 0;

    await api.streamMessage(
      sessionId,
      { text: "No autorizaré la escritura", attachments: [], wants_cheap: true },
      async (event) => {
        received.push(event);
        sequence += 1;
        state = chatReducer(state, {
          type: "CORE_EVENT",
          event,
          receivedAt: sequence * 100,
          eventId: `rejected-${sequence}`,
        });

        if (event.type === "confirm_request") {
          state = chatReducer(state, { type: "CONFIRM_SUBMIT_STARTED" });
          await api.confirm(sessionId, event.confirm_id, false);
          state = chatReducer(state, {
            type: "CONFIRM_RESOLVED",
            confirmId: event.confirm_id,
          });
        }
      },
    );

    const eventTypes = received.map((event) => event.type);
    expect(eventTypes).toContain("confirm_request");
    expect(eventTypes).not.toContain("tool_start");
    expect(eventTypes).not.toContain("tool_end");
    expect(eventTypes.at(-1)).toBe("final");
    expect(state.activities).toEqual([]);
    expect(state.pendingConfirmation).toBeNull();
    expect(state.phase).toBe("idle");
    expect(state.turns[0]).toMatchObject({
      status: "complete",
      content: "Acción rechazada por el usuario. No ejecuté la herramienta.",
    });

    const audit = mock!.auditLog.slice(auditStart);
    expect(audit).toHaveLength(1);
    expect(audit[0]).toMatchObject({ kind: "confirmation", approved: false });
    expect(audit.some((entry) => entry.kind === "tool_execution")).toBe(false);

    const persisted = await api.getSession(sessionId);
    expect(persisted.turns).toHaveLength(2);
    expect(persisted.turns[1]).toEqual({
      role: "assistant",
      text: "Acción rechazada por el usuario. No ejecuté la herramienta.",
    });
  });

  it("sube multipart, envía el file_id y mantiene continuidad real de brain_switch", async () => {
    const before = await api.getBrains();
    const uploaded = await api.upload(
      new File(["contenido zip simulado"], "evidencia.zip", { type: "application/zip" }),
    );
    expect(uploaded).toMatchObject({
      file_id: expect.stringMatching(/^file_/),
      kind: "application/zip",
      size: 22,
    });

    const { session_id: sessionId } = await api.createSession();
    let brainSwitch: Extract<CoreEvent, { type: "brain_switch" }> | undefined;
    await api.streamMessage(
      sessionId,
      {
        text: "Usá el adjunto",
        attachments: [uploaded.file_id],
        tier_hint: "VIBE",
      },
      async (event) => {
        if (event.type === "brain_switch") brainSwitch = event;
        if (event.type === "confirm_request") {
          await api.confirm(sessionId, event.confirm_id, false);
        }
      },
    );

    expect(brainSwitch).toMatchObject({ from: before.escalon_activo, to: "VIBE" });
    const persisted = await api.getSession(sessionId);
    expect(persisted.turns[0]).toMatchObject({
      role: "user",
      text: "Usá el adjunto",
      attachments: [uploaded.file_id],
    });
  });

  it("expone con honestidad el rechazo 413 del upload", async () => {
    const tinyMock = await startMockCore({
      port: 0,
      eventDelayMs: 0,
      token: "tiny-upload-token",
      maxUploadBytes: 128,
    });
    try {
      const tinyApi = new CoreApi({ baseUrl: tinyMock.baseUrl, token: tinyMock.token });
      await expect(
        tinyApi.upload(new File(["x".repeat(256)], "demasiado.zip", { type: "application/zip" })),
      ).rejects.toThrow(/tamaño.*HTTP 413/i);
    } finally {
      await tinyMock.close();
    }
  });
});
