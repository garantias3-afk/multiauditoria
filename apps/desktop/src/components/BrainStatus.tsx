import type { Identity, Tier } from "../core/types";
import { formatCost } from "../utils/format";

export interface BrainStatusProps {
  activeTier: Tier | null;
  activeIdentity: Identity | null;
  costUsdAccumulated: number | null;
  loading?: boolean;
  stale?: boolean;
  error?: string | null;
  className?: string;
}

export function BrainStatus({
  activeTier,
  activeIdentity,
  costUsdAccumulated,
  loading = false,
  stale = false,
  error = null,
  className,
}: BrainStatusProps) {
  const classes = [
    "brain-status",
    activeTier ? `brain-status--${activeTier.toLowerCase()}` : null,
    activeTier === "VIBE" ? "brain-status--expensive" : null,
    stale ? "brain-status--stale" : null,
    className,
  ]
    .filter(Boolean)
    .join(" ");

  const identity = activeIdentity
    ? `${activeIdentity.model_id} @ ${activeIdentity.provider_name}`
    : "Identidad no disponible";

  return (
    <section className={classes} aria-label="Cerebro y costo" aria-live="polite">
      <div className="brain-status__item">
        <span className="brain-status__label">Escalón</span>
        <strong className="brain-status__tier">
          {loading && activeTier === null ? "Consultando…" : (activeTier ?? "Sin datos")}
        </strong>
        {activeTier === "VIBE" ? <span className="brain-status__warning">Alto costo</span> : null}
      </div>

      <div className="brain-status__item brain-status__identity">
        <span className="brain-status__label">Modelo</span>
        <span title={activeIdentity?.cost_class}>{identity}</span>
      </div>

      <div className="brain-status__item">
        <span className="brain-status__label">Costo acumulado</span>
        <strong>
          {costUsdAccumulated === null ? "Costo no disponible" : formatCost(costUsdAccumulated)}
        </strong>
      </div>

      {stale ? <span className="brain-status__stale">Datos desactualizados</span> : null}
      {error ? (
        <span className="brain-status__error" role="alert">
          {error}
        </span>
      ) : null}
    </section>
  );
}

export default BrainStatus;
