import { useEffect, useMemo, useState } from "react";
import { api, type AnalogResponse, type AnalogView } from "../lib/api";

const pct = (v: number | null | undefined, d = 1) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(d)}%`);
const pct0 = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(0)}%`);
const tone = (v: number | null | undefined) => (v == null ? "text-gray-600" : v > 0 ? "text-accent" : v < 0 ? "text-danger" : "text-gray-400");

function fmtFeature(v: number | null | undefined, fmt: string): string {
  if (v == null) return "—";
  switch (fmt) {
    case "pct": return pct(v);
    case "pct0": return pct0(v);
    case "num0": return v.toFixed(0);
    case "num1": return v.toFixed(1);
    case "num2": return v.toFixed(2);
    case "trend": return v > 0 ? "up" : v < 0 ? "down" : "mixed";
    default: return String(v);
  }
}

const TONE_BOX: Record<string, string> = {
  better: "border-accent/40 bg-accent/10",
  worse: "border-danger/40 bg-danger/10",
  similar: "border-border bg-panel/40",
  inconclusive: "border-border bg-panel/40",
};
const TONE_WORD: Record<string, string> = {
  better: "Historically favourable",
  worse: "Historically unfavourable",
  similar: "No edge either way",
  inconclusive: "Inconclusive",
};

/** Paths of the 60 bars after each match, rebased to 100 at the match. */
function FanChart({ view }: { view: AnalogView }) {
  const W = 360;
  const H = 150;
  const pad = { l: 30, r: 8, t: 8, b: 16 };
  const paths = view.paths.filter((p) => p.values.length > 1);
  const len = Math.max(...paths.map((p) => p.values.length), 2);
  const all = paths.flatMap((p) => p.values);
  const lo = Math.min(0.9, ...all);
  const hi = Math.max(1.1, ...all);
  const x = (i: number) => pad.l + (i / (len - 1)) * (W - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - (v - lo) / (hi - lo)) * (H - pad.t - pad.b);
  // median path across matches still running at each step
  const median = Array.from({ length: len }, (_, i) => {
    const vals = paths.map((p) => p.values[i]).filter((v) => v != null).sort((a, b) => a - b);
    return vals.length >= 3 ? vals[Math.floor(vals.length / 2)] : null;
  });
  const line = (vals: (number | null)[]) =>
    vals.map((v, i) => (v == null ? "" : `${i === 0 || vals[i - 1] == null ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`)).join("");
  const ticks = [lo, 1, hi].map((v) => Math.round(v * 100) / 100);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="What happened after similar situations">
      {ticks.map((v) => (
        <g key={v}>
          <line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} stroke={v === 1 ? "#4b5563" : "#1f2430"} strokeDasharray={v === 1 ? "3 3" : undefined} />
          <text x={pad.l - 4} y={y(v) + 3} textAnchor="end" fontSize="9" fill="#6b7280">{pct(v - 1, 0)}</text>
        </g>
      ))}
      {[0, 5, 20, 60].filter((b) => b < len).map((b) => (
        <text key={b} x={x(b)} y={H - 3} textAnchor="middle" fontSize="9" fill="#6b7280">{b === 0 ? "then" : `+${b}`}</text>
      ))}
      {paths.map((p) => (
        <path key={p.time} d={line(p.values)} fill="none" strokeWidth="1"
          stroke={p.values[p.values.length - 1] >= 1 ? "rgba(110,231,183,0.35)" : "rgba(248,113,113,0.35)"} />
      ))}
      <path d={line(median)} fill="none" stroke="#e5e7eb" strokeWidth="2" />
    </svg>
  );
}

