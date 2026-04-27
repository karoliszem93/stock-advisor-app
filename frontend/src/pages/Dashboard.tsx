import { useEffect, useState } from "react";
import { api, type HealthResponse, type Suggestion } from "../lib/api";

export default function Dashboard() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.health().then(setHealth).catch((e) => setError(String(e)));
    api.suggestions().then(setSuggestions).catch(() => {});
  }, []);

  async function runNow() {
    setBusy(true);
    try {
      await api.triggerDailyRun();
      // Pipeline is async on the server. UI can poll /health or refresh later.
      setTimeout(() => api.suggestions().then(setSuggestions), 1500);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-5xl">
      <header className="mb-6">
        <h2 className="text-2xl font-semibold">Today's suggestions</h2>
        <p className="text-sm text-gray-400 mt-1">
          {health?.schedule ?? "Loading scheduler config..."}
        </p>
      </header>

      {error && (
        <div className="mb-4 rounded border border-danger/40 bg-danger/10 p-3 text-sm">
          {error}
        </div>
      )}

      <section className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <Card title="Backend">
          {health ? (
            <ul className="text-sm space-y-1">
              <li>Version: {health.version}</li>
              <li>Currency: {health.config.base_currency}</li>
              <li>
                GitHub PAT:{" "}
                {health.config.github_pat_present ? (
                  <span className="text-accent">present</span>
                ) : (
                  <span className="text-warn">missing</span>
                )}
              </li>
              <li>Ollama: {health.config.ollama_model}</li>
            </ul>
          ) : (
            <span className="text-gray-500">connecting...</span>
          )}
        </Card>
        <Card title="Data providers">
          {health ? (
            <ul className="text-sm space-y-1">
              {Object.entries(health.config.providers_with_keys).map(([k, v]) => (
                <li key={k} className="flex justify-between">
                  <span>{k}</span>
                  <span className={v ? "text-accent" : "text-gray-500"}>
                    {v ? "configured" : "no key yet"}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <span className="text-gray-500">...</span>
          )}
        </Card>
      </section>

      <section className="mb-6">
        <button
          onClick={runNow}
          disabled={busy}
          className="px-4 py-2 rounded bg-accent text-bg font-medium disabled:opacity-50"
        >
          {busy ? "Triggering..." : "Run pipeline now"}
        </button>
        <span className="ml-3 text-xs text-gray-500">
          Async — refresh in a moment to see results once Phase 3 ships.
        </span>
      </section>

      <section>
        <h3 className="text-lg font-medium mb-3">Suggestions</h3>
        {suggestions.length === 0 ? (
          <div className="rounded border border-border bg-panel/30 p-6 text-sm text-gray-400">
            No suggestions yet. The pipeline is a no-op skeleton until Phase 3 ships
            (Ollama-driven synthesis).
          </div>
        ) : (
          <div className="rounded border border-border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-panel/60 text-gray-400 text-left">
                <tr>
                  <th className="px-3 py-2">Date</th>
                  <th className="px-3 py-2">Ticker</th>
                  <th className="px-3 py-2">Risk</th>
                  <th className="px-3 py-2">Timeframe</th>
                  <th className="px-3 py-2">Direction</th>
                  <th className="px-3 py-2">Conf</th>
                  <th className="px-3 py-2">Headline</th>
                </tr>
              </thead>
              <tbody>
                {suggestions.map((s) => (
                  <tr key={s.id} className="border-t border-border">
                    <td className="px-3 py-2">{s.suggestion_date}</td>
                    <td className="px-3 py-2 font-mono">{s.ticker}</td>
                    <td className="px-3 py-2">{s.risk_profile}</td>
                    <td className="px-3 py-2">{s.timeframe}</td>
                    <td className="px-3 py-2 uppercase">{s.direction}</td>
                    <td className="px-3 py-2">
                      {(s.confidence * 100).toFixed(0)}%
                    </td>
                    <td className="px-3 py-2 text-gray-300">{s.headline}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded border border-border bg-panel/40 p-4">
      <div className="text-xs text-gray-400 uppercase tracking-wide mb-2">
        {title}
      </div>
      {children}
    </div>
  );
}
