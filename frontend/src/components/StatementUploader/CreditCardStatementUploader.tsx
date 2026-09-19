import { useState, type ChangeEvent } from "react";
import {
  getErrorDetail,
  isDuplicateStatementError,
  parseStatementText,
  saveStatement,
  type ParsedTransaction,
} from "../../api/statement";
import { encryptJSON } from "../../crypto/clientEncryption";
import { useAuthStore } from "../../store/authStore";
import { useTransactionStore, type StatementEntry } from "../../store/transactionStore";
import { computeContentHash } from "../../utils/contentHash";
import { extractPdfText } from "../../utils/pdfText";

type Status = "idle" | "reading" | "parsing" | "review" | "saving" | "saved" | "payment-failed" | "error";

/**
 * Credit-card-specific variant of StatementUploader.tsx — same file→parse→
 * review flow, plus a required "Payment due date" that drives a second,
 * synthetic transaction on save. Two independent facts get saved as two
 * separate statement entries (see backend/analytics/spending_trends.py's
 * module docstring for the full reasoning):
 *
 * 1. The itemized purchases, under the billing-cycle period label, each
 *    stamped `counts_toward_net_savings: false` — they still drive
 *    SpendingAnalyser/BudgetPlanner (that's genuinely when you spent), but
 *    must NOT also register as a cash-flow event in that period; the real
 *    money doesn't leave the bank until the statement is paid.
 * 2. One synthetic "Credit Card Bill Payment" transaction, dated at the
 *    due date, `counts_toward_category_spend: false` (it's not a new
 *    purchase, just the same rupees already counted above) — this is what
 *    correctly debits the DUE DATE's calendar month for net-savings/goal-
 *    pace purposes. Built directly here rather than via
 *    /statement/categorize-manual — there's no real categorization
 *    question for a payment record, so no need for that round trip.
 *
 * Two separate POST /statement/save calls, not one entry with two periods —
 * StatementEntry can only carry one periodLabel, stamped uniformly onto
 * every transaction inside it (transactionStore.ts's flatten()). The
 * payment entry's distinct source_account suffix ("— Bill Payment") also
 * means it can never collide with the itemized entry's dedup key
 * (source_account, period_label), and reads clearly in StatementList.tsx
 * with zero changes needed there.
 *
 * Confirmed simplification (user's explicit call): the card is always paid
 * in FULL, so the payment amount is exactly the itemized total — no
 * separate "amount actually paid" field, no partial/EMI handling.
 */
