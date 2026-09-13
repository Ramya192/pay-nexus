import { Check } from "lucide-react";
import { useState, type ChangeEvent, type FormEvent } from "react";
import { categorizeManualTransaction, saveStatement, updateStatement, type ParsedTransaction } from "../../api/statement";
import { encryptJSON } from "../../crypto/clientEncryption";
import { useAuthStore } from "../../store/authStore";
import { useTransactionStore, type StatementEntry } from "../../store/transactionStore";
import { computeContentHash } from "../../utils/contentHash";
import { TRANSACTION_CATEGORIES } from "../../utils/categories";

/**
 * A single hand-entered cash expense — the "I paid with cash, there's no
 * statement to upload" gap StatementUploader.tsx can't cover on its own.
 * Deliberately no session-only/save split like PayslipUploader/
 * ManualEntryForm.tsx has: a manual transaction only means anything once
 * persisted, since /chat's `transactions` come entirely from
 * useTransactionStore's persisted, flattened set — there's no session-only
 * staging area for a single expense the way there is for an active payslip.
 *
 * Reuses the existing save/update routes as-is (no new persistence route):
 * appends to this month's "Cash" statement if one's already saved, via the
 * same PUT /statement/{id} the category-correction flow already uses;
 * creates a new one via the existing POST /statement/save otherwise.
 */
export function ManualExpenseEntry() {
  const [date, setDate] = useState("");
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState("");
  const [sourceAccount, setSourceAccount] = useState("Cash");
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  const aesKey = useAuthStore((s) => s.aesKey);
  const entries = useTransactionStore((s) => s.entries);
  const addEntry = useTransactionStore((s) => s.addEntry);
  const updateEntryTransactions = useTransactionStore((s) => s.updateEntryTransactions);

  function resetForm() {
    setDate("");
    setDescription("");
    setAmount("");
    setCategory("");
  }

  function handleFieldChange<T>(setter: (v: T) => void) {
    return (value: T) => {
      setter(value);
      setStatus("idle");
      setError(null);
    };
  }

  /** 0-based count of prior rows in `existing` sharing this row's other
   * four fields — mirrors backend/ingestion/normalize.py's seen_counts
   * dedup exactly, just applied against an already-saved list instead of
   * within one parse batch (see api/statement.ts's categorizeManualTransaction
   * docstring for why a wrong value here silently collides transaction_ids). */
  function computeOccurrence(existing: ParsedTransaction[], txnDate: string, desc: string, amt: number, account: string): number {
    const key = `${txnDate}|${desc.trim().toLowerCase()}|${amt.toFixed(2)}|${account}`;
    return existing.filter(
      (t) => `${t.date}|${t.description.trim().toLowerCase()}|${t.amount.toFixed(2)}|${t.source_account}` === key
    ).length;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!aesKey) return;
    if (!date || !description.trim() || !amount) {
      setStatus("error");
      setError("Date, description, and amount are all required.");
      return;
    }

    setStatus("saving");
    setError(null);
    try {
      const signedAmount = -Math.abs(Number(amount)); // manual entry is always an expense — always money out
      const periodLabel = date.slice(0, 7);
      const existingEntry = entries.find(
        (e: StatementEntry) => e.sourceAccount === sourceAccount && e.periodLabel === periodLabel
      );
      const occurrence = existingEntry
        ? computeOccurrence(existingEntry.transactions, date, description, signedAmount, sourceAccount)
        : 0;

      const newTxn = await categorizeManualTransaction(
        date,
        description.trim(),
        signedAmount,
        sourceAccount,
        category || undefined,
        occurrence
      );

      if (existingEntry) {
        const updatedTransactions = [...existingEntry.transactions, newTxn];
        const blob = await encryptJSON(aesKey, updatedTransactions);
        await updateStatement(existingEntry.id, blob);
        updateEntryTransactions(existingEntry.id, updatedTransactions);
      } else {
        const transactions = [newTxn];
        const [blob, contentHash] = await Promise.all([
          encryptJSON(aesKey, transactions),
          computeContentHash(transactions),
        ]);
        const saved = await saveStatement(sourceAccount, periodLabel, blob, contentHash);
        addEntry({ id: saved.id, sourceAccount, periodLabel, createdAt: saved.created_at, transactions });
      }

      setStatus("saved");
      resetForm();
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "Couldn't save this expense.");
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <label className="text-xs font-medium text-slate-600">Date</label>
          <input
            type="date"
            value={date}
            onChange={(e: ChangeEvent<HTMLInputElement>) => handleFieldChange(setDate)(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium text-slate-600">Amount (₹)</label>
          <input
            type="number"
            min="0"
            step="0.01"
            value={amount}
            onChange={(e: ChangeEvent<HTMLInputElement>) => handleFieldChange(setAmount)(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
        <div className="col-span-2 space-y-1">
          <label className="text-xs font-medium text-slate-600">Description</label>
          <input
            type="text"
            value={description}
            onChange={(e: ChangeEvent<HTMLInputElement>) => handleFieldChange(setDescription)(e.target.value)}
            placeholder="e.g. Vegetable market"
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium text-slate-600">Category</label>
          <select
            value={category}
            onChange={(e: ChangeEvent<HTMLSelectElement>) => handleFieldChange(setCategory)(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          >
            <option value="">Auto-categorize</option>
            {TRANSACTION_CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium text-slate-600">Account</label>
          <input
            type="text"
            value={sourceAccount}
            onChange={(e: ChangeEvent<HTMLInputElement>) => handleFieldChange(setSourceAccount)(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
      </div>
      <button
        type="submit"
        disabled={status === "saving"}
        className="flex items-center gap-1.5 rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
      >
        {status === "saved" && <Check className="h-3.5 w-3.5" aria-hidden="true" />}
        {status === "saving" ? "Adding…" : status === "saved" ? "Added" : "Add expense"}
      </button>
      {error && <p className="text-xs text-red-600">{error}</p>}
      <p className="text-xs text-slate-400">
        Cash purchases don't appear on any bank statement — add them here so SpendingAnalyser and
        your budgets actually see them. Encrypted (AES-256-GCM) before it ever leaves your browser,
        same as an uploaded statement.
      </p>
    </form>
  );
}
