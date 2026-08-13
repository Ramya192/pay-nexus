// Dev-only (import.meta.env.DEV — stripped entirely from a production
// build, same gating App.tsx's old TokenUsageLine used). All four alerts
// in utils/alerts.ts are date-windowed (ITR: Jun-Jul, regime: Feb-Apr,
// headroom: Jan-Mar) or data-windowed (stale payslip: 2+ months since the
// last saved snapshot) — real "today" only lands inside one of those a few
// months a year, so without this there's no way to actually see three of
// the four render without either waiting or changing your system clock.
// Overrides the date passed into computeAlerts(); never touches real data.
const PREVIEW_DATES: Record<string, Date | null> = {
  real: null,
  itr: new Date(new Date().getFullYear(), 6, 26), // July 26 — inside the ITR reminder window
  regime: new Date(new Date().getFullYear(), 2, 15), // March 15 — inside the regime-declaration window
  headroom: new Date(new Date().getFullYear(), 1, 10), // February 10 — inside the deduction-headroom window
};

export function DevAlertPreview({
  value,
  onChange,
}: {
  value: string;
  onChange: (key: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-dashed border-amber-300 bg-amber-50 px-4 py-1.5 text-xs text-amber-800">
      <span className="font-medium">Dev preview — pretend today is:</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-amber-300 bg-white px-1.5 py-0.5 text-xs"
      >
        <option value="real">Today (real date)</option>
        <option value="itr">Jul 26 — ITR filing deadline window</option>
        <option value="regime">Mar 15 — regime declaration window</option>
        <option value="headroom">Feb 10 — deduction headroom window</option>
      </select>
      {value === "headroom" && (
        <span>— also needs the "Investments &amp; loans" tab filled in to actually appear</span>
      )}
      <span className="text-amber-600">
        (stale-payslip isn't date-based — it shows on its own once a saved snapshot is 2+ months old)
      </span>
    </div>
  );
}

export function resolvePreviewDate(key: string): Date {
  return PREVIEW_DATES[key] ?? new Date();
}
