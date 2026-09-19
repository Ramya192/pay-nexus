import { useEffect, useState } from "react";
import { deleteGoal, fetchGoalValuations, updateGoal, type GoalValuationEntry } from "../../api/goals";
import { encryptJSON } from "../../crypto/clientEncryption";
import { useAuthStore } from "../../store/authStore";
import { useGoalStore, type GoalEntry } from "../../store/goalStore";

export function GoalList() {
  const entries = useGoalStore((s) => s.entries);
  const setLiveValue = useGoalStore((s) => s.setLiveValue);
  const [valuationErrors, setValuationErrors] = useState<Record<string, string>>({});

  // One fetch whenever the goal list changes (not on every render, not
  // polled) — an FD's value barely moves minute to minute and a mutual
  // fund's NAV updates once a day, so "the tab was opened" is a fine
  // refresh cadence. See api/goals.ts's fetchGoalValuations docstring.
  useEffect(() => {
    const linked = entries.filter((e) => e.data.instrumentType);
    if (linked.length === 0) return;
    const requests: GoalValuationEntry[] = linked.map((e) =>
      e.data.instrumentType === "fd"
        ? {
            goal_id: e.id,
            instrument_type: "fd",
            fd_principal: e.data.fdPrincipal,
            fd_annual_rate: e.data.fdAnnualRate,
            fd_start_date: e.data.fdStartDate,
          }
        : {
            goal_id: e.id,
            instrument_type: "mutual_fund",
            mf_scheme_code: e.data.mfSchemeCode,
            mf_units_held: e.data.mfUnitsHeld,
          }
    );
    fetchGoalValuations(requests)
      .then((results) => {
        const errors: Record<string, string> = {};
        for (const r of results) {
          if (r.current_value !== null) {
            setLiveValue(r.goal_id, r.current_value);
          } else if (r.error) {
            errors[r.goal_id] = r.error;
          }
        }
        setValuationErrors(errors);
      })
      .catch(() => {
        // A total request failure (e.g. offline) — leave whatever value
        // was last known (starting value, or a previous successful fetch)
        // displayed rather than blanking it out over a transient error.
      });
    // Only re-fetch when the SET of linked goals/their instrument details
    // changes, not on every store update (e.g. a manual goal's progress
    // edit shouldn't re-trigger a network call for unrelated FD/MF goals).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(entries.map((e) => [e.id, e.data.instrumentType, e.data.fdPrincipal, e.data.fdAnnualRate, e.data.fdStartDate, e.data.mfSchemeCode, e.data.mfUnitsHeld]))]);

  if (entries.length === 0) {
    return <p className="text-xs text-slate-400">No financial goals added yet.</p>;
  }

  return (
    <ul className="space-y-2">
      {entries.map((entry) => (
        <GoalCard key={entry.id} entry={entry} valuationError={valuationErrors[entry.id]} />
      ))}
    </ul>
  );
}

function GoalCard({ entry, valuationError }: { entry: GoalEntry; valuationError?: string }) {
  const aesKey = useAuthStore((s) => s.aesKey);
  const updateEntry = useGoalStore((s) => s.updateEntry);
  const removeEntry = useGoalStore((s) => s.removeEntry);
  // The store's `goals` array already has the live value merged in (see
  // goalStore.ts's flatten()) — but entry.data itself is the raw saved
  // record, so read the live-adjusted display value from there directly
  // via the same store, keyed by this entry's id.
  const liveValue = useGoalStore((s) => s.liveValues[entry.id]);

  const [editing, setEditing] = useState(false);
  const [savedInput, setSavedInput] = useState(String(entry.data.savedAmount));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { name, category, targetAmount, targetDate, instrumentType } = entry.data;
  const isInstrumentLinked = Boolean(instrumentType);
  const savedAmount = liveValue ?? entry.data.savedAmount;
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
          {isInstrumentLinked && liveValue !== undefined && (
            <span className="ml-1 text-brand-600">
              · live {instrumentType === "fd" ? "FD value" : "NAV value"}
            </span>
          )}
        </p>
        {valuationError && (
          <p className="text-xs text-amber-600">
            Couldn't fetch a live value: {valuationError} Showing the last known figure instead.
          </p>
        )}
      </div>

      {isInstrumentLinked ? (
        <p className="text-xs text-slate-400">
          Value tracked automatically ({instrumentType === "fd" ? "fixed deposit" : "mutual fund"}) —
          edit the goal's principal/rate or scheme code/units by deleting and re-adding it.
        </p>
      ) : editing ? (
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
