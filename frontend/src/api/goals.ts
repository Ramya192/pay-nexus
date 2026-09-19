import { apiClient } from "./client";
import type { EncryptedBlob } from "../crypto/clientEncryption";

export interface GoalSaveResult {
  id: string;
  created_at: string;
}

/** Persists a new goal — ciphertext in, receipt out. No duplicate check:
 * unlike payslip/statement saves, there's no plaintext field the server
 * could dedup on (see backend/db/models.py's Goal docstring), so every
 * call here just creates a new row. */
export async function createGoal(blob: EncryptedBlob): Promise<GoalSaveResult> {
  const { data } = await apiClient.post<GoalSaveResult>("/goals", {
    ciphertext_b64: blob.ciphertextB64,
    iv_b64: blob.ivB64,
  });
  return data;
}

/** Full replace of an existing goal (e.g. after editing savedAmount) —
 * re-encrypt the whole object client-side and send it here. */
export async function updateGoal(id: string, blob: EncryptedBlob): Promise<GoalSaveResult> {
  const { data } = await apiClient.put<GoalSaveResult>(`/goals/${id}`, {
    ciphertext_b64: blob.ciphertextB64,
    iv_b64: blob.ivB64,
  });
  return data;
}

export async function deleteGoal(id: string): Promise<void> {
  await apiClient.delete(`/goals/${id}`);
}

export interface GoalRow {
  id: string;
  ciphertext_b64: string;
  iv_b64: string;
  created_at: string;
}

/** Still ciphertext at this point — decrypt with crypto/clientEncryption.ts before use. */
export async function fetchGoals(): Promise<GoalRow[]> {
  const { data } = await apiClient.get<GoalRow[]>("/goals");
  return data;
}

export interface GoalValuationEntry {
  goal_id: string;
  instrument_type: "fd" | "mutual_fund";
  fd_principal?: number;
  fd_annual_rate?: number;
  fd_start_date?: string;
  mf_scheme_code?: string;
  mf_units_held?: number;
}

export interface GoalValuationResult {
  goal_id: string;
  current_value: number | null;
  error: string | null;
}

/**
 * Live current-value lookup for FD/mutual-fund-linked goals
 * (backend/analytics/investment_valuation.py) — stateless, nothing
 * persisted, same contract as parseStatementText. Called once per Goals
 * tab load (GoalList.tsx), not on every render — an FD's value barely
 * moves minute to minute and a mutual fund's NAV updates once a day, so
 * there's no real value in polling more often than "the tab was opened."
 */
export async function fetchGoalValuations(
  entries: GoalValuationEntry[]
): Promise<GoalValuationResult[]> {
  if (entries.length === 0) return [];
  const { data } = await apiClient.post<GoalValuationResult[]>("/goals/valuation", entries);
  return data;
}
