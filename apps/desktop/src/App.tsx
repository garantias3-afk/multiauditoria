import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import ActivityPanel from "./components/ActivityPanel";
import BrainStatus from "./components/BrainStatus";
import Composer, { type ComposerAttachmentChip } from "./components/Composer";
import ConfirmationDialog from "./components/ConfirmationDialog";
import MarkdownMessage from "./components/MarkdownMessage";
import SessionSidebar from "./components/SessionSidebar";
import SettingsDialog, { type SettingsValues } from "./components/SettingsDialog";
import { CoreApi, CoreApiError, StreamDisconnectedError, normalizeCoreUrl } from "./core/api";
import { recoverSessionSnapshot } from "./core/recovery";
import type { BrainsResponse, CoreEvent, Tier } from "./core/types";
import {
  chatReducer,
  initialChatState,
  normalizeRecoveredSessionTurns,
  normalizeSessionTurns,
  type ChatAttachment,
  type ChatTurn,
} from "./state/chatReducer";
import { errorMessage, formatBytes } from "./utils/format";
import {
  clearRecentSessionIds,
  forgetRecentSessionId,
  loadCoreUrl,
  loadRecentSessionIds,
  saveCoreUrl,
  saveRecentSessionId,
} from "./utils/storage";

interface LocalAttachment extends ComposerAttachmentChip {
  file: File;
}

interface QueuedCoreEvent {
  event: CoreEvent;
  receivedAt: number;
  eventId: string;
}

interface ConfirmationDecisionInFlight {
  confirmId: string;
  approved: boolean;
  queuedEvents: QueuedCoreEvent[];
}

type HealthState = "unconfigured" | "checking" | "online" | "offline";

