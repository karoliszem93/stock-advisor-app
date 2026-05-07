import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type TickerValidation, type WatchlistItem } from "../lib/api";
import { parseTicker } from "../lib/tickers";

type RunState = "idle" | "running" | "done" | "error";

interface AddError {
  message: string;
  suggestions?: string[];
}

export default function Watchlist() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [ticker, setTicker] = useState("");
  const [note, setNote] = useState("");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<AddError | null>(null);
  const [preview, setPreview] = useState<TickerValidation | null>(null);
  const [runStates, setRunStates] = useState<Record<string, RunState>>({});

  useEffect(() => {
    api.watchlist.list().then(setItems).catch(() => {});
  }, []);

  // Debounced preview validation as the user types.
  useEffect(() => {
    if (!ticker.trim()) {
      setPreview(null);
      setAddError(null);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const res = await api.watchlist.validate(ticker.trim().toUpperCase());
        setPreview(res);
      } catch {
        setPreview(null);
      }
    }, 500);
    return () => clearTimeout(t);
  }, [ticker]);

  async function add() {
    const t = ticker.trim().toUpperCase();
    if (!t) return;
    setAdding(true);
    setAddError(null);
    try {
      await api.watchlist.add(t, note || undefined);
      setTicker("");
      setNote("");
      setPreview(null);
      setItems(await api.watchlist.list());
    } catch (e: unknown) {
      const err = e as { detail?: { message?: string; suggestions?: string[] }; message?: string };
      setAddError({
        message: err.detail?.message || err.message || "Failed to add",
        suggestions: err.detail?.suggestions,
      });
    } finally {
      setAdding(false);
    }
  }

  async function addSuggested(suggestion: string) {
    setTicker(suggestion);
    setAddError(null);
  }

  async function remove(t: string) {
    await api.watchlist.remove(t);
    setItems(await api.watchlist.list());
  }

  async function runAnalysis(t: string) {
    setRunStates((s) => ({ ...s, [t]: "running" }));
    try {
      await api.triggerTickerRun(t);
      setTimeout(() => setRunStates((s) => ({ ...s, [t]: "done" })), 18_000);
    } catch (e) {
      console.error(e);
      setRunStates((s) => ({ ...s, [t]: "error" }));
    }
  }

  return (
    <div className="max-w-3xl">
      <h2 className="text-2xl font-semibold mb-1">Watchlist</h2>
      <p className="text-sm text-gray-400 mb-6">
        Tickers analyzed every run. Tickers are validated against Yahoo Finance
        before being saved — anything that validates here is guaranteed analyzable
        by the pipeline. Use <em>Run analysis</em> for fast single-ticker scoring.
      </p>

      <div className="rounded border border-border bg-panel/40 p-4 mb-6">
        <div className="flex gap-2">
          <input
            value={ticker}
            onChange={(e) => {
              setTicker(e.target.value);
              setAddError(null);
            }}
            onKeyDown={(e) => e.key === "Enter" && add()}
            placeholder="AAPL or VWRL.L"
            className="bg-bg border border-border rounded px-3 py-2 text-sm w-40 font-mono"
          />
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && add()}
            placeholder="optional note"
            className="bg-bg border border-border rounded px-3 py-2 text-sm flex-1"
          />
          <button
            onClick={add}
            disabled={adding}
            className="px-4 py-2 rounded bg-accent text-bg font-medium disabled:opacity-50"
          >
            {adding ? "Adding..." : "Add"}
          </button>
        </div>

        {/* Inline preview while user types — confirms ticker resolves */}
        {preview && preview.valid && ticker.trim() && (
          <div className="mt-2 text-xs text-gray-300">
            <span className="text-accent">✓</span>{" "}
            <span className="font-medium">{preview.name || preview.ticker}</span>
            {preview.exchange && (
              <span className="text-gray-500"> · {preview.exchange}</span>
            )}
            {preview.currency && (
              <span className="text-gray-500"> · {preview.currency}</span>
            )}
            {preview.last_close != null && (
              <span className="text-gray-500">
                {" "}· last close{" "}
                <span className="font-mono">{preview.last_close.toFixed(2)}</span>
              </span>
            )}
            {preview.asset_type === "etf" && (
              <span className="ml-2 text-[10px] text-accent/80">ETF</span>
            )}
          </div>
        )}
        {preview && !preview.valid && ticker.trim() && (
          <div className="mt-2 text-xs text-warn">
            ⚠ Yahoo Finance has no price data for this symbol — try a suffix variant
            (e.g. <code>{preview.suggestions?.[0] ?? "TICKER.L"}</code>).
          </div>
        )}

        {/* Hard error from POST */}
        {addError && (
          <div className="mt-3 rounded border border-danger/40 bg-danger/10 p-3 text-sm">
            <div className="text-danger font-medium">Couldn't add ticker</div>
            <div className="text-gray-300 mt-1">{addError.message}</div>
            {addError.suggestions && addError.suggestions.length > 0 && (
              <div className="mt-2 text-xs text-gray-400">
                Try one of these:{" "}
                {addError.suggestions.map((s, i) => (
                  <span key={s}>
                    {i > 0 && ", "}
                    <button
                      onClick={() => addSuggested(s)}
                      className="font-mono text-accent hover:underline"
                    >
                      {s}
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="rounded border border-border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-panel/60 text-gray-400 text-left">
            <tr>
              <th className="px-3 py-2 w-32">Ticker</th>
              <th className="px-3 py-2 w-24">Exchange</th>
              <th className="px-3 py-2">Note</th>
              <th className="px-3 py-2 w-44"></th>
              <th className="px-3 py-2 w-20"></th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr>
                <td className="px-3 py-4 text-gray-500" colSpan={5}>
                  No tickers yet — add some above.
                </td>
              </tr>
            )}
            {items.map((it) => {
              const t = parseTicker(it.ticker);
              const state = runStates[it.ticker] ?? "idle";
              return (
                <tr key={it.ticker} className="border-t border-border">
                  <td className="px-3 py-2 font-mono" title={t.full}>
                    {t.display}
                  </td>
                  <td
                    className="px-3 py-2 text-xs text-gray-400"
                    title={t.exchangeFull}
                  >
                    {t.exchange}
                  </td>
                  <td className="px-3 py-2 text-gray-300">{it.note}</td>
                  <td className="px-3 py-2">
                    <RunCell ticker={it.ticker} state={state} onRun={runAnalysis} />
                  </td>
                  <td className="px-3 py-2">
                    <button
                      onClick={() => remove(it.ticker)}
                      className="text-danger text-xs hover:underline"
                    >
                      remove
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RunCell({
  ticker,
  state,
  onRun,
}: {
  ticker: string;
  state: RunState;
  onRun: (t: string) => void;
}) {
  if (state === "running") {
    return (
      <span className="text-xs text-blue-400 inline-flex items-center gap-2">
        <Spinner /> running…
      </span>
    );
  }
  if (state === "done") {
    return (
      <span className="text-xs">
        <span className="text-accent mr-2">✓ done</span>
        <Link
          to={`/ticker/${encodeURIComponent(ticker)}`}
          className="text-accent hover:underline"
        >
          view results →
        </Link>
      </span>
    );
  }
  if (state === "error") {
    return <span className="text-xs text-danger">failed — check backend logs</span>;
  }
  return (
    <button
      onClick={() => onRun(ticker)}
      className="text-xs px-3 py-1 rounded border border-accent/40 text-accent hover:bg-accent/10"
      title={`Run the full 13-module analysis for ${ticker} now (~15s, 1 LLM call)`}
    >
      Run analysis
    </button>
  );
}

function Spinner() {
  return (
    <svg
      className="animate-spin h-3 w-3 text-blue-400"
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
  );
}
