import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import {
  AreaSeries,
  BarSeries,
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  PriceScaleMode,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type MouseEventParams,
  type SeriesMarker,
  type SeriesType,
  type Time,
} from "lightweight-charts";
import { bollinger, ema, heikinAshi, macd, rsi, sma, type Bar, type Series } from "../../lib/indicators";
import type { TAOverlay } from "../../lib/api";

export type ChartType = "candles" | "hollow" | "heikin" | "bars" | "line" | "area";
export type ScaleMode = "normal" | "log" | "percent";
export type DrawMode = "none" | "hline" | "trend";
export type RangeKey = "1D" | "5D" | "1M" | "3M" | "6M" | "YTD" | "1Y" | "5Y" | "All";

export interface Indicators {
  volume: boolean;
  sma20: boolean;
  sma50: boolean;
  sma200: boolean;
  ema9: boolean;
  ema21: boolean;
  bb: boolean;
  rsi: boolean;
  macd: boolean;
}

export type Drawing =
  | { type: "hline"; price: number }
  | { type: "trend"; p1: { time: Time; price: number }; p2: { time: Time; price: number } };

export interface ChartMarker {
  time: Time;
  side: "buy" | "sell" | "neutral";
  text: string;
  /** "app" = the app's own suggestion; "ta" = a technical-analysis rule signal */
  source: "app" | "ta";
}

export interface ChartLevel {
  price: number;
  kind: "entry" | "stop" | "target";
  title: string;
}

/** A rule overlay plus the name of the rule it belongs to (for the legend). */
export type NamedOverlay = TAOverlay & { rule?: string };

export interface TradingChartHandle {
  setRange: (range: RangeKey) => void;
  fit: () => void;
  screenshot: () => HTMLCanvasElement | null;
  /** scroll to a bar and put the crosshair on it (legend then shows that bar) */
  focus: (time: Time) => void;
}

interface Props {
  bars: Bar[];
  /** identity of the series (ticker + interval) — zoom resets only when this changes */
  seriesKey: string;
  chartType: ChartType;
  indicators: Indicators;
  scaleMode: ScaleMode;
  drawings: Drawing[];
  drawMode: DrawMode;
  onAddDrawing: (d: Drawing) => void;
  markers: ChartMarker[];
  levels: ChartLevel[];
  /** overlays of the enabled technical-analysis rules */
  taOverlays: NamedOverlay[];
  /** draw marker text on the chart (otherwise names show in the legend on hover) */
  markerLabels: boolean;
  priceDecimals: number;
}

const C = {
  bg: "#0b0d12",
  grid: "#161a23",
  border: "#232733",
  text: "#9ca3af",
  up: "#26a69a",
  down: "#ef5350",
  accent: "#6ee7b7",
  warn: "#fbbf24",
  danger: "#f87171",
  drawing: "#60a5fa",
  taBuy: "#22c55e",
  taSell: "#f97316",
};

const OVERLAYS: { key: keyof Indicators; label: string; color: string; calc: (c: number[]) => Series }[] = [
  { key: "sma20", label: "SMA 20", color: "#f59e0b", calc: (c) => sma(c, 20) },
  { key: "sma50", label: "SMA 50", color: "#3b82f6", calc: (c) => sma(c, 50) },
  { key: "sma200", label: "SMA 200", color: "#e879f9", calc: (c) => sma(c, 200) },
  { key: "ema9", label: "EMA 9", color: "#22d3ee", calc: (c) => ema(c, 9) },
  { key: "ema21", label: "EMA 21", color: "#a3e635", calc: (c) => ema(c, 21) },
];

/** Title + plain-language reading guide for each sub-pane a rule can open. */
const PANE_INFO: Record<string, { title: string; note: string }> = {
  rsi: {
    title: "RSI (14)",
    note: "Momentum 0–100. Guides 70/55/45/30: below 30 oversold · 30–45 in an uptrend = pullback buy zone · 55–70 in a downtrend = bounce sell zone · above 70 overbought.",
  },
  macd: {
    title: "MACD (12, 26, 9)",
    note: "Blue = MACD line, orange = signal line, bars = their difference. Blue crossing above orange = bullish, below = bearish.",
  },
  adx: {
    title: "ADX (14)",
    note: "White = trend strength (above the dashed 25 = strong trend). Green +DI above red −DI = buyers in control, the reverse = sellers.",
  },
  obv: {
    title: "On-balance volume",
    note: "Running total of volume (added on up days, subtracted on down days) and its 20-EMA. Rising with price = volume confirms the move.",
  },
  rs: {
    title: "Relative strength",
    note: "Price ÷ benchmark, rebased to 100. Above its dashed 50-bar average = outperforming the market, below = lagging.",
  },
  z: {
    title: "Z-score (20)",
    note: "Distance from the 20-bar average in standard deviations. Beyond ±2 = stretched; mean reversion expects a snap back.",
  },
  volume: {
    title: "Volume",
    note: "Bright bars = unusual volume (≥ 2.5× the 20-bar average, orange line). Up-bar spikes = buying pressure, down-bar spikes = selling.",
  },
};

