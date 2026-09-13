import { useState } from "react";
import { deleteSnapshot } from "../../api/payslip";
import { usePayslipHistoryStore, type SnapshotEntry } from "../../store/payslipHistoryStore";

/**
 * Lists every saved payslip month with a way to actually manage them —
 * delete one entry, or clean up duplicates in bulk. Didn't exist before:
 * the only saved-history UI was the upload widget, with no way to see or
 * remove what had already been saved. Found missing when a user
 * bulk-uploaded the same 12 files twice (24 rows, no warning) and then
 * asked chat to "remove duplicates" — no agent can write to storage (see
 * backend/agents/orchestrator.py's capability_gap_node), so this panel is
 * where that has to actually happen.
 */
export function PayslipHistoryList() {
  const entries = usePayslipHistoryStore((s) => s.entries);
  const removeEntries = usePayslipHistoryStore((s) => s.removeEntries);
  const [busy, setBusy] = useState<"deleting" | "cleaning" | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (entries.length === 0) {
    return <p className="text-xs text-slate-400">No payslips saved to history yet.</p>;
  }

  const byMonth = groupByMonth(entries);
  const duplicateCount = entries.length - byMonth.size;
  const sortedMonths = [...byMonth.keys()].sort();

  async function handleDelete(entry: SnapshotEntry) {
    if (!window.confirm(`Remove the saved payslip for ${monthLabel(entry.data)}? This can't be undone.`)) {
      return;
    }
    setError(null);
    setBusy("deleting");
    try {
      await deleteSnapshot(entry.id);
      removeEntries([entry.id]);
    } catch {
      setError("Couldn't delete that entry — try again.");
    } finally {
      setBusy(null);
    }
  }

  async function handleRemoveDuplicates() {
    const idsToRemove: string[] = [];
    for (const group of byMonth.values()) {
      if (group.length <= 1) continue;
      // Keep the most recently saved one, delete the rest.
      const [, ...older] = [...group].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
      idsToRemove.push(...older.map((e) => e.id));
    }
    if (idsToRemove.length === 0) return;
    if (!window.confirm(`Remove ${idsToRemove.length} duplicate payslip(s), keeping the most recently saved for each month?`)) {
      return;
    }
    setError(null);
    setBusy("cleaning");
    try {
      for (const id of idsToRemove) {
        await deleteSnapshot(id);
      }
      removeEntries(idsToRemove);
    } catch {
      setError("Couldn't remove all duplicates — some may still be there. Try again.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-2">
      {duplicateCount > 0 && (
        <div className="flex items-center justify-between gap-2 rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs text-amber-700">
          <span>
            {duplicateCount} duplicate {duplicateCount === 1 ? "entry" : "entries"} found.
          </span>
          <button
            type="button"
            onClick={handleRemoveDuplicates}
            disabled={busy !== null}
            className="shrink-0 rounded border border-amber-300 bg-white px-2 py-1 font-medium text-amber-700 hover:bg-amber-100 disabled:opacity-50"
          >
            {busy === "cleaning" ? "Removing…" : "Remove duplicates"}
          </button>
        </div>
      )}
      <ul className="max-h-48 space-y-1 overflow-y-auto text-xs">
        {sortedMonths.map((month) =>
          byMonth.get(month)!.map((entry, idx) => (
            <li
              key={entry.id}
              className="flex items-center justify-between gap-2 rounded px-1 py-1 text-slate-600 hover:bg-slate-50"
            >
              <span className="truncate">
                {month}
                {byMonth.get(month)!.length > 1 && (
                  <span className="ml-1 rounded bg-amber-100 px-1 text-[10px] font-medium text-amber-700">
                    duplicate {idx + 1}/{byMonth.get(month)!.length}
                  </span>
                )}
              </span>
              <button
                type="button"
                onClick={() => handleDelete(entry)}
                disabled={busy !== null}
                className="shrink-0 text-slate-400 hover:text-red-600 disabled:opacity-50"
                title="Delete this saved payslip"
              >
                Delete
              </button>
            </li>
          ))
        )}
      </ul>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}

function groupByMonth(entries: SnapshotEntry[]): Map<string, SnapshotEntry[]> {
  const map = new Map<string, SnapshotEntry[]>();
  for (const entry of entries) {
    const month = monthLabel(entry.data);
    const group = map.get(month) ?? [];
    group.push(entry);
    map.set(month, group);
  }
  return map;
}

function monthLabel(data: Record<string, unknown>): string {
  return typeof data.month === "string" && data.month ? data.month : "unknown month";
}
