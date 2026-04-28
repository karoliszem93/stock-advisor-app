import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type SuggestionDetail as SD } from "../lib/api";
import Confidence from "../components/Confidence";
import DirectionBadge from "../components/DirectionBadge";

export default function SuggestionDetail() {
  const { id } = useParams<{ id: string }>();
  const [s, setS] = useState<SD | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    api.suggestions.get(Number(id)).then(setS).catch((e) => setError(String(e)));
  }, [id]);

  if (error) {
    return (
      <div className="max-w-3xl">
        <div className="rounded border border-danger/40 bg-danger/10 p-3 text-sm">
          {error}
        </div>
      </div>
    );
  }
  if (!s) return <div className="text-gray-400">Loading...</div>;

  const r = s.rationale || {};

  return (
    <div className="max-w-4xl">
      <Link to="/" className="text-xs text-gray-400 hover:text-accent">
        ← back to dashboard
      </Link>

      <header className="my-4 flex items-center gap-3">
        <DirectionBadge direction={s.direction} />
        <Link
          to={`/ticker/${encodeURIComponent(s.ticker)}`}
          className="text-2xl font-mono font-semibold hover:text-accent"
        >
          {s.ticker}
        </Link>
        <span className="text-gray-400 text-sm">
          {s.risk_profile} · {s.timeframe} · {s.suggestion_date} → target {s.target_date}
        </span>
        <Confidence raw={s.confidence} calibrated={s.confidence_calibrated} />
      </header>

      {r.headline && (
        <p className="text-lg text-gray-200 mb-4">{r.headline}</p>
      )}

      {/* Prices */}
      <Section title="Plan">
        <div className="grid grid-cols-3 gap-3 text-sm">
          <KV label="Entry €" value={fmt(s.entry_price_eur)} />
          <KV label="Stop-loss €" value={fmt(s.stop_loss_eur)} />
          <KV label="Target €" value={fmt(s.target_price_eur)} />
          <KV
            label="Suggested risk"
            value={s.suggested_risk_pct != null ? `${(s.suggested_risk_pct * 100).toFixed(2)}% of capital` : "—"}
          />
          <KV label="Asset type" value={s.asset_type} />
          <KV label="Data quality" value={r.data_quality ?? "—"} />
        </div>
      </Section>

      {/* Rationale */}
      <Section title="Why this trade">
        <RationaleBlock title="Technical case" body={r.technical_case} />
        <RationaleBlock title="Fundamental case" body={r.fundamental_case} />
        <RationaleBlock title="Sentiment case" body={r.sentiment_case} />
        <RationaleBlock title="Macro context" body={r.macro_context} />
        <RationaleBlock title="Why this timeframe" body={r.why_this_timeframe} />
      </Section>

      {/* Risks + invalidation */}
      <Section title="Risks & invalidation">
        {(r.key_risks?.length ?? 0) > 0 && (
          <div className="mb-3">
            <div className="text-xs text-gray-400 uppercase tracking-wide mb-1">
              Key risks
            </div>
            <ul className="list-disc pl-5 text-sm text-gray-200 space-y-1">
              {r.key_risks!.map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
          </div>
        )}
        {(r.invalidation_triggers?.length ?? 0) > 0 && (
          <div className="mb-3">
            <div className="text-xs text-gray-400 uppercase tracking-wide mb-1">
              Invalidation triggers
            </div>
            <ul className="list-disc pl-5 text-sm text-gray-200 space-y-1">
              {r.invalidation_triggers!.map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
          </div>
        )}
        {r.counter_argument && (
          <div className="mb-3">
            <div className="text-xs text-gray-400 uppercase tracking-wide mb-1">
              Strongest counter-argument
            </div>
            <p className="text-sm text-gray-200">{r.counter_argument}</p>
          </div>
        )}
      </Section>

      {/* Confidence drivers */}
      {(r.confidence_drivers?.length ?? 0) > 0 && (
        <Section title="Confidence drivers">
          <table className="w-full text-sm">
            <thead className="text-gray-400 text-left">
              <tr>
                <th className="py-1 pr-2">Module</th>
                <th className="py-1 pr-2">Δ</th>
                <th className="py-1 pr-2">Reason</th>
              </tr>
            </thead>
            <tbody>
              {r.confidence_drivers!.map((d, i) => (
                <tr key={i} className="border-t border-border">
                  <td className="py-2 pr-2 font-mono">{d.factor}</td>
                  <td
                    className={`py-2 pr-2 font-mono ${
                      d.delta > 0 ? "text-accent" : d.delta < 0 ? "text-danger" : "text-gray-400"
                    }`}
                  >
                    {d.delta > 0 ? "+" : ""}{d.delta.toFixed(3)}
                  </td>
                  <td className="py-2 pr-2 text-gray-300">{d.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {/* Tax */}
      {r.tax_notes && (
        <Section title="Tax angle (LT-resident)">
          <p className="text-sm text-gray-200">{r.tax_notes}</p>
        </Section>
      )}

      {/* Price notes */}
      {(r.price_notes?.length ?? 0) > 0 && (
        <Section title="Price notes">
          <ul className="list-disc pl-5 text-xs text-gray-400 space-y-1">
            {r.price_notes!.map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded border border-border bg-panel/40 p-4 mb-4">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-3">{title}</h3>
      {children}
    </section>
  );
}

function RationaleBlock({ title, body }: { title: string; body: string | undefined }) {
  if (!body) return null;
  return (
    <div className="mb-3">
      <div className="text-xs text-gray-400 uppercase tracking-wide mb-1">
        {title}
      </div>
      <p className="text-sm text-gray-200 leading-relaxed">{body}</p>
    </div>
  );
}

function KV({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border bg-bg/40 p-2">
      <div className="text-[10px] text-gray-500 uppercase tracking-wide">{label}</div>
      <div className="font-mono">{value}</div>
    </div>
  );
}

function fmt(n: number | null): string {
  if (n == null) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}