function makeId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function App() {
  const [coreUrl, setCoreUrl] = useState(loadCoreUrl);
  const [token, setToken] = useState("");
  const [recentSessionIds, setRecentSessionIds] = useState(() => loadRecentSessionIds(loadCoreUrl()));
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const [composerText, setComposerText] = useState("");
  const [attachments, setAttachments] = useState<LocalAttachment[]>([]);
  const [tierHint, setTierHint] = useState<Tier | undefined>();
  const [wantsCheap, setWantsCheap] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(true);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [testingConnection, setTestingConnection] = useState(false);
  const [testMessage, setTestMessage] = useState<string | null>(null);
  const [testSucceeded, setTestSucceeded] = useState(false);
  const [health, setHealth] = useState<HealthState>("unconfigured");
  const [brains, setBrains] = useState<BrainsResponse | null>(null);
  const [brainsLoading, setBrainsLoading] = useState(false);
  const [brainsError, setBrainsError] = useState<string | null>(null);
  const [sessionBusy, setSessionBusy] = useState(false);
  const [recovering, setRecovering] = useState(false);

  const streamAbortRef = useRef<AbortController | null>(null);
  const pendingConfirmIdRef = useRef<string | null>(null);
  const confirmationDecisionRef = useRef<ConfirmationDecisionInFlight | null>(null);
  const stopRequestedRef = useRef(false);
  const handledStreamAbortRef = useRef(false);
  const eventSequenceRef = useRef(0);
  const objectUrlsRef = useRef(new Set<string>());
  const uploadControllersRef = useRef(new Map<string, AbortController>());
  const settingsTestControllerRef = useRef<AbortController | null>(null);
  const confirmationAbortRef = useRef<AbortController | null>(null);
  const interruptAbortRef = useRef<AbortController | null>(null);
  const interruptTerminalErrorRef = useRef<string | null>(null);
  const sessionRequestInFlightRef = useRef(false);
  const sessionRequestAbortRef = useRef<AbortController | null>(null);
  const operationEpochRef = useRef(0);
  const sendInFlightRef = useRef(false);
  const confirmationInFlightRef = useRef(false);
  const interruptInFlightRef = useRef(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const turnListRef = useRef<HTMLElement>(null);
  const shouldAutoScrollRef = useRef(true);

  const api = useMemo(() => {
    if (!token) return null;
    try {
      return new CoreApi({ baseUrl: coreUrl, token });
    } catch {
      return null;
    }
  }, [coreUrl, token]);

  const turnBusy =
    state.phase === "streaming" ||
    state.phase === "paused" ||
    state.phase === "interrupting" ||
    state.pendingConfirmation !== null ||
    recovering;

  useEffect(() => {
    if (!shouldAutoScrollRef.current) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    messagesEndRef.current?.scrollIntoView({
      block: "end",
      behavior: reducedMotion ? "auto" : "smooth",
    });
  }, [state.turns, state.connectionNotice, state.error]);

  useEffect(() => {
    return () => {
      streamAbortRef.current?.abort();
      settingsTestControllerRef.current?.abort();
      confirmationAbortRef.current?.abort();
      interruptAbortRef.current?.abort();
      sessionRequestAbortRef.current?.abort();
      for (const controller of uploadControllersRef.current.values()) controller.abort();
      uploadControllersRef.current.clear();
      pendingConfirmIdRef.current = null;
      confirmationDecisionRef.current = null;
      for (const url of objectUrlsRef.current) URL.revokeObjectURL(url);
      objectUrlsRef.current.clear();
    };
  }, []);

  useEffect(() => {
    if (!api) {
      setHealth("unconfigured");
      setBrains(null);
      return undefined;
    }

    const controller = new AbortController();
    let active = true;
    let polling = false;
    setHealth("checking");

    const refresh = async () => {
      if (polling) return;
      polling = true;
      setBrainsLoading(true);
      try {
        const next = await api.getBrains(controller.signal);
        if (!active) return;
        setBrains(next);
        setBrainsError(null);
        setHealth("online");
        const candidates = next.backends.filter(
          (backend) => backend.alive && backend.tier === next.escalon_activo,
        );
        dispatch({
          type: "BRAIN_STATUS",
          tier: next.escalon_activo,
          identity: candidates.length === 1 ? candidates[0].identity : null,
        });
      } catch (error) {
        if (!active || isAbortError(error)) return;
        setBrainsError(errorMessage(error));
        setHealth("offline");
      } finally {
        if (active) setBrainsLoading(false);
        polling = false;
      }
    };

    void refresh();
    const interval = window.setInterval(() => void refresh(), 10_000);
    return () => {
      active = false;
      controller.abort();
      window.clearInterval(interval);
    };
  }, [api]);

  const rememberSession = (sessionId: string) => {
    setRecentSessionIds(saveRecentSessionId(coreUrl, sessionId));
  };

  const requireApi = (): CoreApi | null => {
    if (!api) {
      setSettingsError("Configurá una URL local válida y el token del Core.");
      setSettingsOpen(true);
      return null;
    }
    return api;
  };

  const createSession = async (): Promise<string | null> => {
    if (sessionRequestInFlightRef.current) return null;
    const currentApi = requireApi();
    if (!currentApi) return null;
    sessionRequestInFlightRef.current = true;
    const controller = new AbortController();
    const epoch = operationEpochRef.current;
    sessionRequestAbortRef.current = controller;
    setSessionBusy(true);
    try {
      const session = await currentApi.createSession(controller.signal);
      if (epoch !== operationEpochRef.current) return null;
      dispatch({ type: "SESSION_READY", sessionId: session.session_id });
      rememberSession(session.session_id);
      return session.session_id;
    } catch (error) {
      if (isAbortError(error) || epoch !== operationEpochRef.current) return null;
      dispatch({ type: "STREAM_FAILURE", message: errorMessage(error), recoverable: false });
      setHealth("offline");
      return null;
    } finally {
      if (sessionRequestAbortRef.current === controller) sessionRequestAbortRef.current = null;
      sessionRequestInFlightRef.current = false;
      setSessionBusy(false);
    }
  };

  const loadSession = async (sessionId: string) => {
    if (turnBusy || sessionRequestInFlightRef.current) return;
    const currentApi = requireApi();
    if (!currentApi) return;
    sessionRequestInFlightRef.current = true;
    const controller = new AbortController();
    const epoch = operationEpochRef.current;
    sessionRequestAbortRef.current = controller;
    setSessionBusy(true);
    try {
      const session = await currentApi.getSession(sessionId, controller.signal);
      if (epoch !== operationEpochRef.current) return;
      discardLocalPreviewsAndDrafts();
      dispatch({
        type: "SESSION_READY",
        sessionId: session.session_id,
        turns: normalizeSessionTurns(session.turns),
      });
      rememberSession(session.session_id);
      setHealth("online");
    } catch (error) {
      if (isAbortError(error) || epoch !== operationEpochRef.current) return;
      dispatch({ type: "STREAM_FAILURE", message: errorMessage(error), recoverable: false });
    } finally {
      if (sessionRequestAbortRef.current === controller) sessionRequestAbortRef.current = null;
      sessionRequestInFlightRef.current = false;
      setSessionBusy(false);
    }
  };

  const handleNewSession = () => {
    if (turnBusy || sessionBusy) return;
    void (async () => {
      const sessionId = await createSession();
      if (sessionId) discardLocalPreviewsAndDrafts();
    })();
  };

  const discardLocalPreviewsAndDrafts = () => {
    for (const controller of uploadControllersRef.current.values()) controller.abort();
    uploadControllersRef.current.clear();
    for (const url of objectUrlsRef.current) URL.revokeObjectURL(url);
    objectUrlsRef.current.clear();
    setAttachments([]);
    setComposerText("");
    setTierHint(undefined);
    setWantsCheap(false);
  };

  const revokeSentPreviews = () => {
    for (const url of objectUrlsRef.current) URL.revokeObjectURL(url);
    objectUrlsRef.current.clear();
  };

  const uploadAttachment = async (attachmentId: string, file: File) => {
    const currentApi = requireApi();
    if (!currentApi) {
      setAttachments((current) =>
        current.map((item) =>
          item.id === attachmentId
            ? { ...item, status: "error", error: "Configurá el Core antes de subir archivos." }
            : item,
        ),
      );
      return;
    }

    uploadControllersRef.current.get(attachmentId)?.abort();
    const controller = new AbortController();
    uploadControllersRef.current.set(attachmentId, controller);
    setAttachments((current) =>
      current.map((item) =>
        item.id === attachmentId ? { ...item, status: "uploading", error: undefined } : item,
      ),
    );
    try {
      const uploaded = await currentApi.upload(file, controller.signal);
      setAttachments((current) =>
        current.map((item) =>
          item.id === attachmentId
            ? {
                ...item,
                status: "uploaded",
                fileId: uploaded.file_id,
                kind: uploaded.kind,
                size: uploaded.size,
                error: undefined,
              }
            : item,
        ),
      );
    } catch (error) {
      if (isAbortError(error)) return;
      setAttachments((current) =>
        current.map((item) =>
          item.id === attachmentId
            ? { ...item, status: "error", error: errorMessage(error) }
            : item,
        ),
      );
    } finally {
      if (uploadControllersRef.current.get(attachmentId) === controller) {
        uploadControllersRef.current.delete(attachmentId);
      }
    }
  };

  const handleFilesSelected = (files: File[]) => {
    const staged = files.map((file): LocalAttachment => {
      const previewUrl = file.type.startsWith("image/") ? URL.createObjectURL(file) : undefined;
      if (previewUrl) objectUrlsRef.current.add(previewUrl);
      return {
        id: makeId("attachment"),
        name: file.name,
        size: file.size,
        kind: file.type || "application/octet-stream",
        status: "queued",
        previewUrl,
        file,
      };
    });
    setAttachments((current) => [...current, ...staged]);
    for (const item of staged) void uploadAttachment(item.id, item.file);
  };

  const handleRemoveAttachment = (attachmentId: string) => {
    uploadControllersRef.current.get(attachmentId)?.abort();
    uploadControllersRef.current.delete(attachmentId);
    setAttachments((current) => {
      const removed = current.find((item) => item.id === attachmentId);
      if (removed?.previewUrl) {
        URL.revokeObjectURL(removed.previewUrl);
        objectUrlsRef.current.delete(removed.previewUrl);
      }
      return current.filter((item) => item.id !== attachmentId);
    });
  };

  const handleRetryAttachment = (attachmentId: string) => {
    const item = attachments.find((candidate) => candidate.id === attachmentId);
    if (item && item.status === "error") void uploadAttachment(item.id, item.file);
  };

  const nextEventId = () => {
    eventSequenceRef.current += 1;
    return `event-${eventSequenceRef.current}`;
  };

  const handleStreamEvent = (event: CoreEvent): void => {
    if (stopRequestedRef.current) return;
    if (interruptInFlightRef.current && event.type === "error") {
      interruptTerminalErrorRef.current = event.message;
    }
    const envelope: QueuedCoreEvent = {
      event,
      receivedAt: performance.now(),
      eventId: nextEventId(),
    };
    const pendingConfirmId = pendingConfirmIdRef.current;

    if (pendingConfirmId !== null) {
      if (event.type === "error") {
        pendingConfirmIdRef.current = null;
        confirmationDecisionRef.current = null;
        dispatch({ type: "CORE_EVENT", ...envelope });
        return;
      }

      const decision = confirmationDecisionRef.current;
      if (!decision || decision.confirmId !== pendingConfirmId) {
        throw new CoreApiError(
          `Violación de protocolo: el Core emitió ${event.type} antes de la decisión humana.`,
        );
      }
      if (!decision.approved && (event.type === "tool_start" || event.type === "tool_end")) {
        throw new CoreApiError("Violación de protocolo: el Core ejecutó una herramienta rechazada.");
      }
      if (event.type === "confirm_request") {
        throw new CoreApiError("Violación de protocolo: llegó una segunda confirmación antes de cerrar la primera.");
      }
      if (decision.queuedEvents.length >= 100) {
        throw new CoreApiError("El Core emitió demasiados eventos mientras confirmaba la decisión.");
      }
      decision.queuedEvents.push(envelope);
      return;
    }

    if (event.type === "confirm_request") {
      pendingConfirmIdRef.current = event.confirm_id;
    }
    dispatch({ type: "CORE_EVENT", ...envelope });
  };

  const handleSend = async () => {
    if (turnBusy || sessionBusy || sendInFlightRef.current) return;
    const currentApi = requireApi();
    if (!currentApi) return;
    const readyAttachments = attachments.filter(
      (attachment): attachment is LocalAttachment & { fileId: string } =>
        attachment.status === "uploaded" && typeof attachment.fileId === "string",
    );
    if (readyAttachments.length !== attachments.length) return;
    const trimmedText = composerText.trim();
    if (!trimmedText && readyAttachments.length === 0) return;

    sendInFlightRef.current = true;
    try {
      let sessionId = state.sessionId;
      if (!sessionId) {
        sessionId = await createSession();
        if (!sessionId) return;
      }

      const sentAttachments: ChatAttachment[] = readyAttachments.map((attachment) => ({
        fileId: attachment.fileId,
        name: attachment.name,
        kind: attachment.kind ?? "application/octet-stream",
        size: attachment.size,
        previewUrl: attachment.previewUrl,
      }));
      const userTurn: ChatTurn = {
        id: makeId("user"),
        role: "user",
        content: trimmedText,
        status: "complete",
        attachments: sentAttachments,
        brainNotices: [],
      };
      const assistantTurn: ChatTurn = {
        id: makeId("assistant"),
        role: "assistant",
        content: "",
        status: "streaming",
        attachments: [],
        brainNotices: [],
      };

      dispatch({ type: "USER_MESSAGE", turn: userTurn });
      dispatch({ type: "STREAM_STARTED", assistantTurn });
      setComposerText("");
      setAttachments([]);
      stopRequestedRef.current = false;
      handledStreamAbortRef.current = false;
      const controller = new AbortController();
      streamAbortRef.current = controller;
      const streamEpoch = operationEpochRef.current;
      const expectedSnapshotTurns = state.turns.length + 2;

      try {
        await currentApi.streamMessage(
          sessionId,
          {
            text: trimmedText,
            attachments: readyAttachments.map((attachment) => attachment.fileId),
            ...(tierHint ? { tier_hint: tierHint } : {}),
            wants_cheap: wantsCheap,
          },
          handleStreamEvent,
          controller.signal,
        );
        setHealth("online");
      } catch (error) {
        if (stopRequestedRef.current || handledStreamAbortRef.current || isAbortError(error)) return;
        const disconnected = error instanceof StreamDisconnectedError;
        pendingConfirmIdRef.current = null;
        confirmationDecisionRef.current = null;
        dispatch({
          type: "STREAM_FAILURE",
          message: errorMessage(error),
          recoverable: disconnected,
          clearConfirmation: true,
        });
        if (!disconnected) return;

        setRecovering(true);
        try {
          const snapshot = await recoverSessionSnapshot(currentApi, sessionId, {
            attempts: 3,
            signal: controller.signal,
            onAttempt: (attempt, attemptsCount) =>
              dispatch({
                type: "CONNECTION_NOTICE",
                message: `Reconectando con el Core para reconciliar la sesión (${attempt}/${attemptsCount})…`,
              }),
          });
          if (streamEpoch !== operationEpochRef.current) return;
          const normalized = normalizeRecoveredSessionTurns(snapshot.turns);
          if (normalized.length >= expectedSnapshotTurns) {
            pendingConfirmIdRef.current = null;
            confirmationDecisionRef.current = null;
            revokeSentPreviews();
            dispatch({ type: "SESSION_READY", sessionId: snapshot.session_id, turns: normalized });
            dispatch({
              type: "CONNECTION_NOTICE",
              message:
                "Conexión recuperada desde el snapshot. El contrato no permite verificar si el último turno era terminal; el SSE no fue reenviado.",
            });
          } else {
            dispatch({
              type: "CONNECTION_NOTICE",
              message:
                "El Core volvió, pero el snapshot todavía no contiene el turno completo. No se reenvió el mensaje para evitar duplicar efectos.",
            });
          }
          setHealth("online");
        } catch (recoveryError) {
          if (isAbortError(recoveryError)) return;
          dispatch({
            type: "CONNECTION_NOTICE",
            message: `No se pudo reconciliar la sesión: ${errorMessage(recoveryError)}`,
          });
          setHealth("offline");
        } finally {
          if (streamEpoch === operationEpochRef.current) setRecovering(false);
        }
      } finally {
        if (streamAbortRef.current === controller) streamAbortRef.current = null;
      }
    } finally {
      sendInFlightRef.current = false;
    }
  };

  const handleDecision = async (approved: boolean) => {
    const pending = state.pendingConfirmation;
    if (!pending || state.confirmationSubmitting || confirmationInFlightRef.current || !state.sessionId) return;
    const currentApi = requireApi();
    if (!currentApi) return;

    confirmationInFlightRef.current = true;
    const controller = new AbortController();
    confirmationAbortRef.current = controller;
    const decision: ConfirmationDecisionInFlight = {
      confirmId: pending.event.confirm_id,
      approved,
      queuedEvents: [],
    };
    confirmationDecisionRef.current = decision;
    dispatch({ type: "CONFIRM_SUBMIT_STARTED" });
    try {
      await currentApi.confirm(state.sessionId, pending.event.confirm_id, approved, controller.signal);
      if (pendingConfirmIdRef.current !== pending.event.confirm_id) return;
      dispatch({ type: "CONFIRM_RESOLVED", confirmId: pending.event.confirm_id });
      pendingConfirmIdRef.current = null;
      confirmationDecisionRef.current = null;
      for (const queued of decision.queuedEvents) {
        dispatch({ type: "CORE_EVENT", ...queued });
      }
    } catch (error) {
      if (interruptInFlightRef.current || stopRequestedRef.current) return;
      confirmationDecisionRef.current = null;
      pendingConfirmIdRef.current = null;
      handledStreamAbortRef.current = true;
      streamAbortRef.current?.abort();
      dispatch({
        type: "STREAM_FAILURE",
        message:
          decision.queuedEvents.length > 0
            ? "La confirmación no pudo verificarse, pero el Core ya emitió eventos. Se canceló el stream por seguridad."
            : `No se pudo verificar si el Core recibió la decisión (${errorMessage(error)}). Se canceló el stream para no repetir un efecto incierto.`,
        recoverable: false,
        clearConfirmation: true,
      });
    } finally {
      if (confirmationAbortRef.current === controller) confirmationAbortRef.current = null;
      confirmationInFlightRef.current = false;
    }
  };

  const handleInterrupt = async () => {
    if (!state.sessionId || state.phase === "interrupting" || interruptInFlightRef.current) return;
    const currentApi = requireApi();
    if (!currentApi) return;
    interruptInFlightRef.current = true;
    interruptTerminalErrorRef.current = null;
    const controller = new AbortController();
    interruptAbortRef.current = controller;
    confirmationAbortRef.current?.abort();
    dispatch({ type: "INTERRUPT_STARTED" });
    try {
      await currentApi.interrupt(state.sessionId, controller.signal);
      const retainedDecision = confirmationDecisionRef.current;
      const retainedEvents = retainedDecision?.queuedEvents ?? [];
      const retainedTerminal = retainedEvents.some(
        ({ event }) => event.type === "final" || event.type === "error",
      );
      stopRequestedRef.current = true;
      streamAbortRef.current?.abort();
      if (retainedDecision && pendingConfirmIdRef.current === retainedDecision.confirmId) {
        dispatch({ type: "CONFIRM_RESOLVED", confirmId: retainedDecision.confirmId });
      }
      pendingConfirmIdRef.current = null;
      confirmationDecisionRef.current = null;
      for (const retained of retainedEvents) {
        dispatch({ type: "CORE_EVENT", ...retained });
      }
      if (!retainedTerminal) {
        dispatch({
          type: "STREAM_INTERRUPTED",
          ...(interruptTerminalErrorRef.current
            ? { terminalError: interruptTerminalErrorRef.current }
            : {}),
        });
      }
    } catch (error) {
      stopRequestedRef.current = false;
      const uncertainDecision = confirmationDecisionRef.current;
      confirmationDecisionRef.current = null;
      if (uncertainDecision) {
        pendingConfirmIdRef.current = null;
        handledStreamAbortRef.current = true;
        streamAbortRef.current?.abort();
        dispatch({
          type: "STREAM_FAILURE",
          message:
            uncertainDecision.queuedEvents.length > 0
              ? "No se pudo verificar la interrupción durante una decisión y había eventos retenidos. Se canceló el stream por seguridad."
              : "No se pudo verificar la interrupción ni si el Core recibió la decisión en curso. Se canceló el stream para no repetir un efecto incierto.",
          recoverable: false,
          clearConfirmation: true,
        });
      } else if (!isAbortError(error)) {
        dispatch({
          type: "INTERRUPT_FAILED",
          message: interruptTerminalErrorRef.current
            ? `No se pudo confirmar la interrupción. El Core informó además: ${interruptTerminalErrorRef.current}`
            : errorMessage(error),
        });
      }
    } finally {
      if (interruptAbortRef.current === controller) interruptAbortRef.current = null;
      interruptTerminalErrorRef.current = null;
      interruptInFlightRef.current = false;
    }
  };

  const handleSaveSettings = (values: SettingsValues) => {
    if (turnBusy || sessionBusy) {
      setSettingsError("Detené o completá el turno activo antes de cambiar la conexión.");
      return;
    }
    try {
      const normalized = normalizeCoreUrl(values.coreUrl);
      const normalizedToken = values.token.trim();
      if (!normalizedToken) throw new CoreApiError("Ingresá el token del Core.");
      const urlChanged = normalized !== coreUrl;
      const tokenChanged = normalizedToken !== token;
      const credentialChangedDuringRun = token.length > 0 && tokenChanged;
      const credentialsChanged = urlChanged || tokenChanged;
      if (credentialChangedDuringRun && !clearRecentSessionIds(normalized)) {
        throw new CoreApiError(
          "No se pudieron quitar los IDs recientes del almacenamiento local; la conexión no se cambió.",
        );
      }
      operationEpochRef.current += 1;
      sessionRequestAbortRef.current?.abort();
      setCoreUrl(normalized);
      setToken(normalizedToken);
      saveCoreUrl(normalized);
      setRecentSessionIds(credentialChangedDuringRun ? [] : loadRecentSessionIds(normalized));
      setSettingsError(null);
      setSettingsOpen(false);
      setTestMessage(null);
      if (credentialsChanged) {
        pendingConfirmIdRef.current = null;
        confirmationDecisionRef.current = null;
        setRecovering(false);
        setBrains(null);
        setBrainsError(null);
        setHealth("checking");
        discardLocalPreviewsAndDrafts();
        dispatch({ type: "RESET_SESSION" });
      }
    } catch (error) {
      setSettingsError(errorMessage(error));
    }
  };

  const handleTestConnection = async (values: SettingsValues) => {
    settingsTestControllerRef.current?.abort();
    const controller = new AbortController();
    settingsTestControllerRef.current = controller;
    setTestingConnection(true);
    setTestMessage(null);
    setSettingsError(null);
    try {
      const candidate = new CoreApi({ baseUrl: values.coreUrl, token: values.token });
      const result = await candidate.health(controller.signal);
      if (!result.ok) throw new CoreApiError("El Core respondió con ok:false.");
      setTestSucceeded(true);
      setTestMessage("Conexión correcta: healthz respondió ok:true.");
    } catch (error) {
      if (isAbortError(error)) return;
      setTestSucceeded(false);
      setTestMessage(errorMessage(error));
    } finally {
      if (settingsTestControllerRef.current === controller) {
        settingsTestControllerRef.current = null;
        setTestingConnection(false);
      }
    }
  };

  const clearConnectionTestResult = () => {
    setTestMessage(null);
    setTestSucceeded(false);
  };

  const activeTier = state.activeTier ?? brains?.escalon_activo ?? null;
  const activeCandidates = brains?.backends.filter(
    (backend) => backend.alive && backend.tier === brains.escalon_activo,
  );
  const activeIdentity =
    state.activeIdentity ?? (activeCandidates?.length === 1 ? activeCandidates[0].identity : null);
  const identityAmbiguous = (activeCandidates?.length ?? 0) > 1;

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <span className="app-header__eyebrow">Cliente local</span>
          <h1>Robot Desktop</h1>
        </div>
        <div className="app-header__actions">
          <span className={`health-badge health-badge--${health}`} role="status">
            {health === "online"
              ? "Core conectado"
              : health === "checking"
                ? "Comprobando Core"
                : health === "offline"
                  ? "Core sin conexión"
                  : "Core sin configurar"}
          </span>
          <button
            className="button button--secondary"
            type="button"
            disabled={turnBusy || sessionBusy}
            onClick={() => {
              clearConnectionTestResult();
              setSettingsOpen(true);
            }}
          >
            Ajustes
          </button>
        </div>
      </header>

      <BrainStatus
        activeTier={activeTier}
        activeIdentity={activeIdentity}
        costUsdAccumulated={brains?.cost_usd_acumulado ?? null}
        loading={brainsLoading}
        stale={Boolean(brainsError && brains)}
        error={identityAmbiguous ? "El Core informó más de una identidad activa para este escalón." : brainsError}
      />

      <div className="workspace-grid">
        <SessionSidebar
          sessionIds={recentSessionIds}
          activeSessionId={state.sessionId}
          busy={turnBusy || sessionBusy}
          onNewSession={handleNewSession}
          onSelectSession={(sessionId) => void loadSession(sessionId)}
          onResumeSession={(sessionId) => void loadSession(sessionId)}
          onForgetSession={(sessionId) => {
            if (sessionId !== state.sessionId) {
              setRecentSessionIds(forgetRecentSessionId(coreUrl, sessionId));
            }
          }}
        />

        <main className="chat-surface">
          <section
            ref={turnListRef}
            className="turn-list"
            aria-label="Conversación"
            onScroll={(event) => {
              const element = event.currentTarget;
              shouldAutoScrollRef.current =
                element.scrollHeight - element.scrollTop - element.clientHeight < 120;
            }}
          >
            {state.turns.length === 0 ? (
              <div className="empty-chat">
                <p className="empty-chat__mark" aria-hidden="true">R</p>
                <h2>Una interfaz delgada para tu Core local</h2>
                <p>Configurá la conexión, creá una sesión y escribí. La app no ejecuta modelos ni herramientas.</p>
              </div>
            ) : (
              state.turns.map((turn) => <TurnView turn={turn} key={turn.id} />)
            )}

            {state.connectionNotice ? (
              <p className="connection-notice" role="status">{state.connectionNotice}</p>
            ) : null}
            {state.error ? <p className="global-error" role="alert">{state.error}</p> : null}
            <span className="sr-only" role="status" aria-live="polite">
              {state.phase === "streaming"
                ? "El asistente está transmitiendo una respuesta."
                : state.phase === "paused"
                  ? "La respuesta espera una decisión humana."
                  : state.phase === "idle" && state.turns.length > 0
                    ? "El turno finalizó."
                    : ""}
            </span>
            <div ref={messagesEndRef} />
          </section>

          <Composer
            text={composerText}
            attachments={attachments}
            tierHint={tierHint}
            wantsCheap={wantsCheap}
            busy={sessionBusy}
            streaming={turnBusy}
            interrupting={state.phase === "interrupting"}
            onTextChange={setComposerText}
            onFilesSelected={handleFilesSelected}
            onRemoveAttachment={handleRemoveAttachment}
            onRetryAttachment={handleRetryAttachment}
            onTierHintChange={setTierHint}
            onWantsCheapChange={setWantsCheap}
            onSend={() => void handleSend()}
            onInterrupt={() => void handleInterrupt()}
          />
        </main>

        <ActivityPanel activities={state.activities} research={state.research} />
      </div>

      <ConfirmationDialog
        pending={state.pendingConfirmation}
        isSubmitting={state.confirmationSubmitting}
        interrupting={state.phase === "interrupting"}
        onDecision={(approved) => void handleDecision(approved)}
        onInterrupt={() => void handleInterrupt()}
      />

      <SettingsDialog
        open={settingsOpen}
        coreUrl={coreUrl}
        token={token}
        testing={testingConnection}
        testMessage={testMessage}
        testSucceeded={testSucceeded}
        error={settingsError}
        onClose={() => {
          settingsTestControllerRef.current?.abort();
          clearConnectionTestResult();
          setSettingsOpen(false);
        }}
        onSave={handleSaveSettings}
        onTest={(values) => void handleTestConnection(values)}
        onDraftChange={clearConnectionTestResult}
      />
    </div>
  );
}

