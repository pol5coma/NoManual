import { useEffect, useState } from "react";

import {
  getManual,
  reingestManual,
  type ManualUpload,
  type ProgressStep,
} from "./api";

// Fast enough that a step lasting 200 ms is seen happening rather than found
// already done. Polling stops the moment the pipeline finishes, so this costs
// a handful of requests per upload.
const POLL_MS = 600;
const TICK_MS = 100;

interface Props {
  manualId: string;
  // Developer mode: timings and what each step produced. Without it the panel
  // only says which stage the file is at, which is all someone uploading a
  // manual needs.
  detailed: boolean;
  // The upload form floats over this area, so the card steps aside while it
  // is open instead of being covered by it.
  shifted: boolean;
  onClose: () => void;
}

export default function IngestionPanel({
  manualId,
  detailed,
  shifted,
  onClose,
}: Props) {
  const [manual, setManual] = useState<ManualUpload | null>(null);
  const [failed, setFailed] = useState(false);
  // Bumped to restart polling after a manual reprocess, since the effect keys
  // off the manual id and that has not changed.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;

    async function poll() {
      try {
        const current = await getManual(manualId);
        if (!live) return;
        setManual(current);

        // Nothing moves once the pipeline is finished, so stop asking.
        if (current.status === "processing" || current.status === "pending") {
          window.setTimeout(poll, POLL_MS);
        }
      } catch {
        if (live) setFailed(true);
      }
    }

    poll();
    return () => {
      live = false;
    };
  }, [manualId, attempt]);

  if (failed) return null;

  const steps = manual?.progress ?? [];
  const done = steps.filter((step) => step.status === "done").length;
  const running = manual?.status === "processing" || manual?.status === "pending";
  const total = steps.reduce((sum, step) => sum + (step.duration_ms ?? 0), 0);

  // Uploading a PDF that is already indexed links it to the new model and
  // skips the pipeline: same file, same chunks, no reason to pay for the
  // embeddings twice. There is no progress to follow, so the panel says so
  // instead of pretending something is queued.
  const alreadyIndexed = !running && steps.length === 0;

  async function reprocess() {
    try {
      // Optimistic: the request returns the manual already claimed, and the
      // poll below picks up the steps as the worker writes them.
      const claimed = await reingestManual(manualId);
      setManual(claimed);
      setAttempt((current) => current + 1);
    } catch {
      setFailed(true);
    }
  }

  return (
    <section className={shifted ? "ingestion shifted" : "ingestion"}>
      <header>
        <div>
          <h2>
            {running
              ? "Procesando el manual"
              : alreadyIndexed
                ? "Este manual ya estaba indexado"
                : "Manual procesado"}
          </h2>
          <span className="ingestion-title">{manual?.title ?? "…"}</span>
        </div>
        <button type="button" className="link" onClick={onClose}>
          Ocultar
        </button>
      </header>

      {alreadyIndexed ? (
        <div className="ingestion-note">
          <p>
            El mismo PDF ya estaba procesado, así que se ha enlazado a este
            aparato sin volver a generar embeddings.
          </p>
          {detailed && (
            <button type="button" className="button" onClick={reprocess}>
              Reprocesar
            </button>
          )}
        </div>
      ) : (
        <>
          <div className="bar">
            <div
              className="bar-fill"
              style={{ width: `${steps.length ? (done / steps.length) * 100 : 0}%` }}
            />
          </div>
          <p className="bar-label">
            {steps.length ? `${done} de ${steps.length} pasos` : "En cola…"}
          </p>

          <ol className="steps">
            {steps.map((step) => (
              <Step key={step.step} step={step} detailed={detailed} />
            ))}
          </ol>
        </>
      )}

      {manual?.status === "ready" && (
        <footer className="done-label">
          Listo{detailed && total > 0 ? ` en ${formatDuration(total)}` : ""} ·{" "}
          {manual.page_count} páginas · {manual.chunk_count} fragmentos indexados
        </footer>
      )}
      {manual?.status === "failed" && (
        <footer className="failed-label">{manual.error}</footer>
      )}
    </section>
  );
}

function Step({ step, detailed }: { step: ProgressStep; detailed: boolean }) {
  const elapsed = useElapsed(step.status === "running");

  return (
    <li className={`step ${step.status}`}>
      <span className="marker" aria-hidden="true">
        {step.status === "done" ? "✓" : step.status === "failed" ? "!" : ""}
      </span>

      <div className="step-body">
        <div className="step-head">
          <span className="step-label">{step.label}</span>

          {/* A running step counts up, so a slow one looks busy rather than
              stuck. A finished one shows what it actually took. */}
          {detailed && step.status === "running" && (
            <span className="step-time live">{formatDuration(elapsed)}</span>
          )}
          {detailed && step.duration_ms !== undefined && (
            <span className="step-time">{formatDuration(step.duration_ms)}</span>
          )}
        </div>

        {detailed && step.detail && Object.keys(step.detail).length > 0 && (
          <dl className="step-detail">
            {Object.entries(step.detail).map(([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>{formatValue(value)}</dd>
              </div>
            ))}
          </dl>
        )}

        {step.error && <p className="step-error">{step.error}</p>}
      </div>
    </li>
  );
}

// Counts from the moment this step was first seen running. The server records
// the real duration; this is only so the number on screen keeps moving.
function useElapsed(active: boolean): number {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!active) return;

    const startedAt = performance.now();
    const id = window.setInterval(
      () => setElapsed(performance.now() - startedAt),
      TICK_MS,
    );

    return () => window.clearInterval(id);
  }, [active]);

  // Reading it as zero while idle, rather than resetting the state, keeps the
  // effect free of synchronous setState - which React flags as a cascading
  // render.
  return active ? elapsed : 0;
}


function formatDuration(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

// The language breakdown arrives as an object ({"es": 26, "en": 24}); numbers
// get thousands separators so 214 chunks and 13.847 characters read at a
// glance.
function formatValue(value: unknown): string {
  if (typeof value === "number") return value.toLocaleString("es-ES");
  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, count]) => `${key} ${count}`)
      .join(" · ");
  }
  return String(value);
}
