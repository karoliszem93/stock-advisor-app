export default function Validations() {
  return (
    <div className="max-w-4xl">
      <h2 className="text-2xl font-semibold mb-1">Validation history</h2>
      <p className="text-sm text-gray-400 mb-6">
        Track record of past suggestions, scored once their target_date hits.
        Populated from Phase 4 onward.
      </p>
      <div className="rounded border border-border bg-panel/30 p-6 text-sm text-gray-400">
        No validations yet. Once daily runs accumulate suggestions and their
        target dates arrive, results will appear here with EUR-denominated
        returns split into price / dividends / FX / tax components.
      </div>
    </div>
  );
}
