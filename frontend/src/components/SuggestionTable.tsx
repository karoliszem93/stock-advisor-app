import { Link } from "react-router-dom";
import type { Suggestion } from "../lib/api";
import Confidence from "./Confidence";
import DirectionBadge from "./DirectionBadge";

export default function SuggestionTable({
  suggestions,
}: {
  suggestions: Suggestion[];
}) {
  if (suggestions.length === 0) {
    return (
      <div className="rounded border border-border bg-panel/30 p-6 text-sm text-gray-400">
        No suggestions match the current filters.
      </div>
    );
  }

  return (
    <div className="rounded border border-border overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-panel/60 text-gray-400 text-left">
          <tr>
            <th className="px-3 py-2">Date</th>
            <th className="px-3 py-2">Ticker</th>
            <th className="px-3 py-2">Risk</th>
            <th className="px-3 py-2">TF</th>
            <th className="px-3 py-2">Direction</th>
            <th className="px-3 py-2">Conf</th>
            <th className="px-3 py-2">Entry €</th>
            <th className="px-3 py-2">Target €</th>
            <th className="px-3 py-2">Stop €</th>
            <th className="px-3 py-2">Target date</th>
            <th className="px-3 py-2 max-w-xl">Headline</th>
          </tr>
        </thead>
        <tbody>
          {suggestions.map((s) => (
            <tr
              key={s.id}
              className="border-t border-border hover:bg-panel/30 cursor-pointer"
            >
              <td className="px-3 py-2 text-gray-400">{s.suggestion_date}</td>
              <td className="px-3 py-2">
                <Link
                  to={`/ticker/${encodeURIComponent(s.ticker)}`}
                  className="font-mono hover:text-accent"
                >
                  {s.ticker}
                </Link>
              </td>
              <td className="px-3 py-2 capitalize">{s.risk_profile}</td>
              <td className="px-3 py-2 font-mono">{s.timeframe}</td>
              <td className="px-3 py-2">
                <DirectionBadge direction={s.direction} />
              </td>
              <td className="px-3 py-2">
                <Confidence raw={s.confidence} calibrated={s.confidence_calibrated} />
              </td>
              <td className="px-3 py-2 font-mono text-gray-300">
                {fmt(s.entry_price_eur)}
              </td>
              <td className="px-3 py-2 font-mono text-gray-300">
                {fmt(s.target_price_eur)}
              </td>
              <td className="px-3 py-2 font-mono text-gray-300">
                {fmt(s.stop_loss_eur)}
              </td>
              <td className="px-3 py-2 text-gray-400">{s.target_date}</td>
              <td className="px-3 py-2 text-gray-300">
                <Link to={`/suggestion/${s.id}`} className="hover:text-accent">
                  {s.headline ?? "—"}
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function fmt(n: number | null): string {
  if (n == null) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}
