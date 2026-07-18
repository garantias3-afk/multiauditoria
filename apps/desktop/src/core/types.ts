export const TIERS = ["LOCAL", "FREE_QUOTA", "PAID_CHEAP", "VIBE"] as const;

export type Tier = (typeof TIERS)[number];

export interface Identity {
  model_id: string;
  provider_name: string;
  tier: Tier;
  cost_class: string;
}

export interface TokenEvent {
  type: "token";
  text: string;
}

export interface ToolStartEvent {
  type: "tool_start";
  tool: string;
  args: unknown;
}

export interface ToolEndEvent {
  type: "tool_end";
  tool: string;
  result_summary: unknown;
}

export interface BrainSwitchEvent {
  type: "brain_switch";
  from: Tier;
  to: Tier;
  reason: string;
  identity: Identity;
}

export interface ResearchProgressEvent {
  type: "research_progress";
  iteration: number;
  of: number;
  queries: unknown;
  sources_read: unknown;
  cost_usd: number;
}

export interface ConfirmRequestEvent {
  type: "confirm_request";
  tool: string;
  args: unknown;
  confirm_id: string;
}

export interface FinalEvent {
  type: "final";
  text: string;
}

export interface ErrorEvent {
  type: "error";
  message: string;
}

export type CoreEvent =
  | TokenEvent
  | ToolStartEvent
  | ToolEndEvent
  | BrainSwitchEvent
  | ResearchProgressEvent
  | ConfirmRequestEvent
  | FinalEvent
  | ErrorEvent;

export interface MessageRequest {
  text: string;
  attachments: string[];
  tier_hint?: Tier;
  wants_cheap?: boolean;
}

export interface SessionResponse {
  session_id: string;
  turns: unknown[];
}

export interface UploadResponse {
  file_id: string;
  kind: string;
  size: number;
}

export interface BrainBackend {
  tier: Tier;
  identity: Identity;
  alive: boolean;
}

export interface BrainsResponse {
  escalon_activo: Tier;
  backends: BrainBackend[];
  cost_usd_acumulado: number;
}

export interface HealthResponse {
  ok: boolean;
}

export class CoreProtocolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CoreProtocolError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value !== "string") {
    throw new CoreProtocolError(`El evento no contiene un campo string válido: ${key}`);
  }
  return value;
}

function requiredNonEmptyString(record: Record<string, unknown>, key: string): string {
  const value = requiredString(record, key);
  if (value.trim().length === 0) {
    throw new CoreProtocolError(`El evento no contiene un string no vacío válido: ${key}`);
  }
  return value;
}

function requiredFiniteNumber(record: Record<string, unknown>, key: string): number {
  const value = record[key];
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    throw new CoreProtocolError(`El evento no contiene un número finito no negativo válido: ${key}`);
  }
  return value;
}

function requiredField(record: Record<string, unknown>, key: string): unknown {
  if (!Object.prototype.hasOwnProperty.call(record, key)) {
    throw new CoreProtocolError(`El evento no contiene el campo obligatorio: ${key}`);
  }
  return record[key];
}

export function isTier(value: unknown): value is Tier {
  return typeof value === "string" && (TIERS as readonly string[]).includes(value);
}

function requiredTier(record: Record<string, unknown>, key: string): Tier {
  const value = record[key];
  if (!isTier(value)) {
    throw new CoreProtocolError(`El evento contiene un escalón desconocido: ${String(value)}`);
  }
  return value;
}

export function parseIdentity(value: unknown): Identity {
  if (!isRecord(value)) {
    throw new CoreProtocolError("identity debe ser un objeto");
  }

  return {
    model_id: requiredNonEmptyString(value, "model_id"),
    provider_name: requiredNonEmptyString(value, "provider_name"),
    tier: requiredTier(value, "tier"),
    cost_class: requiredNonEmptyString(value, "cost_class"),
  };
}

export function parseCoreEvent(value: unknown): CoreEvent {
  if (!isRecord(value) || typeof value.type !== "string") {
    throw new CoreProtocolError("Cada frame SSE debe contener un objeto JSON con type");
  }

  switch (value.type) {
    case "token":
      return { type: "token", text: requiredString(value, "text") };
    case "tool_start":
      return { type: "tool_start", tool: requiredNonEmptyString(value, "tool"), args: requiredField(value, "args") };
    case "tool_end":
      return {
        type: "tool_end",
        tool: requiredNonEmptyString(value, "tool"),
        result_summary: requiredField(value, "result_summary"),
      };
    case "brain_switch": {
      const identity = parseIdentity(value.identity);
      const to = requiredTier(value, "to");
      if (identity.tier !== to) {
        throw new CoreProtocolError("identity.tier no coincide con el destino de brain_switch");
      }
      return {
        type: "brain_switch",
        from: requiredTier(value, "from"),
        to,
        reason: requiredString(value, "reason"),
        identity,
      };
    }
    case "research_progress":
      return {
        type: "research_progress",
        iteration: requiredFiniteNumber(value, "iteration"),
        of: requiredFiniteNumber(value, "of"),
        queries: requiredField(value, "queries"),
        sources_read: requiredField(value, "sources_read"),
        cost_usd: requiredFiniteNumber(value, "cost_usd"),
      };
    case "confirm_request":
      return {
        type: "confirm_request",
        tool: requiredNonEmptyString(value, "tool"),
        args: requiredField(value, "args"),
        confirm_id: requiredNonEmptyString(value, "confirm_id"),
      };
    case "final":
      return { type: "final", text: requiredString(value, "text") };
    case "error":
      return { type: "error", message: requiredNonEmptyString(value, "message") };
    default:
      throw new CoreProtocolError(`Tipo de evento SSE no reconocido: ${value.type}`);
  }
}

export function parseSessionResponse(value: unknown): SessionResponse {
  if (!isRecord(value) || !Array.isArray(value.turns)) {
    throw new CoreProtocolError("Respuesta de sesión inválida");
  }
  return { session_id: requiredNonEmptyString(value, "session_id"), turns: value.turns };
}

export function parseUploadResponse(value: unknown): UploadResponse {
  if (!isRecord(value)) {
    throw new CoreProtocolError("Respuesta de upload inválida");
  }
  return {
    file_id: requiredNonEmptyString(value, "file_id"),
    kind: requiredNonEmptyString(value, "kind"),
    size: requiredFiniteNumber(value, "size"),
  };
}

export function parseBrainsResponse(value: unknown): BrainsResponse {
  if (!isRecord(value) || !Array.isArray(value.backends)) {
    throw new CoreProtocolError("Respuesta de brains inválida");
  }

  const backends = value.backends.map((backend): BrainBackend => {
    if (!isRecord(backend) || typeof backend.alive !== "boolean") {
      throw new CoreProtocolError("Backend de brains inválido");
    }
    const tier = requiredTier(backend, "tier");
    const identity = parseIdentity(backend.identity);
    if (identity.tier !== tier) {
      throw new CoreProtocolError("backend.tier no coincide con identity.tier");
    }
    return {
      tier,
      identity,
      alive: backend.alive,
    };
  });

  return {
    escalon_activo: requiredTier(value, "escalon_activo"),
    backends,
    cost_usd_acumulado: requiredFiniteNumber(value, "cost_usd_acumulado"),
  };
}

export function parseHealthResponse(value: unknown): HealthResponse {
  if (!isRecord(value) || typeof value.ok !== "boolean") {
    throw new CoreProtocolError("Respuesta de healthz inválida");
  }
  return { ok: value.ok };
}
