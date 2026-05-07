import { useEffect, useMemo, useState } from "react";
import {
  api,
  RISK_PROFILES,
  TIMEFRAMES,
  type Direction,
  type RiskProfile,
  type Suggestion,
  type Timeframe,
} from "../lib/api";
import RunBanner from "../components/RunBanner";
import SuggestionTable from "../components/SuggestionTable";

const DIRECTIONS: Direction[] = ["buy", "avoid", "sell_short"];

export default function Dashboard() {
  const [suggestions, setSuggestions] = useState<Suggestion[] | null>(null);
  const [dates, setDates] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [date, setDate] = useState<string>("");
  const [risk, setRisk] = useState<RiskProfile | "">("");
  const [timeframe, setTimeframe] = useState<Timeframe | "">("");
  // Default to BUY — the most actionable view for the morning brief.
  const [direction, setDirection] = useState<Direction | "">("buy");
  const [tickerFilter, setTickerFilter] = useState<string>("");

  useEffect(() => {
    api.suggestions.distinctDates().then((ds) => {
      setDates(ds);
      // Default to most recent date if available
      if (ds.length > 0) setDate(ds[0]);
    });
  }, []);

  useEffect(() => {
    setSuggestions(null);
    api.suggestions
      .list({
        on_date: date || undefined,
        risk: risk || undefined,
        timeframe: timeframe || undefined,
        direction: direction || undefined,
        ticker: tickerFilter || undefined,
        limit: 500,
      })
      .then(setSuggestions)
      .catch((e) => setError(String(e)));
  }, [date, risk, timeframe, direction, tickerFilter]);

  const counts = useMemo(() => {
    if (!suggestions) return null;
    const total = suggestions.length;
    const byDir = { buy: 0, avoid: 0, sell_short: 0 };
    for (const s of suggestions) byDir[s.direction]++;
    return { total, byDir };
  }, [suggestions]);

  return (
    <div className="max-w-screen-2xl">
      <header className="mb-4">
        <h2 className="text-2xl font-semibold">Dashboard</h2>
      </header>

      <RunBanner />

      {error && (
        <div className="mb-4 rounded border border-danger/40 bg-danger/10 p-3 text-sm">
          {error}
        </div>
      )}

      {/* Filter bar */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Field label="Date">
          <select
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="bg-bg border border-border rounded px-2 py-1 text-sm"
          >
            <option value="">Any</option>
            {dates.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Risk">
          <select
            value={risk}
            onChange={(e) => setRisk(e.target.value as RiskProfile | "")}
            className="bg-bg border border-border rounded px-2 py-1 text-sm capitalize"
          >
            <option value="">All</option>
            {RISK_PROFILES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Timeframe">
          <select
            value={timeframe}
            onChange={(e) => setTimeframe(e.target.value as Timeframe | "")}
            className="bg-bg border border-border rounded px-2 py-1 text-sm font-mono"
          >
            <option value="">All</option>
            {TIMEFRAMES.map((tf) => (
              <option key={tf} value={tf}>
                {tf}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Direction">
          <select
            value={direction}
            onChange={(e) => setDirection(e.target.value as Direction | "")}
            className="bg-bg border border-border rounded px-2 py-1 text-sm uppercase"
          >
            <option value="">All</option>
            {DIRECTIONS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Ticker">
          <input
            value={tickerFilter}
            onChange={(e) => setTickerFilter(e.target.value.toUpperCase())}
            placeholder="AAPL"
            className="bg-bg border border-border rounded px-2 py-1 text-sm w-28 font-mono"
          />
        </Field>

        {(risk || timeframe || direction || tickerFilter) && (
          <button
            onClick={() => {
              setRisk("");
              setTimeframe("");
              setDirection("");
              setTickerFilter("");
            }}
            className="text-xs text-gray-400 hover:text-accent ml-2"
          >
            Clear filters
          </button>
        )}
      </div>

      {/* Counts strip */}
      {counts && (
        <div className="mb-3 text-xs text-gray-400 flex gap-3">
          <span>{counts.total} total</span>
          <span>·</span>
          <span className="text-accent">{counts.byDir.buy} buy</span>
          <span>·</span>
          <span className="text-danger">{counts.byDir.sell_short} sell-short</span>
          <span>·</span>
          <span>{counts.byDir.avoid} avoid</span>
        </div>
      )}

      {suggestions === null ? (
        <div className="rounded border border-border bg-panel/30 p-6 text-sm text-gray-400">
          Loading suggestions...
        </div>
      ) : (
        <SuggestionTable suggestions={suggestions} />
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex items-center gap-2 text-xs text-gray-400">
      <span className="uppercase tracking-wide">{label}</span>
      {children}
    </label>
  );
}
