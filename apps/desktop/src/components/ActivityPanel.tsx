import { useId, useState } from "react";
import type { ResearchProgressEvent } from "../core/types";
import type { ToolActivity } from "../state/chatReducer";
import { formatCost, summarize } from "../utils/format";

export interface ActivityPanelProps {
  activities: readonly ToolActivity[];
  research: ResearchProgressEvent | null;
  defaultOpen?: boolean;
  className?: string;
}

function durationLabel(activity: ToolActivity): string {
  if (activity.status === "running") return "En curso";
  if (activity.status === "outcome_unknown") return "Cierre no verificable";
  if (activity.status === "orphan_end") return "Fin sin inicio correlacionable";
  if (activity.endedAt === undefined) return "Duración no disponible";

  const milliseconds = Math.max(0, activity.endedAt - activity.startedAt);
  if (milliseconds < 1_000) return `~${Math.round(milliseconds)} ms`;
  return `~${(milliseconds / 1_000).toFixed(milliseconds < 10_000 ? 1 : 0)} s`;
}

function statusLabel(activity: ToolActivity): string {
  switch (activity.status) {
    case "running":
      return "En curso";
    case "complete":
      return "Completada";
    case "orphan_end":
      return "Resultado no correlacionado";
    case "outcome_unknown":
      return "Resultado no verificable";
  }
}

function ResearchCard({ research }: { research: ResearchProgressEvent }) {
  const denominator = research.of > 0 ? research.of : 1;
  const progress = Math.min(denominator, Math.max(0, research.iteration));

  return (
    <section className="research-progress" aria-labelledby="research-progress-title">
      <div className="research-progress__heading">
        <h3 id="research-progress-title">Investigación profunda</h3>
        <strong>
          Iteración {research.iteration}/{research.of}
        </strong>
      </div>
      <progress
        value={progress}
        max={denominator}
        aria-label={`Investigación: iteración ${research.iteration} de ${research.of}`}
      />
      <dl className="research-progress__details">
        <div>
          <dt>Consultas</dt>
          <dd>
            <pre>{summarize(research.queries, 1_200)}</pre>
          </dd>
        </div>
        <div>
          <dt>Fuentes leídas</dt>
          <dd>
            <pre>{summarize(research.sources_read, 1_200)}</pre>
          </dd>
        </div>
        <div>
          <dt>Costo informado</dt>
          <dd>{formatCost(research.cost_usd)}</dd>
        </div>
      </dl>
    </section>
  );
}

export function ActivityPanel({
  activities,
  research,
  defaultOpen = true,
  className,
}: ActivityPanelProps) {
  const headingId = useId();
  const [panelOpen, setPanelOpen] = useState(defaultOpen);
  const classes = ["activity-panel", className].filter(Boolean).join(" ");

  return (
    <aside className={classes} aria-labelledby={headingId}>
      <details open={panelOpen} onToggle={(event) => setPanelOpen(event.currentTarget.open)}>
        <summary>
          <span id={headingId}>Actividad</span>
          <span className="activity-panel__count" aria-label={`${activities.length} actividades`}>
            {activities.length}
          </span>
        </summary>

        <div className="activity-panel__content">
          {research ? <ResearchCard research={research} /> : null}

          {activities.length === 0 ? (
            <p className="activity-panel__empty">Todavía no hay herramientas en este turno.</p>
          ) : (
            <ol className="activity-timeline" aria-label="Cronología de herramientas">
              {activities.map((activity) => (
                <li
                  className={`activity-item activity-item--${activity.status}`}
                  key={activity.id}
                >
                  <div className="activity-item__heading">
                    <code>{activity.tool}</code>
                    <span className="activity-item__status">{statusLabel(activity)}</span>
                    <span className="activity-item__duration" title="Duración observada por el cliente">
                      {durationLabel(activity)}
                    </span>
                  </div>

                  <details className="activity-item__details">
                    <summary>Ver argumentos y resultado</summary>
                    <div>
                      <h4>Argumentos resumidos</h4>
                      <pre>{summarize(activity.args, 1_200)}</pre>
                    </div>
                    {activity.resultSummary !== undefined ? (
                      <div>
                        <h4>Resultado resumido</h4>
                        <pre>{summarize(activity.resultSummary, 1_200)}</pre>
                      </div>
                    ) : null}
                  </details>
                </li>
              ))}
            </ol>
          )}
        </div>
      </details>
      <span className="sr-only" role="status" aria-live="polite">
        {activities.some((activity) => activity.status === "running")
          ? "Hay una herramienta en ejecución."
          : ""}
      </span>
    </aside>
  );
}

export default ActivityPanel;
