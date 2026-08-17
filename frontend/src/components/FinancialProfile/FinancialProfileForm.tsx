import { Check } from "lucide-react";
import { useEffect, useState, type ChangeEvent, type FormEvent } from "react";
import { saveFinancialProfile } from "../../api/financialProfile";
import { encryptJSON } from "../../crypto/clientEncryption";
import { useAuthStore } from "../../store/authStore";
import { useFinancialProfileStore, type FinancialProfile } from "../../store/financialProfileStore";

interface FieldDef {
  key: keyof FinancialProfile;
  label: string;
  hint: string;
}

interface Section {
  title: string;
  fields: FieldDef[];
}

const SECTIONS: Section[] = [
  {
    title: "Investments",
    fields: [
      { key: "elssMutualFunds", label: "ELSS mutual funds (₹/yr)", hint: "80C" },
      { key: "ppf", label: "PPF contribution (₹/yr)", hint: "80C" },
      { key: "otherMutualFunds", label: "Other mutual funds (₹)", hint: "not a deduction" },
      { key: "stocks", label: "Stocks (₹)", hint: "not a deduction" },
    ],
  },
  {
    title: "Deposits",
    fields: [
      { key: "fdPrincipal", label: "Fixed deposits — principal (₹)", hint: "not a deduction" },
      { key: "fdInterestEarned", label: "Fixed deposits — interest earned (₹/yr)", hint: "taxable income" },
      { key: "rdPrincipal", label: "Recurring deposits — principal (₹)", hint: "not a deduction" },
      { key: "rdInterestEarned", label: "Recurring deposits — interest earned (₹/yr)", hint: "taxable income" },
    ],
  },
  {
    title: "Home loan",
    fields: [
      { key: "homeLoanPrincipalPaid", label: "Principal repaid (₹/yr)", hint: "80C" },
      { key: "homeLoanInterestPaid", label: "Interest paid (₹/yr)", hint: "24(b), separate from 80C" },
    ],
  },
  {
    title: "Insurance",
    fields: [
      { key: "lifeInsurancePremium", label: "Life insurance premium (₹/yr)", hint: "80C" },
      { key: "healthInsurancePremium", label: "Health insurance premium (₹/yr)", hint: "80D" },
    ],
  },
];

type FormValues = Partial<Record<keyof FinancialProfile, string>>;

export function FinancialProfileForm() {
  const aesKey = useAuthStore((s) => s.aesKey);
  const storedProfile = useFinancialProfileStore((s) => s.profile);
  const setStoreProfile = useFinancialProfileStore((s) => s.setProfile);

  const [values, setValues] = useState<FormValues>({});
  const [seniorCitizen, setSeniorCitizen] = useState(false);
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  // storedProfile is populated asynchronously (fetched + decrypted on
  // login, after this component has likely already mounted) — sync
  // whenever it lands, not just at mount.
  useEffect(() => {
    if (!storedProfile) return;
    const next: FormValues = {};
    for (const section of SECTIONS) {
      for (const field of section.fields) {
        const v = storedProfile[field.key];
        if (typeof v === "number") next[field.key] = String(v);
      }
    }
    setValues(next);
    setSeniorCitizen(Boolean(storedProfile.healthInsuranceForSeniorCitizen));
  }, [storedProfile]);

  function handleChange(key: keyof FinancialProfile, value: string) {
    setValues((v) => ({ ...v, [key]: value }));
    setStatus("idle");
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!aesKey) return;

    const profile: FinancialProfile = { healthInsuranceForSeniorCitizen: seniorCitizen };
    for (const section of SECTIONS) {
      for (const field of section.fields) {
        const raw = values[field.key];
        if (raw === undefined || raw === "") continue;
        (profile[field.key] as number) = Number(raw);
      }
    }

    setStatus("saving");
    setError(null);
    try {
      setStoreProfile(profile);
      const blob = await encryptJSON(aesKey, profile);
      await saveFinancialProfile(blob);
      setStatus("saved");
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "Couldn't save your financial profile.");
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {SECTIONS.map((section) => (
        <div key={section.title} className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            {section.title}
          </h3>
          {section.fields.map((field) => (
            <div key={field.key} className="space-y-1">
              <label className="flex items-baseline justify-between text-xs font-medium text-slate-600">
                <span>{field.label}</span>
                <span className="font-normal text-slate-400">{field.hint}</span>
              </label>
              <input
                type="number"
                min="0"
                value={values[field.key] ?? ""}
                onChange={(e: ChangeEvent<HTMLInputElement>) => handleChange(field.key, e.target.value)}
                className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
              />
            </div>
          ))}
        </div>
      ))}

      <label className="flex items-center gap-2 text-xs text-slate-600">
        <input
          type="checkbox"
          checked={seniorCitizen}
          onChange={(e: ChangeEvent<HTMLInputElement>) => setSeniorCitizen(e.target.checked)}
        />
        Health insurance covers a senior citizen (raises the 80D cap to ₹50,000)
      </label>

      <button
        type="submit"
        disabled={status === "saving"}
        className="flex w-full items-center justify-center gap-1.5 rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
      >
        {status === "saved" && <Check className="h-3.5 w-3.5" aria-hidden="true" />}
        {status === "saving" ? "Saving…" : status === "saved" ? "Saved" : "Save financial profile"}
      </button>
      {error && <p className="text-xs text-red-600">{error}</p>}
      <p className="text-xs text-slate-400">
        Encrypted in your browser before saving (AES-256-GCM) — the server only ever stores
        ciphertext. Personal loan EMIs aren't collected here since they're usually not
        tax-deductible; home loan interest is the one that is (Section 24(b)).
      </p>
    </form>
  );
}
