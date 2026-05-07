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
