import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  RISK_PROFILES,
  TIMEFRAMES,
  type AggregatePerformance,
  type ValidationRow,
} from "../lib/api";
import { parseTicker } from "../lib/tickers";
import HeaderTooltip from "../components/HeaderTooltip";

// Tooltip text per column header in the validations table.
const VAL_TOOLTIPS: Record<string, string> = {
  Validated: "Date the validation sweep scored this suggestion (after target_date passed).",
  Ticker: "Stock or ETF symbol — click to open the per-ticker grid.",
  Exchange: "Exchange where this listing trades.",
  Risk: "Risk profile this suggestion was tailored to.",
  TF: "Timeframe — how far out the call was meant to play out.",
  Direction:
    "BUY = bullish; AVOID = no clear signal — pass; SELL-SHORT = bearish " +
    "(or sell if you held it).",
  Outcome:
    "How the call resolved: CORRECT = direction right + magnitude meaningful; " +
    "INCORRECT = direction wrong or stop-hit; PARTIAL = right direction but " +
    "didn't reach target / hit stop first.",
  Score:
    "Outcome score in [-1, +1]. ≈ price_return × 5 (so ±20% maps to ±1.0). " +
    "For 'Avoid' suggestions: small realized move → +0.5; large missed move → negative.",
  "Total € ret":
    "Realized total return in EUR including price + dividends + FX effect. Gross of tax.",
  "After-tax":
    "After applying LT 15% capital gains and dividend withholding (€500 annual exemption " +
    "not modeled per-trade).",
  MFE:
    "Maximum Favorable Excursion — best-case unrealized gain reached during the window. " +
    "Tells you whether the trade went in your favor at any point.",
  MAE:
    "Maximum Adverse Excursion — worst-case unrealized drawdown during the window. " +
    "Tells you how much the position bled before resolving.",
};

function VHeader({ name, align = "left" }: { name: string; align?: "left" | "right" }) {
  return <HeaderTooltip name={name} tip={VAL_TOOLTIPS[name]} align={align} />;
}

