import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { deleteStatement, updateStatement, type ParsedTransaction } from "../../api/statement";
import { encryptJSON } from "../../crypto/clientEncryption";
import { useAuthStore } from "../../store/authStore";
import { useTransactionStore, type StatementEntry } from "../../store/transactionStore";
import { TRANSACTION_CATEGORIES } from "../../utils/categories";

/**
 * Lists every saved statement with a way to delete one, and — expanding a
 * row — a way to actually see and correct its transactions. Before this,
 * a saved statement only showed as one summary line (account, period,
 * transaction count): no way to check what got saved, or fix a category
 * rules.py/the LLM fallback got wrong (StatementUploader.tsx's own
 * docstring flagged per-row correction as a fast-follow, not built for the
 * initial MVP — this is that fast-follow).
 *
 * A correction re-encrypts and PUTs the WHOLE transaction list back
 * (api/statement.ts's updateStatement) rather than patching one row
 * server-side — there's no per-transaction row to patch, only one
 * ciphertext blob per statement, same reasoning POST /save already works
 * this way.
 */
export function StatementList() {
  const entries = useTransactionStore((s) => s.entries);
  const removeEntries = useTransactionStore((s) => s.removeEntries);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (entries.length === 0) {
    return <p className="text-xs text-slate-400">No bank statements saved yet.</p>;
  }

  const sorted = [...entries].sort((a, b) => a.periodLabel.localeCompare(b.periodLabel));

  async function handleDelete(entry: StatementEntry) {
    if (
      !window.confirm(
        `Remove the saved statement for ${entry.sourceAccount}, ${entry.periodLabel}? This can't be undone.`
      )
    ) {
      return;
    }
    setError(null);
    setBusyId(entry.id);
    try {
      await deleteStatement(entry.id);
      removeEntries([entry.id]);
      if (expandedId === entry.id) setExpandedId(null);
    } catch {
      setError("Couldn't delete that statement — try again.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-2">
      <ul className="max-h-72 space-y-1 overflow-y-auto text-xs">
        {sorted.map((entry) => (
          <li key={entry.id} className="rounded px-1 py-1 text-slate-600 hover:bg-slate-50">
            <div className="flex items-center justify-between gap-2">
              <button
                type="button"
                onClick={() => setExpandedId(expandedId === entry.id ? null : entry.id)}
                className="flex min-w-0 flex-1 items-center gap-1 truncate text-left"
                title="View transactions"
              >
                {expandedId === entry.id ? (
                  <ChevronDown className="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden="true" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden="true" />
                )}
                <span className="truncate">
                  {entry.sourceAccount} — {entry.periodLabel}
                  <span className="ml-1 text-slate-400">({entry.transactions.length} transactions)</span>
                </span>
              </button>
              <button
                type="button"
                onClick={() => handleDelete(entry)}
                disabled={busyId === entry.id}
                className="shrink-0 text-slate-400 hover:text-red-600 disabled:opacity-50"
                title="Delete this saved statement"
              >
                Delete
              </button>
            </div>
            {expandedId === entry.id && <TransactionDetail entry={entry} />}
          </li>
        ))}
      </ul>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}

function TransactionDetail({ entry }: { entry: StatementEntry }) {
  const aesKey = useAuthStore((s) => s.aesKey);
  const updateEntryTransactions = useTransactionStore((s) => s.updateEntryTransactions);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const sorted = [...entry.transactions].sort((a, b) => a.date.localeCompare(b.date));

  async function handleCategoryChange(transactionId: string, category: string) {
    if (!aesKey) return;
    const nextTransactions: ParsedTransaction[] = entry.transactions.map((t) =>
      t.transaction_id === transactionId ? { ...t, category, category_source: "user_corrected" } : t
    );
    setError(null);
    setSavingId(transactionId);
    try {
      const blob = await encryptJSON(aesKey, nextTransactions);
      await updateStatement(entry.id, blob);
      updateEntryTransactions(entry.id, nextTransactions);
    } catch {
      setError("Couldn't save that correction — try again.");
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div className="mt-1.5 space-y-1 border-t border-slate-100 pt-1.5">
      <ul className="max-h-64 space-y-1 overflow-y-auto pr-1">
        {sorted.map((t) => (
          <li key={t.transaction_id} className="flex items-center justify-between gap-2 py-0.5">
            <span className="min-w-0 flex-1 truncate text-slate-600">
              {t.date} · {t.description}
            </span>
            <span className="flex shrink-0 items-center gap-1.5">
              <select
                value={t.category ?? "Uncategorized"}
                onChange={(e) => handleCategoryChange(t.transaction_id, e.target.value)}
                disabled={savingId === t.transaction_id}
                title={
                  t.category_source === "user_corrected"
                    ? "Corrected by you"
                    : t.category_source === "rule"
                      ? "Matched by a keyword rule"
                      : t.category_source === "llm"
                        ? "Categorized by AI — check it if it looks off"
                        : undefined
                }
                className={`rounded border px-1 py-0.5 text-[10px] disabled:opacity-50 ${
                  t.category_source === "user_corrected"
                    ? "border-brand-300 bg-brand-50 text-brand-700"
                    : "border-slate-200 bg-slate-100 text-slate-500"
                }`}
              >
                {TRANSACTION_CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
              <span className={`w-20 shrink-0 text-right ${t.amount < 0 ? "text-slate-700" : "text-emerald-600"}`}>
                {t.amount < 0 ? "-" : "+"}₹{Math.abs(t.amount).toLocaleString("en-IN")}
              </span>
            </span>
          </li>
        ))}
      </ul>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}
