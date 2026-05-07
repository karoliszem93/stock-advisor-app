import { useEffect, useState } from "react";
import { api, type RunLog } from "../lib/api";

const STATUS_COLOR: Record<string, string> = {
  ok: "text-accent",
  partial: "text-warn",
  failed: "text-danger",
  running: "text-blue-400",
};

export default function RunBanner() {
  const [run, setRun] = useState<RunLog | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    refresh();
  }, []);

  function refresh() {
    api.runs.latest("daily_pipeline").then(setRun).catch(() => setRun(null));
  }

  async function trigger() {
    setBusy(true);
    try {
      await api.triggerDailyRun();
      // Refresh quickly so the user sees status change to "running"
      setTimeout(refresh, 800);
      // Then again later — pipeline can take many minutes
      setTimeout(refresh, 30_000);
    } finally {
      setBusy(false);
    }
  }

  if (!run) {
    return (
      <div className="rounded border border-border bg-panel/40 p-3 mb-4 text-sm flex items-center justify-between">
        <span className="text-gray-400">No daily run on record yet.</span>
        <button
          onClick={trigger}
          disabled={busy}
          className="px-3 py-1 rounded bg-accent text-bg text-xs font-medium disabled:opacity-50"
        >
          {busy ? "Triggering..." : "Run pipeline now"}
        </button>
      </div>
    );
  }

  const summary = run.summary || {};
  const errCount = run.errors ? Object.keys(run.errors).length : 0;
  const degraded = errCount > 0 || run.status === "partial";

  return (
    <div
      className={`rounded border p-3 mb-4 text-sm flex items-center justify-between ${
        degraded
          ? "border-warn/40 bg-warn/5"
          : run.status === "failed"
          ? "border-danger/40 bg-danger/5"
          : "border-border bg-panel/40"
      }`}
    >
      <div className="flex items-center gap-3">
        <span className={`font-medium ${STATUS_COLOR[run.status] ?? ""}`}>
          {run.status === "running" ? "RUNNING" : run.status.toUpperCase()}
        </span>
        <span className="text-gray-400">·</span>
        <span className="text-gray-300">
          {run.run_type} at{" "}
          {new Date(run.started_at).toLocaleString(undefined, {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
        {summary && typeof summary === "object" && "suggestions_created" in summary && (
          <>
            <span className="text-gray-400">·</span>
            <span className="text-gray-300">
              {String(summary.suggestions_created)} suggestions across{" "}
              {String(summary.cells)} cells
            </span>
          </>
        )}
        {summary && "duration_seconds" in summary && (
          <>
            <span className="text-gray-400">·</span>
            <span className="text-gray-500">
              {Math.round(Number(summary.duration_seconds))}s
            </span>
          </>
        )}
      </div>

      <div className="flex items-center gap-3">
        {degraded && (
          <span className="text-warn text-xs">
            ⚠ {errCount > 0 ? `${errCount} provider error${errCount === 1 ? "" : "s"}` : "degraded"}
          </span>
        )}
        <button
          onClick={trigger}
          disabled={busy}
          title={run.status === "running" ? "A run is already in progress — clicking will start a parallel run" : "Trigger a pipeline run"}
          className="px-3 py-1 rounded bg-accent text-bg text-xs font-medium disabled:opacity-50"
        >
          {busy ? "..." : "Run now"}
        </button>
      </div>
    </div>
  );
}
