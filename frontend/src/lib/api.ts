// Typed fetch helpers. Base URL is the same origin (Vite proxies /api and /health).

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

export interface Suggestion {
  id: number;
  suggestion_date: string;
  ticker: string;
  asset_type: string;
  timeframe: string;
  risk_profile: string;
  direction: "buy" | "avoid" | "sell_short";
  confidence: number;
  confidence_calibrated: number | null;
  target_date: string;
  headline: string | null;
  entry_price_eur: number | null;
  stop_loss_eur: number | null;
  target_price_eur: number | null;
  suggested_risk_pct: number | null;
}

export interface WatchlistItem {
  ticker: string;
  note: string | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} on ${path}`);
  return r.json() as Promise<T>;
}

export const api = {
  health: () => request<HealthResponse>("/health"),
  suggestions: () => request<Suggestion[]>("/api/suggestions/"),
  watchlist: {
    list: () => request<WatchlistItem[]>("/api/watchlist/"),
    add: (ticker: string, note?: string) =>
      request<WatchlistItem>("/api/watchlist/", {
        method: "POST",
        body: JSON.stringify({ ticker, note }),
      }),
    remove: (ticker: string) =>
      request<{ removed: string }>(`/api/watchlist/${ticker}`, { method: "DELETE" }),
  },
  validations: () => request<unknown[]>("/api/validations/"),
  triggerDailyRun: () =>
    request<{ triggered: string }>("/api/run/daily", { method: "POST" }),
};
