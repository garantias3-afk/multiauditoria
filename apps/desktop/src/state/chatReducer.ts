import type {
  BrainSwitchEvent,
  ConfirmRequestEvent,
  CoreEvent,
  Identity,
  ResearchProgressEvent,
  Tier,
} from "../core/types";

export interface ChatAttachment {
  fileId: string;
  name: string;
  kind: string;
  size: number;
  previewUrl?: string;
}

export interface BrainNotice {
  id: string;
  at: number;
  event: BrainSwitchEvent;
}

export interface ChatTurn {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  status: "complete" | "streaming" | "error" | "interrupted" | "recovered_unverified";
  attachments: ChatAttachment[];
  brainNotices: BrainNotice[];
}

export interface ToolActivity {
  id: string;
  tool: string;
  args: unknown;
  resultSummary?: unknown;
  startedAt: number;
  endedAt?: number;
  status: "running" | "complete" | "orphan_end" | "outcome_unknown";
}

export interface PendingConfirmation {
  event: ConfirmRequestEvent;
  receivedAt: number;
}

export type ChatPhase = "idle" | "streaming" | "paused" | "interrupting" | "error";

export interface ChatState {
  sessionId: string | null;
  turns: ChatTurn[];
  activities: ToolActivity[];
  research: ResearchProgressEvent | null;
  pendingConfirmation: PendingConfirmation | null;
  confirmationSubmitting: boolean;
  phase: ChatPhase;
  error: string | null;
  connectionNotice: string | null;
  activeTier: Tier | null;
  activeIdentity: Identity | null;
}

export const initialChatState: ChatState = {
  sessionId: null,
  turns: [],
  activities: [],
  research: null,
  pendingConfirmation: null,
  confirmationSubmitting: false,
  phase: "idle",
  error: null,
  connectionNotice: null,
  activeTier: null,
  activeIdentity: null,
};

export type ChatAction =
  | { type: "SESSION_READY"; sessionId: string; turns?: ChatTurn[] }
  | { type: "RESET_SESSION" }
  | { type: "USER_MESSAGE"; turn: ChatTurn }
  | { type: "STREAM_STARTED"; assistantTurn: ChatTurn }
  | { type: "CORE_EVENT"; event: CoreEvent; receivedAt: number; eventId: string }
  | { type: "CONFIRM_SUBMIT_STARTED" }
  | { type: "CONFIRM_RESOLVED"; confirmId: string }
  | { type: "INTERRUPT_STARTED" }
  | { type: "INTERRUPT_FAILED"; message: string }
  | { type: "STREAM_INTERRUPTED"; terminalError?: string }
  | { type: "STREAM_FAILURE"; message: string; recoverable: boolean; clearConfirmation?: boolean }
  | { type: "CONNECTION_NOTICE"; message: string | null }
  | { type: "BRAIN_STATUS"; tier: Tier; identity: Identity | null };

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "SESSION_READY":
      return {
        ...initialChatState,
        sessionId: action.sessionId,
        turns: action.turns ?? [],
        activeTier: state.activeTier,
        activeIdentity: state.activeIdentity,
      };
    case "RESET_SESSION":
      return initialChatState;
    case "USER_MESSAGE":
      return { ...state, turns: [...state.turns, action.turn], error: null, connectionNotice: null };
    case "STREAM_STARTED":
      return {
        ...state,
        turns: [...state.turns, action.assistantTurn],
        phase: "streaming",
        error: null,
        activities: [],
        research: null,
        connectionNotice: null,
      };
    case "CORE_EVENT":
      return reduceCoreEvent(state, action.event, action.receivedAt, action.eventId);
    case "CONFIRM_SUBMIT_STARTED":
      return { ...state, confirmationSubmitting: true };
    case "CONFIRM_RESOLVED":
      if (state.pendingConfirmation?.event.confirm_id !== action.confirmId) {
        return state;
      }
      return {
        ...state,
        pendingConfirmation: null,
        confirmationSubmitting: false,
        phase: "streaming",
      };
    case "INTERRUPT_STARTED":
      return { ...state, phase: "interrupting", error: null };
    case "INTERRUPT_FAILED":
      return {
        ...state,
        phase: hasStreamingAssistant(state.turns)
          ? state.pendingConfirmation
            ? "paused"
            : "streaming"
          : state.phase,
        confirmationSubmitting: false,
        error: action.message,
      };
    case "STREAM_INTERRUPTED":
      return {
        ...state,
        phase: action.terminalError ? "error" : "idle",
        error: action.terminalError ?? null,
        connectionNotice: action.terminalError
          ? "El Core confirmó la solicitud de interrupción y también informó un error terminal."
          : null,
        pendingConfirmation: null,
        confirmationSubmitting: false,
        turns: action.terminalError ? state.turns : updateLastInterruptibleAssistant(state.turns),
        activities: closeRunningActivities(state.activities),
      };
    case "STREAM_FAILURE":
      return {
        ...state,
        phase: "error",
        error: action.message,
        connectionNotice: action.recoverable ? "Intentando reconciliar la sesión sin reenviar el mensaje…" : null,
        pendingConfirmation: action.clearConfirmation ? null : state.pendingConfirmation,
        confirmationSubmitting: action.clearConfirmation ? false : state.confirmationSubmitting,
        turns: updateStreamingAssistant(state.turns, (turn) => ({ ...turn, status: "error" })),
        activities: closeRunningActivities(state.activities),
      };
    case "CONNECTION_NOTICE":
      return { ...state, connectionNotice: action.message };
    case "BRAIN_STATUS":
      return { ...state, activeTier: action.tier, activeIdentity: action.identity };
    default:
      return state;
  }
}

