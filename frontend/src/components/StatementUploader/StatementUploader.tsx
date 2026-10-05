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
import { TRANSACTION_CATEGORIES } from "../../utils/categories";
import { computeContentHash } from "../../utils/contentHash";
import { PdfPasswordError } from "../../utils/pdfPasswordError";
import { extractPdfText } from "../../utils/pdfText";
import { PdfPasswordPrompt } from "../PdfPasswordPrompt";

type Status = "idle" | "reading" | "parsing" | "review" | "saving" | "saved" | "error";

/**
 * Upload a bank/credit-card statement (PDF or CSV), review the parsed and
 * categorized transactions, then explicitly save. Same two-step shape as
 * PDFParser.tsx (extract → review → separate "use/save" action) rather than
 * PayslipHistoryUpload.tsx's save-without-review bulk path — a statement's
 * transactions actually drive SpendingAnalyser's answers directly (like the
 * active payslip does for Payslip Reasoning), not archived record for
 * trend-spotting alone, so it gets the same in-the-moment scrutiny.
 *
 * The file itself never reaches the server for either format: PDF text is
 * extracted entirely in the browser (utils/pdfText.ts, pdfjs-dist) and only
 * that text is sent to POST /statement/parse; CSV text is just the file's
 * own contents read directly (already plain text, no extraction needed).
 *
 * Per-row category correction (accepting the categorizer got one wrong) is
 * not built here for V2 MVP — matches backend/categorization/categorize.py's
 * own note that the online-learning classifier is a fast-follow, not a
 * blocker; a wrong category can still be seen and reasoned about via chat
 * even without an edit control here yet.
 */
