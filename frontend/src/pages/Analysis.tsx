import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  api,
  RISK_PROFILES,
  TIMEFRAMES,
  type AnalysisCell,
  type FullAnalysis,
  type ModuleResultFull,
  type RiskProfile,
  type Timeframe,
} from "../lib/api";
import DirectionBadge from "../components/DirectionBadge";
import SymbolSearch from "../components/chart/SymbolSearch";
import { GROUP_ORDER, MODULE_INFO, PROFILE_LABEL } from "../lib/moduleInfo";

const sign = (v: number, d = 2) => `${v >= 0 ? "+" : ""}${v.toFixed(d)}`;
const scoreColor = (v: number | null | undefined) =>
  v == null ? "text-gray-500" : v >= 0.05 ? "text-accent" : v <= -0.05 ? "text-danger" : "text-gray-400";

function ScoreBar({ value }: { value: number | null }) {
  const v = Math.max(-1, Math.min(1, value ?? 0));
  return (
    <div className="relative h-1.5 w-full rounded bg-border">
      <div className="absolute left-1/2 top-[-2px] h-2.5 w-px bg-gray-500" />
      <div
        className={`absolute top-0 h-1.5 rounded ${v >= 0 ? "bg-accent" : "bg-danger"}`}
        style={v >= 0 ? { left: "50%", width: `${v * 50}%` } : { right: "50%", width: `${-v * 50}%` }}
      />
    </div>
  );
}

function topHorizons(hw: Record<string, number>): string {
  const max = Math.max(...Object.values(hw));
  return TIMEFRAMES.filter((t) => (hw[t] ?? 0) >= max * 0.85).join(" · ");
}

