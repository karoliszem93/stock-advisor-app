import type { TAData, TARule } from "../../lib/api";

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
}

export default function TaPanel({
  data, loading, error, enabled, onToggle, onSet, showSignals, onShowSignals, labels, onLabels,
}: Props) {
  const rules = data?.rules ?? [];
  const groups = CATEGORY_ORDER.map((cat) => ({ cat, rules: rules.filter((r) => r.category === cat) }))
    .filter((g) => g.rules.length);
  const s = data?.summary;
  const tech = s ? verdict(s.technical.score) : null;
  const mr = s ? verdict(s.mean_reversion.score) : null;
  const rs = s ? verdict(s.relative_strength.score) : null;

  return (
    <aside className="flex w-80 shrink-0 flex-col overflow-hidden border-l border-border bg-panel/30">
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
    </aside>
  );
}
