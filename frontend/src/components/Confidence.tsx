/** Visual confidence pill — color-graded by level. */
export default function Confidence({
  raw,
  calibrated,
}: {
  raw: number;
  calibrated: number | null | undefined;
}) {
  const v = calibrated ?? raw;
  const pct = Math.round(v * 100);
  const cls =
    v >= 0.7
      ? "bg-accent/20 text-accent border-accent/40"
      : v >= 0.5
      ? "bg-warn/20 text-warn border-warn/40"
      : "bg-gray-500/20 text-gray-400 border-gray-500/30";

  return (
    <span
      title={
        calibrated != null
          ? `raw=${(raw * 100).toFixed(0)}% · calibrated=${pct}%`
          : `raw=${pct}% (uncalibrated; <50 validations)`
      }
      className={`inline-block px-2 py-0.5 rounded text-xs font-mono border ${cls}`}
    >
      {pct}%
      {calibrated == null && <span className="opacity-60 ml-1">(raw)</span>}
    </span>
  );
}