export default function Analysis() {
  const { ticker: routeTicker } = useParams<{ ticker: string }>();
  const navigate = useNavigate();
  const ticker = (routeTicker ?? "").toUpperCase();
  const [data, setData] = useState<FullAnalysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [risk, setRisk] = useState<RiskProfile>(() => {
    try {
      return (JSON.parse(localStorage.getItem("chart.risk") ?? '"balanced"') as RiskProfile) || "balanced";
    } catch {
      return "balanced";
    }
  });
  const [tf, setTf] = useState<Timeframe>(() => {
    try {
      return (JSON.parse(localStorage.getItem("chart.tf") ?? '"1m"') as Timeframe) || "1m";
    } catch {
      return "1m";
    }
  });

  function load(refresh = false) {
    if (!ticker) return;
    setLoading(true);
    setError(null);
    api.analysis(ticker, refresh)
      .then(setData)
      .catch((e) => {
        setData(null);
        setError(String(e).includes("404") ? `No price data for ${ticker}.` : String(e));
      })
      .finally(() => setLoading(false));
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => load(), [ticker]);

  const cell = useMemo(
    () => data?.cells.find((c) => c.risk_profile === risk && c.timeframe === tf) ?? null,
    [data, risk, tf],
  );

  if (!ticker) {
    return (
      <div className="max-w-xl">
        <h2 className="mb-3 text-2xl font-semibold">Analysis</h2>
        <p className="mb-3 text-sm text-gray-400">Pick a symbol to see every indicator behind its Buy / Avoid / Sell call.</p>
        <SymbolSearch value="" onSelect={(s) => navigate(`/analysis/${encodeURIComponent(s)}`)} />
      </div>
    );
  }

  return (
    <div className="max-w-screen-xl space-y-6 pb-10">
      {/* ---- header ---- */}
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <SymbolSearch value={ticker} onSelect={(s) => navigate(`/analysis/${encodeURIComponent(s)}`)} />
          {data && (
            <div className="text-sm">
              <span className="font-semibold text-gray-100">{data.name ?? ticker}</span>
              <span className="ml-2 text-gray-500">
                {[data.exchange, data.currency, data.asset_type === "etf" ? "ETF" : data.sector].filter(Boolean).join(" · ")}
              </span>
              <span className="ml-3 font-mono text-gray-200">{data.last_close?.toFixed(2)}</span>
              <span className="ml-1 text-xs text-gray-500">({data.last_date})</span>
            </div>
          )}
          <div className="ml-auto flex items-center gap-3 text-xs">
            <Link to={`/chart/${encodeURIComponent(ticker)}`} className="text-accent hover:underline">Open chart →</Link>
            <Link to={`/ticker/${encodeURIComponent(ticker)}`} className="text-accent hover:underline">Suggestion history →</Link>
            <button
              onClick={() => load(true)}
              disabled={loading}
              className="rounded border border-border px-2 py-1 text-gray-300 hover:bg-panel disabled:opacity-50"
            >
              {loading ? "Analysing…" : "↻ Recompute"}
            </button>
          </div>
        </div>
        <p className="text-xs text-gray-500">
          Computed live from current data
          {data && ` at ${new Date(data.computed_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`} —
          the same modules and scoring as the 08:00 run, without the AI-written thesis.
          {data?.benchmark && ` Market comparisons use the ${data.benchmark}.`}
        </p>
      </header>

      {error && <div className="rounded border border-danger/40 bg-danger/10 p-3 text-sm">{error}</div>}
      {loading && !data && <div className="text-sm text-gray-400">Running all analysis modules for {ticker}… (a few seconds)</div>}

      {data && (
        <>
          <VerdictMatrix data={data} risk={risk} tf={tf} onSelect={(r, t) => { setRisk(r); setTf(t); }} />
          {cell && <CellBreakdown data={data} cell={cell} />}
          <ModuleSections data={data} />
          {Object.keys(data.data_errors).length > 0 && (
            <details className="rounded border border-border bg-panel/30 p-3 text-xs text-gray-400">
              <summary className="cursor-pointer text-gray-300">Data issues ({Object.keys(data.data_errors).length})</summary>
              <ul className="mt-2 space-y-1">
                {Object.entries(data.data_errors).map(([k, v]) => (
                  <li key={k}><span className="font-mono text-gray-300">{k}</span>: {v}</li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
function VerdictMatrix({ data, risk, tf, onSelect }: {
  data: FullAnalysis; risk: RiskProfile; tf: Timeframe; onSelect: (r: RiskProfile, t: Timeframe) => void;
}) {
  const stored = new Map(data.stored.cells.map((c) => [`${c.risk_profile}.${c.timeframe}`, c]));
  return (
    <section className="rounded border border-border bg-panel/30 p-4">
      <h3 className="mb-1 text-sm font-semibold">Verdict by risk profile and horizon</h3>
      <p className="mb-3 text-xs text-gray-500">
        Each cell weighs the modules below differently: by your risk profile (e.g. Conservative leans on quality and fundamentals,
        Aggressive on momentum) and by horizon (chart signals matter for weeks, fundamentals for months/years).
        BUY when the score is ≥ +{data.thresholds.direction.toFixed(2)} and confidence ≥ {(data.thresholds.min_confidence * 100).toFixed(0)}%,
        SELL-SHORT when ≤ −{data.thresholds.direction.toFixed(2)}, otherwise AVOID. Click a cell for the breakdown.
      </p>
      <div className="overflow-x-auto">
        <table className="text-xs">
          <thead>
            <tr className="text-gray-500">
              <th className="pr-3 text-left font-normal" />
              {TIMEFRAMES.map((t) => <th key={t} className="px-1 pb-1 font-normal">{t}</th>)}
            </tr>
          </thead>
          <tbody>
            {RISK_PROFILES.map((r) => (
              <tr key={r}>
                <td className="pr-3 text-gray-400">{PROFILE_LABEL[r]}</td>
                {TIMEFRAMES.map((t) => {
                  const c = data.cells.find((x) => x.risk_profile === r && x.timeframe === t)!;
                  const s = stored.get(`${r}.${t}`);
                  const sel = r === risk && t === tf;
                  return (
                    <td key={t} className="p-0.5">
                      <button
                        onClick={() => onSelect(r, t)}
                        className={`w-24 rounded border px-1.5 py-1 text-left ${sel ? "border-accent bg-accent/10" : "border-border hover:bg-panel"}`}
                        title={s ? `App's stored call (${data.stored.date}): ${s.direction}` : undefined}
                      >
                        <DirectionBadge direction={c.direction} />
                        <div className={`mt-0.5 font-mono text-[11px] ${scoreColor(c.score)}`}>
                          {sign(c.score)} <span className="text-gray-500">· {(c.confidence * 100).toFixed(0)}%</span>
                        </div>
                        {!c.filter_passed && <div className="text-[10px] text-warn">filtered</div>}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[10px] text-gray-500">Score · confidence. Hover a cell to see the app&apos;s stored call from the last run.</p>
    </section>
  );
}

// ---------------------------------------------------------------------------
function CellBreakdown({ data, cell }: { data: FullAnalysis; cell: AnalysisCell }) {
  const weightSum = cell.contributors.reduce((a, c) => a + c.cell_w * c.horizon_w * c.confidence, 0);
  const rows = cell.contributors.map((c) => ({ ...c, points: weightSum ? c.weighted_contrib / weightSum : 0 }));
  const maxAbs = Math.max(0.0001, ...rows.map((r) => Math.abs(r.points)));
  const counted = new Set(rows.map((r) => r.module));
  const weights = data.profile_weights[cell.risk_profile];
  const excluded = Object.entries(data.modules)
    .filter(([name]) => !counted.has(name))
    .map(([name, m]) => {
      const w = weights[name] ?? 0;
      const h = m.horizon_weights[cell.timeframe] ?? 0;
      const why = m.score == null || m.data_quality === "missing" ? "no data"
        : w <= 0 ? `not used by ${PROFILE_LABEL[cell.risk_profile]}`
        : h <= 0 ? `irrelevant at ${cell.timeframe}`
        : "zero confidence";
      return { name, why };
    });
  const stored = data.stored.cells.find((c) => c.risk_profile === cell.risk_profile && c.timeframe === cell.timeframe);
  const eventNote = cell.notes.find((n) => n.startsWith("Earnings"));

  return (
    <section className="rounded border border-border bg-panel/30 p-4">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h3 className="text-sm font-semibold">
          Why {PROFILE_LABEL[cell.risk_profile]} · {cell.timeframe} is
        </h3>
        <DirectionBadge direction={cell.direction} />
        <span className={`font-mono text-sm ${scoreColor(cell.score)}`}>score {sign(cell.score)}</span>
        <span className="text-xs text-gray-400">confidence {(cell.confidence * 100).toFixed(0)}%</span>
      </div>

      {!cell.filter_passed ? (
        <div className="rounded border border-warn/40 bg-warn/10 p-3 text-sm text-warn">
          Excluded from this profile before scoring: {cell.filter_reason}.
        </div>
      ) : (
        <>
          <p className="mb-2 text-xs text-gray-500">
            The score is a weighted average of what each module says. A module&apos;s weight = how much the{" "}
            {PROFILE_LABEL[cell.risk_profile]} profile relies on it × how relevant it is at {cell.timeframe} × its own confidence.
            &quot;Points&quot; add up to the final score.
          </p>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] text-gray-500">
                <th className="py-1 text-left font-normal">Module</th>
                <th className="py-1 text-right font-normal">Says</th>
                <th className="py-1 text-right font-normal" title="Module's own confidence in its reading">Conf.</th>
                <th className="py-1 text-right font-normal" title="Profile weight × horizon weight">Weight</th>
                <th className="w-1/3 py-1 text-center font-normal">Pushes the verdict</th>
                <th className="py-1 text-right font-normal">Points</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.module} className="border-t border-border/40">
                  <td className="py-1.5 text-gray-200">
                    <a href={`#m-${r.module}`} className="hover:text-accent">{MODULE_INFO[r.module]?.title ?? r.module}</a>
                  </td>
                  <td className={`py-1.5 text-right font-mono ${scoreColor(r.score)}`}>{sign(r.score)}</td>
                  <td className="py-1.5 text-right font-mono text-gray-400">{(r.confidence * 100).toFixed(0)}%</td>
                  <td className="py-1.5 text-right font-mono text-gray-400" title={`profile ${r.cell_w.toFixed(2)} × horizon ${r.horizon_w.toFixed(2)}`}>
                    {(r.cell_w * r.horizon_w).toFixed(3)}
                  </td>
                  <td className="px-3 py-1.5">
                    <div className="relative h-2 w-full">
                      <div className="absolute left-1/2 top-[-2px] h-3 w-px bg-gray-600" />
                      <div
                        className={`absolute top-0 h-2 rounded ${r.points >= 0 ? "bg-accent/80" : "bg-danger/80"}`}
                        style={r.points >= 0
                          ? { left: "50%", width: `${(r.points / maxAbs) * 50}%` }
                          : { right: "50%", width: `${(-r.points / maxAbs) * 50}%` }}
                      />
                    </div>
                  </td>
                  <td className={`py-1.5 text-right font-mono ${scoreColor(r.points)}`}>{sign(r.points, 3)}</td>
                </tr>
              ))}
              <tr className="border-t border-border">
                <td className="py-1.5 font-semibold text-gray-200" colSpan={5}>Final score</td>
                <td className={`py-1.5 text-right font-mono font-semibold ${scoreColor(cell.score)}`}>{sign(cell.score, 3)}</td>
              </tr>
            </tbody>
          </table>
          {excluded.length > 0 && (
            <p className="mt-2 text-[11px] text-gray-500">
              Not counted here: {excluded.map((e) => `${MODULE_INFO[e.name]?.title ?? e.name} (${e.why})`).join(" · ")}.
            </p>
          )}
          {eventNote && <p className="mt-1 text-[11px] text-warn">{eventNote}</p>}
          {cell.confidence < data.thresholds.min_confidence && (
            <p className="mt-1 text-[11px] text-warn">
              Confidence below {(data.thresholds.min_confidence * 100).toFixed(0)}% — reported as AVOID regardless of the score.
            </p>
          )}
        </>
      )}

      <div className="mt-3 border-t border-border/50 pt-2 text-xs text-gray-400">
        {stored ? (
          <>
            The app&apos;s stored suggestion for this cell ({data.stored.date}):{" "}
            <DirectionBadge direction={stored.direction} /> {(stored.confidence * 100).toFixed(0)}% —{" "}
            <Link to={`/suggestion/${stored.id}`} className="text-accent hover:underline">
              {stored.headline ?? "open the full thesis"} →
            </Link>
          </>
        ) : (
          <>No stored suggestion for this cell — the daily run keeps only the strongest candidates per cell.</>
        )}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
function ModuleSections({ data }: { data: FullAnalysis }) {
  const byGroup = GROUP_ORDER.map((g) => ({
    group: g,
    mods: Object.entries(data.modules).filter(([name]) => (MODULE_INFO[name]?.group ?? "Risk") === g),
  })).filter((x) => x.mods.length);
  return (
    <div className="space-y-5">
      <h3 className="text-sm font-semibold">Every indicator, explained</h3>
      {byGroup.map(({ group, mods }) => (
        <section key={group}>
          <h4 className="mb-2 text-[11px] uppercase tracking-wider text-gray-500">{group}</h4>
          <div className="grid gap-3 lg:grid-cols-2">
            {mods.map(([name, m]) => <ModuleCard key={name} name={name} m={m} weights={data.profile_weights} />)}
          </div>
        </section>
      ))}
    </div>
  );
}

function ModuleCard({ name, m, weights }: {
  name: string; m: ModuleResultFull; weights: Record<RiskProfile, Record<string, number>>;
}) {
  const info = MODULE_INFO[name];
  const missing = m.data_quality === "missing" || m.score == null;
  const metrics = info && !missing ? info.metrics(m.raw ?? {}) : [];
  const rules = (m.raw?.rules ?? null) as Record<string, { score: number; state: number; status: string }> | null;
  const dir = m.direction === "bullish" ? "Bullish" : m.direction === "bearish" ? "Bearish" : "Neutral";

  return (
    <article id={`m-${name}`} className={`rounded border border-border bg-panel/30 p-3 ${missing ? "opacity-70" : ""}`}>
      <div className="mb-1 flex items-center gap-2">
        <h5 className="text-sm font-semibold text-gray-100">{info?.title ?? name}</h5>
        {!missing && (
          <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
            m.direction === "bullish" ? "bg-accent/15 text-accent" : m.direction === "bearish" ? "bg-danger/15 text-danger" : "bg-gray-700/40 text-gray-400"
          }`}>{dir}</span>
        )}
        <span className={`ml-auto rounded px-1.5 py-0.5 text-[10px] ${
          m.data_quality === "full" ? "text-gray-500" : m.data_quality === "partial" ? "text-warn" : "text-danger"
        }`}>{m.data_quality === "full" ? "full data" : m.data_quality === "partial" ? "partial data" : "no data"}</span>
      </div>
      {info && <p className="mb-2 text-[11px] leading-4 text-gray-400">{info.what}</p>}

      {!missing && (
        <div className="mb-2 flex items-center gap-3">
          <span className={`w-14 font-mono text-sm ${scoreColor(m.score)}`}>{sign(m.score ?? 0)}</span>
          <div className="flex-1"><ScoreBar value={m.score} /></div>
          <span className="text-[10px] text-gray-500">conf {(m.confidence * 100).toFixed(0)}%</span>
        </div>
      )}

      {m.notes.length > 0 && (
        <ul className="mb-2 space-y-0.5 text-xs text-gray-200">
          {m.notes.map((n, i) => <li key={i} className="flex gap-1.5"><span className="text-gray-600">•</span>{n}</li>)}
        </ul>
      )}
      {missing && m.notes.length === 0 && <p className="mb-2 text-xs text-gray-500">No data available.</p>}

      {metrics.length > 0 && (
        <dl className="mb-2 grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px]">
          {metrics.map((x) => (
            <div key={x.label} className="flex justify-between gap-2 border-b border-border/30 py-0.5" title={x.hint}>
              <dt className="text-gray-500">{x.label}</dt>
              <dd className="text-right font-mono text-gray-200">{x.value}</dd>
            </div>
          ))}
        </dl>
      )}

      {rules && (
        <details className="mb-2" open={name === "technical"}>
          <summary className="cursor-pointer text-[11px] text-gray-400">Rules behind this score ({Object.keys(rules).length})</summary>
          <table className="mt-1 w-full text-[11px]">
            <tbody>
              {Object.entries(rules).map(([id, r]) => (
                <tr key={id} className="border-b border-border/30 align-top">
                  <td className="w-4 py-0.5">
                    <span className={r.state > 0 ? "text-accent" : r.state < 0 ? "text-danger" : "text-gray-600"}>
                      {r.state > 0 ? "▲" : r.state < 0 ? "▼" : "–"}
                    </span>
                  </td>
                  <td className="py-0.5 pr-2 text-gray-300">{r.status}</td>
                  <td className={`w-12 py-0.5 text-right font-mono ${scoreColor(r.score)}`}>{r.score ? sign(r.score) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      {info && <p className="text-[10px] leading-4 text-gray-500"><b className="text-gray-400">How to read:</b> {info.read}</p>}
      <p className="mt-1 text-[10px] text-gray-500">
        Matters most for <span className="text-gray-400">{topHorizons(m.horizon_weights)}</span> · weight by profile:{" "}
        {RISK_PROFILES.map((r) => `${PROFILE_LABEL[r][0]} ${((weights[r]?.[name] ?? 0) * 100).toFixed(0)}%`).join(" · ")}
      </p>
    </article>
  );
}
