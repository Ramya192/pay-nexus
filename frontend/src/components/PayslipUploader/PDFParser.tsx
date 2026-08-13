import { useState, type ChangeEvent } from "react";
import { parsePayslipText } from "../../api/payslip";
import { extractPdfText } from "../../utils/pdfText";

type Status = "idle" | "reading" | "parsing" | "error";

/**
 * The upload half of the two payslip-entry paths (§10's PDFParser +
 * ManualEntryForm). Text is extracted from the PDF entirely in the browser
 * — the file itself never reaches the server, only the extracted text does
 * (POST /payslip/parse) — and the result only *pre-fills* ManualEntryForm
 * via `onExtracted`; nothing here submits a payslip on its own, so upload
 * and manual entry stay two ways into the same editable form rather than
 * upload replacing manual entry.
 *
 * For uploading several *past* months at once instead of just the current
 * one, see PayslipHistoryUpload.tsx — that one saves straight to encrypted
 * storage without this review step, since archived history doesn't need
 * the same in-the-moment scrutiny as the payslip actively driving today's
 * chat.
 */
export function PDFParser({
  onExtracted,
}: {
  onExtracted: (fields: Record<string, unknown>) => void;
}) {
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);

  async function handleFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // clear so re-selecting the same file re-fires onChange
    if (!file) return;

    setError(null);
    setStatus("reading");
    try {
      const text = await extractPdfText(file);
      if (!text.trim()) {
        throw new Error(
          "Couldn't find any text in that PDF — it may be a scanned image. Try entering details manually instead."
        );
      }

      setStatus("parsing");
      const fields = await parsePayslipText(text);
      onExtracted(fields);
      setStatus("idle");
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "Couldn't read that PDF.");
    }
  }

  return (
    <div className="space-y-2 rounded-md border border-dashed border-slate-300 p-3">
      <label className="block text-xs font-medium text-slate-600">
        Upload payslip PDF{" "}
        <span className="font-normal text-slate-400">
          (optional — text is extracted in your browser; only that text, never the file, reaches
          the server)
        </span>
      </label>
      <input
        type="file"
        accept="application/pdf"
        onChange={handleFile}
        disabled={status === "reading" || status === "parsing"}
        className="block w-full text-xs text-slate-600 file:mr-2 file:cursor-pointer file:rounded file:border-0 file:bg-brand-50 file:px-2 file:py-1 file:text-xs file:font-medium file:text-brand-700 hover:file:bg-brand-100"
      />
      {status === "reading" && <p className="text-xs text-slate-500">Reading PDF…</p>}
      {status === "parsing" && <p className="text-xs text-slate-500">Extracting fields…</p>}
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}
