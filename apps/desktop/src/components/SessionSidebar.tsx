import { useState, type FormEvent } from "react";

export interface SessionSidebarProps {
  sessionIds: readonly string[];
  activeSessionId: string | null;
  busy?: boolean;
  onNewSession: () => void;
  onSelectSession: (sessionId: string) => void;
  onResumeSession: (sessionId: string) => void;
  onForgetSession?: (sessionId: string) => void;
  className?: string;
}

export function SessionSidebar({
  sessionIds,
  activeSessionId,
  busy = false,
  onNewSession,
  onSelectSession,
  onResumeSession,
  onForgetSession,
  className,
}: SessionSidebarProps) {
  const [resumeId, setResumeId] = useState("");
  const classes = ["session-sidebar", className].filter(Boolean).join(" ");

  const submitResume = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const sessionId = resumeId.trim();
    if (!sessionId || busy) return;
    onResumeSession(sessionId);
    setResumeId("");
  };

  return (
    <aside className={classes} aria-label="Historial de sesiones">
      <div className="session-sidebar__heading">
        <h2>Sesiones</h2>
        <button className="button button--primary" type="button" disabled={busy} onClick={onNewSession}>
          Nueva
        </button>
      </div>

      <form className="session-sidebar__resume" onSubmit={submitResume}>
        <label htmlFor="resume-session-id">Retomar por ID</label>
        <div>
          <input
            id="resume-session-id"
            value={resumeId}
            onChange={(event) => setResumeId(event.currentTarget.value)}
            placeholder="session_id"
            autoComplete="off"
            spellCheck={false}
            disabled={busy}
          />
          <button type="submit" disabled={busy || resumeId.trim().length === 0}>
            Abrir
          </button>
        </div>
      </form>

      <nav aria-label="Sesiones recientes">
        {sessionIds.length === 0 ? (
          <p className="session-sidebar__empty">No hay IDs de sesión guardados en este dispositivo.</p>
        ) : (
          <ul className="session-sidebar__list">
            {sessionIds.map((sessionId) => {
              const active = sessionId === activeSessionId;
              return (
                <li className={active ? "session-sidebar__item session-sidebar__item--active" : "session-sidebar__item"} key={sessionId}>
                  <button
                    className="session-sidebar__select"
                    type="button"
                    title={sessionId}
                    aria-current={active ? "page" : undefined}
                    disabled={busy || active}
                    onClick={() => onSelectSession(sessionId)}
                  >
                    <span>{sessionId}</span>
                    {active ? <small>Activa</small> : null}
                  </button>
                  {onForgetSession ? (
                    <button
                      className="session-sidebar__forget"
                      type="button"
                      aria-label={`Quitar ${sessionId} de sesiones recientes`}
                      title={active ? "La sesión activa no se puede quitar de recientes" : "Quitar de recientes"}
                      disabled={busy || active}
                      onClick={() => onForgetSession(sessionId)}
                    >
                      ×
                    </button>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </nav>
    </aside>
  );
}

export default SessionSidebar;