function TurnView({ turn }: { turn: ChatTurn }) {
  return (
    <article className={`turn turn--${turn.role} turn--${turn.status}`}>
      <div className="turn__meta">
        <strong>{turn.role === "user" ? "Vos" : turn.role === "assistant" ? "Asistente" : "Sistema"}</strong>
        {turn.status !== "complete" ? <span>{turnStatusLabel(turn.status)}</span> : null}
      </div>

      {turn.brainNotices.map((notice) => (
        <div
          className={`brain-switch-notice brain-switch-notice--${notice.event.to.toLowerCase()}`}
          role="status"
          key={notice.id}
        >
          <strong>{switchVerb(notice.event.from, notice.event.to)} a {notice.event.to}</strong>
          <span> porque {notice.event.reason}</span>
          <small>
            {notice.event.identity.model_id} @ {notice.event.identity.provider_name}
            {notice.event.to === "PAID_CHEAP" || notice.event.to === "VIBE" ? " · puede generar costo" : ""}
          </small>
        </div>
      ))}

      {turn.content ? <MarkdownMessage content={turn.content} /> : <span className="typing-indicator">Pensando…</span>}

      {turn.attachments.length > 0 ? (
        <ul className="sent-attachments" aria-label="Adjuntos enviados">
          {turn.attachments.map((attachment) => (
            <li key={attachment.fileId}>
              {attachment.previewUrl && attachment.kind.startsWith("image/") ? (
                <img src={attachment.previewUrl} alt={`Vista previa de ${attachment.name}`} />
              ) : null}
              <span>{attachment.name}</span>
              <small>{formatBytes(attachment.size)}</small>
            </li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}

function turnStatusLabel(status: ChatTurn["status"]): string {
  switch (status) {
    case "streaming":
      return "Transmitiendo";
    case "error":
      return "Con error";
    case "interrupted":
      return "Interrumpido";
    case "recovered_unverified":
      return "Recuperado · estado final no verificable";
    case "complete":
      return "Completo";
  }
}

function switchVerb(from: Tier, to: Tier): string {
  const rank: Record<Tier, number> = { LOCAL: 0, FREE_QUOTA: 1, PAID_CHEAP: 2, VIBE: 3 };
  if (rank[to] > rank[from]) return "Subí";
  if (rank[to] < rank[from]) return "Bajé";
  return "Cambié";
}

export default App;
