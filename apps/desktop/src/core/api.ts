import { SseParser } from "./sse";
import {
  CoreProtocolError,
  parseBrainsResponse,
  parseHealthResponse,
  parseSessionResponse,
  parseUploadResponse,
  type BrainsResponse,
  type CoreEvent,
  type HealthResponse,
  type MessageRequest,
  type SessionResponse,
  type UploadResponse,
} from "./types";

const DEFAULT_REQUEST_TIMEOUT_MS = 15_000;

export interface CoreApiConfig {
  baseUrl: string;
  token: string;
  fetchImpl?: typeof fetch;
}

export class CoreApiError extends Error {
  readonly status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "CoreApiError";
    this.status = status;
  }
}

export class StreamDisconnectedError extends CoreApiError {
  readonly eventsReceived: number;

  constructor(eventsReceived: number) {
    super(
      eventsReceived > 0
        ? "La transmisión SSE se cortó antes de recibir final o error."
        : "El Core cerró la transmisión SSE sin enviar eventos.",
    );
    this.name = "StreamDisconnectedError";
    this.eventsReceived = eventsReceived;
  }
}

export function normalizeCoreUrl(input: string): string {
  let url: URL;
  try {
    url = new URL(input.trim());
  } catch {
    throw new CoreApiError("La URL del Core no es válida.");
  }

  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new CoreApiError("La URL del Core debe usar HTTP o HTTPS.");
  }
  const hostname = url.hostname.toLowerCase();
  if (!["127.0.0.1", "localhost", "[::1]", "::1"].includes(hostname)) {
    throw new CoreApiError("Por seguridad, el Core debe ser una dirección local (localhost o loopback).");
  }
  if (url.username || url.password || url.search || url.hash) {
    throw new CoreApiError("La URL del Core no puede incluir credenciales, query ni fragmento.");
  }
  url.pathname = url.pathname.replace(/\/+$/, "");
  return url.toString().replace(/\/$/, "");
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch (error) {
    if (error instanceof CoreApiError || isAbortException(error)) throw error;
    throw new CoreApiError("El Core respondió con JSON inválido.", response.status);
  }
}

export class CoreApi {
  readonly baseUrl: string;
  private readonly token: string;
  private readonly fetchImpl: typeof fetch;

  constructor(config: CoreApiConfig) {
    this.baseUrl = normalizeCoreUrl(config.baseUrl);
    this.token = config.token.trim();
    this.fetchImpl = config.fetchImpl ?? fetch;
    if (!this.token) {
      throw new CoreApiError("Ingresá el token del Core antes de conectar.");
    }
  }

  async createSession(signal?: AbortSignal): Promise<SessionResponse> {
    const value = await this.requestJson("/session", { method: "POST", signal });
    return parseSessionResponse({ ...asRecord(value), turns: asRecord(value).turns ?? [] });
  }

  async getSession(sessionId: string, signal?: AbortSignal): Promise<SessionResponse> {
    const session = parseSessionResponse(
      await this.requestJson(`/session/${encodeURIComponent(sessionId)}`, { signal }),
    );
    if (session.session_id !== sessionId) {
      throw new CoreProtocolError("El Core devolvió una sesión distinta de la solicitada.");
    }
    return session;
  }

