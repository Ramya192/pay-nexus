import { useState, type ChangeEvent, type FormEvent } from "react";
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

export function ManualEntryForm({ onSaved }: { onSaved?: () => void }) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [isMetro, setIsMetro] = useState(true);
  const setPayslipData = usePayslipStore((s) => s.setPayslipData);

  function handleChange(key: string, value: string) {
    setValues((v) => ({ ...v, [key]: value }));
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const parsed: Record<string, number | string | boolean> = { isMetro };
    for (const field of FIELDS) {
      const raw = values[field.key];
      if (raw === undefined || raw === "") continue;
      parsed[field.key] = field.type === "number" ? Number(raw) : raw;
    }
    // Session-only for now — persisting it (POST /payslip/save) is a
    // separate step that encrypts first, via crypto/clientEncryption.ts.
    setPayslipData(parsed);
    onSaved?.();
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
              className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
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
      <button
        type="submit"
        className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
      >
        Use this payslip
      </button>
      <p className="text-xs text-slate-400">
        Kept in this session only until you choose to save it — saving encrypts it in your
        browser first (AES-256-GCM), so the server only ever stores ciphertext.
      </p>
    </form>
  );
}
