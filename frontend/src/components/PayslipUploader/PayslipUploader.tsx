import { ManualEntryForm } from "./ManualEntryForm";

/**
 * Wraps the payslip entry paths. A client-side PDFParser (§10 — extracting
 * a PDF payslip into the same structured JSON, in the browser) isn't built
 * yet; manual entry is the only way to get payslip_data into a session
 * right now.
 */
export function PayslipUploader() {
  return (
    <div className="space-y-3">
      <ManualEntryForm />
    </div>
  );
}
