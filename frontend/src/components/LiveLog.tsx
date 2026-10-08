import { useEffect, useRef, useState } from "react";
import { api, type LogLine, type RunLog } from "../lib/api";

const MAX_LINES = 1000;
const COLLAPSED_KEY = "liveLog.collapsed";

const LEVEL_COLOR: Record<string, string> = {
  WARNING: "text-warn",
  ERROR: "text-danger",
  CRITICAL: "text-danger",
};

// "Analyzing (12/43) — AAPL" / "LLM (19/30) — RBOT.L"
const PROGRESS_RE = /^(Analyzing|LLM) \((\d+)\/(\d+)\) — (.+)$/;

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour12: false });
}

function fmtElapsed(fromIso: string): string {
  const s = Math.max(0, Math.round((Date.now() - new Date(fromIso).getTime()) / 1000));
  const m = Math.floor(s / 60);
  return m > 0 ? `${m}m ${s % 60}s` : `${s}s`;
}

export default function LiveLog() {
  const [lines, setLines] = useState<LogLine[]>([]);
  const [run, setRun] = useState<RunLog | null>(null);
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [offline, setOffline] = useState(false);
  const [, setTick] = useState(0);
  const lastId = useRef(0);
  const scroller = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  const running = run?.status === "running";

  // Poll the log feed: fast while a run is active, slower when idle.
  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const r = await api.logs(lastId.current);
        if (cancelled) return;
        // Backend restarted → ids start over; reset our view.
        if (r.last_id < lastId.current) {
          lastId.current = 0;
          setLines([]);
          return;
        }
        if (r.lines.length) {
          lastId.current = r.last_id;
          setLines((prev) => [...prev, ...r.lines].slice(-MAX_LINES));
        }
        setOffline(false);
      } catch {
        if (!cancelled) setOffline(true);
      }
    }
    poll();
    const id = setInterval(poll, running ? 2000 : 10000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [running]);

  // Poll the latest run (any type) for the status pill.
  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const [latest] = await api.runs.list(1);
        if (!cancelled) setRun(latest ?? null);
      } catch {
        /* offline state is shown by the log poller */
      }
    }
    poll();
    const id = setInterval(poll, running ? 5000 : 30000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [running]);

  // Re-render every second so the elapsed timer moves.
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [running]);

  // Keep the view pinned to the newest line unless the user scrolled up.
  useEffect(() => {
    const el = scroller.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [lines, collapsed]);

  function onScroll() {
    const el = scroller.current;
    if (!el) return;
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  }

  function toggle() {
    const next = !collapsed;
    setCollapsed(next);
    try {
      localStorage.setItem(COLLAPSED_KEY, next ? "1" : "0");
    } catch {
      /* per-viewer convenience only */
    }
  }

  // Latest progress line, if the current run has produced one.
  let progress: { stage: string; done: number; total: number; ticker: string } | null = null;
  if (running) {
    for (let i = lines.length - 1; i >= 0; i--) {
      const m = PROGRESS_RE.exec(lines[i].msg);
      if (m) {
        progress = { stage: m[1] === "LLM" ? "Writing theses" : "Analyzing", done: +m[2], total: +m[3], ticker: m[4] };
        break;
      }
      if (new Date(lines[i].ts) < new Date(run!.started_at)) break;
    }
  }

  return (
    <section className="rounded border border-border bg-panel/40 mb-4 text-sm">
      <button
        onClick={toggle}
        className="w-full flex items-center justify-between gap-3 px-3 py-2 text-left"
        aria-expanded={!collapsed}
      >
        <div className="flex items-center gap-2 min-w-0">
          <span
            className={`inline-block h-2 w-2 rounded-full shrink-0 ${
              offline ? "bg-danger" : running ? "bg-blue-400 animate-pulse" : "bg-gray-500"
            }`}
          />
          <span className="font-medium">Live activity</span>
          <span className="text-gray-500 truncate">
            {offline
              ? "· backend unreachable"
              : running
              ? `· ${run!.run_type} running for ${fmtElapsed(run!.started_at)}`
              : "· idle"}
          </span>
        </div>
        <span className="text-gray-500 text-xs shrink-0">{collapsed ? "Show" : "Hide"}</span>
      </button>

      {!collapsed && (
        <div className="border-t border-border">
          {progress && (
            <div className="px-3 pt-2">
              <div className="flex justify-between text-xs text-gray-400 mb-1">
                <span>
                  {progress.stage} {progress.done}/{progress.total} — {progress.ticker}
                </span>
                <span>{Math.round((progress.done / progress.total) * 100)}%</span>
              </div>
              <div className="h-1 rounded bg-border overflow-hidden">
                <div
                  className="h-full bg-blue-400 transition-all"
                  style={{ width: `${(progress.done / progress.total) * 100}%` }}
                />
              </div>
            </div>
          )}
          <div
            ref={scroller}
            onScroll={onScroll}
            className="max-h-64 overflow-y-auto px-3 py-2 font-mono text-xs leading-5"
          >
            {lines.length === 0 ? (
              <div className="text-gray-500">No activity since the backend started.</div>
            ) : (
              lines.map((l) => (
                <div key={l.id} className={`whitespace-pre-wrap break-words ${LEVEL_COLOR[l.level] ?? "text-gray-300"}`}>
                  <span className="text-gray-500">{fmtTime(l.ts)}</span>{" "}
                  <span className="text-gray-500">{l.logger.split(".").pop()}</span>{" "}
                  {l.msg}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </section>
  );
}
