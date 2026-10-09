import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import type { Time } from "lightweight-charts";
import {
  api,
  RISK_PROFILES,
  TIMEFRAMES,
  type ChartData,
  type ChartInterval,
  type RiskProfile,
  type SuggestionDetail,
  type Timeframe,
} from "../lib/api";
import TradingChart, {
  type ChartLevel,
  type ChartMarker,
  type ChartType,
  type Drawing,
  type DrawMode,
  type Indicators,
  type RangeKey,
  type ScaleMode,
  type TradingChartHandle,
} from "../components/chart/TradingChart";
import SymbolSearch from "../components/chart/SymbolSearch";

const INTERVALS: { key: ChartInterval; label: string }[] = [
  { key: "15m", label: "15m" },
  { key: "1h", label: "1H" },
  { key: "4h", label: "4H" },
  { key: "1d", label: "D" },
  { key: "1wk", label: "W" },
  { key: "1mo", label: "M" },
];

const RANGES: Record<"intraday" | "daily" | "long", RangeKey[]> = {
  intraday: ["1D", "5D", "1M", "All"],
  daily: ["1M", "3M", "6M", "YTD", "1Y", "5Y", "All"],
  long: ["1Y", "5Y", "All"],
};

const CHART_TYPES: { key: ChartType; label: string }[] = [
  { key: "candles", label: "Candles" },
  { key: "hollow", label: "Hollow candles" },
  { key: "heikin", label: "Heikin Ashi" },
  { key: "bars", label: "Bars" },
  { key: "line", label: "Line" },
  { key: "area", label: "Area" },
];

const INDICATOR_LABELS: { key: keyof Indicators; label: string; group: string }[] = [
  { key: "volume", label: "Volume", group: "Overlays" },
  { key: "sma20", label: "SMA 20", group: "Overlays" },
  { key: "sma50", label: "SMA 50", group: "Overlays" },
  { key: "sma200", label: "SMA 200", group: "Overlays" },
  { key: "ema9", label: "EMA 9", group: "Overlays" },
  { key: "ema21", label: "EMA 21", group: "Overlays" },
  { key: "bb", label: "Bollinger Bands (20, 2)", group: "Overlays" },
  { key: "rsi", label: "RSI (14)", group: "Panes" },
  { key: "macd", label: "MACD (12, 26, 9)", group: "Panes" },
];

const DEFAULT_INDICATORS: Indicators = {
  volume: true, sma20: false, sma50: true, sma200: true, ema9: false, ema21: false, bb: false, rsi: false, macd: false,
};

// ---- per-browser preferences (best-effort; the page works without storage) ----
function load<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v ? { ...fallback, ...JSON.parse(v) } : fallback;
  } catch {
    return fallback;
  }
}
function loadRaw<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v ? (JSON.parse(v) as T) : fallback;
  } catch {
    return fallback;
  }
}
function save(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable — preferences just won't persist */
  }
}

/** Intraday bars arrive as UTC seconds; shift them so the axis shows local wall time. */
function toLocalTime(t: number): number {
  return t - new Date(t * 1000).getTimezoneOffset() * 60;
}

function decimalsFor(price: number): number {
  if (price >= 1000) return 2;
  if (price >= 1) return 2;
  if (price >= 0.01) return 4;
  return 6;
}

