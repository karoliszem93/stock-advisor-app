import { useEffect, useState } from "react";
import { api, type HealthResponse } from "../lib/api";

export default function Settings() {
  const [h, setH] = useState<HealthResponse | null>(null);
  useEffect(() => {
    api.health().then(setH).catch(() => {});
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
        <KV
          k="Path"
          v="~/.config/stock-advisor/github_token"
        />
        <KV
          k="Status"
          v={
            h?.config.github_pat_present ? "present" : "missing"
          }
        />
      </Section>

      <Section title="Data providers">
        {h &&
          Object.entries(h.config.providers_with_keys).map(([k, v]) => (
            <KV key={k} k={k} v={v ? "configured" : "no key"} />
          ))}
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded border border-border bg-panel/40 p-4 mb-4">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">{title}</h3>
      <dl className="text-sm divide-y divide-border">{children}</dl>
    </div>
  );
}

function KV({ k, v }: { k: string; v: string | undefined | null }) {
  return (
    <div className="flex justify-between py-1">
      <dt className="text-gray-400">{k}</dt>
      <dd className="font-mono">{v ?? "-"}</dd>
    </div>
  );
}
