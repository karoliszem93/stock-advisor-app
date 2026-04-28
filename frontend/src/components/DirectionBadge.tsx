import type { Direction } from "../lib/api";

const STYLE: Record<Direction, string> = {
  buy: "bg-accent/15 text-accent border-accent/40",
  avoid: "bg-gray-500/15 text-gray-400 border-gray-500/30",
  sell_short: "bg-danger/15 text-danger border-danger/40",
};

const LABEL: Record<Direction, string> = {
  buy: "BUY",
  avoid: "AVOID",
  sell_short: "SELL-SHORT",
};

export default function DirectionBadge({ direction }: { direction: Direction }) {
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-[10px] font-semibold tracking-wide border ${
        STYLE[direction]
      }`}
    >
      {LABEL[direction]}
    </span>
  );
}
