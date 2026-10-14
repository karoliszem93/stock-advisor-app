// Typed fetch helpers. Vite proxies /api and /health to the backend.

export type Direction = "buy" | "avoid" | "sell_short";
export type RiskProfile = "conservative" | "balanced" | "growth" | "aggressive";
export type Timeframe = "1w" | "2w" | "1m" | "3m" | "6m" | "1y" | "3y";

export const RISK_PROFILES: RiskProfile[] = ["conservative", "balanced", "growth", "aggressive"];
export const TIMEFRAMES: Timeframe[] = ["1w", "2w", "1m", "3m", "6m", "1y", "3y"];

export interface HealthResponse {
  status: "ok";
  version: string;
  now_utc: string;
  timezone: string;
  schedule: string;
  config: {
    base_currency: string;
    github_pat_present: boolean;
    ollama_host: string;
    ollama_model: string;
    providers_with_keys: Record<string, boolean>;
  };
}

export interface ScoringContributor {
  module: string;
  score: number;
  confidence: number;
  cell_weight: number;
  horizon_weight: number;
  contribution: number;
}

export interface ScoringBreakdown {
  cell_score: number;
  cell_confidence: number;
  direction: Direction;
  direction_threshold: number;
  min_confidence: number;
  filter_passed: boolean;
  filter_reason: string | null;
  contributors: ScoringContributor[];
  raw_module_scores?: Record<
    string,
    { score: number | null; direction: string; confidence: number; data_quality: string }
  >;
}

export interface Rationale {
  headline?: string;
  technical_case?: string;
  fundamental_case?: string;
  sentiment_case?: string;
  macro_context?: string;
  why_this_timeframe?: string;
  key_risks?: string[];
  invalidation_triggers?: string[];
  counter_argument?: string;
  confidence_drivers?: { factor: string; delta: number; reason: string }[];
  scoring_breakdown?: ScoringBreakdown;
  tax_notes?: string;
  data_quality?: "full" | "degraded" | "missing";
  price_notes?: string[];
  /** Native-currency levels (stored from 2026-10-09 onwards). */
  prices?: { currency: string; entry: number; stop_loss: number; target: number };
}

export interface Suggestion {
  id: number;
  suggestion_date: string;
  ticker: string;
  asset_type: "equity" | "etf";
  timeframe: Timeframe;
  risk_profile: RiskProfile;
  direction: Direction;
  confidence: number;
  confidence_calibrated: number | null;
  target_date: string;
  headline: string | null;
  entry_price_eur: number | null;
  stop_loss_eur: number | null;
  target_price_eur: number | null;
  suggested_risk_pct: number | null;
  data_repo_commit_sha: string | null;
}

export interface SuggestionDetail extends Suggestion {
  rationale: Rationale | null;
  suggestion_json_path: string | null;
  analysis_json_path: string | null;
}

export interface WatchlistItem {
  ticker: string;
  note: string | null;
}

export interface TickerValidation {
  valid: boolean;
  ticker: string;
  name?: string;
  exchange?: string;
  currency?: string;
  asset_type?: "equity" | "etf";
  last_close?: number | null;
  error?: string;
  suggestions?: string[];
  warning?: string;
}

export interface ProviderStatus {
  name: string;
  description: string;
  available: boolean;
  key_setting: string | null;
  key_present: boolean;
  key_source_url: string | null;
  rate_limit: {
    capacity: number;
    window_seconds: number;
    used: number;
    remaining: number;
    resets_at: string | null;
  };
  error?: string;
}

export interface ValidationRow {
  id: number;
  suggestion_id: number;
  validated_at: string;
  outcome: "correct" | "incorrect" | "partial";
  outcome_score: number;
  actual_total_return_pct_eur: number | null;
  after_tax_return_pct_eur: number | null;
  actual_price_return_pct: number | null;
  actual_dividend_return_pct: number | null;
  actual_fx_effect_pct: number | null;
  max_favorable_excursion_pct: number | null;
  max_adverse_excursion_pct: number | null;
  target_hit: boolean | null;
  stop_hit: boolean | null;
  ticker: string | null;
  timeframe: string | null;
  risk_profile: string | null;
  direction: string | null;
  confidence: number | null;
  confidence_calibrated: number | null;
}

export interface AggregatePerformance {
  ready: boolean;
  reason?: string;
  total_validated: number;
  overall: {
    hit_rate: number;
    mean_outcome_score: number;
    mean_return_pct_eur: number | null;
  };
  by_cell: Record<
    string,
    {
      n: number;
      hit_rate: number;
      mean_outcome_score: number;
      mean_return_pct_eur: number | null;
    }
  >;
}

export interface RunLog {
  id: number;
  run_type: string;
  status: "running" | "ok" | "partial" | "failed";
  started_at: string;
  finished_at: string | null;
  code_sha: string | null;
  ollama_model: string | null;
  summary: Record<string, unknown> | null;
  errors: Record<string, string> | null;
}

