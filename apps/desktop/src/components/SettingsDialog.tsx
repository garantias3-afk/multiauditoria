import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

export interface SettingsValues {
  coreUrl: string;
  token: string;
}

export interface SettingsDialogProps {
  open: boolean;
  coreUrl: string;
  token: string;
  testing?: boolean;
  testMessage?: string | null;
  testSucceeded?: boolean;
  error?: string | null;
  onClose: () => void;
  onSave: (values: SettingsValues) => void;
  onTest: (values: SettingsValues) => void;
  onDraftChange?: () => void;
}

function focusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((element) => !element.hasAttribute("hidden"));
}

export function SettingsDialog({
  open,
  coreUrl,
  token,
  testing = false,
  testMessage = null,
  testSucceeded = false,
  error = null,
  onClose,
  onSave,
  onTest,
  onDraftChange,
}: SettingsDialogProps) {
  const [draftUrl, setDraftUrl] = useState(coreUrl);
  const [draftToken, setDraftToken] = useState(token);
  const dialogRef = useRef<HTMLDivElement>(null);
  const urlInputRef = useRef<HTMLInputElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    if (!open) return undefined;
    setDraftUrl(coreUrl);
    setDraftToken(token);

    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const frame = requestAnimationFrame(() => urlInputRef.current?.focus());
    return () => {
      cancelAnimationFrame(frame);
      previouslyFocused?.focus();
    };
  }, [open, coreUrl, token]);

  if (!open) return null;

  const values = (): SettingsValues => ({ coreUrl: draftUrl.trim(), token: draftToken });

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!testing) onSave(values());
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab" || !dialogRef.current) return;

    const focusable = focusableElements(dialogRef.current);
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const canSubmit = draftUrl.trim().length > 0 && draftToken.trim().length > 0 && !testing;
  const tokenWillChange = token.trim().length > 0 && draftToken.trim() !== token.trim();

  return (
    <div className="dialog-backdrop settings-backdrop">
      <div
        ref={dialogRef}
        className="dialog settings-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        onKeyDown={handleKeyDown}
      >
        <div className="settings-dialog__heading">
          <h2 id={titleId}>Ajustes del Core</h2>
          <button className="dialog__close" type="button" aria-label="Cerrar ajustes" onClick={onClose}>
            ×
          </button>
        </div>
        <p id={descriptionId}>
          Esta app sólo se conecta al Core local. No ingreses claves de proveedores de IA.
        </p>

        <form onSubmit={submit}>
          <label htmlFor="core-url">URL del Core</label>
          <input
            ref={urlInputRef}
            id="core-url"
            type="url"
            inputMode="url"
            value={draftUrl}
            onChange={(event) => {
              setDraftUrl(event.currentTarget.value);
              onDraftChange?.();
            }}
            placeholder="http://127.0.0.1:8850"
            autoComplete="url"
            spellCheck={false}
            disabled={testing}
            required
          />

          <label htmlFor="core-token">Token del Core</label>
          <input
            id="core-token"
            type="password"
            value={draftToken}
            onChange={(event) => {
              setDraftToken(event.currentTarget.value);
              onDraftChange?.();
            }}
            autoComplete="new-password"
            spellCheck={false}
            disabled={testing}
            required
          />
          <small>El token se conserva sólo en memoria y debe volver a ingresarse al reiniciar.</small>
          {tokenWillChange ? (
            <p className="settings-dialog__warning" role="note">
              Guardar quitará los IDs recientes asociados a la URL elegida. No borra sesiones del Core.
            </p>
          ) : null}

          {error ? (
            <p className="settings-dialog__error" role="alert">
              {error}
            </p>
          ) : null}
          {testMessage ? (
            <p
              className={testSucceeded ? "settings-dialog__test settings-dialog__test--ok" : "settings-dialog__test"}
              role={testSucceeded ? "status" : "alert"}
            >
              {testMessage}
            </p>
          ) : null}

          <div className="settings-dialog__actions">
            <button
              className="button button--secondary"
              type="button"
              disabled={!canSubmit}
              onClick={() => onTest(values())}
            >
              {testing ? "Probando…" : "Probar conexión"}
            </button>
            <button className="button button--primary" type="submit" disabled={!canSubmit}>
              {tokenWillChange ? "Guardar y quitar recientes" : "Guardar"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default SettingsDialog;
