import { useEffect, useMemo, useRef, useState } from "react";
import { api, type SymbolHit } from "../../lib/api";

interface Props {
  value: string;
  onSelect: (symbol: string) => void;
}

/** Symbol picker: the app's own universe instantly, plus Yahoo search for anything else. */
export default function SymbolSearch({ value, onSelect }: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [local, setLocal] = useState<SymbolHit[]>([]);
  const [remote, setRemote] = useState<SymbolHit[]>([]);
  const [active, setActive] = useState(0);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.chart.symbols().then(setLocal).catch(() => setLocal([]));
  }, []);

  // debounced Yahoo search
  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setRemote([]);
      return;
    }
    const id = setTimeout(() => {
      api.chart.search(q).then(setRemote).catch(() => setRemote([]));
    }, 300);
    return () => clearTimeout(id);
  }, [query]);

  // close when clicking outside
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const hits = useMemo(() => {
    const q = query.trim().toUpperCase();
    const mine = local.filter(
      (h) => !q || h.symbol.toUpperCase().includes(q) || (h.name ?? "").toUpperCase().includes(q),
    );
    const seen = new Set(mine.map((h) => h.symbol));
    return [...mine.slice(0, 12), ...remote.filter((h) => !seen.has(h.symbol))];
  }, [query, local, remote]);

  function choose(symbol: string) {
    onSelect(symbol.trim().toUpperCase());
    setQuery("");
    setOpen(false);
  }

  function onKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, hits.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      // a highlighted hit, or whatever was typed (any Yahoo symbol works)
      if (hits[active] && query.trim()) choose(hits[active].symbol);
      else if (query.trim()) choose(query);
    } else if (e.key === "Escape") {
      setOpen(false);
      (e.target as HTMLInputElement).blur();
    }
  }

  return (
    <div ref={box} className="relative">
      <input
        value={open ? query : value}
        onChange={(e) => {
          setQuery(e.target.value);
          setActive(0);
          setOpen(true);
        }}
        onFocus={() => {
          setQuery("");
          setOpen(true);
        }}
        onKeyDown={onKey}
        placeholder="Symbol…"
        spellCheck={false}
        className="w-40 rounded border border-border bg-bg px-2 py-1 text-sm font-semibold uppercase tracking-wide focus:border-accent focus:outline-none"
      />
      {open && hits.length > 0 && (
        <ul className="absolute left-0 top-full z-30 mt-1 max-h-80 w-96 overflow-y-auto rounded border border-border bg-panel shadow-lg">
          {hits.map((h, i) => (
            <li key={`${h.symbol}-${i}`}>
              <button
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(h.symbol)}
                onMouseEnter={() => setActive(i)}
                className={`flex w-full items-center gap-3 px-3 py-1.5 text-left text-sm ${
                  i === active ? "bg-bg" : ""
                }`}
              >
                <span className="w-24 shrink-0 font-semibold">{h.symbol}</span>
                <span className="flex-1 truncate text-gray-400">{h.name ?? ""}</span>
                <span className="shrink-0 text-xs text-gray-500">
                  {h.source === "watchlist" ? "watchlist" : h.source === "curated" ? "ETF list" : h.exchange ?? h.type ?? ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