export type ChartInterval = "15m" | "1h" | "4h" | "1d" | "1wk" | "1mo";

export interface ChartBar {
  /** UTC unix seconds for intraday intervals, "YYYY-MM-DD" for daily and longer. */
  time: number | string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface ChartData {
  ticker: string;
  interval: ChartInterval;
  name: string | null;
  exchange: string | null;
  currency: string | null;
  bars: ChartBar[];
}

export interface SymbolHit {
  symbol: string;
  name: string | null;
  exchange?: string | null;
  type?: string;
  source?: "watchlist" | "curated";
}

// ---- technical-analysis rules (same engine the daily scoring uses) ----
export interface TAPoint {
  time: number | string;
  value: number;
  color?: string;
}

export type TAOverlay =
  | { type: "line"; pane: string; name: string; color: string; data: TAPoint[];
      style?: "solid" | "dashed" | "dotted"; width?: number; guides?: number[] }
  | { type: "histogram"; pane: string; name: string; data: TAPoint[] }
  | { type: "levels"; levels: { price: number; label: string; color: string }[] }
  | { type: "segments"; segments: { points: TAPoint[]; color: string; dashed: boolean; label?: string | null }[] }
  | { type: "background"; data: TAPoint[] };

export interface TARule {
  id: string;
  name: string;
  category: string;
  module: "technical" | "mean_reversion" | "momentum";
  description: string;
  score: number;
  state: -1 | 0 | 1;
  status: string;
  available: boolean;
  meta: Record<string, unknown>;
  /** track record of this rule's signals on this ticker (price move after each signal) */
  stats: Record<"buy" | "sell", SignalStats> | null;
}

export interface SignalStats {
  n: number;
  n_eval_5: number;
  n_eval_20: number;
  win_5?: number;
  win_20?: number;
  avg_5?: number;
  avg_20?: number;
}

export interface TAEvent {
  time: number | string;
  rule: string;
  side: "buy" | "sell";
  label: string;
  price?: number;
  /** price change 5 / 20 bars after the signal (null = too recent) */
  ret_5?: number | null;
  ret_20?: number | null;
}

export interface TAData {
  rules: TARule[];
  events: TAEvent[];
  overlays: Record<string, TAOverlay[]>;
  /** how often ANY bar was followed by a rise — the bar a rule has to beat */
  base_rate?: { up_5?: number; avg_5?: number; up_20?: number; avg_20?: number };
  summary: {
    technical: { score: number; amplifier: number; htf_state: number; htf_conflict: boolean };
    mean_reversion: { score: number };
    relative_strength: { score: number; benchmark: string | null };
    interval: ChartInterval;
    bars_evaluated: number;
  };
}

// ---- full analysis of one ticker (live, same scoring as the daily run) ----
export interface ModuleResultFull {
  module: string;
  score: number | null;
  direction: "bullish" | "bearish" | "neutral";
  confidence: number;
  horizon_weights: Record<Timeframe, number>;
  raw: Record<string, any>;
  notes: string[];
  data_quality: "full" | "partial" | "missing";
  errors: string[];
}

export interface CellContributor {
  module: string;
  score: number;
  confidence: number;
  horizon_w: number;
  cell_w: number;
  weighted_contrib: number;
}

export interface AnalysisCell {
  risk_profile: RiskProfile;
  timeframe: Timeframe;
  direction: Direction;
  score: number;
  confidence: number;
  filter_passed: boolean;
  filter_reason: string | null;
  contributors: CellContributor[];
  notes: string[];
}

export interface FullAnalysis {
  ticker: string;
  name: string | null;
  asset_type: "equity" | "etf";
  currency: string | null;
  exchange: string | null;
  sector: string | null;
  last_close: number;
  last_date: string;
  benchmark: string | null;
  computed_at: string;
  modules: Record<string, ModuleResultFull>;
  profile_weights: Record<RiskProfile, Record<string, number>>;
  cells: AnalysisCell[];
  thresholds: { direction: number; min_confidence: number };
  data_errors: Record<string, string>;
  stored: {
    date: string | null;
    cells: { id: number; risk_profile: RiskProfile; timeframe: Timeframe; direction: Direction; confidence: number; headline: string | null }[];
  };
  cached: boolean;
}

// ---- similar-situation (analog) analysis — information only, not scored ----
export interface AnalogStats {
  n: number;
  up?: number;
  median?: number;
  mean?: number;
  p10?: number;
  p90?: number;
  best?: number;
  worst?: number;
}

export interface AnalogMatch {
  time: string;
  close: number;
  similarity: number;
  distance: number;
  ret_5: number | null;
  ret_20: number | null;
  ret_60: number | null;
  dip_20?: number;
  peak_20?: number;
  features: Record<string, number | null>;
}

export interface AnalogView {
  available: true;
  source: { symbol: string; name: string; is_proxy: boolean };
  today: Record<string, number | null>;
  matches: AnalogMatch[];
  paths: { time: string; values: number[] }[];
  summary: Record<"5" | "20" | "60", { analogs: AnalogStats; base: AnalogStats }> & { dip_20: AnalogStats };
  verdict: { tone: "better" | "worse" | "similar" | "inconclusive"; text: string };
  history_bars: number;
  history_from: string;
  params: { k: number; min_gap: number; horizons: number[] };
}

export interface AnalogResponse {
  available: boolean;
  reason?: string;
  primary?: "own" | "proxy";
  views?: Partial<Record<"own" | "proxy", AnalogView>>;
  today?: Record<string, number | null>;
  features?: { key: string; label: string; weight: number; fmt: string }[];
  own_bars?: number;
}

export interface LogLine {
  id: number;
  ts: string;
  level: "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";
  logger: string;
  msg: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} on ${path}`);
  return r.json() as Promise<T>;
}

function qs(params: Record<string, string | number | undefined | null>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  if (entries.length === 0) return "";
  return "?" + entries.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join("&");
}

export const api = {
  health: () => request<HealthResponse>("/health"),

  suggestions: {
    list: (filters: {
      on_date?: string;
      risk?: RiskProfile;
      timeframe?: Timeframe;
      ticker?: string;
      direction?: Direction;
      limit?: number;
    } = {}) => request<Suggestion[]>(`/api/suggestions/${qs(filters)}`),
    get: (id: number) => request<SuggestionDetail>(`/api/suggestions/${id}`),
    byTicker: (ticker: string) =>
      request<SuggestionDetail[]>(`/api/suggestions/by-ticker/${encodeURIComponent(ticker)}`),
    distinctDates: () => request<string[]>("/api/suggestions/distinct-dates"),
    distinctTickers: () => request<string[]>("/api/suggestions/distinct-tickers"),
  },

  watchlist: {
    list: () => request<WatchlistItem[]>("/api/watchlist/"),
    add: async (ticker: string, note?: string) => {
      // Use raw fetch so we can read the FastAPI 422/400 body shape on validation failures.
      const r = await fetch("/api/watchlist/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker, note }),
      });
      const body = await r.json();
      if (!r.ok) {
        const detail = body?.detail ?? body;
        throw Object.assign(new Error(detail?.message ?? `${r.status}`), {
          status: r.status,
          detail,
        });
      }
      return body as TickerValidation & { note: string | null };
    },
    validate: (ticker: string) =>
      request<TickerValidation>(`/api/watchlist/validate/${encodeURIComponent(ticker)}`),
    remove: (ticker: string) =>
      request<{ removed: string }>(`/api/watchlist/${ticker}`, { method: "DELETE" }),
  },

  validations: {
    list: (limit = 200) => request<ValidationRow[]>(`/api/validations/?limit=${limit}`),
    aggregate: () => request<AggregatePerformance>("/api/validations/aggregate"),
  },

  providers: () => request<ProviderStatus[]>("/api/providers/"),

  runs: {
    list: (limit = 20, run_type?: string) =>
      request<RunLog[]>(`/api/runs/${qs({ limit, run_type })}`),
    latest: (run_type = "daily_pipeline") =>
      request<RunLog | null>(`/api/runs/latest${qs({ run_type })}`),
  },

  chart: {
    bars: (ticker: string, interval: ChartInterval) =>
      request<ChartData>(`/api/chart/bars/${encodeURIComponent(ticker)}${qs({ interval })}`),
    symbols: () => request<SymbolHit[]>("/api/chart/symbols"),
    search: (q: string) => request<SymbolHit[]>(`/api/chart/search${qs({ q })}`),
    analogs: (ticker: string) => request<AnalogResponse>(`/api/chart/analogs/${encodeURIComponent(ticker)}`),
    ta: (ticker: string, interval: ChartInterval) =>
      request<TAData>(`/api/chart/ta/${encodeURIComponent(ticker)}${qs({ interval })}`),
  },

  analysis: (ticker: string, refresh = false) =>
    request<FullAnalysis>(`/api/analysis/${encodeURIComponent(ticker)}${qs({ refresh: refresh ? "true" : undefined })}`),

  logs: (after = 0) =>
    request<{ lines: LogLine[]; last_id: number }>(`/api/logs/${qs({ after })}`),

  triggerDailyRun: () =>
    request<{ triggered: string }>("/api/run/daily", { method: "POST" }),
  triggerValidation: () =>
    request<{ triggered: string }>("/api/run/validate", { method: "POST" }),
  triggerTickerRun: (ticker: string) =>
    request<{ triggered: string; ticker: string }>(
      `/api/run/ticker/${encodeURIComponent(ticker)}`,
      { method: "POST" },
    ),
};
