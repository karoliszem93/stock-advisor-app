import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, RISK_PROFILES, TIMEFRAMES, type SuggestionDetail } from "../lib/api";
import { parseTicker } from "../lib/tickers";
import Confidence from "../components/Confidence";
import DirectionBadge from "../components/DirectionBadge";
import HeaderTooltip from "../components/HeaderTooltip";

const TICKER_TF_TOOLTIPS: Record<string, string> = {
  Date: "Date the suggestion was generated.",
  Risk: "Conservative / Balanced / Growth / Aggressive — risk profile this call is tailored to.",
  TF: "Timeframe — 1w / 2w / 1m / 3m / 6m / 1y / 3y. Target date = suggestion date + this window.",
  Direction:
    "BUY = bullish; AVOID = no clear signal — pass; SELL-SHORT = bearish (or sell if you hold it). " +
    "T212 Invest doesn't allow shorts, so SELL-SHORT is best read as 'don't buy / consider selling'.",
  Conf: "Confidence in the call. (raw) means uncalibrated until ≥50 validated outcomes exist.",
  "Target €": "Profit target in EUR.",
  Headline: "One-line thesis summary. Click for the full structured rationale.",
};

export default function TickerView() {
  const { ticker } = useParams<{ ticker: string }>();
  const [items, setItems] = useState<SuggestionDetail[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ticker) return;
    api.suggestions
      .byTicker(ticker)
      .then(setItems)
      .catch((e) => setError(String(e)));
  }, [ticker]);

  // Latest suggestion_date — we group only the most recent run by default
  const latestDate = useMemo(() => {
    if (!items || items.length === 0) return "";
    return items[0].suggestion_date;
  }, [items]);

  // Build a (risk × timeframe) grid of the latest run
  const grid = useMemo(() => {
    if (!items) return null;
    const latest = items.filter((i) => i.suggestion_date === latestDate);
    const byCell: Record<string, SuggestionDetail | undefined> = {};
    for (const s of latest) byCell[`${s.risk_profile}.${s.timeframe}`] = s;
    return byCell;
  }, [items, latestDate]);

  // Older history, latest first
  const history = useMemo(() => {
    if (!items) return [];
    return items.filter((i) => i.suggestion_date !== latestDate);
  }, [items, latestDate]);

  if (error) {
    return (
      <div className="max-w-3xl">
        <div className="rounded border border-danger/40 bg-danger/10 p-3 text-sm">
          {error}
        </div>
      </div>
    );
  }
  if (items === null) return <div className="text-gray-400">Loading...</div>;

  return (
    <div className="max-w-screen-2xl">
      <Link to="/" className="text-xs text-gray-400 hover:text-accent">
        ← back to dashboard
      </Link>

      <header className="my-4">
        <div className="flex items-baseline gap-3">
          <h2 className="text-2xl font-mono font-semibold">
            {ticker ? parseTicker(ticker).display : ""}
          </h2>
          {ticker && parseTicker(ticker).exchange !== "US" && (
            <span
              className="text-xs text-gray-400 px-2 py-0.5 rounded border border-border"
              title={parseTicker(ticker).exchangeFull}
            >
              {parseTicker(ticker).exchange}
            </span>
          )}
          <span className="text-xs text-gray-500 font-mono">{ticker}</span>
        </div>
        <p className="text-sm text-gray-400 mt-1">
          All suggestions across risk profiles and timeframes.{" "}
          {items.length === 0
            ? "No suggestions on record yet."
            : `${items.length} total · latest run ${latestDate}.`}
        </p>
      </header>

      {items.length === 0 ? (
        <div className="rounded border border-border bg-panel/30 p-6 text-sm text-gray-400">
          This ticker hasn't been analyzed yet. Add it to your watchlist or wait
          for the next daily run.
        </div>
      ) : (
        <>
          {grid && (
            <section className="rounded border border-border bg-panel/40 p-4 mb-6 overflow-x-auto">
              <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-3">
                Latest run — {latestDate}
              </h3>
              <table className="text-sm border-separate border-spacing-1">
                <thead>
                  <tr>
                    <th className="text-left text-xs text-gray-500"></th>
                    {TIMEFRAMES.map((tf) => (
                      <th key={tf} className="text-center text-xs text-gray-500 px-2">
                        {tf}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {RISK_PROFILES.map((r) => (
                    <tr key={r}>
                      <td className="text-xs text-gray-400 capitalize pr-3">
                        {r}
                      </td>
                      {TIMEFRAMES.map((tf) => {
                        const cell = grid[`${r}.${tf}`];
                        if (!cell) {
                          return (
                            <td
                              key={tf}
                              className="border border-border/60 bg-bg/40 rounded p-2 text-center text-xs text-gray-600"
                            >
                              —
                            </td>
                          );
                        }
                        const dirCol =
                          cell.direction === "buy"
                            ? "border-accent/40 bg-accent/5"
                            : cell.direction === "sell_short"
                            ? "border-danger/40 bg-danger/5"
                            : "border-border bg-bg/40";
                        return (
                          <td
                            key={tf}
                            className={`border ${dirCol} rounded p-2 align-top min-w-[110px]`}
                          >
                            <Link
                              to={`/suggestion/${cell.id}`}
                              className="block hover:opacity-80"
                            >
                              <div className="flex items-center justify-between gap-2 mb-1">
                                <DirectionBadge direction={cell.direction} />
                                <Confidence
                                  raw={cell.confidence}
                                  calibrated={cell.confidence_calibrated}
                                />
                              </div>
                              <div className="text-[10px] text-gray-400">
                                target {cell.target_date}
                              </div>
                              {cell.target_price_eur != null && (
                                <div className="text-[10px] font-mono text-gray-300 mt-1">
                                  €{cell.target_price_eur.toFixed(2)}
                                </div>
                              )}
                            </Link>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {history.length > 0 && (
            <section>
              <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
                Earlier runs
              </h3>
              <div className="rounded border border-border overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-panel/60 text-gray-400 text-left">
                    <tr>
                      <HeaderTooltip name="Date" tip={TICKER_TF_TOOLTIPS.Date} />
                      <HeaderTooltip name="Risk" tip={TICKER_TF_TOOLTIPS.Risk} />
                      <HeaderTooltip name="TF" tip={TICKER_TF_TOOLTIPS.TF} />
                      <HeaderTooltip name="Direction" tip={TICKER_TF_TOOLTIPS.Direction} />
                      <HeaderTooltip name="Conf" tip={TICKER_TF_TOOLTIPS.Conf} />
                      <HeaderTooltip name="Target €" tip={TICKER_TF_TOOLTIPS["Target €"]} />
                      <HeaderTooltip name="Headline" tip={TICKER_TF_TOOLTIPS.Headline} />
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((s) => (
                      <tr key={s.id} className="border-t border-border">
                        <td className="px-3 py-2 text-gray-400">
                          {s.suggestion_date}
                        </td>
                        <td className="px-3 py-2 capitalize">{s.risk_profile}</td>
                        <td className="px-3 py-2 font-mono">{s.timeframe}</td>
                        <td className="px-3 py-2">
                          <DirectionBadge direction={s.direction} />
                        </td>
                        <td className="px-3 py-2">
                          <Confidence raw={s.confidence} calibrated={s.confidence_calibrated} />
                        </td>
                        <td className="px-3 py-2 font-mono text-gray-300">
                          {s.target_price_eur != null
                            ? s.target_price_eur.toFixed(2)
                            : "—"}
                        </td>
                        <td className="px-3 py-2 text-gray-300">
                          <Link
                            to={`/suggestion/${s.id}`}
                            className="hover:text-accent"
                          >
                            {s.headline ?? "—"}
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
