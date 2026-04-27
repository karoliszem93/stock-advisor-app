import { useEffect, useState } from "react";
import { api, type WatchlistItem } from "../lib/api";

export default function Watchlist() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [ticker, setTicker] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    api.watchlist.list().then(setItems).catch(() => {});
  }, []);

  async function add() {
    if (!ticker.trim()) return;
    await api.watchlist.add(ticker.trim().toUpperCase(), note || undefined);
    setTicker("");
    setNote("");
    setItems(await api.watchlist.list());
  }

  async function remove(t: string) {
    await api.watchlist.remove(t);
    setItems(await api.watchlist.list());
  }

  return (
    <div className="max-w-3xl">
      <h2 className="text-2xl font-semibold mb-1">Watchlist</h2>
      <p className="text-sm text-gray-400 mb-6">
        Tickers analyzed every run regardless of broad-universe scans. Add the
        stocks/ETFs you actively follow on Trading 212.
      </p>

      <div className="rounded border border-border bg-panel/40 p-4 mb-6">
        <div className="flex gap-2">
          <input
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="AAPL"
            className="bg-bg border border-border rounded px-3 py-2 text-sm w-32"
          />
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="optional note"
            className="bg-bg border border-border rounded px-3 py-2 text-sm flex-1"
          />
          <button
            onClick={add}
            className="px-4 py-2 rounded bg-accent text-bg font-medium"
          >
            Add
          </button>
        </div>
      </div>

      <div className="rounded border border-border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-panel/60 text-gray-400 text-left">
            <tr>
              <th className="px-3 py-2 w-32">Ticker</th>
              <th className="px-3 py-2">Note</th>
              <th className="px-3 py-2 w-24"></th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr>
                <td className="px-3 py-4 text-gray-500" colSpan={3}>
                  No tickers yet — add some above.
                </td>
              </tr>
            )}
            {items.map((it) => (
              <tr key={it.ticker} className="border-t border-border">
                <td className="px-3 py-2 font-mono">{it.ticker}</td>
                <td className="px-3 py-2 text-gray-300">{it.note}</td>
                <td className="px-3 py-2">
                  <button
                    onClick={() => remove(it.ticker)}
                    className="text-danger text-xs hover:underline"
                  >
                    remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
