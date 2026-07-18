import { randomUUID, timingSafeEqual } from "node:crypto";
import {
  createServer,
  type IncomingMessage,
  type Server,
  type ServerResponse,
} from "node:http";
import type { AddressInfo, Socket } from "node:net";
import { pathToFileURL } from "node:url";

import {
  TIERS,
  type CoreEvent,
  type Identity,
  type MessageRequest,
  type Tier,
} from "../src/core/types";

export const DEFAULT_MOCK_API_TOKEN = "robot-mock-token";

const DEFAULT_HOST = "127.0.0.1";
const CLI_PORT = 8850;
const MAX_JSON_BYTES = 1024 * 1024;
const MAX_UPLOAD_BYTES = 32 * 1024 * 1024;

interface StoredTurn {
  role: "user" | "assistant";
  text: string;
  attachments?: string[];
  tier_hint?: Tier;
  wants_cheap?: boolean;
}

interface MockSession {
  session_id: string;
  turns: StoredTurn[];
}

interface UploadedFile {
  file_id: string;
  kind: string;
  size: number;
  name: string;
}

interface ActiveTurn {
  session: MockSession;
  response: ServerResponse;
  cancelled: boolean;
  completed: boolean;
  cancellers: Set<() => void>;
}

type ConfirmationDecision = "approved" | "rejected" | "cancelled";

interface PendingConfirmation {
  sessionId: string;
  settle: (decision: ConfirmationDecision) => void;
}

export interface MockCoreOptions {
  /** Use port 0 (the default) in tests so the operating system chooses a free port. */
  port?: number;
  host?: string;
  token?: string;
  /** Small scripted pauses make streaming observable without making tests slow. */
  eventDelayMs?: number;
  /** Override the upload ceiling in focused tests; production-like mock default is 32 MiB. */
  maxUploadBytes?: number;
}

export interface MockCoreHandle {
  server: Server;
  host: string;
  port: number;
  baseUrl: string;
  /** Alias useful to callers that conventionally name server addresses `url`. */
  url: string;
  token: string;
  auditLog: MockAuditEntry[];
  close: () => Promise<void>;
  stop: () => Promise<void>;
}

export type MockAuditEntry =
  | { kind: "confirmation"; confirmId: string; approved: boolean }
  | { kind: "tool_execution"; tool: string; sessionId: string }
  | { kind: "interrupt"; sessionId: string; hadActiveTurn: boolean };

class HttpError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "HttpError";
    this.status = status;
  }
}

const IDENTITIES: Record<Tier, Identity> = {
  LOCAL: {
    model_id: "mock-local-8b",
    provider_name: "Mock Local Runtime",
    tier: "LOCAL",
    cost_class: "local_free",
  },
  FREE_QUOTA: {
    model_id: "mock-free-quota",
    provider_name: "Mock Free Provider",
    tier: "FREE_QUOTA",
    cost_class: "free_quota",
  },
  PAID_CHEAP: {
    model_id: "mock-paid-cheap",
    provider_name: "Mock Metered Provider",
    tier: "PAID_CHEAP",
    cost_class: "paid_cheap",
  },
  VIBE: {
    model_id: "mock-vibe-premium",
    provider_name: "Mock Premium Provider",
    tier: "VIBE",
    cost_class: "paid_premium",
  },
};

/**
 * Starts an in-memory implementation of the exact Core API surface used by the
 * desktop client. Passing a number is supported as a shorthand for `{ port }`.
 */