const RANGE_DAYS: Record<Exclude<RangeKey, "YTD" | "All">, number> = {
  "1D": 1, "5D": 5, "1M": 31, "3M": 92, "6M": 183, "1Y": 365, "5Y": 1826,
};

function lineData(bars: Bar[], values: Series) {
  const out: { time: Time; value: number }[] = [];
  values.forEach((v, i) => {
    if (v != null && Number.isFinite(v)) out.push({ time: bars[i].time as Time, value: v });
  });
  return out;
}

function timeToMs(t: Time): number {
  return typeof t === "number" ? t * 1000 : new Date(t as string).getTime();
}

function fmtVol(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return String(Math.round(v));
}

// ---- legend model ----
type Swatch = "line" | "dashed" | "dotted" | "hist" | "shade" | "level" | "arrow" | "square" | "band";

interface LegendItem {
  label: string;
  color: string;
  swatch: Swatch;
  /** series whose value at the crosshair is shown next to the label */
  series?: ISeriesApi<SeriesType>;
  last?: number;
  format?: (v: number) => string;
}

interface PaneLegend {
  title?: string;
  note?: string;
  items: LegendItem[];
}

function SwatchIcon({ s, color }: { s: Swatch; color: string }) {
  if (s === "arrow") return <span style={{ color }} className="text-[9px]">▲▼</span>;
  if (s === "square") return <span className="inline-block h-2 w-2" style={{ background: color }} />;
  if (s === "shade") return <span className="inline-block h-2.5 w-3 rounded-sm" style={{ background: color }} />;
  if (s === "hist") return <span className="inline-block h-2.5 w-1.5" style={{ background: color }} />;
  const style = s === "dashed" || s === "level" ? "dashed" : s === "dotted" ? "dotted" : "solid";
  return <span className="inline-block w-3.5" style={{ borderTop: `2px ${style} ${color}` }} />;
}