export function StatementUploader() {
  const aesKey = useAuthStore((s) => s.aesKey);
  const addEntry = useTransactionStore((s) => s.addEntry);

  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [sourceAccount, setSourceAccount] = useState("");
  const [periodLabel, setPeriodLabel] = useState("");
  const [parsed, setParsed] = useState<ParsedTransaction[] | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  // Set while an encrypted PDF is waiting for its password.
  const [passwordPending, setPasswordPending] = useState<{ file: File; incorrect: boolean } | null>(null);

  function handleFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // clear so re-selecting the same file re-fires onChange
    if (!file) return;
    setPasswordPending(null);
    void processFile(file);
  }

  async function processFile(file: File, password?: string) {
    if (!sourceAccount.trim()) {
      setError("Name the account first (e.g. \"HDFC Checking\") so this statement can be told apart from others.");
      return;
    }

    setError(null);
    setParsed(null);
    setWarnings([]);
    setPasswordPending(null);
    setStatus("reading");
    try {
      const format = file.name.toLowerCase().endsWith(".csv") ? "csv" : "pdf";
      const text = format === "pdf" ? await extractPdfText(file, password) : await file.text();
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
      if (err instanceof PdfPasswordError) {
        setStatus("idle");
        setPasswordPending({ file, incorrect: err.incorrect });
        return;
      }
      setStatus("error");
      setError(err instanceof Error ? err.message : "Couldn't read that statement.");
    }
  }

  async function handleSave() {
    if (!parsed || !aesKey) return;
    if (!periodLabel.trim()) {
      setError("Give this statement a period label (e.g. \"2026-07\") before saving.");
      return;
    }

    setError(null);
    setStatus("saving");
    try {
      const [blob, contentHash] = await Promise.all([
        encryptJSON(aesKey, parsed),
        computeContentHash(parsed),
      ]);
      const saved = await saveStatement(sourceAccount.trim(), periodLabel.trim(), blob, contentHash);
      const entry: StatementEntry = {
        id: saved.id,
        sourceAccount: saved.source_account,
        periodLabel: saved.period_label,
        createdAt: saved.created_at,
        transactions: parsed,
      };
      addEntry(entry);
      setStatus("saved");
      setParsed(null);
    } catch (err) {
      setStatus("review");
      if (isDuplicateStatementError(err)) {
        setError(getErrorDetail(err) ?? `A statement for ${sourceAccount}, ${periodLabel} is already saved.`);
      } else {
        setError("Couldn't save that statement — try again.");
      }
    }
  }

  // Fix a wrong/missing category before saving. Marked user_corrected so
  // future uploads learn from it (it feeds historical_labels).
  function handleRowCategory(transactionId: string, category: string) {
    setParsed((rows) =>
      rows
        ? rows.map((t) =>
            t.transaction_id === transactionId ? { ...t, category, category_source: "user_corrected" } : t
          )
        : rows
    );
  }

  const busy = status === "reading" || status === "parsing" || status === "saving";
  const uncategorizedCount =
    parsed?.filter((t) => (t.category ?? "Uncategorized") === "Uncategorized" || t.category_source === "default").length ?? 0;

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <label className="block text-xs font-medium text-slate-600" htmlFor="source-account">
          Account name
        </label>
        <input
          id="source-account"
          type="text"
          value={sourceAccount}
          onChange={(e) => setSourceAccount(e.target.value)}
          placeholder="e.g. HDFC Checking"
          disabled={busy}
          className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
        />
      </div>

      <div className="space-y-2 rounded-md border border-dashed border-slate-300 p-3">
        <label className="block text-xs font-medium text-slate-600" htmlFor="bank-statement-upload">
          Upload bank statement{" "}
          <span className="font-normal text-slate-400">
            (PDF or CSV — text is extracted in your browser; only that text, never the file,
            reaches the server)
          </span>
        </label>
        <input
          id="bank-statement-upload"
          type="file"
          accept="application/pdf,.csv,text/csv"
          onChange={handleFile}
          disabled={busy}
          className="block w-full text-xs text-slate-600 file:mr-2 file:cursor-pointer file:rounded file:border-0 file:bg-brand-50 file:px-2 file:py-1 file:text-xs file:font-medium file:text-brand-700 hover:file:bg-brand-100"
        />
        {status === "reading" && <p className="text-xs text-slate-500">Reading file…</p>}
        {status === "parsing" && <p className="text-xs text-slate-500">Extracting and categorizing transactions…</p>}
        {passwordPending && (
          <PdfPasswordPrompt
            fileName={passwordPending.file.name}
            incorrect={passwordPending.incorrect}
            disabled={busy}
            onSubmit={(pw) => void processFile(passwordPending.file, pw)}
            onCancel={() => setPasswordPending(null)}
          />
        )}
        {error && !parsed && <p className="text-xs text-red-600">{error}</p>}
      </div>

      {parsed && (
        <div className="space-y-2 rounded-md border border-slate-200 p-3">
          {warnings.map((w) => (
            <p key={w} className="text-xs text-amber-600">
              {w}
            </p>
          ))}
          <p className="text-xs text-slate-500">
            {parsed.length} transaction(s) found — review below, then save.
            {uncategorizedCount > 0 && ` ${uncategorizedCount} row(s) couldn't be matched and were filled in automatically (credits as Income, debits as Other, highlighted) — change any that are wrong.`}
          </p>
          <ul className="max-h-56 space-y-1 overflow-y-auto text-xs">
            {parsed.map((t) => (
              <li key={t.transaction_id} className="flex items-center justify-between gap-2 border-b border-slate-100 py-1">
                <span className="truncate text-slate-600">
                  {t.date} · {t.description}
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  <select
                    value={t.category ?? "Uncategorized"}
                    onChange={(e) => handleRowCategory(t.transaction_id, e.target.value)}
                    disabled={busy}
                    aria-label={`Category for ${t.description}`}
                    className={`rounded border px-1 py-0.5 text-[10px] ${
                      t.category_source === "user_corrected"
                        ? "border-brand-300 bg-brand-50 text-brand-700"
                        : (t.category ?? "Uncategorized") === "Uncategorized" || t.category_source === "default"
                          ? "border-amber-300 bg-amber-50 text-amber-700"
                          : "border-slate-200 bg-slate-100 text-slate-500"
                    }`}
                  >
                    {TRANSACTION_CATEGORIES.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                  <span className={t.amount < 0 ? "text-slate-700" : "text-emerald-600"}>
                    {t.amount < 0 ? "-" : "+"}₹{Math.abs(t.amount).toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                  </span>
                </span>
              </li>
            ))}
          </ul>
          <div className="flex items-end gap-2 pt-1">
            <div className="flex-1 space-y-1">
              <label className="block text-xs font-medium text-slate-600" htmlFor="period-label">
                Period label
              </label>
              <input
                id="period-label"
                type="text"
                value={periodLabel}
                onChange={(e) => setPeriodLabel(e.target.value)}
                disabled={busy}
                className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
              />
            </div>
            <button
              type="button"
              onClick={handleSave}
              disabled={busy}
              className="shrink-0 rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
            >
              {status === "saving" ? "Saving…" : "Save statement"}
            </button>
          </div>
          {/* A save failure (e.g. "already saved") is shown next to the Save button the user just
              clicked; up top it sat above the whole review list and was easy to miss. */}
          {error && (
            <p role="alert" className="text-xs text-red-600">
              {error}
            </p>
          )}
        </div>
      )}
      {status === "saved" && <p className="text-xs text-emerald-600">Statement saved.</p>}
    </div>
  );
}

/** "YYYY-MM" from the earliest transaction date, or a "YYYY-MM to YYYY-MM"
 * range if the statement spans more than one calendar month — just a
 * starting suggestion, the field above stays editable before Save. */
function defaultPeriodLabel(transactions: ParsedTransaction[]): string {
  const months = [...new Set(transactions.map((t) => t.date.slice(0, 7)))].sort();
  if (months.length === 0) return "";
  if (months.length === 1) return months[0];
  return `${months[0]} to ${months[months.length - 1]}`;
}
