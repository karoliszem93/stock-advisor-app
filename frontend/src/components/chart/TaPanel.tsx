import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { FullAnalysis, RiskProfile, TAData, TAEvent, TARule, Timeframe } from "../../lib/api";
import { GROUP_ORDER, MODULE_INFO, PROFILE_LABEL } from "../../lib/moduleInfo";

type Call = "buy" | "sell" | "hold" | "na";
const CALL_STYLE: Record<Call, string> = {
  buy: "bg-[#22c55e]/15 text-[#22c55e] border-[#22c55e]/40",
  sell: "bg-[#f97316]/15 text-[#f97316] border-[#f97316]/40",
  hold: "bg-gray-700/40 text-gray-300 border-gray-600/50",
  na: "text-gray-600 border-gray-700",
};
function CallChip({ call }: { call: Call }) {
  return (
    <span className={`inline-block w-11 shrink-0 rounded border px-1 py-0.5 text-center text-[10px] font-semibold ${CALL_STYLE[call]}`}>
      {call === "na" ? "n/a" : call.toUpperCase()}
    </span>
  );
}

const CATEGORY_ORDER = [
  "Trend", "Momentum", "Volume", "Price levels", "Patterns", "Multi-timeframe", "Relative strength", "Mean reversion",
];

// same thresholds as the backend's direction_from_score / the synthesis layer
function verdict(score: number): { label: string; cls: string } {
  if (score >= 0.10) return { label: "Bullish", cls: "text-[#22c55e]" };
  if (score <= -0.10) return { label: "Bearish", cls: "text-[#f97316]" };
  return { label: "Neutral", cls: "text-gray-400" };
}

