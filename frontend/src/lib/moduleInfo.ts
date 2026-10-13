/**
 * Plain-language guide to each analysis module: what it measures, how to read
 * its score, and which of its raw numbers matter (formatted for display).
 */

export type ModuleGroup = "Technical" | "Fundamentals" | "Sentiment & ownership" | "Macro & events" | "Risk";

export interface Metric {
  label: string;
  value: string;
  hint?: string;
}

export interface ModuleInfo {
  title: string;
  group: ModuleGroup;
  what: string;
  read: string;
  metrics: (raw: Record<string, any>) => Metric[];
}

const pct = (v: unknown, digits = 1, isFraction = true) =>
  typeof v === "number" ? `${v >= 0 ? "+" : ""}${(isFraction ? v * 100 : v).toFixed(digits)}%` : "—";
const pctPlain = (v: unknown, digits = 1) => (typeof v === "number" ? `${(v * 100).toFixed(digits)}%` : "—");
const num = (v: unknown, digits = 2) => (typeof v === "number" ? v.toFixed(digits) : "—");
const big = (v: unknown) => {
  if (typeof v !== "number") return "—";
  const a = Math.abs(v);
  return a >= 1e9 ? `${(v / 1e9).toFixed(1)}B` : a >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : a >= 1e3 ? `${(v / 1e3).toFixed(0)}K` : v.toFixed(0);
};
const trend = (v: unknown) => (v === 1 ? "up" : v === -1 ? "down" : v === 0 ? "mixed" : "—");
const keep = (m: Metric[]) => m.filter((x) => x.value !== "—" && x.value !== "");

