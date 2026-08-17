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
