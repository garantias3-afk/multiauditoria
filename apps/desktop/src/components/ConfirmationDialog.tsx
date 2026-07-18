import { useEffect, useId, useRef, type KeyboardEvent } from "react";
import type { PendingConfirmation } from "../state/chatReducer";

export interface ConfirmationDialogProps {
  pending: PendingConfirmation | null;
  isSubmitting: boolean;
  onDecision: (approved: boolean) => void;
  interrupting?: boolean;
  onInterrupt: () => void;
}

function renderArguments(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2) ?? String(value);
  } catch {
    return String(value);
  }
}

function focusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((element) => !element.hasAttribute("hidden"));
}

export function ConfirmationDialog({
  pending,
  isSubmitting,
  onDecision,
  interrupting = false,
  onInterrupt,
}: ConfirmationDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const rejectButtonRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const confirmId = pending?.event.confirm_id;

  useEffect(() => {
    if (!confirmId) return undefined;

    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const frame = requestAnimationFrame(() => rejectButtonRef.current?.focus());

    return () => {
      cancelAnimationFrame(frame);
      previouslyFocused?.focus();
    };
  }, [confirmId]);

  if (!pending) return null;

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      return;
    }

    if (event.key !== "Tab" || !dialogRef.current) return;
    const focusable = focusableElements(dialogRef.current);
    if (focusable.length === 0) {
      event.preventDefault();
      dialogRef.current.focus();
      return;
    }

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

  return (
    <div className="dialog-backdrop confirmation-backdrop">
      <div
        ref={dialogRef}
        className="dialog confirmation-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        tabIndex={-1}
        onKeyDown={handleKeyDown}
      >
        <div className="confirmation-dialog__pause" role="status">
          Stream en pausa · decisión humana requerida
        </div>
        <h2 id={titleId}>¿Permitir esta herramienta?</h2>
        <p id={descriptionId}>
          El Core pidió autorización para ejecutar <strong>{pending.event.tool}</strong>. No se
          continuará hasta que elijas una opción.
        </p>

        <section className="confirmation-dialog__arguments" aria-label="Argumentos de la herramienta">
          <h3>Argumentos</h3>
          <pre>{renderArguments(pending.event.args)}</pre>
        </section>

        <div className="confirmation-dialog__actions">
          <button
            className="button button--danger"
            type="button"
            disabled={interrupting}
            onClick={onInterrupt}
          >
            {interrupting ? "Deteniendo…" : "Detener turno"}
          </button>
          <button
            ref={rejectButtonRef}
            className="button button--secondary"
            type="button"
            disabled={isSubmitting || interrupting}
            onClick={() => onDecision(false)}
          >
            Rechazar
          </button>
          <button
            className="button button--danger"
            type="button"
            disabled={isSubmitting || interrupting}
            onClick={() => onDecision(true)}
          >
            Aprobar
          </button>
        </div>

        {isSubmitting ? (
          <p className="confirmation-dialog__submitting" role="status" aria-live="polite">
            Enviando tu decisión al Core…
          </p>
        ) : null}
      </div>
    </div>
  );
}

export default ConfirmationDialog;
