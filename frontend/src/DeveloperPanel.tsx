import { useCallback, useEffect, useState } from "react";

import {
  deleteManual,
  listManuals,
  reingestManual,
  type ManualUpload,
  type ProgressStep,
} from "./api";

// While anything is being ingested the list refreshes at this rate, so the
// steps are seen arriving. It stops as soon as everything is settled.
const POLL_MS = 600;
const TICK_MS = 100;

interface Props {
  // Manuals of the appliance in the picker. Without one, the latest uploads,
  // which is what you want right after adding a file.
  productId: string;
  productName: string | null;
  // Deleting the last manual of an appliance takes it out of the picker, which
  // only lists products with something indexed. The parent reloads it so the
  // catalogue matches what is really answerable.
  onManualsChanged: () => void;
}

// What the pipeline is doing, and the manuals it has already processed. This
// is the part of the product that normally hides behind a spinner: extraction,
// language detection, chunking, embeddings and indexing, each with what it
// produced and how long it took.
export default function DeveloperPanel({
  productId,
  productName,
  onManualsChanged,
}: Props) {
  const [manuals, setManuals] = useState<ManualUpload[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      return setManuals(await listManuals(productId || undefined));
    } catch {
      setError("Could not load manuals.");
    }
  }, [productId]);

  useEffect(() => {
    let live = true;

    async function poll() {
      if (!live) return;
      try {
        const current = await listManuals(productId || undefined);
        if (!live) return;
        setManuals(current);

        const working = current.some(
          (manual) => manual.status === "processing" || manual.status === "pending",
        );
        // Polling only while something moves: an idle panel costs nothing.
        window.setTimeout(poll, working ? POLL_MS : 5000);
      } catch {
        if (live) setError("Could not load manuals.");
      }
    }

    poll();
    return () => {
      live = false;
    };
  }, [productId]);

  async function reprocess(manual: ManualUpload) {
    try {
      await reingestManual(manual.id);
      load();
      onManualsChanged();
    } catch {
      setError("Could not queue that manual again.");
    }
  }

  async function remove(manual: ManualUpload) {
    // Destructive and not undoable: the chunks and the stored PDF go too, and
    // answers that cited those pages lose their source.
    const confirmed = window.confirm(
      `Delete "${manual.title}"? Its chunks and the stored file go with it.`,
    );
    if (!confirmed) return;

    try {
      await deleteManual(manual.id);
      load();
      onManualsChanged();
    } catch {
      setError("Could not delete that manual.");
    }
  }

  return (
    <section className="developer">
      <header>
        <h2>Manuals</h2>
        <span className="developer-scope">
          {productName ?? "latest uploads"} · {manuals.length}
        </span>
      </header>

      {error && <p className="developer-error">{error}</p>}

      {manuals.length === 0 && !error && (
        <p className="developer-empty">Nothing indexed here yet.</p>
      )}

      <ul className="manuals">
        {manuals.map((manual) => (
          <ManualRow
            key={manual.id}
            manual={manual}
            onReprocess={() => reprocess(manual)}
            onDelete={() => remove(manual)}
          />
        ))}
      </ul>
    </section>
  );
}

function ManualRow({
  manual,
  onReprocess,
  onDelete,
}: {
  manual: ManualUpload;
  onReprocess: () => void;
  onDelete: () => void;
}) {
  const working = manual.status === "processing" || manual.status === "pending";
  const steps = manual.progress ?? [];
  const done = steps.filter((step) => step.status === "done").length;
  const total = steps.reduce((sum, step) => sum + (step.duration_ms ?? 0), 0);

  return (
    <li className="manual">
      <div className="manual-head">
        <div className="manual-id">
          <span className="manual-title">{manual.title}</span>
          <span className="manual-facts">
            {manual.page_count ?? "—"} pages · {manual.chunk_count ?? "—"} chunks
            {!working && total > 0 && ` · ${formatDuration(total)}`}
          </span>
        </div>

        <div className="manual-actions">
          <span className={`status ${manual.status}`}>{manual.status}</span>
          <button
            type="button"
            className="button"
            onClick={onReprocess}
            disabled={working}
          >
            Reprocess
          </button>
          <button
            type="button"
            className="button danger"
            onClick={onDelete}
            disabled={working}
          >
            Delete
          </button>
        </div>
      </div>

      {manual.error && <p className="step-error">{manual.error}</p>}

      {steps.length > 0 && (
        <>
          <div className="bar">
            <div
              className="bar-fill"
              style={{ width: `${(done / steps.length) * 100}%` }}
            />
          </div>

          <ol className="steps">
            {steps.map((step) => (
              <Step key={step.step} step={step} />
            ))}
          </ol>
        </>
      )}
    </li>
  );
}

function Step({ step }: { step: ProgressStep }) {
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
          {step.status === "running" && (
            <span className="step-time live">{formatDuration(elapsed)}</span>
          )}
          {step.duration_ms !== undefined && (
            <span className="step-time">{formatDuration(step.duration_ms)}</span>
          )}
        </div>

        {step.detail && Object.keys(step.detail).length > 0 && (
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
// get thousands separators so 214 chunks and 13,847 characters read at a
// glance.
function formatValue(value: unknown): string {
  if (typeof value === "number") return value.toLocaleString("en-GB");
  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, count]) => `${key} ${count}`)
      .join(" · ");
  }
  return String(value);
}
