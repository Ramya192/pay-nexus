import { apiClient } from "./client";
import type { EncryptedBlob } from "../crypto/clientEncryption";

export interface BudgetRow {
  ciphertext_b64: string;
  iv_b64: string;
  updated_at: string;
}

/** Persists a budget — upserts in place (one row per user). */
export async function saveBudget(blob: EncryptedBlob): Promise<void> {
  await apiClient.put("/budget", {
    ciphertext_b64: blob.ciphertextB64,
    iv_b64: blob.ivB64,
  });
}

/**
 * Still ciphertext at this point — decrypt with crypto/clientEncryption.ts.
 * Returns null for a fresh account with no budget saved yet (404), rather
 * than throwing — same "expected state, not an error" handling as
 * api/financialProfile.ts's fetchFinancialProfile.
 */
export async function fetchBudget(): Promise<BudgetRow | null> {
  try {
    const { data } = await apiClient.get<BudgetRow>("/budget");
    return data;
  } catch (err: unknown) {
    const status = (err as { response?: { status?: number } })?.response?.status;
    if (status === 404) return null;
    throw err;
  }
}

export interface SuggestedBudget {
  salary_bracket: string;
  budgets: Record<string, number>;
}

/** Plaintext, no user data involved — pre-fills BudgetForm.tsx on first
 * visit. `monthlyIncome` is a rough figure the caller derives from
 * whatever payslip data is already in payslipStore, nothing new fetched
 * just for this. */
export async function fetchSuggestedBudget(monthlyIncome?: number): Promise<SuggestedBudget> {
  const { data } = await apiClient.get<SuggestedBudget>("/budget/suggested", {
    params: monthlyIncome ? { monthly_income: monthlyIncome } : {},
  });
  return data;
}
