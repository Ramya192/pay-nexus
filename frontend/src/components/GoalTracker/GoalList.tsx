import { useState } from "react";
import { deleteGoal, updateGoal } from "../../api/goals";
import { encryptJSON } from "../../crypto/clientEncryption";
import { useAuthStore } from "../../store/authStore";
import { useGoalStore, type GoalEntry } from "../../store/goalStore";

export function GoalList() {
  const entries = useGoalStore((s) => s.entries);

  if (entries.length === 0) {
    return <p className="text-xs text-slate-400">No financial goals added yet.</p>;
  }

  return (
    <ul className="space-y-2">
      {entries.map((entry) => (
        <GoalCard key={entry.id} entry={entry} />
      ))}
    </ul>
  );
}

function GoalCard({ entry }: { entry: GoalEntry }) {
  const aesKey = useAuthStore((s) => s.aesKey);
  const updateEntry = useGoalStore((s) => s.updateEntry);
  const removeEntry = useGoalStore((s) => s.removeEntry);

  const [editing, setEditing] = useState(false);
  const [savedInput, setSavedInput] = useState(String(entry.data.savedAmount));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { name, category, targetAmount, targetDate, savedAmount } = entry.data;
  const pct = targetAmount > 0 ? Math.min(100, Math.round((savedAmount / targetAmount) * 100)) : 0;

  async function handleSaveProgress() {
    if (!aesKey) return;
    const nextSaved = Number(savedInput);
    if (Number.isNaN(nextSaved) || nextSaved < 0) {
      setError("Enter a valid amount.");
      return;
    }
    const nextData = { ...entry.data, savedAmount: nextSaved };
    setBusy(true);
    setError(null);
    try {
      const blob = await encryptJSON(aesKey, nextData);
      await updateGoal(entry.id, blob);
      updateEntry(entry.id, nextData);
      setEditing(false);
    } catch {
      setError("Couldn't save progress — try again.");
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    if (!window.confirm(`Remove the goal "${name}"? This can't be undone.`)) return;
    setBusy(true);
    setError(null);
    try {
      await deleteGoal(entry.id);
      removeEntry(entry.id);
    } catch {
      setError("Couldn't delete that goal — try again.");
      setBusy(false);
    }
  }

  return (
    <li className="space-y-2 rounded-md border border-slate-200 p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-slate-800">{name}</p>
          <p className="text-xs text-slate-400">
            {category}
            {targetDate && <> · target {targetDate}</>}
          </p>
        </div>
        <button
          type="button"
          onClick={handleDelete}
          disabled={busy}
          className="shrink-0 text-xs text-slate-400 hover:text-red-600 disabled:opacity-50"
        >
          Delete
        </button>
      </div>

      <div className="space-y-1">
        <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
          <div
            className="h-full rounded-full bg-brand-600 transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
        <p className="text-xs text-slate-500">
          ₹{savedAmount.toLocaleString("en-IN")} of ₹{targetAmount.toLocaleString("en-IN")} ({pct}%)
        </p>
      </div>

      {editing ? (
        <div className="flex items-center gap-2">
          <input
            type="number"
            min="0"
            value={savedInput}
            onChange={(e) => setSavedInput(e.target.value)}
            className="w-28 rounded-md border border-slate-300 px-2 py-1 text-xs focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
          <button
            type="button"
            onClick={handleSaveProgress}
            disabled={busy}
            className="rounded-md bg-brand-600 px-2 py-1 text-xs font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {busy ? "Saving…" : "Save"}
          </button>
          <button
            type="button"
            onClick={() => {
              setEditing(false);
              setSavedInput(String(savedAmount));
              setError(null);
            }}
            className="text-xs text-slate-400 hover:text-slate-600"
          >
            Cancel
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="text-xs text-brand-600 hover:underline"
        >
          Update progress
        </button>
      )}
      {error && <p className="text-xs text-red-600">{error}</p>}
    </li>
  );
}