function reduceCoreEvent(state: ChatState, event: CoreEvent, at: number, eventId: string): ChatState {
  if (state.pendingConfirmation && event.type !== "error") {
    return {
      ...state,
      phase: "paused",
      error: `Violación de protocolo: el Core emitió ${event.type} antes de resolver la confirmación humana.`,
    };
  }

  switch (event.type) {
    case "token":
      return {
        ...state,
        turns: updateStreamingAssistant(state.turns, (turn) => ({ ...turn, content: turn.content + event.text })),
      };
    case "tool_start":
      return {
        ...state,
        activities: [
          ...state.activities,
          {
            id: eventId,
            tool: event.tool,
            args: event.args,
            startedAt: at,
            status: "running",
          },
        ],
      };
    case "tool_end": {
      let matched = false;
      const activities = [...state.activities];
      for (let index = activities.length - 1; index >= 0; index -= 1) {
        const activity = activities[index];
        if (!matched && activity.tool === event.tool && activity.status === "running") {
          activities[index] = {
            ...activity,
            resultSummary: event.result_summary,
            endedAt: at,
            status: "complete",
          };
          matched = true;
        }
      }
      if (!matched) {
        activities.push({
          id: eventId,
          tool: event.tool,
          args: null,
          resultSummary: event.result_summary,
          startedAt: at,
          endedAt: at,
          status: "orphan_end",
        });
      }
      return { ...state, activities };
    }
    case "brain_switch": {
      const notice: BrainNotice = { id: eventId, at, event };
      return {
        ...state,
        activeTier: event.to,
        activeIdentity: event.identity,
        turns: updateStreamingAssistant(state.turns, (turn) => ({
          ...turn,
          brainNotices: [...turn.brainNotices, notice],
        })),
      };
    }
    case "research_progress":
      return { ...state, research: event };
    case "confirm_request":
      return {
        ...state,
        phase: "paused",
        pendingConfirmation: { event, receivedAt: at },
        confirmationSubmitting: false,
      };
    case "final":
      return {
        ...state,
        phase: "idle",
        error: null,
        connectionNotice: null,
        activities: closeRunningActivities(state.activities, at),
        turns: updateStreamingAssistant(state.turns, (turn) => ({
          ...turn,
          content: event.text,
          status: "complete",
        })),
      };
    case "error":
      return {
        ...state,
        phase: "error",
        error: event.message,
        pendingConfirmation: null,
        confirmationSubmitting: false,
        activities: closeRunningActivities(state.activities, at),
        turns: updateStreamingAssistant(state.turns, (turn) => ({ ...turn, status: "error" })),
      };
    default:
      return state;
  }
}

function updateStreamingAssistant(
  turns: ChatTurn[],
  update: (turn: ChatTurn) => ChatTurn,
): ChatTurn[] {
  const result = [...turns];
  for (let index = result.length - 1; index >= 0; index -= 1) {
    if (result[index].role === "assistant" && result[index].status === "streaming") {
      result[index] = update(result[index]);
      break;
    }
  }
  return result;
}

function updateLastInterruptibleAssistant(turns: ChatTurn[]): ChatTurn[] {
  const result = [...turns];
  for (let index = result.length - 1; index >= 0; index -= 1) {
    const turn = result[index];
    if (turn.role !== "assistant") continue;
    if (turn.status === "streaming" || turn.status === "error") {
      result[index] = { ...turn, status: "interrupted" };
    }
    break;
  }
  return result;
}

function closeRunningActivities(
  activities: ToolActivity[],
  endedAt?: number,
): ToolActivity[] {
  return activities.map((activity) =>
    activity.status === "running"
      ? { ...activity, status: "outcome_unknown", ...(endedAt === undefined ? {} : { endedAt }) }
      : activity,
  );
}

export function normalizeSessionTurns(turns: unknown[]): ChatTurn[] {
  return normalizeSessionTurnsWithOptions(turns);
}

export function normalizeRecoveredSessionTurns(turns: unknown[]): ChatTurn[] {
  return normalizeSessionTurnsWithOptions(turns, true);
}

function normalizeSessionTurnsWithOptions(turns: unknown[], recovered = false): ChatTurn[] {
  const normalized: ChatTurn[] = turns.map((raw, index): ChatTurn => {
    const turn = isRecord(raw) ? raw : {};
    const role = turn.role === "user" || turn.role === "system" ? turn.role : "assistant";
    const text = typeof turn.text === "string" ? turn.text : typeof turn.content === "string" ? turn.content : safeJson(raw);
    return {
      id: typeof turn.id === "string" ? turn.id : `history-${index}`,
      role,
      content: text,
      status: "complete",
      attachments: [],
      brainNotices: [],
    };
  });
  if (recovered) {
    for (let index = normalized.length - 1; index >= 0; index -= 1) {
      if (normalized[index].role === "assistant") {
        normalized[index] = { ...normalized[index], status: "recovered_unverified" };
        break;
      }
    }
  }
  return normalized;
}

function hasStreamingAssistant(turns: ChatTurn[]): boolean {
  return turns.some((turn) => turn.role === "assistant" && turn.status === "streaming");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function safeJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? String(value);
  } catch {
    return String(value);
  }
}
