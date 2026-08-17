import { useState, type ChangeEvent, type FormEvent } from "react";
import { createGoal } from "../../api/goals";
import { encryptJSON } from "../../crypto/clientEncryption";
import { useAuthStore } from "../../store/authStore";
import { GOAL_CATEGORIES, useGoalStore, type Goal, type GoalCategory } from "../../store/goalStore";

/**
 * Add a new savings goal — Trip, Home Loan, Education, etc. UI-only for
 * V2: this just persists {name, category, targetAmount, targetDate,
 * savedAmount} encrypted (same client-side-encryption-before-network-call
 * contract as FinancialProfileForm.tsx). The GoalTracker LangGraph agent
 * that would narrate progress and pull live FD/stock prices isn't built
 * yet — see PROJECT_CONTEXT.md's V2 Phase 3 — so goals aren't sent to
 * /chat or reasoned over yet, just tracked here.
 */
export function GoalForm() {
  const aesKey = useAuthStore((s) => s.aesKey);
  const addEntry = useGoalStore((s) => s.addEntry);

  const [name, setName] = useState("");
  const [category, setCategory] = useState<GoalCategory>("Trip");
  const [targetAmount, setTargetAmount] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const [savedAmount, setSavedAmount] = useState("");
  const [status, setStatus] = useState<"idle" | "saving" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!aesKey) return;
    if (!name.trim() || !targetAmount) {
      setError("Name and target amount are required.");
      return;
    }

    const goal: Goal = {
      name: name.trim(),
      category,
      targetAmount: Number(targetAmount),
      targetDate: targetDate || undefined,
      savedAmount: savedAmount ? Number(savedAmount) : 0,
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
            Already saved (₹) <span className="font-normal text-slate-400">(optional)</span>
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
