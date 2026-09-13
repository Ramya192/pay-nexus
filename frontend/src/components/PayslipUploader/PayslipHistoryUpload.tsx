import { useState, type ChangeEvent } from "react";
import { isDuplicatePayslipError, parsePayslipText, savePayslip } from "../../api/payslip";
import { encryptJSON } from "../../crypto/clientEncryption";
import { useAuthStore } from "../../store/authStore";
import { usePayslipHistoryStore } from "../../store/payslipHistoryStore";
import { extractPdfText } from "../../utils/pdfText";

interface FileStatus {
  name: string;
  status: "pending" | "working" | "done" | "duplicate" | "error";
  detail?: string; // the extracted month on success/duplicate, an error message on failure
}

/**
 * Bulk upload for PAST payslips — unlike PDFParser.tsx (the current,
 * reviewed-before-use payslip), each file here is extracted and saved
 * straight to encrypted storage with no manual review step. Deliberate
 * trade-off: reviewing a year's worth of payslips one at a time would be
 * tedious, and none of these are driving today's chat answer the way the
 * current payslip is — they're archived record for computing real trends
 * (backend/payslip_trends.py), not something that needs in-the-moment
 * scrutiny. Files process one at a time (not in parallel) to keep the
 * per-file status list legible and avoid firing a burst of concurrent
 * OpenAI calls.
 */
export function PayslipHistoryUpload() {
  const aesKey = useAuthStore((s) => s.aesKey);
  const addEntry = usePayslipHistoryStore((s) => s.addEntry);
  const [files, setFiles] = useState<FileStatus[]>([]);

  async function handleFiles(e: ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (selected.length === 0 || !aesKey) return;

    setFiles(selected.map((f) => ({ name: f.name, status: "pending" })));

    for (let i = 0; i < selected.length; i++) {
      setFiles((prev) => prev.map((f, idx) => (idx === i ? { ...f, status: "working" } : f)));
      try {
        const text = await extractPdfText(selected[i]);
        if (!text.trim()) throw new Error("No extractable text (scanned image?)");

        const fields = await parsePayslipText(text);
        const month = typeof fields.month === "string" ? fields.month : null;
        if (!month) throw new Error("Couldn't determine the pay period — skipped");

        const blob = await encryptJSON(aesKey, fields);
        const saved = await savePayslip(month, blob);
        addEntry({ id: saved.id, createdAt: saved.created_at, data: fields });

        setFiles((prev) =>
          prev.map((f, idx) => (idx === i ? { ...f, status: "done", detail: month } : f))
        );
      } catch (err) {
        if (isDuplicatePayslipError(err)) {
          // A payslip for this month was already saved (from an earlier
          // upload, possibly this same batch run twice) — surfaced
          // distinctly rather than silently creating a second row for it.
          setFiles((prev) =>
            prev.map((f, idx) => (idx === i ? { ...f, status: "duplicate", detail: "already saved" } : f))
          );
          continue;
        }
        const detail = err instanceof Error ? err.message : "Failed to process";
        setFiles((prev) => prev.map((f, idx) => (idx === i ? { ...f, status: "error", detail } : f)));
      }
    }
  }

  return (
    <div className="space-y-2">
      <label className="block text-xs font-medium text-slate-600">
        Upload past payslips (PDF, select multiple)
      </label>
      <input
        type="file"
        accept="application/pdf"
        multiple
        onChange={handleFiles}
        className="block w-full text-xs text-slate-600 file:mr-2 file:cursor-pointer file:rounded file:border-0 file:bg-brand-50 file:px-2 file:py-1 file:text-xs file:font-medium file:text-brand-700 hover:file:bg-brand-100"
      />
      {files.length > 0 && (
        <ul className="space-y-1 text-xs">
          {files.map((f) => (
            <li key={f.name} className="flex items-center justify-between gap-2 text-slate-600">
              <span className="truncate">{f.name}</span>
              <span
                className={
                  f.status === "done"
                    ? "text-emerald-600"
                    : f.status === "duplicate"
                      ? "text-amber-600"
                      : f.status === "error"
                        ? "text-red-600"
                        : "text-slate-400"
                }
              >
                {f.status === "pending" && "queued"}
                {f.status === "working" && "processing…"}
                {f.status === "done" && `saved (${f.detail})`}
                {f.status === "duplicate" && "already saved — skipped"}
                {f.status === "error" && f.detail}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-slate-400">
        Each file is extracted and saved straight to encrypted storage — no review step, since
        these are archived record for spotting trends, not driving today's answer. Text is
        extracted in your browser; only that text, never the PDF, reaches the server.
      </p>
    </div>
  );
}