  async confirm(
    sessionId: string,
    confirmId: string,
    approved: boolean,
    signal?: AbortSignal,
  ): Promise<void> {
    const value = await this.requestJson(`/session/${encodeURIComponent(sessionId)}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm_id: confirmId, approved }),
      signal,
    });
    if (!isRecord(value) || value.ok !== true) {
      throw new CoreApiError("El Core no confirmó la decisión humana.");
    }
  }

  async interrupt(sessionId: string, signal?: AbortSignal): Promise<void> {
    const value = await this.requestJson(`/session/${encodeURIComponent(sessionId)}/interrupt`, {
      method: "POST",
      signal,
    });
    if (!isRecord(value) || value.ok !== true) {
      throw new CoreApiError("El Core no confirmó la interrupción.");
    }
  }

  async upload(file: File, signal?: AbortSignal): Promise<UploadResponse> {
    const body = new FormData();
    body.append("file", file, file.name);
    const deadline = createDeadlineSignal(signal);
    try {
      const response = await this.request("/upload", { method: "POST", body, signal: deadline.signal });
      return parseUploadResponse(await readJson(response));
    } finally {
      deadline.cleanup();
    }
  }

  async getBrains(signal?: AbortSignal): Promise<BrainsResponse> {
    return parseBrainsResponse(await this.requestJson("/brains", { signal }));
  }

  async health(signal?: AbortSignal): Promise<HealthResponse> {
    return parseHealthResponse(await this.requestJson("/healthz", { signal }));
  }

  async streamMessage(
    sessionId: string,
    message: MessageRequest,
    onEvent: (event: CoreEvent) => void | Promise<void>,
    signal?: AbortSignal,
  ): Promise<void> {
    const connectionDeadline = createDeadlineSignal(signal);
    let response: Response;
    try {
      response = await this.request(`/session/${encodeURIComponent(sessionId)}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify(message),
        signal: connectionDeadline.signal,
      });
      connectionDeadline.clearTimeoutOnly();
    } catch (error) {
      connectionDeadline.cleanup();
      throw error;
    }

    const contentType = response.headers.get("content-type") ?? "";
    if (!contentType.toLowerCase().includes("text/event-stream")) {
      try {
        await response.body?.cancel();
      } catch {
        // Best-effort cleanup; the protocol error remains authoritative.
      }
      connectionDeadline.cleanup();
      throw new CoreApiError("El Core no respondió con text/event-stream.", response.status);
    }
    if (!response.body) {
      connectionDeadline.cleanup();
      throw new CoreApiError("La respuesta SSE no tiene un cuerpo legible.", response.status);
    }

    const parser = new SseParser();
    const reader = response.body.getReader();
    let eventsReceived = 0;
    let terminalEventSeen = false;

    let cancelReader = true;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const events = parser.push(value);
        for (const event of events) {
          if (terminalEventSeen) {
            throw new CoreApiError("El Core emitió eventos después de un evento terminal.");
          }
          eventsReceived += 1;
          terminalEventSeen = event.type === "final" || event.type === "error";
          await onEvent(event);
        }
        if (terminalEventSeen) {
          try {
            await reader.cancel();
          } catch {
            // The terminal event is authoritative even if transport cleanup races.
          }
          cancelReader = false;
          break;
        }
      }
      for (const event of parser.finish()) {
        if (terminalEventSeen) {
          throw new CoreApiError("El Core emitió eventos después de un evento terminal.");
        }
        eventsReceived += 1;
        terminalEventSeen = event.type === "final" || event.type === "error";
        await onEvent(event);
      }
      if (!terminalEventSeen && !signal?.aborted) {
        throw new StreamDisconnectedError(eventsReceived);
      }
      cancelReader = false;
    } catch (error) {
      if (
        signal?.aborted ||
        isAbortException(error) ||
        error instanceof CoreApiError ||
        error instanceof CoreProtocolError ||
        error instanceof StreamDisconnectedError
      ) {
        throw error;
      }
      throw new StreamDisconnectedError(eventsReceived);
    } finally {
      if (cancelReader) {
        try {
          await reader.cancel();
        } catch {
          // Best-effort cancellation: the original protocol/network error is more useful.
        }
      }
      reader.releaseLock();
      connectionDeadline.cleanup();
    }
  }

  private async requestJson(path: string, init: RequestInit = {}): Promise<unknown> {
    const deadline = createDeadlineSignal(init.signal ?? undefined);
    try {
      return await readJson(await this.request(path, { ...init, signal: deadline.signal }));
    } finally {
      deadline.cleanup();
    }
  }

  private async request(path: string, init: RequestInit): Promise<Response> {
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${this.token}`);
    headers.set("Cache-Control", "no-store");

    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, { ...init, headers });
    } catch (error) {
      if (error instanceof CoreApiError || isAbortException(error)) {
        throw error;
      }
      throw new CoreApiError("No se pudo conectar con el Core local. Verificá que esté activo.");
    }

    if (!response.ok) {
      const prefix = response.status === 413 ? "El Core rechazó el archivo por tamaño." : "El Core rechazó la solicitud.";
      try {
        await response.body?.cancel();
      } catch {
        // Best-effort cleanup; the HTTP error remains authoritative.
      }
      throw new CoreApiError(`${prefix} HTTP ${response.status}.`, response.status);
    }
    return response;
  }
}

function createDeadlineSignal(parent?: AbortSignal, timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS): {
  signal: AbortSignal;
  clearTimeoutOnly: () => void;
  cleanup: () => void;
} {
  const controller = new AbortController();
  const onParentAbort = () => controller.abort(parent?.reason);
  if (parent?.aborted) {
    controller.abort(parent.reason);
  } else {
    parent?.addEventListener("abort", onParentAbort, { once: true });
  }
  let timeout: ReturnType<typeof globalThis.setTimeout> | null = globalThis.setTimeout(() => {
    controller.abort(new CoreApiError("El Core no respondió dentro de 15 segundos."));
  }, timeoutMs);
  const clearTimeoutOnly = () => {
    if (timeout !== null) {
      globalThis.clearTimeout(timeout);
      timeout = null;
    }
  };
  return {
    signal: controller.signal,
    clearTimeoutOnly,
    cleanup: () => {
      clearTimeoutOnly();
      parent?.removeEventListener("abort", onParentAbort);
    },
  };
}

function isAbortException(error: unknown): boolean {
  return error instanceof DOMException && (error.name === "AbortError" || error.name === "TimeoutError");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asRecord(value: unknown): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new CoreApiError("El Core respondió con una forma inesperada.");
  }
  return value;
}