export default function Chart() {
  const { ticker: routeTicker } = useParams<{ ticker: string }>();
  const navigate = useNavigate();
  const ticker = (routeTicker ?? loadRaw<string>("chart.ticker", "")).toUpperCase();

  const [interval, setIntervalKey] = useState<ChartInterval>(() => loadRaw("chart.interval", "1d"));
  const [chartType, setChartType] = useState<ChartType>(() => loadRaw("chart.type", "candles"));
  const [indicators, setIndicators] = useState<Indicators>(() => load("chart.indicators", DEFAULT_INDICATORS));
  const [scaleMode, setScaleMode] = useState<ScaleMode>("normal");
  const [drawMode, setDrawMode] = useState<DrawMode>("none");
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [showSugg, setShowSugg] = useState<boolean>(() => loadRaw("chart.showSuggestions", true));
  const [risk, setRisk] = useState<RiskProfile>(() => loadRaw("chart.risk", "balanced"));
  const [tf, setTf] = useState<Timeframe>(() => loadRaw("chart.tf", "1m"));
  const [data, setData] = useState<ChartData | null>(null);
  const [suggestions, setSuggestions] = useState<SuggestionDetail[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [indMenu, setIndMenu] = useState(false);
  const chart = useRef<TradingChartHandle>(null);
  const wrap = useRef<HTMLDivElement>(null);

  // default symbol: first watchlist item
  useEffect(() => {
    if (ticker) return;
    api.chart.symbols().then((s) => s[0] && navigate(`/chart/${s[0].symbol}`, { replace: true })).catch(() => {});
  }, [ticker, navigate]);

  useEffect(() => save("chart.interval", interval), [interval]);
  useEffect(() => save("chart.type", chartType), [chartType]);
  useEffect(() => save("chart.indicators", indicators), [indicators]);
  useEffect(() => save("chart.showSuggestions", showSugg), [showSugg]);
  useEffect(() => save("chart.risk", risk), [risk]);
  useEffect(() => save("chart.tf", tf), [tf]);
  useEffect(() => {
    if (ticker) save("chart.ticker", ticker);
  }, [ticker]);

  // drawings are kept per symbol + interval kind (intraday times differ from daily ones)
  const intraday = interval === "15m" || interval === "1h" || interval === "4h";
  const drawingsKey = `chart.drawings.${ticker}.${intraday ? "intraday" : "daily"}`;
  useEffect(() => setDrawings(loadRaw<Drawing[]>(drawingsKey, [])), [drawingsKey]);
  const updateDrawings = useCallback(
    (next: Drawing[]) => {
      setDrawings(next);
      save(drawingsKey, next);
    },
    [drawingsKey],
  );
  const addDrawing = useCallback(
    (d: Drawing) => {
      setDrawings((prev) => {
        const next = [...prev, d];
        save(drawingsKey, next);
        return next;
      });
      if (d.type === "hline") setDrawMode("none");
      if (d.type === "trend") setDrawMode("none");
    },
    [drawingsKey],
  );

  // load bars
  useEffect(() => {
    if (!ticker) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.chart
      .bars(ticker, interval)
      .then((d) => {
        if (cancelled) return;
        const bars = intraday ? d.bars.map((b) => ({ ...b, time: toLocalTime(b.time as number) })) : d.bars;
        setData({ ...d, bars });
      })
      .catch((e) => {
        if (!cancelled) {
          setData(null);
          setError(String(e).includes("404") ? `No price data for ${ticker}.` : String(e));
        }
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [ticker, interval, intraday]);

  // load the app's suggestions for this symbol
  useEffect(() => {
    if (!ticker) return;
    api.suggestions.byTicker(ticker).then(setSuggestions).catch(() => setSuggestions([]));
  }, [ticker]);

  // Esc leaves drawing mode
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawMode("none");
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const bars = data?.bars ?? [];
  const last = bars[bars.length - 1];
  const priceDecimals = last ? decimalsFor(last.close) : 2;

  // suggestion markers for the selected risk profile + timeframe (daily+ charts)
  const cellSuggestions = useMemo(
    () => suggestions.filter((s) => s.risk_profile === risk && s.timeframe === tf),
    [suggestions, risk, tf],
  );
  const markers = useMemo<ChartMarker[]>(() => {
    if (!showSugg || intraday || !bars.length) return [];
    const times = bars.map((b) => b.time as string);
    const out: ChartMarker[] = [];
    for (const s of cellSuggestions) {
      // snap to the bar containing the suggestion date (weekly/monthly bars start earlier)
      let i = times.length - 1;
      while (i >= 0 && times[i] > s.suggestion_date) i--;
      if (i < 0) continue;
      out.push({ time: times[i] as Time, direction: s.direction, text: s.direction === "buy" ? "B" : s.direction === "sell_short" ? "S" : "" });
    }
    // one marker per bar, ascending by time (library requirement)
    const byTime = new Map(out.map((m) => [String(m.time), m]));
    return [...byTime.values()].sort((a, b) => String(a.time).localeCompare(String(b.time)));
  }, [showSugg, intraday, bars, cellSuggestions]);

  // entry / stop / target of the latest suggestion in that cell
  const latest = cellSuggestions[0];
  const levels = useMemo<ChartLevel[]>(() => {
    if (!showSugg || !latest) return [];
    const p = latest.rationale?.prices;
    const native = p ?? (data?.currency === "EUR" && latest.entry_price_eur != null
      ? { entry: latest.entry_price_eur, stop_loss: latest.stop_loss_eur!, target: latest.target_price_eur! }
      : null);
    if (!native) return [];
    const tag = `${latest.direction === "sell_short" ? "Short" : latest.direction === "buy" ? "Buy" : "Avoid"} ${tf}`;
    return [
      { price: native.entry, kind: "entry", title: `${tag} entry` },
      { price: native.stop_loss, kind: "stop", title: "Stop" },
      { price: native.target, kind: "target", title: "Target" },
    ];
  }, [showSugg, latest, data?.currency, tf]);
  const levelsMissing = showSugg && latest && levels.length === 0;

  function screenshot() {
    const canvas = chart.current?.screenshot();
    if (!canvas) return;
    const a = document.createElement("a");
    a.href = canvas.toDataURL("image/png");
    a.download = `${ticker}-${interval}-${new Date().toISOString().slice(0, 10)}.png`;
    a.click();
  }

  function fullscreen() {
    if (document.fullscreenElement) document.exitFullscreen();
    else wrap.current?.requestFullscreen();
  }

  const btn = (on: boolean) =>
    `px-2 py-1 rounded text-xs ${on ? "bg-accent/15 text-accent border border-accent/40" : "text-gray-300 hover:bg-panel border border-transparent"}`;
  const rangeSet = intraday ? RANGES.intraday : interval === "1d" ? RANGES.daily : RANGES.long;

  return (
    <div ref={wrap} className="flex h-[calc(100vh-3rem)] flex-col bg-bg">
      {/* ---- top toolbar ---- */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border pb-2">
        <SymbolSearch value={ticker} onSelect={(s) => navigate(`/chart/${encodeURIComponent(s)}`)} />
        <div className="min-w-0 max-w-xs truncate text-sm text-gray-400" title={data?.name ?? ""}>
          {data?.name}
          {data?.currency && <span className="ml-2 text-xs text-gray-500">{data.exchange} · {data.currency}</span>}
        </div>

        <div className="mx-1 h-5 w-px bg-border" />
        {INTERVALS.map((i) => (
          <button key={i.key} className={btn(interval === i.key)} onClick={() => setIntervalKey(i.key)}>
            {i.label}
          </button>
        ))}

        <div className="mx-1 h-5 w-px bg-border" />
        <select
          value={chartType}
          onChange={(e) => setChartType(e.target.value as ChartType)}
          className="rounded border border-border bg-bg px-2 py-1 text-xs"
        >
          {CHART_TYPES.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
        </select>

        <div className="relative">
          <button className={btn(indMenu)} onClick={() => setIndMenu((v) => !v)}>
            Indicators ▾
          </button>
          {indMenu && (
            <div
              className="absolute left-0 top-full z-30 mt-1 w-56 rounded border border-border bg-panel p-2 shadow-lg"
              onMouseLeave={() => setIndMenu(false)}
            >
              {["Overlays", "Panes"].map((g) => (
                <div key={g} className="mb-1">
                  <div className="px-1 pb-1 text-[10px] uppercase tracking-wider text-gray-500">{g}</div>
                  {INDICATOR_LABELS.filter((i) => i.group === g).map((i) => (
                    <label key={i.key} className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-xs hover:bg-bg">
                      <input
                        type="checkbox"
                        checked={indicators[i.key]}
                        onChange={(e) => setIndicators((s) => ({ ...s, [i.key]: e.target.checked }))}
                      />
                      {i.label}
                    </label>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="mx-1 h-5 w-px bg-border" />
        <button className={btn(drawMode === "hline")} title="Horizontal line" onClick={() => setDrawMode(drawMode === "hline" ? "none" : "hline")}>
          ― H-line
        </button>
        <button className={btn(drawMode === "trend")} title="Trend line (two clicks)" onClick={() => setDrawMode(drawMode === "trend" ? "none" : "trend")}>
          ╱ Trend
        </button>
        <button className={btn(false)} title="Undo last drawing" disabled={!drawings.length} onClick={() => updateDrawings(drawings.slice(0, -1))}>
          ↶ Undo
        </button>
        <button className={btn(false)} title="Remove all drawings on this symbol" disabled={!drawings.length} onClick={() => updateDrawings([])}>
          Clear
        </button>

        <div className="mx-1 h-5 w-px bg-border" />
        <label className="flex items-center gap-1 text-xs text-gray-300">
          <input type="checkbox" checked={showSugg} onChange={(e) => setShowSugg(e.target.checked)} />
          Suggestions
        </label>
        {showSugg && (
          <>
            <select value={risk} onChange={(e) => setRisk(e.target.value as RiskProfile)} className="rounded border border-border bg-bg px-1 py-1 text-xs">
              {RISK_PROFILES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
            <select value={tf} onChange={(e) => setTf(e.target.value as Timeframe)} className="rounded border border-border bg-bg px-1 py-1 text-xs">
              {TIMEFRAMES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </>
        )}

        <div className="ml-auto flex items-center gap-1">
          <button className={btn(false)} title="Fit all data" onClick={() => chart.current?.fit()}>⤢ Fit</button>
          <button className={btn(false)} title="Save chart as PNG" onClick={screenshot}>📷</button>
          <button className={btn(false)} title="Fullscreen" onClick={fullscreen}>⛶</button>
        </div>
      </div>

      {/* ---- chart ---- */}
      <div className="relative min-h-0 flex-1">
        {error ? (
          <div className="m-4 rounded border border-danger/40 bg-danger/10 p-3 text-sm">{error}</div>
        ) : (
          <TradingChart
            ref={chart}
            bars={bars}
            seriesKey={`${ticker}:${interval}`}
            chartType={chartType}
            indicators={indicators}
            scaleMode={scaleMode}
            drawings={drawings}
            drawMode={drawMode}
            onAddDrawing={addDrawing}
            markers={markers}
            levels={levels}
            priceDecimals={priceDecimals}
          />
        )}
        {loading && (
          <div className="absolute right-3 top-2 z-10 text-xs text-gray-500">Loading…</div>
        )}
      </div>

      {/* ---- bottom bar ---- */}
      <div className="flex flex-wrap items-center gap-1 border-t border-border pt-2 text-xs">
        {rangeSet.map((r) => (
          <button key={r} className={btn(false)} onClick={() => chart.current?.setRange(r)}>{r}</button>
        ))}
        <div className="mx-1 h-4 w-px bg-border" />
        <button className={btn(scaleMode === "log")} onClick={() => setScaleMode(scaleMode === "log" ? "normal" : "log")}>log</button>
        <button className={btn(scaleMode === "percent")} onClick={() => setScaleMode(scaleMode === "percent" ? "normal" : "percent")}>%</button>
        <span className="ml-auto text-gray-500">
          {levelsMissing && "Levels shown for suggestions made from 2026-10-09 on (or EUR-priced). "}
          {showSugg && intraday && "Suggestion markers show on D/W/M charts. "}
          {bars.length > 0 && `${bars.length.toLocaleString()} bars`}
        </span>
      </div>
    </div>
  );
}
