import { describe, expect, it } from "vitest";

import type { BrainSwitchEvent, CoreEvent, ResearchProgressEvent } from "../src/core/types";
import {
  chatReducer,
  initialChatState,
  type ChatState,
  type ChatTurn,
} from "../src/state/chatReducer";

function assistantTurn(overrides: Partial<ChatTurn> = {}): ChatTurn {
  return {
    id: "assistant-1",
    role: "assistant",
    content: "",
    status: "streaming",
    attachments: [],
    brainNotices: [],
    ...overrides,
  };
}

function streamingState(): ChatState {
  return chatReducer(
    { ...initialChatState, sessionId: "session-1" },
    { type: "STREAM_STARTED", assistantTurn: assistantTurn() },
  );
}

function coreEvent(
  state: ChatState,
  event: CoreEvent,
  receivedAt: number,
  eventId: string,
): ChatState {
  return chatReducer(state, { type: "CORE_EVENT", event, receivedAt, eventId });
}

describe("chatReducer", () => {
  it("acumula tokens en un único turno y usa final como texto canónico sin duplicarlo", () => {
    const started = streamingState();
    const first = coreEvent(started, { type: "token", text: "Hola" }, 10, "event-1");
    const second = coreEvent(first, { type: "token", text: " mundo" }, 20, "event-2");
    const completed = coreEvent(
      second,
      { type: "final", text: "Hola mundo." },
      30,
      "event-3",
    );

    expect(started.turns[0].content).toBe("");
    expect(second.turns).toHaveLength(1);
    expect(second.turns[0]).toMatchObject({ content: "Hola mundo", status: "streaming" });
    expect(completed.turns[0]).toMatchObject({ content: "Hola mundo.", status: "complete" });
    expect(completed.phase).toBe("idle");
  });

  it("cierra primero la tool duplicada más recientemente abierta", () => {
    let state = streamingState();
    state = coreEvent(
      state,
      { type: "tool_start", tool: "search", args: { query: "primera" } },
      100,
      "tool-1",
    );
    state = coreEvent(
      state,
      { type: "tool_start", tool: "search", args: { query: "segunda" } },
      200,
      "tool-2",
    );
    state = coreEvent(
      state,
      { type: "tool_end", tool: "search", result_summary: "segunda lista" },
      260,
      "end-2",
    );

    expect(state.activities).toEqual([
      expect.objectContaining({ id: "tool-1", status: "running", startedAt: 100 }),
      expect.objectContaining({
        id: "tool-2",
        status: "complete",
        startedAt: 200,
        endedAt: 260,
        resultSummary: "segunda lista",
      }),
    ]);

    state = coreEvent(
      state,
      { type: "tool_end", tool: "search", result_summary: "primera lista" },
      300,
      "end-1",
    );
    expect(state.activities[0]).toMatchObject({
      id: "tool-1",
      status: "complete",
      endedAt: 300,
      resultSummary: "primera lista",
    });
  });

  it("registra un tool_end huérfano de forma visible", () => {
    const state = coreEvent(
      streamingState(),
      { type: "tool_end", tool: "missing", result_summary: "resultado inesperado" },
      50,
      "orphan-1",
    );

    expect(state.activities).toEqual([
      {
        id: "orphan-1",
        tool: "missing",
        args: null,
        resultSummary: "resultado inesperado",
        startedAt: 50,
        endedAt: 50,
        status: "orphan_end",
      },
    ]);
  });

  it("conserva todos los datos del progreso de research", () => {
    const event: ResearchProgressEvent = {
      type: "research_progress",
      iteration: 3,
      of: 5,
      queries: ["consulta uno", "consulta dos"],
      sources_read: { count: 8 },
      cost_usd: 0.0034,
    };

    const state = coreEvent(streamingState(), event, 100, "research-1");

    expect(state.research).toEqual(event);
  });

  it("inicia cada turno con actividad y research propios", () => {
    let state = coreEvent(
      streamingState(),
      { type: "tool_start", tool: "search", args: { q: "turno anterior" } },
      10,
      "old-tool",
    );
    state = coreEvent(
      state,
      {
        type: "research_progress",
        iteration: 1,
        of: 1,
        queries: [],
        sources_read: [],
        cost_usd: 0,
      },
      20,
      "old-research",
    );

    const next = chatReducer(state, {
      type: "STREAM_STARTED",
      assistantTurn: assistantTurn({ id: "assistant-2" }),
    });

    expect(next.activities).toEqual([]);
    expect(next.research).toBeNull();
  });

  it("deja de afirmar que una tool sigue en curso si el stream falla", () => {
    const running = coreEvent(
      streamingState(),
      { type: "tool_start", tool: "search", args: {} },
      10,
      "tool-running",
    );

    const failed = chatReducer(running, {
      type: "STREAM_FAILURE",
      message: "SSE desconectado",
      recoverable: true,
    });

    expect(failed.activities[0]).toMatchObject({
      id: "tool-running",
      status: "outcome_unknown",
    });
  });

  it("actualiza cerebro e inserta el aviso en el turno assistant activo", () => {
    const event: BrainSwitchEvent = {
      type: "brain_switch",
      from: "LOCAL",
      to: "VIBE",
      reason: "Se agotaron los escalones baratos",
      identity: {
        model_id: "vibe-mock",
        provider_name: "Mock Provider",
        tier: "VIBE",
        cost_class: "expensive",
      },
    };

    const state = coreEvent(streamingState(), event, 444, "brain-1");

    expect(state.activeTier).toBe("VIBE");
    expect(state.activeIdentity).toEqual(event.identity);
    expect(state.turns[0].brainNotices).toEqual([{ id: "brain-1", at: 444, event }]);
  });

  it("limpia la identidad anterior al cambiar de credenciales/Core", () => {
    const state: ChatState = {
      ...initialChatState,
      activeTier: "VIBE",
      activeIdentity: {
        model_id: "old-model",
        provider_name: "Old Core",
        tier: "VIBE",
        cost_class: "expensive",
      },
    };

    expect(chatReducer(state, { type: "RESET_SESSION" })).toEqual(initialChatState);
  });

  it("pausa ante HITL y no permite que otro evento avance antes de resolverlo", () => {
    const paused = coreEvent(
      streamingState(),
      {
        type: "confirm_request",
        tool: "delete_file",
        args: { path: "/tmp/a" },
        confirm_id: "confirm-1",
      },
      500,
      "confirm-event",
    );

    expect(paused.phase).toBe("paused");
    expect(paused.pendingConfirmation).toMatchObject({
      receivedAt: 500,
      event: { confirm_id: "confirm-1", tool: "delete_file" },
    });

    const violated = coreEvent(paused, { type: "token", text: "no debe verse" }, 510, "token-late");
    expect(violated.phase).toBe("paused");
    expect(violated.turns[0].content).toBe("");
    expect(violated.pendingConfirmation).toEqual(paused.pendingConfirmation);
    expect(violated.error).toMatch(/Violación de protocolo/);
  });

  it("sólo resuelve HITL con el confirm_id correcto", () => {
    let state = coreEvent(
      streamingState(),
      {
        type: "confirm_request",
        tool: "write_file",
        args: { path: "/tmp/a" },
        confirm_id: "confirm-real",
      },
      500,
      "confirm-event",
    );
    state = chatReducer(state, { type: "CONFIRM_SUBMIT_STARTED" });
    expect(state.confirmationSubmitting).toBe(true);

    const wrongId = chatReducer(state, { type: "CONFIRM_RESOLVED", confirmId: "otro-id" });
    expect(wrongId).toBe(state);

    const resolved = chatReducer(state, {
      type: "CONFIRM_RESOLVED",
      confirmId: "confirm-real",
    });
    expect(resolved.phase).toBe("streaming");
    expect(resolved.pendingConfirmation).toBeNull();
    expect(resolved.confirmationSubmitting).toBe(false);
  });

  it("retira una confirmación si el SSE se corta para impedir acciones sin canal de resultado", () => {
    let state = coreEvent(
      streamingState(),
      {
        type: "confirm_request",
        tool: "write_file",
        args: { path: "/tmp/a" },
        confirm_id: "confirm-disconnected",
      },
      500,
      "confirm-event",
    );
    state = chatReducer(state, { type: "CONFIRM_SUBMIT_STARTED" });

    const disconnected = chatReducer(state, {
      type: "STREAM_FAILURE",
      message: "SSE desconectado",
      recoverable: true,
      clearConfirmation: true,
    });

    expect(disconnected).toMatchObject({
      phase: "error",
      pendingConfirmation: null,
      confirmationSubmitting: false,
    });
    expect(disconnected.connectionNotice).toMatch(/reconciliar/);
  });

  it("convierte un error terminal en estado visible sin perder el texto parcial", () => {
    const partial = coreEvent(
      streamingState(),
      { type: "token", text: "Trabajo parcial" },
      10,
      "token-1",
    );
    const failed = coreEvent(
      partial,
      { type: "error", message: "Falló la herramienta" },
      20,
      "error-1",
    );

    expect(failed.phase).toBe("error");
    expect(failed.error).toBe("Falló la herramienta");
    expect(failed.turns[0]).toMatchObject({ content: "Trabajo parcial", status: "error" });
  });

  it("no oculta un error terminal aunque el ACK de interrupt llegue después", () => {
    const partial = coreEvent(
      streamingState(),
      { type: "token", text: "Trabajo parcial" },
      10,
      "token-1",
    );
    const terminalFirst = coreEvent(
      partial,
      { type: "error", message: "Turno interrumpido por el usuario." },
      20,
      "error-1",
    );
    const acknowledged = chatReducer(terminalFirst, {
      type: "STREAM_INTERRUPTED",
      terminalError: "Turno interrumpido por el usuario.",
    });

    expect(acknowledged.phase).toBe("error");
    expect(acknowledged.error).toBe("Turno interrumpido por el usuario.");
    expect(acknowledged.connectionNotice).toMatch(/también informó un error terminal/);
    expect(acknowledged.turns[0]).toMatchObject({
      content: "Trabajo parcial",
      status: "error",
    });
  });

  it("no rebautiza un error histórico si el turno actual finalizó antes del ACK de interrupt", () => {
    const historical: ChatTurn = assistantTurn({
      id: "assistant-old",
      status: "error",
      content: "fallo anterior",
    });
    const current: ChatTurn = assistantTurn({
      id: "assistant-current",
      status: "complete",
      content: "final concurrente",
    });
    const state: ChatState = {
      ...initialChatState,
      sessionId: "session-1",
      turns: [historical, current],
      phase: "interrupting",
    };

    const acknowledged = chatReducer(state, { type: "STREAM_INTERRUPTED" });

    expect(acknowledged.turns).toEqual([historical, current]);
    expect(acknowledged.phase).toBe("idle");
  });
});
