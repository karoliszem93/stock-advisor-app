import { useMemo, useState } from "react";
import type { TAData, TAEvent, TARule } from "../../lib/api";

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
}: Props) {
  const [tab, setTab] = useState<"rules" | "signals">("rules");
  const [sideFilter, setSideFilter] = useState<"all" | "buy" | "sell">("all");
  const [onlyShown, setOnlyShown] = useState(true);
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

function SignalsTab({
  data, signals, ruleName, enabled, onlyShown, setOnlyShown, sideFilter, setSideFilter, onFocus,
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
}) {
  const base = data.base_rate;
  const rules = data.rules.filter((r) => r.stats && (r.stats.buy.n + r.stats.sell.n) > 0 && (!onlyShown || enabled.has(r.id)));
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-border px-3 py-2 text-[10px] leading-4 text-gray-500">
        How each rule&apos;s signals played out on this chart. <b className="text-gray-400">+5 / +20</b> = price change 5 and 20
        bars after the signal. A buy &quot;worked&quot; if price rose, a sell if it fell. Compare with the base rate: a rule
        is only useful if it beats how often price rose anyway.
      </div>

      {/* track record per rule */}
      <div className="max-h-[45%] overflow-y-auto border-b border-border px-3 py-2">
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
      <div className="flex-1 overflow-y-auto">
        {signals.length === 0 ? (
          <div className="p-3 text-xs text-gray-500">
            No signals. {onlyShown ? "Tick rules on the Rules tab, or untick “shown rules only”." : ""}
          </div>
        ) : (
          <table className="w-full text-[11px]">
            <thead className="sticky top-0 bg-panel text-[10px] text-gray-500">
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
    </div>
  );
}