export const MODULE_INFO: Record<string, ModuleInfo> = {
  technical: {
    title: "Technical (chart rules)",
    group: "Technical",
    what: "Classic chart reading: trend vs the 200-EMA, RSI, MACD, ADX trend strength, volume-confirmed breakouts, on-balance volume, support & resistance, candlestick and chart patterns, and the weekly trend.",
    read: "Positive = the chart leans bullish. Rule contributions are summed, amplified in strong trends (ADX > 25) and damped when they fight the weekly trend. Counts most for 1w–1m.",
    metrics: (r) => keep([
      { label: "Last close", value: num(r.last_close) },
      { label: "RSI (14)", value: num(r.rsi_14, 0), hint: "<30 oversold, >70 overbought" },
      { label: "ADX (14)", value: num(r.adx_14, 0), hint: ">25 strong trend" },
      { label: "200-EMA", value: num(r.ema_200) },
      { label: "ATR (14)", value: num(r.atr_14), hint: "average daily range — sizes stops/targets" },
      { label: "Weekly trend", value: trend(r.weekly_trend) },
      { label: "Support", value: (r.support_levels ?? []).map((x: number) => x.toFixed(2)).join(" · ") },
      { label: "Resistance", value: (r.resistance_levels ?? []).map((x: number) => x.toFixed(2)).join(" · ") },
    ]),
  },
  momentum: {
    title: "Momentum",
    group: "Technical",
    what: "How the price has performed over 1, 3, 6 and 12 months, and whether it beat its own market (relative strength vs its benchmark).",
    read: "Positive = strong and/or outperforming recent performance — trends tend to persist for months. Counts most for 1m–6m.",
    metrics: (r) => keep([
      { label: "1 month", value: pct(r.ret_1m_pct, 1, false) },
      { label: "3 months", value: pct(r.ret_3m_pct, 1, false) },
      { label: "6 months", value: pct(r.ret_6m_pct, 1, false) },
      { label: "12 months", value: pct(r.ret_12m_pct, 1, false) },
      { label: `vs ${r.benchmark ?? "benchmark"} (3m)`, value: typeof r.rs_vs_benchmark_3m === "number" ? pct(r.rs_vs_benchmark_3m - 1) : "—", hint: "out/under-performance" },
      { label: "Acceleration", value: num(r.acceleration, 2), hint: "recent month faster than the trailing 3 months" },
    ]),
  },
  mean_reversion: {
    title: "Mean reversion",
    group: "Technical",
    what: "How stretched the price is from its recent average (z-score) and its Bollinger Bands.",
    read: "Stretched UP gives a negative score (expects a pull-back), stretched DOWN a positive one (expects a bounce). Counts most for 1–2 weeks, barely at all beyond 3 months.",
    metrics: (r) => keep([
      { label: "Z-score 20", value: num(r.z20, 2), hint: "beyond ±2 = stretched" },
      { label: "Z-score 50", value: num(r.z50, 2) },
      { label: "Bollinger %B", value: num(r.bb_pct, 2), hint: "0 = lower band, 1 = upper band" },
      { label: "ATRs from 200-EMA", value: num(r.stretch_atr, 1), hint: ">5 = long-term stretch" },
    ]),
  },
  volatility_regime: {
    title: "Volatility regime",
    group: "Risk",
    what: "How bumpy the last 30 days were compared with the asset's own past two years.",
    read: "Calm (low) volatility is mildly positive; high or extreme volatility is negative and can exclude the asset from the Conservative profile.",
    metrics: (r) => keep([
      { label: "30-day volatility", value: typeof r.vol_30d_pct === "number" ? `${r.vol_30d_pct.toFixed(1)}%` : "—", hint: "annualized" },
      { label: "Percentile (2y)", value: pctPlain(r.percentile_2y, 0) },
      { label: "Regime", value: r.regime ?? "—" },
    ]),
  },
  risk_metrics: {
    title: "Risk metrics",
    group: "Risk",
    what: "Beta (how much it moves with its market), long-term volatility, worst drawdown and Sharpe ratio over 3 years.",
    read: "Mostly a filter, not a signal: high beta or deep drawdowns exclude the asset from cautious profiles. Tiny score nudge for good Sharpe / deep drawdowns.",
    metrics: (r) => keep([
      { label: "Beta (3y)", value: num(r.beta_3y, 2), hint: "1 = moves like its market" },
      { label: "Volatility (3y)", value: typeof r.vol_3y_annualized_pct === "number" ? `${r.vol_3y_annualized_pct.toFixed(1)}%` : "—" },
      { label: "Max drawdown (3y)", value: typeof r.max_drawdown_3y_pct === "number" ? `${r.max_drawdown_3y_pct.toFixed(1)}%` : "—" },
      { label: "Sharpe (3y)", value: num(r.sharpe_3y, 2), hint: ">1 good risk-adjusted return" },
    ]),
  },
  fundamental_equity: {
    title: "Fundamentals",
    group: "Fundamentals",
    what: "Valuation (P/E, PEG, P/B, FCF yield), profitability (ROE, margins), 3-year growth, debt, recent earnings beats and analyst consensus.",
    read: "Positive = attractively valued, profitable and growing, with analysts on side. Counts most for 3 months and longer.",
    metrics: (r) => {
      const t = r.ttm ?? {};
      const g = r.growth ?? {};
      return keep([
        { label: "P/E", value: num(t.pe, 1) },
        { label: "PEG", value: num(t.peg, 2), hint: "<1 growth at a reasonable price" },
        { label: "P/B", value: num(t.pb, 2) },
        { label: "FCF yield", value: pctPlain(t.fcf_yield) },
        { label: "ROE", value: pctPlain(t.roe) },
        { label: "Operating margin", value: pctPlain(t.op_margin) },
        { label: "Net margin", value: pctPlain(t.net_margin) },
        { label: "Debt / equity", value: num(t.debt_to_equity, 2) },
        { label: "Revenue growth (3y CAGR)", value: pct(g.rev_3y) },
        { label: "EPS growth (3y CAGR)", value: pct(g.eps_3y) },
        { label: "Earnings beats (last 4)", value: typeof r.earnings_beats_last_4 === "number" ? `${r.earnings_beats_last_4}/4` : "—" },
        { label: "Analyst target vs price", value: pct(r.analyst_upside) },
        { label: "Analyst ratings", value: r.analyst_count ? `${r.analyst_count} (score ${num(r.analyst_rec_score, 2)})` : "—", hint: "+1 all strong buy, −1 all strong sell" },
        { label: "Data source", value: r.source ?? "—" },
      ]);
    },
  },
  etf_fundamental: {
    title: "ETF profile",
    group: "Fundamentals",
    what: "What you'd own and what it costs: domicile (tax), accumulating vs distributing, fees, fund size and concentration.",
    read: "Positive = tax-efficient Irish UCITS, cheap, large and diversified. Counts most for long horizons.",
    metrics: (r) => keep([
      { label: "Domicile", value: r.domicile ?? "—" },
      { label: "Share class", value: r.distribution ?? "—" },
      { label: "Fee (TER)", value: typeof r.expense_ratio === "number" ? `${(r.expense_ratio * 100).toFixed(2)}%` : "—" },
      { label: "Fund size", value: big(r.aum) },
      { label: "Top 10 holdings", value: pctPlain(r.top10_weight, 0) },
      { label: "Largest holdings", value: (r.top_holdings ?? []).join(", ") },
      { label: "Largest sector", value: r.top_sector ? String(r.top_sector).replace(/_/g, " ") : "—" },
      { label: "Category", value: r.category ? String(r.category).replace(/_/g, " ") : "—" },
    ]),
  },
  quality: {
    title: "Quality scores",
    group: "Fundamentals",
    what: "Accounting-based health checks: Piotroski F-Score (0–9 financial strength), Altman Z (bankruptcy risk), Beneish M (earnings-manipulation risk).",
    read: "Positive = financially strong and clean books. Not meaningful for banks/insurers. A low Piotroski excludes stocks from Conservative/Growth.",
    metrics: (r) => keep([
      { label: "Piotroski F", value: typeof r.piotroski_f === "number" ? `${r.piotroski_f}/9` : "—", hint: "≥7 strong, ≤3 weak" },
      { label: "Altman Z", value: num(r.altman_z, 2), hint: ">3 safe, <1.8 distress" },
      { label: "Beneish M", value: num(r.beneish_m, 2), hint: "> −1.78 = possible manipulation" },
    ]),
  },
  news_sentiment: {
    title: "News sentiment",
    group: "Sentiment & ownership",
    what: "Tone of recent headlines (last 14 days) — company news for stocks, news about the underlying market for ETFs — plus GDELT's global news tone when available.",
    read: "Positive = predominantly upbeat coverage. Counts mostly for short horizons (1w–1m); news fades fast.",
    metrics: (r) => keep([
      { label: "Headlines analysed", value: typeof r.headline_count === "number" ? String(r.headline_count) : "—" },
      { label: "Headline polarity", value: num(r.mean_polarity, 2), hint: "−1 negative … +1 positive" },
      { label: "GDELT tone", value: r.gdelt_tone ? num(r.gdelt_tone.avg_tone, 2) : "—", hint: "global news tone, ±3 typical" },
    ]),
  },
  social_sentiment: {
    title: "Social sentiment",
    group: "Sentiment & ownership",
    what: "Reddit mention volume and tone over the last week.",
    read: "Positive = growing, upbeat retail attention. Not active until a Reddit key is configured.",
    metrics: (r) => keep([
      { label: "Posts (7d)", value: typeof r.post_count_7d === "number" ? String(r.post_count_7d) : "—" },
      { label: "Polarity", value: num(r.mean_polarity, 2) },
    ]),
  },
  insider_institutional: {
    title: "Insiders, short interest & ownership",
    group: "Sentiment & ownership",
    what: "Insider buying/selling over 90 days (US: SEC Form 4 + Finnhub), short interest (FINRA + Yahoo) and institutional ownership.",
    read: "Positive = insiders buying, short sellers retreating. Heavy or rising short interest is negative.",
    metrics: (r) => keep([
      { label: "Insider buys / sells (90d)", value: r.insider_buys_90d || r.insider_sells_90d ? `${r.insider_buys_90d} / ${r.insider_sells_90d}` : "—" },
      { label: "Net insider value (90d)", value: r.net_value_usd_90d ? `$${big(r.net_value_usd_90d)}` : "—" },
      { label: "Short % of float", value: pctPlain(r.short_pct_float) },
      { label: "Days to cover", value: num(r.days_to_cover, 1) },
      { label: "Short interest change", value: pct(r.short_change_pct), hint: `since previous FINRA report${r.short_settlement_date ? ` (${r.short_settlement_date})` : ""}` },
      { label: "Held by institutions", value: pctPlain(r.held_pct_institutions, 0) },
    ]),
  },
  macro: {
    title: "Macro backdrop",
    group: "Macro & events",
    what: "Economic conditions: US (VIX, Treasury yields, yield curve) and euro area (VSTOXX, ECB rate, euro yields, inflation, economic sentiment), blended by how European the asset is.",
    read: "Positive = risk-friendly environment (calm markets, falling rates, healthy economy). Counts most for 1–6 months.",
    metrics: (r) => keep([
      { label: "Euro-area exposure", value: pctPlain(r.eu_exposure, 0) },
      { label: "US score / euro score", value: `${num(r.us_score, 2)} / ${num(r.eu_score, 2)}` },
      { label: "VIX", value: num(r.vix, 1), hint: "<15 calm, >25 fearful" },
      { label: "US 10Y yield", value: typeof r.us10y === "number" ? `${r.us10y.toFixed(2)}%` : "—" },
      { label: "US yield curve 10Y–2Y", value: num(r.yield_curve_2_10, 2), hint: "<0 = recession warning" },
      { label: "VSTOXX", value: num(r.vstoxx, 1) },
      { label: "ECB deposit rate", value: typeof r.ecb_deposit_rate === "number" ? `${r.ecb_deposit_rate.toFixed(2)}%` : "—" },
      { label: "Euro inflation", value: typeof r.ea_hicp === "number" ? `${r.ea_hicp.toFixed(1)}%` : "—", hint: "ECB target 2%" },
      { label: "EU economic sentiment", value: num(r.eu_esi, 1), hint: "100 = long-term average" },
      { label: "EUR/USD", value: num(r.eurusd, 4) },
    ]),
  },
  event_awareness: {
    title: "Upcoming events",
    group: "Macro & events",
    what: "Earnings and ex-dividend dates falling inside each horizon.",
    read: "Earnings inside the window add gap risk: a small negative score and reduced confidence for those horizons.",
    metrics: (r) => keep([
      { label: "Next earnings", value: r.next_earnings ?? "—" },
      {
        label: "Ex-dividend in window",
        value: Object.entries(r.by_timeframe ?? {})
          .filter(([, v]: [string, any]) => v?.ex_dividend_in_window?.length)
          .map(([tf]) => tf).join(", "),
      },
    ]),
  },
};

export const GROUP_ORDER: ModuleGroup[] = ["Technical", "Fundamentals", "Sentiment & ownership", "Macro & events", "Risk"];

export const PROFILE_LABEL: Record<string, string> = {
  conservative: "Conservative", balanced: "Balanced", growth: "Growth", aggressive: "Aggressive",
};
