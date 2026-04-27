import { useEffect, useState } from "react";
import { api, type HealthResponse, type ProviderStatus } from "../lib/api";

export default function Settings() {
  const [h, setH] = useState<HealthResponse | null>(null);
  const [providers, setProviders] = useState<ProviderStatus[]>([]);

  useEffect(() => {
    api.health().then(setH).catch(() => {});
    api.providers().then(setProviders).catch(() => {});
  }, []);

  return (
    <div className="max-w-3xl">
      <h2 className="text-2xl font-semibold mb-1">Settings</h2>
      <p className="text-sm text-gray-400 mb-6">
        Read-only view of current configuration. Edit values in
        <code className="mx-1 px-1 bg-panel rounded">backend/.env</code>
        and restart the backend.
      </p>

      <Section title="Schedule">
        <KV k="Timezone" v={h?.timezone} />
        <KV k="Cron" v={h?.schedule} />
      </Section>

      <Section title="LLM (Ollama)">
        <KV k="Host" v={h?.config.ollama_host} />
        <KV k="Model" v={h?.config.ollama_model} />
      </Section>

      <Section title="GitHub PAT">
        <KV k="Path" v="~/.config/stock-advisor/github_token" />
        <KV
          k="Status"
          v={h?.config.github_pat_present ? "present" : "missing"}
        />
      </Section>

      <Section title="Data providers">
        <table className="w-full text-sm">
          <thead className="text-gray-500 text-left">
            <tr>
              <th className="py-1 pr-2">Provider</th>
              <th className="py-1 pr-2">Status</th>
              <th className="py-1 pr-2">Quota</th>
              <th className="py-1 pr-2">Get key</th>
            </tr>
          </thead>
          <tbody>
            {providers.map((p) => (
              <tr key={p.name} className="border-t border-border align-top">
                <td className="py-2 pr-2">
                  <div className="font-mono">{p.name}</div>
                  <div className="text-xs text-gray-500">{p.description}</div>
                </td>
                <td className="py-2 pr-2">
                  {p.key_setting === null ? (
                    <span className="text-accent">no key needed</span>
                  ) : p.key_present ? (
                    <span className="text-accent">configured</span>
                  ) : (
                    <span className="text-warn">no key</span>
                  )}
                </td>
                <td className="py-2 pr-2 text-xs text-gray-400">
                  {p.rate_limit.used}/{p.rate_limit.capacity} per{" "}
                  {Math.round(p.rate_limit.window_seconds / 3600)}h
                </td>
                <td className="py-2 pr-2">
                  {p.key_source_url && !p.key_present ? (
                    <a
                      href={p.key_source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-accent text-xs hover:underline"
                    >
                      get key →
                    </a>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded border border-border bg-panel/40 p-4 mb-4">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">{title}</h3>
      <div className="text-sm">{children}</div>
    </div>
  );
}

function KV({ k, v }: { k: string; v: string | undefined | null }) {
  return (
    <div className="flex justify-between py-1 border-b border-border last:border-b-0">
      <span className="text-gray-400">{k}</span>
      <span className="font-mono">{v ?? "-"}</span>
    </div>
  );
}