const TradingChart = forwardRef<TradingChartHandle, Props>(function TradingChart(props, ref) {
  const {
    bars, seriesKey, chartType, indicators, scaleMode, drawings, drawMode, markers, levels, taOverlays,
    markerLabels, priceDecimals,
  } = props;
  const container = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRefs = useRef<ISeriesApi<SeriesType>[]>([]);
  const mainRef = useRef<ISeriesApi<SeriesType> | null>(null);
  const lastKey = useRef<string>("");
  const pendingTrend = useRef<{ time: Time; price: number } | null>(null);
  const [pending, setPending] = useState(false);
  const drawModeRef = useRef(drawMode);
  const onAddRef = useRef(props.onAddDrawing);
  drawModeRef.current = drawMode;
  onAddRef.current = props.onAddDrawing;

  const [legends, setLegends] = useState<PaneLegend[]>([]);
  const [paneTops, setPaneTops] = useState<number[]>([]);
  const [hoverVals, setHoverVals] = useState<Map<ISeriesApi<SeriesType>, number> | null>(null);
  const [legendOpen, setLegendOpenState] = useState<boolean>(() => {
    try {
      return localStorage.getItem("chart.legendOpen") !== "0";
    } catch {
      return true;
    }
  });
  const setLegendOpen = (open: boolean) => {
    setLegendOpenState(open);
    try {
      localStorage.setItem("chart.legendOpen", open ? "1" : "0");
    } catch {
      /* per-browser preference only */
    }
  };

  // ---- indicator values, computed once per data/config change (also feed the legend) ----
  const computed = useMemo(() => {
    const closes = bars.map((b) => b.close);
    return {
      display: chartType === "heikin" ? heikinAshi(bars) : bars,
      overlays: OVERLAYS.filter((o) => indicators[o.key]).map((o) => ({ ...o, values: o.calc(closes) })),
      bb: indicators.bb ? bollinger(closes, 20, 2) : null,
      rsi: indicators.rsi ? rsi(closes, 14) : null,
      macd: indicators.macd ? macd(closes) : null,
      indexByTime: new Map(bars.map((b, i) => [String(b.time), i])),
    };
  }, [bars, chartType, indicators]);
  const computedRef = useRef(computed);
  computedRef.current = computed;

  const [legendIdx, setLegendIdx] = useState<number | null>(null);
  // bar pinned by focus(); programmatic crosshair events are ignored until the mouse really moves
  const focusLock = useRef<number | null>(null);

  // where each pane starts (for its legend), re-measured on build and resize
  const measurePanes = useCallback(() => {
    const chart = chartRef.current;
    const box = container.current?.getBoundingClientRect();
    if (!chart || !box) return;
    setPaneTops(chart.panes().map((p) => (p.getHTMLElement()?.getBoundingClientRect().top ?? box.top) - box.top));
  }, []);

  // ---- create the chart once ----
  useEffect(() => {
    if (!container.current) return;
    const chart = createChart(container.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: C.bg },
        textColor: C.text,
        fontSize: 11,
        panes: { separatorColor: C.border, separatorHoverColor: "#374151", enableResize: true },
        attributionLogo: true,
      },
      grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: C.border },
      timeScale: { borderColor: C.border, rightOffset: 8, timeVisible: true, secondsVisible: false },
    });
    chartRef.current = chart;

    const onMove = (p: MouseEventParams<Time>) => {
      if (focusLock.current !== null) {
        if (!p.sourceEvent) return; // scroll / setCrosshairPosition, not the user
        focusLock.current = null;
      }
      if (p.time === undefined) {
        setLegendIdx(null);
        setHoverVals(null);
        return;
      }
      setLegendIdx(computedRef.current.indexByTime.get(String(p.time)) ?? null);
      const vals = new Map<ISeriesApi<SeriesType>, number>();
      p.seriesData.forEach((d, s) => {
        const v = (d as { value?: number; close?: number }).value ?? (d as { close?: number }).close;
        if (v != null) vals.set(s, v);
      });
      setHoverVals(vals);
    };
    const onClick = (p: MouseEventParams<Time>) => {
      const mode = drawModeRef.current;
      const main = mainRef.current;
      if (mode === "none" || !main || !p.point) return;
      const price = main.coordinateToPrice(p.point.y);
      if (price == null) return;
      if (mode === "hline") {
        onAddRef.current({ type: "hline", price });
      } else if (mode === "trend" && p.time !== undefined) {
        if (!pendingTrend.current) {
          pendingTrend.current = { time: p.time, price };
          setPending(true);
        } else {
          onAddRef.current({ type: "trend", p1: pendingTrend.current, p2: { time: p.time, price } });
          pendingTrend.current = null;
          setPending(false);
        }
      }
    };
    chart.subscribeCrosshairMove(onMove);
    chart.subscribeClick(onClick);
    const ro = new ResizeObserver(() => measurePanes());
    ro.observe(container.current);
    return () => {
      ro.disconnect();
      chart.unsubscribeCrosshairMove(onMove);
      chart.unsubscribeClick(onClick);
      chart.remove();
      chartRef.current = null;
    };
  }, [measurePanes]);

  // leaving draw mode drops a half-finished trend line
  useEffect(() => {
    if (drawMode !== "trend") {
      pendingTrend.current = null;
      setPending(false);
    }
  }, [drawMode]);

  // ---- (re)build all series whenever data or configuration changes ----
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const keepRange = lastKey.current === seriesKey ? chart.timeScale().getVisibleLogicalRange() : null;

    for (const s of seriesRefs.current) chart.removeSeries(s);
    seriesRefs.current = [];
    while (chart.panes().length > 1) chart.removePane(chart.panes().length - 1);
    if (!bars.length) {
      setLegends([]);
      return;
    }
    // time of day only matters on intraday charts (numeric times)
    chart.applyOptions({ timeScale: { timeVisible: typeof bars[0].time === "number" } });

    const add = <T extends SeriesType>(s: ISeriesApi<T>) => {
      seriesRefs.current.push(s as unknown as ISeriesApi<SeriesType>);
      return s;
    };
    const fmt = { type: "price" as const, precision: priceDecimals, minMove: 1 / 10 ** priceDecimals };
    const pf = (v: number) => v.toFixed(priceDecimals);
    const { display } = computed;

    const legend: PaneLegend[] = [{ items: [] }];
    const reg = (pane: number, item: LegendItem) => {
      while (legend.length <= pane) legend.push({ items: [] });
      legend[pane].items.push(item);
    };
    const lastOf = (data: { value: number }[]) => (data.length ? data[data.length - 1].value : undefined);
    const ruleTag = (rule?: string) => (rule ? ` · ${rule}` : "");

    // higher-timeframe trend shading, added first so it sits under the candles
    for (const ov of taOverlays) {
      if (ov.type !== "background") continue;
      const bg = add(chart.addSeries(HistogramSeries, {
        priceScaleId: "ta-bg", lastValueVisible: false, priceLineVisible: false, priceFormat: { type: "volume" },
      }));
      bg.priceScale().applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false });
      bg.setData(ov.data.map((p) => ({
        time: p.time as Time,
        value: p.value === 0 ? 0 : 1,
        color: p.value > 0 ? "rgba(38,166,154,0.08)" : p.value < 0 ? "rgba(239,83,80,0.08)" : "rgba(0,0,0,0)",
      })));
      reg(0, { label: `Background: green = ${ov.rule ?? "higher-timeframe trend"} up, red = down`, color: "rgba(38,166,154,0.35)", swatch: "shade" });
    }

    // main price series
    let main: ISeriesApi<SeriesType>;
    if (chartType === "line" || chartType === "area") {
      const data = display.map((b) => ({ time: b.time as Time, value: b.close }));
      main = chartType === "line"
        ? add(chart.addSeries(LineSeries, { color: C.drawing, lineWidth: 2, priceFormat: fmt }))
        : add(chart.addSeries(AreaSeries, {
            lineColor: C.drawing, topColor: "rgba(96,165,250,0.35)", bottomColor: "rgba(96,165,250,0.02)",
            lineWidth: 2, priceFormat: fmt,
          }));
      main.setData(data);
    } else if (chartType === "bars") {
      main = add(chart.addSeries(BarSeries, { upColor: C.up, downColor: C.down, priceFormat: fmt }));
      main.setData(display.map((b) => ({ ...b, time: b.time as Time })));
    } else {
      const hollow = chartType === "hollow";
      main = add(chart.addSeries(CandlestickSeries, {
        upColor: hollow ? "rgba(0,0,0,0)" : C.up,
        downColor: C.down,
        borderUpColor: C.up,
        borderDownColor: C.down,
        borderVisible: hollow,
        wickUpColor: C.up,
        wickDownColor: C.down,
        priceFormat: fmt,
      }));
      main.setData(display.map((b) => ({ ...b, time: b.time as Time })));
    }
    mainRef.current = main;

    // volume, overlaid at the bottom of the price pane
    if (indicators.volume) {
      const vol = add(chart.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false,
      }));
      vol.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
      const vd = bars.map((b) => ({
        time: b.time as Time,
        value: b.volume,
        color: b.close >= b.open ? "rgba(38,166,154,0.45)" : "rgba(239,83,80,0.45)",
      }));
      vol.setData(vd);
      reg(0, { label: "Volume (bottom bars)", color: "rgba(156,163,175,0.6)", swatch: "hist", series: vol, last: lastOf(vd), format: fmtVol });
    }

    const thin = { lineWidth: 1 as const, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false };
    for (const o of computed.overlays) {
      const s = add(chart.addSeries(LineSeries, { ...thin, color: o.color, priceFormat: fmt }));
      const d = lineData(bars, o.values);
      s.setData(d);
      reg(0, { label: `${o.label} · indicator`, color: o.color, swatch: "line", series: s, last: lastOf(d), format: pf });
    }
    if (computed.bb) {
      const band = { ...thin, color: "rgba(167,139,250,0.8)", priceFormat: fmt };
      const up = add(chart.addSeries(LineSeries, band));
      const du = lineData(bars, computed.bb.upper);
      up.setData(du);
      const lo = add(chart.addSeries(LineSeries, band));
      const dl = lineData(bars, computed.bb.lower);
      lo.setData(dl);
      add(chart.addSeries(LineSeries, { ...band, lineStyle: LineStyle.Dashed })).setData(lineData(bars, computed.bb.mid));
      reg(0, { label: "Bollinger upper (20, 2) · indicator", color: "rgba(167,139,250,0.9)", swatch: "line", series: up, last: lastOf(du), format: pf });
      reg(0, { label: "Bollinger lower", color: "rgba(167,139,250,0.9)", swatch: "line", series: lo, last: lastOf(dl), format: pf });
    }

    // sub-panes from the Indicators menu
    let pane = 1;
    if (computed.rsi) {
      const r = add(chart.addSeries(LineSeries, { lineWidth: 1, color: "#c084fc", priceLineVisible: false }, pane));
      const d = lineData(bars, computed.rsi);
      r.setData(d);
      for (const lvl of [70, 30]) {
        r.createPriceLine({ price: lvl, color: "#4b5563", lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: "" });
      }
      reg(pane, { label: "RSI 14", color: "#c084fc", swatch: "line", series: r, last: lastOf(d), format: (v) => v.toFixed(1) });
      legend[pane].title = "RSI (14) · indicator";
      legend[pane].note = "Above 70 = overbought, below 30 = oversold (dashed lines).";
      pane++;
    }
    if (computed.macd) {
      const m = computed.macd;
      const h = add(chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane));
      h.setData(m.hist.flatMap((v, i) =>
        v == null ? [] : [{ time: bars[i].time as Time, value: v, color: v >= 0 ? "rgba(38,166,154,0.6)" : "rgba(239,83,80,0.6)" }],
      ));
      const ml = add(chart.addSeries(LineSeries, { ...thin, color: "#60a5fa" }, pane));
      const dm = lineData(bars, m.line);
      ml.setData(dm);
      const ms = add(chart.addSeries(LineSeries, { ...thin, color: "#f59e0b" }, pane));
      const ds = lineData(bars, m.signal);
      ms.setData(ds);
      reg(pane, { label: "MACD", color: "#60a5fa", swatch: "line", series: ml, last: lastOf(dm), format: (v) => v.toFixed(3) });
      reg(pane, { label: "Signal", color: "#f59e0b", swatch: "line", series: ms, last: lastOf(ds), format: (v) => v.toFixed(3) });
      legend[pane].title = "MACD (12, 26, 9) · indicator";
      legend[pane].note = PANE_INFO.macd.note;
      pane++;
    }

    // technical-analysis rule overlays (each sub-pane key gets its own pane)
    const paneIndex = new Map<string, number>();
    const paneFor = (key: string, rule?: string) => {
      if (key === "main") return 0;
      if (!paneIndex.has(key)) {
        const idx = pane++;
        paneIndex.set(key, idx);
        while (legend.length <= idx) legend.push({ items: [] });
        const info = PANE_INFO[key];
        legend[idx].title = `${info?.title ?? key}${rule ? ` · rule: ${rule}` : ""}`;
        legend[idx].note = info?.note;
      }
      return paneIndex.get(key)!;
    };
    const lineStyle = (s?: string) => (s === "dashed" ? LineStyle.Dashed : s === "dotted" ? LineStyle.Dotted : LineStyle.Solid);
    let hasLevels = false;
    let hasPatterns = false;
    for (const ov of taOverlays) {
      if (ov.type === "line") {
        const idx = paneFor(ov.pane, ov.rule);
        const s = add(chart.addSeries(LineSeries, {
          ...thin, color: ov.color, lineWidth: (ov.width ?? 1) as 1 | 2, lineStyle: lineStyle(ov.style),
          ...(idx === 0 ? { priceFormat: fmt } : {}),
        }, idx));
        const d = ov.data.map((p) => ({ time: p.time as Time, value: p.value }));
        s.setData(d);
        for (const g of ov.guides ?? []) {
          s.createPriceLine({ price: g, color: "#4b5563", lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: "" });
        }
        reg(idx, {
          label: idx === 0 ? `${ov.name}${ruleTag(ov.rule)}` : ov.name,
          color: ov.color,
          swatch: ov.style === "dashed" ? "dashed" : ov.style === "dotted" ? "dotted" : "line",
          series: s,
          last: lastOf(d),
          format: idx === 0 ? pf : ov.pane === "volume" || ov.pane === "obv" ? fmtVol : (v) => v.toFixed(2),
        });
      } else if (ov.type === "histogram") {
        const idx = paneFor(ov.pane, ov.rule);
        const s = add(chart.addSeries(HistogramSeries, {
          priceLineVisible: false, lastValueVisible: false,
          priceFormat: ov.pane === "volume" ? { type: "volume" } : { type: "price", precision: 3, minMove: 0.001 },
        }, idx));
        const d = ov.data.map((p) => ({ time: p.time as Time, value: p.value, color: p.color }));
        s.setData(d);
        reg(idx, {
          label: ov.name, color: "rgba(156,163,175,0.7)", swatch: "hist", series: s, last: lastOf(d),
          format: ov.pane === "volume" ? fmtVol : (v) => v.toFixed(3),
        });
      } else if (ov.type === "levels") {
        for (const l of ov.levels) {
          main.createPriceLine({ price: l.price, color: l.color, lineWidth: 1, lineStyle: LineStyle.Solid, axisLabelVisible: true, title: l.label });
        }
        if (ov.levels.length && !hasLevels) {
          hasLevels = true;
          reg(0, { label: `S1–S3 support (green) / R1–R3 resistance (red), (n×) = touches${ruleTag(ov.rule)}`, color: C.up, swatch: "line" });
        }
      } else if (ov.type === "segments") {
        for (const sg of ov.segments) {
          // the library needs strictly ascending times
          const pts = sg.points.filter((p, i, a) => i === 0 || timeToMs(p.time as Time) > timeToMs(a[i - 1].time as Time));
          if (pts.length < 2) continue;
          add(chart.addSeries(LineSeries, {
            ...thin, lineWidth: 1, color: sg.color, lineStyle: sg.dashed ? LineStyle.Dashed : LineStyle.Solid,
            priceFormat: fmt,
          })).setData(pts.map((p) => ({ time: p.time as Time, value: p.value })));
        }
        if (ov.segments.length && !hasPatterns) {
          hasPatterns = true;
          reg(0, { label: `Pattern outlines (dashed = neckline / flag channel; green bullish, red bearish)${ruleTag(ov.rule)}`, color: C.up, swatch: "line" });
        }
      }
    }

    const panes = chart.panes();
    panes.forEach((p, i) => p.setStretchFactor(i === 0 ? 4 : 1));

    // drawings
    for (const d of drawings) {
      if (d.type === "hline") {
        main.createPriceLine({ price: d.price, color: C.drawing, lineWidth: 1, lineStyle: LineStyle.Solid, axisLabelVisible: true, title: "" });
      } else {
        const pts = [d.p1, d.p2].sort((a, b) => timeToMs(a.time) - timeToMs(b.time));
        if (timeToMs(pts[0].time) === timeToMs(pts[1].time)) continue;
        add(chart.addSeries(LineSeries, { ...thin, lineWidth: 2, color: C.drawing, pointMarkersVisible: true, priceFormat: fmt }))
          .setData(pts.map((p) => ({ time: p.time, value: p.price })));
      }
    }
    if (drawings.length) reg(0, { label: "Your drawings", color: C.drawing, swatch: "line" });

    // markers: the app's suggestions (squares) + rule signals (arrows)
    if (markers.length) {
      const sorted = [...markers].sort((a, b) => timeToMs(a.time) - timeToMs(b.time));
      createSeriesMarkers(main, sorted.map((m): SeriesMarker<Time> => {
        const text = markerLabels || m.source === "app" ? m.text : "";
        if (m.source === "app") {
          return m.side === "buy"
            ? { time: m.time, position: "belowBar", color: C.accent, shape: "square", text: m.text }
            : m.side === "sell"
            ? { time: m.time, position: "aboveBar", color: C.danger, shape: "square", text: m.text }
            : { time: m.time, position: "aboveBar", color: "#6b7280", shape: "circle", size: 0.5 };
        }
        return m.side === "buy"
          ? { time: m.time, position: "belowBar", color: C.taBuy, shape: "arrowUp", text }
          : { time: m.time, position: "aboveBar", color: C.taSell, shape: "arrowDown", text };
      }));
      if (markers.some((m) => m.source === "ta")) {
        reg(0, { label: "Rule signals: green ▲ buy / orange ▼ sell — hover a bar to see which rule", color: C.taBuy, swatch: "arrow" });
      }
      if (markers.some((m) => m.source === "app")) {
        reg(0, { label: "App suggestions (B = buy, S = sell; grey dot = avoid)", color: C.accent, swatch: "square" });
      }
    }
    for (const l of levels) {
      main.createPriceLine({
        price: l.price,
        color: l.kind === "target" ? C.accent : l.kind === "stop" ? C.danger : "#9ca3af",
        lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: l.title,
      });
    }
    if (levels.length) reg(0, { label: "Latest app suggestion: entry (grey) / stop (red) / target (green)", color: "#9ca3af", swatch: "level" });

    chart.priceScale("right").applyOptions({
      mode: scaleMode === "log" ? PriceScaleMode.Logarithmic : scaleMode === "percent" ? PriceScaleMode.Percentage : PriceScaleMode.Normal,
    });

    if (keepRange) {
      chart.timeScale().setVisibleLogicalRange(keepRange);
    } else {
      // default view: the most recent ~150 bars, like TradingView
      chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, bars.length - 150), to: bars.length + 5 });
    }
    lastKey.current = seriesKey;
    setLegends(legend);

    // pane positions settle after layout; re-measure then, and whenever a pane is resized
    const raf = requestAnimationFrame(measurePanes);
    const ro = new ResizeObserver(() => measurePanes());
    chart.panes().forEach((p) => {
      const el = p.getHTMLElement();
      if (el) ro.observe(el);
    });
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [computed, bars, seriesKey, chartType, indicators, scaleMode, drawings, markers, levels, taOverlays, markerLabels, priceDecimals, measurePanes]);

  useImperativeHandle(ref, () => ({
    fit: () => chartRef.current?.timeScale().fitContent(),
    screenshot: () => chartRef.current?.takeScreenshot(true) ?? null,
    setRange: (range: RangeKey) => {
      const chart = chartRef.current;
      if (!chart || !bars.length) return;
      if (range === "All") return chart.timeScale().fitContent();
      const lastMs = timeToMs(bars[bars.length - 1].time as Time);
      const fromMs = range === "YTD"
        ? new Date(new Date(lastMs).getFullYear(), 0, 1).getTime()
        : lastMs - RANGE_DAYS[range] * 86_400_000;
      const fromIdx = bars.findIndex((b) => timeToMs(b.time as Time) >= fromMs);
      if (fromIdx <= 0) return chart.timeScale().fitContent();
      chart.timeScale().setVisibleLogicalRange({ from: fromIdx, to: bars.length + 3 });
    },
    focus: (time: Time) => {
      const chart = chartRef.current;
      const main = mainRef.current;
      const i = computedRef.current.indexByTime.get(String(time));
      if (!chart || !main || i === undefined) return;
      focusLock.current = i;
      setLegendIdx(i);
      setHoverVals(null);
      chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, i - 60), to: Math.min(bars.length + 5, i + 40) });
      // the range applies on the next frames; place the crosshair once the bar has moved into view
      requestAnimationFrame(() => requestAnimationFrame(() => {
        if (focusLock.current === i) chart.setCrosshairPosition(bars[i].close, time, main);
      }));
    },
  }), [bars]);

  // ---- legend values (crosshair bar, else the last bar) ----
  const idx = legendIdx ?? bars.length - 1;
  const bar = bars[idx];
  const prev = idx > 0 ? bars[idx - 1] : null;
  const f = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(priceDecimals));
  const change = bar && prev ? bar.close - prev.close : null;
  const markersByTime = useMemo(() => {
    const m = new Map<string, ChartMarker[]>();
    for (const mk of markers) {
      if (!mk.text) continue;
      const k = String(mk.time);
      m.set(k, [...(m.get(k) ?? []), mk]);
    }
    return m;
  }, [markers]);
  const barSignals = bar ? markersByTime.get(String(bar.time)) ?? [] : [];

  const itemValue = (it: LegendItem) => {
    if (!it.series || !it.format) return null;
    const v = hoverVals ? hoverVals.get(it.series) : it.last;
    return v == null ? "—" : it.format(v);
  };

  const ItemRow = ({ it }: { it: LegendItem }) => {
    const v = itemValue(it);
    return (
      <span className="inline-flex items-center gap-1 whitespace-nowrap">
        <SwatchIcon s={it.swatch} color={it.color} />
        <span className="text-gray-400">{it.label}</span>
        {v != null && <span className="text-gray-100">{v}</span>}
      </span>
    );
  };

  return (
    <div className="relative h-full w-full">
      <div
        ref={container}
        className="h-full w-full"
        style={{ cursor: drawMode === "none" ? "default" : "crosshair" }}
      />

      {/* price-pane legend */}
      {bar && (
        <div className="absolute left-2 top-2 z-10 max-w-[70%] text-xs font-mono leading-5">
          <div className="pointer-events-none flex flex-wrap gap-x-3 text-gray-300">
            <span>O <b className="font-normal text-gray-100">{f(bar.open)}</b></span>
            <span>H <b className="font-normal text-gray-100">{f(bar.high)}</b></span>
            <span>L <b className="font-normal text-gray-100">{f(bar.low)}</b></span>
            <span>C <b className="font-normal text-gray-100">{f(bar.close)}</b></span>
            {change != null && prev && (
              <span className={change >= 0 ? "text-[#26a69a]" : "text-[#ef5350]"}>
                {change >= 0 ? "+" : ""}{change.toFixed(priceDecimals)} ({((change / prev.close) * 100).toFixed(2)}%)
              </span>
            )}
          </div>
          {barSignals.length > 0 && (
            <div className="pointer-events-none flex flex-wrap gap-x-2">
              <span className="text-gray-500">Signals on this bar:</span>
              {barSignals.map((s, i) => (
                <span key={i} className={s.side === "buy" ? (s.source === "app" ? "text-accent" : "text-[#22c55e]") : s.side === "sell" ? (s.source === "app" ? "text-danger" : "text-[#f97316]") : "text-gray-400"}>
                  {s.side === "buy" ? "▲" : s.side === "sell" ? "▼" : "•"} {s.text}
                </span>
              ))}
            </div>
          )}
          {legends[0]?.items.length ? (
            <div className="mt-1 inline-flex max-w-full flex-col rounded border border-border bg-bg/90 px-2 py-1">
              <button
                className="flex items-center gap-2 text-left font-sans text-[11px] text-gray-300 hover:text-white"
                onClick={() => setLegendOpen(!legendOpen)}
                title={legendOpen ? "Collapse the legend" : "Expand the legend"}
              >
                <span className="text-gray-400">{legendOpen ? "▾" : "▸"}</span>
                <span className="font-medium">Legend</span>
                <span className="text-gray-500">({legends[0].items.length})</span>
                {!legendOpen && (
                  // collapsed: just the colours, names on hover
                  <span className="flex items-center gap-1.5">
                    {legends[0].items.map((it, i) => (
                      <span key={i} title={it.label} className="inline-flex"><SwatchIcon s={it.swatch} color={it.color} /></span>
                    ))}
                  </span>
                )}
                <span className="ml-auto pl-3 text-[10px] text-gray-500">{legendOpen ? "hide" : "show"}</span>
              </button>
              {legendOpen && (
                <div className="pointer-events-none mt-0.5 flex flex-col">
                  {legends[0].items.map((it, i) => <ItemRow key={i} it={it} />)}
                </div>
              )}
            </div>
          ) : null}
        </div>
      )}

      {/* sub-pane legends: title, series with values, reading guide */}
      {legends.slice(1).map((lg, k) => {
        const top = paneTops[k + 1];
        if (top == null || (!lg.title && !lg.items.length)) return null;
        return (
          <div
            key={k}
            className="pointer-events-none absolute left-2 z-10 max-w-[75%] rounded bg-bg/80 px-1.5 py-0.5 text-[11px] leading-4"
            style={{ top: top + 3 }}
          >
            <div className="flex flex-wrap items-center gap-x-3 font-mono">
              {lg.title && <span className="font-sans font-semibold text-gray-200">{lg.title}</span>}
              {lg.items.map((it, i) => <ItemRow key={i} it={it} />)}
            </div>
            {lg.note && legendOpen && <div className="text-[10px] text-gray-500">{lg.note}</div>}
          </div>
        );
      })}

      {drawMode !== "none" && (
        <div className="pointer-events-none absolute bottom-10 left-1/2 z-10 -translate-x-1/2 rounded bg-panel/90 px-3 py-1 text-xs text-gray-300 border border-border">
          {drawMode === "hline"
            ? "Click to place a horizontal line · Esc to stop"
            : pending ? "Click the second point" : "Click the first point of the trend line · Esc to stop"}
        </div>
      )}
    </div>
  );
});

export default TradingChart;