export async function startMockCore(
  optionsOrPort: MockCoreOptions | number = {},
): Promise<MockCoreHandle> {
  const options =
    typeof optionsOrPort === "number" ? { port: optionsOrPort } : optionsOrPort;
  const host = options.host?.trim() || DEFAULT_HOST;
  const port = options.port ?? 0;
  const token = options.token?.trim() || process.env.ROBOT_API_TOKEN?.trim() || DEFAULT_MOCK_API_TOKEN;
  const eventDelayMs = options.eventDelayMs ?? 8;
  const maxUploadBytes = options.maxUploadBytes ?? MAX_UPLOAD_BYTES;

  if (!Number.isInteger(port) || port < 0 || port > 65_535) {
    throw new RangeError("Mock Core port must be an integer between 0 and 65535.");
  }
  if (!Number.isFinite(eventDelayMs) || eventDelayMs < 0) {
    throw new RangeError("Mock Core eventDelayMs must be a non-negative number.");
  }
  if (!Number.isInteger(maxUploadBytes) || maxUploadBytes < 1) {
    throw new RangeError("Mock Core maxUploadBytes must be a positive integer.");
  }

  const sessions = new Map<string, MockSession>();
  const uploads = new Map<string, UploadedFile>();
  const activeTurns = new Map<string, ActiveTurn>();
  const pendingConfirmations = new Map<string, PendingConfirmation>();
  const sockets = new Set<Socket>();
  const timerCancellers = new Set<() => void>();
  const auditLog: MockAuditEntry[] = [];

  let activeTier: Tier = "LOCAL";
  let accumulatedCostUsd = 0;
  let stopping = false;
  let closePromise: Promise<void> | undefined;

  function setCorsHeaders(request: IncomingMessage, response: ServerResponse): void {
    const originHeader = request.headers.origin;
    const origin = Array.isArray(originHeader) ? originHeader[0] : originHeader;
    response.setHeader("Access-Control-Allow-Origin", origin || "*");
    response.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    response.setHeader(
      "Access-Control-Allow-Headers",
      "Authorization, Content-Type, Accept, Cache-Control",
    );
    response.setHeader("Access-Control-Max-Age", "600");
    if (request.headers["access-control-request-private-network"] === "true") {
      response.setHeader("Access-Control-Allow-Private-Network", "true");
    }
    response.setHeader("Vary", "Origin");
    response.setHeader("Cache-Control", "no-store");
    response.setHeader("X-Content-Type-Options", "nosniff");
  }

  function sendJson(response: ServerResponse, status: number, value: unknown): void {
    if (response.destroyed || response.writableEnded) return;
    const body = Buffer.from(JSON.stringify(value), "utf8");
    response.statusCode = status;
    response.setHeader("Content-Type", "application/json; charset=utf-8");
    response.setHeader("Content-Length", String(body.byteLength));
    response.end(body);
  }

  function isAuthorized(request: IncomingMessage): boolean {
    const suppliedHeader = request.headers.authorization;
    const supplied = Array.isArray(suppliedHeader) ? suppliedHeader[0] ?? "" : suppliedHeader ?? "";
    const expectedBytes = Buffer.from(`Bearer ${token}`, "utf8");
    const suppliedBytes = Buffer.from(supplied, "utf8");
    return (
      expectedBytes.byteLength === suppliedBytes.byteLength &&
      timingSafeEqual(expectedBytes, suppliedBytes)
    );
  }

  function sendSse(response: ServerResponse, event: CoreEvent): boolean {
    if (response.destroyed || response.writableEnded) return false;
    response.write(`data: ${JSON.stringify(event)}\n\n`);
    return !response.destroyed;
  }

  function delayForTurn(turn: ActiveTurn): Promise<boolean> {
    if (turn.cancelled || stopping) return Promise.resolve(false);
    if (eventDelayMs === 0) return Promise.resolve(true);

    return new Promise((resolve) => {
      let settled = false;
      const finish = (canContinue: boolean): void => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        turn.cancellers.delete(cancel);
        timerCancellers.delete(cancel);
        resolve(canContinue);
      };
      const cancel = (): void => finish(false);
      const timer = setTimeout(() => finish(!turn.cancelled && !stopping), eventDelayMs);
      turn.cancellers.add(cancel);
      timerCancellers.add(cancel);
    });
  }

  function createConfirmationWait(
    turn: ActiveTurn,
    confirmId: string,
  ): Promise<ConfirmationDecision> {
    return new Promise((resolve) => {
      let settled = false;
      const settle = (decision: ConfirmationDecision): void => {
        if (settled) return;
        settled = true;
        pendingConfirmations.delete(confirmId);
        turn.cancellers.delete(cancel);
        resolve(decision);
      };
      const cancel = (): void => settle("cancelled");
      turn.cancellers.add(cancel);
      pendingConfirmations.set(confirmId, {
        sessionId: turn.session.session_id,
        settle,
      });
    });
  }

  function cancelTurn(turn: ActiveTurn, emitInterruptEvent: boolean): void {
    if (turn.completed || turn.cancelled) return;
    turn.cancelled = true;
    for (const cancel of [...turn.cancellers]) cancel();
    turn.cancellers.clear();

    if (!turn.response.destroyed && !turn.response.writableEnded) {
      if (emitInterruptEvent) {
        sendSse(turn.response, {
          type: "error",
          message: "Turno interrumpido por el usuario.",
        });
      }
      turn.response.end();
    }
  }

  function selectTargetTier(message: MessageRequest): Tier {
    if (message.tier_hint) return message.tier_hint;
    return message.wants_cheap ? "FREE_QUOTA" : "PAID_CHEAP";
  }

  function costForTier(tier: Tier): number {
    switch (tier) {
      case "LOCAL":
      case "FREE_QUOTA":
        return 0;
      case "PAID_CHEAP":
        return 0.0042;
      case "VIBE":
        return 0.08;
    }
  }

  async function emitWithDelay(turn: ActiveTurn, event: CoreEvent): Promise<boolean> {
    if (turn.cancelled || stopping || !sendSse(turn.response, event)) return false;
    return delayForTurn(turn);
  }

  async function runScriptedTurn(turn: ActiveTurn, message: MessageRequest): Promise<void> {
    try {
      const targetTier = selectTargetTier(message);
      const fromTier = activeTier;
      const researchCost = costForTier(targetTier);
      activeTier = targetTier;
      accumulatedCostUsd = Number((accumulatedCostUsd + researchCost).toFixed(6));

      if (!(await emitWithDelay(turn, { type: "token", text: "Voy a revisar la solicitud " }))) {
        return;
      }
      if (fromTier !== targetTier) {
        if (
          !(await emitWithDelay(turn, {
            type: "brain_switch",
            from: fromTier,
            to: targetTier,
            reason:
              targetTier === "VIBE"
                ? "el turno pidió explícitamente el escalón premium"
                : targetTier === "FREE_QUOTA"
                  ? "el modo barato priorizó una cuota gratuita"
                  : fromTier === "LOCAL"
                    ? "el modelo local no alcanzó para esta tarea simulada"
                    : "el turno pidió cambiar al escalón económico pago",
            identity: IDENTITIES[targetTier],
          }))
        ) {
          return;
        }
      }
      if (
        !(await emitWithDelay(turn, {
          type: "research_progress",
          iteration: 1,
          of: 2,
          queries: ["contrato Core API", "seguridad HITL"],
          sources_read: ["documentación local del mock"],
          cost_usd: Number((researchCost / 2).toFixed(6)),
        }))
      ) {
        return;
      }
      if (!(await emitWithDelay(turn, { type: "token", text: "y contrastar la evidencia. " }))) {
        return;
      }
      if (
        !(await emitWithDelay(turn, {
          type: "research_progress",
          iteration: 2,
          of: 2,
          queries: ["confirmación humana antes de herramientas"],
          sources_read: ["contrato Core API", "prueba de integración del cliente"],
          cost_usd: researchCost,
        }))
      ) {
        return;
      }

      const confirmId = `confirm_${randomUUID()}`;
      const toolArgs = {
        path: "mock-output.txt",
        operation: "write",
        preview: "resultado simulado del Core",
      };
      const decisionPromise = createConfirmationWait(turn, confirmId);

      // The confirmation is registered before the frame is written, so even a
      // very fast client can decide without racing the mock. No tool event can
      // be emitted until this promise resolves as approved.
      if (
        !sendSse(turn.response, {
          type: "confirm_request",
          tool: "filesystem.write_file",
          args: toolArgs,
          confirm_id: confirmId,
        })
      ) {
        for (const cancel of [...turn.cancellers]) cancel();
        return;
      }

      const decision = await decisionPromise;
      if (decision === "cancelled" || turn.cancelled || stopping) return;
      if (decision === "rejected") {
        const finalText = "Acción rechazada por el usuario. No ejecuté la herramienta.";
        turn.session.turns.push({ role: "assistant", text: finalText });
        sendSse(turn.response, { type: "final", text: finalText });
        turn.completed = true;
        turn.response.end();
        return;
      }

      auditLog.push({
        kind: "tool_execution",
        tool: "filesystem.write_file",
        sessionId: turn.session.session_id,
      });
      if (
        !(await emitWithDelay(turn, {
          type: "tool_start",
          tool: "filesystem.write_file",
          args: toolArgs,
        }))
      ) {
        return;
      }
      if (
        !(await emitWithDelay(turn, {
          type: "tool_end",
          tool: "filesystem.write_file",
          result_summary: {
            ok: true,
            summary: "La escritura simulada terminó correctamente.",
          },
        }))
      ) {
        return;
      }

      const finalText =
        "La simulación completó la investigación y ejecutó la herramienta después de tu aprobación.";
      turn.session.turns.push({ role: "assistant", text: finalText });
      sendSse(turn.response, { type: "final", text: finalText });
      turn.completed = true;
      turn.response.end();
    } catch (error) {
      if (!turn.cancelled && !turn.response.destroyed && !turn.response.writableEnded) {
        const message = error instanceof Error ? error.message : "Error interno del Mock Core.";
        sendSse(turn.response, { type: "error", message });
        turn.response.end();
      }
    } finally {
      for (const cancel of [...turn.cancellers]) cancel();
      turn.cancellers.clear();
      activeTurns.delete(turn.session.session_id);
    }
  }

  async function readBody(request: IncomingMessage, maxBytes: number): Promise<Buffer> {
    const chunks: Buffer[] = [];
    let total = 0;
    let tooLarge = false;

    for await (const chunk of request) {
      const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      total += bytes.byteLength;
      if (total > maxBytes) {
        tooLarge = true;
      } else if (!tooLarge) {
        chunks.push(bytes);
      }
    }

    if (tooLarge) throw new HttpError(413, "request_body_too_large");
    return Buffer.concat(chunks, total);
  }

  async function readJsonObject(request: IncomingMessage): Promise<Record<string, unknown>> {
    const contentType = request.headers["content-type"] ?? "";
    if (!contentType.toLowerCase().startsWith("application/json")) {
      throw new HttpError(415, "content_type_must_be_application_json");
    }
    const bytes = await readBody(request, MAX_JSON_BYTES);
    let parsed: unknown;
    try {
      parsed = JSON.parse(bytes.toString("utf8"));
    } catch {
      throw new HttpError(400, "invalid_json");
    }
    if (!isRecord(parsed)) throw new HttpError(400, "json_body_must_be_an_object");
    return parsed;
  }

  function parseMessageRequest(value: Record<string, unknown>): MessageRequest {
    if (typeof value.text !== "string") throw new HttpError(400, "text_must_be_a_string");
    if (!Array.isArray(value.attachments) || !value.attachments.every((item) => typeof item === "string")) {
      throw new HttpError(400, "attachments_must_be_a_string_array");
    }
    if (value.tier_hint !== undefined && !isTier(value.tier_hint)) {
      throw new HttpError(400, "tier_hint_is_invalid");
    }
    if (value.wants_cheap !== undefined && typeof value.wants_cheap !== "boolean") {
      throw new HttpError(400, "wants_cheap_must_be_boolean");
    }
    return {
      text: value.text,
      attachments: [...value.attachments],
      ...(value.tier_hint === undefined ? {} : { tier_hint: value.tier_hint }),
      ...(value.wants_cheap === undefined ? {} : { wants_cheap: value.wants_cheap }),
    };
  }

  function parseMultipartFile(body: Buffer, contentType: string): Omit<UploadedFile, "file_id"> {
    const boundaryMatch = /(?:^|;)\s*boundary=(?:"([^"]+)"|([^;\s]+))/i.exec(contentType);
    const boundary = boundaryMatch?.[1] ?? boundaryMatch?.[2];
    if (!boundary) throw new HttpError(400, "multipart_boundary_required");

    const delimiter = Buffer.from(`--${boundary}`, "utf8");
    const nextDelimiter = Buffer.from(`\r\n--${boundary}`, "utf8");
    const headerSeparator = Buffer.from("\r\n\r\n", "utf8");
    let cursor = 0;

    while (true) {
      const delimiterAt = body.indexOf(delimiter, cursor);
      if (delimiterAt < 0) break;
      let headersStart = delimiterAt + delimiter.byteLength;
      if (body.subarray(headersStart, headersStart + 2).toString("ascii") === "--") break;
      if (body.subarray(headersStart, headersStart + 2).toString("ascii") === "\r\n") {
        headersStart += 2;
      }
      const headersEnd = body.indexOf(headerSeparator, headersStart);
      if (headersEnd < 0) break;
      const dataStart = headersEnd + headerSeparator.byteLength;
      const dataEnd = body.indexOf(nextDelimiter, dataStart);
      if (dataEnd < 0) break;

      const rawHeaders = body.subarray(headersStart, headersEnd).toString("utf8");
      const disposition = rawHeaders
        .split("\r\n")
        .find((line) => line.toLowerCase().startsWith("content-disposition:"));
      const fieldName = /\bname="([^"]+)"/i.exec(disposition ?? "")?.[1];
      if (fieldName === "file") {
        const filename = /\bfilename="([^"]*)"/i.exec(disposition ?? "")?.[1] || "upload.bin";
        const partContentType = rawHeaders
          .split("\r\n")
          .find((line) => line.toLowerCase().startsWith("content-type:"))
          ?.slice("content-type:".length)
          .trim();
        return {
          name: filename,
          kind: partContentType || "application/octet-stream",
          size: dataEnd - dataStart,
        };
      }
      cursor = dataEnd + 2;
    }

    throw new HttpError(400, "multipart_file_field_required");
  }

  async function handleMessage(
    request: IncomingMessage,
    response: ServerResponse,
    session: MockSession,
  ): Promise<void> {
    if (activeTurns.has(session.session_id)) {
      throw new HttpError(409, "session_already_streaming");
    }
    const message = parseMessageRequest(await readJsonObject(request));
    session.turns.push({
      role: "user",
      text: message.text,
      attachments: [...message.attachments],
      ...(message.tier_hint === undefined ? {} : { tier_hint: message.tier_hint }),
      ...(message.wants_cheap === undefined ? {} : { wants_cheap: message.wants_cheap }),
    });

    response.statusCode = 200;
    response.setHeader("Content-Type", "text/event-stream; charset=utf-8");
    response.setHeader("Connection", "keep-alive");
    response.setHeader("X-Accel-Buffering", "no");
    response.flushHeaders();

    const turn: ActiveTurn = {
      session,
      response,
      cancelled: false,
      completed: false,
      cancellers: new Set(),
    };
    activeTurns.set(session.session_id, turn);
    response.once("close", () => {
      if (!turn.completed) cancelTurn(turn, false);
    });
    void runScriptedTurn(turn, message);
  }

  async function route(request: IncomingMessage, response: ServerResponse): Promise<void> {
    setCorsHeaders(request, response);
    if (request.method === "OPTIONS") {
      response.statusCode = 204;
      response.setHeader("Content-Length", "0");
      response.end();
      return;
    }
    if (!isAuthorized(request)) {
      response.setHeader("WWW-Authenticate", 'Bearer realm="Mock Core"');
      sendJson(response, 401, { error: "unauthorized" });
      return;
    }
    if (stopping) {
      sendJson(response, 503, { error: "mock_core_stopping" });
      return;
    }

    const requestUrl = new URL(request.url ?? "/", `http://${host}`);
    const pathParts = requestUrl.pathname.split("/").filter(Boolean);

    if (request.method === "GET" && requestUrl.pathname === "/healthz") {
      sendJson(response, 200, { ok: true });
      return;
    }
    if (request.method === "GET" && requestUrl.pathname === "/brains") {
      sendJson(response, 200, {
        escalon_activo: activeTier,
        backends: TIERS.map((tier) => ({ tier, identity: IDENTITIES[tier], alive: true })),
        cost_usd_acumulado: accumulatedCostUsd,
      });
      return;
    }
    if (request.method === "POST" && requestUrl.pathname === "/session") {
      const sessionId = `session_${randomUUID()}`;
      sessions.set(sessionId, { session_id: sessionId, turns: [] });
      sendJson(response, 200, { session_id: sessionId });
      return;
    }
    if (request.method === "POST" && requestUrl.pathname === "/upload") {
      const contentType = request.headers["content-type"] ?? "";
      if (!contentType.toLowerCase().startsWith("multipart/form-data")) {
        throw new HttpError(415, "content_type_must_be_multipart_form_data");
      }
      const body = await readBody(request, maxUploadBytes);
      const parsed = parseMultipartFile(body, contentType);
      const file: UploadedFile = { file_id: `file_${randomUUID()}`, ...parsed };
      uploads.set(file.file_id, file);
      sendJson(response, 200, { file_id: file.file_id, kind: file.kind, size: file.size });
      return;
    }

    if (pathParts[0] === "session" && pathParts[1]) {
      let sessionId: string;
      try {
        sessionId = decodeURIComponent(pathParts[1]);
      } catch {
        throw new HttpError(400, "invalid_session_id");
      }
      const session = sessions.get(sessionId);
      if (!session) throw new HttpError(404, "session_not_found");

      if (request.method === "GET" && pathParts.length === 2) {
        sendJson(response, 200, {
          session_id: session.session_id,
          turns: session.turns.map((turn) => ({ ...turn })),
        });
        return;
      }
      if (request.method === "POST" && pathParts.length === 3 && pathParts[2] === "message") {
        await handleMessage(request, response, session);
        return;
      }
      if (request.method === "POST" && pathParts.length === 3 && pathParts[2] === "confirm") {
        const value = await readJsonObject(request);
        if (typeof value.confirm_id !== "string" || typeof value.approved !== "boolean") {
          throw new HttpError(400, "confirm_id_and_approved_are_required");
        }
        const pending = pendingConfirmations.get(value.confirm_id);
        if (!pending || pending.sessionId !== sessionId) {
          throw new HttpError(404, "confirmation_not_pending");
        }
        auditLog.push({
          kind: "confirmation",
          confirmId: value.confirm_id,
          approved: value.approved,
        });
        pending.settle(value.approved ? "approved" : "rejected");
        sendJson(response, 200, { ok: true });
        return;
      }
      if (request.method === "POST" && pathParts.length === 3 && pathParts[2] === "interrupt") {
        const activeTurn = activeTurns.get(sessionId);
        auditLog.push({
          kind: "interrupt",
          sessionId,
          hadActiveTurn: Boolean(activeTurn),
        });
        if (activeTurn) cancelTurn(activeTurn, true);
        sendJson(response, 200, { ok: true });
        return;
      }
    }

    sendJson(response, 404, { error: "route_not_found" });
  }

  const server = createServer((request, response) => {
    void route(request, response).catch((error: unknown) => {
      if (response.headersSent || response.writableEnded || response.destroyed) return;
      if (error instanceof HttpError) {
        sendJson(response, error.status, { error: error.message });
        return;
      }
      const message = error instanceof Error ? error.message : "internal_mock_error";
      sendJson(response, 500, { error: message });
    });
  });

  server.on("connection", (socket) => {
    sockets.add(socket);
    socket.once("close", () => sockets.delete(socket));
  });

  await new Promise<void>((resolve, reject) => {
    const onError = (error: Error): void => {
      server.off("listening", onListening);
      reject(error);
    };
    const onListening = (): void => {
      server.off("error", onError);
      resolve();
    };
    server.once("error", onError);
    server.once("listening", onListening);
    server.listen(port, host);
  });

  const address = server.address();
  if (!address || typeof address === "string") {
    server.close();
    throw new Error("Mock Core did not expose a TCP address.");
  }
  const actualPort = (address as AddressInfo).port;
  const baseUrl = `http://${host}:${actualPort}`;

  const close = (): Promise<void> => {
    closePromise ??= (async () => {
      stopping = true;
      for (const turn of [...activeTurns.values()]) cancelTurn(turn, false);
      for (const pending of [...pendingConfirmations.values()]) pending.settle("cancelled");
      pendingConfirmations.clear();
      for (const cancel of [...timerCancellers]) cancel();
      timerCancellers.clear();

      const closed = new Promise<void>((resolve, reject) => {
        server.close((error?: Error) => {
          if (error) reject(error);
          else resolve();
        });
      });
      server.closeIdleConnections?.();
      for (const socket of [...sockets]) socket.destroy();
      await closed;
      sockets.clear();
      activeTurns.clear();
      sessions.clear();
      uploads.clear();
    })();
    return closePromise;
  };

  return {
    server,
    host,
    port: actualPort,
    baseUrl,
    url: baseUrl,
    token,
    auditLog,
    close,
    stop: close,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isTier(value: unknown): value is Tier {
  return typeof value === "string" && (TIERS as readonly string[]).includes(value);
}

async function runCli(): Promise<void> {
  const configuredPort = Number(process.env.PORT ?? CLI_PORT);
  const mock = await startMockCore({ port: configuredPort });
  console.log(`Mock Core listening on ${mock.baseUrl}`);
  if (!process.env.ROBOT_API_TOKEN?.trim()) {
    console.log(`Mock Bearer token: ${DEFAULT_MOCK_API_TOKEN}`);
  }

  let closing = false;
  const shutdown = async (): Promise<void> => {
    if (closing) return;
    closing = true;
    await mock.close();
  };
  process.once("SIGINT", () => void shutdown());
  process.once("SIGTERM", () => void shutdown());
}

const invokedModuleUrl = process.argv[1] ? pathToFileURL(process.argv[1]).href : "";
if (import.meta.url === invokedModuleUrl) {
  void runCli().catch((error: unknown) => {
    console.error(error);
    process.exitCode = 1;
  });
}