export default function Validations() {
  const [rows, setRows] = useState<ValidationRow[] | null>(null);
  const [agg, setAgg] = useState<AggregatePerformance | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.validations.list(500).then(setRows).catch((e) => setErr(String(e)));
    api.validations.aggregate().then(setAgg).catch(() => {});
  }, []);

  return (
    <div className="max-w-screen-2xl">
      <header className="mb-4">
        <h2 className="text-2xl font-semibold">Validation history</h2>
        <p className="text-sm text-gray-400">
          Suggestions whose target date has arrived, scored against actual
          price + dividend + FX outcomes.
        </p>
      </header>

      {err && (
        <div className="mb-4 rounded border border-danger/40 bg-danger/10 p-3 text-sm">
          {err}
        </div>
      )}

      {/* Aggregate */}
      <Aggregate agg={agg} />

      {/* Validations table */}
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mt-6 mb-2">
        Validated suggestions ({rows?.length ?? 0})
      </h3>
      {rows === null ? (
        <div className="text-sm text-gray-400">Loading...</div>
      ) : rows.length === 0 ? (
        <div className="rounded border border-border bg-panel/30 p-6 text-sm text-gray-400">
          No validated suggestions yet — none have reached their target date.
        </div>
      ) : (
        <div className="rounded border border-border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-panel/60 text-gray-400 text-left">
              <tr>
                <VHeader name="Validated" />
                <VHeader name="Ticker" />
                <VHeader name="Exchange" />
                <VHeader name="Risk" />
                <VHeader name="TF" />
                <VHeader name="Direction" />
                <VHeader name="Outcome" />
                <VHeader name="Score" align="right" />
                <VHeader name="Total € ret" align="right" />
                <VHeader name="After-tax" align="right" />
                <VHeader name="MFE" align="right" />
                <VHeader name="MAE" align="right" />
              </tr>
            </thead>
            <tbody>
              {rows.map((v) => (
                <tr key={v.id} className="border-t border-border">
                  <td className="px-3 py-2 text-gray-400">
                    {new Date(v.validated_at).toLocaleDateString()}
                  </td>
                  <td className="px-3 py-2 font-mono">
                    {v.ticker && (
                      <Link
                        to={`/ticker/${encodeURIComponent(v.ticker)}`}
                        className="hover:text-accent"
                        title={`Full ticker: ${v.ticker}`}
                      >
                        {parseTicker(v.ticker).display}
                      </Link>
                    )}
                  </td>
                  <td
                    className="px-3 py-2 text-xs text-gray-400"
                    title={v.ticker ? parseTicker(v.ticker).exchangeFull : ""}
                  >
                    {v.ticker ? parseTicker(v.ticker).exchange : "—"}
                  </td>
                  <td className="px-3 py-2 capitalize">{v.risk_profile}</td>
                  <td className="px-3 py-2 font-mono">{v.timeframe}</td>
                  <td className="px-3 py-2 uppercase text-xs text-gray-400">
                    {v.direction}
                  </td>
                  <td
                    className={`px-3 py-2 font-medium ${
                      v.outcome === "correct"
                        ? "text-accent"
                        : v.outcome === "incorrect"
                        ? "text-danger"
                        : "text-warn"
                    }`}
                  >
                    {v.outcome}
                  </td>
                  <td className="px-3 py-2 text-right font-mono">
                    {v.outcome_score.toFixed(2)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono">
                    {pct(v.actual_total_return_pct_eur)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono">
                    {pct(v.after_tax_return_pct_eur)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-accent/80">
                    {pct(v.max_favorable_excursion_pct)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-danger/80">
                    {pct(v.max_adverse_excursion_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Aggregate({ agg }: { agg: AggregatePerformance | null }) {
  if (!agg) {
    return (
      <div className="rounded border border-border bg-panel/30 p-6 text-sm text-gray-400">
        Loading aggregate...
      </div>
    );
  }
  if (!agg.ready) {
    return (
      <div className="rounded border border-border bg-panel/30 p-6 text-sm text-gray-400">
        Aggregate not ready yet — {agg.reason}.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
      <Card title="Total validated" value={String(agg.total_validated)} />
      <Card
        title="Hit rate (overall)"
        value={`${(agg.overall.hit_rate * 100).toFixed(0)}%`}
      />
      <Card
        title="Mean €-return"
        value={
          agg.overall.mean_return_pct_eur != null
            ? `${(agg.overall.mean_return_pct_eur * 100).toFixed(2)}%`
            : "—"
        }
      />

      {/* Heat-map of by-cell hit rate */}
      <div className="md:col-span-3 rounded border border-border bg-panel/40 p-4 overflow-x-auto">
        <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-3">
          Hit rate by (risk × timeframe)
        </h3>
        <table className="text-sm">
          <thead>
            <tr>
              <th className=""></th>
              {TIMEFRAMES.map((tf) => (
                <th
                  key={tf}
                  className="text-center text-xs text-gray-500 font-mono px-2 pb-1"
                >
                  {tf}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {RISK_PROFILES.map((r) => (
              <tr key={r}>
                <td className="text-xs text-gray-400 capitalize pr-3">{r}</td>
                {TIMEFRAMES.map((tf) => {
                  const c = agg.by_cell[`${r}.${tf}`];
                  if (!c || c.n === 0) {
                    return (
                      <td
                        key={tf}
                        className="text-center text-xs text-gray-600 px-2 py-1"
                      >
                        —
                      </td>
                    );
                  }
                  const hr = c.hit_rate;
                  const bg =
                    hr >= 0.6
                      ? "bg-accent/30"
                      : hr >= 0.4
                      ? "bg-warn/20"
                      : "bg-danger/20";
                  return (
                    <td
                      key={tf}
                      className={`text-center font-mono text-xs px-2 py-1 rounded ${bg}`}
                      title={`n=${c.n} · score ${c.mean_outcome_score.toFixed(2)}`}
                    >
                      {(hr * 100).toFixed(0)}%
                      <div className="text-[9px] opacity-60">n={c.n}</div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Card({ title, value }: { title: string; value: string }) {
  return (
    <div className="rounded border border-border bg-panel/40 p-4">
      <div className="text-xs text-gray-400 uppercase tracking-wide mb-1">
        {title}
      </div>
      <div className="text-2xl font-mono">{value}</div>
    </div>
  );
}

function pct(v: number | null): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(2)}%`;
}
