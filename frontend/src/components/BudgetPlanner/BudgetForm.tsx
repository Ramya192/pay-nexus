import { Check } from "lucide-react";
import { useEffect, useState, type ChangeEvent, type FormEvent } from "react";
import { fetchSuggestedBudget, saveBudget } from "../../api/budget";
import { encryptJSON } from "../../crypto/clientEncryption";
import { useAuthStore } from "../../store/authStore";
import { BUDGET_CATEGORIES, useBudgetStore } from "../../store/budgetStore";
import { usePayslipStore } from "../../store/payslipStore";

// Rough monthly-gross estimate for the suggested-budget pre-fill only — not
// the same precision as backend/tax_slabs.py's estimate_annual_gross_income
// (which also uses payslip_history and a proper method note); this is just
// enough to pick a sensible starting salary bracket, still fully editable
// before anything is saved.
const _GROSS_FIELDS = ["basic", "hra", "specialAllowance", "bonus"];

function roughMonthlyIncome(payslipData: Record<string, unknown> | null): number | undefined {
  if (!payslipData) return undefined;
  const total = _GROSS_FIELDS.reduce((sum, key) => {
    const v = payslipData[key];
    return sum + (typeof v === "number" ? v : 0);
  }, 0);
  return total > 0 ? total : undefined;
}

/**
 * Set per-category monthly budget targets — prefilled from GET
 * /budget/suggested (a salary-bracket-scaled default) on first visit if
 * nothing is saved yet, then fully editable before saving. Overspending
 * analysis itself happens in chat (agents/budget_agent.py) against
 * whatever's saved here, not computed in this component — same "form to
 * set the data, chat to reason over it" split as PayslipUploader/
 * FinancialProfileForm.
 */
export function BudgetForm() {
  const aesKey = useAuthStore((s) => s.aesKey);
  const payslipData = usePayslipStore((s) => s.payslipData);
  const storedBudget = useBudgetStore((s) => s.budget);
  const setStoreBudget = useBudgetStore((s) => s.setBudget);

  const [values, setValues] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<"idle" | "loading" | "saving" | "saved" | "error">("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (storedBudget) {
      const next: Record<string, string> = {};
      for (const category of BUDGET_CATEGORIES) {
        if (typeof storedBudget[category] === "number") next[category] = String(storedBudget[category]);
      }
      setValues(next);
      setStatus("idle");
      return;
    }

    // Nothing saved yet — pre-fill from a salary-bracket-scaled suggestion.
    let cancelled = false;
    fetchSuggestedBudget(roughMonthlyIncome(payslipData))
      .then((suggested) => {
        if (cancelled) return;
        const next: Record<string, string> = {};
        for (const category of BUDGET_CATEGORIES) {
          if (typeof suggested.budgets[category] === "number") next[category] = String(suggested.budgets[category]);
        }
        setValues(next);
        setStatus("idle");
      })
      .catch(() => {
        if (!cancelled) setStatus("idle"); // fall back to a blank form, still usable
      });
    return () => {
      cancelled = true;
    };
    // Only re-run if storedBudget itself changes identity (e.g. login
    // hydration landing later) — not on every payslipData keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storedBudget]);

  function handleChange(category: string, value: string) {
    setValues((v) => ({ ...v, [category]: value }));
    setStatus("idle");
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!aesKey) return;

    const budget: Record<string, number> = {};
    for (const category of BUDGET_CATEGORIES) {
      const raw = values[category];
      if (raw === undefined || raw === "") continue;
      budget[category] = Number(raw);
    }

    setStatus("saving");
    setError(null);
    try {
      const blob = await encryptJSON(aesKey, budget);
      await saveBudget(blob);
      setStoreBudget(budget);
      setStatus("saved");
    } catch {
      setStatus("error");
      setError("Couldn't save your budget — try again.");
    }
  }

  if (status === "loading") {
    return <p className="text-xs text-slate-400">Loading…</p>;
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      {BUDGET_CATEGORIES.map((category) => (
        <div key={category} className="space-y-1">
          <label className="block text-xs font-medium text-slate-600" htmlFor={`budget-${category}`}>
            {category} (₹/month)
          </label>
          <input
            id={`budget-${category}`}
            type="number"
            min="0"
            value={values[category] ?? ""}
            onChange={(e: ChangeEvent<HTMLInputElement>) => handleChange(category, e.target.value)}
            className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
      ))}

      <button
        type="submit"
        disabled={status === "saving"}
        className="flex w-full items-center justify-center gap-1.5 rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
      >
        {status === "saved" && <Check className="h-3.5 w-3.5" aria-hidden="true" />}
        {status === "saving" ? "Saving…" : status === "saved" ? "Saved" : "Save budget"}
      </button>
      {error && <p className="text-xs text-red-600">{error}</p>}
      <p className="text-xs text-slate-400">
        Starting figures are a rough, salary-bracket-scaled suggestion — edit freely. Ask the
        BudgetPlanner in chat once you've saved a bank statement to see actual overspending alerts
        against these targets.
      </p>
    </form>
  );
}
