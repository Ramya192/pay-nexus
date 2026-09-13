import { Check } from "lucide-react";
import { useState, type ChangeEvent, type FormEvent } from "react";
import { isDuplicatePayslipError, savePayslip } from "../../api/payslip";
import { encryptJSON } from "../../crypto/clientEncryption";
import { useAuthStore } from "../../store/authStore";
import { usePayslipHistoryStore } from "../../store/payslipHistoryStore";
import { usePayslipStore } from "../../store/payslipStore";

interface FieldDef {
  key: string;
  label: string;
  type: "month" | "number";
}

const FIELDS: FieldDef[] = [
  { key: "month", label: "Month", type: "month" },
  { key: "basic", label: "Basic (₹)", type: "number" },
  { key: "hra", label: "HRA received (₹)", type: "number" },
  { key: "specialAllowance", label: "Special Allowance (₹)", type: "number" },
  { key: "pfEmployee", label: "PF — employee (₹)", type: "number" },
  { key: "pfEmployer", label: "PF — employer (₹)", type: "number" },
  { key: "professionalTax", label: "Professional Tax (₹)", type: "number" },
  { key: "tds", label: "TDS (₹)", type: "number" },
  { key: "bonus", label: "Bonus this month (₹)", type: "number" },
  { key: "rentPaid", label: "Monthly rent paid (₹)", type: "number" },
];

export function ManualEntryForm({
  onSaved,
  initialValues,
  initialIsMetro,
}: {
  onSaved?: () => void;
  /** Pre-fill from PDFParser's extraction — still just a starting point, every field stays editable. */
  initialValues?: Record<string, string>;
  initialIsMetro?: boolean;
}) {
  const [values, setValues] = useState<Record<string, string>>(initialValues ?? {});
  const [isMetro, setIsMetro] = useState(initialIsMetro ?? true);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "duplicate" | "error">("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  // Mirrors saveStatus's pattern — was missing entirely before, so
  // clicking "Use this payslip" gave no feedback at all and users
  // (reasonably) clicked it several times unsure whether it had done
  // anything. Resets to idle on any field edit, same as saveStatus does,
  // since a stale "Using this payslip" checkmark would be actively misleading once the form no
  // longer matches what's actually driving chat answers.
  const [useStatus, setUseStatus] = useState<"idle" | "used">("idle");
  const setPayslipData = usePayslipStore((s) => s.setPayslipData);
  const addEntry = usePayslipHistoryStore((s) => s.addEntry);
  const aesKey = useAuthStore((s) => s.aesKey);

  function handleChange(key: string, value: string) {
    setValues((v) => ({ ...v, [key]: value }));
    setSaveStatus("idle");
    setUseStatus("idle");
  }

  function buildPayslipData(): Record<string, number | string | boolean> {
    const parsed: Record<string, number | string | boolean> = { isMetro };
    for (const field of FIELDS) {
      const raw = values[field.key];
      if (raw === undefined || raw === "") continue;
      parsed[field.key] = field.type === "number" ? Number(raw) : raw;
    }
    return parsed;
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    // Session-only — sets the payslip actively driving today's chat
    // answers. Persisting it to history is the separate action below.
    setPayslipData(buildPayslipData());
    setUseStatus("used");
    onSaved?.();
  }

  async function handleSaveToHistory() {
    if (!aesKey) return;
    const payslipData = buildPayslipData();
    const month = typeof payslipData.month === "string" ? payslipData.month : "";
    if (!month) {
      setSaveStatus("error");
      setSaveError("Enter a month before saving to history.");
      return;
    }

    setSaveStatus("saving");
    setSaveError(null);
    try {
      const blob = await encryptJSON(aesKey, payslipData);
      const saved = await savePayslip(month, blob);
      addEntry({ id: saved.id, createdAt: saved.created_at, data: payslipData });
      setSaveStatus("saved");
    } catch (err) {
      if (isDuplicatePayslipError(err)) {
        // Not really an error — the same month is already saved. Surfacing
        // this distinctly (rather than a red "failed to save") is the fix
        // for uploads silently creating duplicate rows with no signal.
        setSaveStatus("duplicate");
        return;
      }
      setSaveStatus("error");
      setSaveError(err instanceof Error ? err.message : "Couldn't save to history.");
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        {FIELDS.map((field) => (
          <div key={field.key} className="space-y-1">
            <label className="text-xs font-medium text-slate-600">{field.label}</label>
            <input
              type={field.type}
              value={values[field.key] ?? ""}
              onChange={(e: ChangeEvent<HTMLInputElement>) => handleChange(field.key, e.target.value)}
              className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
          </div>
        ))}
      </div>
      <label className="flex items-center gap-2 text-sm text-slate-600">
        <input
          type="checkbox"
          checked={isMetro}
          onChange={(e: ChangeEvent<HTMLInputElement>) => setIsMetro(e.target.checked)}
        />
        Metro city (affects HRA exemption %)
      </label>
      <div className="flex gap-2">
        <button
          type="submit"
          className="flex items-center gap-1.5 rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
        >
          {useStatus === "used" && <Check className="h-3.5 w-3.5" aria-hidden="true" />}
          {useStatus === "used" ? "Using this payslip" : "Use this payslip"}
        </button>
        <button
          type="button"
          onClick={handleSaveToHistory}
          disabled={saveStatus === "saving"}
          className="flex items-center gap-1.5 rounded-md border border-brand-200 px-4 py-2 text-sm font-medium text-brand-700 hover:bg-brand-50 disabled:opacity-50"
        >
          {saveStatus === "saved" && <Check className="h-3.5 w-3.5" aria-hidden="true" />}
          {saveStatus === "saving"
            ? "Saving…"
            : saveStatus === "saved"
              ? "Saved to history"
              : saveStatus === "duplicate"
                ? "Already saved"
                : "Save to history"}
        </button>
      </div>
      {saveStatus === "duplicate" && (
        <p className="text-xs text-amber-600">
          A payslip for this month is already saved — delete it from Payslip history first if you
          want to replace it.
        </p>
      )}
      {saveError && <p className="text-xs text-red-600">{saveError}</p>}
      <p className="text-xs text-slate-400">
        "Use this payslip" is session-only and drives today's chat answers. "Save to history"
        persists it (encrypted, AES-256-GCM — the server only ever stores ciphertext) so the
        Savings Advisor can compute real trends across months later.
      </p>
    </form>
  );
}
