const CORE_URL_KEY = "robot.core_url";
const SESSION_IDS_KEY_PREFIX = "robot.session_ids:";
const DEFAULT_CORE_URL = "http://127.0.0.1:8850";

export function loadCoreUrl(): string {
  try {
    return window.localStorage.getItem(CORE_URL_KEY) ?? DEFAULT_CORE_URL;
  } catch {
    return DEFAULT_CORE_URL;
  }
}

export function saveCoreUrl(url: string): void {
  try {
    window.localStorage.setItem(CORE_URL_KEY, url);
  } catch {
    // The app remains usable when browser storage is disabled.
  }
}

export function loadRecentSessionIds(coreUrl: string): string[] {
  try {
    const raw = window.localStorage.getItem(sessionStorageKey(coreUrl));
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string").slice(0, 20) : [];
  } catch {
    return [];
  }
}

export function saveRecentSessionId(coreUrl: string, sessionId: string): string[] {
  const next = [sessionId, ...loadRecentSessionIds(coreUrl).filter((item) => item !== sessionId)].slice(0, 20);
  try {
    window.localStorage.setItem(sessionStorageKey(coreUrl), JSON.stringify(next));
  } catch {
    // Session IDs are a convenience only; failure must not break the chat.
  }
  return next;
}

export function forgetRecentSessionId(coreUrl: string, sessionId: string): string[] {
  const next = loadRecentSessionIds(coreUrl).filter((item) => item !== sessionId);
  try {
    window.localStorage.setItem(sessionStorageKey(coreUrl), JSON.stringify(next));
  } catch {
    // Session IDs are a convenience only; failure must not break the chat.
  }
  return next;
}

export function clearRecentSessionIds(coreUrl: string): boolean {
  try {
    window.localStorage.removeItem(sessionStorageKey(coreUrl));
    return true;
  } catch {
    return false;
  }
}

function sessionStorageKey(coreUrl: string): string {
  return `${SESSION_IDS_KEY_PREFIX}${coreUrl}`;
}
