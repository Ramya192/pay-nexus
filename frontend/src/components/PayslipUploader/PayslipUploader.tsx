import { useState } from "react";
import { ManualEntryForm } from "./ManualEntryForm";
import { PDFParser } from "./PDFParser";

/**
 * Two paths into one form, per §10's component tree: upload a PDF to
 * pre-fill ManualEntryForm, or just type values in directly — either way,
 * every field stays editable and nothing submits until "Use this payslip."
 * Extraction is best-effort (an LLM reading arbitrary payslip layouts), so
 * upload is deliberately never treated as a replacement for review.
 */
export function PayslipUploader() {
  const [prefill, setPrefill] = useState<{ values: Record<string, string>; isMetro: boolean } | null>(
    null
  );
  // Bumped on every successful extraction so ManualEntryForm remounts with
  // the new initialValues — simpler than lifting its form state up here,
  // and the form has no state worth preserving across a re-prefill anyway.
  const [formKey, setFormKey] = useState(0);

  function handleExtracted(fields: Record<string, unknown>) {
    const values: Record<string, string> = {};
    for (const [key, value] of Object.entries(fields)) {
      if (key === "isMetro" || value === null || value === undefined) continue;
      values[key] = String(value);
    }
    const isMetro = typeof fields.isMetro === "boolean" ? fields.isMetro : true;
    setPrefill({ values, isMetro });
    setFormKey((k) => k + 1);
  }

  return (
    <div className="space-y-3">
      <PDFParser onExtracted={handleExtracted} />
      <div className="flex items-center gap-2 text-xs text-slate-400">
        <div className="h-px flex-1 bg-slate-200" />
        or enter manually
        <div className="h-px flex-1 bg-slate-200" />
      </div>
      <ManualEntryForm
        key={formKey}
        initialValues={prefill?.values}
        initialIsMetro={prefill?.isMetro}
      />
    </div>
  );
}
