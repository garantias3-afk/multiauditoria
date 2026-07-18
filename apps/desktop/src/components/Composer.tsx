import { useRef, useState, type ChangeEvent, type DragEvent, type FormEvent, type KeyboardEvent } from "react";
import { TIERS, type Tier } from "../core/types";
import { formatBytes } from "../utils/format";

export type ComposerAttachmentStatus = "queued" | "uploading" | "uploaded" | "error";

export interface ComposerAttachmentChip {
  id: string;
  name: string;
  size: number;
  status: ComposerAttachmentStatus;
  kind?: string;
  fileId?: string;
  previewUrl?: string;
  error?: string;
}

export interface ComposerProps {
  text: string;
  attachments: readonly ComposerAttachmentChip[];
  tierHint: Tier | undefined;
  wantsCheap: boolean;
  busy?: boolean;
  streaming?: boolean;
  interrupting?: boolean;
  onTextChange: (text: string) => void;
  onFilesSelected: (files: File[]) => void;
  onRemoveAttachment: (attachmentId: string) => void;
  onRetryAttachment?: (attachmentId: string) => void;
  onTierHintChange: (tier: Tier | undefined) => void;
  onWantsCheapChange: (wantsCheap: boolean) => void;
  onSend: () => void;
  onInterrupt: () => void;
  className?: string;
}

function isImageAttachment(attachment: ComposerAttachmentChip): boolean {
  if (attachment.kind?.startsWith("image/")) return true;
  return /\.(avif|gif|jpe?g|png|svg|webp)$/i.test(attachment.name);
}

function attachmentStatusLabel(status: ComposerAttachmentStatus): string {
  switch (status) {
    case "queued":
      return "En cola";
    case "uploading":
      return "Subiendo";
    case "uploaded":
      return "Listo";
    case "error":
      return "Error";
  }
}

export function Composer({
  text,
  attachments,
  tierHint,
  wantsCheap,
  busy = false,
  streaming = false,
  interrupting = false,
  onTextChange,
  onFilesSelected,
  onRemoveAttachment,
  onRetryAttachment,
  onTierHintChange,
  onWantsCheapChange,
  onSend,
  onInterrupt,
  className,
}: ComposerProps) {
  const [dragActive, setDragActive] = useState(false);
  const dragDepth = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const interactionDisabled = busy || streaming;
  const uploadsReady = attachments.every((attachment) => attachment.status === "uploaded");
  const hasContent = text.trim().length > 0 || attachments.length > 0;
  const canSend = hasContent && uploadsReady && !interactionDisabled;
  const classes = ["composer", dragActive ? "composer--drag-active" : null, className]
    .filter(Boolean)
    .join(" ");

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (canSend) onSend();
  };

  const handleTextKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    if (canSend) onSend();
  };

  const handleFileInput = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.currentTarget.files ?? []);
    event.currentTarget.value = "";
    if (files.length > 0) onFilesSelected(files);
  };

  const handleDragEnter = (event: DragEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (interactionDisabled) return;
    dragDepth.current += 1;
    setDragActive(true);
  };

  const handleDragLeave = (event: DragEvent<HTMLFormElement>) => {
    event.preventDefault();
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDragActive(false);
  };

  const handleDragOver = (event: DragEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = interactionDisabled ? "none" : "copy";
    }
  };

  const handleDrop = (event: DragEvent<HTMLFormElement>) => {
    event.preventDefault();
    dragDepth.current = 0;
    setDragActive(false);
    if (interactionDisabled) return;
    const files = Array.from(event.dataTransfer.files);
    if (files.length > 0) onFilesSelected(files);
  };

  return (
    <form
      className={classes}
      onSubmit={submit}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {dragActive ? (
        <div className="composer__drop-overlay" aria-hidden="true">
          Soltá los archivos para subirlos
        </div>
      ) : null}

      {attachments.length > 0 ? (
        <ul className="attachment-list" aria-label="Archivos adjuntos">
          {attachments.map((attachment) => (
            <li
              className={`attachment-chip attachment-chip--${attachment.status}`}
              key={attachment.id}
            >
              {attachment.previewUrl && isImageAttachment(attachment) ? (
                <img src={attachment.previewUrl} alt={`Vista previa de ${attachment.name}`} />
              ) : (
                <span className="attachment-chip__icon" aria-hidden="true">
                  Archivo
                </span>
              )}
              <span className="attachment-chip__body">
                <strong title={attachment.name}>{attachment.name}</strong>
                <small>
                  {formatBytes(attachment.size)} · {attachmentStatusLabel(attachment.status)}
                </small>
                {attachment.error ? <span role="alert">{attachment.error}</span> : null}
              </span>
              {attachment.status === "error" && onRetryAttachment ? (
                <button
                  type="button"
                  disabled={interactionDisabled}
                  onClick={() => onRetryAttachment(attachment.id)}
                >
                  Reintentar
                </button>
              ) : null}
              <button
                className="attachment-chip__remove"
                type="button"
                aria-label={`Quitar ${attachment.name}`}
                disabled={interactionDisabled}
                onClick={() => onRemoveAttachment(attachment.id)}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      <textarea
        className="composer__input"
        value={text}
        onChange={(event) => onTextChange(event.currentTarget.value)}
        onKeyDown={handleTextKeyDown}
        placeholder={streaming ? "Esperá o detené el turno actual…" : "Escribí un mensaje…"}
        aria-label="Mensaje"
        aria-describedby="composer-keyboard-help"
        rows={3}
        disabled={interactionDisabled}
      />
      <small id="composer-keyboard-help">Enter envía · Shift+Enter agrega una línea</small>

      <div className="composer__controls">
        <input
          ref={fileInputRef}
          className="sr-only"
          type="file"
          multiple
          tabIndex={-1}
          aria-hidden="true"
          disabled={interactionDisabled}
          onChange={handleFileInput}
        />
        <button
          className="button button--secondary"
          type="button"
          disabled={interactionDisabled}
          onClick={() => fileInputRef.current?.click()}
        >
          Adjuntar
        </button>

        <label className={tierHint === "VIBE" ? "composer__tier composer__tier--expensive" : "composer__tier"}>
          Escalón por turno
          <select
            value={tierHint ?? ""}
            disabled={interactionDisabled}
            onChange={(event) => {
              const value = event.currentTarget.value;
              onTierHintChange(value === "" ? undefined : (value as Tier));
            }}
          >
            <option value="">Automático</option>
            {TIERS.map((tier) => (
              <option value={tier} key={tier}>
                {tier === "VIBE" ? "VIBE · alto costo" : tier}
              </option>
            ))}
          </select>
        </label>

        <label className="composer__cheap-mode">
          <input
            type="checkbox"
            checked={wantsCheap}
            disabled={interactionDisabled}
            onChange={(event) => onWantsCheapChange(event.currentTarget.checked)}
          />
          Modo barato
        </label>

        <div className="composer__primary-actions">
          {streaming ? (
            <button
              className="button button--danger"
              type="button"
              disabled={interrupting}
              onClick={onInterrupt}
            >
              {interrupting ? "Deteniendo…" : "Detener"}
            </button>
          ) : (
            <button className="button button--primary" type="submit" disabled={!canSend}>
              Enviar
            </button>
          )}
        </div>
      </div>

      {!uploadsReady ? (
        <p className="composer__upload-status" role="status" aria-live="polite">
          Esperando que terminen los uploads antes de enviar.
        </p>
      ) : null}
      {tierHint === "VIBE" ? (
        <p className="composer__cost-warning" role="status">
          VIBE está marcado como un escalón de alto costo.
        </p>
      ) : null}
    </form>
  );
}

export default Composer;
