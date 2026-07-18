import { CoreApi, CoreApiError } from "./api";
import type { SessionResponse } from "./types";

export interface RecoveryOptions {
  attempts?: number;
  signal?: AbortSignal;
  onAttempt?: (attempt: number, attempts: number) => void;
}

/**
 * Reconciles from the only safe read endpoint in the current contract.
 * It deliberately never replays POST /message because that could duplicate effects.
 */
export async function recoverSessionSnapshot(
  api: CoreApi,
  sessionId: string,
  options: RecoveryOptions = {},
): Promise<SessionResponse> {
  const attempts = Math.max(1, options.attempts ?? 3);
  let lastError: unknown;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    options.onAttempt?.(attempt, attempts);
    try {
      const health = await api.health(options.signal);
      if (!health.ok) {
        throw new CoreApiError("El Core respondió healthz con ok:false.");
      }
      return await api.getSession(sessionId, options.signal);
    } catch (error) {
      if (options.signal?.aborted) throw error;
      lastError = error;
      if (attempt < attempts) {
        await abortableDelay(250 * 2 ** (attempt - 1), options.signal);
      }
    }
  }

  throw lastError instanceof Error
    ? lastError
    : new CoreApiError("No se pudo reconciliar la sesión después del corte.");
}

function abortableDelay(milliseconds: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
      return;
    }

    const timeout = globalThis.setTimeout(() => {
      cleanup();
      resolve();
    }, milliseconds);
    const onAbort = () => {
      globalThis.clearTimeout(timeout);
      cleanup();
      reject(signal?.reason ?? new DOMException("Aborted", "AbortError"));
    };
    const cleanup = () => signal?.removeEventListener("abort", onAbort);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}