function StateChip({ rule }: { rule: TARule }) {
  if (!rule.available) return <span className="text-[10px] text-gray-600">n/a</span>;
  const s = rule.state;
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
        s > 0 ? "bg-[#22c55e]/15 text-[#22c55e]" : s < 0 ? "bg-[#f97316]/15 text-[#f97316]" : "bg-gray-700/40 text-gray-400"
      }`}
    >
      {s > 0 ? "▲ Bull" : s < 0 ? "▼ Bear" : "– Neutral"}
    </span>
  );
}

interface Props {
  data: TAData | null;
  loading: boolean;
  error: string | null;
  enabled: Set<string>;
  onToggle: (id: string) => void;
  onSet: (ids: string[]) => void;
  showSignals: boolean;
  onShowSignals: (v: boolean) => void;
  labels: boolean;
  onLabels: (v: boolean) => void;
  /** jump the chart to a signal */
  onFocus: (time: number | string) => void;
  /** full analysis (all modules) for the "every analysis result" section */
  analysis: FullAnalysis | null;
  analysisLoading: boolean;
  risk: RiskProfile;
  tf: Timeframe;
  ticker: string;
}

const pct = (v: number | null | undefined, digits = 1) =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;

/** Did the move after the signal go the signal's way? */
const worked = (e: TAEvent, v: number | null | undefined) =>
  v == null ? null : e.side === "buy" ? v > 0 : v < 0;

function fmtTime(t: number | string): string {
  // intraday times are already shifted to local wall time, so read them as UTC
  return typeof t === "number" ? new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ") : t;
}

export default function TaPanel({
  data, loading, error, enabled, onToggle, onSet, showSignals, onShowSignals, labels, onLabels, onFocus,
  analysis, analysisLoading, risk, tf, ticker,
}: Props) {
  const [tab, setTab] = useState<"rules" | "signals">("rules");
  const [sideFilter, setSideFilter] = useState<"all" | "buy" | "sell">("all");
  const [onlyShown, setOnlyShown] = useState(false);
  const ruleName = useMemo(() => new Map((data?.rules ?? []).map((r) => [r.id, r.name])), [data]);
  const signals = useMemo(() => {
    const evs = (data?.events ?? []).filter(
      (e) => (!onlyShown || enabled.has(e.rule)) && (sideFilter === "all" || e.side === sideFilter),
    );
    return evs.slice().reverse();
  }, [data, onlyShown, enabled, sideFilter]);
  const rules = data?.rules ?? [];
  const groups = CATEGORY_ORDER.map((cat) => ({ cat, rules: rules.filter((r) => r.category === cat) }))
    .filter((g) => g.rules.length);
  const s = data?.summary;
  const tech = s ? verdict(s.technical.score) : null;
  const mr = s ? verdict(s.mean_reversion.score) : null;
  const rs = s ? verdict(s.relative_strength.score) : null;

  return (
    <aside className="flex w-[25rem] shrink-0 flex-col overflow-hidden border-l border-border bg-panel/30">
      <div className="border-b border-border p-3">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-semibold">Technical rules</h3>
          {loading && <span className="text-[10px] text-gray-500">Loading…</span>}
        </div>
        {error && <div className="text-xs text-danger">{error}</div>}
        {s && tech && mr && rs && (
          <div className="space-y-1 text-xs">
            <div className="flex justify-between">
              <span className="text-gray-400" title="Sum of the trend, momentum, volume, level, pattern and weekly rules × ADX amplifier, damped when it fights the higher-timeframe trend.">
                Technical
              </span>
              <span className={tech.cls}>
                {tech.label} <span className="font-mono">{s.technical.score >= 0 ? "+" : ""}{s.technical.score.toFixed(2)}</span>
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400" title="Z-score and Bollinger Bands: stretched up = bearish, stretched down = bullish. Weighs most on 1–2 week horizons.">
                Mean reversion
              </span>
              <span className={mr.cls}>
                {mr.label} <span className="font-mono">{s.mean_reversion.score >= 0 ? "+" : ""}{s.mean_reversion.score.toFixed(2)}</span>
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400" title="Relative-strength part of the Momentum module (3-month out/under-performance vs the benchmark).">
                Rel. strength{s.relative_strength.benchmark ? ` vs ${s.relative_strength.benchmark}` : ""}
              </span>
              <span className={s.relative_strength.benchmark ? rs.cls : "text-gray-600"}>
                {s.relative_strength.benchmark ? (
                  <>
                    {rs.label} <span className="font-mono">{s.relative_strength.score >= 0 ? "+" : ""}{s.relative_strength.score.toFixed(2)}</span>
                  </>
                ) : "n/a"}
              </span>
            </div>
            {s.technical.htf_conflict && (
              <div className="text-[11px] text-warn">Signals fight the higher-timeframe trend — damped ×0.6.</div>
            )}
            {s.technical.amplifier !== 1 && (
              <div className="text-[11px] text-gray-500">
                ADX {s.technical.amplifier > 1 ? "strong trend: ×1.15" : "no trend: ×0.85"} applied.
              </div>
            )}
            <p className="pt-1 text-[10px] leading-4 text-gray-500">
              Chart rules only, on the selected interval (the daily scoring uses D). The app&apos;s final call also
              weighs fundamentals, news, macro and risk.
            </p>
          </div>
        )}
      </div>

      <div className="flex border-b border-border text-xs">
        {(["rules", "signals"] as const).map((k) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`flex-1 py-1.5 ${tab === k ? "border-b-2 border-accent text-accent" : "text-gray-400 hover:text-gray-200"}`}
          >
            {k === "rules" ? "Rules" : `Signals${data ? ` (${data.events.length})` : ""}`}
          </button>
        ))}
      </div>

      {tab === "signals" && data && (
        <SignalsTab
          data={data}
          signals={signals}
          ruleName={ruleName}
          enabled={enabled}
          onlyShown={onlyShown}
          setOnlyShown={setOnlyShown}
          sideFilter={sideFilter}
          setSideFilter={setSideFilter}
          onFocus={onFocus}
          analysis={analysis}
          analysisLoading={analysisLoading}
          risk={risk}
          tf={tf}
          ticker={ticker}
        />
      )}

      {tab === "rules" && (
      <>
      <div className="flex flex-wrap items-center gap-1 border-b border-border px-3 py-2 text-[11px]">
        <span className="text-gray-500">Show:</span>
        <button className="rounded px-1.5 py-0.5 text-gray-300 hover:bg-bg" onClick={() => onSet(rules.map((r) => r.id))}>all</button>
        <button className="rounded px-1.5 py-0.5 text-gray-300 hover:bg-bg" onClick={() => onSet([])}>none</button>
        <button
          className="rounded px-1.5 py-0.5 text-gray-300 hover:bg-bg"
          title="Show only rules that currently say bullish or bearish"
          onClick={() => onSet(rules.filter((r) => r.state !== 0).map((r) => r.id))}
        >
          active now
        </button>
        <label className="ml-auto flex items-center gap-1 text-gray-400" title="Buy/sell arrows of the shown rules">
          <input type="checkbox" checked={showSignals} onChange={(e) => onShowSignals(e.target.checked)} />
          arrows
        </label>
        <label className="flex items-center gap-1 text-gray-400" title="Write signal names on the chart (otherwise hover a bar: the legend lists its signals)">
          <input type="checkbox" checked={labels} onChange={(e) => onLabels(e.target.checked)} disabled={!showSignals} />
          labels
        </label>
      </div>

      <div className="flex-1 overflow-y-auto">
        {groups.map((g) => (
          <div key={g.cat} className="border-b border-border/60 px-3 py-2">
            <div className="pb-1 text-[10px] uppercase tracking-wider text-gray-500">{g.cat}</div>
            {g.rules.map((r) => (
              <div key={r.id} className={`py-1 ${r.available ? "" : "opacity-50"}`}>
                <label className="flex cursor-pointer items-center gap-2 text-xs" title={r.description}>
                  <input type="checkbox" checked={enabled.has(r.id)} onChange={() => onToggle(r.id)} />
                  <span className="flex-1 truncate">{r.name}</span>
                  {r.score !== 0 && (
                    <span className={`font-mono text-[10px] ${r.score > 0 ? "text-[#22c55e]" : "text-[#f97316]"}`}>
                      {r.score > 0 ? "+" : ""}{r.score.toFixed(2)}
                    </span>
                  )}
                  <StateChip rule={r} />
                </label>
                <div className="pl-5 text-[11px] leading-4 text-gray-400">{r.status}</div>
                <details className="pl-5">
                  <summary className="cursor-pointer text-[10px] text-gray-600 hover:text-gray-400">rule</summary>
                  <div className="text-[10px] leading-4 text-gray-500">{r.description}</div>
                </details>
              </div>
            ))}
          </div>
        ))}
      </div>
      </>
      )}
    </aside>
  );
}

function Section({ title, sub, children, defaultOpen = true }: {
  title: string; sub?: string; children: React.ReactNode; defaultOpen?: boolean;
}) {
  return (
    <details open={defaultOpen} className="border-b border-border">
      <summary className="cursor-pointer select-none bg-panel/60 px-3 py-2 text-xs font-semibold text-gray-200 hover:text-white">
        {title}
        {sub && <span className="ml-2 font-normal text-gray-500">{sub}</span>}
      </summary>
      {children}
    </details>
  );
}

function NowRules({ data }: { data: TAData }) {
  const rows = CATEGORY_ORDER.flatMap((cat) => data.rules.filter((r) => r.category === cat));
  const n = { buy: 0, sell: 0, hold: 0 };
  const call = (r: TARule): Call => (!r.available ? "na" : r.state > 0 ? "buy" : r.state < 0 ? "sell" : "hold");
  rows.forEach((r) => { const c = call(r); if (c !== "na") n[c]++; });
  return (
    <Section title="Chart rules — right now" sub={`${n.buy} buy · ${n.sell} sell · ${n.hold} hold`}>
      <ul className="divide-y divide-border/40">
        {rows.map((r) => (
          <li key={r.id} className="flex gap-2 px-3 py-1.5" title={r.description}>
            <CallChip call={call(r)} />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline gap-2 text-[11px]">
                <span className="truncate text-gray-200">{r.name}</span>
                {r.score !== 0 && (
                  <span className={`ml-auto font-mono text-[10px] ${r.score > 0 ? "text-[#22c55e]" : "text-[#f97316]"}`}>
                    {r.score > 0 ? "+" : ""}{r.score.toFixed(2)}
                  </span>
                )}
              </div>
              <div className="text-[11px] leading-4 text-gray-400">{r.status}</div>
            </div>
          </li>
        ))}
      </ul>
      <p className="px-3 pb-2 text-[10px] text-gray-500">
        BUY/SELL = the rule leans bullish/bearish on the latest bar; HOLD = no signal. Numbers are what each rule adds to the
        technical score (rules leaning one way without a number are context, e.g. MACD above signal with no recent cross).
      </p>
    </Section>
  );
}

function NowAnalysis({ analysis, loading, risk, tf, ticker }: {
  analysis: FullAnalysis | null; loading: boolean; risk: RiskProfile; tf: Timeframe; ticker: string;
}) {
  if (!analysis) {
    return (
      <Section title="Full analysis — right now">
        <p className="px-3 py-2 text-[11px] text-gray-500">{loading ? "Running all analysis modules…" : "Analysis unavailable."}</p>
      </Section>
    );
  }
  const cell = analysis.cells.find((c) => c.risk_profile === risk && c.timeframe === tf);
  const counted = new Map((cell?.contributors ?? []).map((c) => [c.module, c]));
  const weightSum = (cell?.contributors ?? []).reduce((a, c) => a + c.cell_w * c.horizon_w * c.confidence, 0);
  const mods = GROUP_ORDER.flatMap((g) =>
    Object.entries(analysis.modules).filter(([name]) => (MODULE_INFO[name]?.group ?? "Risk") === g),
  );
  const callOf = (m: (typeof analysis.modules)[string]): Call =>
    m.score == null || m.data_quality === "missing" ? "na" : m.direction === "bullish" ? "buy" : m.direction === "bearish" ? "sell" : "hold";
  const final: Call = !cell ? "na" : cell.direction === "buy" ? "buy" : cell.direction === "sell_short" ? "sell" : "hold";
  return (
    <Section title="Full analysis — right now" sub="technical + fundamentals + sentiment + macro + risk">
      {cell && (
        <div className="border-b border-border/60 px-3 py-2 text-[11px]">
          <div className="flex items-center gap-2">
            <CallChip call={final} />
            <span className="text-gray-200">
              Overall for <b>{PROFILE_LABEL[risk]} · {tf}</b>
            </span>
            <span className="ml-auto font-mono text-gray-300">
              {cell.score >= 0 ? "+" : ""}{cell.score.toFixed(2)} · {(cell.confidence * 100).toFixed(0)}%
            </span>
          </div>
          <p className="mt-1 leading-4 text-gray-400">
            {!cell.filter_passed
              ? `Excluded from this profile: ${cell.filter_reason}.`
              : `Weighted blend of the modules below (change profile / horizon in the toolbar). BUY needs ≥ +${analysis.thresholds.direction.toFixed(2)}, SELL ≤ −${analysis.thresholds.direction.toFixed(2)}, otherwise HOLD (shown as AVOID elsewhere).`}
          </p>
        </div>
      )}
      <ul className="divide-y divide-border/40">
        {mods.map(([name, m]) => {
          const c = counted.get(name);
          const points = c && weightSum ? c.weighted_contrib / weightSum : null;
          const why = m.notes.length ? m.notes : [m.data_quality === "missing" ? "No data available." : "Nothing notable — neutral reading."];
          return (
            <li key={name} className="flex gap-2 px-3 py-1.5">
              <CallChip call={callOf(m)} />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2 text-[11px]">
                  <span className="truncate text-gray-200">{MODULE_INFO[name]?.title ?? name}</span>
                  <span className="text-[10px] text-gray-600">{MODULE_INFO[name]?.group}</span>
                  <span
                    className="ml-auto whitespace-nowrap font-mono text-[10px] text-gray-400"
                    title="Module score · points it adds to the overall verdict for the selected profile and horizon"
                  >
                    {m.score != null ? `${m.score >= 0 ? "+" : ""}${m.score.toFixed(2)}` : "—"}
                    {points != null ? (
                      <span className={points >= 0 ? "text-[#22c55e]" : "text-[#f97316]"}> → {points >= 0 ? "+" : ""}{points.toFixed(3)}</span>
                    ) : <span className="text-gray-600"> → not counted</span>}
                  </span>
                </div>
                <ul className="text-[11px] leading-4 text-gray-400">
                  {why.slice(0, 4).map((n, i) => <li key={i}>{n}</li>)}
                </ul>
              </div>
            </li>
          );
        })}
      </ul>
      <p className="px-3 pb-2 text-[10px] text-gray-500">
        &quot;→&quot; = points added to the overall score above. Full numbers and explanations on the{" "}
        <Link to={`/analysis/${encodeURIComponent(ticker)}`} className="text-accent hover:underline">Analysis page</Link>.
      </p>
    </Section>
  );
}

function SignalsTab({
  data, signals, ruleName, enabled, onlyShown, setOnlyShown, sideFilter, setSideFilter, onFocus,
  analysis, analysisLoading, risk, tf, ticker,
}: {
  data: TAData;
  signals: TAEvent[];
  ruleName: Map<string, string>;
  enabled: Set<string>;
  onlyShown: boolean;
  setOnlyShown: (v: boolean) => void;
  sideFilter: "all" | "buy" | "sell";
  setSideFilter: (v: "all" | "buy" | "sell") => void;
  onFocus: (time: number | string) => void;
  analysis: FullAnalysis | null;
  analysisLoading: boolean;
  risk: RiskProfile;
  tf: Timeframe;
  ticker: string;
}) {
  const base = data.base_rate;
  const rules = data.rules.filter((r) => r.stats && (r.stats.buy.n + r.stats.sell.n) > 0 && (!onlyShown || enabled.has(r.id)));
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <NowRules data={data} />
      <NowAnalysis analysis={analysis} loading={analysisLoading} risk={risk} tf={tf} ticker={ticker} />

      <Section title="Signal history & track record" sub={`${data.events.length} past signals`} defaultOpen={false}>
      <div className="border-b border-border px-3 py-2 text-[10px] leading-4 text-gray-500">
        How each rule&apos;s signals played out on this chart. <b className="text-gray-400">+5 / +20</b> = price change 5 and 20
        bars after the signal. A buy &quot;worked&quot; if price rose, a sell if it fell. Compare with the base rate: a rule
        is only useful if it beats how often price rose anyway.
      </div>

      {/* track record per rule */}
      <div className="border-b border-border px-3 py-2">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-[10px] text-gray-500">
              <th className="pb-1 text-left font-normal">Rule</th>
              <th className="pb-1 text-right font-normal" colSpan={2} title="Buy signals: % that rose within 20 bars (count) · average 20-bar move">▲ Buys: worked · avg</th>
              <th className="pb-1 pl-2 text-right font-normal" colSpan={2} title="Sell signals: % that fell within 20 bars (count) · average 20-bar move">▼ Sells: worked · avg</th>
            </tr>
          </thead>
          <tbody>
            {base?.up_20 != null && (
              <tr className="whitespace-nowrap border-b border-border/50 text-gray-400">
                <td className="py-1" title="Any bar, no signal: how often price was higher / lower 20 bars later">Base rate (any bar)</td>
                <td className="py-1 text-right font-mono">{(base.up_20 * 100).toFixed(0)}%</td>
                <td className="py-1 pl-1.5 text-right font-mono">{pct(base.avg_20)}</td>
                <td className="py-1 pl-2 text-right font-mono">{((1 - base.up_20) * 100).toFixed(0)}%</td>
                <td className="py-1 pl-1.5 text-right font-mono">{pct(base.avg_20 != null ? -base.avg_20 : null)}</td>
              </tr>
            )}
            {rules.map((r) => {
              const b = r.stats!.buy;
              const s = r.stats!.sell;
              const beatB = b.win_20 != null && base?.up_20 != null ? b.win_20 > base.up_20 : null;
              const beatS = s.win_20 != null && base?.up_20 != null ? s.win_20 > 1 - base.up_20 : null;
              const cells = (n: number, win: number | undefined, avg: number | undefined, beat: boolean | null, first: boolean) =>
                n === 0 ? (
                  <>
                    <td className={`py-1 text-right text-gray-600 ${first ? "" : "pl-2"}`}>—</td>
                    <td />
                  </>
                ) : (
                  <>
                    <td className={`py-1 text-right font-mono ${first ? "" : "pl-2"}`}>
                      <span className={beat == null ? "text-gray-400" : beat ? "text-[#22c55e]" : "text-[#f97316]"}>
                        {win == null ? "—" : `${(win * 100).toFixed(0)}%`}
                      </span>
                      <span className="text-gray-600"> ({n})</span>
                    </td>
                    <td className="py-1 pl-1.5 text-right font-mono text-gray-400">{pct(avg)}</td>
                  </>
                );
              return (
                <tr key={r.id} className="whitespace-nowrap border-b border-border/30">
                  <td className="max-w-[9rem] truncate py-1 text-gray-300" title={r.name}>{r.name}</td>
                  {cells(b.n, b.win_20, b.avg_20, beatB, true)}
                  {cells(s.n, s.win_20, s.avg_20, beatS, false)}
                </tr>
              );
            })}
          </tbody>
        </table>
        <div className="pt-1 text-[10px] text-gray-600">
          Green = better than the base rate, orange = worse. Last 2,000 bars; past results don&apos;t guarantee future ones.
        </div>
      </div>

      {/* filters */}
      <div className="flex items-center gap-1 border-b border-border px-3 py-1.5 text-[11px]">
        {(["all", "buy", "sell"] as const).map((k) => (
          <button
            key={k}
            onClick={() => setSideFilter(k)}
            className={`rounded px-1.5 py-0.5 ${sideFilter === k ? "bg-bg text-gray-100" : "text-gray-400 hover:bg-bg"}`}
          >
            {k}
          </button>
        ))}
        <label className="ml-auto flex items-center gap-1 text-gray-400" title="Only signals of the rules ticked on the Rules tab">
          <input type="checkbox" checked={onlyShown} onChange={(e) => setOnlyShown(e.target.checked)} />
          shown rules only
        </label>
      </div>

      {/* every signal, newest first */}
      <div>
        {signals.length === 0 ? (
          <div className="p-3 text-xs text-gray-500">
            No signals. {onlyShown ? "Tick rules on the Rules tab, or untick “shown rules only”." : ""}
          </div>
        ) : (
          <table className="w-full text-[11px]">
            <thead className="bg-panel text-[10px] text-gray-500">
              <tr>
                <th className="px-3 py-1 text-left font-normal">Date</th>
                <th className="py-1 text-left font-normal">Signal</th>
                <th className="py-1 text-right font-normal">+5</th>
                <th className="px-3 py-1 text-right font-normal">+20</th>
              </tr>
            </thead>
            <tbody>
              {signals.slice(0, 500).map((e, i) => {
                const w5 = worked(e, e.ret_5);
                const w20 = worked(e, e.ret_20);
                return (
                  <tr
                    key={i}
                    onClick={() => onFocus(e.time)}
                    className="cursor-pointer border-b border-border/30 hover:bg-bg"
                    title={`${ruleName.get(e.rule) ?? e.rule} — click to show on the chart`}
                  >
                    <td className="whitespace-nowrap px-3 py-1 font-mono text-gray-400">{fmtTime(e.time)}</td>
                    <td className="max-w-[11rem] truncate py-1">
                      <span className={e.side === "buy" ? "text-[#22c55e]" : "text-[#f97316]"}>{e.side === "buy" ? "▲" : "▼"}</span>{" "}
                      <span className="text-gray-200">{e.label}</span>
                      {e.price != null && <span className="text-gray-500"> @ {e.price.toFixed(2)}</span>}
                    </td>
                    <td className={`py-1 text-right font-mono ${w5 == null ? "text-gray-600" : w5 ? "text-[#22c55e]" : "text-[#f97316]"}`}>
                      {e.ret_5 === null ? "…" : pct(e.ret_5)}
                    </td>
                    <td className={`px-3 py-1 text-right font-mono ${w20 == null ? "text-gray-600" : w20 ? "text-[#22c55e]" : "text-[#f97316]"}`}>
                      {e.ret_20 === null ? "…" : pct(e.ret_20)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      </Section>
    </div>
  );
}
