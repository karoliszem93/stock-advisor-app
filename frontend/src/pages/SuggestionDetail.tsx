import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  api,
  TIMEFRAMES,
  type ScoringBreakdown,
  type Suggestion,
  type SuggestionDetail as SD,
  type Timeframe,
} from "../lib/api";
import { parseTicker } from "../lib/tickers";
import Confidence from "../components/Confidence";
import DirectionBadge from "../components/DirectionBadge";

export default function SuggestionDetail() {
  const { id } = useParams<{ id: string }>();
  const [s, setS] = useState<SD | null>(null);
  const [peers, setPeers] = useState<Suggestion[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    api.suggestions.get(Number(id)).then(setS).catch((e) => setError(String(e)));
  }, [id]);

  // Once we have the suggestion, fetch its peers (same ticker, same date, all risk profiles).
  useEffect(() => {
    if (!s) return;
    api.suggestions
      .list({
        on_date: s.suggestion_date,
        ticker: s.ticker,
        limit: 100, // ~28 max (4 risk × 7 timeframes)
      })
      .then(setPeers)
      .catch(() => setPeers([]));
  }, [s]);

  if (error) {
    return (
      <div className="max-w-3xl">
        <div className="rounded border border-danger/40 bg-danger/10 p-3 text-sm">
          {error}
        </div>
      </div>
    );
  }
  if (!s) return <div className="text-gray-400">Loading...</div>;

  const r = s.rationale || {};
  const t = parseTicker(s.ticker);
  const sb = r.scoring_breakdown;

  return (
    <div className="max-w-5xl">
      <Link to="/" className="text-xs text-gray-400 hover:text-accent">
        ← back to dashboard
      </Link>

      <header className="my-4 flex items-center gap-3 flex-wrap">
        <DirectionBadge direction={s.direction} />
        <Link
          to={`/ticker/${encodeURIComponent(s.ticker)}`}
          className="text-2xl font-mono font-semibold hover:text-accent"
          title={`Full ticker: ${s.ticker}`}
        >
          {t.display}
        </Link>
        {t.exchange !== "US" && (
          <span
            className="text-xs text-gray-400 px-2 py-0.5 rounded border border-border"
            title={t.exchangeFull}
          >
            {t.exchange}
          </span>
        )}
        <span className="text-gray-400 text-sm">
          {s.risk_profile} · {s.timeframe} · {s.suggestion_date} → target {s.target_date}
        </span>
        <Confidence raw={s.confidence} calibrated={s.confidence_calibrated} />
      </header>

      {r.headline && <p className="text-lg text-gray-200 mb-4">{r.headline}</p>}

      {/* Plan */}
      <Section title="Plan">
        <div className="grid grid-cols-3 gap-3 text-sm">
          <KV label="Entry €" value={fmt(s.entry_price_eur)} />
          <KV label="Stop-loss €" value={fmt(s.stop_loss_eur)} />
          <KV label="Target €" value={fmt(s.target_price_eur)} />
          <KV
            label="Suggested risk"
            value={
              s.suggested_risk_pct != null
                ? `${(s.suggested_risk_pct * 100).toFixed(2)}% of capital`
                : "—"
            }
          />
          <KV label="Asset type" value={s.asset_type} />
          <KV label="Data quality" value={r.data_quality ?? "—"} />
        </div>
      </Section>

      {/* Same ticker — other timeframes & risk profiles */}
      <PeerGrid current={s} peers={peers} />

      {/* How this was calculated */}
      <ScoringSection sb={sb} suggestion={s} drivers={r.confidence_drivers} />

      {/* Rationale */}
      <Section title="Why this trade">
        <RationaleBlock title="Technical case" body={r.technical_case} />
        <RationaleBlock title="Fundamental case" body={r.fundamental_case} />
        <RationaleBlock title="Sentiment case" body={r.sentiment_case} />
        <RationaleBlock title="Macro context" body={r.macro_context} />
        <RationaleBlock title="Why this timeframe" body={r.why_this_timeframe} />
      </Section>

      {/* Risks + invalidation */}
      <Section title="Risks & invalidation">
        {(r.key_risks?.length ?? 0) > 0 && (
          <div className="mb-3">
            <Heading>Key risks</Heading>
            <ul className="list-disc pl-5 text-sm text-gray-200 space-y-1">
              {r.key_risks!.map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
          </div>
        )}
        {(r.invalidation_triggers?.length ?? 0) > 0 && (
          <div className="mb-3">
            <Heading>Invalidation triggers</Heading>
            <ul className="list-disc pl-5 text-sm text-gray-200 space-y-1">
              {r.invalidation_triggers!.map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
          </div>
        )}
        {r.counter_argument && (
          <div className="mb-3">
            <Heading>Strongest counter-argument</Heading>
            <p className="text-sm text-gray-200">{r.counter_argument}</p>
          </div>
        )}
      </Section>

      {/* Tax */}
      {r.tax_notes && (
        <Section title="Tax angle (LT-resident)">
          <p className="text-sm text-gray-200">{r.tax_notes}</p>
        </Section>
      )}

      {/* Price notes */}
      {(r.price_notes?.length ?? 0) > 0 && (
        <Section title="Price notes">
          <ul className="list-disc pl-5 text-xs text-gray-400 space-y-1">
            {r.price_notes!.map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Peer grid — same ticker on the same date, all risk profiles & timeframes
// ---------------------------------------------------------------------------
function PeerGrid({
  current,
  peers,
}: {
  current: Suggestion;
  peers: Suggestion[];
}) {
  // Build lookup: peerByCell[risk][tf]
  const byCell = useMemo(() => {
    const map: Record<string, Record<string, Suggestion>> = {};
    for (const p of peers) {
      (map[p.risk_profile] ??= {})[p.timeframe] = p;
    }
    return map;
  }, [peers]);

  const risks = Object.keys(byCell).sort();
  if (risks.length === 0) return null;

  return (
    <Section title={`Same ticker on ${current.suggestion_date} — all timeframes & risk profiles`}>
      <p className="text-xs text-gray-400 mb-3">
        How the model rates {current.ticker} across every cell on this date. Click any cell
        to see its full rationale.
      </p>
      <div className="overflow-x-auto">
        <table className="text-sm border-separate border-spacing-1">
          <thead>
            <tr>
              <th></th>
              {TIMEFRAMES.map((tf) => (
                <th key={tf} className="text-center text-xs text-gray-500 px-2">
                  {tf}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {risks.map((r) => (
              <tr key={r}>
                <td className="text-xs text-gray-400 capitalize pr-3">{r}</td>
                {TIMEFRAMES.map((tf) => {
                  const cell = byCell[r]?.[tf as Timeframe];
                  const isCurrent = cell?.id === current.id;
                  if (!cell) {
                    return (
                      <td
                        key={tf}
                        className="border border-border/60 bg-bg/40 rounded p-2 text-center text-xs text-gray-600 min-w-[100px]"
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
                      className={`border ${dirCol} rounded p-2 align-top min-w-[110px] ${
                        isCurrent ? "ring-2 ring-accent/60" : ""
                      }`}
                    >
                      <Link to={`/suggestion/${cell.id}`} className="block hover:opacity-80">
                        <div className="flex items-center justify-between gap-1 mb-1">
                          <DirectionBadge direction={cell.direction} />
                          <Confidence
                            raw={cell.confidence}
                            calibrated={cell.confidence_calibrated}
                          />
                        </div>
                        {cell.target_price_eur != null && (
                          <div className="text-[10px] font-mono text-gray-300">
                            tgt €{cell.target_price_eur.toFixed(2)}
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
      </div>
      <p className="text-[11px] text-gray-500 mt-2">
        Highlighted cell = the suggestion you're currently viewing.
      </p>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Scoring breakdown — full math behind the call
// ---------------------------------------------------------------------------
function ScoringSection({
  sb,
  suggestion,
  drivers,
}: {
  sb: ScoringBreakdown | undefined;
  suggestion: Suggestion;
  drivers:
    | { factor: string; delta: number; reason: string }[]
    | undefined;
}) {
  // Two render modes: rich (when full sb is present, post-fix) vs legacy (top-5 drivers only).
  if (sb && sb.contributors && sb.contributors.length) {
    const sorted = [...sb.contributors].sort(
      (a, b) => Math.abs(b.contribution) - Math.abs(a.contribution),
    );
    const dirReason = explainDirection(sb);

    return (
      <Section title="How this was calculated">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm mb-4">
          <KV label="Cell score" value={fmtSigned(sb.cell_score)} />
          <KV label="Cell confidence" value={`${(sb.cell_confidence * 100).toFixed(0)}%`} />
          <KV
            label="Direction threshold"
            value={`±${sb.direction_threshold.toFixed(2)}`}
          />
          <KV
            label="Min confidence"
            value={`${(sb.min_confidence * 100).toFixed(0)}%`}
          />
        </div>
        <p className="text-sm text-gray-200 mb-4">{dirReason}</p>

        <Heading>Module-by-module contributions</Heading>
        <p className="text-[11px] text-gray-500 mb-2">
          Each module emits a score in [-1, +1]. Its contribution to the cell score is
          <code className="mx-1 px-1 rounded bg-panel">cell_weight × horizon_weight × score × confidence</code>
          . Sum of contributions divided by sum of weights = cell_score.
        </p>
        <div className="rounded border border-border overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-panel/60 text-gray-400 text-left">
              <tr>
                <th className="px-3 py-2">Module</th>
                <th className="px-3 py-2 text-right">Score</th>
                <th className="px-3 py-2 text-right">Conf</th>
                <th className="px-3 py-2 text-right">Cell w</th>
                <th className="px-3 py-2 text-right">Horizon w</th>
                <th className="px-3 py-2 text-right">Contribution</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((c) => (
                <tr key={c.module} className="border-t border-border">
                  <td className="px-3 py-1.5 font-mono">{c.module}</td>
                  <td className="px-3 py-1.5 text-right font-mono">
                    {fmtSigned(c.score)}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono">
                    {(c.confidence * 100).toFixed(0)}%
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-gray-400">
                    {c.cell_weight.toFixed(2)}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-gray-400">
                    {c.horizon_weight.toFixed(2)}
                  </td>
                  <td
                    className={`px-3 py-1.5 text-right font-mono ${
                      c.contribution > 0
                        ? "text-accent"
                        : c.contribution < 0
                        ? "text-danger"
                        : "text-gray-400"
                    }`}
                  >
                    {fmtSigned(c.contribution)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {!sb.filter_passed && sb.filter_reason && (
          <p className="text-xs text-warn mt-3">
            ⚠ Risk filter: {sb.filter_reason}
          </p>
        )}
      </Section>
    );
  }

  // Legacy fallback for old suggestions (only top-5 drivers in DB).
  if (!drivers || drivers.length === 0) return null;
  return (
    <Section title="How this was calculated (legacy)">
      <p className="text-xs text-gray-500 mb-2">
        This suggestion was generated before the full scoring breakdown was persisted.
        Showing top contributors only — re-run the pipeline to get the full module-by-module
        view on future suggestions.
      </p>
      <table className="w-full text-sm">
        <thead className="text-gray-400 text-left">
          <tr>
            <th className="py-1 pr-2">Module</th>
            <th className="py-1 pr-2">Δ</th>
            <th className="py-1 pr-2">Reason</th>
          </tr>
        </thead>
        <tbody>
          {drivers.map((d, i) => (
            <tr key={i} className="border-t border-border">
              <td className="py-2 pr-2 font-mono">{d.factor}</td>
              <td
                className={`py-2 pr-2 font-mono ${
                  d.delta > 0 ? "text-accent" : d.delta < 0 ? "text-danger" : "text-gray-400"
                }`}
              >
                {fmtSigned(d.delta)}
              </td>
              <td className="py-2 pr-2 text-gray-300">{d.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {/* Use suggestion confidence as a fallback display */}
      <p className="text-xs text-gray-500 mt-3">
        Final confidence: {(suggestion.confidence * 100).toFixed(0)}%
      </p>
    </Section>
  );
}

function explainDirection(sb: ScoringBreakdown): string {
  const score = sb.cell_score;
  const conf = sb.cell_confidence;
  const t = sb.direction_threshold;
  const mc = sb.min_confidence;

  if (sb.direction === "buy") {
    return (
      `Cell score ${fmtSigned(score)} is above the +${t.toFixed(2)} BUY threshold ` +
      `and confidence ${(conf * 100).toFixed(0)}% is at or above the ${(mc * 100).toFixed(0)}% minimum, ` +
      `so the call is BUY.`
    );
  }
  if (sb.direction === "sell_short") {
    return (
      `Cell score ${fmtSigned(score)} is below the −${t.toFixed(2)} SELL-SHORT threshold ` +
      `and confidence ${(conf * 100).toFixed(0)}% is at or above the ${(mc * 100).toFixed(0)}% minimum, ` +
      `so the call is SELL-SHORT.`
    );
  }
  // avoid
  if (conf < mc) {
    return (
      `Confidence ${(conf * 100).toFixed(0)}% is below the ${(mc * 100).toFixed(0)}% minimum — ` +
      `not enough conviction to commit to a direction. Call is AVOID.`
    );
  }
  return (
    `Cell score ${fmtSigned(score)} is between ±${t.toFixed(2)} — no clear directional edge. ` +
    `Call is AVOID.`
  );
}

// ---------------------------------------------------------------------------
// Small UI helpers
// ---------------------------------------------------------------------------
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded border border-border bg-panel/40 p-4 mb-4">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-3">{title}</h3>
      {children}
    </section>
  );
}

function RationaleBlock({ title, body }: { title: string; body: string | undefined }) {
  if (!body) return null;
  return (
    <div className="mb-3">
      <Heading>{title}</Heading>
      <p className="text-sm text-gray-200 leading-relaxed">{body}</p>
    </div>
  );
}

function Heading({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-xs text-gray-400 uppercase tracking-wide mb-1">{children}</div>
  );
}

function KV({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border bg-bg/40 p-2">
      <div className="text-[10px] text-gray-500 uppercase tracking-wide">{label}</div>
      <div className="font-mono">{value}</div>
    </div>
  );
}

function fmt(n: number | null): string {
  if (n == null) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function fmtSigned(n: number): string {
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(3)}`;
}
