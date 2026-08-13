import { Check, CircleDashed } from "lucide-react";
import { usePayslipStore } from "../../store/payslipStore";

/**
 * Persistent — not just a one-off click confirmation — answer to "is a
 * payslip actually driving my chat answers right now." Found missing when
 * a user clicked "Use this payslip" and, with no feedback at all, clicked
 * it several more times unsure whether anything had happened. A button-
 * level checkmark alone only helps at the moment of the click; this stays
 * visible the whole time a payslip is (or isn't) active this session.
 */
export function ActivePayslipBanner() {
  const payslipData = usePayslipStore((s) => s.payslipData);
  const month = typeof payslipData?.month === "string" ? payslipData.month : null;

  if (!payslipData) {
    return (
      <p className="mb-3 flex items-center gap-1.5 rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-500">
        <CircleDashed className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        No payslip active this session — chat answers about "this payslip" won't have anything to
        go on until you click "Use this payslip" below.
      </p>
    );
  }

  return (
    <p className="mb-3 flex items-center gap-1.5 rounded-md bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-700">
      <Check className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      Active this session: {month ? `payslip for ${month}` : "a payslip"} — driving chat answers now.
    </p>
  );
}
