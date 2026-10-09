import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
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
  direction: "buy" | "avoid" | "sell_short";
  text: string;
}

export interface ChartLevel {
  price: number;
  kind: "entry" | "stop" | "target";
  title: string;
}

export interface TradingChartHandle {
  setRange: (range: RangeKey) => void;
  fit: () => void;
  screenshot: () => HTMLCanvasElement | null;
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
};

const OVERLAYS: { key: keyof Indicators; label: string; color: string; calc: (c: number[]) => Series }[] = [
  { key: "sma20", label: "SMA 20", color: "#f59e0b", calc: (c) => sma(c, 20) },
  { key: "sma50", label: "SMA 50", color: "#3b82f6", calc: (c) => sma(c, 50) },
  { key: "sma200", label: "SMA 200", color: "#e879f9", calc: (c) => sma(c, 200) },
  { key: "ema9", label: "EMA 9", color: "#22d3ee", calc: (c) => ema(c, 9) },
  { key: "ema21", label: "EMA 21", color: "#a3e635", calc: (c) => ema(c, 21) },
];

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
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return String(Math.round(v));
}

interface LegendRow { label: string; value: string; color: string }

const TradingChart = forwardRef<TradingChartHandle, Props>(function TradingChart(props, ref) {
  const { bars, seriesKey, chartType, indicators, scaleMode, drawings, drawMode, markers, levels, priceDecimals } = props;
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
      if (p.time === undefined) {
        setLegendIdx(null);
        return;
      }
      setLegendIdx(computedRef.current.indexByTime.get(String(p.time)) ?? null);
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
    return () => {
      chart.unsubscribeCrosshairMove(onMove);
      chart.unsubscribeClick(onClick);
      chart.remove();
      chartRef.current = null;
    };
  }, []);

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
    if (!bars.length) return;

    const add = <T extends SeriesType>(s: ISeriesApi<T>) => {
      seriesRefs.current.push(s as unknown as ISeriesApi<SeriesType>);
      return s;
    };
    const fmt = { type: "price" as const, precision: priceDecimals, minMove: 1 / 10 ** priceDecimals };
    const { display } = computed;

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
      vol.setData(bars.map((b) => ({
        time: b.time as Time,
        value: b.volume,
        color: b.close >= b.open ? "rgba(38,166,154,0.45)" : "rgba(239,83,80,0.45)",
      })));
    }

    const thin = { lineWidth: 1 as const, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false };
    for (const o of computed.overlays) {
      add(chart.addSeries(LineSeries, { ...thin, color: o.color, priceFormat: fmt })).setData(lineData(bars, o.values));
    }
    if (computed.bb) {
      const band = { ...thin, color: "rgba(167,139,250,0.8)", priceFormat: fmt };
      add(chart.addSeries(LineSeries, band)).setData(lineData(bars, computed.bb.upper));
      add(chart.addSeries(LineSeries, band)).setData(lineData(bars, computed.bb.lower));
      add(chart.addSeries(LineSeries, { ...band, lineStyle: LineStyle.Dashed })).setData(lineData(bars, computed.bb.mid));
    }

    // sub-panes
    let pane = 1;
    if (computed.rsi) {
      const r = add(chart.addSeries(LineSeries, { lineWidth: 1, color: "#c084fc", priceLineVisible: false }, pane));
      r.setData(lineData(bars, computed.rsi));
      for (const lvl of [70, 30]) {
        r.createPriceLine({ price: lvl, color: "#4b5563", lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: "" });
      }
      pane++;
    }
    if (computed.macd) {
      const m = computed.macd;
      const h = add(chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane));
      h.setData(m.hist.flatMap((v, i) =>
        v == null ? [] : [{ time: bars[i].time as Time, value: v, color: v >= 0 ? "rgba(38,166,154,0.6)" : "rgba(239,83,80,0.6)" }],
      ));
      add(chart.addSeries(LineSeries, { ...thin, color: "#60a5fa" }, pane)).setData(lineData(bars, m.line));
      add(chart.addSeries(LineSeries, { ...thin, color: "#f59e0b" }, pane)).setData(lineData(bars, m.signal));
      pane++;
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

    // suggestion markers + levels
    if (markers.length) {
      createSeriesMarkers(main, markers.map((m): SeriesMarker<Time> =>
        m.direction === "buy"
          ? { time: m.time, position: "belowBar", color: C.accent, shape: "arrowUp", text: m.text }
          : m.direction === "sell_short"
          ? { time: m.time, position: "aboveBar", color: C.danger, shape: "arrowDown", text: m.text }
          : { time: m.time, position: "aboveBar", color: "#6b7280", shape: "circle", size: 0.5 },
      ));
    }
    for (const l of levels) {
      main.createPriceLine({
        price: l.price,
        color: l.kind === "target" ? C.accent : l.kind === "stop" ? C.danger : "#9ca3af",
        lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: l.title,
      });
    }

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
  }, [computed, bars, seriesKey, chartType, indicators, scaleMode, drawings, markers, levels, priceDecimals]);

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
  }), [bars]);

  // ---- legend (OHLC + indicator values at the crosshair, else the last bar) ----
  const idx = legendIdx ?? bars.length - 1;
  const bar = bars[idx];
  const prev = idx > 0 ? bars[idx - 1] : null;
  const rows: LegendRow[] = [];
  const f = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(priceDecimals));
  for (const o of computed.overlays) rows.push({ label: o.label, value: f(o.values[idx]), color: o.color });
  if (computed.bb) rows.push({ label: "BB 20 2", value: `${f(computed.bb.upper[idx])} / ${f(computed.bb.lower[idx])}`, color: "#a78bfa" });
  if (computed.rsi) rows.push({ label: "RSI 14", value: computed.rsi[idx]?.toFixed(1) ?? "—", color: "#c084fc" });
  if (computed.macd) {
    const m = computed.macd;
    rows.push({ label: "MACD", value: `${m.line[idx]?.toFixed(3) ?? "—"} / ${m.signal[idx]?.toFixed(3) ?? "—"}`, color: "#60a5fa" });
  }
  const change = bar && prev ? bar.close - prev.close : null;

  return (
    <div className="relative h-full w-full">
      <div
        ref={container}
        className="h-full w-full"
        style={{ cursor: drawMode === "none" ? "default" : "crosshair" }}
      />
      {bar && (
        <div className="pointer-events-none absolute left-2 top-2 z-10 text-xs font-mono leading-5">
          <div className="flex flex-wrap gap-x-3 text-gray-300">
            <span>O <b className="font-normal text-gray-100">{f(bar.open)}</b></span>
            <span>H <b className="font-normal text-gray-100">{f(bar.high)}</b></span>
            <span>L <b className="font-normal text-gray-100">{f(bar.low)}</b></span>
            <span>C <b className="font-normal text-gray-100">{f(bar.close)}</b></span>
            {change != null && prev && (
              <span className={change >= 0 ? "text-[#26a69a]" : "text-[#ef5350]"}>
                {change >= 0 ? "+" : ""}{change.toFixed(priceDecimals)} ({((change / prev.close) * 100).toFixed(2)}%)
              </span>
            )}
            {indicators.volume && <span>Vol <b className="font-normal text-gray-100">{fmtVol(bar.volume)}</b></span>}
          </div>
          {rows.map((r) => (
            <div key={r.label}>
              <span style={{ color: r.color }}>{r.label}</span> <span className="text-gray-200">{r.value}</span>
            </div>
          ))}
        </div>
      )}
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