export default function SimilarSituations({ ticker, onFocus, compact = false }: {
  ticker: string;
  /** jump the chart to a date (only meaningful for the ticker's own history) */
  onFocus?: (time: string) => void;
  compact?: boolean;
}) {
  const [data, setData] = useState<AnalogResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewKey, setViewKey] = useState<"own" | "proxy" | null>(null);

  useEffect(() => {
    if (!ticker) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    api.chart.analogs(ticker)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setViewKey(d.primary ?? null);
      })
      .catch((e) => !cancelled && setError(String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [ticker]);

  const view = data?.views && viewKey ? data.views[viewKey] : undefined;
  const both = data?.views?.own && data?.views?.proxy;
  const agree = useMemo(() => {
    if (!both) return null;
    const a = data!.views!.own!.verdict.tone;
    const b = data!.views!.proxy!.verdict.tone;
    if (a === "inconclusive" || b === "inconclusive") return null;
    return a === b;
  }, [both, data]);

  if (loading) return <p className="px-3 py-3 text-xs text-gray-500">Searching {ticker}&apos;s history for similar situations…</p>;
  if (error) return <p className="px-3 py-3 text-xs text-danger">{error}</p>;
  if (!data) return null;
  if (!data.available || !view) return <p className="px-3 py-3 text-xs text-gray-500">{data.reason ?? "Not available."}</p>;

  const s = view.summary;
  const pad = compact ? "px-3" : "";
  return (
    <div className={`space-y-3 ${compact ? "py-2" : ""}`}>
      <p className={`${pad} text-[10px] leading-4 text-gray-500`}>
        Finds the past days whose chart situation (trend, momentum, stretch, volatility, range, weekly trend) was closest to
        today&apos;s and shows what happened next. <b className="text-gray-400">Information only — not used in any score.</b>
      </p>

      {/* source toggle */}
      {both && (
        <div className={`${pad} space-y-1`}>
          <div className="flex gap-1 text-[11px]">
            {(["own", "proxy"] as const).map((k) => {
              const v = data.views![k]!;
              return (
                <button
                  key={k}
                  onClick={() => setViewKey(k)}
                  className={`flex-1 rounded border px-2 py-1 text-left ${viewKey === k ? "border-accent bg-accent/10 text-gray-100" : "border-border text-gray-400 hover:bg-panel"}`}
                >
                  <div className="font-medium">{k === "own" ? `${ticker} itself` : v.source.name}</div>
                  <div className="text-[10px] text-gray-500">since {v.history_from.slice(0, 4)} · {v.history_bars.toLocaleString()} days</div>
                </button>
              );
            })}
          </div>
          {agree !== null && (
            <p className={`text-[10px] ${agree ? "text-accent" : "text-warn"}`}>
              {agree ? "✓ Both histories point the same way — a stronger hint." : "⚠ The two histories disagree — treat as inconclusive."}
            </p>
          )}
        </div>
      )}
      {!both && view.source.is_proxy && (
        <p className={`${pad} text-[10px] text-gray-500`}>
          Using the {view.source.name} (since {view.history_from.slice(0, 4)}) — {ticker}&apos;s own history is too short.
        </p>
      )}

      {/* verdict */}
      <div className={`${compact ? "mx-3" : ""} rounded border p-2 text-xs ${TONE_BOX[view.verdict.tone]}`}>
        <div className="mb-0.5 font-semibold text-gray-100">{TONE_WORD[view.verdict.tone]}</div>
        <div className="leading-4 text-gray-300">{view.verdict.text}</div>
      </div>

      {/* outcomes */}
      <div className={pad}>
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-[10px] text-gray-500">
              <th className="py-1 text-left font-normal">After</th>
              <th className="py-1 text-right font-normal" title="Similar situations: % higher · median move">Similar: up · median</th>
              <th className="py-1 text-right font-normal" title="Middle 80% of outcomes">Range</th>
              <th className="py-1 text-right font-normal" title="Any day: % higher · median move">Any day</th>
            </tr>
          </thead>
          <tbody>
            {(["5", "20", "60"] as const).map((h) => {
              const a = s[h].analogs;
              const b = s[h].base;
              const better = a.up != null && b.up != null ? a.up - b.up : null;
              return (
                <tr key={h} className="border-t border-border/40">
                  <td className="py-1 text-gray-300">{h} bars</td>
                  <td className="py-1 text-right font-mono">
                    <span className={better == null ? "" : better >= 0.1 ? "text-accent" : better <= -0.1 ? "text-danger" : "text-gray-200"}>{pct0(a.up)}</span>
                    <span className={tone(a.median)}> · {pct(a.median)}</span>
                    <span className="text-gray-600"> ({a.n})</span>
                  </td>
                  <td className="py-1 text-right font-mono text-gray-400">{pct(a.p10, 0)} … {pct(a.p90, 0)}</td>
                  <td className="py-1 text-right font-mono text-gray-500">{pct0(b.up)} · {pct(b.median)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {s.dip_20.n > 0 && (
          <p className="mt-1 text-[10px] text-gray-500">
            Dip along the way (lowest point within 20 bars): typically <span className="text-gray-300">{pct(s.dip_20.median)}</span>,
            worst <span className="text-danger">{pct(s.dip_20.worst)}</span> — useful for sizing the stop.
          </p>
        )}
      </div>

      {/* fan */}
      <div className={pad}>
        <div className="mb-0.5 text-[10px] text-gray-500">Path over the next 60 bars after each similar situation (white = median)</div>
        <FanChart view={view} />
      </div>

      {/* today's fingerprint */}
      <details className={pad} open={!compact}>
        <summary className="cursor-pointer text-[11px] text-gray-400">Today&apos;s situation (what was matched)</summary>
        <dl className="mt-1 grid grid-cols-2 gap-x-4 text-[11px]">
          {(data.features ?? []).map((f) => (
            <div key={f.key} className="flex justify-between border-b border-border/30 py-0.5">
              <dt className="text-gray-500">{f.label}</dt>
              <dd className="font-mono text-gray-200">{fmtFeature(view.today[f.key], f.fmt)}</dd>
            </div>
          ))}
        </dl>
      </details>

      {/* matches */}
      <div className={pad}>
        <div className="mb-0.5 text-[10px] text-gray-500">
          The {view.matches.length} most similar past situations (each ≥ {view.params.min_gap} days apart)
          {onFocus && !view.source.is_proxy ? " — click to show on the chart" : ""}
        </div>
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-[10px] text-gray-500">
              <th className="py-1 text-left font-normal">Date</th>
              <th className="py-1 text-right font-normal" title="Share of all past days that were less similar">Match</th>
              <th className="py-1 text-right font-normal">+5</th>
              <th className="py-1 text-right font-normal">+20</th>
              <th className="py-1 text-right font-normal">+60</th>
              <th className="py-1 text-right font-normal" title="Lowest point within 20 bars">Dip</th>
            </tr>
          </thead>
          <tbody>
            {view.matches.map((m) => {
              const clickable = onFocus && !view.source.is_proxy;
              return (
                <tr
                  key={m.time}
                  onClick={clickable ? () => onFocus!(m.time) : undefined}
                  className={`border-t border-border/30 ${clickable ? "cursor-pointer hover:bg-bg" : ""}`}
                >
                  <td className="py-0.5 font-mono text-gray-400">{m.time}</td>
                  <td className="py-0.5 text-right font-mono text-gray-500">{(m.similarity * 100).toFixed(1)}%</td>
                  <td className={`py-0.5 text-right font-mono ${tone(m.ret_5)}`}>{m.ret_5 == null ? "…" : pct(m.ret_5)}</td>
                  <td className={`py-0.5 text-right font-mono ${tone(m.ret_20)}`}>{m.ret_20 == null ? "…" : pct(m.ret_20)}</td>
                  <td className={`py-0.5 text-right font-mono ${tone(m.ret_60)}`}>{m.ret_60 == null ? "…" : pct(m.ret_60)}</td>
                  <td className="py-0.5 text-right font-mono text-gray-500">{pct(m.dip_20)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="mt-1 text-[10px] leading-4 text-gray-600">
          Past behaviour in similar setups is a hint, not a forecast. Spread out the dates: matches from very different
          market eras deserve less weight.
        </p>
      </div>
    </div>
  );
}