export function CreditCardStatementUploader() {
  const aesKey = useAuthStore((s) => s.aesKey);
  const addEntry = useTransactionStore((s) => s.addEntry);

  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [sourceAccount, setSourceAccount] = useState("");
  const [periodLabel, setPeriodLabel] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [parsed, setParsed] = useState<ParsedTransaction[] | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  // Set once the itemized entry has saved but the payment entry hasn't yet
  // (or failed) — lets "Retry payment record" re-attempt ONLY that second
  // save, since the itemized entry is already persisted and re-saving it
  // would just 409 against itself.
  const [pendingPayment, setPendingPayment] = useState<{ sourceAccount: string; itemizedTotal: number } | null>(null);

  async function handleFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!sourceAccount.trim()) {
      setError('Name the card first (e.g. "HDFC Credit Card") so this statement can be told apart from others.');
      return;
    }

    setError(null);
    setParsed(null);
    setWarnings([]);
    setPendingPayment(null);
    setStatus("reading");
    try {
      const format = file.name.toLowerCase().endsWith(".csv") ? "csv" : "pdf";
      const text = format === "pdf" ? await extractPdfText(file) : await file.text();
      if (!text.trim()) {
        throw new Error(
          format === "pdf"
            ? "Couldn't find any text in that PDF — it may be a scanned image."
            : "That CSV file appears to be empty."
        );
      }

      setStatus("parsing");
      const result = await parseStatementText(text, sourceAccount.trim(), format);
      if (result.transactions.length === 0) {
        throw new Error("No transactions could be read from that file.");
      }

      const newWarnings: string[] = [];
      if (result.skipped_row_count > 0) {
        newWarnings.push(
          `${result.skipped_row_count} row(s) couldn't be read (missing date, description, or amount) and were skipped.`
        );
      }
      if (result.truncated_chars > 0) {
        newWarnings.push(
          "This statement was long enough that only part of it could be parsed — some transactions near the end may be missing."
        );
      }
      setWarnings(newWarnings);
      setParsed(result.transactions);
      setPeriodLabel(defaultPeriodLabel(result.transactions));
      setStatus("review");
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "Couldn't read that statement.");
    }
  }

  /** Sum of the itemized transactions' own signed amounts — already
   * negative for a normal, all-expense statement, so this IS the exact
   * bank debit at payment time (no extra sign flip needed): if you charged
   * ₹5,000 total, the itemized rows sum to -5000, and paying that bill in
   * full is also a -5000 event. A refund/credit row already nets correctly
   * the same way. */
  function itemizedTotal(transactions: ParsedTransaction[]): number {
    return transactions.reduce((sum, t) => sum + t.amount, 0);
  }

  async function saveItemizedEntry(): Promise<void> {
    if (!parsed || !aesKey) return;
    const flagged: ParsedTransaction[] = parsed.map((t) => ({ ...t, counts_toward_net_savings: false }));
    const [blob, contentHash] = await Promise.all([encryptJSON(aesKey, flagged), computeContentHash(flagged)]);
    const saved = await saveStatement(sourceAccount.trim(), periodLabel.trim(), blob, contentHash);
    const entry: StatementEntry = {
      id: saved.id,
      sourceAccount: saved.source_account,
      periodLabel: saved.period_label,
      createdAt: saved.created_at,
      transactions: flagged,
    };
    addEntry(entry);
  }

  async function savePaymentEntry(cardAccount: string, total: number): Promise<void> {
    if (!aesKey) return;
    const paymentAccount = `${cardAccount} — Bill Payment`;
    const paymentTxn: ParsedTransaction = {
      transaction_id: crypto.randomUUID(),
      date: dueDate,
      description: "Credit Card Bill Payment",
      amount: total,
      source_account: paymentAccount,
      category: "Credit Card Payment",
      category_source: null,
      counts_toward_category_spend: false,
    };
    const transactions = [paymentTxn];
    const [blob, contentHash] = await Promise.all([
      encryptJSON(aesKey, transactions),
      computeContentHash(transactions),
    ]);
    const saved = await saveStatement(paymentAccount, dueDate.slice(0, 7), blob, contentHash);
    addEntry({
      id: saved.id,
      sourceAccount: saved.source_account,
      periodLabel: saved.period_label,
      createdAt: saved.created_at,
      transactions,
    });
  }

  async function handleSave() {
    if (!parsed || !aesKey) return;
    if (!periodLabel.trim()) {
      setError('Give this statement a billing-cycle period label (e.g. "16 Mar 2026 to 14 Apr 2026") before saving.');
      return;
    }
    if (!dueDate) {
      setError("Enter the payment due date before saving — it's what makes this statement debit the right month.");
      return;
    }

    setError(null);
    setStatus("saving");
    try {
      await saveItemizedEntry();
    } catch (err) {
      setStatus("review");
      if (isDuplicateStatementError(err)) {
        setError(getErrorDetail(err) ?? `A statement for ${sourceAccount}, ${periodLabel} is already saved.`);
      } else {
        setError("Couldn't save the itemized statement — try again.");
      }
      return;
    }

    // Itemized entry is now genuinely persisted — from here, ANY failure
    // must NOT re-attempt saveItemizedEntry() (it would 409 against the
    // row we just created). Only the payment record can still be retried.
    const total = itemizedTotal(parsed);
    try {
      await savePaymentEntry(sourceAccount.trim(), total);
      setStatus("saved");
      setParsed(null);
    } catch {
      setStatus("payment-failed");
      setPendingPayment({ sourceAccount: sourceAccount.trim(), itemizedTotal: total });
      // Clear the review panel now too, same as the success path already
      // does -- otherwise it stayed rendered alongside the new retry panel
      // below, with its own still-clickable "Save statement" button that
      // would re-attempt saving the itemized entry a second time (already
      // persisted at this point, so at best a confusing 409).
      setParsed(null);
      setError(
        "Purchases saved, but the payment record failed to save — your net-savings figures won't reflect this " +
          "bill yet until you retry."
      );
    }
  }

  async function handleRetryPayment() {
    if (!pendingPayment) return;
    setStatus("saving");
    setError(null);
    try {
      await savePaymentEntry(pendingPayment.sourceAccount, pendingPayment.itemizedTotal);
      setStatus("saved");
      setParsed(null);
      setPendingPayment(null);
    } catch {
      setStatus("payment-failed");
      setError("Still couldn't save the payment record — try again.");
    }
  }

  const busy = status === "reading" || status === "parsing" || status === "saving";

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <label className="block text-xs font-medium text-slate-600" htmlFor="cc-source-account">
          Card name
        </label>
        <input
          id="cc-source-account"
          type="text"
          value={sourceAccount}
          onChange={(e) => setSourceAccount(e.target.value)}
          placeholder="e.g. HDFC Credit Card"
          disabled={busy || !!pendingPayment}
          className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
        />
      </div>

      {!pendingPayment && (
        <div className="space-y-2 rounded-md border border-dashed border-slate-300 p-3">
          <label className="block text-xs font-medium text-slate-600" htmlFor="cc-statement-upload">
            Upload credit card statement{" "}
            <span className="font-normal text-slate-400">
              (PDF or CSV — text is extracted in your browser; only that text, never the file,
              reaches the server)
            </span>
          </label>
          <input
            id="cc-statement-upload"
            type="file"
            accept="application/pdf,.csv,text/csv"
            onChange={handleFile}
            disabled={busy}
            className="block w-full text-xs text-slate-600 file:mr-2 file:cursor-pointer file:rounded file:border-0 file:bg-brand-50 file:px-2 file:py-1 file:text-xs file:font-medium file:text-brand-700 hover:file:bg-brand-100"
          />
          {status === "reading" && <p className="text-xs text-slate-500">Reading file…</p>}
          {status === "parsing" && <p className="text-xs text-slate-500">Extracting and categorizing transactions…</p>}
          {error && <p className="text-xs text-red-600">{error}</p>}
        </div>
      )}

      {parsed && (
        <div className="space-y-2 rounded-md border border-slate-200 p-3">
          {warnings.map((w) => (
            <p key={w} className="text-xs text-amber-600">
              {w}
            </p>
          ))}
          <p className="text-xs text-slate-500">
            {parsed.length} transaction(s) found — review below, then save.
          </p>
          <ul className="max-h-56 space-y-1 overflow-y-auto text-xs">
            {parsed.map((t) => (
              <li key={t.transaction_id} className="flex items-center justify-between gap-2 border-b border-slate-100 py-1">
                <span className="truncate text-slate-600">
                  {t.date} · {t.description}
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">
                    {t.category ?? "Uncategorized"}
                  </span>
                  <span className={t.amount < 0 ? "text-slate-700" : "text-emerald-600"}>
                    {t.amount < 0 ? "-" : "+"}₹{Math.abs(t.amount).toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                  </span>
                </span>
              </li>
            ))}
          </ul>
          <div className="grid grid-cols-2 gap-2 pt-1">
            <div className="space-y-1">
              <label className="block text-xs font-medium text-slate-600" htmlFor="cc-period-label">
                Billing cycle
              </label>
              <input
                id="cc-period-label"
                type="text"
                value={periodLabel}
                onChange={(e) => setPeriodLabel(e.target.value)}
                disabled={busy}
                className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
              />
            </div>
            <div className="space-y-1">
              <label className="block text-xs font-medium text-slate-600" htmlFor="cc-due-date">
                Payment due date
              </label>
              <input
                id="cc-due-date"
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                disabled={busy}
                className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
              />
            </div>
          </div>
          <p className="text-xs text-slate-400">
            The due date's own month is what your net-savings/goal-pace figures will reflect — the
            billing cycle above only controls how these purchases group for spending-by-category.
          </p>
          <button
            type="button"
            onClick={handleSave}
            disabled={busy}
            className="w-full rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {status === "saving" ? "Saving…" : "Save statement"}
          </button>
        </div>
      )}

      {pendingPayment && (
        <div className="space-y-2 rounded-md border border-amber-200 bg-amber-50 p-3">
          <p className="text-xs text-amber-700">
            Purchases are saved. The bill-payment record (due {dueDate}, ₹
            {Math.abs(pendingPayment.itemizedTotal).toLocaleString("en-IN", { maximumFractionDigits: 0 })}) hasn't saved yet —
            your net-savings figures won't include this bill until it does.
          </p>
          <button
            type="button"
            onClick={handleRetryPayment}
            disabled={status === "saving"}
            className="rounded-md bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
          >
            {status === "saving" ? "Retrying…" : "Retry payment record"}
          </button>
          {/* A retry failure sets `error` while pendingPayment is still set
              -- this is the only place that error can actually be seen; the
              old bottom-of-page fallback below required `!pendingPayment`,
              which a retry failure never satisfies, so it silently never
              rendered here even though `error` was genuinely set. */}
          {error && <p className="text-xs text-red-600">{error}</p>}
        </div>
      )}

      {status === "saved" && <p className="text-xs text-emerald-600">Statement and payment record both saved.</p>}
    </div>
  );
}

/** Same suggestion logic as StatementUploader.tsx's defaultPeriodLabel —
 * a starting point, stays editable before Save. */
function defaultPeriodLabel(transactions: ParsedTransaction[]): string {
  const months = [...new Set(transactions.map((t) => t.date.slice(0, 7)))].sort();
  if (months.length === 0) return "";
  if (months.length === 1) return months[0];
  return `${months[0]} to ${months[months.length - 1]}`;
}
