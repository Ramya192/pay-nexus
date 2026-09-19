import { useState, type ChangeEvent, type FormEvent } from "react";
import { createGoal } from "../../api/goals";
import { encryptJSON } from "../../crypto/clientEncryption";
import { useAuthStore } from "../../store/authStore";
import {
  GOAL_CATEGORIES,
  useGoalStore,
  type Goal,
  type GoalCategory,
  type InstrumentType,
} from "../../store/goalStore";

/**
 * Add a new savings goal — Trip, Home Loan, Education, etc. Persists
 * {name, category, targetAmount, targetDate, savedAmount, ...instrument
 * fields} encrypted (same client-side-encryption-before-network-call
 * contract as FinancialProfileForm.tsx). "Track manually" is the default
 * and everything V2 ever supported; "Fixed deposit"/"Mutual fund" (V2.1)
 * additionally get a live current-value lookup instead of a hand-typed
 * "already saved" figure — see GoalList.tsx, which does that fetch.
 */
export function GoalForm() {
  const aesKey = useAuthStore((s) => s.aesKey);
  const addEntry = useGoalStore((s) => s.addEntry);

  const [name, setName] = useState("");
  const [category, setCategory] = useState<GoalCategory>("Trip");
  const [targetAmount, setTargetAmount] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const [savedAmount, setSavedAmount] = useState("");
  const [instrumentType, setInstrumentType] = useState<InstrumentType | "manual">("manual");
  const [fdPrincipal, setFdPrincipal] = useState("");
  const [fdAnnualRate, setFdAnnualRate] = useState("");
  const [fdStartDate, setFdStartDate] = useState("");
  const [mfSchemeCode, setMfSchemeCode] = useState("");
  const [mfUnitsHeld, setMfUnitsHeld] = useState("");
  const [status, setStatus] = useState<"idle" | "saving" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!aesKey) return;
    if (!name.trim() || !targetAmount) {
      setError("Name and target amount are required.");
      return;
    }
    if (instrumentType === "fd" && (!fdPrincipal || !fdAnnualRate || !fdStartDate)) {
      setError("Principal, annual rate, and start date are required for a fixed deposit.");
      return;
    }
    if (instrumentType === "mutual_fund" && (!mfSchemeCode || !mfUnitsHeld)) {
      setError("Scheme code and units held are required for a mutual fund.");
      return;
    }

    const goal: Goal = {
      name: name.trim(),
      category,
      targetAmount: Number(targetAmount),
      targetDate: targetDate || undefined,
      // For an instrument-linked goal, this is only ever a starting/last-
      // known figure — GoalList.tsx overwrites the DISPLAYED value with a
      // live lookup as soon as it loads. Still meaningful to save: it's
      // what shows before that first live fetch completes, and what's
      // there if the live lookup fails.
      savedAmount: savedAmount ? Number(savedAmount) : 0,
      ...(instrumentType === "fd" && {
        instrumentType: "fd" as const,
        fdPrincipal: Number(fdPrincipal),
        fdAnnualRate: Number(fdAnnualRate),
        fdStartDate,
      }),
      ...(instrumentType === "mutual_fund" && {
        instrumentType: "mutual_fund" as const,
        mfSchemeCode: mfSchemeCode.trim(),
        mfUnitsHeld: Number(mfUnitsHeld),
      }),
    };

    setError(null);
    setStatus("saving");
    try {
      const blob = await encryptJSON(aesKey, goal);
      const saved = await createGoal(blob);
      addEntry({ id: saved.id, createdAt: saved.created_at, data: goal });
      setName("");
      setTargetAmount("");
      setTargetDate("");
      setSavedAmount("");
      setInstrumentType("manual");
      setFdPrincipal("");
      setFdAnnualRate("");
      setFdStartDate("");
      setMfSchemeCode("");
      setMfUnitsHeld("");
      setStatus("idle");
    } catch {
      setStatus("error");
      setError("Couldn't save that goal — try again.");
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3 rounded-md border border-slate-200 p-3">
      <div className="space-y-1">
        <label className="block text-xs font-medium text-slate-600" htmlFor="goal-name">
          Goal name
        </label>
        <input
          id="goal-name"
          type="text"
          value={name}
          onChange={(e: ChangeEvent<HTMLInputElement>) => setName(e.target.value)}
          placeholder="e.g. Goa Trip, Home Loan Down Payment"
          className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
        />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <label className="block text-xs font-medium text-slate-600" htmlFor="goal-category">
            Category
          </label>
          <select
            id="goal-category"
            value={category}
            onChange={(e: ChangeEvent<HTMLSelectElement>) => setCategory(e.target.value as GoalCategory)}
            className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          >
            {GOAL_CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <label className="block text-xs font-medium text-slate-600" htmlFor="goal-target-date">
            Target date <span className="font-normal text-slate-400">(optional)</span>
          </label>
          <input
            id="goal-target-date"
            type="date"
            value={targetDate}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setTargetDate(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <label className="block text-xs font-medium text-slate-600" htmlFor="goal-target-amount">
            Target amount (₹)
          </label>
          <input
            id="goal-target-amount"
            type="number"
            min="0"
            value={targetAmount}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setTargetAmount(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
        <div className="space-y-1">
          <label className="block text-xs font-medium text-slate-600" htmlFor="goal-saved-amount">
            {instrumentType === "manual" ? (
              <>
                Already saved (₹) <span className="font-normal text-slate-400">(optional)</span>
              </>
            ) : (
              <>
                Starting value (₹) <span className="font-normal text-slate-400">(shown until the first live lookup)</span>
              </>
            )}
          </label>
          <input
            id="goal-saved-amount"
            type="number"
            min="0"
            value={savedAmount}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setSavedAmount(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
      </div>

      <div className="space-y-1">
        <label className="block text-xs font-medium text-slate-600" htmlFor="goal-instrument-type">
          Track this goal's value
        </label>
        <select
          id="goal-instrument-type"
          value={instrumentType}
          onChange={(e: ChangeEvent<HTMLSelectElement>) => setInstrumentType(e.target.value as InstrumentType | "manual")}
          className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
        >
          <option value="manual">Manually (type in progress myself)</option>
          <option value="fd">Fixed deposit (auto-computed from principal + rate)</option>
          <option value="mutual_fund">Mutual fund (live NAV lookup by scheme code)</option>
        </select>
      </div>

      {instrumentType === "fd" && (
        <div className="grid grid-cols-3 gap-2 rounded-md bg-slate-50 p-2">
          <div className="space-y-1">
            <label className="block text-xs font-medium text-slate-600" htmlFor="fd-principal">
              Principal (₹)
            </label>
            <input
              id="fd-principal"
              type="number"
              min="0"
              value={fdPrincipal}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setFdPrincipal(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
          </div>
          <div className="space-y-1">
            <label className="block text-xs font-medium text-slate-600" htmlFor="fd-rate">
              Annual rate (%)
            </label>
            <input
              id="fd-rate"
              type="number"
              min="0"
              step="0.1"
              value={fdAnnualRate}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setFdAnnualRate(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
          </div>
          <div className="space-y-1">
            <label className="block text-xs font-medium text-slate-600" htmlFor="fd-start-date">
              Opened on
            </label>
            <input
              id="fd-start-date"
              type="date"
              value={fdStartDate}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setFdStartDate(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
          </div>
        </div>
      )}

      {instrumentType === "mutual_fund" && (
        <div className="grid grid-cols-2 gap-2 rounded-md bg-slate-50 p-2">
          <div className="space-y-1">
            <label className="block text-xs font-medium text-slate-600" htmlFor="mf-scheme-code">
              AMFI scheme code
            </label>
            <input
              id="mf-scheme-code"
              type="text"
              value={mfSchemeCode}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setMfSchemeCode(e.target.value)}
              placeholder="e.g. 119598"
              className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
          </div>
          <div className="space-y-1">
            <label className="block text-xs font-medium text-slate-600" htmlFor="mf-units">
              Units held
            </label>
            <input
              id="mf-units"
              type="number"
              min="0"
              step="0.001"
              value={mfUnitsHeld}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setMfUnitsHeld(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
          </div>
        </div>
      )}

      <button
        type="submit"
        disabled={status === "saving"}
        className="w-full rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
      >
        {status === "saving" ? "Saving…" : "Add goal"}
      </button>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </form>
  );
}
